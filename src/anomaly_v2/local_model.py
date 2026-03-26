from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


LOCAL_MODEL_NAME = "seal_v4"
LOCAL_MODEL_VERSION = "seal_v4-online.1"
RESAMPLE_RULE = "10min"


def _trapz_compat(y: np.ndarray, dx: float = 1.0) -> float:
    trapezoid = getattr(np, "trapezoid", None)
    if callable(trapezoid):
        return float(trapezoid(y, dx=dx))
    return float(np.trapz(y, dx=dx))


def calc_absolute_humidity(temp_c: pd.Series, rh: pd.Series) -> pd.Series:
    svp = 6.112 * np.exp((17.67 * temp_c) / (temp_c + 243.5))
    avp = svp * rh / 100.0
    return 2.1674 * avp / (273.15 + temp_c) * 100.0


def _safe_corr(a: pd.Series, b: pd.Series) -> float:
    a_num = pd.to_numeric(a, errors="coerce")
    b_num = pd.to_numeric(b, errors="coerce")
    mask = a_num.notna() & b_num.notna()
    if int(mask.sum()) < 3:
        return 0.0
    value = a_num[mask].corr(b_num[mask])
    if pd.isna(value):
        return 0.0
    return float(value)


def _robust_z_positive(values: List[float], current: float) -> float:
    if len(values) < 3:
        return 0.0
    arr = np.asarray([float(v) for v in values if pd.notna(v)], dtype=float)
    if arr.size < 3:
        return 0.0
    median = float(np.median(arr))
    mad = float(np.median(np.abs(arr - median)))
    scale = max(mad * 1.4826, 1e-6)
    return max(0.0, (float(current) - median) / scale)


def _clip01(value: float) -> float:
    return float(max(0.0, min(1.0, value)))


def prepare_points_df(points: List[Dict[str, Any]]) -> pd.DataFrame:
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

    df["AH_in"] = calc_absolute_humidity(df["in_temp"], df["in_hum"])
    df["AH_out"] = calc_absolute_humidity(df["out_temp"], df["out_hum"])
    df["dT"] = df["in_temp"] - df["out_temp"]
    df["dAH"] = df["AH_in"] - df["AH_out"]
    df["headroom_ah"] = df["AH_out"] - df["AH_in"]
    return df.reset_index(drop=True)


def resample_points_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    hourly = (
        df.set_index("time")[["ts", "in_temp", "out_temp", "in_hum", "out_hum", "AH_in", "AH_out", "dT", "dAH", "headroom_ah"]]
        .resample(RESAMPLE_RULE)
        .mean(numeric_only=True)
        .interpolate(limit_direction="both")
        .reset_index()
    )
    if hourly.empty:
        return hourly
    hourly["ts"] = (hourly["time"].astype("int64") // 1_000_000).astype("int64")
    hourly["d_out_h"] = pd.to_numeric(hourly["out_hum"], errors="coerce").diff()
    hourly["d_in_h"] = pd.to_numeric(hourly["in_hum"], errors="coerce").diff()
    hourly["d_ah_in"] = pd.to_numeric(hourly["AH_in"], errors="coerce").diff()
    return hourly


def tail_hours(df: pd.DataFrame, hours: float) -> pd.DataFrame:
    if df.empty:
        return df
    end = df["time"].max()
    start = end - pd.Timedelta(hours=float(hours))
    out = df[df["time"] >= start].copy()
    if out.empty:
        return out
    return out.reset_index(drop=True)


def phase_stats(df: pd.DataFrame) -> Dict[str, float]:
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

    drive = pd.to_numeric(df["d_out_h"], errors="coerce") > 0
    diffs = df["time"].diff().dt.total_seconds().dropna() / 3600.0
    dx_hours = float(diffs.median()) if not diffs.empty else (10.0 / 60.0)

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
    components = [
        0.28 * _clip01(float(stats.get("respond_in_h_pos_ratio", 0.0) or 0.0)),
        0.24 * _clip01(float(stats.get("positive_headroom_ratio", 0.0) or 0.0)),
        0.20 * _clip01(max(0.0, float(stats.get("rh_gain_per_out", 0.0) or 0.0)) / 1.5),
        0.16 * _clip01(max(0.0, float(stats.get("delta_ah_in", 0.0) or 0.0)) / 0.25),
        0.12 * _clip01(max(0.0, float(stats.get("max_step_in_h", 0.0) or 0.0)) / 0.4),
    ]
    return float(sum(components))


def build_transition_windows(df: pd.DataFrame, hours: float = 2.0) -> List[pd.DataFrame]:
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


def classify_transition(df: pd.DataFrame, no_heat_context: bool) -> Dict[str, Any]:
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
    current = features[-1]
    history = features[:-1]
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
    status = "transition_boost_alert" if (strong_shape and score >= 0.30) or (moderate_shape and score >= 0.15) else "transition_weak"
    return {
        "status": status,
        "score": score,
        "latest_delta_in_h": float(current.get("delta_in_h", np.nan)),
        "latest_delta_ah_in": float(current.get("delta_ah_in", np.nan)),
        "latest_headroom_ratio": float(current.get("positive_headroom_ratio", np.nan)),
    }


def classify_no_heat(df: pd.DataFrame) -> Dict[str, Any]:
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

    main_signal = response_signal_score(main_stats)
    long_signal = response_signal_score(long_stats)
    short_signal = response_signal_score(short_stats)
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

    if not onset_positive:
        status = "static_abstain_low_signal"
        score = _clip01(0.15 + 0.35 * main_signal)
    elif late_persistence and breathing_bias:
        status = "static_hard_case_watch"
        score = _clip01(0.42 + 0.20 * max(main_signal, long_signal))
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
        "early_stats": early_stats,
        "late_stats": late_stats,
        "main_stats": main_stats,
        "long_stats": long_stats,
    }


def classify_context(df: pd.DataFrame) -> Dict[str, Any]:
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


def run_local_detection(
    *,
    dev_num: str,
    device_timestamp: int,
    points: List[Dict[str, Any]],
    requested_model_name: str,
) -> Dict[str, Any]:
    started = time.perf_counter()
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

    df = resample_points_df(raw_df)
    span_hours = float((df["time"].iloc[-1] - df["time"].iloc[0]).total_seconds() / 3600.0) if len(df) >= 2 else 0.0
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

    context = classify_context(df)
    no_heat_result = classify_no_heat(df) if context["branch"] == "ext_high_hum_no_heat" else None
    transition_result = classify_transition(df, context["branch"] == "ext_high_hum_no_heat")

    status = "low_info_background"
    risk_level = "low"
    primary_evidence = "background"
    score = 0.08
    is_anomaly = False
    threshold = 0.70

    if transition_result["status"] == "transition_boost_alert":
        status = "transition_boost_alert"
        risk_level = "high"
        primary_evidence = "transition_boost"
        score = max(0.84, float(transition_result["score"]))
        is_anomaly = True
        threshold = 0.72
    elif context["branch"] == "ext_high_hum_no_heat" and no_heat_result:
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
            "no_heat": no_heat_result,
        },
    }
