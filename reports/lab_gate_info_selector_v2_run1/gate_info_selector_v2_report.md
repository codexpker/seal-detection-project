# Gate / Info Selector v2 报告

- 核心思路：不再用单一全局 info_score 裁决所有窗口，而是做分支感知路由。

## 路由结果

- route_role_counts = `{'transition_context': 119, 'reject_heat_related': 93, 'static_threshold_favored': 67, 'static_memory_candidate': 32, 'background_high_hum': 29, 'transition_core': 18, 'reject_complex_or_unknown': 3}`
- route_branch_counts = `{'transition_branch': 137, 'none': 125, 'static_threshold_branch': 67, 'static_memory_branch': 32}`
- transition_near_branch_coverage = `1.0`
- static_routed_runs = `6`
- static_routed_windows = `99`
- threshold_favored_ratio = `0.18559556786703602`

## 当前结论

- 转移窗口应单独路由到 transition 分支，不再和静态高湿窗口混在一起。
- 静态高湿窗口不再强行统一裁切；记忆分支保留全量 candidate windows，阈值分支只重点关注 delta_half_dAH 为正的窗口。
- 第一阶段的优化方向不是继续缩窗口，而是把窗口分配给正确的后续分支。
