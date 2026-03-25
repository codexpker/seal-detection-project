# 历史旧数据干扰回归测试总览

## 这份材料的定位

- 这是 `old_data` 的挑战集回归分诊，不是主训练集结果，也不是主链路分类精度报告。
- 目标是证明系统在强干扰历史数据面前，能够保持保守，不把严格密封样本直接当成泄漏告警。

## 核心统计

- total_ok_runs: `34`
- subgroup_counts: `{'sealed_strict': 19, 'unsealed': 8, 'sealed_no_screw_grease': 7}`
- final_status_counts: `{'strict_sealed_negative_control_safe': 11, 'strict_sealed_interference_watch': 8, 'weak_seal_low_signal': 4, 'challenge_positive_like': 4, 'weak_seal_watch': 3, 'challenge_watch': 3, 'challenge_low_signal': 1}`
- strict_safe_rate: `0.5789473684210527`
- strict_watch_rate: `0.42105263157894735`
- strict_positive_like_count: `0`
- weak_watch_rate: `0.42857142857142855`
- unsealed_positive_like_rate: `0.5`
- unsealed_watch_or_high_rate: `0.875`

## 现场建议讲法

- `strict sealed` 只能落到 `safe` 或 `watch`，不能被直接讲成泄漏。
- `sealed_no_screw_grease` 单独作为结构弱化挑战子集，默认只做 `watch / abstain`。
- `unsealed` 中若同时出现高 candidate 比例和较快动态响应，才进入 `positive-like`。

## 建议现场展示的样例

- 严格密封干扰样例: 2026-01-04 165808 | status=strict_sealed_interference_watch | candidate_high_info_ratio=0.922 | best_lag_rh_h=1.000
- 严格密封保守样例: 2025-12-15 230921 | status=strict_sealed_negative_control_safe | candidate_high_info_ratio=0.500 | best_lag_rh_h=6.000
- 结构弱化 watch 样例: 2025-10-18 165216 | status=weak_seal_watch | candidate_high_info_ratio=0.429 | best_lag_rh_h=0.000
- 非密封 challenge-positive 样例: 2025-11-03 193657 | status=challenge_positive_like | candidate_high_info_ratio=1.000 | best_lag_rh_h=1.000