# Transition 个案对比图说明

- 明细表：`/Users/xpker/seal_detection_project/reports/seal_v4_transition_case_study_v1_run1/transition_case_windows_v1.csv`
- 对比图：`/Users/xpker/seal_detection_project/reports/seal_v4_transition_case_study_v1_run1/transition_case_comparison_v1.png`

## 读图要点

- 左侧 `20260308` 是典型快跳变：`delta_in_h` 很快超过旧门槛 `0.6`，因此旧规则就能打出 `transition_boost_alert`。
- 右侧 `20260323` 是慢爬升：`delta_in_h` 长时间停在 `0.55~0.59`，`delta_ah_in` 和 `score` 已经足够，但旧规则因为差一点没过 `0.6` 而 miss。
- `online.3` 新增的 `sustained_slow_shape` 只在连续 3 个窗口都满足慢爬升条件时才触发，因此补回了 `20260323`，但不会把短暂抖动也打成 transition。