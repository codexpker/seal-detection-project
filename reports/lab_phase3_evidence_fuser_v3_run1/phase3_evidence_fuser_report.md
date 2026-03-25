# 实验室第三阶段 状态段级证据融合 v3 报告

- 结论：`PASS`
- review_queue_runs：`6`
- transition_capture_rate：`1.0`
- transition_boost_capture_rate：`1.0`
- static_eval_balanced_accuracy：`1.0`
- static_prediction_coverage：`0.6666666666666666`
- adopt_v3_default：`True`

## v3 的核心变化

- `gate / info selector v3` 已接入运行级决策层，transition 证据改用多视角分数，不再只沿用旧的相对分数。
- 静态分支不做重构，继续沿用当前已验证的阈值分支、相似性分支和多视角 support/watch 逻辑。
- 决策输出增加了 `route_reason_summary` 与 transition v3 指标，方便解释为什么这个运行被送进当前状态。

## v2 / v3 对照

- v2_verdict = `PASS`
- v3_verdict = `PASS`
- status_changed_count = `0`
- evidence_changed_count = `0`
- risk_changed_count = `0`
- changed_status_files = `[]`

## Transition v3 升级摘要

- mean_near_rank_v2 = `0.9028011204481793`
- mean_near_rank_v3 = `0.9420168067226891`
- mean_score_lift_v2 = `0.8036397830412765`
- mean_score_lift_v3 = `2.6382133061513757`

- 2026-03-04 120007_seal_unheated-2026-03-04 163909_unseal_unheated | rank_v2=0.943 | rank_v3=0.943 | lift_v2=1.244 | lift_v3=3.541
- 2026-03-08 172014_seal_unheated | rank_v2=0.863 | rank_v3=0.941 | lift_v2=0.364 | lift_v3=1.736

## 验收判断

- transition_evidence_captured = `True`
- transition_boost_attached = `True`
- threshold_abstain_enabled = `True`
- hard_case_watch_enabled = `True`
- dynamic_support_recovers_miss = `True`
- all_runs_resolved_to_status = `True`
- static_review_quality_ready = `True`
- static_coverage_acceptable = `True`
- verdict_not_worse = `True`
- transition_capture_not_worse = `True`
- transition_boost_not_worse = `True`
- static_balanced_accuracy_not_worse = `True`
- static_coverage_not_worse = `True`
- transition_rank_improved = `True`
- transition_lift_improved = `True`

## 需要复核的运行

- 2026-03-03 181049_unseal_unheated | status=static_dynamic_support_alert | evidence=multiview_support | segment=S002 | notes=threshold_pred=0 | similarity_pred=0 | dynamic_vote_count=4 | hard_case_ratio=0.863 | multiview support recovers static miss | route=selected_static_candidate | static_context_score_v3=0.261 | delta_half_dAH_negative || selected_static_candidate | static_context_score_v3=0.337 | delta_half_dAH_nonnegative
- 2026-03-06 160246_seal_unheated | status=static_hard_case_watch | evidence=hard_case_multiview | segment=S001 | notes=threshold_pred=0 | similarity_pred=1 | dynamic_vote_count=5 | hard_case_ratio=0.547 | hard case watch overrides static alerting | route=selected_static_candidate | static_context_score_v3=1.735 | delta_half_dAH_nonnegative || selected_static_candidate | static_context_score_v3=1.274 | delta_half_dAH_nonnegative
- 2026-03-04 120007_seal_unheated-2026-03-04 163909_unseal_unheated | status=transition_boost_alert | evidence=transition_branch+multiview | segment=S001 | notes=transition boost features=delta_in_hum,delta_half_in_hum,max_hourly_hum_rise,std_out_hum,corr_AH | transition evidence passed | transition_boost_count=5 | rank_v3=0.943 | lift_v3=3.541 | route=phase=near_transition | transition_multiview_score_v3 || phase=post_transition | transition_multiview_score_v3
- 2026-03-08 172014_seal_unheated | status=transition_boost_alert | evidence=transition_branch+multiview | segment=S002 | notes=transition boost features=delta_in_hum,delta_half_in_hum,max_hourly_hum_rise,corr_AH | transition evidence passed | transition_boost_count=4 | rank_v3=0.941 | lift_v3=1.736 | route=phase=near_transition | transition_multiview_score_v3 || phase=post_transition | transition_multiview_score_v3
- 2026-03-04 163909_unseal_unheated | status=static_dynamic_supported_alert | evidence=threshold+similarity+multiview | segment=S001 | notes=threshold_pred=1 | similarity_pred=1 | dynamic_vote_count=5 | hard_case_ratio=1.091 | dynamic support agrees with static alert | route=selected_static_candidate | static_context_score_v3=0.598 | delta_half_dAH_nonnegative || selected_static_candidate | static_context_score_v3=0.610 | delta_half_dAH_nonnegative
- 2026-03-22 150919_unseal_unheated | status=static_dynamic_supported_alert | evidence=threshold+similarity+multiview | segment=S002 | notes=threshold_pred=1 | similarity_pred=1 | dynamic_vote_count=5 | hard_case_ratio=1.745 | dynamic support agrees with static alert | route=selected_static_candidate | static_context_score_v3=0.430 | delta_half_dAH_negative || selected_static_candidate | static_context_score_v3=0.334 | delta_half_dAH_negative

## 静态多视角增强摘要

- 2026-03-06 160246_seal_unheated | votes=5/6 | dynamic_support=True | hard_case_watch=True | hits=corr_out_hum_in_hum,max_corr_outRH_inRH_change,frac_threshold_favored,frac_pos_delta_half_dAH,q90_delta_half_dAH_w
- 2026-03-04 163909_unseal_unheated | votes=5/6 | dynamic_support=True | hard_case_watch=False | hits=corr_out_hum_in_hum,max_corr_outRH_inRH_change,frac_threshold_favored,frac_pos_delta_half_dAH,q90_delta_half_dAH_w
- 2026-03-22 150919_unseal_unheated | votes=5/6 | dynamic_support=True | hard_case_watch=False | hits=corr_out_hum_in_hum,frac_threshold_favored,frac_pos_delta_half_dAH,q90_delta_half_dAH_w,std_in_hum_run
- 2026-03-03 181049_unseal_unheated | votes=4/6 | dynamic_support=True | hard_case_watch=False | hits=corr_out_hum_in_hum,max_corr_outRH_inRH_change,q90_delta_half_dAH_w,std_in_hum_run
- 2026-03-02 161335_seal_unheated | votes=1/6 | dynamic_support=False | hard_case_watch=False | hits=std_in_hum_run
- 2026-03-23 213435_seal_unheated | votes=1/6 | dynamic_support=False | hard_case_watch=False | hits=corr_out_hum_in_hum

## 当前判断

- 这一步依然不是“统一分类器”，而是把 v3 的 route/info 优化接到运行级证据融合层，验证它是否真的改善最强的 transition 场景。
- `transition` 分支在运行级上没有回退，同时获得了更强的 rank / lift 解释，因此可以作为默认路径替换 v2。
- `static` 分支当前没有被重新设计；这次升级的目标是保留静态稳定性，同时把优化集中在数据已经支持的 transition 证据上。
- 下一步如果继续优化，重点应放在 `transition event` 的开始/结束边界和解释展示，而不是重开全局 seal/unseal 分类器。
