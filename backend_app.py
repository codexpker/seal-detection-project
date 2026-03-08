import asyncio
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, List, Literal, Optional

import httpx
import mysql.connector
from fastapi import FastAPI, Path, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, PlainTextResponse
from pydantic import BaseModel


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
HOME_MIN_DISPLAY_SECONDS = int(_env("HOME_MIN_DISPLAY_SECONDS", "60"))
MODEL_TIMEOUT_SECONDS = float(_env("MODEL_TIMEOUT_SECONDS", "0.8"))
MODEL_CONNECT_TIMEOUT_SECONDS = float(_env("MODEL_CONNECT_TIMEOUT_SECONDS", "0.3"))
MODEL_CALL_RETRIES = int(_env("MODEL_CALL_RETRIES", "2"))
MODEL_SERVICE_ENABLED = _env("MODEL_SERVICE_ENABLED", "false").lower() in ("1", "true", "yes", "on")
DEVICE_PROCESS_MIN_INTERVAL_MS = int(_env("DEVICE_PROCESS_MIN_INTERVAL_MS", "3000"))


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


# -----------------------------
# Pydantic models
# -----------------------------


class ModelSelectRequest(BaseModel):
    model_name: Literal["auto", "xgboost", "gru"] = "auto"


class DeviceModelSelectRequest(BaseModel):
    model_name: Literal["auto", "xgboost", "gru"] = "auto"


class ReplayRequest(BaseModel):
    dev_num: str
    start_ts: int
    end_ts: int
    model_name: Literal["auto", "xgboost", "gru"] = "auto"


class ModelRollbackRequest(BaseModel):
    model_name: Literal["xgboost", "gru", "auto"]
    target_version: str


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
RUNTIME_METRICS: Dict[str, int] = {
    "process_total": 0,
    "process_ok": 0,
    "process_insufficient": 0,
    "process_model_timeout": 0,
    "process_model_error": 0,
    "process_skipped_interval": 0,
    "model_call_total": 0,
    "model_call_retry": 0,
    "queue_enqueued": 0,
    "queue_merged": 0,
    "queue_processed": 0,
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
    "auto": ["auto"],
}
ACTIVE_MODEL_VERSION: Dict[str, str] = {
    "xgboost": "xgboost-2026.02",
    "gru": "gru-2026.02",
    "auto": "auto",
}


def get_effective_model_for_device(dev_num: str) -> str:
    rows = query_all(
        "SELECT model_name FROM device_model_preference WHERE dev_num=%s LIMIT 1",
        (dev_num,),
    )
    if rows and rows[0].get("model_name"):
        return rows[0]["model_name"]
    return DEFAULT_MODEL


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
    return item


def get_device_model_info(dev_num: str) -> Dict[str, str]:
    rows = query_all(
        "SELECT model_name FROM device_model_preference WHERE dev_num=%s LIMIT 1",
        (dev_num,),
    )
    if rows and rows[0].get("model_name"):
        return {"model_name": str(rows[0]["model_name"]), "source": "device"}
    return {"model_name": DEFAULT_MODEL, "source": "default"}


def get_device_model(dev_num: str) -> str:
    return get_device_model_info(dev_num)["model_name"]


def set_device_model(dev_num: str, model_name: str) -> None:
    execute(
        "INSERT INTO device_model_preference (dev_num, model_name, updated_at) "
        "VALUES (%s,%s,%s) "
        "ON DUPLICATE KEY UPDATE model_name=VALUES(model_name), updated_at=VALUES(updated_at)",
        (dev_num, model_name, now_ms()),
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


async def process_latest_for_device(dev_num: str, device_timestamp: int) -> Dict[str, Any]:
    RUNTIME_METRICS["process_total"] += 1
    points = fetch_window(dev_num, device_timestamp, WINDOW_N, WINDOW_T_MINUTES)
    model_name = get_device_model(dev_num)

    if len(points) < 1:
        result = {
            "request_id": str(uuid.uuid4()),
            "is_anomaly": False,
            "anomaly_score": 0.0,
            "threshold": 0.0,
            "model_name": model_name,
            "model_version": None,
            "infer_latency_ms": 0,
            "status": "insufficient_data",
        }
        RUNTIME_METRICS["process_insufficient"] += 1
    else:
        try:
            result = await call_model_service(dev_num, points, model_name, device_timestamp)
            RUNTIME_METRICS["process_ok"] += 1
        except httpx.TimeoutException:
            result = {
                "request_id": str(uuid.uuid4()),
                "is_anomaly": False,
                "anomaly_score": 0.0,
                "threshold": 0.0,
                "model_name": model_name,
                "model_version": None,
                "infer_latency_ms": int(MODEL_TIMEOUT_SECONDS * 1000),
                "status": "model_timeout",
            }
            RUNTIME_METRICS["process_model_timeout"] += 1
        except Exception:
            result = {
                "request_id": str(uuid.uuid4()),
                "is_anomaly": False,
                "anomaly_score": 0.0,
                "threshold": 0.0,
                "model_name": model_name,
                "model_version": None,
                "infer_latency_ms": 0,
                "status": "model_error",
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
        "method": "N_AND_T",
        "point": latest_point,
        "anomaly_points": [latest_point],
        "detection": result,
        "mark": mark,
    }

    save_fault_archive(event_payload)
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


# -----------------------------
# FastAPI app
# -----------------------------


app = FastAPI(title="Seal Detection Backend API", version="1.0.0")
bootstrap_schema()


@app.on_event("startup")
async def startup_worker() -> None:
    global QUEUE_WORKER_STARTED
    if not QUEUE_WORKER_STARTED:
        asyncio.create_task(process_queue_worker())
        QUEUE_WORKER_STARTED = True


@app.get("/api/health")
def health():
    return ok({"status": "up"})


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
        "SELECT dev_num, display_mark_ts, event_hour_bucket, status FROM anomaly_event "
        "WHERE dev_num=%s ORDER BY display_mark_ts DESC LIMIT 100",
        (dev_num,),
    )
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
        "SELECT dev_num, display_mark_ts, event_hour_bucket, status FROM anomaly_event "
        "WHERE dev_num=%s AND display_mark_ts BETWEEN %s AND %s ORDER BY display_mark_ts",
        (dev_num, start_ts, end_range_ts),
    )
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
                asyncio.run(process_latest_for_device(req.dev_num, device_ts))
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


@app.get("/api/diagnosis/replay/{task_id}")
def diagnosis_replay_status(task_id: str = Path(...)):
    task = REPLAY_TASKS.get(task_id)
    if not task:
        return fail(404, "task not found")
    return ok(task)


@app.get("/api/models")
def models():
    return ok(
        {
            "default_model": DEFAULT_MODEL,
            "model_service_enabled": MODEL_SERVICE_ENABLED,
            "models": [
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
                    "enabled": MODEL_SERVICE_ENABLED,
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
    DEFAULT_MODEL = req.model_name
    return ok({"default_model": DEFAULT_MODEL, "updated_at": now_ms()})


@app.post("/api/models/rollback")
def model_rollback(req: ModelRollbackRequest):
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
    if not MODEL_SERVICE_ENABLED:
        return fail(1004, "model service disabled")
    set_device_model(dev_num, req.model_name)
    return ok({"dev_num": dev_num, "model_name": req.model_name, "updated_at": now_ms()})


@app.post("/api/internal/process/{dev_num}/{device_timestamp}")
async def internal_process(dev_num: str, device_timestamp: int, queued: int = Query(1, ge=0, le=1)):
    """手工触发单设备单时间点检测（用于联调/测试）。queued=1 走合并队列，queued=0 立即执行。"""
    if queued == 1:
        result = await enqueue_device_process(dev_num, device_timestamp)
        return ok({"dev_num": dev_num, "device_timestamp": device_timestamp, **result})

    payload = await process_latest_for_device(dev_num, device_timestamp)
    return ok(payload)


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