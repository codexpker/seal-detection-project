from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import struct
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd


DEFAULT_HOST = os.getenv("SIM_MQTT_HOST", "0.0.0.0")
DEFAULT_PORT = int(os.getenv("SIM_MQTT_PORT", "21883"))
DEFAULT_TOPIC = os.getenv("SIM_MQTT_TOPIC", "/sys/petrochemical/report")
DEFAULT_POOL_DIR = Path(os.getenv("SIM_POOL_DIR", "sim_mqtt_pool"))
DEFAULT_INTERVAL_SECONDS = float(os.getenv("SIM_INTERVAL_SECONDS", "60"))
DEFAULT_SCAN_SECONDS = float(os.getenv("SIM_SCAN_SECONDS", "5"))

DEFAULT_PROJECT_NAME = os.getenv("SIM_PROJECT_NAME", "BSTProject")
DEFAULT_PROJECT_NUM = os.getenv("SIM_PROJECT_NUM", "001")
DEFAULT_DEV_NAME = os.getenv("SIM_DEV_NAME", "AHCZ-D1S-26801")
DEFAULT_DEV_NUM = os.getenv("SIM_DEV_NUM", "848872DC45E1D3F")


COLUMN_ALIASES = {
    "time": ["time", "时间", "timestamp", "date", "datetime", "采集时间"],
    "project_name": ["project_name", "项目名称"],
    "project_num": ["project_num", "项目编码", "项目编号"],
    "dev_name": ["dev_name", "设备名称", "传感器编号", "sensor_name"],
    "dev_num": ["dev_num", "设备编码", "传感器编码", "sensor_code", "imei"],
    "snr": ["snr", "SNR", "信噪比"],
    "rsrp": ["rsrp", "RSRP", "信号质量"],
    "in_temp": ["in_temp", "内部温度", "内温", "温度_内", "InSideTemp"],
    "in_hum": ["in_hum", "内部湿度", "内湿", "湿度_内", "InSideHumi"],
    "out_temp": ["out_temp", "外部温度", "外温", "温度_外", "OutSideTemp"],
    "out_hum": ["out_hum", "外部湿度", "外湿", "湿度_外", "OutSideHumi"],
    "phase_temp_a": ["phase_temp_a", "A相温度", "PhaseTempA", "Atemp"],
    "phase_temp_b": ["phase_temp_b", "B相温度", "PhaseTempB", "Btemp"],
    "phase_temp_c": ["phase_temp_c", "C相温度", "PhaseTempC", "Ctemp"],
    "mlx_max_temp": ["mlx_max_temp", "红外最高温度", "MlxMaxTemp"],
    "mlx_min_temp": ["mlx_min_temp", "红外最低温度", "MlxMinTemp"],
    "mlx_avg_temp": ["mlx_avg_temp", "红外平均温度", "MlxAvgTemp"],
    "inside_bat": ["inside_bat", "传感器电池采样", "InSideBat"],
    "outside_bat": ["outside_bat", "融合终端电池采样", "OutSideBat"],
}


def parse_allowed_users() -> Dict[str, str]:
    raw = os.getenv(
        "SIM_MQTT_USERS",
        "czxy01:123456,czxy02:123456,czxy03:123456,czxy04:123456,czxy05:123456",
    )
    result: Dict[str, str] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            result[item] = ""
            continue
        username, password = item.split(":", 1)
        result[username.strip()] = password.strip()
    return result


def safe_float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    try:
        return float(value)
    except Exception:
        return None


def normalize_time_seconds(value, fallback_seconds: int) -> int:
    if value is None or value == "":
        return fallback_seconds
    try:
        if isinstance(value, pd.Timestamp):
            return int(value.timestamp())
        ts = pd.to_datetime(value, errors="coerce")
        if ts is not None and not pd.isna(ts):
            return int(ts.timestamp())
    except Exception:
        pass

    try:
        raw = int(float(value))
        if raw > 1_000_000_000_000:
            return raw // 1000
        if raw > 0:
            return raw
    except Exception:
        pass

    return fallback_seconds


def read_remaining_length(sock: socket.socket) -> int:
    multiplier = 1
    value = 0
    while True:
        encoded = recv_exact(sock, 1)[0]
        value += (encoded & 127) * multiplier
        if (encoded & 128) == 0:
            return value
        multiplier *= 128
        if multiplier > 128 * 128 * 128:
            raise ValueError("MQTT 剩余长度字段非法")


def encode_remaining_length(length: int) -> bytes:
    out = bytearray()
    while True:
        digit = length % 128
        length //= 128
        if length > 0:
            digit |= 0x80
        out.append(digit)
        if length == 0:
            break
    return bytes(out)


def recv_exact(sock: socket.socket, length: int) -> bytes:
    chunks = []
    remaining = length
    while remaining > 0:
        data = sock.recv(remaining)
        if not data:
            raise ConnectionError("连接已关闭")
        chunks.append(data)
        remaining -= len(data)
    return b"".join(chunks)


def encode_utf8(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack("!H", len(raw)) + raw


def decode_utf8(packet: bytes, offset: int) -> Tuple[str, int]:
    if offset + 2 > len(packet):
        raise ValueError("UTF-8 字段长度不足")
    length = struct.unpack("!H", packet[offset: offset + 2])[0]
    start = offset + 2
    end = start + length
    if end > len(packet):
        raise ValueError("UTF-8 字段内容不足")
    return packet[start:end].decode("utf-8", errors="ignore"), end


def mqtt_match(filter_text: str, topic: str) -> bool:
    if filter_text == topic:
        return True
    filter_parts = filter_text.split("/")
    topic_parts = topic.split("/")
    for idx, part in enumerate(filter_parts):
        if part == "#":
            return True
        if idx >= len(topic_parts):
            return False
        if part == "+":
            continue
        if part != topic_parts[idx]:
            return False
    return len(filter_parts) == len(topic_parts)


def build_connack(return_code: int) -> bytes:
    return bytes([0x20, 0x02, 0x00, return_code])


def build_suback(packet_id: int, qos: int = 0) -> bytes:
    variable_header = struct.pack("!H", packet_id)
    payload = bytes([qos])
    return bytes([0x90]) + encode_remaining_length(len(variable_header) + len(payload)) + variable_header + payload


def build_pingresp() -> bytes:
    return bytes([0xD0, 0x00])


def build_publish_packet(topic: str, payload: bytes) -> bytes:
    variable_header = encode_utf8(topic)
    fixed_header = bytes([0x30]) + encode_remaining_length(len(variable_header) + len(payload))
    return fixed_header + variable_header + payload


@dataclass
class ClientSession:
    socket: socket.socket
    address: Tuple[str, int]
    client_id: str = ""
    username: str = ""
    subscriptions: Optional[set] = None

    def __post_init__(self):
        if self.subscriptions is None:
            self.subscriptions = set()


class SimpleMQTTBroker:
    def __init__(self, host: str, port: int, allowed_users: Dict[str, str]):
        self.host = host
        self.port = port
        self.allowed_users = allowed_users
        self.server_socket: Optional[socket.socket] = None
        self.running = False
        self.lock = threading.Lock()
        self.sessions: List[ClientSession] = []

    def start(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(20)
        self.running = True
        threading.Thread(target=self._accept_loop, daemon=True).start()
        logging.info("✅ 本地 MQTT broker 已启动: %s:%s", self.host, self.port)

    def stop(self):
        self.running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
        with self.lock:
            sessions = list(self.sessions)
            self.sessions.clear()
        for session in sessions:
            try:
                session.socket.close()
            except Exception:
                pass

    def publish(self, topic: str, payload_text: str):
        payload_bytes = payload_text.encode("utf-8")
        packet = build_publish_packet(topic, payload_bytes)
        delivered = 0
        with self.lock:
            target_sessions = list(self.sessions)
        for session in target_sessions:
            if not any(mqtt_match(topic_filter, topic) for topic_filter in session.subscriptions):
                continue
            try:
                session.socket.sendall(packet)
                delivered += 1
            except Exception:
                self._drop_session(session)
        logging.info("📤 Broker转发 topic=%s 订阅端=%s", topic, delivered)

    def _accept_loop(self):
        while self.running:
            try:
                client_sock, address = self.server_socket.accept()
                session = ClientSession(socket=client_sock, address=address)
                with self.lock:
                    self.sessions.append(session)
                threading.Thread(target=self._client_loop, args=(session,), daemon=True).start()
            except OSError:
                break
            except Exception as exc:
                logging.error("broker accept 异常: %s", exc)
                time.sleep(0.5)

    def _drop_session(self, session: ClientSession):
        with self.lock:
            if session in self.sessions:
                self.sessions.remove(session)
        try:
            session.socket.close()
        except Exception:
            pass
        logging.info("🔌 客户端断开: %s %s", session.client_id or "-", session.address)

    def _client_loop(self, session: ClientSession):
        sock = session.socket
        sock.settimeout(120)
        logging.info("👤 客户端接入: %s", session.address)
        try:
            while self.running:
                first = sock.recv(1)
                if not first:
                    break
                packet_type = first[0] >> 4
                remaining_length = read_remaining_length(sock)
                packet = recv_exact(sock, remaining_length)

                if packet_type == 1:
                    if not self._handle_connect(session, packet):
                        break
                elif packet_type == 8:
                    self._handle_subscribe(session, packet)
                elif packet_type == 3:
                    self._handle_publish(session, packet)
                elif packet_type == 12:
                    sock.sendall(build_pingresp())
                elif packet_type == 14:
                    break
                else:
                    logging.debug("忽略未实现 MQTT 包类型: %s", packet_type)
        except (ConnectionError, socket.timeout):
            pass
        except Exception as exc:
            logging.warning("客户端循环异常 %s: %s", session.address, exc)
        finally:
            self._drop_session(session)

    def _handle_connect(self, session: ClientSession, packet: bytes) -> bool:
        protocol_name, offset = decode_utf8(packet, 0)
        if offset + 4 > len(packet):
            raise ValueError("CONNECT 报文过短")
        protocol_level = packet[offset]
        connect_flags = packet[offset + 1]
        _keepalive = struct.unpack("!H", packet[offset + 2: offset + 4])[0]
        offset += 4

        client_id, offset = decode_utf8(packet, offset)
        username = ""
        password = ""

        if connect_flags & 0x04:
            _will_topic, offset = decode_utf8(packet, offset)
            _will_message, offset = decode_utf8(packet, offset)

        if connect_flags & 0x80:
            username, offset = decode_utf8(packet, offset)
        if connect_flags & 0x40:
            password, offset = decode_utf8(packet, offset)

        if protocol_name not in {"MQTT", "MQIsdp"} or protocol_level not in {3, 4}:
            session.socket.sendall(build_connack(0x01))
            return False

        expected_password = self.allowed_users.get(username)
        if self.allowed_users and expected_password is None:
            session.socket.sendall(build_connack(0x05))
            return False
        if expected_password is not None and expected_password != password:
            session.socket.sendall(build_connack(0x05))
            return False

        session.client_id = client_id
        session.username = username
        session.socket.sendall(build_connack(0x00))
        logging.info("✅ 客户端已认证: client_id=%s username=%s", client_id, username)
        return True

    def _handle_subscribe(self, session: ClientSession, packet: bytes):
        if len(packet) < 2:
            raise ValueError("SUBSCRIBE 报文过短")
        packet_id = struct.unpack("!H", packet[:2])[0]
        offset = 2
        granted_qos = 0
        while offset < len(packet):
            topic_filter, offset = decode_utf8(packet, offset)
            if offset >= len(packet):
                raise ValueError("SUBSCRIBE 缺少 QoS")
            _requested_qos = packet[offset]
            offset += 1
            session.subscriptions.add(topic_filter)
            logging.info("📡 客户端订阅: client_id=%s topic=%s", session.client_id, topic_filter)
        session.socket.sendall(build_suback(packet_id, granted_qos))

    def _handle_publish(self, session: ClientSession, packet: bytes):
        topic, offset = decode_utf8(packet, 0)
        payload = packet[offset:]
        logging.info("📨 收到客户端发布: client_id=%s topic=%s", session.client_id, topic)
        self.publish(topic, payload.decode("utf-8", errors="ignore"))


class ExcelReplayServer:
    def __init__(
        self,
        broker: SimpleMQTTBroker,
        pool_dir: Path,
        topic: str,
        interval_seconds: float,
        scan_seconds: float,
    ):
        self.broker = broker
        self.pool_dir = pool_dir
        self.topic = topic
        self.interval_seconds = interval_seconds
        self.scan_seconds = scan_seconds

        self.processed_dir = pool_dir / "processed"
        self.failed_dir = pool_dir / "failed"
        self.queue: Queue[Path] = Queue()
        self.running = False
        self.queued_files: set[str] = set()
        self.current_file: Optional[str] = None
        self.current_index = 0
        self.total_sent = 0
        self.lock = threading.Lock()

    def start(self):
        self.pool_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self.failed_dir.mkdir(parents=True, exist_ok=True)

        self.running = True
        threading.Thread(target=self._scan_loop, daemon=True).start()
        threading.Thread(target=self._publish_loop, daemon=True).start()
        logging.info("✅ Excel 回放服务已启动，池目录: %s", self.pool_dir)

    def stop(self):
        self.running = False

    def _scan_loop(self):
        while self.running:
            try:
                candidates = sorted(
                    [
                        path
                        for path in self.pool_dir.iterdir()
                        if path.is_file() and path.suffix.lower() in {".xlsx", ".xls", ".csv"}
                    ]
                )
                for path in candidates:
                    key = str(path.resolve())
                    if key in self.queued_files:
                        continue
                    self.queue.put(path)
                    self.queued_files.add(key)
                    logging.info("📥 已加入回放队列: %s", path.name)
            except Exception as exc:
                logging.error("扫描池目录失败: %s", exc)
            time.sleep(self.scan_seconds)

    def _publish_loop(self):
        while self.running:
            try:
                path = self.queue.get(timeout=1)
            except Empty:
                continue

            resolved = str(path.resolve())
            try:
                self._replay_file(path)
                self._move_file(path, self.processed_dir)
            except Exception as exc:
                logging.error("❌ 回放失败 %s: %s", path.name, exc)
                self._move_file(path, self.failed_dir)
            finally:
                self.queued_files.discard(resolved)
                with self.lock:
                    self.current_file = None
                    self.current_index = 0

    def _move_file(self, src: Path, target_dir: Path):
        if not src.exists():
            return
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        target = target_dir / f"{src.stem}_{timestamp}{src.suffix}"
        shutil.move(str(src), str(target))
        logging.info("📦 文件已移动到: %s", target)

    def _replay_file(self, path: Path):
        rows = self._load_rows(path)
        if not rows:
            raise ValueError("文件中没有可发布的数据行")

        with self.lock:
            self.current_file = path.name

        logging.info("🚀 开始回放: %s，共 %s 行", path.name, len(rows))

        for index, row in enumerate(rows, start=1):
            if not self.running:
                break

            payload = self._build_payload(row, fallback_seconds=int(time.time()))
            message_text = json.dumps(payload, ensure_ascii=False)
            self.broker.publish(self.topic, message_text)

            with self.lock:
                self.current_index = index
                self.total_sent += 1

            logging.info(
                "🧪 已发布 %s/%s dev=%s time=%s",
                index,
                len(rows),
                payload.get("dev_num", ""),
                payload.get("date", ""),
            )

            if index < len(rows):
                time.sleep(self.interval_seconds)

        logging.info("✅ 回放完成: %s", path.name)

    def _load_rows(self, path: Path) -> List[Dict[str, object]]:
        suffix = path.suffix.lower()
        if suffix == ".csv":
            df = pd.read_csv(path)
        else:
            excel_file = pd.ExcelFile(path)
            preferred_sheet = next((name for name in excel_file.sheet_names if name.strip().lower() == "serial data log"), None)
            sheet_name = preferred_sheet or excel_file.sheet_names[0]
            df = excel_file.parse(sheet_name=sheet_name)

        df = self._normalize_dataframe(df)
        if df.empty:
            return []
        return df.to_dict(orient="records")

    def _normalize_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        renamed: Dict[str, str] = {}
        normalized_name_map = {str(col).strip().lower(): col for col in df.columns}

        for std_name, aliases in COLUMN_ALIASES.items():
            for alias in aliases:
                matched = normalized_name_map.get(str(alias).strip().lower())
                if matched is not None:
                    renamed[matched] = std_name
                    break

        out = df.rename(columns=renamed).copy()
        out = out.dropna(how="all").reset_index(drop=True)
        return out

    def _build_payload(self, row: Dict[str, object], fallback_seconds: int) -> Dict[str, object]:
        dev_num = str(row.get("dev_num") or DEFAULT_DEV_NUM).strip()
        dev_name = str(row.get("dev_name") or DEFAULT_DEV_NAME).strip()
        project_name = str(row.get("project_name") or DEFAULT_PROJECT_NAME).strip()
        project_num = str(row.get("project_num") or DEFAULT_PROJECT_NUM).strip()
        ts_seconds = normalize_time_seconds(row.get("time"), fallback_seconds)

        datas: Dict[str, object] = {}

        def put(prefixed_key: str, value):
            numeric = safe_float(value)
            if numeric is None:
                return
            datas[f"{dev_num}_{prefixed_key}"] = f"{numeric:.2f}"

        put("SNR", row.get("snr"))
        put("RSRP", row.get("rsrp"))
        put("InSideTemp", row.get("in_temp"))
        put("InSideHumi", row.get("in_hum"))
        put("OutSideTemp", row.get("out_temp"))
        put("OutSideHumi", row.get("out_hum"))
        put("PhaseTempA", row.get("phase_temp_a"))
        put("PhaseTempB", row.get("phase_temp_b"))
        put("PhaseTempC", row.get("phase_temp_c"))
        put("MlxMaxTemp", row.get("mlx_max_temp"))
        put("MlxMinTemp", row.get("mlx_min_temp"))
        put("MlxAvgTemp", row.get("mlx_avg_temp"))
        put("InSideBat", row.get("inside_bat"))
        put("OutSideBat", row.get("outside_bat"))

        return {
            "date": str(ts_seconds),
            "project_name": project_name,
            "project_num": project_num,
            "dev_name": dev_name,
            "dev_num": dev_num,
            "datas": datas,
        }

    def snapshot(self) -> Dict[str, object]:
        with self.lock:
            return {
                "current_file": self.current_file,
                "current_index": self.current_index,
                "total_sent": self.total_sent,
                "queued_files": list(self.queued_files),
                "pool_dir": str(self.pool_dir),
                "interval_seconds": self.interval_seconds,
                "topic": self.topic,
            }


def monitor_status(replay_server: ExcelReplayServer):
    while True:
        snapshot = replay_server.snapshot()
        logging.info(
            "📊 状态 current_file=%s row=%s total_sent=%s queue=%s interval=%ss",
            snapshot["current_file"] or "-",
            snapshot["current_index"],
            snapshot["total_sent"],
            len(snapshot["queued_files"]),
            snapshot["interval_seconds"],
        )
        time.sleep(60)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    allowed_users = parse_allowed_users()
    broker = SimpleMQTTBroker(
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        allowed_users=allowed_users,
    )
    broker.start()

    replay_server = ExcelReplayServer(
        broker=broker,
        pool_dir=DEFAULT_POOL_DIR,
        topic=DEFAULT_TOPIC,
        interval_seconds=DEFAULT_INTERVAL_SECONDS,
        scan_seconds=DEFAULT_SCAN_SECONDS,
    )
    replay_server.start()

    threading.Thread(target=monitor_status, args=(replay_server,), daemon=True).start()

    logging.info("=".ljust(72, "="))
    logging.info("本地 Excel → MQTT 模拟服务已启动")
    logging.info("broker      : %s:%s", DEFAULT_HOST, DEFAULT_PORT)
    logging.info("topic       : %s", DEFAULT_TOPIC)
    logging.info("pool_dir    : %s", DEFAULT_POOL_DIR.resolve())
    logging.info("interval    : %ss", DEFAULT_INTERVAL_SECONDS)
    logging.info("mqtt users  : %s", ", ".join(sorted(allowed_users.keys())))
    logging.info("默认设备     : %s (%s)", DEFAULT_DEV_NAME, DEFAULT_DEV_NUM)
    logging.info("把 .xlsx/.xls/.csv 文件丢进池目录后会自动开始回放")
    logging.info("=".ljust(72, "="))

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("收到停止信号，准备退出")
    finally:
        replay_server.stop()
        broker.stop()


if __name__ == "__main__":
    main()
