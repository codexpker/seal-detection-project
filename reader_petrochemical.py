import paho.mqtt.client as mqtt
import json
from datetime import datetime
import mysql.connector
from mysql.connector import Error, pooling
import logging
import threading
import time
import traceback
import sys
import os
import hashlib
import requests

# ---------- 配置信息 ----------
# 本地模拟 / 现场演示 MQTT 配置
#
# 默认连接本地模拟服务：
#   127.0.0.1:21883
#
# 如需切回现场环境，可通过环境变量覆盖：
#   MQTT_BROKER=183.6.64.133
#   MQTT_PORT=21883
#   MQTT_USERNAME=czxy02
#   MQTT_PASSWORD=123456
#   MQTT_CLIENT_ID=czxy02
# 默认使用 czxy01
mqtt_broker = os.getenv("MQTT_BROKER", "127.0.0.1")
mqtt_port = int(os.getenv("MQTT_PORT", "21883"))
mqtt_username = os.getenv("MQTT_USERNAME", "czxy01")
mqtt_password = os.getenv("MQTT_PASSWORD", "123456")
mqtt_topic = os.getenv("MQTT_TOPIC", "/sys/petrochemical/report")
# 该 broker 使用 MQTT v3.1.1 更稳妥
mqtt_protocol = mqtt.MQTTv311
backend_base_url = "http://127.0.0.1:8000"
auto_trigger_enabled = True

# 现场传感器台账（按图片信息）
sensor_registry = {
    "AHCZ-D1S-26801": "848872DC45E1D3F",
    "AHCZ-D1S-26802": "848872DC45DDF49",
    "AHCZ-D1S-26803": "848872DC45E5A3E",
    "AHCZ-D1S-26804": "848872DC45D9341",
}

sensor_registry_by_code = {code: name for name, code in sensor_registry.items()}

# MySQL 配置
mysql_config = {
    'host': 'localhost',
    'user': 'root',
    'password': 'xpker1234',
    'database': 'bst',
    'pool_name': 'mqtt_pool',
    'pool_size': 5,
    'pool_reset_session': True,
    'autocommit': True
}


# ---------- 全局统计 ----------
class MessageStats:
    def __init__(self):
        self.total_messages = 0
        self.success_saves = 0
        self.failed_saves = 0
        self.lock = threading.Lock()

    def add_message(self):
        with self.lock:
            self.total_messages += 1

    def add_success(self):
        with self.lock:
            self.success_saves += 1

    def add_failure(self):
        with self.lock:
            self.failed_saves += 1

    def get_stats(self):
        with self.lock:
            return {
                'total': self.total_messages,
                'success': self.success_saves,
                'failed': self.failed_saves
            }


# 创建全局实例
message_stats = MessageStats()


# ---------- MQTT去重（连续重复压缩 + 心跳保留） ----------
DEDUP_HEARTBEAT_SECONDS = 300  # 5分钟：连续重复值至少保留一条心跳样本
_recent_payload_fingerprints = {}
_dedup_lock = threading.Lock()


# ---------- 全局异常处理器 ----------
def setup_global_exception_handler():
    """设置全局异常处理器"""

    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            # 键盘中断，正常退出
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        logging.error("‼️ 未捕获的全局异常:", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = handle_exception


# ---------- MySQL 连接管理器 ----------
class MySQLConnectionManager:
    """MySQL连接管理器，支持自动重连"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_manager()
            return cls._instance

    def _init_manager(self):
        """初始化连接管理器"""
        self.connection_pool = None
        self.last_check_time = time.time()
        self.init_connection_pool()
        self.start_health_check()
        logging.info("✅ MySQL连接管理器初始化完成")

    def init_connection_pool(self):
        """初始化连接池"""
        try:
            self.connection_pool = pooling.MySQLConnectionPool(**mysql_config)
            logging.debug("MySQL连接池初始化成功")
            return True
        except Error as e:
            logging.error(f"❌ MySQL连接池初始化失败: {e}")
            self.connection_pool = None
            return False

    def get_connection(self):
        """获取数据库连接"""
        try:
            if not self.connection_pool:
                if not self.init_connection_pool():
                    return None

            connection = self.connection_pool.get_connection()
            if connection.is_connected():
                return connection
        except Error as e:
            logging.warning(f"从连接池获取连接失败: {e}")

        # 如果连接池获取失败，尝试直接连接
        try:
            config_copy = mysql_config.copy()
            # 移除连接池专用参数
            for key in ['pool_name', 'pool_size', 'pool_reset_session']:
                config_copy.pop(key, None)

            connection = mysql.connector.connect(**config_copy)
            if connection.is_connected():
                logging.debug("使用直接连接（连接池异常）")
                return connection
        except Error as e:
            logging.error(f"直接连接也失败: {e}")

        return None

    def check_connection(self):
        """检查连接是否可用 - 简化版本"""
        try:
            # 直接使用简单连接测试
            config_copy = mysql_config.copy()
            for key in ['pool_name', 'pool_size', 'pool_reset_session']:
                config_copy.pop(key, None)

            connection = mysql.connector.connect(**config_copy)
            if connection.is_connected():
                connection.close()
                return True
        except:
            pass
        return False

    def start_health_check(self):
        """启动健康检查线程"""

        def health_check():
            consecutive_failures = 0
            last_report_time = 0

            while True:
                try:
                    current_time = time.time()
                    # 每30秒检查一次
                    if current_time - self.last_check_time >= 30:
                        self.last_check_time = current_time

                        if self.check_connection():
                            if consecutive_failures > 0:
                                logging.info("✅ MySQL连接已恢复")
                                consecutive_failures = 0
                        else:
                            consecutive_failures += 1
                            # 连续失败3次才报警（间隔90秒）
                            if consecutive_failures >= 3 and (current_time - last_report_time) > 90:
                                logging.warning("⚠️ MySQL连接检查失败，尝试重新初始化...")
                                self.init_connection_pool()
                                last_report_time = current_time

                    time.sleep(10)  # 每10秒检查一次循环

                except Exception as e:
                    logging.debug(f"健康检查线程异常: {e}")
                    time.sleep(30)

        thread = threading.Thread(target=health_check, daemon=True)
        thread.start()
        logging.debug("MySQL健康检查线程已启动")


# ---------- 数据格式检测 ----------
def detect_data_format(wavevalue_data):
    """
    检测数据格式类型
    返回: 1=简单格式, 2=复杂格式
    """
    if not wavevalue_data:
        return 1

    try:
        # 检查是否包含复杂格式的特有字段
        complex_fields = ['InSideHumi', 'InSideTemp', 'OutSideHumi', 'OutSideTemp']
        for field in complex_fields:
            if field in wavevalue_data:
                return 2

        return 1
    except:
        return 1


def detect_data_format_from_sources(wavevalue_data, datas_obj, prefix_candidates=None):
    """同时兼容旧 Wavevalue 与新 datas 前缀格式"""
    if prefix_candidates is None:
        prefix_candidates = []

    if detect_data_format(wavevalue_data) == 2:
        return 2

    complex_fields = ['InSideHumi', 'InSideTemp', 'OutSideHumi', 'OutSideTemp']

    if isinstance(datas_obj, dict):
        for field in complex_fields:
            if field in datas_obj:
                return 2

            for prefix in prefix_candidates:
                if prefix and f"{prefix}_{field}" in datas_obj:
                    return 2

        for key in datas_obj.keys():
            for field in complex_fields:
                if key.endswith(f"_{field}"):
                    return 2

    return 1


# ---------- 数据提取和映射 ----------
def build_payload_fingerprint(data):
    """保留旧入口，兼容调用"""
    try:
        canonical = dict(data) if isinstance(data, dict) else {}
        canonical.pop('date', None)
        raw = json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        return hashlib.sha1(raw.encode('utf-8')).hexdigest()
    except Exception:
        return ''


def build_db_data_fingerprint(db_data):
    """按业务字段计算指纹，避免 MQTT 附带噪声字段导致去重失效"""
    try:
        canonical = {
            'dev_num': db_data.get('dev_num'),
            'data_format': db_data.get('data_format'),
            'device_type': db_data.get('device_type'),
            'a_temp': db_data.get('a_temp'),
            'b_temp': db_data.get('b_temp'),
            'c_temp': db_data.get('c_temp'),
            'in_temp': db_data.get('in_temp'),
            'in_hum': db_data.get('in_hum'),
            'out_temp': db_data.get('out_temp'),
            'out_hum': db_data.get('out_hum'),
            'mlx_max_temp': db_data.get('mlx_max_temp'),
            'mlx_min_temp': db_data.get('mlx_min_temp'),
            'mlx_avg_temp': db_data.get('mlx_avg_temp'),
        }
        raw = json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        return hashlib.sha1(raw.encode('utf-8')).hexdigest()
    except Exception:
        return ''


def should_keep_payload(dev_num, fingerprint, ts_ms):
    """
    连续重复压缩策略：
    - 签名变化：立即保留
    - 签名不变：仅当距离上次保留 >= 心跳窗口(默认5分钟)时保留一条
    """
    if not dev_num or not fingerprint:
        return True

    with _dedup_lock:
        item = _recent_payload_fingerprints.get(dev_num)
        if not item:
            _recent_payload_fingerprints[dev_num] = {
                'fp': fingerprint,
                'last_seen_ts': ts_ms,
                'last_kept_ts': ts_ms,
            }
            return True

        last_fp = item.get('fp')
        last_kept_ts = int(item.get('last_kept_ts', 0))

        # 先更新最后看到时间
        item['last_seen_ts'] = ts_ms

        # 业务值变化：立即保留并重置基准
        if last_fp != fingerprint:
            item['fp'] = fingerprint
            item['last_kept_ts'] = ts_ms
            return True

        # 业务值未变化：到达心跳窗口才保留一条
        if ts_ms - last_kept_ts >= DEDUP_HEARTBEAT_SECONDS * 1000:
            item['last_kept_ts'] = ts_ms
            return True

        # 轻量清理，避免内存持续增长
        if len(_recent_payload_fingerprints) > 5000:
            threshold = ts_ms - 24 * 60 * 60 * 1000
            for k in list(_recent_payload_fingerprints.keys()):
                if int(_recent_payload_fingerprints[k].get('last_seen_ts', 0)) < threshold:
                    _recent_payload_fingerprints.pop(k, None)

    return False


def extract_device_data(raw_json):
    """从原始JSON中提取并映射数据"""
    try:
        # 解析JSON
        data = json.loads(raw_json)

        # 获取Wavevalue数据
        wavevalue_list = data.get('Wavevalue', [])
        if not isinstance(wavevalue_list, list) or len(wavevalue_list) == 0:
            wavevalue_data = {}
        else:
            wavevalue_data = wavevalue_list[0]

        # 优先解析设备标识
        dev_num = str(
            data.get('dev_num')
            or data.get('device_code')
            or data.get('sensor_code')
            or data.get('imei')
            or ''
        ).strip()
        dev_name = str(
            data.get('dev_name')
            or data.get('sensor_name')
            or data.get('sensor_num')
            or sensor_registry_by_code.get(dev_num, '')
            or ''
        ).strip()

        # 处理datas部分
        datas_obj = data.get('datas', {})
        if not isinstance(datas_obj, dict):
            datas_obj = {}
        datas_json = json.dumps(datas_obj) if datas_obj else None

        # 处理Wavevalue部分
        wavevalue_json = json.dumps(wavevalue_list) if wavevalue_list else None

        prefix_candidates = []
        for candidate in [dev_num, dev_name, sensor_registry.get(dev_name, ''), data.get('sensor_code', '')]:
            candidate = str(candidate or '').strip()
            if candidate and candidate not in prefix_candidates:
                prefix_candidates.append(candidate)

        def datas_get(key):
            if key in datas_obj:
                return datas_obj.get(key)

            for prefix in prefix_candidates:
                composed_key = f"{prefix}_{key}"
                if composed_key in datas_obj:
                    return datas_obj.get(composed_key)

            for existing_key, existing_value in datas_obj.items():
                if existing_key.endswith(f"_{key}"):
                    return existing_value

            return None

        def wave_or_datas(*keys):
            for key in keys:
                if key in wavevalue_data and wavevalue_data.get(key) is not None:
                    return wavevalue_data.get(key)

                prefixed_value = datas_get(key)
                if prefixed_value is not None:
                    return prefixed_value

            return None

        # 检测数据格式
        data_format = detect_data_format_from_sources(wavevalue_data, datas_obj, prefix_candidates)

        # 构建设备时间戳（统一毫秒）
        normalized_ts = normalize_timestamp_ms(data.get('date', 0))

        # 构建基础数据字典
        db_data = {
            'data_format': data_format,
            'project_name': data.get('project_name', ''),
            'project_num': data.get('project_num', ''),
            'dev_name': dev_name,
            'dev_num': dev_num,
            'signal_snr': safe_float(datas_get('SNR')),
            'signal_rsrp': safe_float(datas_get('RSRP')),
            'device_timestamp': normalized_ts,
            'raw_json': raw_json,
            'datas_json': datas_json,
            'wavevalue_json': wavevalue_json
        }

        # 根据数据格式映射字段
        if data_format == 1:  # 简单格式
            db_data.update({
                'device_type': 1,
                'a_temp': safe_float(wave_or_datas('Atemp', 'PhaseTempA')),
                'b_temp': safe_float(wave_or_datas('Btemp', 'PhaseTempB')),
                'c_temp': safe_float(wave_or_datas('Ctemp', 'PhaseTempC')),
                'in_temp': safe_float(wave_or_datas('Htemp', 'InSideTemp')),
                'in_hum': safe_float(wave_or_datas('Hdamp', 'InSideHumi')),
                'out_temp': None,
                'out_hum': None,
                'mlx_max_temp': None,
                'mlx_min_temp': None,
                'mlx_avg_temp': None
            })

        elif data_format == 2:  # 复杂格式
            db_data.update({
                'device_type': 2,
                'a_temp': safe_float(wave_or_datas('PhaseTempA', 'Atemp')),
                'b_temp': safe_float(wave_or_datas('PhaseTempB', 'Btemp')),
                'c_temp': safe_float(wave_or_datas('PhaseTempC', 'Ctemp')),
                'in_temp': safe_float(wave_or_datas('InSideTemp', 'Htemp')),
                'in_hum': safe_float(wave_or_datas('InSideHumi', 'Hdamp')),
                'out_temp': safe_float(wave_or_datas('OutSideTemp')),
                'out_hum': safe_float(wave_or_datas('OutSideHumi')),
                'mlx_max_temp': safe_float(wave_or_datas('MlxMaxTemp')),
                'mlx_min_temp': safe_float(wave_or_datas('MlxMinTemp')),
                'mlx_avg_temp': safe_float(wave_or_datas('MlxAvgTemp'))
            })

        return db_data

    except Exception as e:
        logging.error(f"提取数据失败: {e}")
        return None


def safe_float(value, default=None):
    """安全转换为float"""
    if value is None:
        return default
    try:
        return float(value)
    except:
        return default


def normalize_timestamp_ms(value):
    """统一设备时间戳为毫秒（兼容秒/毫秒/字符串）"""
    try:
        if value is None:
            return int(time.time() * 1000)
        ts = int(float(value))
        if ts <= 0:
            return int(time.time() * 1000)
        # 10位通常是秒级，转换为毫秒
        if ts < 1_000_000_000_000:
            ts *= 1000
        return ts
    except Exception:
        return int(time.time() * 1000)


# ---------- MySQL 操作 ----------
def trigger_detection(dev_num, device_timestamp):
    if not auto_trigger_enabled:
        return True

    try:
        url = f"{backend_base_url}/api/internal/process/{dev_num}/{int(device_timestamp)}?queued=1"
        resp = requests.post(url, timeout=1.2)
        if resp.status_code == 200:
            logging.info(f"🔁 自动触发检测成功: {dev_num}@{device_timestamp}")
            return True
        logging.warning(f"自动触发检测失败: status={resp.status_code}, body={resp.text[:200]}")
    except Exception as e:
        logging.warning(f"自动触发检测异常: {e}")
    return False


def save_to_mysql_with_retry(db_manager, db_data, max_retries=2):
    """将数据保存到MySQL（带重试）"""
    if not db_manager or not db_data:
        return False

    for attempt in range(max_retries):
        try:
            connection = db_manager.get_connection()
            if not connection:
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                return False

            cursor = connection.cursor()

            # 构建插入SQL
            columns = ', '.join(db_data.keys())
            placeholders = ', '.join(['%s'] * len(db_data))

            # 排除唯一约束字段
            update_columns = []
            for col in db_data.keys():
                if col not in ['dev_num', 'device_timestamp']:
                    update_columns.append(f"{col} = VALUES({col})")

            updates = ', '.join(update_columns)

            sql = f"""
            INSERT INTO device_monitoring_data ({columns})
            VALUES ({placeholders})
            ON DUPLICATE KEY UPDATE {updates}, updated_at = NOW()
            """

            # 执行插入
            values = tuple(db_data.values())
            cursor.execute(sql, values)

            record_id = cursor.lastrowid
            cursor.close()
            connection.close()

            if record_id:
                logging.info(f"💾 数据保存成功 (ID: {record_id})")
            else:
                logging.debug("数据已存在（重复记录）")

            return True

        except Error as e:
            if attempt < max_retries - 1:
                logging.debug(f"保存失败，重试 {attempt + 1}/{max_retries}: {e}")
                time.sleep(1)
            else:
                logging.error(f"❌ 保存失败: {e}")
        except Exception as e:
            logging.error(f"保存数据时发生未知错误: {e}")
            break

    return False


# ---------- MQTT 回调函数（兼容不同版本） ----------
def build_client_id(prefix="petrochemical_sub"):
    """生成唯一 client_id，避免同 ID 互踢导致反复断连"""
    configured_client_id = os.getenv("MQTT_CLIENT_ID", "").strip()
    if configured_client_id:
        return configured_client_id
    return f"{prefix}_{os.getpid()}"


def on_connect(client, userdata, flags, reasonCode, properties=None):
    """连接回调 - 兼容不同MQTT版本"""
    try:
        if reasonCode == 0:
            logging.info("✅ 连接到MQTT服务器")
            client.subscribe(mqtt_topic)
            logging.info(f"📡 订阅主题: {mqtt_topic}")
        else:
            logging.error(f"❌ 连接失败, 代码: {reasonCode}")
    except Exception as e:
        logging.error(f"连接回调异常: {e}")


def on_message(client, userdata, msg):
    """处理接收到的MQTT消息"""
    # 更新消息计数
    message_stats.add_message()

    try:
        raw_payload = msg.payload.decode("utf-8", errors='ignore')
        logging.info(f"\n📨 收到消息 from: {msg.topic}")

        # 提取并映射数据
        db_data = extract_device_data(raw_payload)
        if not db_data:
            logging.error("数据提取失败")
            message_stats.add_failure()
            return

        # 显示关键信息
        format_name = "简单格式" if db_data['data_format'] == 1 else "复杂格式"
        device_alias = sensor_registry_by_code.get(db_data['dev_num'], '')
        if device_alias and not db_data['dev_name']:
            db_data['dev_name'] = device_alias

        logging.info(f"设备: {db_data['dev_name']} ({db_data['dev_num']})")
        logging.info(f"格式: {format_name}")

        try:
            time_str = datetime.fromtimestamp(db_data['device_timestamp'] / 1000)
            logging.info(f"时间: {time_str}")
        except:
            logging.info(f"时间戳: {db_data['device_timestamp']}")

        # 连续重复压缩 + 心跳保留（避免重复写库与重复触发）
        fp = build_db_data_fingerprint(db_data)
        if not should_keep_payload(db_data.get('dev_num', ''), fp, db_data.get('device_timestamp', 0)):
            logging.info(
                f"⏭️ 连续重复已压缩(心跳{DEDUP_HEARTBEAT_SECONDS}s): "
                f"{db_data.get('dev_num', '')}@{db_data.get('device_timestamp', 0)}"
            )
            return

        if db_data['data_format'] == 1:
            logging.info(f"三相温度: A={db_data['a_temp']}, B={db_data['b_temp']}, C={db_data['c_temp']}")
            logging.info(f"室内环境: 温度={db_data['in_temp']}, 湿度={db_data['in_hum']}")
        else:
            logging.info(f"三相温度: A={db_data['a_temp']}, B={db_data['b_temp']}, C={db_data['c_temp']}")
            logging.info(f"室内环境: 温度={db_data['in_temp']}, 湿度={db_data['in_hum']}")
            logging.info(f"室外环境: 温度={db_data['out_temp']}, 湿度={db_data['out_hum']}")
            logging.info(
                f"MLX: 最大={db_data['mlx_max_temp']}, 最小={db_data['mlx_min_temp']}, 平均={db_data['mlx_avg_temp']}")

        # 保存到数据库
        if 'mysql_manager' in userdata and userdata['mysql_manager']:
            if save_to_mysql_with_retry(userdata['mysql_manager'], db_data):
                message_stats.add_success()
                trigger_detection(db_data.get('dev_num', ''), db_data.get('device_timestamp', 0))
            else:
                message_stats.add_failure()
        else:
            logging.warning("MySQL管理器不可用")
            message_stats.add_failure()

    except Exception as e:
        logging.error(f"处理消息时出错: {e}")
        message_stats.add_failure()


# 定义兼容不同MQTT版本的断开连接回调
def on_disconnect_generic(*args, **kwargs):
    """通用断开连接回调，兼容 paho-mqtt v1/v2 的参数差异"""
    try:
        # v1 常见: (client, userdata, rc)
        # v2 常见: (client, userdata, disconnect_flags, reason_code, properties)
        if len(args) >= 5:
            client, userdata, disconnect_flags, reason_code, properties = args[:5]
            rc = int(reason_code) if isinstance(reason_code, int) or str(reason_code).isdigit() else str(reason_code)
            if rc == 0:
                logging.info("MQTT连接正常断开")
            else:
                logging.warning(f"MQTT连接断开，reason_code: {reason_code}, flags: {disconnect_flags}")
                logging.info("已交由客户端自动重连")
            return

        if len(args) >= 3:
            client, userdata, rc = args[:3]
            if rc == 0:
                logging.info("MQTT连接正常断开")
            else:
                logging.warning(f"MQTT连接断开，代码: {rc}")
                logging.info("已交由客户端自动重连")
            return

        logging.error(f"未知的断开连接回调参数数量: {len(args)}")

    except Exception as e:
        logging.error(f"断开连接回调异常: {e}")


# ---------- 程序状态监控 ----------
def monitor_program_status():
    """监控程序状态"""
    start_time = time.time()

    while True:
        try:
            current_time = time.time()
            uptime = current_time - start_time
            hours = int(uptime // 3600)
            minutes = int((uptime % 3600) // 60)
            seconds = int(uptime % 60)

            stats = message_stats.get_stats()

            logging.info(f"\n📊 程序状态报告:")
            logging.info(f"   运行时间: {hours}小时 {minutes}分钟 {seconds}秒")
            logging.info(f"   接收消息: {stats['total']}条")
            logging.info(f"   成功保存: {stats['success']}条")
            logging.info(f"   保存失败: {stats['failed']}条")

            if stats['total'] > 0:
                success_rate = stats['success'] / stats['total'] * 100
                logging.info(f"   保存成功率: {success_rate:.1f}%")

            time.sleep(300)
        except Exception as e:
            logging.error(f"状态监控异常: {e}")
            time.sleep(300)


# ---------- 主程序 ----------
def main():
    # 设置全局异常处理器
    setup_global_exception_handler()

    # 配置日志（添加文件输出确保日志不丢失）
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.StreamHandler(),  # 输出到控制台
            logging.FileHandler('mqtt_reader.log', encoding='utf-8', mode='a')  # 输出到文件
        ]
    )

    logging.info("=" * 60)
    logging.info("🚀 MQTT石化主题采集程序启动")
    logging.info("=" * 60)

    # 初始化MySQL连接管理器
    mysql_manager = MySQLConnectionManager()

    # 尝试不同的MQTT客户端配置
    try:
        client_id = build_client_id("petrochemical_sub")

        # 方案1：使用回调API版本2（最新）
        try:
            client = mqtt.Client(
                client_id=client_id,
                protocol=mqtt_protocol,
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                userdata={'mysql_manager': mysql_manager}
            )
            logging.info(f"✅ 使用MQTT回调API版本2，client_id={client_id}")
        except AttributeError:
            # 方案2：使用回调API版本1
            client = mqtt.Client(
                client_id=client_id,
                protocol=mqtt_protocol,
                userdata={'mysql_manager': mysql_manager}
            )
            logging.info(f"✅ 使用MQTT回调API版本1，client_id={client_id}")
        except Exception:
            # 方案3：使用默认配置
            client = mqtt.Client(
                client_id=client_id,
                userdata={'mysql_manager': mysql_manager}
            )
            logging.info(f"✅ 使用MQTT默认配置，client_id={client_id}")

    except Exception as e:
        logging.error(f"创建MQTT客户端失败: {e}")
        return

    # 设置回调函数
    client.username_pw_set(mqtt_username, mqtt_password)
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect_generic  # 使用通用回调

    # 设置重连参数
    client.reconnect_delay_set(min_delay=1, max_delay=120)

    # 启动状态监控线程
    try:
        monitor_thread = threading.Thread(target=monitor_program_status, daemon=True)
        monitor_thread.start()
        logging.info("✅ 状态监控线程已启动")
    except Exception as e:
        logging.error(f"启动状态监控失败: {e}")

    # 设置程序运行标志
    running = True

    def signal_handler(signum, frame):
        nonlocal running
        logging.info("\n收到停止信号，正在关闭程序...")
        running = False

    try:
        import signal
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    except:
        pass

    try:
        # 连接MQTT
        logging.info(f"🔗 连接到MQTT服务器: {mqtt_broker}:{mqtt_port}")

        # 设置连接超时
        client.connect(mqtt_broker, mqtt_port, 60)
        logging.info("🚀 MQTT客户端启动，等待消息...")

        # 使用网络线程自动维护连接（包含自动重连）
        client.loop_start()

        # 主循环：仅维持进程，不手动调用 reconnect，避免重连风暴
        while running:
            time.sleep(1)

    except KeyboardInterrupt:
        logging.info("\n🛑 程序被用户中断")
    except Exception as e:
        logging.error(f"❌ MQTT连接错误: {e}")
        logging.error(f"详细错误信息: {traceback.format_exc()}")
    finally:
        logging.info("🧹 清理资源...")
        try:
            client.loop_stop()
            client.disconnect()
            logging.info("✅ MQTT连接已关闭")
        except:
            pass


if __name__ == "__main__":
    main()
