import argparse
import json
import time
from datetime import datetime

import paho.mqtt.client as mqtt

try:
    import mysql.connector
    from mysql.connector import Error
except Exception:
    mysql = None
    Error = Exception


# 现场演示专用
# MQTT 配置来自 人工配置文档.md
MQTT_BROKER = "192.168.2.112"
MQTT_PORT = 1883
MQTT_USERNAME = "czxy1"
MQTT_PASSWORD = "123456"
MQTT_TOPIC = "/sys/petrochemical/report"
MQTT_PROTOCOL = mqtt.MQTTv311

# 数据库配置（与 reader.py 一致）
MYSQL_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "xpker1234",
    "database": "bst",
    "autocommit": True,
}

SAVE_TO_DB = False


def safe_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def normalize_timestamp_ms(value):
    try:
        if value is None:
            return int(time.time() * 1000)
        ts = int(float(value))
        if ts <= 0:
            return int(time.time() * 1000)
        if ts < 1_000_000_000_000:
            ts *= 1000
        return ts
    except Exception:
        return int(time.time() * 1000)


def extract_db_fields(payload: dict, raw_payload: str):
    """按数据库字段映射解析示例数据格式。"""
    dev_num = payload.get("dev_num", "")
    dev_name = payload.get("dev_name", "")
    device_timestamp = normalize_timestamp_ms(payload.get("date", 0))

    datas_obj = payload.get("datas", {}) if isinstance(payload.get("datas", {}), dict) else {}
    wavevalue_list = payload.get("Wavevalue", [])
    wavevalue_data = wavevalue_list[0] if isinstance(wavevalue_list, list) and wavevalue_list else {}

    # 兼容 datas 使用 dev_num_ 前缀键
    prefix = f"{dev_num}_" if dev_num else ""

    def datas_get(key):
        if key in datas_obj:
            return datas_obj.get(key)
        prefixed_key = f"{prefix}{key}"
        if prefix and prefixed_key in datas_obj:
            return datas_obj.get(prefixed_key)
        return None

    def wave_or_datas(*keys):
        for k in keys:
            if isinstance(wavevalue_data, dict) and k in wavevalue_data and wavevalue_data.get(k) is not None:
                return wavevalue_data.get(k)
            v = datas_get(k)
            if v is not None:
                return v
        return None

    a_temp = safe_float(wave_or_datas("Atemp", "PhaseTempA"))
    b_temp = safe_float(wave_or_datas("Btemp", "PhaseTempB"))
    c_temp = safe_float(wave_or_datas("Ctemp", "PhaseTempC"))
    in_temp = safe_float(wave_or_datas("Htemp", "InSideTemp"))
    in_hum = safe_float(wave_or_datas("Hdamp", "InSideHumi"))
    out_temp = safe_float(wave_or_datas("OutSideTemp"))
    out_hum = safe_float(wave_or_datas("OutSideHumi"))
    mlx_max_temp = safe_float(wave_or_datas("MlxMaxTemp"))
    mlx_min_temp = safe_float(wave_or_datas("MlxMinTemp"))
    mlx_avg_temp = safe_float(wave_or_datas("MlxAvgTemp"))

    # 对该示例格式，按复杂格式处理
    data_format = 2
    device_type = 2

    return {
        "data_format": data_format,
        "project_name": payload.get("project_name", ""),
        "project_num": payload.get("project_num", ""),
        "dev_name": dev_name,
        "dev_num": dev_num,
        "signal_snr": safe_float(datas_get("SNR")),
        "signal_rsrp": safe_float(datas_get("RSRP")),
        "device_timestamp": device_timestamp,
        "raw_json": raw_payload,
        "datas_json": json.dumps(datas_obj, ensure_ascii=False) if datas_obj else None,
        "wavevalue_json": json.dumps(wavevalue_list, ensure_ascii=False) if wavevalue_list else None,
        "device_type": device_type,
        "a_temp": a_temp,
        "b_temp": b_temp,
        "c_temp": c_temp,
        "in_temp": in_temp,
        "in_hum": in_hum,
        "out_temp": out_temp,
        "out_hum": out_hum,
        "mlx_max_temp": mlx_max_temp,
        "mlx_min_temp": mlx_min_temp,
        "mlx_avg_temp": mlx_avg_temp,
    }


def save_to_mysql(db_data: dict):
    if not SAVE_TO_DB:
        return True

    if mysql is None:
        print("❌ 未安装 mysql-connector-python，无法落库")
        return False

    try:
        connection = mysql.connector.connect(**MYSQL_CONFIG)
        cursor = connection.cursor()

        columns = ", ".join(db_data.keys())
        placeholders = ", ".join(["%s"] * len(db_data))

        update_columns = []
        for col in db_data.keys():
            if col not in ["dev_num", "device_timestamp"]:
                update_columns.append(f"{col}=VALUES({col})")

        sql = f"""
        INSERT INTO device_monitoring_data ({columns})
        VALUES ({placeholders})
        ON DUPLICATE KEY UPDATE {', '.join(update_columns)}, updated_at=NOW()
        """

        cursor.execute(sql, tuple(db_data.values()))
        connection.commit()

        cursor.close()
        connection.close()
        return True
    except Error as e:
        print(f"❌ 落库失败: {e}")
        return False


def on_connect(client, userdata, flags, reasonCode, properties=None):
    if reasonCode == 0:
        print("✅ MQTT连接成功")
        client.subscribe(MQTT_TOPIC)
        print(f"📡 订阅主题: {MQTT_TOPIC}")
        print(f"💾 数据库落库: {'开启' if SAVE_TO_DB else '关闭'}")
    else:
        print(f"❌ MQTT连接失败, 代码: {reasonCode}")


def on_message(client, userdata, msg):
    try:
        raw_payload = msg.payload.decode("utf-8", errors="ignore")
        payload = json.loads(raw_payload)

        db_data = extract_db_fields(payload, raw_payload)
        if not db_data.get("dev_num"):
            return

        ts = datetime.fromtimestamp(db_data["device_timestamp"] / 1000)
        print("\n" + "=" * 70)
        print(f"设备: {db_data['dev_name']} ({db_data['dev_num']})")
        print(f"时间: {ts}")
        print(f"信号: SNR={db_data['signal_snr']}  RSRP={db_data['signal_rsrp']}")
        print(f"三相温度: A={db_data['a_temp']}  B={db_data['b_temp']}  C={db_data['c_temp']}")
        print(f"室内环境: 温度={db_data['in_temp']}  湿度={db_data['in_hum']}")
        print(f"室外环境: 温度={db_data['out_temp']}  湿度={db_data['out_hum']}")
        print(f"MLX: 最大={db_data['mlx_max_temp']}  最小={db_data['mlx_min_temp']}  平均={db_data['mlx_avg_temp']}")

        if save_to_mysql(db_data):
            if SAVE_TO_DB:
                print("✅ 已落库 device_monitoring_data")
        else:
            print("⚠️ 本条消息落库失败")
        print("=" * 70)

    except Exception as e:
        print(f"处理消息失败: {e}")


def main():
    global SAVE_TO_DB

    parser = argparse.ArgumentParser(description="现场MQTT演示脚本（支持可选落库）")
    parser.add_argument("--save-db", action="store_true", help="开启写入 MySQL device_monitoring_data")
    args = parser.parse_args()
    SAVE_TO_DB = args.save_db

    try:
        client = mqtt.Client(protocol=MQTT_PROTOCOL)
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        client.on_connect = on_connect
        client.on_message = on_message

        print(f"🔗 连接到MQTT: {MQTT_BROKER}:{MQTT_PORT}")
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n🛑 已停止")
    except Exception as e:
        print(f"❌ 连接异常: {e}")


if __name__ == "__main__":
    main()
