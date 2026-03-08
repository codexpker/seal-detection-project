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
│   └── components/TrendChart.vue  # 曲线组件
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
