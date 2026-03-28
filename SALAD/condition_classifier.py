# -*- coding: utf-8 -*-
"""
condition_classifier.py

功能：
对“一个24小时窗口的 dataframe”进行工况分类。
输入：一个包含时间、内外温湿度列的 dataframe
输出：
    1) 工况标签
    2) 特征字典
    3) 预处理后的窗口 dataframe
"""

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# -----------------------------
# 配置参数
# -----------------------------
@dataclass
class Config:
    window_hours: int = 24

    # 规则阈值
    low_std_temp: float = 0.6
    low_std_hum: float = 2.1
    low_abs_slope_temp: float = 0.08
    low_abs_slope_ah: float = 0.03

    heat_dT_mean_thresh: float = 3.0
    heat_dT_half_diff_thresh: float = 1.5

    startup_temp_rise_thresh: float = 4.0
    startup_slope_thresh: float = 0.35
    startup_slope_gap_thresh: float = 0.10

    cooling_temp_drop_thresh: float = -3.0
    cooling_slope_thresh: float = -0.25
    cooling_slope_gap_thresh: float = 0.10

    out_high_hum_thresh: float = 80.0
    out_high_ah_thresh: float = 12.0

    moisture_transition_hum_increase: float = 6.0
    moisture_transition_ah_increase: float = 1.0

    internal_moist_high_hum: float = 80.0
    internal_moist_ratio: float = 0.60
    internal_moist_ah_margin: float = 0.8


CFG = Config()

CLASS_NAMES = [
    "低信息工况",
    "外部高湿驱动工况",
    "热源稳定工况",
    "热源启动窗口",
    "冷却窗口",
    "内部积湿状态切换窗口",
    "内部积湿工况",
    "复杂耦合工况",
]


# 中文 -> 英文状态码（无空格，推荐用于系统）
CLASS_NAME_EN = {
    "低信息工况": "LOW_INFO",
    "外部高湿驱动工况": "EXT_HIGH_HUM",
    "热源稳定工况": "HEAT_STABLE",
    "热源启动窗口": "HEAT_START",
    "冷却窗口": "COOLING",
    "内部积湿状态切换窗口": "MOIST_TRANSITION",
    "内部积湿工况": "INTERNAL_MOIST",
    "复杂耦合工况": "COMPLEX",
}

# -----------------------------
# 列名映射
# -----------------------------
COLUMN_ALIASES = {
    "time": ["time", "时间", "timestamp", "date", "datetime"],
    "in_temp": ["in_temp", "内部温度", "内温", "温度_内", "in_temperature"],
    "in_hum": ["in_hum", "内部湿度", "内湿", "湿度_内", "in_humidity"],
    "out_temp": ["out_temp", "外部温度", "外温", "温度_外", "out_temperature"],
    "out_hum": ["out_hum", "外部湿度", "外湿", "湿度_外", "out_humidity"],
}


# -----------------------------
# 基础工具函数
# -----------------------------
def find_column(df: pd.DataFrame, aliases: List[str]) -> Optional[str]:
    lower_map = {str(c).strip().lower(): c for c in df.columns}
    for a in aliases:
        key = str(a).strip().lower()
        if key in lower_map:
            return lower_map[key]
    return None


def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    col_map = {}
    for std_name, aliases in COLUMN_ALIASES.items():
        found = find_column(df, aliases)
        if found is None:
            raise ValueError(f"缺少必要列：{std_name}，候选别名={aliases}")
        col_map[found] = std_name
    df = df.rename(columns=col_map).copy()
    return df[["time", "in_temp", "in_hum", "out_temp", "out_hum"]]


def calc_absolute_humidity(temp_c: pd.Series, rh: pd.Series) -> pd.Series:
    """
    绝对湿度，单位 g/m^3
    """
    svp = 6.112 * np.exp((17.67 * temp_c) / (temp_c + 243.5))   # hPa
    avp = svp * rh / 100.0
    ah = 2.1674 * avp / (273.15 + temp_c) * 100.0
    return ah


def preprocess_df(df: pd.DataFrame) -> pd.DataFrame:
    df = standardize_columns(df)

    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df = df.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)

    for c in ["in_temp", "in_hum", "out_temp", "out_hum"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["in_temp", "in_hum", "out_temp", "out_hum"]).copy()

    df["AH_in"] = calc_absolute_humidity(df["in_temp"], df["in_hum"])
    df["AH_out"] = calc_absolute_humidity(df["out_temp"], df["out_hum"])
    df["dT"] = df["in_temp"] - df["out_temp"]
    df["dRH"] = df["in_hum"] - df["out_hum"]
    df["dAH"] = df["AH_in"] - df["AH_out"]

    return df


def infer_median_interval_seconds(df: pd.DataFrame) -> float:
    dt = df["time"].diff().dt.total_seconds().dropna()
    if len(dt) == 0:
        return 60.0
    return float(dt.median())


def safe_std(x: pd.Series) -> float:
    if len(x) < 2:
        return 0.0
    return float(np.nanstd(x, ddof=1))


def slope_per_hour(time_s: pd.Series, value_s: pd.Series) -> float:
    if len(time_s) < 3:
        return 0.0
    x = (time_s - time_s.min()).dt.total_seconds() / 3600.0
    y = value_s.values.astype(float)
    if np.allclose(y, y[0]):
        return 0.0
    try:
        coef = np.polyfit(x, y, 1)
        return float(coef[0])
    except Exception:
        return 0.0


def corr_safe(a: pd.Series, b: pd.Series) -> float:
    if len(a) < 3:
        return 0.0
    v = np.corrcoef(a.values.astype(float), b.values.astype(float))[0, 1]
    if np.isnan(v):
        return 0.0
    return float(v)


# -----------------------------
# 特征提取
# -----------------------------
def extract_features(wdf: pd.DataFrame, cfg: Config = CFG) -> Dict[str, float]:
    feat = {}

    for c in ["in_temp", "out_temp", "in_hum", "out_hum", "AH_in", "AH_out", "dT", "dAH"]:
        feat[f"mean_{c}"] = float(wdf[c].mean())

    for c in ["in_temp", "out_temp", "in_hum", "out_hum", "AH_in", "AH_out", "dT", "dAH"]:
        feat[f"std_{c}"] = safe_std(wdf[c])

    for c in ["in_temp", "out_temp", "in_hum", "out_hum", "AH_in", "AH_out", "dT", "dAH"]:
        feat[f"slope_{c}"] = slope_per_hour(wdf["time"], wdf[c])

    n = len(wdf)
    half = n // 2
    first = wdf.iloc[:half].copy()
    second = wdf.iloc[half:].copy()

    for c in ["in_temp", "out_temp", "in_hum", "out_hum", "AH_in", "AH_out", "dT", "dAH"]:
        feat[f"first_mean_{c}"] = float(first[c].mean()) if len(first) else np.nan
        feat[f"second_mean_{c}"] = float(second[c].mean()) if len(second) else np.nan
        feat[f"delta_half_{c}"] = feat[f"second_mean_{c}"] - feat[f"first_mean_{c}"]

    feat["first_slope_in_temp"] = slope_per_hour(first["time"], first["in_temp"]) if len(first) >= 3 else 0.0
    feat["second_slope_in_temp"] = slope_per_hour(second["time"], second["in_temp"]) if len(second) >= 3 else 0.0
    feat["first_slope_AH_in"] = slope_per_hour(first["time"], first["AH_in"]) if len(first) >= 3 else 0.0
    feat["second_slope_AH_in"] = slope_per_hour(second["time"], second["AH_in"]) if len(second) >= 3 else 0.0

    feat["delta_in_temp"] = float(wdf["in_temp"].iloc[-1] - wdf["in_temp"].iloc[0])
    feat["delta_out_temp"] = float(wdf["out_temp"].iloc[-1] - wdf["out_temp"].iloc[0])
    feat["delta_in_hum"] = float(wdf["in_hum"].iloc[-1] - wdf["in_hum"].iloc[0])
    feat["delta_AH_in"] = float(wdf["AH_in"].iloc[-1] - wdf["AH_in"].iloc[0])

    feat["corr_temp"] = corr_safe(wdf["in_temp"], wdf["out_temp"])
    feat["corr_hum"] = corr_safe(wdf["in_hum"], wdf["out_hum"])
    feat["corr_AH"] = corr_safe(wdf["AH_in"], wdf["AH_out"])

    feat["high_in_hum_ratio"] = float((wdf["in_hum"] >= cfg.internal_moist_high_hum).mean())
    feat["high_out_hum_ratio"] = float((wdf["out_hum"] >= cfg.out_high_hum_thresh).mean())
    feat["in_ah_gt_out_ah_ratio"] = float((wdf["AH_in"] > (wdf["AH_out"] + cfg.internal_moist_ah_margin)).mean())

    wd = wdf.set_index("time").resample("1h").mean(numeric_only=True).interpolate(limit_direction="both")
    feat["max_hourly_temp_rise"] = float(wd["in_temp"].diff().max()) if len(wd) > 1 else 0.0
    feat["max_hourly_temp_drop"] = float(wd["in_temp"].diff().min()) if len(wd) > 1 else 0.0
    feat["max_hourly_hum_rise"] = float(wd["in_hum"].diff().max()) if len(wd) > 1 else 0.0

    return feat


# -----------------------------
# 分类规则
# -----------------------------
def classify_window_from_features(feat: Dict[str, float], cfg: Config = CFG) -> str:
    """
    分类顺序：
    1. 内部积湿状态切换窗口
    2. 内部积湿工况
    3. 热源启动窗口
    4. 热源稳定工况
    5. 冷却窗口
    6. 外部高湿驱动工况
    7. 低信息工况
    8. 复杂耦合工况
    """

    moisture_transition = (
        feat["delta_half_in_hum"] >= cfg.moisture_transition_hum_increase
        and feat["delta_half_AH_in"] >= cfg.moisture_transition_ah_increase
        and feat["std_out_hum"] < max(cfg.low_std_hum * 2, 5.0)
    )
    if moisture_transition:
        return "内部积湿状态切换窗口"

    internal_moist = (
        feat["mean_in_hum"] >= cfg.internal_moist_high_hum
        and feat["high_in_hum_ratio"] >= cfg.internal_moist_ratio
        and feat["mean_AH_in"] > feat["mean_AH_out"] + cfg.internal_moist_ah_margin
    )
    if internal_moist:
        return "内部积湿工况"

    startup_a = (
        feat["delta_in_temp"] >= cfg.startup_temp_rise_thresh
        and feat["slope_in_temp"] >= cfg.startup_slope_thresh
        and (feat["slope_in_temp"] - feat["slope_out_temp"]) >= cfg.startup_slope_gap_thresh
    )
    startup_b = (
        feat["mean_dT"] >= cfg.heat_dT_mean_thresh
        and feat["slope_in_temp"] >= cfg.startup_slope_thresh
        and feat["delta_in_temp"] >= cfg.startup_temp_rise_thresh
    )
    if startup_a or startup_b:
        return "热源启动窗口"

    heat_stable = (
        feat["mean_dT"] >= cfg.heat_dT_mean_thresh
        and abs(feat["slope_in_temp"]) < 0.20
        and abs(feat["delta_half_dT"]) < 1.5
    )
    if heat_stable:
        return "热源稳定工况"

    cooling = (
        feat["slope_in_temp"] <= cfg.cooling_slope_thresh
        and (feat["slope_out_temp"] - feat["slope_in_temp"]) >= cfg.cooling_slope_gap_thresh
        and feat["delta_in_temp"] <= cfg.cooling_temp_drop_thresh
    )
    if cooling:
        return "冷却窗口"

    external_high_hum = (
        (feat["mean_out_hum"] >= cfg.out_high_hum_thresh or feat["mean_AH_out"] >= cfg.out_high_ah_thresh)
        and feat["mean_dT"] < cfg.heat_dT_mean_thresh
    )
    if external_high_hum:
        return "外部高湿驱动工况"

    low_info = (
        feat["std_in_temp"] < cfg.low_std_temp
        and feat["std_out_temp"] < cfg.low_std_temp
        and feat["std_in_hum"] < cfg.low_std_hum
        and feat["std_out_hum"] < cfg.low_std_hum
        and abs(feat["slope_in_temp"]) < cfg.low_abs_slope_temp
        and abs(feat["slope_AH_in"]) < cfg.low_abs_slope_ah
        and feat["mean_dT"] < cfg.heat_dT_mean_thresh
    )
    if low_info:
        return "低信息工况"

    return "复杂耦合工况"


def classify_24h_dataframe(df_24h: pd.DataFrame, cfg: Config = CFG) -> Tuple[str, Dict[str, float], pd.DataFrame]:
    """
    对一个24小时窗口的 dataframe 进行分类。

    返回：
        label: 工况类别
        feat:  特征字典
        wdf:   预处理后的窗口数据
    """
    wdf = preprocess_df(df_24h)

    if len(wdf) < 3:
        raise ValueError("有效数据点过少，无法分类。")

    span_hours = (wdf["time"].max() - wdf["time"].min()).total_seconds() / 3600.0
    if span_hours < 20:
        print(f"[WARN] 当前窗口时间跨度仅 {span_hours:.2f} 小时，小于24小时，分类结果仅供参考。")

    feat = extract_features(wdf, cfg)
    label = classify_window_from_features(feat, cfg)
    label_en = CLASS_NAME_EN.get(label, "UNKNOWN")
    return label_en, feat, wdf