# 实验室第三阶段 状态段级证据融合 v4 报告

- 结论：`PASS`
- review_queue_runs：`6`
- transition_capture_rate：`1.0`
- transition_boost_capture_rate：`1.0`
- static_eval_balanced_accuracy：`1.0`
- static_prediction_coverage：`0.6666666666666666`
- adopt_v4_default：`True`

## v4 的核心变化

- 只在 `外部高湿-无热源` 静态支线上接入 `no_heat probe v3`，不改 transition 主线，也不重启 cooling 分支。
- `probe_supported` 只增强 `static_dynamic_support_alert` 这一类“已有静态支持但还不够强”的运行。
- `probe_breathing_watch` 只作为误报抑制层，对 alert-like 静态运行主动压回 watch。

## v3 / v4 对照

- v3_verdict = `PASS`
- v4_verdict = `PASS`
- status_changed_count = `1`
- evidence_changed_count = `1`
- risk_changed_count = `1`
- changed_status_files = `['2026-03-03 181049_unseal_unheated']`
- promoted_supported_count = `1`
- suppressed_breathing_count = `0`

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
- changes_restricted_to_no_heat_branch = `True`
- probe_effective = `True`

## no-heat probe v3 叠加结果

- 2026-03-06 160246_seal_unheated | probe=ext_high_hum_no_heat_probe_breathing_watch | overlay=breathing_watch_context_only | final_status=static_hard_case_watch | evidence=hard_case_multiview | rationale=late_persistence_with_low_ah_decay
- 2026-03-02 161335_seal_unheated | probe=ext_high_hum_no_heat_probe_negative | overlay=negative_context_only | final_status=static_abstain_low_signal | evidence=similarity_branch | rationale=early_response_absent
- 2026-03-03 181049_unseal_unheated | probe=ext_high_hum_no_heat_probe_supported | overlay=supported_upgrades_dynamic_support | final_status=static_dynamic_supported_alert | evidence=multiview_support+no_heat_probe | rationale=early_response_present_without_persistent_breathing_pattern

## 需要复核的运行

- 2026-03-03 181049_unseal_unheated | status=static_dynamic_supported_alert | evidence=multiview_support+no_heat_probe | segment=S002 | notes=threshold_pred=0 | similarity_pred=0 | dynamic_vote_count=4 | hard_case_ratio=0.863 | multiview support recovers static miss | no_heat_probe_v3=ext_high_hum_no_heat_probe_supported | no_heat probe corroborates multiview-supported static alert | overlay=supported_upgrades_dynamic_support
- 2026-03-06 160246_seal_unheated | status=static_hard_case_watch | evidence=hard_case_multiview | segment=S001 | notes=threshold_pred=0 | similarity_pred=1 | dynamic_vote_count=5 | hard_case_ratio=0.547 | hard case watch overrides static alerting | no_heat_probe_v3=ext_high_hum_no_heat_probe_breathing_watch | overlay=breathing_watch_context_only
- 2026-03-04 120007_seal_unheated-2026-03-04 163909_unseal_unheated | status=transition_boost_alert | evidence=transition_branch+multiview | segment=S001 | notes=transition boost features=delta_in_hum,delta_half_in_hum,max_hourly_hum_rise,std_out_hum,corr_AH | transition evidence passed | transition_boost_count=5
- 2026-03-08 172014_seal_unheated | status=transition_boost_alert | evidence=transition_branch+multiview | segment=S002 | notes=transition boost features=delta_in_hum,delta_half_in_hum,max_hourly_hum_rise,corr_AH | transition evidence passed | transition_boost_count=4
- 2026-03-04 163909_unseal_unheated | status=static_dynamic_supported_alert | evidence=threshold+similarity+multiview | segment=S001 | notes=threshold_pred=1 | similarity_pred=1 | dynamic_vote_count=5 | hard_case_ratio=1.091 | dynamic support agrees with static alert
- 2026-03-22 150919_unseal_unheated | status=static_dynamic_supported_alert | evidence=threshold+similarity+multiview | segment=S002 | notes=threshold_pred=1 | similarity_pred=1 | dynamic_vote_count=5 | hard_case_ratio=1.745 | dynamic support agrees with static alert

## 当前判断

- `v4` 不是新模型，而是把已经验证通过的 `no_heat probe v3` 以极小范围接回静态决策层。
- 如果 `adopt_v4_default = True`，后续默认主线可以升级成：`gate/info selector v3 -> evidence_fuser v4 -> transition event summary`。
- cooling 仍保持 review / 物理解释探针角色，不进入默认主判定。
