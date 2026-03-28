from __future__ import annotations

import importlib
import math
import os
import sys
import time
from functools import lru_cache
from typing import Any, Dict, List

import pandas as pd


SALAD_MODEL_NAME = "salad_gru"
SALAD_MODEL_VERSION = "salad_router-2026.03"
SALAD_WINDOW_HOURS = 24
SALAD_SCAN_STEP_HOURS = 1
SALAD_ABNORMAL_LABELS = {"UNSEALED", "MOISTURE_INGRESS", "MOISTURE_ACCUMULATION"}
SALAD_LABEL_SEVERITY = {
    "UNKNOWN": 0,
    "SEALED": 0,
    "UNSEALED": 1,
    "MOISTURE_INGRESS": 2,
    "MOISTURE_ACCUMULATION": 3,
}

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SALAD_DIR = os.path.join(_REPO_ROOT, "SALAD")
_HIGH_HUM_DIR = os.path.join(_SALAD_DIR, "HighHumCond")
_MOIST_DIR = os.path.join(_SALAD_DIR, "InternalMoistureAccumulationModel")
_SEAL_TC_DIR = os.path.join(_SALAD_DIR, "SealSence_TC")
_SEAL_MODEL_DIR = os.path.join(_SEAL_TC_DIR, "model")


def _ensure_salad_paths() -> None:
    for path in (_SALAD_DIR, _HIGH_HUM_DIR, _MOIST_DIR, _SEAL_TC_DIR):
        if path not in sys.path:
            sys.path.insert(0, path)


@lru_cache(maxsize=1)
def _load_salad_modules() -> Dict[str, Any]:
    _ensure_salad_paths()
    return {
        "router": importlib.import_module("salad_model_router"),
        "high_hum": importlib.import_module("high_hum_seal_model"),
        "moisture": importlib.import_module("moisture_detector"),
        "seal_infer": importlib.import_module("seal_infer_industrial"),
    }


@lru_cache(maxsize=1)
def _get_seal_tc_infer() -> Any:
    modules = _load_salad_modules()
    return modules["seal_infer"].SealInferIndustrial(model_dir=_SEAL_MODEL_DIR)


def _default_router_config() -> Any:
    modules = _load_salad_modules()
    return modules["router"].RouterConfig(enable_debug=False)


def infer_median_interval_seconds(df: pd.DataFrame) -> float:
    dt = df["time"].diff().dt.total_seconds().dropna()
    if len(dt) == 0:
        return 60.0
    return float(dt.median())


def pad_head_if_shorter_than_24h(df: pd.DataFrame, window_hours: int = SALAD_WINDOW_HOURS) -> pd.DataFrame:
    if df.empty:
        return df

    first_time = df["time"].min()
    last_time = df["time"].max()
    span = last_time - first_time
    target_span = pd.Timedelta(hours=window_hours)

    if span >= target_span:
        return df

    interval_sec = max(infer_median_interval_seconds(df), 1.0)
    missing_sec = (target_span - span).total_seconds()
    n_pad = int(math.ceil(missing_sec / interval_sec))
    if n_pad <= 0:
        return df

    first_row = df.iloc[0].copy()
    pad_times = [
        first_time - pd.Timedelta(seconds=interval_sec * idx)
        for idx in range(n_pad, 0, -1)
    ]
    pad_df = pd.DataFrame([first_row.to_dict() for _ in range(n_pad)])
    pad_df["time"] = pad_times

    out = pd.concat([pad_df, df], ignore_index=True)
    return out.sort_values("time").reset_index(drop=True)


def points_to_dataframe(points: List[Dict[str, Any]]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for point in points:
        rows.append(
            {
                "time": pd.to_datetime(point.get("ts"), unit="ms", errors="coerce"),
                "in_temp": pd.to_numeric(point.get("in_temp"), errors="coerce"),
                "in_hum": pd.to_numeric(point.get("in_hum"), errors="coerce"),
                "out_temp": pd.to_numeric(point.get("out_temp"), errors="coerce"),
                "out_hum": pd.to_numeric(point.get("out_hum"), errors="coerce"),
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.dropna(subset=["time", "in_temp", "in_hum", "out_temp", "out_hum"]).copy()
    if df.empty:
        return df
    return df.sort_values("time").reset_index(drop=True)


def normalize_salad_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["time", "in_temp", "in_hum", "out_temp", "out_hum"])

    out = df.copy()
    if "time" in out.columns:
        out["time"] = pd.to_datetime(out["time"], errors="coerce")
    elif isinstance(out.index, pd.DatetimeIndex):
        out = out.reset_index().rename(columns={out.index.name or "index": "time"})
        out["time"] = pd.to_datetime(out["time"], errors="coerce")
    else:
        raise ValueError("SALAD 输入缺少 time 列，且索引不是 DatetimeIndex")

    required_cols = ["in_temp", "in_hum", "out_temp", "out_hum"]
    missing = [col for col in required_cols if col not in out.columns]
    if missing:
        raise ValueError(f"SALAD 输入缺少必要字段: {missing}")

    for col in required_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out = out.dropna(subset=["time", *required_cols]).copy()
    if out.empty:
        return pd.DataFrame(columns=["time", *required_cols])

    out = out.sort_values("time").drop_duplicates(subset=["time"], keep="last").reset_index(drop=True)
    return out[["time", *required_cols]]


def prepare_salad_window_df(points: List[Dict[str, Any]]) -> pd.DataFrame:
    df = points_to_dataframe(points)
    if df.empty:
        return df

    end_time = df["time"].max()
    start_time = end_time - pd.Timedelta(hours=SALAD_WINDOW_HOURS)
    df = df[df["time"] >= start_time].copy()
    if df.empty:
        return df
    return pad_head_if_shorter_than_24h(df, window_hours=SALAD_WINDOW_HOURS)


def prepare_salad_window_df_from_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = normalize_salad_dataframe(df)
    if df.empty:
        return df

    end_time = df["time"].max()
    start_time = end_time - pd.Timedelta(hours=SALAD_WINDOW_HOURS)
    df = df[df["time"] >= start_time].copy()
    if df.empty:
        return df
    return pad_head_if_shorter_than_24h(df, window_hours=SALAD_WINDOW_HOURS)


def build_salad_sliding_windows(
    df: pd.DataFrame,
    *,
    window_hours: int = SALAD_WINDOW_HOURS,
    step_hours: int = SALAD_SCAN_STEP_HOURS,
) -> List[Dict[str, Any]]:
    normalized = normalize_salad_dataframe(df)
    if normalized.empty:
        return []

    window_delta = pd.Timedelta(hours=window_hours)
    step_delta = pd.Timedelta(hours=step_hours)
    start_time = normalized["time"].min()
    end_time = normalized["time"].max()
    span = end_time - start_time

    if span < window_delta:
        padded_df = pad_head_if_shorter_than_24h(normalized, window_hours=window_hours)
        return [
            {
                "window_id": "W0001",
                "window_start": padded_df["time"].min(),
                "window_end": padded_df["time"].max(),
                "source_start": start_time,
                "source_end": end_time,
                "padded": True,
                "df": padded_df,
            }
        ]

    windows: List[Dict[str, Any]] = []
    cursor = start_time
    index = 1
    while cursor + window_delta <= end_time:
        window_end = cursor + window_delta
        window_df = normalized[(normalized["time"] >= cursor) & (normalized["time"] <= window_end)].copy()
        if not window_df.empty:
            padded_df = pad_head_if_shorter_than_24h(window_df, window_hours=window_hours)
            windows.append(
                {
                    "window_id": f"W{index:04d}",
                    "window_start": cursor,
                    "window_end": window_end,
                    "source_start": window_df["time"].min(),
                    "source_end": window_df["time"].max(),
                    "padded": len(padded_df) > len(window_df),
                    "df": padded_df,
                }
            )
            index += 1
        cursor += step_delta

    tail_start = end_time - window_delta
    if not windows or abs((windows[-1]["window_start"] - tail_start).total_seconds()) >= 1:
        tail_df = normalized[(normalized["time"] >= tail_start) & (normalized["time"] <= end_time)].copy()
        if not tail_df.empty:
            padded_df = pad_head_if_shorter_than_24h(tail_df, window_hours=window_hours)
            windows.append(
                {
                    "window_id": f"W{index:04d}",
                    "window_start": tail_start,
                    "window_end": end_time,
                    "source_start": tail_df["time"].min(),
                    "source_end": tail_df["time"].max(),
                    "padded": len(padded_df) > len(tail_df),
                    "df": padded_df,
                }
            )

    return windows


def run_salad_router(df_24h: pd.DataFrame) -> Dict[str, Any]:
    modules = _load_salad_modules()
    router = modules["router"]
    cfg = _default_router_config()

    condition, feat, cleaned_df = router.classify_24h_dataframe(df_24h)

    if condition == "LOW_INFO":
        model_name = "NONE"
        label = "UNKNOWN"
        detail = None
    elif condition == "EXT_HIGH_HUM":
        raw_label = modules["high_hum"].predict_seal_state(
            cleaned_df,
            smooth_win=cfg.smooth_win,
            downsample_factor=cfg.downsample_factor,
            sub_size=cfg.sub_size,
            step=cfg.step,
            return_features=False,
        )
        model_name = "HighHumCond"
        label = router.validate_label(raw_label)
        detail = None
    elif condition in ("INTERNAL_MOIST", "MOIST_TRANSITION"):
        moisture_result = modules["moisture"].detect_window_state(
            window_df=cleaned_df,
            time_col=cfg.time_col,
            hum_col=cfg.hum_col,
            hum_threshold=cfg.hum_threshold,
            min_duration_hours=cfg.min_duration_hours,
        )
        model_name = "InternalMoisture"
        label = router.validate_label(moisture_result["state"])
        detail = moisture_result
    else:
        infer = _get_seal_tc_infer()
        seal_result = infer.predict_one_window_df(cleaned_df)
        model_name = "SealSence_TC"
        label = router.validate_label(seal_result["label"])
        detail = seal_result

    return {
        "condition": condition,
        "model": model_name,
        "label": label,
        "feature": feat,
        "detail": detail,
    }


def _run_salad_detection_from_window_df(
    *,
    dev_num: str,
    device_timestamp: int,
    requested_model_name: str,
    window_df: pd.DataFrame,
    started: float,
) -> Dict[str, Any]:
    threshold = 0.70

    if window_df.empty:
        return {
            "request_id": None,
            "is_anomaly": False,
            "anomaly_score": 0.0,
            "threshold": threshold,
            "label": "UNKNOWN",
            "model_name": SALAD_MODEL_NAME,
            "model_version": SALAD_MODEL_VERSION,
            "infer_latency_ms": int((time.perf_counter() - started) * 1000),
            "status": "insufficient_data",
            "method": "SALAD_ROUTER",
            "requested_model_name": requested_model_name,
        }

    router_result = run_salad_router(window_df)
    label = str(router_result.get("label") or "UNKNOWN").upper()
    condition = str(router_result.get("condition") or "UNKNOWN").upper()

    status = "salad_unknown"
    risk_level = "low"
    primary_evidence = "salad_unknown"
    score = 0.0
    is_anomaly = False

    if condition == "LOW_INFO":
        status = "salad_low_info"
        primary_evidence = "salad_condition_gate"
        score = 0.05
    elif label == "SEALED":
        status = "salad_sealed"
        primary_evidence = "salad_router_sealed"
        score = 0.08
    elif label == "UNSEALED":
        status = "salad_unsealed"
        risk_level = "high"
        primary_evidence = "salad_router_unsealed"
        score = 0.92
        is_anomaly = True
    elif label == "MOISTURE_INGRESS":
        status = "salad_moisture_ingress"
        risk_level = "high"
        primary_evidence = "salad_moisture_ingress"
        score = 0.96
        is_anomaly = True
    elif label == "MOISTURE_ACCUMULATION":
        status = "salad_moisture_accumulation"
        risk_level = "high"
        primary_evidence = "salad_moisture_accumulation"
        score = 0.98
        is_anomaly = True

    latency = int((time.perf_counter() - started) * 1000)
    context = {
        "dev_num": dev_num,
        "device_timestamp": device_timestamp,
        "window_hours": SALAD_WINDOW_HOURS,
        "window_points": int(len(window_df)),
        "condition": condition,
        "routed_model": router_result.get("model"),
        "label": label,
        "risk_level": risk_level,
        "primary_evidence": primary_evidence,
        "feature": router_result.get("feature"),
        "detail": router_result.get("detail"),
    }

    return {
        "request_id": None,
        "is_anomaly": is_anomaly,
        "anomaly_score": float(score),
        "threshold": float(threshold),
        "label": label,
        "model_name": SALAD_MODEL_NAME,
        "model_version": SALAD_MODEL_VERSION,
        "infer_latency_ms": latency,
        "status": status,
        "method": "SALAD_ROUTER",
        "requested_model_name": requested_model_name,
        "local_context": context,
    }


def run_salad_detection(
    *,
    dev_num: str,
    device_timestamp: int,
    points: List[Dict[str, Any]],
    requested_model_name: str,
) -> Dict[str, Any]:
    started = time.perf_counter()

    if not points:
        return {
            "request_id": None,
            "is_anomaly": False,
            "anomaly_score": 0.0,
            "threshold": 0.70,
            "label": "UNKNOWN",
            "model_name": SALAD_MODEL_NAME,
            "model_version": SALAD_MODEL_VERSION,
            "infer_latency_ms": int((time.perf_counter() - started) * 1000),
            "status": "insufficient_data",
            "method": "SALAD_ROUTER",
            "requested_model_name": requested_model_name,
        }

    try:
        window_df = prepare_salad_window_df(points)
        return _run_salad_detection_from_window_df(
            dev_num=dev_num,
            device_timestamp=device_timestamp,
            requested_model_name=requested_model_name,
            window_df=window_df,
            started=started,
        )
    except Exception as exc:
        return {
            "request_id": None,
            "is_anomaly": False,
            "anomaly_score": 0.0,
            "threshold": 0.70,
            "label": "UNKNOWN",
            "model_name": SALAD_MODEL_NAME,
            "model_version": SALAD_MODEL_VERSION,
            "infer_latency_ms": int((time.perf_counter() - started) * 1000),
            "status": "salad_error",
            "method": "SALAD_ROUTER",
            "requested_model_name": requested_model_name,
            "local_context": {
                "dev_num": dev_num,
                "device_timestamp": device_timestamp,
                "risk_level": "low",
                "primary_evidence": "salad_runtime_error",
                "error": str(exc),
            },
        }


def run_salad_detection_df(
    *,
    dev_num: str,
    device_timestamp: int,
    df: pd.DataFrame,
    requested_model_name: str,
) -> Dict[str, Any]:
    started = time.perf_counter()
    try:
        window_df = prepare_salad_window_df_from_dataframe(df)
        return _run_salad_detection_from_window_df(
            dev_num=dev_num,
            device_timestamp=device_timestamp,
            requested_model_name=requested_model_name,
            window_df=window_df,
            started=started,
        )
    except Exception as exc:
        return {
            "request_id": None,
            "is_anomaly": False,
            "anomaly_score": 0.0,
            "threshold": 0.70,
            "label": "UNKNOWN",
            "model_name": SALAD_MODEL_NAME,
            "model_version": SALAD_MODEL_VERSION,
            "infer_latency_ms": int((time.perf_counter() - started) * 1000),
            "status": "salad_error",
            "method": "SALAD_ROUTER",
            "requested_model_name": requested_model_name,
            "local_context": {
                "dev_num": dev_num,
                "device_timestamp": device_timestamp,
                "risk_level": "low",
                "primary_evidence": "salad_runtime_error",
                "error": str(exc),
            },
        }


def run_salad_sliding_scan_df(
    *,
    dev_num: str,
    df: pd.DataFrame,
    requested_model_name: str,
    step_hours: int = SALAD_SCAN_STEP_HOURS,
) -> List[Dict[str, Any]]:
    window_defs = build_salad_sliding_windows(df, window_hours=SALAD_WINDOW_HOURS, step_hours=step_hours)
    results: List[Dict[str, Any]] = []
    for item in window_defs:
        window_end_ts = int(pd.Timestamp(item["window_end"]).value // 1_000_000)
        detection = run_salad_detection_df(
            dev_num=dev_num,
            device_timestamp=window_end_ts,
            df=item["df"],
            requested_model_name=requested_model_name,
        )
        local_context = detection.get("local_context") or {}
        results.append(
            {
                "window_id": item["window_id"],
                "window_start_ts": int(pd.Timestamp(item["window_start"]).value // 1_000_000),
                "window_end_ts": window_end_ts,
                "source_start_ts": int(pd.Timestamp(item["source_start"]).value // 1_000_000),
                "source_end_ts": int(pd.Timestamp(item["source_end"]).value // 1_000_000),
                "window_hours": SALAD_WINDOW_HOURS,
                "step_hours": step_hours,
                "padded": bool(item["padded"]),
                "label": str(detection.get("label") or "UNKNOWN").upper(),
                "status": detection.get("status"),
                "is_anomaly": bool(detection.get("is_anomaly", False)),
                "anomaly_score": float(detection.get("anomaly_score", 0.0) or 0.0),
                "threshold": float(detection.get("threshold", 0.0) or 0.0),
                "condition": local_context.get("condition"),
                "routed_model": local_context.get("routed_model"),
                "risk_level": local_context.get("risk_level"),
                "primary_evidence": local_context.get("primary_evidence"),
                "error_detail": local_context.get("error"),
                "raw_result": detection,
            }
        )
    return results
