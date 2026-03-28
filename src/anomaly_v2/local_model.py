from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


# ==================== 模型常量定义 ====================
LOCAL_MODEL_NAME = "seal_v4"  # 局部模型名称：密封检测 v4 版本
LOCAL_MODEL_VERSION = "seal_v4-online.3"  # 模型版本号：在线学习第 3 版
RESAMPLE_RULE = "10min"  # 重采样规则：10 分钟间隔


# ==================== 数学工具函数 ====================

def _trapz_compat(y: np.ndarray, dx: float = 1.0) -> float:
    """
    梯形积分兼容函数
    
    适配不同 NumPy 版本的梯形积分 API：
    - NumPy 1.24+ 使用 np.trapezoid
    - 旧版本使用 np.trapz
    
    Args:
        y: 待积分的数组
        dx: 采样间隔（默认 1.0）
    
    Returns:
        积分结果（浮点数）
    """
    trapezoid = getattr(np, "trapezoid", None)
    if callable(trapezoid):
        return float(trapezoid(y, dx=dx))
    return float(np.trapz(y, dx=dx))


# ==================== 湿度物理量计算 ====================

def calc_absolute_humidity(temp_c: pd.Series, rh: pd.Series) -> pd.Series:
    """
    计算绝对湿度（Absolute Humidity, AH）
    
    基于温度（℃）和相对湿度（%）计算空气中的水汽含量（g/m³）
    公式来源：气象学标准计算
    
    Args:
        temp_c: 温度序列（摄氏度）
        rh: 相对湿度序列（百分比 0-100）
    
    Returns:
        绝对湿度序列（单位：g/m³）
    """
    # 饱和水汽压（SVP）：Magnus 公式
    svp = 6.112 * np.exp((17.67 * temp_c) / (temp_c + 243.5))
    # 实际水汽压（AVP）
    avp = svp * rh / 100.0
    # 绝对湿度：理想气体状态方程推导
    return 2.1674 * avp / (273.15 + temp_c) * 100.0


def calc_dew_point_c(temp_c: pd.Series, rh_pct: pd.Series) -> pd.Series:
    """
    计算露点温度（Dew Point）
    
    基于 Magnus 公式的反函数，计算空气冷却至饱和时的温度
    
    Args:
        temp_c: 温度序列（摄氏度）
        rh_pct: 相对湿度序列（百分比 0-100）
    
    Returns:
        露点温度序列（摄氏度）
    """
    temp = pd.to_numeric(temp_c, errors="coerce")
    rh = pd.to_numeric(rh_pct, errors="coerce").clip(lower=1e-3, upper=100.0)
    a = 17.62  # Magnus 公式参数 a
    b = 243.12  # Magnus 公式参数 b
    gamma = np.log(rh / 100.0) + (a * temp / (b + temp))
    dew = (b * gamma) / (a - gamma)
    return pd.Series(dew, index=temp.index)


def calc_vpd_kpa(temp_c: pd.Series, rh_pct: pd.Series) -> pd.Series:
    """
    计算水汽压差（Vapor Pressure Deficit, VPD）
    
    VPD = 饱和水汽压 - 实际水汽压
    反映空气的"干燥程度"，影响水分蒸发速率
    
    Args:
        temp_c: 温度序列（摄氏度）
        rh_pct: 相对湿度序列（百分比 0-100）
    
    Returns:
        VPD 序列（单位：kPa）
    """
    temp = pd.to_numeric(temp_c, errors="coerce")
    rh = pd.to_numeric(rh_pct, errors="coerce").clip(lower=0.0, upper=100.0)
    # 饱和水汽压（Tetens 公式）
    sat = 0.6108 * np.exp((17.27 * temp) / (temp + 237.3))
    # 实际水汽压
    actual = sat * (rh / 100.0)
    return pd.Series(sat - actual, index=temp.index)


# ==================== 统计工具函数 ====================

def _safe_corr(a: pd.Series, b: pd.Series) -> float:
    """
    安全的相关系数计算
    
    处理缺失值和异常值，确保相关系数计算的稳定性
    
    Args:
        a: 序列 a
        b: 序列 b
    
    Returns:
        Pearson 相关系数（-1~1），若数据不足则返回 0.0
    """
    a_num = pd.to_numeric(a, errors="coerce")
    b_num = pd.to_numeric(b, errors="coerce")
    mask = a_num.notna() & b_num.notna()
    if int(mask.sum()) < 3:  # 至少需要 3 个有效数据点
        return 0.0
    value = a_num[mask].corr(b_num[mask])
    if pd.isna(value):
        return 0.0
    return float(value)


def _robust_z_positive(values: List[float], current: float) -> float:
    """
    鲁棒正态化 Z 分数
    
    基于中位数和中位数绝对偏差（MAD）计算 Z 分数
    只保留正值（用于检测异常增强）
    
    Args:
        values: 历史值列表
        current: 当前值
    
    Returns:
        正态化 Z 分数（≥0），若数据不足则返回 0.0
    """
    if len(values) < 3:
        return 0.0
    arr = np.asarray([float(v) for v in values if pd.notna(v)], dtype=float)
    if arr.size < 3:
        return 0.0
    median = float(np.median(arr))
    mad = float(np.median(np.abs(arr - median)))
    scale = max(mad * 1.4826, 1e-6)  # MAD 转换为标准差的系数
    return max(0.0, (float(current) - median) / scale)


def _clip01(value: float) -> float:
    """裁剪到 [0, 1] 区间"""
    return float(max(0.0, min(1.0, value)))


def _safe_gain_ratio(delta_response: float, delta_drive: float, min_abs_drive: float = 0.2) -> float:
    """
    安全的增益比率计算
    
    计算响应变化与驱动变化的比率（系统灵敏度指标）
    
    Args:
        delta_response: 响应变化量
        delta_drive: 驱动变化量
        min_abs_drive: 最小有效驱动变化阈值（避免除以接近零的数）
    
    Returns:
        增益比率，若驱动变化太小则返回 NaN
    """
    if pd.isna(delta_response) or pd.isna(delta_drive) or abs(float(delta_drive)) < min_abs_drive:
        return np.nan
    return float(delta_response / delta_drive)


def _safe_float(value: Any, default: float = np.nan) -> float:
    """安全类型转换：任意值转为浮点数"""
    try:
        if pd.isna(value):
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _clip_range(value: Any, low: float, high: float) -> float:
    """
    线性归一化到 [0, 1]
    
    将值映射到指定范围，超出范围则裁剪到边界
    
    Args:
        value: 待归一化的值
        low: 范围下限（对应输出 0）
        high: 范围上限（对应输出 1）
    
    Returns:
        归一化后的值（0~1）
    """
    numeric = _safe_float(value, np.nan)
    if pd.isna(numeric):
        return 0.0
    if high <= low:
        return 0.0
    return _clip01((numeric - low) / (high - low))


def _clip_inverse(value: Any, good: float, bad: float) -> float:
    """
    反向归一化到 [0, 1]
    
    越小越好的指标归一化（good 为最优值，bad 为最差值）
    
    Args:
        value: 待归一化的值
        good: 最优值（对应输出 1）
        bad: 最差值（对应输出 0）
    
    Returns:
        归一化后的值（0~1）
    """
    numeric = _safe_float(value, np.nan)
    if pd.isna(numeric):
        return 0.0
    if bad <= good:
        return 0.0
    return _clip01((bad - numeric) / (bad - good))


def _lagged_corr(x: pd.Series, y: pd.Series, max_lag: int = 6, min_pairs: int = 6) -> tuple[float, float]:
    """
    滞后相关性分析
    
    寻找两个序列在不同时间滞后下的最大相关性及对应的滞后步长
    用于检测系统的延迟响应特性
    
    Args:
        x: 驱动序列（如外部湿度）
        y: 响应序列（如内部湿度）
        max_lag: 最大滞后步数（默认 6）
        min_pairs: 最小有效数据点对数
    
    Returns:
        (最佳相关系数，最佳滞后步数)，若数据不足则返回 (NaN, NaN)
    """
    best_corr = -2.0
    best_lag = np.nan
    x_num = pd.to_numeric(x, errors="coerce")
    y_num = pd.to_numeric(y, errors="coerce")
    for lag in range(max_lag + 1):
        pair = pd.concat([x_num, y_num.shift(-lag)], axis=1).dropna()
        if len(pair) < min_pairs:
            continue
        corr_val = pair.iloc[:, 0].corr(pair.iloc[:, 1])
        if pd.notna(corr_val) and float(corr_val) > best_corr:
            best_corr = float(corr_val)
            best_lag = float(lag)
    return (best_corr if best_corr > -1.5 else np.nan, best_lag)


# ==================== 阶段特征提取 ====================

def _summarize_generic_phase(
    phase_df: pd.DataFrame,
    drive_col: str,
    response_col: str,
    response_change_col: str,
    min_drive_delta: float = 0.2,
) -> Dict[str, float]:
    """
    通用阶段特征摘要
    
    提取某个时间段内的驱动 - 响应关系特征
    
    Args:
        phase_df: 时间段数据框
        drive_col: 驱动变量列名
        response_col: 响应变量列名
        response_change_col: 响应变化量列名
        min_drive_delta: 最小有效驱动变化阈值
    
    Returns:
        特征字典：
        - delta_drive: 驱动总变化量
        - delta_response: 响应总变化量
        - gain_per_drive: 单位驱动变化的响应增益
        - respond_pos_ratio: 响应正向变化比例
    """
    if phase_df.empty:
        return {
            "delta_drive": np.nan,
            "delta_response": np.nan,
            "gain_per_drive": np.nan,
            "respond_pos_ratio": np.nan,
        }

    drive = pd.to_numeric(phase_df[drive_col], errors="coerce")
    response = pd.to_numeric(phase_df[response_col], errors="coerce")
    response_change = pd.to_numeric(phase_df[response_change_col], errors="coerce")
    delta_drive = float(drive.iloc[-1] - drive.iloc[0])
    delta_response = float(response.iloc[-1] - response.iloc[0])
    active = drive.diff() > 0
    return {
        "delta_drive": delta_drive,
        "delta_response": delta_response,
        "gain_per_drive": _safe_gain_ratio(delta_response, delta_drive, min_abs_drive=min_drive_delta),
        "respond_pos_ratio": float((response_change.loc[active] > 0).mean()) if active.any() else np.nan,
    }


def _ingress_regression(
    drive_series: pd.Series,
    response_delta_series: pd.Series,
    min_drive: float = 0.05,
    min_points: int = 4,
) -> Dict[str, float]:
    """
    侵入回归分析
    
    分析驱动变量对响应变化量的线性回归关系
    用于量化外部条件对内部状态的影响程度
    
    Args:
        drive_series: 驱动序列（如露点差）
        response_delta_series: 响应变化序列（如内部露点变化）
        min_drive: 最小有效驱动值
        min_points: 最小有效数据点数
    
    Returns:
        回归特征字典：
        - slope: 回归斜率（灵敏度）
        - r2: 决定系数（拟合优度）
        - count: 有效数据点数
        - pos_gain_per_area: 正向增益与驱动面积的比值
        - neg_response_ratio: 负响应比例（反向响应占比）
        - capture_ratio: 捕获比例（正向响应占比）
    """
    x = pd.to_numeric(drive_series, errors="coerce").shift(1)  # 驱动滞后 1 期
    y = pd.to_numeric(response_delta_series, errors="coerce")
    valid = x.notna() & y.notna() & (x > min_drive)
    if int(valid.sum()) < min_points:
        return {
            "slope": np.nan,
            "r2": np.nan,
            "count": float(valid.sum()),
            "pos_gain_per_area": np.nan,
            "neg_response_ratio": np.nan,
            "capture_ratio": np.nan,
        }

    x_valid = x.loc[valid].astype(float)
    y_valid = y.loc[valid].astype(float)
    slope, intercept = np.polyfit(x_valid, y_valid, 1)
    pred = slope * x_valid + intercept
    ss_res = float(((y_valid - pred) ** 2).sum())
    ss_tot = float(((y_valid - y_valid.mean()) ** 2).sum())
    r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 1e-9 else np.nan
    drive_area = float(x_valid.clip(lower=0.0).sum())
    return {
        "slope": float(slope),
        "r2": r2,
        "count": float(valid.sum()),
        "pos_gain_per_area": float(y_valid.clip(lower=0.0).sum() / max(drive_area, 1e-6)),
        "neg_response_ratio": float((y_valid < 0).mean()),
        "capture_ratio": float((y_valid > 0).mean()),
    }


# ==================== 数据预处理 ====================

def prepare_points_df(points: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    准备原始数据点 DataFrame
    
    将原始测量点转换为包含衍生变量的标准格式
    
    Args:
        points: 原始数据点列表，每个点包含：
            - ts: 毫秒时间戳
            - in_temp: 内部温度
            - out_temp: 外部温度
            - in_hum: 内部湿度
            - out_hum: 外部湿度
    
    Returns:
        预处理后的 DataFrame，新增列：
        - time: datetime 对象
        - AH_in/AH_out: 内外绝对湿度
        - dT: 内外温差
        - dAH: 内外绝对湿度差
        - headroom_ah: 外部相对内部的湿度余量
    """
    if not points:
        return pd.DataFrame()

    df = pd.DataFrame(points).copy()
    required = ["ts", "in_temp", "out_temp", "in_hum", "out_hum"]
    for col in required:
        if col not in df.columns:
            return pd.DataFrame()

    df["ts"] = pd.to_numeric(df["ts"], errors="coerce")
    for col in ["in_temp", "out_temp", "in_hum", "out_hum"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=required).sort_values("ts").reset_index(drop=True)
    if df.empty:
        return df

    df["time"] = pd.to_datetime(df["ts"], unit="ms", errors="coerce")
    df = df.dropna(subset=["time"]).copy()
    if df.empty:
        return df

    # 计算衍生变量
    df["AH_in"] = calc_absolute_humidity(df["in_temp"], df["in_hum"])
    df["AH_out"] = calc_absolute_humidity(df["out_temp"], df["out_hum"])
    df["dT"] = df["in_temp"] - df["out_temp"]
    df["dAH"] = df["AH_in"] - df["AH_out"]
    df["headroom_ah"] = df["AH_out"] - df["AH_in"]
    return df.reset_index(drop=True)


def resample_points_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    重采样到固定时间间隔
    
    将不规则采样的数据重采样为 10 分钟间隔，并计算更多衍生变量
    
    Args:
        df: 预处理后的 DataFrame（来自 prepare_points_df）
    
    Returns:
        重采样后的 DataFrame，新增列：
        - d_out_h/d_in_h: 内外湿度的一阶差分
        - d_ah_in: 内部绝对湿度差分
        - dew_in/dew_out: 内外露点温度
        - dew_gap: 内外露点差
        - d_dew_out/d_dew_in: 露点差分
        - vpd_in/vpd_out: 内外水汽压差
        - vpd_gap: 内外 VPD 差
    """
    if df.empty:
        return df

    # 重采样为 10 分钟均值并插值
    hourly = (
        df.set_index("time")[["ts", "in_temp", "out_temp", "in_hum", "out_hum", "AH_in", "AH_out", "dT", "dAH", "headroom_ah"]]
        .resample(RESAMPLE_RULE)
        .mean(numeric_only=True)
        .interpolate(limit_direction="both")
        .reset_index()
    )
    if hourly.empty:
        return hourly
    
    # 恢复时间戳
    hourly["ts"] = (hourly["time"].astype("int64") // 1_000_000).astype("int64")
    
    # 计算一阶差分和衍生变量
    hourly["d_out_h"] = pd.to_numeric(hourly["out_hum"], errors="coerce").diff()
    hourly["d_in_h"] = pd.to_numeric(hourly["in_hum"], errors="coerce").diff()
    hourly["d_ah_in"] = pd.to_numeric(hourly["AH_in"], errors="coerce").diff()
    hourly["dew_in"] = calc_dew_point_c(hourly["in_temp"], hourly["in_hum"])
    hourly["dew_out"] = calc_dew_point_c(hourly["out_temp"], hourly["out_hum"])
    hourly["dew_gap"] = pd.to_numeric(hourly["dew_out"], errors="coerce") - pd.to_numeric(hourly["dew_in"], errors="coerce")
    hourly["d_dew_out"] = pd.to_numeric(hourly["dew_out"], errors="coerce").diff()
    hourly["d_dew_in"] = pd.to_numeric(hourly["dew_in"], errors="coerce").diff()
    hourly["vpd_in"] = calc_vpd_kpa(hourly["in_temp"], hourly["in_hum"])
    hourly["vpd_out"] = calc_vpd_kpa(hourly["out_temp"], hourly["out_hum"])
    hourly["vpd_gap"] = pd.to_numeric(hourly["vpd_out"], errors="coerce") - pd.to_numeric(hourly["vpd_in"], errors="coerce")
    return hourly


def tail_hours(df: pd.DataFrame, hours: float) -> pd.DataFrame:
    """
    截取末尾 N 小时的数据
    
    Args:
        df: 时间序列 DataFrame
        hours: 时长（小时）
    
    Returns:
        末尾 N 小时的子集
    """
    if df.empty:
        return df
    end = df["time"].max()
    start = end - pd.Timedelta(hours=float(hours))
    out = df[df["time"] >= start].copy()
    if out.empty:
        return out
    return out.reset_index(drop=True)


# ==================== 阶段统计分析 ====================

def phase_stats(df: pd.DataFrame) -> Dict[str, float]:
    """
    阶段统计特征
    
    计算某个时间段内的综合统计特征，用于后续评分
    
    Args:
        df: 时间段数据框（已重采样）
    
    Returns:
        特征字典（20 个特征）：
        - 基础统计：points, duration_h, mean_out_hum, mean_out_ah, mean_dt
        - 变化量：delta_out_h, delta_in_h, delta_ah_in
        - 湿度余量：positive_headroom_ratio, headroom_area（积分）
        - 响应特性：respond_in_h_pos_ratio, respond_ah_pos_ratio
        - 增益指标：rh_gain_per_out, ah_decay_per_headroom
        - 极值与相关性：max_step_in_h, corr_out_in_h
    """
    if df.empty:
        return {
            "points": 0.0,
            "duration_h": 0.0,
            "mean_out_hum": np.nan,
            "mean_out_ah": np.nan,
            "mean_dt": np.nan,
            "delta_out_h": np.nan,
            "delta_in_h": np.nan,
            "delta_ah_in": np.nan,
            "positive_headroom_ratio": np.nan,
            "headroom_area": np.nan,
            "respond_in_h_pos_ratio": np.nan,
            "respond_ah_pos_ratio": np.nan,
            "rh_gain_per_out": np.nan,
            "ah_decay_per_headroom": np.nan,
            "max_step_in_h": np.nan,
            "corr_out_in_h": np.nan,
        }

    # 驱动标志：外部湿度增加的时刻
    drive = pd.to_numeric(df["d_out_h"], errors="coerce") > 0
    diffs = df["time"].diff().dt.total_seconds().dropna() / 3600.0
    dx_hours = float(diffs.median()) if not diffs.empty else (10.0 / 60.0)  # 采样间隔（小时）

    delta_out_h = float(df["out_hum"].iloc[-1] - df["out_hum"].iloc[0])
    delta_in_h = float(df["in_hum"].iloc[-1] - df["in_hum"].iloc[0])
    delta_ah_in = float(df["AH_in"].iloc[-1] - df["AH_in"].iloc[0])
    headroom = pd.to_numeric(df["headroom_ah"], errors="coerce").clip(lower=0.0)

    return {
        "points": float(len(df)),
        "duration_h": float((df["time"].iloc[-1] - df["time"].iloc[0]).total_seconds() / 3600.0),
        "mean_out_hum": float(pd.to_numeric(df["out_hum"], errors="coerce").mean()),
        "mean_out_ah": float(pd.to_numeric(df["AH_out"], errors="coerce").mean()),
        "mean_dt": float(pd.to_numeric(df["dT"], errors="coerce").mean()),
        "delta_out_h": delta_out_h,
        "delta_in_h": delta_in_h,
        "delta_ah_in": delta_ah_in,
        "positive_headroom_ratio": float((pd.to_numeric(df["headroom_ah"], errors="coerce") > 0).mean()),
        "headroom_area": _trapz_compat(headroom.to_numpy(dtype=float), dx=dx_hours),
        "respond_in_h_pos_ratio": float((df.loc[drive, "d_in_h"] > 0).mean()) if drive.any() else np.nan,
        "respond_ah_pos_ratio": float((df.loc[drive, "d_ah_in"] > 0).mean()) if drive.any() else np.nan,
        "rh_gain_per_out": float(delta_in_h / delta_out_h) if abs(delta_out_h) > 1e-6 else np.nan,
        "ah_decay_per_headroom": float(delta_ah_in / max(float(headroom.sum()) * dx_hours, 1e-6)),
        "max_step_in_h": float(pd.to_numeric(df["d_in_h"], errors="coerce").max()),
        "corr_out_in_h": _safe_corr(df["out_hum"], df["in_hum"]),
    }


def response_signal_score(stats: Dict[str, float]) -> float:
    """
    响应信号强度评分
    
    基于多特征加权计算密封响应的信号强度（0~1）
    
    Args:
        stats: phase_stats 输出的特征字典
    
    Returns:
        综合评分（0~1），越高表示响应信号越强
    """
    components = [
        0.28 * _clip01(float(stats.get("respond_in_h_pos_ratio", 0.0) or 0.0)),  # 内部湿度正向响应比例
        0.24 * _clip01(float(stats.get("positive_headroom_ratio", 0.0) or 0.0)),  # 湿度余量正向比例
        0.20 * _clip01(max(0.0, float(stats.get("rh_gain_per_out", 0.0) or 0.0)) / 1.5),  # 湿度增益归一化
        0.16 * _clip01(max(0.0, float(stats.get("delta_ah_in", 0.0) or 0.0)) / 0.25),  # 绝对湿度变化归一化
        0.12 * _clip01(max(0.0, float(stats.get("max_step_in_h", 0.0) or 0.0)) / 0.4),  # 最大阶跃归一化
    ]
    return float(sum(components))


# ==================== 无加热工况多视角分析 ====================

def compute_no_heat_multiview(df: pd.DataFrame, early_stats: Dict[str, float], late_stats: Dict[str, float]) -> Dict[str, Any]:
    """
    无加热工况的多视角特征分析
    
    在高湿无加热条件下，通过多个视角评估密封性能：
    1. 支持度评分：多变量一致性
    2. 呼吸效应防护分：排除正常呼吸干扰
    3. 混杂因素防护分：排除其他因素干扰
    
    Args:
        df: 长时间序列数据（通常 12 小时）
        early_stats: 前半段特征统计
        late_stats: 后半段特征统计
    
    Returns:
        分析结果字典：
        - feature_ready: 特征是否可用
        - support_score_v2: 支持度评分（0~1）
        - breathing_guard_score_v2: 呼吸效应防护分（0~1）
        - confound_guard_score_v2: 混杂因素防护分（0~1）
        - 其他详细特征值
    """
    # 重采样为 1 小时分辨率
    hourly = (
        df.set_index("time")[["in_temp", "out_temp", "in_hum", "out_hum", "AH_in", "AH_out", "d_out_h", "d_in_h", "d_ah_in", "headroom_ah", "dew_in", "dew_out", "dew_gap", "d_dew_out", "d_dew_in", "vpd_in", "vpd_out", "vpd_gap"]]
        .resample("1h")
        .mean(numeric_only=True)
        .interpolate(limit_direction="both")
        .reset_index()
    )
    if len(hourly) < 8:
        return {
            "feature_ready": False,
            "support_score_v2": 0.0,
            "breathing_guard_score_v2": 0.0,
            "confound_guard_score_v2": 0.0,
        }

    early_phase = hourly.iloc[: min(6, len(hourly))].copy()
    late_phase = hourly.iloc[-min(6, len(hourly)):].copy()
    early_dew = _summarize_generic_phase(early_phase, "dew_out", "dew_in", "d_dew_in")

    # 多变量滞后相关性分析
    max_corr_level_hum, best_lag_level_hum = _lagged_corr(hourly["out_hum"], hourly["in_hum"])
    max_corr_level_ah, best_lag_level_ah = _lagged_corr(hourly["AH_out"], hourly["AH_in"])
    max_corr_level_dew, best_lag_level_dew = _lagged_corr(hourly["dew_out"], hourly["dew_in"])
    max_corr_outrh_inrh_change, best_lag_rh_h = _lagged_corr(hourly["d_out_h"], hourly["d_in_h"])
    
    # 露点侵入回归分析
    dew_proxy = _ingress_regression(hourly["dew_gap"], hourly["d_dew_in"], min_drive=0.05)
    
    # 前后阶段差异特征
    late_minus_early_rh_gain = (
        float(late_stats.get("rh_gain_per_out", np.nan)) - float(early_stats.get("rh_gain_per_out", np.nan))
        if pd.notna(late_stats.get("rh_gain_per_out", np.nan)) and pd.notna(early_stats.get("rh_gain_per_out", np.nan))
        else np.nan
    )
    late_minus_early_vpd_gap = float(late_phase["vpd_gap"].mean() - early_phase["vpd_gap"].mean())
    vpd_in_mean = float(pd.to_numeric(df["vpd_in"], errors="coerce").mean())
    dew_capture_ratio = _safe_float(dew_proxy.get("capture_ratio"), np.nan)
    dew_neg_response_ratio = _safe_float(dew_proxy.get("neg_response_ratio"), np.nan)
    early_dew_gain_per_out = _safe_float(early_dew.get("gain_per_drive"), np.nan)

    # 支持度评分：多变量一致性与时间演化
    support_score = float(
        0.22 * _clip_range(max_corr_level_hum, 0.75, 0.95)
        + 0.18 * _clip_range(max_corr_level_ah, 0.70, 0.92)
        + 0.16 * _clip_range(max_corr_level_dew, 0.70, 0.92)
        + 0.16 * _clip_range(max_corr_outrh_inrh_change, 0.55, 0.90)
        + 0.12 * _clip_inverse(best_lag_level_hum, 0.0, 4.0)
        + 0.16 * _clip_range(late_minus_early_rh_gain, 0.05, 0.50)
    )

    # 呼吸效应防护评分：排除正常呼吸模式
    breathing_flags = [
        dew_neg_response_ratio >= 0.85 if pd.notna(dew_neg_response_ratio) else False,  # 高负响应比
        dew_capture_ratio <= 0.10 if pd.notna(dew_capture_ratio) else False,  # 低捕获比
        early_dew_gain_per_out <= -0.15 if pd.notna(early_dew_gain_per_out) else False,  # 负增益
        late_minus_early_rh_gain <= 0.10 if pd.notna(late_minus_early_rh_gain) else False,  # 增益不增长
    ]
    breathing_guard_score = float(np.mean([float(flag) for flag in breathing_flags]))

    # 混杂因素防护评分：排除其他干扰
    confound_flags = [
        early_dew_gain_per_out >= 1.0 if pd.notna(early_dew_gain_per_out) else False,  # 过高增益
        late_minus_early_vpd_gap >= 0.20 if pd.notna(late_minus_early_vpd_gap) else False,  # VPD 变化过大
        max_corr_outrh_inrh_change <= 0.70 if pd.notna(max_corr_outrh_inrh_change) else False,  # 变化相关性过低
        late_minus_early_rh_gain <= 0.0 if pd.notna(late_minus_early_rh_gain) else False,  # 增益下降
    ]
    confound_guard_score = float(np.mean([float(flag) for flag in confound_flags]))

    return {
        "feature_ready": True,
        "support_score_v2": support_score,
        "breathing_guard_score_v2": breathing_guard_score,
        "confound_guard_score_v2": confound_guard_score,
        "max_corr_level_hum": _safe_float(max_corr_level_hum, np.nan),
        "best_lag_level_hum": _safe_float(best_lag_level_hum, np.nan),
        "max_corr_level_ah": _safe_float(max_corr_level_ah, np.nan),
        "best_lag_level_ah": _safe_float(best_lag_level_ah, np.nan),
        "max_corr_level_dew": _safe_float(max_corr_level_dew, np.nan),
        "best_lag_level_dew": _safe_float(best_lag_level_dew, np.nan),
        "max_corr_outRH_inRH_change": _safe_float(max_corr_outrh_inrh_change, np.nan),
        "best_lag_rh_h": _safe_float(best_lag_rh_h, np.nan),
        "early_dew_gain_per_out": early_dew_gain_per_out,
        "late_minus_early_rh_gain": _safe_float(late_minus_early_rh_gain, np.nan),
        "late_minus_early_vpd_gap": _safe_float(late_minus_early_vpd_gap, np.nan),
        "dew_capture_ratio": dew_capture_ratio,
        "dew_neg_response_ratio": dew_neg_response_ratio,
        "vpd_in_mean": vpd_in_mean,
    }


# ==================== 过渡事件检测 ====================

def build_transition_windows(df: pd.DataFrame, hours: float = 2.0) -> List[pd.DataFrame]:
    """
    构建滑动时间窗口
    
    为过渡事件检测构建重叠的滑动窗口序列
    
    Args:
        df: 时间序列 DataFrame
        hours: 窗口宽度（小时，默认 2.0）
    
    Returns:
        窗口列表，每个窗口包含至少 6 个数据点
    """
    if df.empty:
        return []
    windows: List[pd.DataFrame] = []
    width = pd.Timedelta(hours=float(hours))
    for idx in range(len(df)):
        end_time = df["time"].iloc[idx]
        start_time = end_time - width
        wdf = df[(df["time"] >= start_time) & (df["time"] <= end_time)].copy()
        if len(wdf) >= 6:
            windows.append(wdf.reset_index(drop=True))
    return windows


def _transition_window_summary(features: List[Dict[str, float]], no_heat_context: bool) -> List[Dict[str, Any]]:
    """
    过渡窗口摘要评分
    
    基于历史窗口的特征序列，评估当前窗口的过渡事件强度
    
    Args:
        features: 窗口特征列表（按时间顺序）
        no_heat_context: 是否为无加热工况
    
    Returns:
        摘要列表，每个摘要包含：
        - status: 状态（transition_boost_alert / transition_weak）
        - score: 过渡强度评分
        - latest_delta_in_h: 最新内部湿度变化
        - latest_delta_ah_in: 最新内部绝对湿度变化
        - latest_headroom_ratio: 最新湿度余量比例
        - slow_shape_candidate: 是否为缓慢型候选
        - slow_shape_run_length: 缓慢型连续出现次数
    """
    if len(features) < 3 or not no_heat_context:
        return []
    
    summaries: List[Dict[str, Any]] = []
    slow_run = 0
    for idx in range(2, len(features)):
        current = features[idx]
        history = features[:idx]
        
        # 基于历史分布的鲁棒 Z 分数评分
        score_raw = (
            0.35 * _robust_z_positive([f.get("delta_in_h", np.nan) for f in history], float(current.get("delta_in_h", 0.0) or 0.0))
            + 0.30 * _robust_z_positive([f.get("delta_ah_in", np.nan) for f in history], float(current.get("delta_ah_in", 0.0) or 0.0))
            + 0.20 * _robust_z_positive([f.get("max_step_in_h", np.nan) for f in history], float(current.get("max_step_in_h", 0.0) or 0.0))
            + 0.15 * _robust_z_positive(
                [f.get("positive_headroom_ratio", np.nan) for f in history],
                float(current.get("positive_headroom_ratio", 0.0) or 0.0),
            )
        )
        score = _clip01(score_raw / 4.0)
        
        # 形态判断
        strong_shape = (
            float(current.get("delta_in_h", 0.0) or 0.0) >= 0.8
            and float(current.get("delta_ah_in", 0.0) or 0.0) >= 0.03
            and float(current.get("positive_headroom_ratio", 0.0) or 0.0) >= 0.5
        )
        moderate_shape = (
            float(current.get("delta_in_h", 0.0) or 0.0) >= 0.6
            and float(current.get("delta_ah_in", 0.0) or 0.0) >= 0.03
            and float(current.get("positive_headroom_ratio", 0.0) or 0.0) >= 0.5
        )
        slow_shape = (
            float(current.get("delta_in_h", 0.0) or 0.0) >= 0.55
            and float(current.get("delta_ah_in", 0.0) or 0.0) >= 0.08
            and float(current.get("positive_headroom_ratio", 0.0) or 0.0) >= 0.5
            and score >= 0.28
        )
        
        if slow_shape:
            slow_run += 1
        else:
            slow_run = 0
        
        sustained_slow_shape = slow_run >= 3
        
        # 状态判定
        status = (
            "transition_boost_alert"
            if (strong_shape and score >= 0.30) or (moderate_shape and score >= 0.15) or sustained_slow_shape
            else "transition_weak"
        )
        
        summaries.append(
            {
                "status": status,
                "score": score,
                "latest_delta_in_h": float(current.get("delta_in_h", np.nan)),
                "latest_delta_ah_in": float(current.get("delta_ah_in", np.nan)),
                "latest_headroom_ratio": float(current.get("positive_headroom_ratio", np.nan)),
                "slow_shape_candidate": slow_shape,
                "slow_shape_run_length": int(slow_run),
            }
        )
    return summaries


def classify_transition(df: pd.DataFrame, no_heat_context: bool) -> Dict[str, Any]:
    """
    过渡事件分类
    
    判断当前是否处于过渡事件（如密封失效导致的快速变化）
    
    Args:
        df: 时间序列 DataFrame
        no_heat_context: 是否为无加热工况
    
    Returns:
        分类结果（同 _transition_window_summary 的最新一项）
    """
    windows = build_transition_windows(df, 2.0)
    if len(windows) < 3 or not no_heat_context:
        return {
            "status": "transition_weak",
            "score": 0.0,
            "latest_delta_in_h": np.nan,
            "latest_delta_ah_in": np.nan,
            "latest_headroom_ratio": np.nan,
        }
    features = [phase_stats(w) for w in windows]
    summaries = _transition_window_summary(features, no_heat_context)
    return summaries[-1] if summaries else {
        "status": "transition_weak",
        "score": 0.0,
        "latest_delta_in_h": np.nan,
        "latest_delta_ah_in": np.nan,
        "latest_headroom_ratio": np.nan,
    }


def summarize_transition_event(df: pd.DataFrame, no_heat_context: bool) -> Optional[Dict[str, Any]]:
    """
    过渡事件汇总
    
    识别并总结完整的过渡事件（连续的强过渡窗口序列）
    
    Args:
        df: 时间序列 DataFrame
        no_heat_context: 是否为无加热工况
    
    Returns:
        事件摘要或 None：
        - event_start_ts: 事件开始时间戳
        - event_end_ts: 事件结束时间戳
        - peak_time_ts: 峰值时间戳
        - peak_score: 峰值评分
        - window_count: 窗口数量
        - duration_hours: 事件持续时间（小时）
    """
    windows = build_transition_windows(df, 2.0)
    if len(windows) < 3 or not no_heat_context:
        return None
    features = [phase_stats(w) for w in windows]
    summaries = _transition_window_summary(features, no_heat_context)
    if not summaries:
        return None

    # 识别连续的事件运行
    event_runs: List[List[int]] = []
    current_run: List[int] = []
    for idx, item in enumerate(summaries, start=2):
        if item.get("status") == "transition_boost_alert":
            current_run.append(idx)
        elif current_run:
            event_runs.append(current_run)
            current_run = []
    if current_run:
        event_runs.append(current_run)
    if not event_runs:
        return None

    # 选择最长的连续事件
    event = max(event_runs, key=len)
    peak_idx = max(event, key=lambda idx: float(summaries[idx - 2].get("score", 0.0) or 0.0))
    start_window = windows[event[0]]
    end_window = windows[event[-1]]
    peak_window = windows[peak_idx]
    peak_summary = summaries[peak_idx - 2]
    
    return {
        "event_start_ts": int(start_window["ts"].iloc[0]),
        "event_end_ts": int(end_window["ts"].iloc[-1]),
        "peak_time_ts": int(peak_window["ts"].iloc[-1]),
        "peak_score": float(peak_summary.get("score", 0.0) or 0.0),
        "window_count": int(len(event)),
        "duration_hours": float((end_window["time"].iloc[-1] - start_window["time"].iloc[0]).total_seconds() / 3600.0),
    }


# ==================== 无加热工况分类 ====================

def classify_no_heat(df: pd.DataFrame) -> Dict[str, Any]:
    """
    无加热工况分类器
    
    针对高湿无加热条件下的密封性能进行综合评估
    
    Args:
        df: 时间序列 DataFrame（已重采样）
    
    Returns:
        分类结果字典：
        - status: 状态分类
          * static_abstain_low_signal: 信号不足弃权
          * static_hard_case_watch: 复杂情况观察
          * static_dynamic_supported_alert: 动态支持告警
        - score: 综合评分（0~1）
        - main_signal: 主信号强度
        - long_signal: 长期信号强度
        - short_signal: 短期信号强度
        - score_main_minus_long: 主长期信号差值
        - onset_positive_v3: 起始正向标志
        - late_persistence_v3: 后期持续性标志
        - breathing_bias_v3: 呼吸偏置标志
        - multiview_v2: 多视角分析结果
        - early/late/main/long/short_stats: 各时段统计特征
    """
    long_df = tail_hours(df, 12)
    main_df = tail_hours(df, 6)
    short_df = tail_hours(df, 2)
    if len(long_df) < 18 or len(main_df) < 9:
        return {
            "status": "static_abstain_low_signal",
            "score": 0.0,
            "main_signal": 0.0,
            "long_signal": 0.0,
            "short_signal": 0.0,
        }

    # 划分前后阶段
    midpoint = long_df["time"].max() - pd.Timedelta(hours=6)
    early_df = long_df[long_df["time"] <= midpoint].copy()
    late_df = long_df[long_df["time"] > midpoint].copy()
    if early_df.empty or late_df.empty:
        half = max(1, len(long_df) // 2)
        early_df = long_df.iloc[:half].copy()
        late_df = long_df.iloc[half:].copy()

    early_stats = phase_stats(early_df)
    late_stats = phase_stats(late_df)
    main_stats = phase_stats(main_df)
    long_stats = phase_stats(long_df)
    short_stats = phase_stats(short_df)
    multiview = compute_no_heat_multiview(long_df, early_stats, late_stats)

    # 计算多尺度信号强度
    main_signal = response_signal_score(main_stats)
    long_signal = response_signal_score(long_stats)
    short_signal = response_signal_score(short_stats)
    
    # 关键标志位
    onset_positive = (
        float(early_stats.get("respond_in_h_pos_ratio", 0.0) or 0.0) >= 0.75
        and float(early_stats.get("rh_gain_per_out", 0.0) or 0.0) > 0.0
        and float(main_stats.get("positive_headroom_ratio", 0.0) or 0.0) >= 0.5
        and main_signal >= 0.35
    )
    score_main_minus_long = main_signal - long_signal
    late_persistence = (
        float(late_stats.get("respond_in_h_pos_ratio", 0.0) or 0.0) >= 0.75
        and score_main_minus_long < 0.08
    )
    breathing_bias = (
        float(late_stats.get("rh_gain_per_out", 0.0) or 0.0) > float(early_stats.get("rh_gain_per_out", 0.0) or 0.0)
        and float(late_stats.get("ah_decay_per_headroom", -1.0) or -1.0) >= -0.01
    )
    
    # 多视角特征
    support_score_v2 = float(multiview.get("support_score_v2", 0.0) or 0.0)
    breathing_guard_score_v2 = float(multiview.get("breathing_guard_score_v2", 0.0) or 0.0)
    confound_guard_score_v2 = float(multiview.get("confound_guard_score_v2", 0.0) or 0.0)
    strong_multiview_support = (
        support_score_v2 >= 0.68
        and breathing_guard_score_v2 < 0.50
        and confound_guard_score_v2 < 0.50
    )
    guarded_hard_case = breathing_guard_score_v2 >= 0.50 or confound_guard_score_v2 >= 0.50

    # 状态决策树
    if not onset_positive:
        status = "static_abstain_low_signal"
        score = _clip01(0.15 + 0.35 * main_signal)
    elif guarded_hard_case or (late_persistence and breathing_bias):
        status = "static_hard_case_watch"
        score = _clip01(0.40 + 0.18 * max(main_signal, long_signal, breathing_guard_score_v2, confound_guard_score_v2))
    elif strong_multiview_support:
        status = "static_dynamic_supported_alert"
        score = _clip01(0.70 + 0.20 * max(main_signal, short_signal, support_score_v2))
    elif support_score_v2 >= 0.50:
        status = "static_hard_case_watch"
        score = _clip01(0.44 + 0.14 * max(main_signal, support_score_v2))
    else:
        status = "static_dynamic_supported_alert"
        score = _clip01(0.68 + 0.22 * max(main_signal, short_signal))

    return {
        "status": status,
        "score": score,
        "main_signal": main_signal,
        "long_signal": long_signal,
        "short_signal": short_signal,
        "score_main_minus_long": score_main_minus_long,
        "onset_positive_v3": onset_positive,
        "late_persistence_v3": late_persistence,
        "breathing_bias_v3": breathing_bias,
        "multiview_v2": multiview,
        "early_stats": early_stats,
        "late_stats": late_stats,
        "main_stats": main_stats,
        "long_stats": long_stats,
    }


# ==================== 工况分类 ====================

def classify_context(df: pd.DataFrame) -> Dict[str, Any]:
    """
    工况分类器
    
    根据环境条件判断当前属于哪种工况分支
    
    Args:
        df: 时间序列 DataFrame（已重采样）
    
    Returns:
        分类结果字典：
        - branch: 工况分支
          * heat_related: 加热相关
          * ext_high_hum_no_heat: 高湿无加热
          * low_info: 低信息量
        - high_external_humidity: 是否高外湿
        - heat_related: 是否加热相关
        - latest_6h/latest_2h: 最近 6h/2h 统计特征
    """
    latest_6h = phase_stats(tail_hours(df, 6))
    latest_2h = phase_stats(tail_hours(df, 2))
    mean_out_hum = float(latest_6h.get("mean_out_hum", np.nan))
    mean_out_ah = float(latest_6h.get("mean_out_ah", np.nan))
    mean_dt = float(latest_6h.get("mean_dt", np.nan))

    high_external_humidity = bool(
        (pd.notna(mean_out_hum) and mean_out_hum >= 78.0)
        or (pd.notna(mean_out_ah) and mean_out_ah >= 12.0)
    )
    heat_related = bool(pd.notna(mean_dt) and mean_dt >= 5.0)
    no_heat_high_hum = high_external_humidity and not heat_related

    if heat_related:
        branch = "heat_related"
    elif no_heat_high_hum:
        branch = "ext_high_hum_no_heat"
    else:
        branch = "low_info"

    return {
        "branch": branch,
        "high_external_humidity": high_external_humidity,
        "heat_related": heat_related,
        "latest_6h": latest_6h,
        "latest_2h": latest_2h,
    }


# ==================== 主检测流程 ====================

def run_local_detection(
    *,
    dev_num: str,
    device_timestamp: int,
    points: List[Dict[str, Any]],
    requested_model_name: str,
) -> Dict[str, Any]:
    """
    局部密封检测主函数
    
    执行完整的密封性检测流程，返回 anomaly 判定结果
    
    Args:
        dev_num: 设备编号
        device_timestamp: 设备时间戳（毫秒）
        points: 原始测量点列表
        requested_model_name: 请求的模型名称
    
    Returns:
        检测结果字典：
        - request_id: 请求 ID（本地模型为 None）
        - is_anomaly: 是否异常（布尔）
        - anomaly_score: 异常评分（0~1）
        - threshold: 判定阈值
        - model_name/model_version: 模型名称和版本
        - infer_latency_ms: 推理延迟（毫秒）
        - status: 状态描述
        - method: 检测方法标识
        - requested_model_name: 请求的模型名称
        - local_context: 本地上下文信息
          * dev_num/device_timestamp: 设备信息
          * span_hours: 数据跨度（小时）
          * resampled_points: 重采样点数
          * context_branch: 工况分支
          * risk_level: 风险等级（low/watch/high）
          * primary_evidence: 主要证据类型
          * context_latest_6h: 最近 6h 特征
          * transition: 过渡事件结果
          * transition_event: 过渡事件汇总
          * no_heat: 无加热工况结果
    """
    started = time.perf_counter()
    
    # 数据预处理
    raw_df = prepare_points_df(points)
    if raw_df.empty:
        latency = int((time.perf_counter() - started) * 1000)
        return {
            "request_id": None,
            "is_anomaly": False,
            "anomaly_score": 0.0,
            "threshold": 0.70,
            "model_name": LOCAL_MODEL_NAME,
            "model_version": LOCAL_MODEL_VERSION,
            "infer_latency_ms": latency,
            "status": "insufficient_data",
            "method": "LOCAL_SEAL_V4",
            "requested_model_name": requested_model_name,
        }

    # 重采样
    df = resample_points_df(raw_df)
    span_hours = float((df["time"].iloc[-1] - df["time"].iloc[0]).total_seconds() / 3600.0) if len(df) >= 2 else 0.0
    
    # 数据充分性检查
    if len(df) < 12 or span_hours < 2.0:
        latency = int((time.perf_counter() - started) * 1000)
        return {
            "request_id": None,
            "is_anomaly": False,
            "anomaly_score": 0.0,
            "threshold": 0.70,
            "model_name": LOCAL_MODEL_NAME,
            "model_version": LOCAL_MODEL_VERSION,
            "infer_latency_ms": latency,
            "status": "insufficient_history_local",
            "method": "LOCAL_SEAL_V4",
            "requested_model_name": requested_model_name,
            "local_context": {"span_hours": span_hours, "resampled_points": int(len(df))},
        }

    # 工况分类
    context = classify_context(df)
    
    # 专项分析（仅在高湿无加热工况下执行）
    no_heat_result = classify_no_heat(df) if context["branch"] == "ext_high_hum_no_heat" else None
    transition_result = classify_transition(df, context["branch"] == "ext_high_hum_no_heat")
    transition_event = summarize_transition_event(df, context["branch"] == "ext_high_hum_no_heat")

    # 默认状态
    status = "low_info_background"
    risk_level = "low"
    primary_evidence = "background"
    score = 0.08
    is_anomaly = False
    threshold = 0.70

    # 决策逻辑
    if transition_result["status"] == "transition_boost_alert":
        # 过渡事件告警（最高优先级）
        status = "transition_boost_alert"
        risk_level = "high"
        primary_evidence = "transition_boost"
        score = max(0.84, float(transition_result["score"]))
        is_anomaly = True
        threshold = 0.72
    elif context["branch"] == "ext_high_hum_no_heat" and no_heat_result:
        # 高湿无热工况详细评估
        status = str(no_heat_result["status"])
        score = float(no_heat_result["score"])
        if status == "static_dynamic_supported_alert":
            risk_level = "high"
            primary_evidence = "multiview_support+no_heat_probe"
            is_anomaly = True
            threshold = 0.68
        elif status == "static_hard_case_watch":
            risk_level = "watch"
            primary_evidence = "hard_case_multiview+no_heat_probe"
        else:
            risk_level = "low"
            primary_evidence = "low_signal_no_heat"
    elif context["branch"] == "heat_related":
        # 加热相关工况（低风险）
        status = "heat_related_background"
        risk_level = "low"
        primary_evidence = "heat_related_gate"
        score = 0.12

    latency = int((time.perf_counter() - started) * 1000)
    return {
        "request_id": None,
        "is_anomaly": is_anomaly,
        "anomaly_score": float(score),
        "threshold": float(threshold),
        "model_name": LOCAL_MODEL_NAME,
        "model_version": LOCAL_MODEL_VERSION,
        "infer_latency_ms": latency,
        "status": status,
        "method": "LOCAL_SEAL_V4",
        "requested_model_name": requested_model_name,
        "local_context": {
            "dev_num": dev_num,
            "device_timestamp": device_timestamp,
            "span_hours": span_hours,
            "resampled_points": int(len(df)),
            "context_branch": context["branch"],
            "risk_level": risk_level,
            "primary_evidence": primary_evidence,
            "context_latest_6h": context["latest_6h"],
            "transition": transition_result,
            "transition_event": transition_event,
            "no_heat": no_heat_result,
        },
    }
