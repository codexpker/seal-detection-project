# MVP实现文档（二期异常检测）

> 目标：用最小改动在现有系统中落地“可运行、可评估、可回退”的二期检测链路。  
> 适用周期：1~2 周完成首版，先影子运行，再灰度启用。

---

## 1. 先回答“从哪开始”

**建议起点：先做“离线回放版 MVP”，再做在线接入。**

原因：
1. 你已有回放能力，改造成本最低；
2. 可先验证“特征 + 阈值 + 事件策略”是否有效；
3. 避免直接改在线链路带来生产噪音。

所以第一步不是上复杂模型，而是：
- 先把二期特征算出来；
- 先跑统计基线得分；
- 先做事件级判定；
- 先产出对照报告（一期 vs 二期）。

---

## 2. MVP范围（必须做 / 暂不做）

### 2.1 必须做（MVP）

1. 点级分数：`score_raw`、`score_smooth`
2. 事件级判定：开始/结束/峰值/持续时间
3. 二期结果入库（可单独表，避免污染一期）
4. 回放对照：一期 vs 二期事件级指标
5. 开关控制：`ANOMALY_V2_ENABLED=false` 默认关闭

### 2.2 暂不做（MVP后）

1. 深度模型（TranAD 等）
2. 自动在线重训练
3. 全量设备实时启用

---

## 3. MVP技术方案（最小实现）

## 3.1 输入

复用已有监测数据表，按设备读取最近窗口：
- `temp_in`, `temp_out`, `hum_in`, `hum_out`, `timestamp`

新增计算：
- `dt`（与上一条间隔秒数）

## 3.2 特征（MVP最小集）

1. `delta_t = temp_in - temp_out`
2. `delta_h = hum_in - hum_out`
3. `delta_h_norm = delta_h / (abs(hum_out) + 1e-6)`
4. `slope_delta_h = (delta_h_t - delta_h_{t-1}) / dt`
5. `vol_5`：短窗波动（例如最近5点标准差）

## 3.3 点级打分（统计基线）

- Robust Z-Score（基于滑窗 median + MAD）
- EWMA 平滑得到 `score_smooth`

建议初值：
- `alpha = 0.25`
- `warn_threshold = 0.65`
- `recover_threshold = 0.45`

## 3.4 事件级策略（迟滞）

- 连续 `N_start=3` 点超过 `warn_threshold` → 事件开始
- 连续 `N_end=5` 点低于 `recover_threshold` → 事件结束
- 记录事件峰值、时长、触发原因

---

## 4. 数据库与接口（MVP建议）

## 4.1 新增表（建议）

### A. 点级分数表 `anomaly_score_v2`

字段建议：
- `id`
- `dev_num`
- `device_timestamp`
- `score_raw`
- `score_smooth`
- `feature_json`
- `created_at`

### B. 事件表 `anomaly_event_v2`

字段建议：
- `id`
- `event_id`
- `dev_num`
- `start_ts`
- `end_ts`
- `peak_score`
- `duration_sec`
- `event_level`
- `decision_reason`
- `created_at`

## 4.2 新增内部接口（建议）

1. `POST /api/internal/anomaly/v2/score/{dev_num}/{device_timestamp}`
2. `POST /api/internal/anomaly/v2/event/{dev_num}/{device_timestamp}`
3. `GET /api/runtime/anomaly-v2/metrics`

> MVP阶段可先只做内部函数调用，不强制开放独立HTTP接口。

---

## 5. 具体实施步骤（按天执行）

### Day 1：准备与开关

1. 新增配置：
   - `ANOMALY_V2_ENABLED`
   - `ANOMALY_V2_SHADOW_MODE`（只算分不告警）
2. 建二期数据表（或先写入日志）
3. 在回放任务中挂二期入口（不影响一期）

### Day 2：特征与点级打分

1. 实现特征计算函数（纯函数，便于单测）
2. 实现 Robust Z + EWMA
3. 打通 `score_raw/score_smooth` 入库

### Day 3：事件策略

1. 实现迟滞状态机（start/end）
2. 输出事件记录并入库
3. 增加冷却时间（如 10 分钟）防告警风暴

### Day 4：回放对照评估

1. 选 3~5 台设备跑历史区间
2. 输出对照报告：
   - 事件级 Precision/Recall（若有标注）
   - 误报/天
   - 平均告警提前量
3. 根据结果微调阈值

### Day 5：小流量影子运行

1. 线上开启 `SHADOW_MODE=true`
2. 不改变业务告警，只记录二期结果
3. 观察 24~72 小时稳定性

---

## 6. 验收标准（MVP Done Definition）

满足以下即视为 MVP 完成：

1. 二期分数与事件可持续写库；
2. 回放可输出一期/二期对照结果；
3. 影子运行连续 24h 无报错中断；
4. 在试点设备上，二期误报率较一期有下降（或同等误报下提前量更优）；
5. 支持一键回退（关闭配置即可）。

---

## 7. 你现在就可以做的第一件事

**第一件事：在现有“回放任务”里新增一个 `v2_shadow` 执行分支。**

只做三件小事：
1. 读窗口数据；
2. 计算 `score_smooth`；
3. 按迟滞规则吐出事件并写入 `anomaly_event_v2`。

做完这一步，你就有了可评估的 MVP 主骨架。

---

## 8. 开源与文献如何在MVP中落地（避免“只参考不用”）

### 开源落地方式

1. **River（online-ml/river）**
   - MVP阶段用途：先不强依赖，作为 Day 6+ 可插拔在线模型。
   - 接入点：替换或并行于统计基线的 `score_raw` 生成器。

2. **Merlion（salesforce/Merlion）**
   - MVP阶段用途：离线快速对比算法，不直接上生产。
   - 接入点：回放脚本中多模型横评。

3. **TSB-AD（TheDatumOrg/TSB-AD）**
   - MVP阶段用途：借鉴评估范式（PR 视角、统一对比方式）。
   - 接入点：你的回放评估报告模板。

### 文献落地方式

1. **TSB-AD / NeurIPS 2024**：指导你优先做“可靠评估 + 稳健基线”。
2. **TranAD / VLDB 2022**：作为后续深度模型对照组，不阻塞MVP。
3. **DAGMM / ICLR 2018**：作为无监督离线基线候选，补充统计法对照。

---

## 9. 风险与快速止损

1. 误报高：提高 `N_start`、提高 `warn_threshold`、增加冷却时间。
2. 漏报高：降低 `warn_threshold`、降低 `N_end`、缩短平滑窗口。
3. 结果抖动：增大 EWMA 平滑（降低 `alpha`）。
4. 算力压力：先仅对试点设备启用 v2。

---

## 10. 影子运行首轮参数建议（24~72h）

> 目标：先拿到“可解释、可复盘、可调参”的第一轮结果，不追求一步到位。

### 10.1 参数三档（建议先用“保守档”）

#### A. 保守档（先控误报，推荐默认）

- `ANOMALY_V2_ALPHA=0.20`
- `ANOMALY_V2_WARN_THRESHOLD=0.72`
- `ANOMALY_V2_RECOVER_THRESHOLD=0.50`
- `ANOMALY_V2_EVENT_START_COUNT=4`
- `ANOMALY_V2_EVENT_END_COUNT=6`
- `ANOMALY_V2_EVENT_MIN_DURATION_SEC=240`
- `ANOMALY_V2_EVENT_COOLDOWN_SEC=900`

适用：现场干扰多、运维对误报敏感。

#### B. 平衡档（推荐二轮）

- `ANOMALY_V2_ALPHA=0.25`
- `ANOMALY_V2_WARN_THRESHOLD=0.65`
- `ANOMALY_V2_RECOVER_THRESHOLD=0.45`
- `ANOMALY_V2_EVENT_START_COUNT=3`
- `ANOMALY_V2_EVENT_END_COUNT=5`
- `ANOMALY_V2_EVENT_MIN_DURATION_SEC=180`
- `ANOMALY_V2_EVENT_COOLDOWN_SEC=600`

适用：希望兼顾误报与漏报。

#### C. 激进档（先抓召回，慎用）

- `ANOMALY_V2_ALPHA=0.30`
- `ANOMALY_V2_WARN_THRESHOLD=0.58`
- `ANOMALY_V2_RECOVER_THRESHOLD=0.40`
- `ANOMALY_V2_EVENT_START_COUNT=2`
- `ANOMALY_V2_EVENT_END_COUNT=4`
- `ANOMALY_V2_EVENT_MIN_DURATION_SEC=120`
- `ANOMALY_V2_EVENT_COOLDOWN_SEC=300`

适用：宁可多报也不希望漏掉潜在异常。

### 10.2 影子运行执行清单

1. 仅试点设备开启：`ANOMALY_V2_ENABLED=true` + `ANOMALY_V2_SHADOW_MODE=true`。
2. 首轮使用“保守档”运行 24h。
3. 每 6h 拉取一次：
   - `/api/runtime/metrics`
   - `/api/diagnosis/replay/compare?start_ts=...&end_ts=...`
4. 对 Top-K 高分事件做人审抽检（建议每批 20 条）。
5. 若误报明显偏高：提高 `WARN_THRESHOLD` 或 `START_COUNT`。
6. 若漏报明显偏高：降低 `WARN_THRESHOLD` 或 `START_COUNT`，并缩短 `COOLDOWN`。
7. 24h 后固化结论，进入 72h 复验（可切“平衡档”）。

### 10.3 首轮评估输出模板（建议）

1. 设备范围与时间范围
2. 参数档位（保守/平衡/激进）
3. v1/v2 事件数量对比
4. 人审样本命中率（Top-K）
5. 误报变化结论（↑/↓）
6. 下一轮参数调整建议

---

## 11. 当前工作记录（2026-03-08）

### 10.1 已完成（Day1 + Day2 + Day3部分能力）

1. **配置开关已接入后端**（`backend_app.py`）
   - `ANOMALY_V2_ENABLED`
   - `ANOMALY_V2_SHADOW_MODE`
   - `ANOMALY_V2_ALPHA`
   - `ANOMALY_V2_WARN_THRESHOLD`
   - `ANOMALY_V2_RECOVER_THRESHOLD`
   - `ANOMALY_V2_MIN_POINTS`

2. **二期数据表已在启动建表逻辑中加入**
   - `anomaly_score_v2`（点级分数与特征快照）
   - `anomaly_event_v2`（事件级结果，含 `shadow_mode`）

3. **特征函数骨架已实现（MVP最小集）**
   - `delta_t`
   - `delta_h`
   - `delta_h_norm`
   - `slope_delta_h`
   - `vol_5`

4. **点级打分骨架已实现**
   - Robust Z-Score（基于 median/MAD）
   - 归一化 `score_raw`
   - EWMA 平滑得到 `score_smooth`

5. **事件迟滞状态机已接入（配置化升级版）**
   - 新增参数：`ANOMALY_V2_EVENT_START_COUNT`、`ANOMALY_V2_EVENT_END_COUNT`
   - 新增参数：`ANOMALY_V2_EVENT_MIN_DURATION_SEC`、`ANOMALY_V2_EVENT_COOLDOWN_SEC`
   - 机制升级为：启动计数 + 恢复计数 + 最短时长 + 冷却时间
   - 结束事件写入 `anomaly_event_v2`，默认影子模式

6. **主流程集成与指标透出已完成**
   - 在 `process_latest_for_device` 中并行执行 v2
   - v2 输出挂载到诊断事件 `event_payload["anomaly_v2"]`
   - `/api/runtime/metrics` 增加 `anomaly_v2` 配置与运行计数（含新参数）

7. **新增回放对照接口（Day4前置）**
   - `GET /api/diagnosis/replay/compare?dev_num=&start_ts=&end_ts=`
   - 输出 v1/v2 事件统计与差异：
     - v1 点级异常数、v1 事件数
     - v2 事件数、v2 影子事件数
     - v2 事件等级分布
     - 事件数差值（v2-v1）

### 10.2 参考依据（已纳入执行设计）

- **River**：作为在线模型插拔位（后续 Day 6+）
- **Merlion**：用于离线横评补充
- **TSB-AD（NeurIPS 2024）**：用于评估范式与基线优先思想
- **TranAD / DAGMM**：保留为后续对照组

### 10.3 下一步建议（按MVP节奏）

1. 在试点设备开启 `SHADOW_MODE=true` 运行 24~72h。
2. 基于 `/api/diagnosis/replay/compare` 固化对照报表模板。
3. 按误报率目标微调 `START_COUNT/END_COUNT/COOLDOWN` 参数。
4. 准备 Day4 的人工复核样本集（Top-K 高分事件）。

### 10.4 本轮新增接口（2026-03-08）

1. **v2 最近事件查询**
   - `GET /api/anomaly/v2/events/recent`
   - 参数：`limit`、`dev_num`、`shadow_mode=all|true|false`
   - 用途：快速排查近期事件并按影子/非影子过滤。

2. **v2 影子运行汇总**
   - `GET /api/anomaly/v2/shadow/summary`
   - 参数：`start_ts`、`end_ts`、`top_n`
   - 输出：
     - 点级分数统计（count / avg / max）
     - 事件统计（总数、影子数、平均时长、峰值、等级分布）
     - Top 设备排行（事件数+峰值）
   - 用途：支持 24~72h 影子运行后的快速复盘与周报汇总。

3. **一期/二期对照接口（已在上一轮完成）**
   - `GET /api/diagnosis/replay/compare`
   - 用途：同时间窗对比 v1 与 v2 的事件规模差异。

4. **一键周报接口（本轮新增）**
   - `GET /api/anomaly/v2/report/weekly`
   - 参数：`start_ts`、`end_ts`、`dev_num`（可选）、`top_n`
   - 聚合内容：
     - v1/v2 对照（事件规模差异）
     - v2 影子运行分数与事件统计
     - Top 设备排行
     - 关键事件列表（按峰值/时长）
   - 用途：一条接口直接产出周会复盘原始数据。

5. **设备最近N点回放接口（本轮新增）**
   - `POST /api/diagnosis/replay/recent/{dev_num}?points=50&queued=0`
   - 作用：自动拉取指定设备最近 N 个不同时间戳并逐点回放处理。
   - 用途：避免重复处理同一个 timestamp，快速验证 v2 事件策略是否会触发。

## 11. 自主执行与验收清单（本轮）

### 11.1 自主执行范围

本轮已按“可独立验收”标准完成：

1. 二期核心流程完整性检查（配置→特征→打分→事件→入库→分析接口）。
2. 关键接口存在性与参数化检查。
3. 代码静态质量检查（linter）。
4. 过程与结果文档化，供你最终验收。

### 11.2 验证结果（已完成）

> 现场联调补充（2026-03-08）：
>
> 第一轮根因：v2 默认开关为关闭（`enabled=false`），导致不产生 `anomaly_score_v2`/`anomaly_event_v2` 数据。
>
> 第二轮根因：即使启用 v2，主流程窗口受 `WINDOW_T_MINUTES` 限制时只有 1 个点，而 v2 要求 `min_points>=2`，因此仍不触发。
>
> 已完成修复：
>
> 1. 新增运行时控制接口，无需重启即可开关/调参 v2。
> 2. 在主流程中为 v2 增加“样本回补”机制：当窗口点数不足时，自动按条数回拉历史样本（不加 T 限制）以满足 `min_points`。
> 3. 触发接口支持 `fallback_latest`，避免时间戳超前导致空窗口。

1. **配置参数已齐备**
   - 已确认 `ANOMALY_V2_ENABLED`、`ANOMALY_V2_SHADOW_MODE`、`ANOMALY_V2_ALPHA`、`ANOMALY_V2_WARN_THRESHOLD`、`ANOMALY_V2_RECOVER_THRESHOLD`、`ANOMALY_V2_MIN_POINTS`。
   - 已确认事件策略参数：`ANOMALY_V2_EVENT_START_COUNT`、`ANOMALY_V2_EVENT_END_COUNT`、`ANOMALY_V2_EVENT_MIN_DURATION_SEC`、`ANOMALY_V2_EVENT_COOLDOWN_SEC`。

2. **关键接口已齐备**
   - `GET /api/diagnosis/replay/compare`
   - `GET /api/anomaly/v2/events/recent`
   - `GET /api/anomaly/v2/shadow/summary`
   - `GET /api/anomaly/v2/report/weekly`
   - `GET /api/runtime/metrics`

3. **流程集成已确认**
   - v2 在主处理链路中并行执行，不破坏 v1。
   - v2 分数与事件可独立入库（`anomaly_score_v2`、`anomaly_event_v2`）。

4. **质量检查**
   - `backend_app.py` linter 检查通过，无新增错误。

### 11.3 你的最终验收步骤（建议按此顺序）

> 现场联调修正（2026-03-08）：
>
> 终端结果显示，你在手工触发时把 `DEV_NUM` 留成了占位字符串“你的设备号”，导致查询不到真实设备数据，窗口大小为 0，从而 v2 计数一直为 0。
> 为避免类似误操作，已增强内部触发接口：
>
> - `POST /api/internal/process/{dev_num}/{device_timestamp}` 新增 `fallback_latest`（默认 1）
> - 当传入时间戳晚于该设备最新数据时，自动回退到该设备最新 `latest_ts`
> - 返回里补充 `requested_device_timestamp` / `effective_device_timestamp` / `latest_ts`
>
> 建议今后先用真实设备号，或直接传近期时间戳。

1. 开启影子模式并运行（推荐运行时接口，不重启）：

   - 查看当前配置：`GET /api/anomaly/v2/control`
   - 开启 v2 + 影子模式：`POST /api/anomaly/v2/control`
     ```json
     {
       "enabled": true,
       "shadow_mode": true
     }
     ```

2. 如需快速试跑，可同步调低触发门槛（可选）：

   - `POST /api/anomaly/v2/control`
     ```json
     {
       "warn_threshold": 0.65,
       "recover_threshold": 0.45,
       "event_start_count": 3,
       "event_end_count": 5,
       "event_min_duration_sec": 180,
       "event_cooldown_sec": 600
     }
     ```

3. 运行 24h 后拉取三类数据：
   - `/api/runtime/metrics`
   - `/api/anomaly/v2/shadow/summary?start_ts=...&end_ts=...`
   - `/api/anomaly/v2/report/weekly?start_ts=...&end_ts=...`

3. 对照验证：
   - `/api/diagnosis/replay/compare?start_ts=...&end_ts=...`

4. 重点判定：
   - 事件规模是否可控（无告警风暴）
   - Top设备是否符合业务直觉
   - 关键事件（peak/duration）是否可解释

### 11.4 最新联调结论（2026-03-09）

1. 已使用 `POST /api/diagnosis/replay/recent/{dev_num}?points=120&queued=0` 完成 120 点连续回放。
2. 回放执行结果：`processed_points=120`、`ok_count=120`、`fail_count=0`。
3. v2 运行计数已增长：`anomaly_v2_runs=121`，且 `anomaly_v2_errors=0`，说明二期链路稳定可运行。
4. 当前 `anomaly_v2_events=0` 属于业务结果（未达到事件阈值），非系统故障：
   - 当前参数为保守档（`warn_threshold=0.72` 等）；
   - 分数统计约 `avg_raw/max_smooth ≈ 0.099`，低于事件触发门槛。
5. 一期模型服务当前仍存在 `model_error`（模型端可用性问题），但不阻塞二期 v2 分数链路验证。

### 11.5 Day2 交付：日报脚本（已完成）

### 11.6 Day3 交付：漂移检测简版（已完成）

### 11.7 Day4 交付：Top-K人工复核样本导出（已完成）

### 11.8 Day5 交付：人工标注回灌（已完成）

1. 新增标注接口：`POST /api/anomaly/v2/review/label`
   - 入参：`event_id`、`label(true|false|uncertain)`、`reviewer`、`note`
   - 行为：按 `event_id` 幂等写入/更新人工标注。

2. 新增标注查询接口：`GET /api/anomaly/v2/review/labels`
   - 参数：`label=all|true|false|uncertain`、`limit`
   - 输出：标注记录 + 关联事件信息。

3. 新增标注表：`anomaly_review_label_v2`
   - 用途：沉淀首版现场金标准样本集。

### 11.9 Day6 交付：首版评估汇总（已完成）

1. 新增评估接口：`GET /api/anomaly/v2/eval/summary`
   - 统计人工标注数量分布（true/false/uncertain）
   - 基于已标注样本给出 Precision / Recall / F1（首版）
   - 输出混淆近似统计（tp/fp/fn）

2. 说明：
   - 仅基于“已复核样本”计算；
   - `uncertain` 默认不计入 fp/fn。

### 11.10 Day7 交付：收口状态（已完成）

1. 二期 MVP 主体能力已全链路具备：
   - 运行时控制、回放、对照、汇总、周报、漂移、Top-K、标注回灌、评估汇总。
2. 剩余外部阻塞项（不属于二期骨架代码缺陷）：
   - 一期模型服务 `MODEL_SERVICE_URL` 侧持续 `model_error`，需模型服务侧修复与联调。

1. 新增接口：`GET /api/anomaly/v2/review/topk`
   - 参数：`start_ts`、`end_ts`、`limit`、`dev_num`（可选）
   - 排序：按 `peak_score DESC, duration_sec DESC`
   - 用途：提取人工复核候选事件（Top-K）

2. 新增导出接口：`GET /api/anomaly/v2/review/topk/export`
   - 参数：`start_ts`、`end_ts`、`limit`、`dev_num`（可选）
   - 输出：CSV 文件（用于人工复核打标）

3. 建议复核流程（最小闭环）：
   - 每日导出 Top-30；
   - 人工标注 `true/false/uncertain`；
   - 按周汇总形成首版现场金标准样本集。

1. 新增接口：`GET /api/anomaly/v2/drift/summary`
   - 参数：`start_ts`、`end_ts`、`dev_num`（可选）
   - 方法：`half_window_mean_std_shift`
   - 输出：
     - 前后半窗均值/方差统计
     - `drift_score`
     - `drift_flag`（默认阈值 `2.0`）

2. 日报脚本已集成漂移结果：`src/scripts/anomaly_v2_daily_report.py`
   - 详细 JSON 中新增：`drift_summary`
   - KPI CSV 中新增：`drift_flag`、`drift_score`、`drift_method`

已新增脚本：`src/scripts/anomaly_v2_daily_report.py`

功能：
1. 自动抓取以下接口并汇总：
   - `/api/runtime/metrics`
   - `/api/diagnosis/replay/compare`
   - `/api/anomaly/v2/shadow/summary`
   - `/api/anomaly/v2/report/weekly`
2. 输出双文件：
   - 详细 JSON：完整原始结果与元信息
   - 扁平 CSV：关键 KPI 一行汇总（便于日报/周报表格化）

示例命令：
`python3 src/scripts/anomaly_v2_daily_report.py --base-url http://localhost:8000 --hours 24 --dev-num 000000060160526 --top-n 10 --out-dir reports/anomaly_v2`

### 11.11 现阶段主线任务（按优先级执行）

> 目标：从“可运行”推进到“可上线试点”。

#### P0（必须先完成）

1. 一期模型服务可用性修复（`process_model_error`）
   - 检查 `MODEL_SERVICE_URL` 连通性、模型服务健康状态、超时与错误码。
   - 输出《模型服务故障定位记录》并完成修复验证。

2. 人工复核样本积累（首批金标准）
   - 每日导出 Top-30 事件并完成人工标注（`true/false/uncertain`）。
   - 首批目标：累计 ≥100 条已复核样本。

#### P1（P0完成后执行）

3. 输出首版事件级评估结果
   - 基于已复核样本输出 Precision / Recall / F1、误报率。
   - 固化日报/周报指标口径。

4. 三档参数对照并固化推荐参数
   - 保守档 / 平衡档 / 激进档 A/B 对照。
   - 输出推荐参数与适用场景。

5. 影子运行 24~72h 形成试点验收结论
   - 判定维度：事件规模可控、Top设备可解释、关键事件可复核。

#### P2（增强项）

6. 漂移检测增强（从简版到在线）
   - 在当前简版 drift 基础上接入 ADWIN/等价方法（后续）。

7. 在线模型并行接入
   - 以当前 baseline 为主，River 在线模型并行 shadow，对照评估后再决策切换。

### 11.12 下一步执行安排（本周）

1. 先完成 P0-1：模型服务侧问题定位与恢复。
2. 并行推进 P0-2：启动每日 Top-K 复核打标。
3. 达到样本量后执行 P1-3/P1-4：形成首版指标与参数推荐。

## 12. 文档版本

- 版本：`v2026.03.09-mvp.11`
- 状态：二期MVP链路与 Day1~Day7 计划能力已落地；当前进入“P0主线收口（模型服务可用性 + 人工复核样本）”阶段
- 下一次更新触发条件：完成首批 ≥100 条人工复核并输出首版参数推荐与事件级评估结论
