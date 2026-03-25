# Gate / Info Selector v3 报告

- 核心策略：只优化数据已经明确支持的部分。`transition` 分数升级为多视角版本；`static` 分支保留已验证路由逻辑，但显式补充静态支持分数与路由理由。

## 路由结果

- route_role_counts = `{'transition_context': 119, 'reject_heat_related': 93, 'static_threshold_favored': 67, 'static_memory_candidate': 32, 'background_high_hum': 29, 'transition_core': 18, 'reject_complex_or_unknown': 3}`
- route_branch_counts = `{'transition_branch': 137, 'none': 125, 'static_threshold_branch': 67, 'static_memory_branch': 32}`
- transition_near_branch_coverage = `1.0`
- threshold_favored_ratio = `0.18559556786703602`

## Transition 分数升级

- mean_near_rank_v2 = `0.9028011204481793`
- mean_near_rank_v3 = `0.9420168067226891`
- mean_score_lift_v2 = `0.8036397830412765`
- mean_score_lift_v3 = `2.6382133061513757`

### per-file transition comparison

- 2026-03-04 120007_seal_unheated-2026-03-04 163909_unseal_unheated | rank_v2=0.943 | rank_v3=0.943 | lift_v2=1.244 | lift_v3=3.541
- 2026-03-08 172014_seal_unheated | rank_v2=0.863 | rank_v3=0.941 | lift_v2=0.364 | lift_v3=1.736

## Static 分支影响

- threshold_branch: available=`True` | covered_runs=`5` | abstained_runs=`1` | best_feature=`slope_in_h_per_h` | run_balanced_accuracy=`0.8333333333333333`
- similarity_all_static: run_auc=`0.888888888888889` | run_balanced_accuracy=`0.6666666666666666`

### static_context_score_v3 by route branch

- static_memory_branch | count=32 | mean=1.108 | median=0.382
- static_threshold_branch | count=67 | mean=0.666 | median=0.444

## 验收判断

- transition_routing_pass = `True`
- transition_score_upgrade_pass = `True`
- threshold_branch_not_worse = `True`

## 当前结论

- `transition` 是当前最值得继续优化的分支；v3 的多视角分数明显提高了近转移窗口的排序和分数抬升。
- `static` 分支当前仍不适合大幅重构。窗口层面的静态区分仍弱，因此 v3 只增加诊断性的 `static_context_score_v3` 与路由理由，不推翻已验证成立的 `delta_half_dAH >= 0` favored 规则。
- 这一步说明：下一轮优化应优先把 v3 的 transition scoring 接进后续 evidence fuser，而不是重启全局分类器或直接扩更复杂模型。
