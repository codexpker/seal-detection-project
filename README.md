# Seal Detection Project

电机接线盒密封性异常检测系统（FastAPI + Vue3 + MySQL）。

## 当前状态（2026-03）

已完成并验证主链路：

1. MQTT 入库（`reader.py`）
2. 自动触发检测（后端排队处理）
3. 检测结果落库（`detection_result_log`）
4. 首页/诊断页 SSE 实时展示
5. 故障专档落库与查询（`fault_archive`）

近期关键调整：

- 设备轮播改为“事件流”语义（按最新检测事件时间排序）
- 首页轮播点击设备号可跳转设备查询并自动执行查询
- 设备查询支持锚点时间 `end_ts`，可对齐首页实时片段
- 高频处理下不再丢“最新事件”（节流命中会回写待处理队列）
- MQTT 去重改为“连续重复压缩 + 5 分钟心跳保留”

---

## 项目结构（核心）

```text
seal_detection_project/
├── backend_app.py                 # FastAPI 主服务
├── reader.py                      # MQTT 消息入库与触发检测
├── migration_mvp_backend.sql      # 数据库初始化脚本
├── requirements.txt               # Python 依赖
├── package.json                   # 前端依赖
├── src/
│   ├── App.vue                    # 前端主页面
│   ├── api.js                     # 前端 API 封装
│   ├── styles.css                 # 全局样式
│   ├── components/TrendChart.vue  # 曲线组件
│   └── anomaly_v2/
│       ├── baseline.py            # 二期 baseline：特征/统计分数/相似度/融合
│       ├── state_machine.py       # 事件迟滞状态机
│       └── pipeline.py            # 二期主流程编排（被 backend_app 调用）
└── docs/
    ├── 技术沉淀文档.md
    ├── 项目说明文档.md
    └── 后续扩展TODO.md
```

---

## 快速启动

### 1) 安装依赖

```bash
pip install -r requirements.txt
npm install
```

### 2) 初始化数据库（首次）

```bash
mysql -u root -p bst < migration_mvp_backend.sql
```

### 3) 启动后端

```bash
python3 -m uvicorn backend_app:app --host 0.0.0.0 --port 8000 --reload
```

> 当前仓库默认没有独立 `model_service` 进程入口。若仅联调二期 v2，建议显式关闭一期模型调用：

```bash
export MODEL_SERVICE_ENABLED=false
```

### 4) 启动前端

```bash
npm run dev
```

### 5) 启动 MQTT 读入（可选）

```bash
python3 reader.py
```

---

## 常用接口

### 健康与运行
- `GET /api/health`
- `GET /api/runtime/metrics`

### 首页与轮播
- `GET /api/home/current`
- `GET /api/home/stream`
- `GET /api/home/device-ticker`

### 设备查询
- `GET /api/device/detail/{dev_num}?hours=48&end_ts=<ms>&points_limit=<n>`
- `GET /api/device/{dev_num}/anomalies?hours=48&page=1&page_size=100`

### 管理与诊断
- `GET /api/admin/recent`
- `GET /api/diagnosis/stream`
- `GET /api/diagnosis/recent`
- `POST /api/diagnosis/replay`
- `GET /api/diagnosis/replay/{task_id}`
- `POST /api/diagnosis/replay/recent/{dev_num}?points=120&queued=0`（最近 N 点快速回放）
- `GET /api/diagnosis/replay/compare?start_ts=&end_ts=&dev_num=`（一期/二期对照）

### 二期（Anomaly v2）
- `GET /api/anomaly/v2/control`
- `POST /api/anomaly/v2/control`（运行时开关与调参）
- `GET /api/anomaly/v2/events/recent`
- `GET /api/anomaly/v2/shadow/summary`
- `GET /api/anomaly/v2/report/weekly`
- `GET /api/anomaly/v2/drift/summary`
- `GET /api/anomaly/v2/review/topk`
- `GET /api/anomaly/v2/review/topk/export`
- `POST /api/anomaly/v2/review/label`
- `GET /api/anomaly/v2/review/labels`

---

## 二期快速使用（建议流程）

### 1) 开启二期影子模式

```bash
curl -s -X POST "http://localhost:8000/api/anomaly/v2/control" \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": true,
    "shadow_mode": true,
    "alpha": 0.20,
    "warn_threshold": 0.72,
    "recover_threshold": 0.50,
    "min_points": 5,
    "event_start_count": 4,
    "event_end_count": 6,
    "event_min_duration_sec": 240,
    "event_cooldown_sec": 900,
    "sim_enabled": true,
    "sim_weight": 0.30,
    "sim_k": 5
  }' | python3 -m json.tool
```

### 2) 跑最近 N 点回放（推荐联调方式）

```bash
curl -s -X POST "http://localhost:8000/api/diagnosis/replay/recent/000000060160526?points=120&queued=0" | python3 -m json.tool
```

### 3) 查看运行指标与汇总

```bash
curl -s "http://localhost:8000/api/runtime/metrics" | python3 -m json.tool
END_TS=$(python3 - <<'PY'
import time
print(int(time.time()*1000))
PY
)
START_TS=$((END_TS - 24*60*60*1000))
curl -s "http://localhost:8000/api/anomaly/v2/shadow/summary?start_ts=${START_TS}&end_ts=${END_TS}&top_n=10" | python3 -m json.tool
curl -s "http://localhost:8000/api/anomaly/v2/report/weekly?start_ts=${START_TS}&end_ts=${END_TS}&dev_num=000000060160526&top_n=10" | python3 -m json.tool
```

### 4) 自动生成日报（JSON + CSV）

```bash
python3 src/scripts/anomaly_v2_daily_report.py \
  --base-url http://localhost:8000 \
  --hours 24 \
  --dev-num 000000060160526 \
  --top-n 10 \
  --out-dir reports/anomaly_v2
```

### 5) 批量回灌人工标注（CSV -> API）

CSV 需至少包含列：`event_id,label`（可选：`reviewer,note`）

```bash
# 先做校验（不写入）
python3 src/scripts/anomaly_v2_import_labels.py \
  --csv reports/anomaly_v2/topk_review_20260310.csv \
  --base-url http://localhost:8000 \
  --dry-run

# 再正式回灌
python3 src/scripts/anomaly_v2_import_labels.py \
  --csv reports/anomaly_v2/topk_review_20260310.csv \
  --base-url http://localhost:8000
```

---

## 关键业务规则

1. 首页大图：有策略切换（最短展示时长控制）
2. 设备轮播：每条检测事件都可进入轮播（实时监控）
3. MQTT 去重：
   - 若设备业务值变化：立即保留
   - 若业务值连续不变：仅每 5 分钟保留一条心跳样本
4. 检测触发：默认 `queued=1`，同设备高频事件合并处理

---

## 更多文档

- 技术实现与状态：`docs/技术沉淀文档.md`
- 业务说明：`docs/项目说明文档.md`
- 后续计划：`docs/后续扩展TODO.md`
