# Gate / Info Selector v2 报告

- 核心思路：不再用单一全局 info_score 裁决所有窗口，而是做分支感知路由。

## 路由结果

- route_role_counts = `{'transition_context': 119, 'reject_heat_related': 93, 'static_threshold_favored': 67, 'static_memory_candidate': 32, 'background_high_hum': 29, 'transition_core': 18, 'reject_complex_or_unknown': 3}`
- route_branch_counts = `{'transition_branch': 137, 'none': 125, 'static_threshold_branch': 67, 'static_memory_branch': 32}`
- transition_near_branch_coverage = `1.0`
- static_routed_runs = `6`
- static_routed_windows = `99`
- threshold_favored_ratio = `0.18559556786703602`

## 下游影响

- baseline_all_static: feature=`delta_half_dAH` | run_balanced_accuracy=`0.6666666666666666`
- threshold_branch: available=`True` | covered_runs=`5` | abstained_runs=`1` | best_feature=`slope_in_h_per_h` | run_balanced_accuracy=`0.8333333333333333` | gain_vs_all_static=`0.16666666666666663`
- similarity_all_static: run_auc=`0.888888888888889` | run_balanced_accuracy=`0.6666666666666666`
- similarity_memory_only: run_auc=`0.7777777777777778` | run_balanced_accuracy=`0.6666666666666666`

## 验收判断

- transition_routing_pass = `True`
- threshold_branch_gain_pass = `True`
- threshold_branch_abstention_required = `True`

## 当前结论

- 转移窗口应单独路由到 transition 分支，不再和静态高湿窗口混在一起。
- 静态高湿窗口不再强行统一裁切；记忆分支保留全量 candidate windows，阈值分支只重点关注 delta_half_dAH 为正的窗口。
- 这次优化对相似性分支没有明显增益，但对阈值分支有纯化价值；阈值分支应允许对无 favored window 的运行显式放弃判定。
- 第一阶段的优化方向不是继续缩窗口，而是把窗口分配给正确的后续分支，并允许低把握度分支 abstain。
