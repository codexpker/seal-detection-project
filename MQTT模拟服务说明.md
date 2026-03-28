# MQTT 模拟服务说明

用于在公司 MQTT 不可用时，本地模拟：

- Excel / CSV 文件进入池目录
- 服务按固定间隔逐行回放
- 通过本地 MQTT broker 发布到石化主题

## 启动

```bash
python3 mqtt_excel_replay_server.py
```

默认配置：

- broker：`0.0.0.0:21883`
- topic：`/sys/petrochemical/report`
- 池目录：`sim_mqtt_pool`
- 发布间隔：`60` 秒
- 账号：`czxy01~czxy05`
- 密码：`123456`

## 与 reader 联调

把 `reader_petrochemical.py` 里的 MQTT 配置改成：

- `mqtt_broker = "127.0.0.1"`
- `mqtt_port = 21883`
- `mqtt_username = "czxy01"`
- `mqtt_password = "123456"`
- `mqtt_topic = "/sys/petrochemical/report"`

## 放文件

把 `.xlsx`、`.xls` 或 `.csv` 文件放进：

- `sim_mqtt_pool`

处理完成后会自动移动到：

- `sim_mqtt_pool/processed`

失败文件会移动到：

- `sim_mqtt_pool/failed`

## 常用环境变量

```bash
SIM_MQTT_HOST=127.0.0.1
SIM_MQTT_PORT=21883
SIM_MQTT_TOPIC=/sys/petrochemical/report
SIM_POOL_DIR=sim_mqtt_pool
SIM_INTERVAL_SECONDS=60
SIM_DEV_NAME=AHCZ-D1S-26801
SIM_DEV_NUM=848872DC45E1D3F
```

快速测试可把间隔改短：

```bash
SIM_INTERVAL_SECONDS=1 python3 mqtt_excel_replay_server.py
```

## 表头支持

优先识别这些列名别名：

- 时间：`time` / `时间` / `date` / `datetime`
- 设备名：`dev_name` / `设备名称` / `传感器编号`
- 设备编码：`dev_num` / `设备编码` / `传感器编码`
- 内温湿：`in_temp` / `in_hum`
- 外温湿：`out_temp` / `out_hum`
- 三相温度：`phase_temp_a` / `phase_temp_b` / `phase_temp_c`
- 信号：`snr` / `rsrp`

如果 Excel 没有设备名或设备编码，会使用环境变量默认值。

## 批量导库

如果你不想等 MQTT 一分钟一条回放，可以直接批量写数据库：

```bash
python3 bulk_import_excel_to_db.py 你的文件.xlsx
```

常用方式：

```bash
# 单文件导入，导入后每个设备只触发最新一条检测
python3 bulk_import_excel_to_db.py data.xlsx

# 目录批量导入
python3 bulk_import_excel_to_db.py ./excel_dir --glob '*.xlsx'

# 只看解析结果，不写库
python3 bulk_import_excel_to_db.py data.xlsx --dry-run --trigger-mode none

# 导入后不触发检测
python3 bulk_import_excel_to_db.py data.xlsx --trigger-mode none

# 导入后每条都触发检测（量大时会慢）
python3 bulk_import_excel_to_db.py data.xlsx --trigger-mode all
```
