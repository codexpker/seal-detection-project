import asyncio
import io
import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, List, Literal, Optional
import httpx
import mysql.connector
import pandas as pd
from fastapi import FastAPI, File, Form, Path, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, PlainTextResponse
from pydantic import BaseModel

from src.anomaly_v2 import local_model as local_anomaly_model
from src.anomaly_v2 import pipeline as v2_pipeline
from src.anomaly_v2 import upload_parser as upload_excel_parser


# -----------------------------
# Config
# -----------------------------


def _env(key: str, default: str) -> str:
    return os.getenv(key, default)


DB_CONFIG = {
    "host": _env("MYSQL_HOST", "localhost"),
    "user": _env("MYSQL_USER", "root"),
    "password": _env("MYSQL_PASSWORD", "xpker1234"),
    "database": _env("MYSQL_DATABASE", "bst"),
    "autocommit": True,
}

MODEL_SERVICE_URL = _env("MODEL_SERVICE_URL", "http://localhost:9000")
DEFAULT_MODEL_NAME = _env("DEFAULT_MODEL_NAME", "auto")
BEST_MODEL_NAME = _env("BEST_MODEL_NAME", "gru")
WINDOW_N = int(_env("WINDOW_N", "120"))
WINDOW_T_MINUTES = int(_env("WINDOW_T_MINUTES", "10"))
LOCAL_MODEL_WINDOW_N = int(_env("LOCAL_MODEL_WINDOW_N", "5000"))
LOCAL_MODEL_WINDOW_T_MINUTES = int(_env("LOCAL_MODEL_WINDOW_T_MINUTES", "720"))
HOME_MIN_DISPLAY_SECONDS = int(_env("HOME_MIN_DISPLAY_SECONDS", "60"))
MODEL_TIMEOUT_SECONDS = float(_env("MODEL_TIMEOUT_SECONDS", "0.8"))
MODEL_CONNECT_TIMEOUT_SECONDS = float(_env("MODEL_CONNECT_TIMEOUT_SECONDS", "0.3"))
MODEL_CALL_RETRIES = int(_env("MODEL_CALL_RETRIES", "2"))
MODEL_SERVICE_ENABLED = _env("MODEL_SERVICE_ENABLED", "false").lower() in ("1", "true", "yes", "on")
DEVICE_PROCESS_MIN_INTERVAL_MS = int(_env("DEVICE_PROCESS_MIN_INTERVAL_MS", "3000"))
ANOMALY_V2_ENABLED = _env("ANOMALY_V2_ENABLED", "false").lower() in ("1", "true", "yes", "on")
ANOMALY_V2_SHADOW_MODE = _env("ANOMALY_V2_SHADOW_MODE", "true").lower() in ("1", "true", "yes", "on")
ANOMALY_V2_ALPHA = float(_env("ANOMALY_V2_ALPHA", "0.20"))
ANOMALY_V2_WARN_THRESHOLD = float(_env("ANOMALY_V2_WARN_THRESHOLD", "0.72"))
ANOMALY_V2_RECOVER_THRESHOLD = float(_env("ANOMALY_V2_RECOVER_THRESHOLD", "0.50"))
ANOMALY_V2_MIN_POINTS = int(_env("ANOMALY_V2_MIN_POINTS", "5"))
ANOMALY_V2_EVENT_START_COUNT = int(_env("ANOMALY_V2_EVENT_START_COUNT", "4"))
ANOMALY_V2_EVENT_END_COUNT = int(_env("ANOMALY_V2_EVENT_END_COUNT", "6"))
ANOMALY_V2_EVENT_MIN_DURATION_SEC = int(_env("ANOMALY_V2_EVENT_MIN_DURATION_SEC", "240"))
ANOMALY_V2_EVENT_COOLDOWN_SEC = int(_env("ANOMALY_V2_EVENT_COOLDOWN_SEC", "900"))
LOCAL_MODEL_NAME = local_anomaly_model.LOCAL_MODEL_NAME
LOCAL_MODEL_VERSION = local_anomaly_model.LOCAL_MODEL_VERSION
EXTERNAL_MODEL_NAMES = {"xgboost", "gru"}
ALL_MODEL_NAMES = {"auto", "xgboost", "gru", LOCAL_MODEL_NAME}


# -----------------------------
# Generic response
# -----------------------------


class ApiResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: Any = None


def ok(data: Any) -> Dict[str, Any]:
    return {"code": 0, "message": "ok", "data": data}


def fail(code: int, message: str) -> Dict[str, Any]:
    return {"code": code, "message": message, "data": None}


STATUS_DISPLAY_MAP: Dict[str, Dict[str, str]] = {
    "transition_boost_alert": {
        "status_label": "转移增强告警",
        "status_short": "转移告警",
        "risk_level": "high",
        "tone": "danger",
    },
    "static_dynamic_supported_alert": {
        "status_label": "高湿响应支持告警",
        "status_short": "高湿支持",
        "risk_level": "high",
        "tone": "warning",
    },
    "static_dynamic_support_alert": {
        "status_label": "高湿响应支持告警",
        "status_short": "高湿支持",
        "risk_level": "high",
        "tone": "warning",
    },
    "static_hard_case_watch": {
        "status_label": "难例观察",
        "status_short": "观察",
        "risk_level": "watch",
        "tone": "warning",
    },
    "static_abstain_low_signal": {
        "status_label": "低信号保守通过",
        "status_short": "低信号",
        "risk_level": "low",
        "tone": "muted",
    },
    "heat_related_background": {
        "status_label": "热相关背景",
        "status_short": "热相关",
        "risk_level": "low",
        "tone": "muted",
    },
    "low_info_background": {
        "status_label": "低信息背景",
        "status_short": "低信息",
        "risk_level": "low",
        "tone": "muted",
    },
    "insufficient_data": {
        "status_label": "数据不足",
        "status_short": "不足",
        "risk_level": "low",
        "tone": "muted",
    },
    "insufficient_history_local": {
        "status_label": "历史窗口不足",
        "status_short": "窗口不足",
        "risk_level": "low",
        "tone": "muted",
    },
    "ongoing": {
        "status_label": "异常事件",
        "status_short": "异常",
        "risk_level": "high",
        "tone": "danger",
    },
    "no_detection": {
        "status_label": "无检测结果",
        "status_short": "无检测",
        "risk_level": "low",
        "tone": "muted",
    },
}


def describe_detection_status(status: Optional[str]) -> Dict[str, str]:
    key = str(status or "").strip() or "unknown"
    meta = STATUS_DISPLAY_MAP.get(key)
    if meta:
        return {"status": key, **meta}
    fallback_short = key.replace("_", " ")[:16] if key else "未知"
    return {
        "status": key,
        "status_label": key.replace("_", " ") if key else "未知状态",
        "status_short": fallback_short,
        "risk_level": "low",
        "tone": "muted",
    }


def enrich_mark_payload(item: Dict[str, Any]) -> Dict[str, Any]:
    enriched = dict(item)
    enriched.update(describe_detection_status(item.get("status")))
    if enriched.get("display_mark_ts") and not enriched.get("first_detected_ts"):
        enriched["first_detected_ts"] = enriched["display_mark_ts"]
    if enriched.get("display_mark_ts") and not enriched.get("last_detected_ts"):
        enriched["last_detected_ts"] = enriched["display_mark_ts"]
    return enriched


# -----------------------------
# Pydantic models
# -----------------------------


class ModelSelectRequest(BaseModel):
    model_name: Literal["auto", "xgboost", "gru", "seal_v4"] = "auto"


class DeviceModelSelectRequest(BaseModel):
    model_name: Literal["auto", "xgboost", "gru", "seal_v4"] = "auto"


class ReplayRequest(BaseModel):
    dev_num: str
    start_ts: int
    end_ts: int
    model_name: Literal["auto", "xgboost", "gru", "seal_v4"] = "auto"


class ModelRollbackRequest(BaseModel):
    model_name: Literal["xgboost", "gru", "auto", "seal_v4"]
    target_version: str


class AnomalyV2ControlRequest(BaseModel):
    enabled: Optional[bool] = None
    shadow_mode: Optional[bool] = None
    alpha: Optional[float] = None
    warn_threshold: Optional[float] = None
    recover_threshold: Optional[float] = None
    min_points: Optional[int] = None
    event_start_count: Optional[int] = None
    event_end_count: Optional[int] = None
    event_min_duration_sec: Optional[int] = None
    event_cooldown_sec: Optional[int] = None
    sim_enabled: Optional[bool] = None
    sim_weight: Optional[float] = None
    sim_k: Optional[int] = None
    debug_trace: Optional[bool] = None


class AnomalyV2ReviewLabelRequest(BaseModel):
    event_id: str
    label: Literal["true", "false", "uncertain"]
    reviewer: str = ""
    note: str = ""


# -----------------------------
# Runtime state
# -----------------------------


@dataclass
class HomeState:
    current_dev_num: Optional[str] = None
    current_since_ts: int = 0


class EventBus:
    def __init__(self) -> None:
        self._home_subscribers: List[asyncio.Queue] = []
        self._diag_subscribers: List[asyncio.Queue] = []

    async def publish_home(self, event_type: str, payload: Dict[str, Any]) -> None:
        for q in list(self._home_subscribers):
            await q.put((event_type, payload))

    async def publish_diag(self, event_type: str, payload: Dict[str, Any]) -> None:
        for q in list(self._diag_subscribers):
            await q.put((event_type, payload))

    def subscribe_home(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._home_subscribers.append(q)
        return q

    def subscribe_diag(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._diag_subscribers.append(q)
        return q

    def unsubscribe_home(self, q: asyncio.Queue) -> None:
        if q in self._home_subscribers:
            self._home_subscribers.remove(q)

    def unsubscribe_diag(self, q: asyncio.Queue) -> None:
        if q in self._diag_subscribers:
            self._diag_subscribers.remove(q)


event_bus = EventBus()
home_state = HomeState()
pending_latest_map: Dict[str, Dict[str, Any]] = {}
DEFAULT_MODEL = BEST_MODEL_NAME or DEFAULT_MODEL_NAME
if not MODEL_SERVICE_ENABLED and DEFAULT_MODEL in EXTERNAL_MODEL_NAMES:
    DEFAULT_MODEL = LOCAL_MODEL_NAME
RUNTIME_METRICS: Dict[str, int] = {
    "process_total": 0,
    "process_ok": 0,
    "process_insufficient": 0,
    "process_model_timeout": 0,
    "process_model_error": 0,
    "process_model_skipped": 0,
    "process_skipped_interval": 0,
    "model_call_total": 0,
    "model_call_retry": 0,
    "queue_enqueued": 0,
    "queue_merged": 0,
    "queue_processed": 0,
    "anomaly_v2_runs": 0,
    "anomaly_v2_events": 0,
    "anomaly_v2_shadow_events": 0,
    "anomaly_v2_errors": 0,
}
REPLAY_TASKS: Dict[str, Dict[str, Any]] = {}
# 记录“服务端处理时间(ms)”，不要使用设备上报时间做节流（设备时间可能是秒级）
DEVICE_LAST_PROCESS_AT_MS: Dict[str, int] = {}
PENDING_PROCESS_TS_BY_DEV: Dict[str, int] = {}
QUEUE_LOCK = asyncio.Lock()
QUEUE_WORKER_STARTED = False
MODEL_VERSION_CATALOG: Dict[str, List[str]] = {
    "xgboost": ["xgboost-2026.01", "xgboost-2026.02"],
    "gru": ["gru-2026.01", "gru-2026.02"],
    LOCAL_MODEL_NAME: [LOCAL_MODEL_VERSION],
    "auto": ["auto"],
}
ACTIVE_MODEL_VERSION: Dict[str, str] = {
    "xgboost": "xgboost-2026.02",
    "gru": "gru-2026.02",
    LOCAL_MODEL_NAME: LOCAL_MODEL_VERSION,
    "auto": "auto",
}
ANOMALY_V2_STATE_BY_DEV: Dict[str, Dict[str, Any]] = {}
ANOMALY_V2_REF_WINDOWS_BY_DEV: Dict[str, List[Dict[str, float]]] = {}
ANOMALY_V2_LAST_DEBUG_BY_DEV: Dict[str, Dict[str, Any]] = {}
ANOMALY_V2_RUNTIME: Dict[str, Any] = {
    "enabled": ANOMALY_V2_ENABLED,
    "shadow_mode": ANOMALY_V2_SHADOW_MODE,
    "alpha": ANOMALY_V2_ALPHA,
    "warn_threshold": ANOMALY_V2_WARN_THRESHOLD,
    "recover_threshold": ANOMALY_V2_RECOVER_THRESHOLD,
    "min_points": ANOMALY_V2_MIN_POINTS,
    "event_start_count": ANOMALY_V2_EVENT_START_COUNT,
    "event_end_count": ANOMALY_V2_EVENT_END_COUNT,
    "event_min_duration_sec": ANOMALY_V2_EVENT_MIN_DURATION_SEC,
    "event_cooldown_sec": ANOMALY_V2_EVENT_COOLDOWN_SEC,
    "sim_enabled": False,
    "sim_weight": 0.3,
    "sim_k": 5,
    "debug_trace": False,
}
DB_BOOTSTRAP_OK = False
DB_BOOTSTRAP_ERROR = ""


def get_effective_model_for_device(dev_num: str) -> str:
    return resolve_effective_model_name(get_requested_model_for_device(dev_num))


def normalize_model_name(model_name: Optional[str]) -> str:
    value = str(model_name or "").strip().lower()
    if not value:
        return "auto"
    return value if value in ALL_MODEL_NAMES else "auto"


def get_requested_model_for_device(dev_num: str) -> str:
    rows = query_all(
        "SELECT model_name FROM device_model_preference WHERE dev_num=%s LIMIT 1",
        (dev_num,),
    )
    if rows and rows[0].get("model_name"):
        return normalize_model_name(rows[0]["model_name"])
    return normalize_model_name(DEFAULT_MODEL)


def resolve_effective_model_name(model_name: Optional[str]) -> str:
    requested = normalize_model_name(model_name)
    if requested == "auto":
        if MODEL_SERVICE_ENABLED and normalize_model_name(BEST_MODEL_NAME) in EXTERNAL_MODEL_NAMES:
            return normalize_model_name(BEST_MODEL_NAME)
        return LOCAL_MODEL_NAME
    if requested in EXTERNAL_MODEL_NAMES:
        return requested if MODEL_SERVICE_ENABLED else LOCAL_MODEL_NAME
    if requested == LOCAL_MODEL_NAME:
        return LOCAL_MODEL_NAME
    return LOCAL_MODEL_NAME


def is_local_model(model_name: Optional[str]) -> bool:
    return resolve_effective_model_name(model_name) == LOCAL_MODEL_NAME


# -----------------------------
# DB helpers
# -----------------------------


def get_conn():
    return mysql.connector.connect(**DB_CONFIG)


def bootstrap_schema() -> None:
    ddl_list = [
        (
            "CREATE TABLE IF NOT EXISTS detection_result_log ("
            "id BIGINT AUTO_INCREMENT PRIMARY KEY,"
            "request_id VARCHAR(64) NULL,"
            "dev_num VARCHAR(50) NOT NULL,"
            "device_timestamp BIGINT NOT NULL,"
            "window_start_ts BIGINT NOT NULL,"
            "window_end_ts BIGINT NOT NULL,"
            "window_size INT NOT NULL,"
            "model_name VARCHAR(32) NOT NULL,"
            "model_version VARCHAR(64) NULL,"
            "is_anomaly TINYINT NOT NULL DEFAULT 0,"
            "anomaly_score DOUBLE NULL,"
            "threshold DOUBLE NULL,"
            "infer_latency_ms INT NULL,"
            "status VARCHAR(32) NOT NULL DEFAULT 'ok',"
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
            "INDEX idx_detection_dev_ts (dev_num, device_timestamp),"
            "INDEX idx_detection_created (created_at),"
            "INDEX idx_detection_request_id (request_id)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        ),
        (
            "CREATE TABLE IF NOT EXISTS anomaly_event ("
            "id BIGINT AUTO_INCREMENT PRIMARY KEY,"
            "dev_num VARCHAR(50) NOT NULL,"
            "event_hour_bucket BIGINT NOT NULL,"
            "first_detected_ts BIGINT NOT NULL,"
            "last_detected_ts BIGINT NOT NULL,"
            "display_mark_ts BIGINT NOT NULL,"
            "status VARCHAR(16) NOT NULL DEFAULT 'ongoing',"
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
            "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,"
            "UNIQUE KEY uk_dev_hour (dev_num, event_hour_bucket),"
            "INDEX idx_anomaly_display_ts (display_mark_ts),"
            "INDEX idx_anomaly_dev_ts (dev_num, display_mark_ts)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        ),
        (
            "CREATE TABLE IF NOT EXISTS fault_archive ("
            "id BIGINT AUTO_INCREMENT PRIMARY KEY,"
            "request_id VARCHAR(64) NULL,"
            "dev_num VARCHAR(50) NOT NULL,"
            "device_timestamp BIGINT NOT NULL,"
            "event_hour_bucket BIGINT NOT NULL,"
            "is_anomaly TINYINT NOT NULL DEFAULT 0,"
            "anomaly_score DOUBLE NULL,"
            "threshold DOUBLE NULL,"
            "model_name VARCHAR(32) NOT NULL,"
            "model_version VARCHAR(64) NULL,"
            "method VARCHAR(64) NOT NULL DEFAULT 'N_AND_T',"
            "anomaly_points_json JSON NULL,"
            "diagnosis_status VARCHAR(32) NOT NULL DEFAULT 'ok',"
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
            "INDEX idx_fault_dev_ts (dev_num, device_timestamp),"
            "INDEX idx_fault_created (created_at),"
            "INDEX idx_fault_is_anomaly (is_anomaly)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        ),
        (
            "CREATE TABLE IF NOT EXISTS device_model_preference ("
            "id BIGINT AUTO_INCREMENT PRIMARY KEY,"
            "dev_num VARCHAR(50) NOT NULL,"
            "model_name VARCHAR(32) NOT NULL,"
            "updated_at BIGINT NOT NULL,"
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
            "updated_at_ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,"
            "UNIQUE KEY uk_dev_num (dev_num),"
            "INDEX idx_model_name (model_name)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        ),
        (
            "CREATE TABLE IF NOT EXISTS anomaly_score_v2 ("
            "id BIGINT AUTO_INCREMENT PRIMARY KEY,"
            "dev_num VARCHAR(50) NOT NULL,"
            "device_timestamp BIGINT NOT NULL,"
            "score_raw DOUBLE NOT NULL,"
            "score_smooth DOUBLE NOT NULL,"
            "feature_json JSON NULL,"
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
            "INDEX idx_v2_score_dev_ts (dev_num, device_timestamp),"
            "INDEX idx_v2_score_created (created_at)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        ),
        (
            "CREATE TABLE IF NOT EXISTS anomaly_event_v2 ("
            "id BIGINT AUTO_INCREMENT PRIMARY KEY,"
            "event_id VARCHAR(128) NOT NULL,"
            "dev_num VARCHAR(50) NOT NULL,"
            "start_ts BIGINT NOT NULL,"
            "end_ts BIGINT NOT NULL,"
            "peak_score DOUBLE NOT NULL,"
            "duration_sec INT NOT NULL,"
            "event_level VARCHAR(16) NOT NULL,"
            "decision_reason VARCHAR(128) NOT NULL,"
            "shadow_mode TINYINT NOT NULL DEFAULT 1,"
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
            "UNIQUE KEY uk_v2_event_id (event_id),"
            "INDEX idx_v2_event_dev_ts (dev_num, start_ts),"
            "INDEX idx_v2_event_created (created_at)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        ),
        (
            "CREATE TABLE IF NOT EXISTS anomaly_review_label_v2 ("
            "id BIGINT AUTO_INCREMENT PRIMARY KEY,"
            "event_id VARCHAR(128) NOT NULL,"
            "label VARCHAR(16) NOT NULL,"
            "reviewer VARCHAR(64) NULL,"
            "note VARCHAR(500) NULL,"
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
            "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,"
            "UNIQUE KEY uk_review_event_id (event_id),"
            "INDEX idx_review_label (label),"
            "INDEX idx_review_updated (updated_at)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        ),
    ]

    for ddl in ddl_list:
        execute(ddl)


def query_all(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    conn = get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        conn.close()


def execute(sql: str, params: tuple = ()) -> None:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


# -----------------------------
# Core service functions
# -----------------------------


def now_ms() -> int:
    return int(time.time() * 1000)


def hour_bucket(ts_ms: int) -> int:
    return (ts_ms // 3_600_000) * 3_600_000


def fetch_window(dev_num: str, end_ts: int, n: int, t_minutes: int = 0) -> List[Dict[str, Any]]:
    """取最近 N 条数据；若 t_minutes>0 则额外加时间约束，否则只按条数取。"""
    if t_minutes > 0:
        start_ts = end_ts - t_minutes * 60_000
        sql = (
            "SELECT device_timestamp AS ts, in_temp, out_temp, in_hum, out_hum "
            "FROM device_monitoring_data "
            "WHERE dev_num = %s AND device_timestamp BETWEEN %s AND %s "
            "ORDER BY device_timestamp DESC LIMIT %s"
        )
        rows = query_all(sql, (dev_num, start_ts, end_ts, n))
    else:
        sql = (
            "SELECT device_timestamp AS ts, in_temp, out_temp, in_hum, out_hum "
            "FROM device_monitoring_data "
            "WHERE dev_num = %s AND device_timestamp <= %s "
            "ORDER BY device_timestamp DESC LIMIT %s"
        )
        rows = query_all(sql, (dev_num, end_ts, n))
    rows.reverse()
    return rows


def fetch_points_for_model(dev_num: str, end_ts: int, model_name: str) -> List[Dict[str, Any]]:
    effective_model = resolve_effective_model_name(model_name)
    if effective_model == LOCAL_MODEL_NAME:
        return fetch_window(dev_num, end_ts, LOCAL_MODEL_WINDOW_N, LOCAL_MODEL_WINDOW_T_MINUTES)
    return fetch_window(dev_num, end_ts, WINDOW_N, WINDOW_T_MINUTES)


def slugify_upload_token(value: str, fallback: str = "upload") -> str:
    token = re.sub(r"[^0-9a-zA-Z_]+", "_", str(value or "").strip())
    token = re.sub(r"_+", "_", token).strip("_")
    return token or fallback


def build_upload_dev_num(file_name: str, dev_num_hint: str = "") -> str:
    base = slugify_upload_token(dev_num_hint or os.path.splitext(os.path.basename(file_name))[0], "upload")
    suffix = str(now_ms())[-8:]
    prefix = f"upload_{base}"
    max_prefix_len = max(1, 50 - len(suffix) - 1)
    prefix = prefix[:max_prefix_len]
    return f"{prefix}_{suffix}"


def load_uploaded_excel_points(file_bytes: bytes) -> pd.DataFrame:
    excel = pd.ExcelFile(io.BytesIO(file_bytes))
    last_error: Optional[Exception] = None
    for sheet_name in excel.sheet_names:
        try:
            raw_df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=sheet_name)
            df = upload_excel_parser.preprocess_excel_df(raw_df)
            if not df.empty:
                return df
        except Exception as err:
            last_error = err
            continue
    if last_error:
        raise ValueError(f"无法解析上传的 Excel：{last_error}")
    raise ValueError("上传文件中未找到可用工作表")


def dataframe_to_series(df: pd.DataFrame) -> List[Dict[str, Any]]:
    series: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        series.append(
            {
                "ts": int(pd.Timestamp(row["time"]).value // 1_000_000),
                "in_temp": float(row["in_temp"]),
                "out_temp": float(row["out_temp"]),
                "in_hum": float(row["in_hum"]),
                "out_hum": float(row["out_hum"]),
            }
        )
    return series


async def predict_points_window(
    dev_num: str,
    points: List[Dict[str, Any]],
    requested_model_name: str,
    device_timestamp: int,
) -> Dict[str, Any]:
    effective_model_name = resolve_effective_model_name(requested_model_name)
    if effective_model_name == LOCAL_MODEL_NAME:
        return call_local_model(dev_num, points, requested_model_name, device_timestamp)
    return await call_model_service(dev_num, points, effective_model_name, device_timestamp)


def compress_marks_by_hour(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    latest_by_bucket: Dict[int, Dict[str, Any]] = {}
    for item in items:
        bucket = int(item["event_hour_bucket"])
        prev = latest_by_bucket.get(bucket)
        if prev is None or int(item["display_mark_ts"]) >= int(prev["display_mark_ts"]):
            latest_by_bucket[bucket] = item
    return sorted((enrich_mark_payload(x) for x in latest_by_bucket.values()), key=lambda x: int(x["display_mark_ts"]))


async def analyze_uploaded_points(
    *,
    df: pd.DataFrame,
    dev_num: str,
    requested_model_name: str,
    process_mode: str,
    file_name: str,
) -> Dict[str, Any]:
    series = dataframe_to_series(df)
    prepared = local_anomaly_model.prepare_points_df(series)
    resampled = local_anomaly_model.resample_points_df(prepared)

    if process_mode == "latest":
        scan_timestamps = [int(series[-1]["ts"])]
    else:
        scan_timestamps = [int(ts) for ts in resampled["ts"].dropna().astype("int64").tolist()]
        if not scan_timestamps:
            scan_timestamps = [int(series[-1]["ts"])]

    detections: List[Dict[str, Any]] = []
    marks: List[Dict[str, Any]] = []
    point_idx = 0
    prefix_points: List[Dict[str, Any]] = []
    for ts in scan_timestamps:
        while point_idx < len(series) and int(series[point_idx]["ts"]) <= ts:
            prefix_points.append(series[point_idx])
            point_idx += 1
        if not prefix_points:
            continue

        result = await predict_points_window(dev_num, prefix_points, requested_model_name, ts)
        detection_item = {
            "device_timestamp": ts,
            "is_anomaly": bool(result.get("is_anomaly", False)),
            "anomaly_score": float(result.get("anomaly_score", 0.0) or 0.0),
            "threshold": float(result.get("threshold", 0.0) or 0.0),
            "model_name": result.get("model_name"),
            "model_version": result.get("model_version"),
            "status": result.get("status"),
            "method": result.get("method", "UPLOAD_SCAN"),
            "risk_level": ((result.get("local_context") or {}).get("risk_level")),
            "primary_evidence": ((result.get("local_context") or {}).get("primary_evidence")),
        }
        detection_item.update(describe_detection_status(detection_item.get("status")))
        detections.append(detection_item)
        if detection_item["is_anomaly"]:
            marks.append(
                enrich_mark_payload(
                {
                    "dev_num": dev_num,
                    "display_mark_ts": ts,
                    "first_detected_ts": ts,
                    "last_detected_ts": ts,
                    "event_hour_bucket": hour_bucket(ts),
                    "status": detection_item["status"] or "ongoing",
                    "anomaly_score": detection_item["anomaly_score"],
                    "threshold": detection_item["threshold"],
                    "risk_level": detection_item.get("risk_level"),
                    "primary_evidence": detection_item.get("primary_evidence"),
                }
                )
            )

    latest = detections[-1] if detections else {
        "device_timestamp": int(series[-1]["ts"]),
        "is_anomaly": False,
        "anomaly_score": 0.0,
        "threshold": 0.0,
        "model_name": resolve_effective_model_name(requested_model_name),
        "model_version": None,
        "status": "no_detection",
        "method": "UPLOAD_SCAN",
    }

    start_ts = int(series[0]["ts"])
    end_ts = int(series[-1]["ts"])
    anomaly_count = sum(1 for item in detections if item["is_anomaly"])
    detail = {
        "dev_num": dev_num,
        "range": {
            "hours": round((end_ts - start_ts) / 3_600_000, 3),
            "start_ts": start_ts,
            "end_ts": end_ts,
            "latest_ts": end_ts,
            "anchor_ts": end_ts,
            "points_limit": None,
            "source": "upload_xlsx",
            "file_name": file_name,
            "scan_points": len(scan_timestamps),
        },
        "series": series,
        "marks": compress_marks_by_hour(marks),
        "latest_detection": latest,
    }
    return {
        "dev_num": dev_num,
        "detail": detail,
        "latest_detection": latest,
        "summary": {
            "row_count": int(len(series)),
            "scan_count": int(len(detections)),
            "anomaly_count": int(anomaly_count),
            "mark_count": int(len(detail["marks"])),
            "file_name": file_name,
            "process_mode": process_mode,
        },
    }
 
 
def fetch_device_latest(dev_num: str, limit: int = 500) -> List[Dict[str, Any]]:
    """取设备最近 limit 条数据，有多少展示多少。"""
    sql = (
        "SELECT device_timestamp AS ts, in_temp, out_temp, in_hum, out_hum "
        "FROM device_monitoring_data "
        "WHERE dev_num = %s "
        "ORDER BY device_timestamp DESC LIMIT %s"
    )
    rows = query_all(sql, (dev_num, limit))
    rows.reverse()
    return rows


async def call_model_service(dev_num: str, points: List[Dict[str, Any]], model_name: str, device_timestamp: int) -> Dict[str, Any]:
    req_id = str(uuid.uuid4())
    payload = {
        "request_id": req_id,
        "dev_num": dev_num,
        "model_name": model_name,
        "model_version": None,
        "window": {
            "start_ts": points[0]["ts"] if points else device_timestamp,
            "end_ts": points[-1]["ts"] if points else device_timestamp,
            "size": len(points),
            "points": points,
        },
        "meta": {"window_rule": "N_AND_T", "n": WINDOW_N, "t_minutes": WINDOW_T_MINUTES},
    }

    timeout = httpx.Timeout(MODEL_TIMEOUT_SECONDS, connect=MODEL_CONNECT_TIMEOUT_SECONDS)
    last_error: Optional[Exception] = None
    for attempt in range(1, MODEL_CALL_RETRIES + 1):
        RUNTIME_METRICS["model_call_total"] += 1
        if attempt > 1:
            RUNTIME_METRICS["model_call_retry"] += 1
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(f"{MODEL_SERVICE_URL}/model/predict", json=payload)
                resp.raise_for_status()
                data = resp.json()
            return {
                "request_id": req_id,
                "is_anomaly": bool(data.get("is_anomaly", False)),
                "anomaly_score": float(data.get("score", 0.0)),
                "threshold": float(data.get("threshold", 0.0)),
                "model_name": data.get("model_name", model_name),
                "model_version": data.get("model_version"),
                "infer_latency_ms": int(data.get("latency_ms", 0)),
                "status": "ok",
            }
        except Exception as err:
            last_error = err
            if attempt < MODEL_CALL_RETRIES:
                await asyncio.sleep(0.05 * attempt)

    if last_error:
        raise last_error
    raise RuntimeError("model service call failed")


def call_local_model(dev_num: str, points: List[Dict[str, Any]], requested_model_name: str, device_timestamp: int) -> Dict[str, Any]:
    result = local_anomaly_model.run_local_detection(
        dev_num=dev_num,
        device_timestamp=device_timestamp,
        points=points,
        requested_model_name=requested_model_name,
    )
    result["request_id"] = str(uuid.uuid4())
    return result


def save_detection_log(dev_num: str, device_timestamp: int, points: List[Dict[str, Any]], result: Dict[str, Any]) -> None:
    if points:
        w_start, w_end = points[0]["ts"], points[-1]["ts"]
    else:
        w_start = w_end = device_timestamp
    sql = (
        "INSERT INTO detection_result_log "
        "(request_id, dev_num, device_timestamp, window_start_ts, window_end_ts, window_size, model_name, model_version, "
        "is_anomaly, anomaly_score, threshold, infer_latency_ms, status) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
    )
    execute(
        sql,
        (
            result.get("request_id"),
            dev_num,
            device_timestamp,
            w_start,
            w_end,
            len(points),
            result.get("model_name"),
            result.get("model_version"),
            1 if result.get("is_anomaly") else 0,
            result.get("anomaly_score"),
            result.get("threshold"),
            result.get("infer_latency_ms"),
            result.get("status", "ok"),
        ),
    )


def upsert_anomaly_event(dev_num: str, detected_ts: int) -> Optional[Dict[str, Any]]:
    bucket = hour_bucket(detected_ts)
    sql = (
        "INSERT INTO anomaly_event (dev_num, event_hour_bucket, first_detected_ts, last_detected_ts, display_mark_ts, status) "
        "VALUES (%s,%s,%s,%s,%s,'ongoing') "
        "ON DUPLICATE KEY UPDATE last_detected_ts=VALUES(last_detected_ts), updated_at=CURRENT_TIMESTAMP"
    )
    execute(sql, (dev_num, bucket, detected_ts, detected_ts, detected_ts))

    row = query_all(
        "SELECT dev_num, event_hour_bucket, first_detected_ts, last_detected_ts, display_mark_ts, status "
        "FROM anomaly_event WHERE dev_num=%s AND event_hour_bucket=%s LIMIT 1",
        (dev_num, bucket),
    )
    return row[0] if row else None


def latest_detection(dev_num: str) -> Optional[Dict[str, Any]]:
    rows = query_all(
        "SELECT is_anomaly, anomaly_score, threshold, model_name, model_version, infer_latency_ms, status "
        "FROM detection_result_log WHERE dev_num=%s ORDER BY device_timestamp DESC LIMIT 1",
        (dev_num,),
    )
    if not rows:
        return None
    item = rows[0]
    item["is_anomaly"] = bool(item["is_anomaly"])
    item.update(describe_detection_status(item.get("status")))
    return item


def get_device_model_info(dev_num: str) -> Dict[str, str]:
    rows = query_all(
        "SELECT model_name FROM device_model_preference WHERE dev_num=%s LIMIT 1",
        (dev_num,),
    )
    if rows and rows[0].get("model_name"):
        requested = normalize_model_name(rows[0]["model_name"])
        source = "device"
    else:
        requested = normalize_model_name(DEFAULT_MODEL)
        source = "default"
    effective = resolve_effective_model_name(requested)
    if effective != requested:
        source = f"{source}_fallback_local"
    return {"model_name": requested, "effective_model_name": effective, "source": source}


def get_device_model(dev_num: str) -> str:
    return get_device_model_info(dev_num)["effective_model_name"]


def set_device_model(dev_num: str, model_name: str) -> None:
    normalized = normalize_model_name(model_name)
    execute(
        "INSERT INTO device_model_preference (dev_num, model_name, updated_at) "
        "VALUES (%s,%s,%s) "
        "ON DUPLICATE KEY UPDATE model_name=VALUES(model_name), updated_at=VALUES(updated_at)",
        (dev_num, normalized, now_ms()),
    )


def save_fault_archive(payload: Dict[str, Any]) -> None:
    detection = payload.get("detection") or {}
    window = payload.get("window") or {}
    point = payload.get("point") or {}
    anomaly_points = [
        {
            "ts": point.get("ts", payload.get("device_timestamp")),
            "in_temp": point.get("in_temp"),
            "out_temp": point.get("out_temp"),
            "in_hum": point.get("in_hum"),
            "out_hum": point.get("out_hum"),
        }
    ]
    execute(
        "INSERT INTO fault_archive "
        "(request_id, dev_num, device_timestamp, event_hour_bucket, is_anomaly, anomaly_score, threshold, "
        "model_name, model_version, method, anomaly_points_json, diagnosis_status) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            payload.get("request_id"),
            payload.get("dev_num"),
            payload.get("device_timestamp"),
            hour_bucket(payload.get("device_timestamp", 0)),
            1 if detection.get("is_anomaly") else 0,
            detection.get("anomaly_score"),
            detection.get("threshold"),
            detection.get("model_name"),
            detection.get("model_version"),
            payload.get("method", "N_AND_T"),
            json.dumps(anomaly_points, ensure_ascii=False),
            detection.get("status", "ok"),
        ),
    )


async def enqueue_device_process(dev_num: str, device_timestamp: int) -> Dict[str, Any]:
    async with QUEUE_LOCK:
        existed = dev_num in PENDING_PROCESS_TS_BY_DEV
        if existed:
            PENDING_PROCESS_TS_BY_DEV[dev_num] = max(PENDING_PROCESS_TS_BY_DEV[dev_num], device_timestamp)
            RUNTIME_METRICS["queue_merged"] += 1
            return {"queued": True, "merged": True}

        PENDING_PROCESS_TS_BY_DEV[dev_num] = device_timestamp
        RUNTIME_METRICS["queue_enqueued"] += 1
        return {"queued": True, "merged": False}


async def process_queue_worker() -> None:
    while True:
        item: Optional[tuple[str, int]] = None
        async with QUEUE_LOCK:
            if PENDING_PROCESS_TS_BY_DEV:
                dev_num = next(iter(PENDING_PROCESS_TS_BY_DEV.keys()))
                ts = PENDING_PROCESS_TS_BY_DEV.pop(dev_num)
                item = (dev_num, ts)

        if not item:
            await asyncio.sleep(0.05)
            continue

        dev_num, device_ts = item
        now_ts = now_ms()
        last_processed_at = DEVICE_LAST_PROCESS_AT_MS.get(dev_num, 0)
        # 按“处理发生时间”限流，避免设备时间戳精度/回拨导致长期跳过处理
        if now_ts - last_processed_at < DEVICE_PROCESS_MIN_INTERVAL_MS:
            # 不丢弃该设备最新事件：回写到待处理队列，等待最小间隔后再处理
            async with QUEUE_LOCK:
                if dev_num in PENDING_PROCESS_TS_BY_DEV:
                    PENDING_PROCESS_TS_BY_DEV[dev_num] = max(PENDING_PROCESS_TS_BY_DEV[dev_num], device_ts)
                else:
                    PENDING_PROCESS_TS_BY_DEV[dev_num] = device_ts
            RUNTIME_METRICS["process_skipped_interval"] += 1
            await asyncio.sleep(0.05)
            continue

        try:
            await process_latest_for_device(dev_num, device_ts)
            DEVICE_LAST_PROCESS_AT_MS[dev_num] = now_ms()
            RUNTIME_METRICS["queue_processed"] += 1
        except Exception:
            # 保持worker不中断
            continue


async def process_latest_for_device(
    dev_num: str,
    device_timestamp: int,
    model_name_override: Optional[str] = None,
) -> Dict[str, Any]:
    RUNTIME_METRICS["process_total"] += 1
    requested_model_name = normalize_model_name(model_name_override or get_device_model_info(dev_num)["model_name"])
    model_name = resolve_effective_model_name(requested_model_name)
    points = fetch_points_for_model(dev_num, device_timestamp, requested_model_name)

    if len(points) < 1:
        result = {
            "request_id": str(uuid.uuid4()),
            "is_anomaly": False,
            "anomaly_score": 0.0,
            "threshold": 0.0,
            "model_name": LOCAL_MODEL_NAME if is_local_model(requested_model_name) else model_name,
            "model_version": None,
            "infer_latency_ms": 0,
            "status": "insufficient_data",
            "requested_model_name": requested_model_name,
            "method": "LOCAL_SEAL_V4" if is_local_model(requested_model_name) else "N_AND_T",
        }
        RUNTIME_METRICS["process_insufficient"] += 1
    else:
        if is_local_model(requested_model_name):
            result = call_local_model(dev_num, points, requested_model_name, device_timestamp)
            RUNTIME_METRICS["process_ok"] += 1
        else:
            try:
                result = await call_model_service(dev_num, points, model_name, device_timestamp)
                RUNTIME_METRICS["process_ok"] += 1
            except httpx.TimeoutException:
                if not MODEL_SERVICE_ENABLED:
                    result = call_local_model(dev_num, points, requested_model_name, device_timestamp)
                    RUNTIME_METRICS["process_model_skipped"] += 1
                else:
                    result = {
                        "request_id": str(uuid.uuid4()),
                        "is_anomaly": False,
                        "anomaly_score": 0.0,
                        "threshold": 0.0,
                        "model_name": model_name,
                        "model_version": None,
                        "infer_latency_ms": int(MODEL_TIMEOUT_SECONDS * 1000),
                        "status": "model_timeout",
                        "requested_model_name": requested_model_name,
                        "method": "N_AND_T",
                    }
                    RUNTIME_METRICS["process_model_timeout"] += 1
            except Exception:
                if not MODEL_SERVICE_ENABLED:
                    result = call_local_model(dev_num, points, requested_model_name, device_timestamp)
                    RUNTIME_METRICS["process_model_skipped"] += 1
                else:
                    result = {
                        "request_id": str(uuid.uuid4()),
                        "is_anomaly": False,
                        "anomaly_score": 0.0,
                        "threshold": 0.0,
                        "model_name": model_name,
                        "model_version": None,
                        "infer_latency_ms": 0,
                        "status": "model_error",
                        "requested_model_name": requested_model_name,
                        "method": "N_AND_T",
                    }
                    RUNTIME_METRICS["process_model_error"] += 1

    save_detection_log(dev_num, device_timestamp, points, result)

    mark = None
    if result["is_anomaly"]:
        mark = upsert_anomaly_event(dev_num, device_timestamp)

    latest_point = points[-1] if points else {"ts": device_timestamp}
    event_payload = {
        "request_id": result["request_id"],
        "dev_num": dev_num,
        "device_timestamp": device_timestamp,
        "window": {
            "start_ts": points[0]["ts"] if points else device_timestamp,
            "end_ts": points[-1]["ts"] if points else device_timestamp,
            "size": len(points),
        },
        "method": result.get("method", "N_AND_T"),
        "point": latest_point,
        "anomaly_points": [latest_point],
        "detection": result,
        "mark": mark,
    }

    save_fault_archive(event_payload)

    anomaly_v2_payload: Optional[Dict[str, Any]] = None
    v2_enabled = bool(ANOMALY_V2_RUNTIME.get("enabled", ANOMALY_V2_ENABLED))
    if v2_enabled:
        try:
            # v2 特征不强依赖 T 窗口；当主流程窗口过短时，回补“按条数”历史样本，避免长期无法触发 v2
            v2_points = points
            v2_min_points = int(ANOMALY_V2_RUNTIME.get("min_points", ANOMALY_V2_MIN_POINTS))
            if len(v2_points) < v2_min_points:
                v2_points = fetch_window(dev_num, device_timestamp, max(WINDOW_N, v2_min_points), 0)
            anomaly_v2_payload = run_anomaly_v2(dev_num, device_timestamp, v2_points)
        except Exception:
            RUNTIME_METRICS["anomaly_v2_errors"] += 1

    if anomaly_v2_payload:
        event_payload["anomaly_v2"] = {
            "enabled": anomaly_v2_payload.get("enabled", False),
            "shadow_mode": anomaly_v2_payload.get("shadow_mode", True),
            "score_raw": anomaly_v2_payload.get("score_raw"),
            "score_smooth": anomaly_v2_payload.get("score_smooth"),
            "event": anomaly_v2_payload.get("event"),
            "debug": anomaly_v2_payload.get("debug"),
        }
    else:
        event_payload["anomaly_v2"] = None

    pending_latest_map[dev_num] = event_payload

    # 诊断流（完整事件）
    await event_bus.publish_diag("diagnosis_result", event_payload)

    # 首页右侧设备轮播流：每条处理结果都推送，不受首页大图最短展示时长限制
    await event_bus.publish_home(
        "ticker_event",
        {
            "request_id": result["request_id"],
            "dev_num": dev_num,
            "device_timestamp": device_timestamp,
            "is_anomaly": bool(result.get("is_anomaly")),
            "model_name": result.get("model_name"),
            "status": result.get("status"),
            "anomaly_score": result.get("anomaly_score"),
        },
    )

    # 首页大图展示调度（受 HOME_MIN_DISPLAY_SECONDS 策略控制）
    await schedule_home_event(event_payload)
    return event_payload


async def schedule_home_event(payload: Dict[str, Any]) -> None:
    current_ts = now_ms()
    dev_num = payload["dev_num"]

    if home_state.current_dev_num is None:
        home_state.current_dev_num = dev_num
        home_state.current_since_ts = current_ts
        await event_bus.publish_home("device_switch", {"from_dev": None, "to_dev": dev_num, "switch_ts": current_ts})
        await event_bus.publish_home("device_update", payload)
        if payload.get("mark"):
            await event_bus.publish_home("anomaly_mark", payload["mark"])
        pending_latest_map.pop(dev_num, None)
        return

    elapsed_seconds = (current_ts - home_state.current_since_ts) // 1000
    if elapsed_seconds < HOME_MIN_DISPLAY_SECONDS:
        if dev_num == home_state.current_dev_num:
            await event_bus.publish_home("device_update", payload)
            if payload.get("mark"):
                await event_bus.publish_home("anomaly_mark", payload["mark"])
        return

    if pending_latest_map:
        latest_item = max(pending_latest_map.values(), key=lambda x: x.get("device_timestamp", 0))
        to_dev = latest_item["dev_num"]
        if to_dev != home_state.current_dev_num:
            old_dev = home_state.current_dev_num
            home_state.current_dev_num = to_dev
            home_state.current_since_ts = current_ts
            await event_bus.publish_home("device_switch", {"from_dev": old_dev, "to_dev": to_dev, "switch_ts": current_ts})
        await event_bus.publish_home("device_update", latest_item)
        if latest_item.get("mark"):
            await event_bus.publish_home("anomaly_mark", latest_item["mark"])
        pending_latest_map.pop(to_dev, None)


def save_anomaly_v2_score(
    dev_num: str,
    device_timestamp: int,
    score_raw: float,
    score_smooth: float,
    features: Dict[str, Any],
) -> None:
    execute(
        "INSERT INTO anomaly_score_v2 "
        "(dev_num, device_timestamp, score_raw, score_smooth, feature_json) "
        "VALUES (%s,%s,%s,%s,%s)",
        (
            dev_num,
            device_timestamp,
            float(score_raw),
            float(score_smooth),
            json.dumps(features, ensure_ascii=False),
        ),
    )


def save_anomaly_v2_event(event: Dict[str, Any]) -> None:
    execute(
        "INSERT INTO anomaly_event_v2 "
        "(event_id, dev_num, start_ts, end_ts, peak_score, duration_sec, event_level, decision_reason, shadow_mode) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON DUPLICATE KEY UPDATE "
        "end_ts=VALUES(end_ts), "
        "peak_score=VALUES(peak_score), "
        "duration_sec=VALUES(duration_sec), "
        "event_level=VALUES(event_level), "
        "decision_reason=VALUES(decision_reason), "
        "shadow_mode=VALUES(shadow_mode)",
        (
            event.get("event_id"),
            event.get("dev_num"),
            event.get("start_ts"),
            event.get("end_ts"),
            event.get("peak_score"),
            event.get("duration_sec"),
            event.get("event_level"),
            event.get("decision_reason"),
            1 if event.get("shadow_mode") else 0,
        ),
    )


def run_anomaly_v2(dev_num: str, device_timestamp: int, points: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    result = v2_pipeline.run_v2_pipeline(
        dev_num=dev_num,
        device_timestamp=device_timestamp,
        points=points,
        runtime=ANOMALY_V2_RUNTIME,
        state_by_dev=ANOMALY_V2_STATE_BY_DEV,
        refs_by_dev=ANOMALY_V2_REF_WINDOWS_BY_DEV,
        save_score=save_anomaly_v2_score,
        save_event=save_anomaly_v2_event,
        default_enabled=ANOMALY_V2_ENABLED,
        default_min_points=ANOMALY_V2_MIN_POINTS,
        default_alpha=ANOMALY_V2_ALPHA,
        default_warn_threshold=ANOMALY_V2_WARN_THRESHOLD,
        default_recover_threshold=ANOMALY_V2_RECOVER_THRESHOLD,
        default_event_start_count=ANOMALY_V2_EVENT_START_COUNT,
        default_event_end_count=ANOMALY_V2_EVENT_END_COUNT,
        default_event_min_duration_sec=ANOMALY_V2_EVENT_MIN_DURATION_SEC,
        default_event_cooldown_sec=ANOMALY_V2_EVENT_COOLDOWN_SEC,
        default_shadow_mode=ANOMALY_V2_SHADOW_MODE,
    )
    if not result:
        return None

    RUNTIME_METRICS["anomaly_v2_runs"] += 1
    event_record = result.get("event")
    if event_record:
        RUNTIME_METRICS["anomaly_v2_events"] += 1
        if bool(result.get("shadow_mode")):
            RUNTIME_METRICS["anomaly_v2_shadow_events"] += 1

    debug_payload = result.get("debug")
    if isinstance(debug_payload, dict):
        ANOMALY_V2_LAST_DEBUG_BY_DEV[dev_num] = debug_payload
    return result


# -----------------------------
# FastAPI app
# -----------------------------


app = FastAPI(title="Seal Detection Backend API", version="1.0.0")


@app.on_event("startup")
async def startup_worker() -> None:
    global QUEUE_WORKER_STARTED, DB_BOOTSTRAP_OK, DB_BOOTSTRAP_ERROR
    try:
        bootstrap_schema()
        DB_BOOTSTRAP_OK = True
        DB_BOOTSTRAP_ERROR = ""
    except Exception as err:
        DB_BOOTSTRAP_OK = False
        DB_BOOTSTRAP_ERROR = str(err)
    if not QUEUE_WORKER_STARTED:
        asyncio.create_task(process_queue_worker())
        QUEUE_WORKER_STARTED = True


@app.get("/api/health")
def health():
    return ok({
        "status": "up",
        "db_bootstrap_ok": DB_BOOTSTRAP_OK,
        "db_bootstrap_error": DB_BOOTSTRAP_ERROR,
    })


@app.get("/api/home/current")
def home_current():
    dev_num = home_state.current_dev_num
    if not dev_num:
        return fail(1002, "no current device")

    # 若当前展示设备已无最近检测记录（历史残留/重启后状态脏数据），自动回退到最新检测设备
    latest_row = query_all(
        "SELECT dev_num FROM detection_result_log ORDER BY device_timestamp DESC LIMIT 1"
    )
    if latest_row:
        latest_dev = latest_row[0].get("dev_num")
        has_current = query_all(
            "SELECT 1 AS ok FROM detection_result_log WHERE dev_num=%s LIMIT 1",
            (dev_num,),
        )
        if not has_current and latest_dev:
            dev_num = str(latest_dev)
            home_state.current_dev_num = dev_num
            home_state.current_since_ts = now_ms()

    points = fetch_device_latest(dev_num, WINDOW_N)
    marks = query_all(
        "SELECT dev_num, event_hour_bucket, first_detected_ts, last_detected_ts, display_mark_ts, status FROM anomaly_event "
        "WHERE dev_num=%s ORDER BY display_mark_ts DESC LIMIT 100",
        (dev_num,),
    )
    marks = [enrich_mark_payload(item) for item in marks]
    detection = latest_detection(dev_num)
    current_ts = now_ms()
    remain = max(0, HOME_MIN_DISPLAY_SECONDS - int((current_ts - home_state.current_since_ts) / 1000))
    data = {
        "dev_num": dev_num,
        "display_since_ts": home_state.current_since_ts,
        "display_remain_seconds": remain,
        "window": {
            "start_ts": points[0]["ts"] if points else current_ts,
            "end_ts": points[-1]["ts"] if points else current_ts,
            "size": len(points),
        },
        "series": points,
        "marks": marks,
        "detection": detection,
    }
    return ok(data)


@app.get("/api/home/device-ticker")
def home_device_ticker(limit: int = Query(50, ge=1, le=200)):
    # 设备轮播应体现“最新上报事件流”，而非“每设备一条最新值”
    rows = query_all(
        "SELECT dev_num, device_timestamp, is_anomaly, model_name, status, anomaly_score "
        "FROM detection_result_log "
        "ORDER BY device_timestamp DESC LIMIT %s",
        (limit,),
    )
    for row in rows:
        row["is_anomaly"] = bool(row.get("is_anomaly"))
    return ok({"limit": limit, "items": rows})


async def sse_event_generator(queue: asyncio.Queue) -> AsyncGenerator[str, None]:
    try:
        while True:
            try:
                event_type, payload = await asyncio.wait_for(queue.get(), timeout=15)
                yield f"event: {event_type}\n"
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            except asyncio.TimeoutError:
                yield "event: heartbeat\n"
                yield f"data: {{\"ts\": {now_ms()}}}\n\n"
    finally:
        return


@app.get("/api/home/stream")
async def home_stream():
    q = event_bus.subscribe_home()

    async def gen():
        try:
            async for chunk in sse_event_generator(q):
                yield chunk
        finally:
            event_bus.unsubscribe_home(q)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/device/detail/{dev_num}")
def device_curve(
    dev_num: str = Path(...),
    hours: int = Query(48, ge=1, le=8760),
    end_ts: Optional[int] = Query(None),
    points_limit: Optional[int] = Query(None, ge=10, le=1000),
):
    latest_row = query_all(
        "SELECT MAX(device_timestamp) AS latest_ts FROM device_monitoring_data WHERE dev_num=%s",
        (dev_num,),
    )
    latest_ts = int(latest_row[0]["latest_ts"]) if latest_row and latest_row[0].get("latest_ts") else 0

    anchor_ts = int(end_ts) if end_ts else max(now_ms(), latest_ts)

    if points_limit:
        rows_desc = query_all(
            "SELECT device_timestamp AS ts, in_temp, out_temp, in_hum, out_hum "
            "FROM device_monitoring_data WHERE dev_num=%s AND device_timestamp <= %s "
            "ORDER BY device_timestamp DESC LIMIT %s",
            (dev_num, anchor_ts, points_limit),
        )
        series = list(reversed(rows_desc))
        if not series:
            return fail(1002, f"no data for dev_num={dev_num}")
        start_ts = int(series[0]["ts"])
        end_range_ts = int(series[-1]["ts"])
    else:
        start_ts = anchor_ts - hours * 3600 * 1000
        end_range_ts = anchor_ts
        series = query_all(
            "SELECT device_timestamp AS ts, in_temp, out_temp, in_hum, out_hum "
            "FROM device_monitoring_data WHERE dev_num=%s AND device_timestamp BETWEEN %s AND %s "
            "ORDER BY device_timestamp",
            (dev_num, start_ts, end_range_ts),
        )
        if not series:
            return fail(1002, f"no data for dev_num={dev_num}")

    marks = query_all(
        "SELECT dev_num, event_hour_bucket, first_detected_ts, last_detected_ts, display_mark_ts, status FROM anomaly_event "
        "WHERE dev_num=%s AND display_mark_ts BETWEEN %s AND %s ORDER BY display_mark_ts",
        (dev_num, start_ts, end_range_ts),
    )
    marks = [enrich_mark_payload(item) for item in marks]
    return ok(
        {
            "dev_num": dev_num,
            "range": {
                "hours": hours,
                "start_ts": start_ts,
                "end_ts": end_range_ts,
                "latest_ts": latest_ts,
                "anchor_ts": anchor_ts,
                "points_limit": points_limit,
            },
            "series": series,
            "marks": marks,
            "latest_detection": latest_detection(dev_num),
        }
    )


@app.get("/api/device/{dev_num}/anomalies")
def device_anomalies(
    dev_num: str = Path(...),
    hours: int = Query(48, ge=1, le=8760),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
):
    end_ts = now_ms()
    start_ts = end_ts - hours * 3600 * 1000
    offset = (page - 1) * page_size

    total_rows = query_all(
        "SELECT COUNT(*) AS cnt FROM anomaly_event WHERE dev_num=%s AND display_mark_ts BETWEEN %s AND %s",
        (dev_num, start_ts, end_ts),
    )
    total = int(total_rows[0]["cnt"]) if total_rows else 0

    items = query_all(
        "SELECT dev_num, event_hour_bucket, first_detected_ts, last_detected_ts, display_mark_ts, status "
        "FROM anomaly_event WHERE dev_num=%s AND display_mark_ts BETWEEN %s AND %s "
        "ORDER BY display_mark_ts DESC LIMIT %s OFFSET %s",
        (dev_num, start_ts, end_ts, page_size, offset),
    )
    items = [enrich_mark_payload(item) for item in items]
    return ok({"dev_num": dev_num, "page": page, "page_size": page_size, "total": total, "items": items})


@app.get("/api/device/stats")
def device_stats():
    rows = query_all("SELECT COUNT(DISTINCT dev_num) AS device_count FROM device_monitoring_data")
    device_count = int(rows[0]["device_count"]) if rows else 0
    return ok({"device_count": device_count})


@app.get("/api/device/ids")
def device_ids(
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=1000),
    sort_by: str = Query("count", pattern="^(count|dev_num)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    dev_num: str = Query("", max_length=50),
):
    offset = (page - 1) * page_size
    dev_num = dev_num.strip()
    where_clause = "WHERE dev_num LIKE %s" if dev_num else ""
    where_params: List[Any] = [f"%{dev_num}%"] if dev_num else []

    total_rows = query_all(
        f"SELECT COUNT(*) AS cnt FROM (SELECT dev_num FROM device_monitoring_data {where_clause} GROUP BY dev_num) t",
        tuple(where_params),
    )
    total = int(total_rows[0]["cnt"]) if total_rows else 0

    order_field = "record_count" if sort_by == "count" else "dev_num"
    order_dir = "ASC" if sort_order == "asc" else "DESC"

    items = query_all(
        "SELECT dev_num, COUNT(*) AS record_count FROM device_monitoring_data "
        f"{where_clause} "
        "GROUP BY dev_num "
        f"ORDER BY {order_field} {order_dir}, dev_num ASC LIMIT %s OFFSET %s",
        tuple(where_params + [page_size, offset]),
    )
    return ok(
        {
            "page": page,
            "page_size": page_size,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "total": total,
            "items": items,
        }
    )


@app.get("/api/admin/recent")
def admin_recent(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: str = Query("all", pattern="^(all|anomaly|normal)$"),
    sort_by: str = Query("time", pattern="^(time|score)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    dev_num: str = Query("", max_length=50),
):
    offset = (page - 1) * page_size

    conditions: List[str] = []
    params: List[Any] = []

    if status == "anomaly":
        conditions.append("is_anomaly=1")
    elif status == "normal":
        conditions.append("is_anomaly=0")

    dev_num = dev_num.strip()
    if dev_num:
        conditions.append("dev_num LIKE %s")
        params.append(f"%{dev_num}%")

    where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""

    total_rows = query_all(
        f"SELECT COUNT(*) AS cnt FROM detection_result_log{where_clause}",
        tuple(params),
    )
    total = int(total_rows[0]["cnt"]) if total_rows else 0

    order_field = "device_timestamp" if sort_by == "time" else "anomaly_score"
    order_dir = "ASC" if sort_order == "asc" else "DESC"

    items = query_all(
        "SELECT request_id, dev_num, device_timestamp, is_anomaly, anomaly_score, threshold, "
        "model_name, model_version, infer_latency_ms, status, created_at "
        f"FROM detection_result_log{where_clause} ORDER BY {order_field} {order_dir}, device_timestamp DESC LIMIT %s OFFSET %s",
        tuple(params + [page_size, offset]),
    )
    for item in items:
        item["is_anomaly"] = bool(item["is_anomaly"])
    return ok(
        {
            "page": page,
            "page_size": page_size,
            "status": status,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "dev_num": dev_num,
            "total": total,
            "items": items,
        }
    )


@app.get("/api/fault/devices")
def fault_devices(
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=1000),
):
    offset = (page - 1) * page_size
    total_rows = query_all(
        "SELECT COUNT(*) AS cnt FROM ("
        "  SELECT dev_num FROM fault_archive WHERE is_anomaly=1 GROUP BY dev_num"
        ") t"
    )
    total = int(total_rows[0]["cnt"]) if total_rows else 0

    items = query_all(
        "SELECT dev_num, MAX(device_timestamp) AS latest_anomaly_ts, COUNT(*) AS anomaly_count "
        "FROM fault_archive WHERE is_anomaly=1 GROUP BY dev_num "
        "ORDER BY latest_anomaly_ts DESC LIMIT %s OFFSET %s",
        (page_size, offset),
    )
    return ok({"page": page, "page_size": page_size, "total": total, "items": items})


@app.get("/api/fault/recent")
def fault_recent(
    limit: int = Query(100, ge=1, le=1000),
    dev_num: str = Query("", max_length=50),
    hours: int = Query(0, ge=0, le=8760),
):
    conditions: List[str] = []
    params: List[Any] = []

    dev_num = dev_num.strip()
    if dev_num:
        conditions.append("dev_num LIKE %s")
        params.append(f"%{dev_num}%")

    if hours > 0:
        end_ts = now_ms()
        start_ts = end_ts - hours * 3600 * 1000
        conditions.append("device_timestamp BETWEEN %s AND %s")
        params.extend([start_ts, end_ts])

    where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""

    items = query_all(
        "SELECT request_id, dev_num, device_timestamp, event_hour_bucket, is_anomaly, anomaly_score, threshold, "
        "model_name, model_version, method, anomaly_points_json, diagnosis_status, created_at "
        f"FROM fault_archive{where_clause} ORDER BY device_timestamp DESC LIMIT %s",
        tuple(params + [limit]),
    )
    for item in items:
        item["is_anomaly"] = bool(item["is_anomaly"])
    return ok({"limit": limit, "dev_num": dev_num, "hours": hours, "items": items})


@app.get("/api/diagnosis/faults/recent")
def diagnosis_faults_recent(limit: int = Query(50, ge=1, le=500)):
    items = query_all(
        "SELECT request_id, dev_num, device_timestamp, event_hour_bucket, is_anomaly, anomaly_score, threshold, "
        "model_name, model_version, method, anomaly_points_json, diagnosis_status, created_at "
        "FROM fault_archive ORDER BY device_timestamp DESC LIMIT %s",
        (limit,),
    )
    for item in items:
        item["is_anomaly"] = bool(item["is_anomaly"])
    return ok({"limit": limit, "items": items})


@app.get("/api/diagnosis/stream")
async def diagnosis_stream():
    q = event_bus.subscribe_diag()

    async def gen():
        try:
            async for chunk in sse_event_generator(q):
                yield chunk
        finally:
            event_bus.unsubscribe_diag(q)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/diagnosis/recent")
def diagnosis_recent(limit: int = Query(200, ge=1, le=1000)):
    items = query_all(
        "SELECT request_id, dev_num, device_timestamp, window_start_ts, window_end_ts, window_size, "
        "is_anomaly, anomaly_score, threshold, model_name, model_version, infer_latency_ms, status, created_at "
        "FROM detection_result_log ORDER BY device_timestamp DESC LIMIT %s",
        (limit,),
    )
    for i in items:
        i["is_anomaly"] = bool(i["is_anomaly"])
    return ok({"limit": limit, "items": items})


@app.get("/api/diagnosis/device/{dev_num}")
def diagnosis_by_device(
    dev_num: str = Path(...),
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(1000, ge=1, le=5000),
):
    end_ts = now_ms()
    start_ts = end_ts - hours * 3600 * 1000
    items = query_all(
        "SELECT request_id, dev_num, device_timestamp, window_start_ts, window_end_ts, window_size, "
        "is_anomaly, anomaly_score, threshold, model_name, model_version, infer_latency_ms, status, created_at "
        "FROM detection_result_log WHERE dev_num=%s AND device_timestamp BETWEEN %s AND %s "
        "ORDER BY device_timestamp DESC LIMIT %s",
        (dev_num, start_ts, end_ts, limit),
    )
    for i in items:
        i["is_anomaly"] = bool(i["is_anomaly"])
    return ok({"dev_num": dev_num, "range": {"hours": hours, "start_ts": start_ts, "end_ts": end_ts}, "items": items})


def _run_replay_task(task_id: str, req: ReplayRequest) -> None:
    REPLAY_TASKS[task_id]["status"] = "running"
    try:
        rows = query_all(
            "SELECT device_timestamp FROM device_monitoring_data "
            "WHERE dev_num=%s AND device_timestamp BETWEEN %s AND %s "
            "ORDER BY device_timestamp ASC",
            (req.dev_num, req.start_ts, req.end_ts),
        )
        total = len(rows)
        REPLAY_TASKS[task_id]["total"] = total

        for idx, row in enumerate(rows, start=1):
            device_ts = int(row["device_timestamp"])
            try:
                override = normalize_model_name(req.model_name)
                asyncio.run(process_latest_for_device(req.dev_num, device_ts, model_name_override=override))
                REPLAY_TASKS[task_id]["processed"] = idx
            except Exception as err:
                REPLAY_TASKS[task_id]["failed"] += 1
                REPLAY_TASKS[task_id]["last_error"] = str(err)

        REPLAY_TASKS[task_id]["status"] = "completed"
        REPLAY_TASKS[task_id]["finished_at"] = now_ms()
    except Exception as err:
        REPLAY_TASKS[task_id]["status"] = "failed"
        REPLAY_TASKS[task_id]["last_error"] = str(err)
        REPLAY_TASKS[task_id]["finished_at"] = now_ms()


@app.post("/api/diagnosis/replay")
def diagnosis_replay(req: ReplayRequest):
    task_id = f"replay_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    REPLAY_TASKS[task_id] = {
        "task_id": task_id,
        "status": "pending",
        "dev_num": req.dev_num,
        "start_ts": req.start_ts,
        "end_ts": req.end_ts,
        "model_name": req.model_name,
        "total": 0,
        "processed": 0,
        "failed": 0,
        "last_error": "",
        "created_at": now_ms(),
        "finished_at": None,
    }
    threading.Thread(target=_run_replay_task, args=(task_id, req), daemon=True).start()
    return ok({"task_id": task_id, "accepted": True})


@app.get("/api/diagnosis/replay/compare")
def diagnosis_replay_compare(
    dev_num: str = Query("", max_length=50),
    start_ts: int = Query(..., ge=0),
    end_ts: int = Query(..., ge=0),
):
    if end_ts <= start_ts:
        return fail(1005, "end_ts must be greater than start_ts")

    conditions = ["device_timestamp BETWEEN %s AND %s"]
    params: List[Any] = [start_ts, end_ts]

    if dev_num.strip():
        conditions.append("dev_num = %s")
        params.append(dev_num.strip())

    where_clause_detection = " AND ".join(conditions)

    v1_anomaly_rows = query_all(
        "SELECT COUNT(*) AS cnt FROM detection_result_log WHERE " + where_clause_detection + " AND is_anomaly=1",
        tuple(params),
    )
    v1_point_anomaly_count = int(v1_anomaly_rows[0]["cnt"]) if v1_anomaly_rows else 0

    v1_event_conditions = ["display_mark_ts BETWEEN %s AND %s"]
    v1_event_params: List[Any] = [start_ts, end_ts]
    if dev_num.strip():
        v1_event_conditions.append("dev_num = %s")
        v1_event_params.append(dev_num.strip())

    v1_event_rows = query_all(
        "SELECT COUNT(*) AS cnt FROM anomaly_event WHERE " + " AND ".join(v1_event_conditions),
        tuple(v1_event_params),
    )
    v1_event_count = int(v1_event_rows[0]["cnt"]) if v1_event_rows else 0

    v2_event_conditions = ["start_ts <= %s", "end_ts >= %s"]
    v2_event_params: List[Any] = [end_ts, start_ts]
    if dev_num.strip():
        v2_event_conditions.append("dev_num = %s")
        v2_event_params.append(dev_num.strip())

    v2_event_rows = query_all(
        "SELECT COUNT(*) AS cnt FROM anomaly_event_v2 WHERE " + " AND ".join(v2_event_conditions),
        tuple(v2_event_params),
    )
    v2_event_count = int(v2_event_rows[0]["cnt"]) if v2_event_rows else 0

    v2_shadow_rows = query_all(
        "SELECT COUNT(*) AS cnt FROM anomaly_event_v2 WHERE " + " AND ".join(v2_event_conditions) + " AND shadow_mode=1",
        tuple(v2_event_params),
    )
    v2_shadow_count = int(v2_shadow_rows[0]["cnt"]) if v2_shadow_rows else 0

    v2_level_rows = query_all(
        "SELECT event_level, COUNT(*) AS cnt FROM anomaly_event_v2 WHERE "
        + " AND ".join(v2_event_conditions)
        + " GROUP BY event_level",
        tuple(v2_event_params),
    )
    v2_level_dist: Dict[str, int] = {str(r["event_level"]): int(r["cnt"]) for r in v2_level_rows}

    return ok(
        {
            "scope": {
                "dev_num": dev_num.strip() or None,
                "start_ts": start_ts,
                "end_ts": end_ts,
            },
            "v1": {
                "point_anomaly_count": v1_point_anomaly_count,
                "event_count": v1_event_count,
            },
            "v2": {
                "event_count": v2_event_count,
                "shadow_event_count": v2_shadow_count,
                "event_level_distribution": v2_level_dist,
            },
            "delta": {
                "event_count_diff_v2_minus_v1": v2_event_count - v1_event_count,
            },
        }
    )


@app.get("/api/diagnosis/replay/report")
def diagnosis_replay_report(
    dev_num: str = Query("", max_length=50),
    start_ts: int = Query(..., ge=0),
    end_ts: int = Query(..., ge=0),
    target_false_alarm_per_day: float = Query(5.0, ge=0.0),
):
    if end_ts <= start_ts:
        return fail(1005, "end_ts must be greater than start_ts")

    compare_resp = diagnosis_replay_compare(dev_num=dev_num, start_ts=start_ts, end_ts=end_ts)
    if compare_resp.get("code") != 0:
        return compare_resp

    data = compare_resp.get("data") or {}
    v1 = data.get("v1") or {}
    v2 = data.get("v2") or {}

    span_days = max(1e-6, (end_ts - start_ts) / 86_400_000)
    v1_event_count = int(v1.get("event_count") or 0)
    v2_event_count = int(v2.get("event_count") or 0)
    v2_shadow_count = int(v2.get("shadow_event_count") or 0)

    v1_false_alarm_per_day = round(v1_event_count / span_days, 3)
    v2_false_alarm_per_day = round(v2_event_count / span_days, 3)

    acceptance_checks = {
        "shadow_mode_only": ANOMALY_V2_SHADOW_MODE,
        "v2_false_alarm_per_day_le_target": v2_false_alarm_per_day <= target_false_alarm_per_day,
        "api_ok": True,
    }
    accepted = all(acceptance_checks.values())

    summary_lines = [
        "# Shadow Run Acceptance Report",
        "",
        f"- dev_num: {dev_num.strip() or 'ALL'}",
        f"- start_ts: {start_ts}",
        f"- end_ts: {end_ts}",
        f"- span_days: {span_days:.3f}",
        "",
        "## V1 vs V2",
        f"- v1_event_count: {v1_event_count}",
        f"- v2_event_count: {v2_event_count}",
        f"- v2_shadow_event_count: {v2_shadow_count}",
        f"- v1_false_alarm_per_day: {v1_false_alarm_per_day}",
        f"- v2_false_alarm_per_day: {v2_false_alarm_per_day}",
        "",
        "## Acceptance",
        f"- target_false_alarm_per_day: {target_false_alarm_per_day}",
        f"- shadow_mode_only: {acceptance_checks['shadow_mode_only']}",
        f"- v2_false_alarm_per_day_le_target: {acceptance_checks['v2_false_alarm_per_day_le_target']}",
        f"- accepted: {accepted}",
    ]

    return ok(
        {
            "scope": data.get("scope"),
            "v1": v1,
            "v2": v2,
            "delta": data.get("delta"),
            "metrics": {
                "span_days": span_days,
                "v1_false_alarm_per_day": v1_false_alarm_per_day,
                "v2_false_alarm_per_day": v2_false_alarm_per_day,
            },
            "acceptance": {
                "target_false_alarm_per_day": target_false_alarm_per_day,
                "checks": acceptance_checks,
                "accepted": accepted,
            },
            "summary_markdown": "\n".join(summary_lines),
        }
    )


@app.get("/api/diagnosis/replay/{task_id}")
def diagnosis_replay_status(task_id: str = Path(...)):
    task = REPLAY_TASKS.get(task_id)
    if not task:
        return fail(404, "task not found")
    return ok(task)


@app.post("/api/diagnosis/replay/recent/{dev_num}")
async def diagnosis_replay_recent_device(
    dev_num: str = Path(...),
    points: int = Query(50, ge=5, le=1000),
    queued: int = Query(0, ge=0, le=1),
):
    rows = query_all(
        "SELECT device_timestamp FROM device_monitoring_data "
        "WHERE dev_num=%s ORDER BY device_timestamp DESC LIMIT %s",
        (dev_num, points),
    )
    if not rows:
        return fail(1002, f"no data for dev_num={dev_num}")

    timestamps = [int(r["device_timestamp"]) for r in reversed(rows)]

    ok_count = 0
    fail_count = 0
    last_error = ""

    for ts in timestamps:
        try:
            if queued == 1:
                await enqueue_device_process(dev_num, ts)
            else:
                await process_latest_for_device(dev_num, ts)
            ok_count += 1
        except Exception as err:
            fail_count += 1
            last_error = str(err)

    mode = "queued" if queued == 1 else "direct"
    return ok(
        {
            "dev_num": dev_num,
            "mode": mode,
            "requested_points": points,
            "processed_points": len(timestamps),
            "ok_count": ok_count,
            "fail_count": fail_count,
            "start_ts": timestamps[0],
            "end_ts": timestamps[-1],
            "last_error": last_error,
        }
    )


@app.get("/api/anomaly/v2/events/recent")
def anomaly_v2_recent_events(
    limit: int = Query(100, ge=1, le=2000),
    dev_num: str = Query("", max_length=50),
    shadow_mode: str = Query("all", pattern="^(all|true|false)$"),
):
    conditions: List[str] = []
    params: List[Any] = []

    dev_num = dev_num.strip()
    if dev_num:
        conditions.append("dev_num LIKE %s")
        params.append(f"%{dev_num}%")

    if shadow_mode == "true":
        conditions.append("shadow_mode=1")
    elif shadow_mode == "false":
        conditions.append("shadow_mode=0")

    where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = query_all(
        "SELECT event_id, dev_num, start_ts, end_ts, peak_score, duration_sec, event_level, decision_reason, shadow_mode, created_at "
        f"FROM anomaly_event_v2{where_clause} ORDER BY end_ts DESC LIMIT %s",
        tuple(params + [limit]),
    )
    for row in rows:
        row["shadow_mode"] = bool(row.get("shadow_mode"))
    return ok({"limit": limit, "dev_num": dev_num, "shadow_mode": shadow_mode, "items": rows})


@app.get("/api/anomaly/v2/review/topk")
def anomaly_v2_review_topk(
    start_ts: int = Query(..., ge=0),
    end_ts: int = Query(..., ge=0),
    limit: int = Query(30, ge=1, le=500),
    dev_num: str = Query("", max_length=50),
):
    if end_ts <= start_ts:
        return fail(1005, "end_ts must be greater than start_ts")

    dev_num = dev_num.strip()
    conditions = ["start_ts <= %s", "end_ts >= %s"]
    params: List[Any] = [end_ts, start_ts]
    if dev_num:
        conditions.append("dev_num = %s")
        params.append(dev_num)

    rows = query_all(
        "SELECT event_id, dev_num, start_ts, end_ts, peak_score, duration_sec, event_level, decision_reason, shadow_mode, created_at "
        "FROM anomaly_event_v2 WHERE "
        + " AND ".join(conditions)
        + " ORDER BY peak_score DESC, duration_sec DESC LIMIT %s",
        tuple(params + [limit]),
    )
    for row in rows:
        row["shadow_mode"] = bool(row.get("shadow_mode"))

    return ok(
        {
            "scope": {"start_ts": start_ts, "end_ts": end_ts, "dev_num": dev_num or None},
            "limit": limit,
            "items": rows,
        }
    )


@app.post("/api/anomaly/v2/review/label")
def anomaly_v2_review_label(req: AnomalyV2ReviewLabelRequest):
    event_id = req.event_id.strip()
    if not event_id:
        return fail(1007, "event_id is required")

    exists = query_all("SELECT 1 AS ok FROM anomaly_event_v2 WHERE event_id=%s LIMIT 1", (event_id,))
    if not exists:
        return fail(404, "event not found")

    execute(
        "INSERT INTO anomaly_review_label_v2 (event_id, label, reviewer, note) "
        "VALUES (%s,%s,%s,%s) "
        "ON DUPLICATE KEY UPDATE label=VALUES(label), reviewer=VALUES(reviewer), note=VALUES(note)",
        (event_id, req.label, req.reviewer.strip(), req.note.strip()),
    )

    row = query_all(
        "SELECT event_id, label, reviewer, note, created_at, updated_at "
        "FROM anomaly_review_label_v2 WHERE event_id=%s LIMIT 1",
        (event_id,),
    )
    return ok({"item": row[0] if row else None})


@app.get("/api/anomaly/v2/review/labels")
def anomaly_v2_review_labels(
    label: str = Query("all", pattern="^(all|true|false|uncertain)$"),
    limit: int = Query(200, ge=1, le=2000),
):
    conditions: List[str] = []
    params: List[Any] = []
    if label != "all":
        conditions.append("l.label=%s")
        params.append(label)

    where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = query_all(
        "SELECT l.event_id, l.label, l.reviewer, l.note, l.updated_at, "
        "e.dev_num, e.start_ts, e.end_ts, e.peak_score, e.duration_sec, e.event_level "
        "FROM anomaly_review_label_v2 l "
        "JOIN anomaly_event_v2 e ON e.event_id=l.event_id"
        f"{where_clause} ORDER BY l.updated_at DESC LIMIT %s",
        tuple(params + [limit]),
    )
    return ok({"label": label, "limit": limit, "items": rows})


@app.get("/api/anomaly/v2/review/topk/export")
def anomaly_v2_review_topk_export(
    start_ts: int = Query(..., ge=0),
    end_ts: int = Query(..., ge=0),
    limit: int = Query(200, ge=1, le=2000),
    dev_num: str = Query("", max_length=50),
):
    if end_ts <= start_ts:
        return PlainTextResponse("end_ts must be greater than start_ts", status_code=400)

    dev_num = dev_num.strip()
    conditions = ["start_ts <= %s", "end_ts >= %s"]
    params: List[Any] = [end_ts, start_ts]
    if dev_num:
        conditions.append("dev_num = %s")
        params.append(dev_num)

    rows = query_all(
        "SELECT event_id, dev_num, start_ts, end_ts, peak_score, duration_sec, event_level, decision_reason, shadow_mode, created_at "
        "FROM anomaly_event_v2 WHERE "
        + " AND ".join(conditions)
        + " ORDER BY peak_score DESC, duration_sec DESC LIMIT %s",
        tuple(params + [limit]),
    )

    header = [
        "event_id",
        "dev_num",
        "start_ts",
        "end_ts",
        "peak_score",
        "duration_sec",
        "event_level",
        "decision_reason",
        "shadow_mode",
        "created_at",
    ]
    lines = [",".join(header)]
    for row in rows:
        vals = []
        for k in header:
            v = row.get(k, "")
            s = str(v).replace('"', '""')
            vals.append(f'"{s}"')
        lines.append(",".join(vals))

    csv_content = "\n".join(lines)
    filename = "anomaly_v2_review_topk.csv"
    return PlainTextResponse(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/api/anomaly/v2/shadow/summary")
def anomaly_v2_shadow_summary(
    start_ts: int = Query(..., ge=0),
    end_ts: int = Query(..., ge=0),
    top_n: int = Query(10, ge=1, le=100),
):
    if end_ts <= start_ts:
        return fail(1005, "end_ts must be greater than start_ts")

    score_rows = query_all(
        "SELECT COUNT(*) AS cnt, AVG(score_raw) AS avg_raw, AVG(score_smooth) AS avg_smooth, "
        "MAX(score_smooth) AS max_smooth "
        "FROM anomaly_score_v2 WHERE device_timestamp BETWEEN %s AND %s",
        (start_ts, end_ts),
    )
    score_stats = score_rows[0] if score_rows else {"cnt": 0, "avg_raw": None, "avg_smooth": None, "max_smooth": None}

    event_rows = query_all(
        "SELECT COUNT(*) AS total_events, "
        "SUM(CASE WHEN shadow_mode=1 THEN 1 ELSE 0 END) AS shadow_events, "
        "AVG(duration_sec) AS avg_duration_sec, "
        "MAX(peak_score) AS max_peak_score "
        "FROM anomaly_event_v2 WHERE start_ts <= %s AND end_ts >= %s",
        (end_ts, start_ts),
    )
    event_stats = event_rows[0] if event_rows else {"total_events": 0, "shadow_events": 0, "avg_duration_sec": None, "max_peak_score": None}

    level_rows = query_all(
        "SELECT event_level, COUNT(*) AS cnt FROM anomaly_event_v2 "
        "WHERE start_ts <= %s AND end_ts >= %s GROUP BY event_level",
        (end_ts, start_ts),
    )
    level_distribution: Dict[str, int] = {str(r["event_level"]): int(r["cnt"]) for r in level_rows}

    top_devices = query_all(
        "SELECT dev_num, COUNT(*) AS event_count, MAX(peak_score) AS peak_score_max, "
        "AVG(duration_sec) AS duration_avg_sec "
        "FROM anomaly_event_v2 WHERE start_ts <= %s AND end_ts >= %s "
        "GROUP BY dev_num ORDER BY event_count DESC, peak_score_max DESC LIMIT %s",
        (end_ts, start_ts, top_n),
    )

    return ok(
        {
            "scope": {"start_ts": start_ts, "end_ts": end_ts},
            "score_stats": {
                "count": int(score_stats.get("cnt") or 0),
                "avg_raw": score_stats.get("avg_raw"),
                "avg_smooth": score_stats.get("avg_smooth"),
                "max_smooth": score_stats.get("max_smooth"),
            },
            "event_stats": {
                "total_events": int(event_stats.get("total_events") or 0),
                "shadow_events": int(event_stats.get("shadow_events") or 0),
                "avg_duration_sec": event_stats.get("avg_duration_sec"),
                "max_peak_score": event_stats.get("max_peak_score"),
                "level_distribution": level_distribution,
            },
            "top_devices": top_devices,
        }
    )


@app.get("/api/anomaly/v2/eval/summary")
def anomaly_v2_eval_summary():
    rows = query_all(
        "SELECT l.label, COUNT(*) AS cnt FROM anomaly_review_label_v2 l GROUP BY l.label"
    )
    label_cnt: Dict[str, int] = {str(r["label"]): int(r["cnt"]) for r in rows}

    true_cnt = int(label_cnt.get("true", 0))
    false_cnt = int(label_cnt.get("false", 0))
    uncertain_cnt = int(label_cnt.get("uncertain", 0))
    total_cnt = true_cnt + false_cnt + uncertain_cnt

    reviewed_rows = query_all(
        "SELECT e.event_id, e.peak_score, l.label "
        "FROM anomaly_event_v2 e "
        "JOIN anomaly_review_label_v2 l ON e.event_id=l.event_id"
    )

    pred_positive = 0
    tp = 0
    fp = 0
    fn = 0

    for r in reviewed_rows:
        score = float(r.get("peak_score") or 0.0)
        label = str(r.get("label") or "")
        pred = score >= float(ANOMALY_V2_RUNTIME.get("warn_threshold", ANOMALY_V2_WARN_THRESHOLD))
        actual = label == "true"

        if pred:
            pred_positive += 1
        if pred and actual:
            tp += 1
        if pred and not actual and label == "false":
            fp += 1
        if (not pred) and actual:
            fn += 1

    precision = (tp / (tp + fp)) if (tp + fp) > 0 else None
    recall = (tp / (tp + fn)) if (tp + fn) > 0 else None
    f1 = (2 * precision * recall / (precision + recall)) if precision is not None and recall is not None and (precision + recall) > 0 else None

    return ok(
        {
            "review_stats": {
                "total": total_cnt,
                "true": true_cnt,
                "false": false_cnt,
                "uncertain": uncertain_cnt,
            },
            "confusion_like": {
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "pred_positive": pred_positive,
            },
            "metrics": {
                "precision": precision,
                "recall": recall,
                "f1": f1,
            },
            "note": "Evaluation is based on reviewed labels only; uncertain labels are excluded from fp/fn.",
        }
    )


@app.get("/api/anomaly/v2/drift/summary")
def anomaly_v2_drift_summary(
    start_ts: int = Query(..., ge=0),
    end_ts: int = Query(..., ge=0),
    dev_num: str = Query("", max_length=50),
):
    if end_ts <= start_ts:
        return fail(1005, "end_ts must be greater than start_ts")

    dev_num = dev_num.strip()
    conditions = ["device_timestamp BETWEEN %s AND %s"]
    params: List[Any] = [start_ts, end_ts]
    if dev_num:
        conditions.append("dev_num = %s")
        params.append(dev_num)

    rows = query_all(
        "SELECT device_timestamp, score_smooth FROM anomaly_score_v2 WHERE "
        + " AND ".join(conditions)
        + " ORDER BY device_timestamp ASC",
        tuple(params),
    )
    if len(rows) < 10:
        return ok(
            {
                "scope": {"start_ts": start_ts, "end_ts": end_ts, "dev_num": dev_num or None},
                "count": len(rows),
                "drift": {"flag": False, "reason": "insufficient_points", "score": 0.0},
            }
        )

    vals = [float(r["score_smooth"]) for r in rows if r.get("score_smooth") is not None]
    n = len(vals)
    if n < 10:
        return ok(
            {
                "scope": {"start_ts": start_ts, "end_ts": end_ts, "dev_num": dev_num or None},
                "count": n,
                "drift": {"flag": False, "reason": "insufficient_points", "score": 0.0},
            }
        )

    mid = n // 2
    a = vals[:mid]
    b = vals[mid:]
    mean_a = sum(a) / len(a)
    mean_b = sum(b) / len(b)

    def _std(xs: List[float]) -> float:
        m = sum(xs) / len(xs)
        return (sum((x - m) ** 2 for x in xs) / len(xs)) ** 0.5

    std_a = _std(a)
    std_b = _std(b)
    std_base = max(1e-6, (std_a + std_b) / 2)

    mean_shift = mean_b - mean_a
    shift_ratio = abs(mean_shift) / std_base
    std_ratio = (std_b + 1e-6) / (std_a + 1e-6)

    drift_score = min(10.0, shift_ratio + abs(std_ratio - 1.0))
    drift_flag = drift_score >= 2.0

    return ok(
        {
            "scope": {"start_ts": start_ts, "end_ts": end_ts, "dev_num": dev_num or None},
            "count": n,
            "stats": {
                "mean_first_half": mean_a,
                "mean_second_half": mean_b,
                "std_first_half": std_a,
                "std_second_half": std_b,
                "mean_shift": mean_shift,
                "std_ratio": std_ratio,
            },
            "drift": {
                "flag": drift_flag,
                "score": drift_score,
                "threshold": 2.0,
                "method": "half_window_mean_std_shift",
            },
        }
    )


@app.get("/api/anomaly/v2/report/weekly")
def anomaly_v2_weekly_report(
    start_ts: int = Query(..., ge=0),
    end_ts: int = Query(..., ge=0),
    dev_num: str = Query("", max_length=50),
    top_n: int = Query(10, ge=1, le=100),
):
    if end_ts <= start_ts:
        return fail(1005, "end_ts must be greater than start_ts")

    dev_num = dev_num.strip()

    # Compare v1/v2
    compare_conditions = ["device_timestamp BETWEEN %s AND %s"]
    compare_params: List[Any] = [start_ts, end_ts]
    if dev_num:
        compare_conditions.append("dev_num = %s")
        compare_params.append(dev_num)

    where_clause_detection = " AND ".join(compare_conditions)

    v1_anomaly_rows = query_all(
        "SELECT COUNT(*) AS cnt FROM detection_result_log WHERE " + where_clause_detection + " AND is_anomaly=1",
        tuple(compare_params),
    )
    v1_point_anomaly_count = int(v1_anomaly_rows[0]["cnt"]) if v1_anomaly_rows else 0

    v1_event_conditions = ["display_mark_ts BETWEEN %s AND %s"]
    v1_event_params: List[Any] = [start_ts, end_ts]
    if dev_num:
        v1_event_conditions.append("dev_num = %s")
        v1_event_params.append(dev_num)

    v1_event_rows = query_all(
        "SELECT COUNT(*) AS cnt FROM anomaly_event WHERE " + " AND ".join(v1_event_conditions),
        tuple(v1_event_params),
    )
    v1_event_count = int(v1_event_rows[0]["cnt"]) if v1_event_rows else 0

    v2_event_conditions = ["start_ts <= %s", "end_ts >= %s"]
    v2_event_params: List[Any] = [end_ts, start_ts]
    if dev_num:
        v2_event_conditions.append("dev_num = %s")
        v2_event_params.append(dev_num)

    v2_event_rows = query_all(
        "SELECT COUNT(*) AS cnt FROM anomaly_event_v2 WHERE " + " AND ".join(v2_event_conditions),
        tuple(v2_event_params),
    )
    v2_event_count = int(v2_event_rows[0]["cnt"]) if v2_event_rows else 0

    v2_shadow_rows = query_all(
        "SELECT COUNT(*) AS cnt FROM anomaly_event_v2 WHERE " + " AND ".join(v2_event_conditions) + " AND shadow_mode=1",
        tuple(v2_event_params),
    )
    v2_shadow_count = int(v2_shadow_rows[0]["cnt"]) if v2_shadow_rows else 0

    v2_level_rows = query_all(
        "SELECT event_level, COUNT(*) AS cnt FROM anomaly_event_v2 WHERE "
        + " AND ".join(v2_event_conditions)
        + " GROUP BY event_level",
        tuple(v2_event_params),
    )
    v2_level_distribution: Dict[str, int] = {str(r["event_level"]): int(r["cnt"]) for r in v2_level_rows}

    # Shadow summary
    score_conditions = ["device_timestamp BETWEEN %s AND %s"]
    score_params: List[Any] = [start_ts, end_ts]
    if dev_num:
        score_conditions.append("dev_num = %s")
        score_params.append(dev_num)

    score_rows = query_all(
        "SELECT COUNT(*) AS cnt, AVG(score_raw) AS avg_raw, AVG(score_smooth) AS avg_smooth, "
        "MAX(score_smooth) AS max_smooth "
        "FROM anomaly_score_v2 WHERE " + " AND ".join(score_conditions),
        tuple(score_params),
    )
    score_stats = score_rows[0] if score_rows else {"cnt": 0, "avg_raw": None, "avg_smooth": None, "max_smooth": None}

    event_rows = query_all(
        "SELECT COUNT(*) AS total_events, "
        "SUM(CASE WHEN shadow_mode=1 THEN 1 ELSE 0 END) AS shadow_events, "
        "AVG(duration_sec) AS avg_duration_sec, "
        "MAX(peak_score) AS max_peak_score "
        "FROM anomaly_event_v2 WHERE " + " AND ".join(v2_event_conditions),
        tuple(v2_event_params),
    )
    event_stats = event_rows[0] if event_rows else {"total_events": 0, "shadow_events": 0, "avg_duration_sec": None, "max_peak_score": None}

    top_devices_conditions = ["start_ts <= %s", "end_ts >= %s"]
    top_devices_params: List[Any] = [end_ts, start_ts]
    if dev_num:
        top_devices_conditions.append("dev_num = %s")
        top_devices_params.append(dev_num)

    top_devices = query_all(
        "SELECT dev_num, COUNT(*) AS event_count, MAX(peak_score) AS peak_score_max, "
        "AVG(duration_sec) AS duration_avg_sec "
        "FROM anomaly_event_v2 WHERE "
        + " AND ".join(top_devices_conditions)
        + " GROUP BY dev_num ORDER BY event_count DESC, peak_score_max DESC LIMIT %s",
        tuple(top_devices_params + [top_n]),
    )

    key_events = query_all(
        "SELECT event_id, dev_num, start_ts, end_ts, peak_score, duration_sec, event_level, decision_reason, shadow_mode, created_at "
        "FROM anomaly_event_v2 WHERE "
        + " AND ".join(v2_event_conditions)
        + " ORDER BY peak_score DESC, duration_sec DESC LIMIT 20",
        tuple(v2_event_params),
    )
    for row in key_events:
        row["shadow_mode"] = bool(row.get("shadow_mode"))

    report_title = "anomaly_v2_weekly_report"
    if dev_num:
        report_title = f"anomaly_v2_weekly_report_{dev_num}"

    return ok(
        {
            "report": {
                "name": report_title,
                "generated_at": now_ms(),
                "scope": {"start_ts": start_ts, "end_ts": end_ts, "dev_num": dev_num or None},
            },
            "comparison": {
                "v1": {
                    "point_anomaly_count": v1_point_anomaly_count,
                    "event_count": v1_event_count,
                },
                "v2": {
                    "event_count": v2_event_count,
                    "shadow_event_count": v2_shadow_count,
                    "event_level_distribution": v2_level_distribution,
                },
                "delta": {
                    "event_count_diff_v2_minus_v1": v2_event_count - v1_event_count,
                },
            },
            "shadow_summary": {
                "score_stats": {
                    "count": int(score_stats.get("cnt") or 0),
                    "avg_raw": score_stats.get("avg_raw"),
                    "avg_smooth": score_stats.get("avg_smooth"),
                    "max_smooth": score_stats.get("max_smooth"),
                },
                "event_stats": {
                    "total_events": int(event_stats.get("total_events") or 0),
                    "shadow_events": int(event_stats.get("shadow_events") or 0),
                    "avg_duration_sec": event_stats.get("avg_duration_sec"),
                    "max_peak_score": event_stats.get("max_peak_score"),
                },
                "top_devices": top_devices,
            },
            "key_events": key_events,
        }
    )


@app.get("/api/anomaly/v2/control")
def get_anomaly_v2_control(dev_num: str = Query("", max_length=50)):
    dev = dev_num.strip()
    data: Dict[str, Any] = {"config": ANOMALY_V2_RUNTIME}
    if dev:
        data["debug_last"] = ANOMALY_V2_LAST_DEBUG_BY_DEV.get(dev)
    return ok(data)


@app.get("/api/anomaly/v2/debug/last")
def anomaly_v2_debug_last(dev_num: str = Query(..., max_length=50)):
    dev = dev_num.strip()
    if not dev:
        return fail(1007, "dev_num is required")

    last_row = query_all(
        "SELECT device_timestamp, score_raw, score_smooth, feature_json "
        "FROM anomaly_score_v2 WHERE dev_num=%s ORDER BY device_timestamp DESC LIMIT 1",
        (dev,),
    )
    if not last_row:
        return ok({"dev_num": dev, "exists": False})

    row = last_row[0]
    features = row.get("feature_json")
    if isinstance(features, str):
        try:
            features = json.loads(features)
        except Exception:
            features = {"raw": features}

    return ok(
        {
            "dev_num": dev,
            "exists": True,
            "runtime_enabled": bool(ANOMALY_V2_RUNTIME.get("enabled", False)),
            "runtime_config": ANOMALY_V2_RUNTIME,
            "last_score": {
                "device_timestamp": row.get("device_timestamp"),
                "score_raw": row.get("score_raw"),
                "score_smooth": row.get("score_smooth"),
                "features": features,
            },
            "last_debug": ANOMALY_V2_LAST_DEBUG_BY_DEV.get(dev),
        }
    )


@app.post("/api/anomaly/v2/control")
def set_anomaly_v2_control(req: AnomalyV2ControlRequest):
    updates: Dict[str, Any] = {}

    if req.enabled is not None:
        ANOMALY_V2_RUNTIME["enabled"] = bool(req.enabled)
        updates["enabled"] = ANOMALY_V2_RUNTIME["enabled"]
    if req.shadow_mode is not None:
        ANOMALY_V2_RUNTIME["shadow_mode"] = bool(req.shadow_mode)
        updates["shadow_mode"] = ANOMALY_V2_RUNTIME["shadow_mode"]
    if req.alpha is not None:
        if not (0.0 < req.alpha <= 1.0):
            return fail(1006, "alpha must be in (0, 1]")
        ANOMALY_V2_RUNTIME["alpha"] = float(req.alpha)
        updates["alpha"] = ANOMALY_V2_RUNTIME["alpha"]
    if req.warn_threshold is not None:
        if not (0.0 <= req.warn_threshold <= 1.0):
            return fail(1006, "warn_threshold must be in [0, 1]")
        ANOMALY_V2_RUNTIME["warn_threshold"] = float(req.warn_threshold)
        updates["warn_threshold"] = ANOMALY_V2_RUNTIME["warn_threshold"]
    if req.recover_threshold is not None:
        if not (0.0 <= req.recover_threshold <= 1.0):
            return fail(1006, "recover_threshold must be in [0, 1]")
        ANOMALY_V2_RUNTIME["recover_threshold"] = float(req.recover_threshold)
        updates["recover_threshold"] = ANOMALY_V2_RUNTIME["recover_threshold"]
    if req.min_points is not None:
        if req.min_points < 2:
            return fail(1006, "min_points must be >= 2")
        ANOMALY_V2_RUNTIME["min_points"] = int(req.min_points)
        updates["min_points"] = ANOMALY_V2_RUNTIME["min_points"]
    if req.event_start_count is not None:
        if req.event_start_count < 1:
            return fail(1006, "event_start_count must be >= 1")
        ANOMALY_V2_RUNTIME["event_start_count"] = int(req.event_start_count)
        updates["event_start_count"] = ANOMALY_V2_RUNTIME["event_start_count"]
    if req.event_end_count is not None:
        if req.event_end_count < 1:
            return fail(1006, "event_end_count must be >= 1")
        ANOMALY_V2_RUNTIME["event_end_count"] = int(req.event_end_count)
        updates["event_end_count"] = ANOMALY_V2_RUNTIME["event_end_count"]
    if req.event_min_duration_sec is not None:
        if req.event_min_duration_sec < 0:
            return fail(1006, "event_min_duration_sec must be >= 0")
        ANOMALY_V2_RUNTIME["event_min_duration_sec"] = int(req.event_min_duration_sec)
        updates["event_min_duration_sec"] = ANOMALY_V2_RUNTIME["event_min_duration_sec"]
    if req.event_cooldown_sec is not None:
        if req.event_cooldown_sec < 0:
            return fail(1006, "event_cooldown_sec must be >= 0")
        ANOMALY_V2_RUNTIME["event_cooldown_sec"] = int(req.event_cooldown_sec)
        updates["event_cooldown_sec"] = ANOMALY_V2_RUNTIME["event_cooldown_sec"]
    if req.sim_enabled is not None:
        ANOMALY_V2_RUNTIME["sim_enabled"] = bool(req.sim_enabled)
        updates["sim_enabled"] = ANOMALY_V2_RUNTIME["sim_enabled"]
    if req.sim_weight is not None:
        if not (0.0 <= req.sim_weight <= 1.0):
            return fail(1006, "sim_weight must be in [0, 1]")
        ANOMALY_V2_RUNTIME["sim_weight"] = float(req.sim_weight)
        updates["sim_weight"] = ANOMALY_V2_RUNTIME["sim_weight"]
    if req.sim_k is not None:
        if req.sim_k < 1:
            return fail(1006, "sim_k must be >= 1")
        ANOMALY_V2_RUNTIME["sim_k"] = int(req.sim_k)
        updates["sim_k"] = ANOMALY_V2_RUNTIME["sim_k"]
    if req.debug_trace is not None:
        ANOMALY_V2_RUNTIME["debug_trace"] = bool(req.debug_trace)
        updates["debug_trace"] = ANOMALY_V2_RUNTIME["debug_trace"]

    return ok({"updated": updates, "config": ANOMALY_V2_RUNTIME, "updated_at": now_ms()})


@app.get("/api/models")
def models():
    return ok(
        {
            "default_model": DEFAULT_MODEL,
            "model_service_enabled": MODEL_SERVICE_ENABLED,
            "local_model_name": LOCAL_MODEL_NAME,
            "models": [
                {
                    "model_name": LOCAL_MODEL_NAME,
                    "enabled": True,
                    "latest_version": LOCAL_MODEL_VERSION,
                    "active_version": ACTIVE_MODEL_VERSION[LOCAL_MODEL_NAME],
                    "versions": MODEL_VERSION_CATALOG[LOCAL_MODEL_NAME],
                },
                {
                    "model_name": "xgboost",
                    "enabled": MODEL_SERVICE_ENABLED,
                    "latest_version": MODEL_VERSION_CATALOG["xgboost"][-1],
                    "active_version": ACTIVE_MODEL_VERSION["xgboost"],
                    "versions": MODEL_VERSION_CATALOG["xgboost"],
                },
                {
                    "model_name": "gru",
                    "enabled": MODEL_SERVICE_ENABLED,
                    "latest_version": MODEL_VERSION_CATALOG["gru"][-1],
                    "active_version": ACTIVE_MODEL_VERSION["gru"],
                    "versions": MODEL_VERSION_CATALOG["gru"],
                },
                {
                    "model_name": "auto",
                    "enabled": True,
                    "latest_version": "auto",
                    "active_version": ACTIVE_MODEL_VERSION["auto"],
                    "versions": MODEL_VERSION_CATALOG["auto"],
                },
            ],
        }
    )


@app.post("/api/models/select")
def model_select(req: ModelSelectRequest):
    global DEFAULT_MODEL
    requested = normalize_model_name(req.model_name)
    if requested in EXTERNAL_MODEL_NAMES and not MODEL_SERVICE_ENABLED:
        return fail(1004, "model service disabled for external models")
    DEFAULT_MODEL = requested
    return ok({"default_model": DEFAULT_MODEL, "effective_model_name": resolve_effective_model_name(DEFAULT_MODEL), "updated_at": now_ms()})


@app.post("/api/models/rollback")
def model_rollback(req: ModelRollbackRequest):
    if req.model_name == LOCAL_MODEL_NAME:
        return fail(1003, "local model does not support rollback")
    versions = MODEL_VERSION_CATALOG.get(req.model_name, [])
    if req.target_version not in versions:
        return fail(1003, f"unsupported target_version={req.target_version}")
    ACTIVE_MODEL_VERSION[req.model_name] = req.target_version
    return ok({"model_name": req.model_name, "active_version": req.target_version, "updated_at": now_ms()})


@app.get("/api/fault/recent/export")
def fault_recent_export_csv(
    limit: int = Query(1000, ge=1, le=20000),
    dev_num: str = Query("", max_length=50),
    hours: int = Query(0, ge=0, le=8760),
):
    conditions: List[str] = []
    params: List[Any] = []

    dev_num = dev_num.strip()
    if dev_num:
        conditions.append("dev_num LIKE %s")
        params.append(f"%{dev_num}%")

    if hours > 0:
        end_ts = now_ms()
        start_ts = end_ts - hours * 3600 * 1000
        conditions.append("device_timestamp BETWEEN %s AND %s")
        params.extend([start_ts, end_ts])

    where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""

    items = query_all(
        "SELECT request_id, dev_num, device_timestamp, event_hour_bucket, is_anomaly, anomaly_score, threshold, "
        "model_name, model_version, method, diagnosis_status, created_at "
        f"FROM fault_archive{where_clause} ORDER BY device_timestamp DESC LIMIT %s",
        tuple(params + [limit]),
    )

    header = [
        "request_id",
        "dev_num",
        "device_timestamp",
        "event_hour_bucket",
        "is_anomaly",
        "anomaly_score",
        "threshold",
        "model_name",
        "model_version",
        "method",
        "diagnosis_status",
        "created_at",
    ]
    lines = [",".join(header)]
    for row in items:
        values = []
        for key in header:
            val = row.get(key)
            text = "" if val is None else str(val)
            text = text.replace('"', '""')
            if "," in text or '"' in text:
                text = f'"{text}"'
            values.append(text)
        lines.append(",".join(values))

    csv_text = "\n".join(lines)
    return PlainTextResponse(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=fault_recent.csv"},
    )


@app.get("/api/device/{dev_num}/model")
def get_device_model_api(dev_num: str = Path(...)):
    model_info = get_device_model_info(dev_num)
    return ok({"dev_num": dev_num, **model_info})


@app.post("/api/device/{dev_num}/model/select")
def select_device_model(dev_num: str = Path(...), req: DeviceModelSelectRequest = ...):
    requested = normalize_model_name(req.model_name)
    if requested not in ALL_MODEL_NAMES:
        return fail(1003, f"unsupported model_name={req.model_name}")
    if requested in EXTERNAL_MODEL_NAMES and not MODEL_SERVICE_ENABLED:
        return fail(1004, "model service disabled for external models")
    set_device_model(dev_num, requested)
    return ok(
        {
            "dev_num": dev_num,
            "model_name": requested,
            "effective_model_name": resolve_effective_model_name(requested),
            "updated_at": now_ms(),
        }
    )


@app.post("/api/internal/process/{dev_num}/{device_timestamp}")
async def internal_process(
    dev_num: str,
    device_timestamp: int,
    queued: int = Query(1, ge=0, le=1),
    fallback_latest: int = Query(1, ge=0, le=1),
):
    """手工触发单设备单时间点检测（用于联调/测试）。queued=1 走合并队列，queued=0 立即执行。"""
    latest_row = query_all(
        "SELECT MAX(device_timestamp) AS latest_ts FROM device_monitoring_data WHERE dev_num=%s",
        (dev_num,),
    )
    latest_ts = int(latest_row[0]["latest_ts"]) if latest_row and latest_row[0].get("latest_ts") else 0
    if latest_ts <= 0:
        return fail(1002, f"no monitoring data for dev_num={dev_num}")

    effective_ts = device_timestamp
    if fallback_latest == 1 and device_timestamp > latest_ts:
        effective_ts = latest_ts

    if queued == 1:
        result = await enqueue_device_process(dev_num, effective_ts)
        return ok({"dev_num": dev_num, "device_timestamp": effective_ts, "latest_ts": latest_ts, **result})

    payload = await process_latest_for_device(dev_num, effective_ts)
    payload["requested_device_timestamp"] = device_timestamp
    payload["effective_device_timestamp"] = effective_ts
    payload["latest_ts"] = latest_ts
    return ok(payload)


@app.post("/api/upload/xlsx")
async def upload_local_xlsx(
    file: UploadFile = File(...),
    model_name: str = Form("seal_v4"),
    dev_num_hint: str = Form(""),
    process_mode: str = Form("full"),
):
    normalized_model = normalize_model_name(model_name)
    if normalized_model not in ALL_MODEL_NAMES:
        return fail(1003, f"unsupported model_name={model_name}")
    if normalized_model in EXTERNAL_MODEL_NAMES and not MODEL_SERVICE_ENABLED:
        return fail(1004, "model service disabled for external models")
    if process_mode not in {"full", "latest"}:
        return fail(1005, "process_mode must be full or latest")

    file_bytes = await file.read()
    if not file_bytes:
        return fail(1002, "empty upload file")

    try:
        df = load_uploaded_excel_points(file_bytes)
    except Exception as err:
        return fail(1002, str(err))

    upload_dev_num = build_upload_dev_num(file.filename or "upload.xlsx", dev_num_hint)
    try:
        analysis = await analyze_uploaded_points(
            df=df,
            dev_num=upload_dev_num,
            requested_model_name=normalized_model,
            process_mode=process_mode,
            file_name=file.filename or "upload.xlsx",
        )
    except Exception as err:
        return fail(1002, f"upload analysis failed: {err}")

    return ok(
        {
            **analysis,
            "model_name": normalized_model,
            "effective_model_name": resolve_effective_model_name(normalized_model),
            "process_mode": process_mode,
            "file_name": file.filename,
            "source": "upload_xlsx_memory",
        }
    )


@app.get("/api/runtime/metrics")
def runtime_metrics():
    return ok({
        "metrics": RUNTIME_METRICS,
        "queue": {
            "pending_devices": len(PENDING_PROCESS_TS_BY_DEV),
            "device_process_min_interval_ms": DEVICE_PROCESS_MIN_INTERVAL_MS,
        },
        "model_service_url": MODEL_SERVICE_URL,
        "model_call_retries": MODEL_CALL_RETRIES,
        "model_timeout_seconds": MODEL_TIMEOUT_SECONDS,
        "active_model_versions": ACTIVE_MODEL_VERSION,
        "anomaly_v2": ANOMALY_V2_RUNTIME,
    })


@app.get("/api/fault/recent/export")
def fault_recent_export(
    limit: int = Query(1000, ge=1, le=50000),
    dev_num: str = Query("", max_length=50),
    hours: int = Query(0, ge=0, le=8760),
):
    conditions: List[str] = []
    params: List[Any] = []

    dev_num = dev_num.strip()
    if dev_num:
        conditions.append("dev_num LIKE %s")
        params.append(f"%{dev_num}%")

    if hours > 0:
        end_ts = now_ms()
        start_ts = end_ts - hours * 3600 * 1000
        conditions.append("device_timestamp BETWEEN %s AND %s")
        params.extend([start_ts, end_ts])

    where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = query_all(
        "SELECT request_id, dev_num, device_timestamp, is_anomaly, anomaly_score, threshold, "
        "model_name, model_version, method, diagnosis_status, created_at "
        f"FROM fault_archive{where_clause} ORDER BY device_timestamp DESC LIMIT %s",
        tuple(params + [limit]),
    )

    header = [
        "request_id",
        "dev_num",
        "device_timestamp",
        "is_anomaly",
        "anomaly_score",
        "threshold",
        "model_name",
        "model_version",
        "method",
        "diagnosis_status",
        "created_at",
    ]
    lines = [",".join(header)]
    for row in rows:
        line = []
        for k in header:
            v = row.get(k, "")
            s = str(v).replace('"', '""')
            line.append(f'"{s}"')
        lines.append(",".join(line))

    csv_content = "\n".join(lines)
    return PlainTextResponse(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=fault_recent.csv"},
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
