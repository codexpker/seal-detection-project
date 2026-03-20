import json
import time
from datetime import datetime
import paho.mqtt.client as mqtt

# 现场演示专用：仅展示三台设备的数据
# MQTT 配置来自 人工配置文档.md
MQTT_BROKER = "192.168.2.112"
MQTT_PORT = 1883
MQTT_USERNAME = "czxy1"
MQTT_PASSWORD = "123456"
MQTT_TOPIC = "/sys/petrochemical/report"
MQTT_PROTOCOL = mqtt.MQTTv311



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


def extract_display_fields(payload: dict):
    """复用 reader.py 的字段逻辑，仅保留可识别字段"""
    dev_num = payload.get("dev_num", "")
    dev_name = payload.get("dev_name", "")
    device_timestamp = normalize_timestamp_ms(payload.get("date", 0))

    datas_obj = payload.get("datas", {}) if isinstance(payload.get("datas", {}), dict) else {}
    wavevalue_list = payload.get("Wavevalue", [])
    wavevalue_data = wavevalue_list[0] if isinstance(wavevalue_list, list) and wavevalue_list else {}

    # 兼容 datas 使用 dev_num_ 前缀的情况
    prefix = f"{dev_num}_" if dev_num else ""

    def datas_get(key):
        if key in datas_obj:
            return datas_obj.get(key)
        if prefix and f"{prefix}{key}" in datas_obj:
            return datas_obj.get(f"{prefix}{key}")
        return None

    # 仅识别 datas 中的 SNR / RSRP（支持前缀）
    signal_snr = safe_float(datas_get("SNR"))
    signal_rsrp = safe_float(datas_get("RSRP"))

    # 兼容简单/复杂字段命名（Wavevalue优先，其次 datas 前缀键）
    def wave_or_datas(*keys):
        for k in keys:
            if k in wavevalue_data and wavevalue_data.get(k) is not None:
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

    return {
        "dev_num": dev_num,
        "dev_name": dev_name,
        "device_timestamp": device_timestamp,
        "signal_snr": signal_snr,
        "signal_rsrp": signal_rsrp,
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


def on_connect(client, userdata, flags, reasonCode, properties=None):
    if reasonCode == 0:
        print("✅ MQTT连接成功")
        client.subscribe(MQTT_TOPIC)
        print(f"📡 订阅主题: {MQTT_TOPIC}")
    else:
        print(f"❌ MQTT连接失败, 代码: {reasonCode}")


def on_message(client, userdata, msg):
    try:
        raw_payload = msg.payload.decode("utf-8", errors="ignore")
        payload = json.loads(raw_payload)

        data = extract_display_fields(payload)
        dev_num = data.get("dev_num", "")
        if not dev_num:
            return

        ts = datetime.fromtimestamp(data["device_timestamp"] / 1000)

        print("\n" + "=" * 60)
        print(f"设备: {data['dev_name']} ({data['dev_num']})")
        print(f"时间: {ts}")
        print(f"信号: SNR={data['signal_snr']}  RSRP={data['signal_rsrp']}")
        print(f"三相温度: A={data['a_temp']}  B={data['b_temp']}  C={data['c_temp']}")
        print(f"室内环境: 温度={data['in_temp']}  湿度={data['in_hum']}")
        print(f"室外环境: 温度={data['out_temp']}  湿度={data['out_hum']}")
        print(f"MLX: 最大={data['mlx_max_temp']}  最小={data['mlx_min_temp']}  平均={data['mlx_avg_temp']}")
        print("=" * 60)

    except Exception as e:
        print(f"处理消息失败: {e}")


def main():
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
