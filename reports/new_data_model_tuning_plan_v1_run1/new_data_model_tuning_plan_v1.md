# New Data Model Tuning Plan v1

## 当前数据状态

- run_count: `20`
- changed_run_count: `13`
- mainfield_segment_count: `12`
- transition_primary_segment_count: `3`
- guarded_positive_segment_count: `1`
- breathing_watch_segment_count: `1`
- confound_segment_count: `1`
- transition_secondary_segment_count: `4`
- auto_seed_label_counts: `{'transition_positive': 3, 'breathing_watch': 1, 'confound': 1}`

## 调优主线

1. `transition` 继续做主分支，不重启 whole-run 统一分类。
2. `static support` 继续保持 `support / watch / uncertain` 四态，不压回二分类。
3. `tri-memory + guard` 保留为硬约束，先减少误抬，再谈覆盖率。
4. `breathing_watch / confound / transition_secondary_control` 只做 challenge 池，不进主训练正池。

## 当前最该优化的模型点

- **Transition 主分支**：只围绕 3 条 `transition_positive` 做事件级提分、提前量、持续性验证。
- **Static 支持层**：只允许在人工确认后把 guarded 段升级到 `supported positive`，尤其是 `181049` 这一类。
- **误报抑制层**：继续用 `160246` 和 `20260321 heat-off` 约束 `breathing/confound`，防止静态支线误抬。
- **控制迁移层**：4 条 `transition_secondary_control` 继续作为边界条件验证，不参与主战场训练。

## 待复核优先队列

- 120165524_20260303-181049_unsealed_extHigh_intLow_noHeat_noChange_na::full | status=static_review_weak_positive_guarded | memory=hard_negative | anomaly_adv=-5.475595361803923 | guard=0.5409836065573771
- 120165519_20260309-102255_sealed_extLow_intHigh_noHeat_Change_20260310-1000_unsealed::post_change | status=transition_secondary_control | memory=nan | anomaly_adv=nan | guard=nan
- 120165519_20260313-111811_sealed_extLow_intHigh_Heat_Change_20260315-1500_unsealed::post_change | status=transition_secondary_control | memory=nan | anomaly_adv=nan | guard=nan
- 120165520_20260310-170038_sealed_extEq_intEq_Heat_Change_20260313-1002_unsealed::post_change | status=transition_secondary_control | memory=nan | anomaly_adv=nan | guard=nan
- 120165520_20260318-090358_sealed_extEq_intEq_Heat_Change_20260319-1520_unsealed::post_change | status=transition_secondary_control | memory=nan | anomaly_adv=nan | guard=nan

## 具体执行建议

1. 先用 `review_agenda_v1.csv` 完成 3 条主战场 transition 的人工确认。
2. 单独复核 `181049`，只在确认其跨数据集仍稳定时，才考虑从 `guarded` 升到 `supported`。
3. 保持 `160246 -> breathing_watch`、`20260321 -> confound` 的 hard-negative 角色，不抬进正池。
4. 复核完成后只重跑 `feedback_loop_v2`，再看 `pending` 是否还有 guarded 正段残留。
5. 只有当 guarded 段被连续人工确认后，才考虑调 `guard_score_thresh / weak_support_thresh`。

## 当前不要做

- 不要重启 whole-run `GRU/XGBoost`。
- 不要把 `181049` 自动并入 `positive_reference`。
- 不要把 `transition_secondary_control` 并入主战场 transition 正池。
- 不要把 `dew/vpd` 派生特征重新全量堆回统一模型。
