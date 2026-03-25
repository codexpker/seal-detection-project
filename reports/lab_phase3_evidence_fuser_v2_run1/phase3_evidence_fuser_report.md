# 实验室第三阶段 状态段级证据融合 v2 报告

- 结论：`PASS`
- review_queue_runs：`6`
- transition_capture_rate：`1.0`
- transition_boost_capture_rate：`1.0`
- static_eval_balanced_accuracy：`1.0`
- static_prediction_coverage：`0.6666666666666666`
- hard_case_watch_runs：`1`
- dynamic_support_recovered_runs：`1`

## v2 的三处新增

- `transition_boost`：把转移邻域里更强的湿度抬升特征接进转移告警，不再只看旧的 transition score。
- `hard_case_watch`：对跨标签更近的静态难例主动降级为 review / abstain，不让它继续污染静态判定。
- `dynamic_support`：对原分支漏掉、但多视角证据很强的静态运行进行补充提升。

## 运行级结果分布

- final_status_counts = `{'gated_background': 5, 'gated_heat_related': 3, 'transition_boost_alert': 2, 'static_dynamic_supported_alert': 2, 'static_abstain_low_signal': 1, 'static_dynamic_support_alert': 1, 'static_hard_case_watch': 1, 'static_low_risk': 1}`
- risk_level_counts = `{'abstain': 9, 'high': 4, 'medium': 1, 'watch': 1, 'low': 1}`

## 验收判断

- transition_evidence_captured = `True`
- transition_boost_attached = `True`
- threshold_abstain_enabled = `True`
- hard_case_watch_enabled = `True`
- dynamic_support_recovers_miss = `True`
- all_runs_resolved_to_status = `True`
- static_review_quality_ready = `True`
- static_coverage_acceptable = `True`

## 需要复核的运行

- 2026-03-03 181049_unseal_unheated | status=static_dynamic_support_alert | evidence=multiview_support | segment=S002 | notes=threshold_pred=0 | similarity_pred=0 | dynamic_vote_count=4 | hard_case_ratio=0.863 | multiview support recovers static miss
- 2026-03-06 160246_seal_unheated | status=static_hard_case_watch | evidence=hard_case_multiview | segment=S001 | notes=threshold_pred=0 | similarity_pred=1 | dynamic_vote_count=5 | hard_case_ratio=0.547 | hard case watch overrides static alerting
- 2026-03-04 120007_seal_unheated-2026-03-04 163909_unseal_unheated | status=transition_boost_alert | evidence=transition_branch+multiview | segment=S001 | notes=transition boost features=delta_in_hum,delta_half_in_hum,max_hourly_hum_rise,std_out_hum,corr_AH | transition evidence passed | transition_boost_count=5
- 2026-03-08 172014_seal_unheated | status=transition_boost_alert | evidence=transition_branch+multiview | segment=S002 | notes=transition boost features=delta_in_hum,delta_half_in_hum,max_hourly_hum_rise,corr_AH | transition evidence passed | transition_boost_count=4
- 2026-03-04 163909_unseal_unheated | status=static_dynamic_supported_alert | evidence=threshold+similarity+multiview | segment=S001 | notes=threshold_pred=1 | similarity_pred=1 | dynamic_vote_count=5 | hard_case_ratio=1.091 | dynamic support agrees with static alert
- 2026-03-22 150919_unseal_unheated | status=static_dynamic_supported_alert | evidence=threshold+similarity+multiview | segment=S002 | notes=threshold_pred=1 | similarity_pred=1 | dynamic_vote_count=5 | hard_case_ratio=1.745 | dynamic support agrees with static alert

## 静态多视角增强摘要

- 2026-03-06 160246_seal_unheated | votes=5/6 | dynamic_support=True | hard_case_watch=True | hits=corr_out_hum_in_hum,max_corr_outRH_inRH_change,frac_threshold_favored,frac_pos_delta_half_dAH,q90_delta_half_dAH_w
- 2026-03-04 163909_unseal_unheated | votes=5/6 | dynamic_support=True | hard_case_watch=False | hits=corr_out_hum_in_hum,max_corr_outRH_inRH_change,frac_threshold_favored,frac_pos_delta_half_dAH,q90_delta_half_dAH_w
- 2026-03-22 150919_unseal_unheated | votes=5/6 | dynamic_support=True | hard_case_watch=False | hits=corr_out_hum_in_hum,frac_threshold_favored,frac_pos_delta_half_dAH,q90_delta_half_dAH_w,std_in_hum_run
- 2026-03-03 181049_unseal_unheated | votes=4/6 | dynamic_support=True | hard_case_watch=False | hits=corr_out_hum_in_hum,max_corr_outRH_inRH_change,q90_delta_half_dAH_w,std_in_hum_run
- 2026-03-02 161335_seal_unheated | votes=1/6 | dynamic_support=False | hard_case_watch=False | hits=std_in_hum_run
- 2026-03-23 213435_seal_unheated | votes=1/6 | dynamic_support=False | hard_case_watch=False | hits=corr_out_hum_in_hum

## 当前判断

- 这一步依然不是“统一分类器”，而是把多视角证据压成更稳的运行级状态机输出。
- `transition` 现在已经不仅能报，还能给出 `boost` 证据；演示时可直接把它作为最强场景。
- `2026-03-06 160246_seal_unheated` 这类静态难例现在会进入 `hard_case_watch`，不再被硬判成告警。
- `2026-03-03 181049_unseal_unheated` 这类旧分支漏报、但多视角证据很强的运行，现在会进入 `dynamic_support` 路径。
- 当前最合理的现场口径仍然是：强证据直接进入 review，弱证据辅助提分，难例与干扰主动保守。
