# -*- coding: utf-8 -*-
"""
基于 24 小时滑动窗口的工况分类器 v1

增强点：
1. 支持直接读取 zip 内的实验 Excel 数据
2. 支持读取实验说明表并把实验级标签回填到窗口级结果
3. 输出窗口汇总、文件级汇总、metadata 覆盖情况和转移段分析
4. 保留原有 8 类规则分类逻辑，便于继续调阈值
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


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


COLUMN_ALIASES = {
    "time": ["time", "时间", "timestamp", "date", "datetime"],
    "in_temp": ["in_temp", "内部温度", "内温", "温度_内", "in_temperature"],
    "in_hum": ["in_hum", "内部湿度", "内湿", "湿度_内", "in_humidity"],
    "out_temp": ["out_temp", "外部温度", "外温", "温度_外", "out_temperature"],
    "out_hum": ["out_hum", "外部湿度", "外湿", "湿度_外", "out_humidity"],
}


@dataclass
class Config:
    input_dir: str = "./excel_input"
    input_zip: str = "./data/data_2026-03-24.zip"
    metadata_xlsx: str = "./data/A312实验室采集数据说明文档.xlsx"
    output_dir: str = "./reports/condition_classifier_v1"

    window_hours: int = 24
    step_hours: int = 1
    transition_near_hours: int = 6
    min_window_coverage_ratio: float = 0.60

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

    export_window_csv: bool = False
    export_feature_json: bool = False
    export_window_plot: bool = False


CFG = Config()


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def normalize_filename_token(name: Any) -> str:
    token = str(name or "").strip()
    token = token.replace("\\", "/").split("/")[-1]
    if token.lower().endswith(".xlsx") or token.lower().endswith(".xls"):
        token = token.rsplit(".", 1)[0]
    token = " ".join(token.split())
    return token


def parse_datetime_or_none(value: Any) -> Optional[pd.Timestamp]:
    if value in (None, "", "无"):
        return None
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    return pd.Timestamp(ts)


def is_missing_time(value: Any) -> bool:
    return value is None or pd.isna(value)


def bool_from_cli(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def find_column(df: pd.DataFrame, aliases: Iterable[str]) -> Optional[str]:
    lower_map = {str(c).strip().lower(): c for c in df.columns}
    for alias in aliases:
        key = str(alias).strip().lower()
        if key in lower_map:
            return lower_map[key]
    return None


def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    col_map: Dict[str, str] = {}
    for std_name, aliases in COLUMN_ALIASES.items():
        found = find_column(df, aliases)
        if found is None:
            raise ValueError(f"缺少必要列：{std_name}，候选别名={aliases}")
        col_map[found] = std_name
    df = df.rename(columns=col_map).copy()
    return df[["time", "in_temp", "in_hum", "out_temp", "out_hum"]]


def calc_absolute_humidity(temp_c: pd.Series, rh: pd.Series) -> pd.Series:
    svp = 6.112 * np.exp((17.67 * temp_c) / (temp_c + 243.5))
    avp = svp * rh / 100.0
    return 2.1674 * avp / (273.15 + temp_c) * 100.0


def preprocess_df(df: pd.DataFrame) -> pd.DataFrame:
    df = standardize_columns(df)
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df = df.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)

    for col in ["in_temp", "in_hum", "out_temp", "out_hum"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

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


def sliding_windows(df: pd.DataFrame, cfg: Config) -> List[Tuple[pd.Timestamp, pd.Timestamp, pd.DataFrame]]:
    start = df["time"].min().floor("h")
    end = df["time"].max().ceil("h")
    window_delta = pd.Timedelta(hours=cfg.window_hours)
    step_delta = pd.Timedelta(hours=cfg.step_hours)

    median_sec = infer_median_interval_seconds(df)
    expected_count = max(1, int(window_delta.total_seconds() / max(median_sec, 1.0)))
    min_count = int(expected_count * cfg.min_window_coverage_ratio)

    windows: List[Tuple[pd.Timestamp, pd.Timestamp, pd.DataFrame]] = []
    cur = start
    while cur + window_delta <= end:
        w_end = cur + window_delta
        wdf = df[(df["time"] >= cur) & (df["time"] < w_end)].copy()
        if len(wdf) >= min_count:
            windows.append((cur, w_end, wdf))
        cur += step_delta
    return windows


def safe_std(series: pd.Series) -> float:
    if len(series) < 2:
        return 0.0
    return float(np.nanstd(series, ddof=1))


def slope_per_hour(time_s: pd.Series, value_s: pd.Series) -> float:
    if len(time_s) < 3:
        return 0.0
    x = (time_s - time_s.min()).dt.total_seconds() / 3600.0
    y = value_s.values.astype(float)
    if np.allclose(y, y[0]):
        return 0.0
    try:
        return float(np.polyfit(x, y, 1)[0])
    except Exception:
        return 0.0


def corr_safe(a: pd.Series, b: pd.Series) -> float:
    if len(a) < 3:
        return 0.0
    v = np.corrcoef(a.values.astype(float), b.values.astype(float))[0, 1]
    if np.isnan(v):
        return 0.0
    return float(v)


def extract_features(wdf: pd.DataFrame) -> Dict[str, float]:
    feat: Dict[str, float] = {}

    for col in ["in_temp", "out_temp", "in_hum", "out_hum", "AH_in", "AH_out", "dT", "dAH"]:
        feat[f"mean_{col}"] = float(wdf[col].mean())
        feat[f"std_{col}"] = safe_std(wdf[col])
        feat[f"slope_{col}"] = slope_per_hour(wdf["time"], wdf[col])

    half = len(wdf) // 2
    first = wdf.iloc[:half].copy()
    second = wdf.iloc[half:].copy()
    for col in ["in_temp", "out_temp", "in_hum", "out_hum", "AH_in", "AH_out", "dT", "dAH"]:
        first_mean = float(first[col].mean()) if len(first) else np.nan
        second_mean = float(second[col].mean()) if len(second) else np.nan
        feat[f"first_mean_{col}"] = first_mean
        feat[f"second_mean_{col}"] = second_mean
        feat[f"delta_half_{col}"] = second_mean - first_mean

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

    feat["high_in_hum_ratio"] = float((wdf["in_hum"] >= CFG.internal_moist_high_hum).mean())
    feat["high_out_hum_ratio"] = float((wdf["out_hum"] >= CFG.out_high_hum_thresh).mean())
    feat["in_ah_gt_out_ah_ratio"] = float((wdf["AH_in"] > (wdf["AH_out"] + CFG.internal_moist_ah_margin)).mean())

    wd = wdf.set_index("time").resample("1h").mean(numeric_only=True).interpolate(limit_direction="both")
    feat["max_hourly_temp_rise"] = float(wd["in_temp"].diff().max()) if len(wd) > 1 else 0.0
    feat["max_hourly_temp_drop"] = float(wd["in_temp"].diff().min()) if len(wd) > 1 else 0.0
    feat["max_hourly_hum_rise"] = float(wd["in_hum"].diff().max()) if len(wd) > 1 else 0.0
    return feat


def classify_window(feat: Dict[str, float], cfg: Config) -> str:
    moisture_transition = (
        feat["delta_half_in_hum"] >= cfg.moisture_transition_hum_increase
        and feat["delta_half_dAH"] >= cfg.moisture_transition_ah_increase
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
        and abs(feat["delta_half_dT"]) < cfg.heat_dT_half_diff_thresh
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


def feature_brief_text(feat: Dict[str, float], label: str) -> str:
    lines = [
        f"工况: {label}",
        f"mean dT={feat['mean_dT']:.2f}℃",
        f"mean dAH={feat['mean_dAH']:.2f} g/m³",
        f"slope T_in={feat['slope_in_temp']:.2f} ℃/h",
        f"slope AH_in={feat['slope_AH_in']:.2f} g/m³/h",
        f"corr(AH)={feat['corr_AH']:.2f}",
        f"std out_hum={feat['std_out_hum']:.2f}",
    ]
    return "\n".join(lines)


def plot_window(wdf: pd.DataFrame, feat: Dict[str, float], label: str, save_path: str, title_prefix: str = "") -> None:
    fig, ax1 = plt.subplots(figsize=(15, 8))
    ax2 = ax1.twinx()

    ax1.plot(wdf["time"], wdf["in_temp"], color="red", linewidth=1.8, label="内部温度")
    ax1.plot(wdf["time"], wdf["out_temp"], color="red", linestyle="--", linewidth=1.4, label="外部温度")
    ax1.plot(wdf["time"], wdf["in_hum"], color="blue", linewidth=1.8, label="内部湿度")
    ax1.plot(wdf["time"], wdf["out_hum"], color="blue", linestyle="--", linewidth=1.4, label="外部湿度")
    ax1.set_ylabel("温度(℃) / 湿度(%)")
    ax1.set_xlabel("时间")
    ax1.grid(True, linestyle="--", alpha=0.3)

    ax2.plot(wdf["time"], wdf["AH_in"], color="black", linewidth=1.8, label="内部绝对湿度")
    ax2.plot(wdf["time"], wdf["AH_out"], color="black", linestyle="--", linewidth=1.4, label="外部绝对湿度")
    ax2.set_ylabel("绝对湿度 (g/m³)")

    title = f"{title_prefix}\n{wdf['time'].min()} ~ {wdf['time'].max()} | 工况类别：{label}"
    ax1.set_title(title, fontsize=13)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right", fontsize=10)

    ax1.text(
        0.01,
        0.99,
        feature_brief_text(feat, label),
        transform=ax1.transAxes,
        fontsize=10,
        va="top",
        ha="left",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="white", alpha=0.85),
    )

    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close(fig)


def save_window_csv(wdf: pd.DataFrame, save_path: str) -> None:
    wdf.to_csv(save_path, index=False, encoding="utf-8-sig")


def load_excel_sheets(file_path: str) -> List[Tuple[str, pd.DataFrame]]:
    xls = pd.ExcelFile(file_path)
    result: List[Tuple[str, pd.DataFrame]] = []
    for sheet in xls.sheet_names:
        try:
            df = pd.read_excel(file_path, sheet_name=sheet)
        except Exception as exc:
            print(f"[WARN] 读取 sheet 失败：{file_path} | {sheet} | {exc}")
            continue
        if df is not None and len(df) > 0:
            result.append((sheet, df))
    return result


def load_metadata_manifest(metadata_xlsx: str) -> pd.DataFrame:
    if not metadata_xlsx or not os.path.exists(metadata_xlsx):
        return pd.DataFrame()

    df = pd.read_excel(metadata_xlsx)
    df = df.rename(
        columns={
            "设备ID": "device_id_manifest",
            "初始状态": "initial_state",
            "外部湿度": "ext_humidity_level",
            "内部湿度": "in_humidity_level",
            "热源": "heat_source",
            "开孔时间": "hole_time",
            "更新时间": "updated_time",
            "数据文件名": "data_file_name",
            "备注": "notes",
        }
    )

    if "data_file_name" not in df.columns:
        return pd.DataFrame()

    df["data_file_name"] = df["data_file_name"].map(normalize_filename_token)
    df = df[df["data_file_name"] != ""].copy()
    df["device_id_manifest"] = df["device_id_manifest"].map(lambda x: str(int(x)).zfill(12) if pd.notna(x) else "")
    df["hole_time"] = df["hole_time"].map(parse_datetime_or_none)
    df["updated_time"] = df["updated_time"].map(parse_datetime_or_none)
    df = df.drop_duplicates(subset=["data_file_name"], keep="first").reset_index(drop=True)
    return df


def expected_family_from_manifest(meta: Dict[str, Any]) -> str:
    ext_level = str(meta.get("ext_humidity_level", "") or "").strip()
    in_level = str(meta.get("in_humidity_level", "") or "").strip()
    heat = str(meta.get("heat_source", "") or "").strip()
    hole_time = meta.get("hole_time")
    if not is_missing_time(hole_time):
        return "transition_run"
    if ext_level == "高" and in_level == "低" and heat == "无":
        return "ext_high_hum_no_heat"
    if ext_level == "高" and in_level == "低" and heat == "有":
        return "ext_high_hum_with_heat"
    if ext_level == "中" and in_level == "中" and heat == "无":
        return "balanced_no_heat"
    if ext_level == "中" and in_level == "中" and heat == "有":
        return "balanced_with_heat"
    if ext_level == "低" and in_level == "高" and heat == "无":
        return "internal_moist_no_heat"
    if ext_level == "低" and in_level == "高" and heat == "有":
        return "internal_moist_with_heat"
    return "unknown"


def expected_label_candidates(expected_family: str) -> List[str]:
    mapping = {
        "transition_run": ["内部积湿状态切换窗口", "外部高湿驱动工况"],
        "ext_high_hum_no_heat": ["外部高湿驱动工况", "内部积湿状态切换窗口"],
        "ext_high_hum_with_heat": ["热源启动窗口", "热源稳定工况", "冷却窗口", "复杂耦合工况"],
        "balanced_no_heat": ["低信息工况", "复杂耦合工况"],
        "balanced_with_heat": ["热源启动窗口", "热源稳定工况", "冷却窗口", "复杂耦合工况"],
        "internal_moist_no_heat": ["内部积湿工况", "内部积湿状态切换窗口", "低信息工况"],
        "internal_moist_with_heat": ["内部积湿工况", "热源启动窗口", "热源稳定工况"],
    }
    return mapping.get(expected_family, [])


def predicted_group(label: str) -> str:
    if label == "低信息工况":
        return "exclude_low_info"
    if label in {"外部高湿驱动工况", "内部积湿状态切换窗口"}:
        return "candidate_high_info"
    if label == "内部积湿工况":
        return "internal_moisture"
    if label in {"热源稳定工况", "热源启动窗口", "冷却窗口"}:
        return "heat_related"
    return "complex_coupled"


def transition_phase(window_center: pd.Timestamp, hole_time: Optional[pd.Timestamp], near_hours: int) -> str:
    if is_missing_time(hole_time):
        return "no_transition"
    delta_hours = (window_center - hole_time).total_seconds() / 3600.0
    if abs(delta_hours) <= near_hours:
        return "near_transition"
    if delta_hours < -near_hours:
        return "pre_transition"
    return "post_transition"


def process_one_sheet(
    file_path: str,
    sheet_name: str,
    raw_df: pd.DataFrame,
    cfg: Config,
    meta_row: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    file_base = os.path.splitext(os.path.basename(file_path))[0]
    safe_sheet = sheet_name.replace("/", "_").replace("\\", "_").replace(" ", "_")
    sheet_out_dir = os.path.join(cfg.output_dir, f"{file_base}__{safe_sheet}")
    ensure_dir(sheet_out_dir)
    ensure_dir(os.path.join(sheet_out_dir, "images"))
    ensure_dir(os.path.join(sheet_out_dir, "csv"))
    ensure_dir(os.path.join(sheet_out_dir, "features"))

    df = preprocess_df(raw_df)
    windows = sliding_windows(df, cfg)

    meta_row = meta_row or {}
    expected_family = expected_family_from_manifest(meta_row)
    expected_candidates = expected_label_candidates(expected_family)

    summary_rows: List[Dict[str, Any]] = []
    for idx, (w_start, w_end, wdf) in enumerate(windows, start=1):
        feat = extract_features(wdf)
        label = classify_window(feat, cfg)
        window_id = f"W{idx:04d}"
        prefix = f"{file_base}__{safe_sheet}__{window_id}"
        img_path = os.path.join(sheet_out_dir, "images", f"{prefix}.png")
        csv_path = os.path.join(sheet_out_dir, "csv", f"{prefix}.csv")
        json_path = os.path.join(sheet_out_dir, "features", f"{prefix}.json")

        if cfg.export_window_plot:
            title_prefix = f"{file_base} | {sheet_name} | {window_id}"
            plot_window(wdf, feat, label, img_path, title_prefix=title_prefix)

        if cfg.export_window_csv:
            save_window_csv(wdf, csv_path)

        if cfg.export_feature_json:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(feat, f, ensure_ascii=False, indent=2)

        center = w_start + (w_end - w_start) / 2
        hole_time = meta_row.get("hole_time")
        phase = transition_phase(center, hole_time, cfg.transition_near_hours)
        row = {
            "file": file_base,
            "sheet": sheet_name,
            "window_id": window_id,
            "start_time": w_start,
            "end_time": w_end,
            "window_center_time": center,
            "n_samples": len(wdf),
            "class_label": label,
            "predicted_group": predicted_group(label),
            "expected_family": expected_family,
            "expected_candidates": "|".join(expected_candidates),
            "expected_match": int(label in expected_candidates) if expected_candidates else np.nan,
            "transition_phase": phase,
            "device_id_manifest": meta_row.get("device_id_manifest", ""),
            "initial_state": meta_row.get("initial_state", ""),
            "ext_humidity_level": meta_row.get("ext_humidity_level", ""),
            "in_humidity_level": meta_row.get("in_humidity_level", ""),
            "heat_source": meta_row.get("heat_source", ""),
            "hole_time": hole_time,
            "updated_time": meta_row.get("updated_time"),
            "notes": meta_row.get("notes", ""),
            "image_path": img_path if cfg.export_window_plot else "",
            "csv_path": csv_path if cfg.export_window_csv else "",
            **feat,
        }
        summary_rows.append(row)
    return summary_rows


def collect_input_files(cfg: Config, work_dir: str) -> List[str]:
    files: List[str] = []
    if os.path.isdir(cfg.input_dir):
        files.extend(sorted(glob.glob(os.path.join(cfg.input_dir, "*.xlsx")) + glob.glob(os.path.join(cfg.input_dir, "*.xls"))))
    if files:
        return files

    if not cfg.input_zip or not os.path.exists(cfg.input_zip):
        raise FileNotFoundError(f"未找到输入目录或 zip：{cfg.input_dir} | {cfg.input_zip}")

    with zipfile.ZipFile(cfg.input_zip) as zf:
        members = [
            n
            for n in zf.namelist()
            if (n.lower().endswith(".xlsx") or n.lower().endswith(".xls")) and not n.startswith("old_data/")
        ]
        for name in members:
            zf.extract(name, work_dir)
            files.append(os.path.join(work_dir, name))
    return sorted(files)


def build_file_summary(summary_df: pd.DataFrame) -> pd.DataFrame:
    if summary_df.empty:
        return pd.DataFrame()

    rows: List[Dict[str, Any]] = []
    for file_name, group in summary_df.groupby("file", dropna=False):
        class_counts = group["class_label"].value_counts()
        dominant_label = class_counts.idxmax()
        dominant_ratio = float(class_counts.iloc[0] / max(len(group), 1))
        row: Dict[str, Any] = {
            "file": file_name,
            "n_windows": int(len(group)),
            "dominant_label": dominant_label,
            "dominant_ratio": dominant_ratio,
            "expected_family": group["expected_family"].iloc[0],
            "initial_state": group["initial_state"].iloc[0],
            "heat_source": group["heat_source"].iloc[0],
            "ext_humidity_level": group["ext_humidity_level"].iloc[0],
            "in_humidity_level": group["in_humidity_level"].iloc[0],
            "hole_time": group["hole_time"].iloc[0],
            "near_transition_windows": int((group["transition_phase"] == "near_transition").sum()),
            "near_transition_transition_label_ratio": float(
                ((group["transition_phase"] == "near_transition") & (group["class_label"] == "内部积湿状态切换窗口")).mean()
            )
            if (group["transition_phase"] == "near_transition").any()
            else np.nan,
            "expected_match_ratio": float(group["expected_match"].dropna().mean()) if group["expected_match"].notna().any() else np.nan,
        }
        for class_name in CLASS_NAMES:
            row[f"count_{class_name}"] = int(class_counts.get(class_name, 0))
            row[f"ratio_{class_name}"] = float(class_counts.get(class_name, 0) / max(len(group), 1))
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["expected_family", "file"]).reset_index(drop=True)


def build_transition_summary(summary_df: pd.DataFrame) -> pd.DataFrame:
    if summary_df.empty:
        return pd.DataFrame()
    mask = summary_df["transition_phase"] != "no_transition"
    if not mask.any():
        return pd.DataFrame()
    cols = [
        "file",
        "window_id",
        "start_time",
        "end_time",
        "window_center_time",
        "class_label",
        "expected_family",
        "transition_phase",
        "mean_dT",
        "mean_dAH",
        "delta_half_in_hum",
        "delta_half_dAH",
        "slope_in_temp",
        "slope_AH_in",
        "hole_time",
    ]
    return summary_df.loc[mask, cols].sort_values(["file", "window_center_time"]).reset_index(drop=True)


def build_metadata_coverage(files: List[str], metadata_df: pd.DataFrame) -> pd.DataFrame:
    file_tokens = {normalize_filename_token(os.path.basename(path)) for path in files}
    meta_tokens = set(metadata_df["data_file_name"].tolist()) if not metadata_df.empty else set()

    rows: List[Dict[str, Any]] = []
    for token in sorted(file_tokens | meta_tokens):
        rows.append(
            {
                "file_token": token,
                "in_input_files": int(token in file_tokens),
                "in_metadata_manifest": int(token in meta_tokens),
            }
        )
    return pd.DataFrame(rows)


def build_overall_report(summary_df: pd.DataFrame, file_summary_df: pd.DataFrame, coverage_df: pd.DataFrame) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "total_windows": int(len(summary_df)),
        "total_files": int(summary_df["file"].nunique()) if not summary_df.empty else 0,
        "class_distribution": summary_df["class_label"].value_counts().to_dict() if not summary_df.empty else {},
        "predicted_group_distribution": summary_df["predicted_group"].value_counts().to_dict() if not summary_df.empty else {},
        "coverage": {
            "matched_file_count": int(((coverage_df["in_input_files"] == 1) & (coverage_df["in_metadata_manifest"] == 1)).sum()) if not coverage_df.empty else 0,
            "input_only_count": int(((coverage_df["in_input_files"] == 1) & (coverage_df["in_metadata_manifest"] == 0)).sum()) if not coverage_df.empty else 0,
            "metadata_only_count": int(((coverage_df["in_input_files"] == 0) & (coverage_df["in_metadata_manifest"] == 1)).sum()) if not coverage_df.empty else 0,
        },
    }

    if not file_summary_df.empty:
        report["dominant_labels"] = file_summary_df["dominant_label"].value_counts().to_dict()
        report["expected_match_ratio_mean"] = float(file_summary_df["expected_match_ratio"].dropna().mean()) if file_summary_df["expected_match_ratio"].notna().any() else None
        transition_rows = file_summary_df[file_summary_df["near_transition_windows"] > 0]
        if not transition_rows.empty:
            report["transition_files"] = transition_rows[["file", "dominant_label", "near_transition_windows", "near_transition_transition_label_ratio"]].to_dict(orient="records")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Condition classifier v1 for lab data")
    parser.add_argument("--input-dir", default=CFG.input_dir)
    parser.add_argument("--input-zip", default=CFG.input_zip)
    parser.add_argument("--metadata-xlsx", default=CFG.metadata_xlsx)
    parser.add_argument("--output-dir", default=CFG.output_dir)
    parser.add_argument("--window-hours", type=int, default=CFG.window_hours)
    parser.add_argument("--step-hours", type=int, default=CFG.step_hours)
    parser.add_argument("--transition-near-hours", type=int, default=CFG.transition_near_hours)
    parser.add_argument("--export-window-csv", default=str(CFG.export_window_csv).lower())
    parser.add_argument("--export-feature-json", default=str(CFG.export_feature_json).lower())
    parser.add_argument("--export-window-plot", default=str(CFG.export_window_plot).lower())
    return parser.parse_args()


def config_from_args(args: argparse.Namespace) -> Config:
    cfg = Config()
    cfg.input_dir = args.input_dir
    cfg.input_zip = args.input_zip
    cfg.metadata_xlsx = args.metadata_xlsx
    cfg.output_dir = args.output_dir
    cfg.window_hours = args.window_hours
    cfg.step_hours = args.step_hours
    cfg.transition_near_hours = args.transition_near_hours
    cfg.export_window_csv = bool_from_cli(args.export_window_csv)
    cfg.export_feature_json = bool_from_cli(args.export_feature_json)
    cfg.export_window_plot = bool_from_cli(args.export_window_plot)
    return cfg


def main(cfg: Config) -> None:
    ensure_dir(cfg.output_dir)
    ensure_dir(os.path.join(cfg.output_dir, "summary"))

    metadata_df = load_metadata_manifest(cfg.metadata_xlsx)
    metadata_map = {
        row["data_file_name"]: row.to_dict()
        for _, row in metadata_df.iterrows()
    } if not metadata_df.empty else {}

    with tempfile.TemporaryDirectory(prefix="condition_classifier_v1_") as tmp_dir:
        files = collect_input_files(cfg, tmp_dir)
        if not files:
            raise FileNotFoundError("未找到任何可处理的 Excel 文件")

        all_rows: List[Dict[str, Any]] = []
        for file_path in files:
            file_base = normalize_filename_token(os.path.basename(file_path))
            meta_row = metadata_map.get(file_base, {})
            print(f"[INFO] 处理文件：{file_base}")
            sheets = load_excel_sheets(file_path)
            for sheet_name, raw_df in sheets:
                try:
                    rows = process_one_sheet(file_path, sheet_name, raw_df, cfg, meta_row)
                    all_rows.extend(rows)
                    print(f"       -> sheet={sheet_name}, 窗口数={len(rows)}")
                except Exception as exc:
                    print(f"[ERROR] 处理失败：{file_path} | {sheet_name} | {exc}")

    summary_df = pd.DataFrame(all_rows)
    file_summary_df = build_file_summary(summary_df)
    transition_df = build_transition_summary(summary_df)
    coverage_df = build_metadata_coverage(files, metadata_df)
    report = build_overall_report(summary_df, file_summary_df, coverage_df)

    summary_dir = os.path.join(cfg.output_dir, "summary")
    ensure_dir(summary_dir)
    summary_df.to_csv(os.path.join(summary_dir, "window_summary.csv"), index=False, encoding="utf-8-sig")
    file_summary_df.to_csv(os.path.join(summary_dir, "file_summary.csv"), index=False, encoding="utf-8-sig")
    transition_df.to_csv(os.path.join(summary_dir, "transition_windows.csv"), index=False, encoding="utf-8-sig")
    coverage_df.to_csv(os.path.join(summary_dir, "metadata_coverage.csv"), index=False, encoding="utf-8-sig")
    if not metadata_df.empty:
        metadata_df.to_csv(os.path.join(summary_dir, "run_manifest_from_xlsx.csv"), index=False, encoding="utf-8-sig")
    with open(os.path.join(summary_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    print(f"[DONE] 窗口汇总：{os.path.join(summary_dir, 'window_summary.csv')}")
    print(f"[DONE] 文件汇总：{os.path.join(summary_dir, 'file_summary.csv')}")
    print(f"[DONE] 转移分析：{os.path.join(summary_dir, 'transition_windows.csv')}")
    print(f"[DONE] metadata 覆盖：{os.path.join(summary_dir, 'metadata_coverage.csv')}")
    print(f"[DONE] 报告 JSON：{os.path.join(summary_dir, 'report.json')}")


if __name__ == "__main__":
    main(config_from_args(parse_args()))
