# 现场演示总览

## 当前主线

`分支感知路由 -> 转移段相对打分 -> evidence_fuser v4`

## 核心结论

- verdict: `PASS`
- transition_capture_rate: `1.0`
- transition_boost_capture_rate: `1.0`
- static_eval_balanced_accuracy: `1.0`
- static_prediction_coverage: `0.6666666666666666`

## 外部高湿响应补充证据

- no_heat_status_counts_v2: `{'ext_high_hum_no_heat_multiscale_breathing_watch': 1, 'ext_high_hum_no_heat_multiscale_negative': 1, 'ext_high_hum_no_heat_multiscale_supported': 1}`
- no_heat_three_state_ready_v2: `True`
- short_window_overreacts_v2: `True`
- cooling_status_counts_v2: `{'ext_high_hum_cooling_multiscale_no_segment': 2, 'ext_high_hum_cooling_multiscale_long_confirmed_candidate': 1}`
- cooling_validation_ready_v2: `False`
- no_heat_probe_v3_status_counts: `{'ext_high_hum_no_heat_probe_breathing_watch': 1, 'ext_high_hum_no_heat_probe_negative': 1, 'ext_high_hum_no_heat_probe_supported': 1}`
- no_heat_probe_v3_onset_positive_count: `2`
- no_heat_probe_v3_late_persistence_count: `1`

### v2 重点样例

- 2026-03-06 160246_seal_unheated | no_heat=ext_high_hum_no_heat_multiscale_breathing_watch | score_2h/6h/12h=0.404/0.265/0.464 | rationale=long_scale_not_weaker_than_main | short_scale_more_spiky_than_main
- 2026-03-02 161335_seal_unheated | no_heat=ext_high_hum_no_heat_multiscale_negative | score_2h/6h/12h=0.000/0.000/0.000 | rationale=main_and_long_low_signal
- 2026-03-03 181049_unseal_unheated | no_heat=ext_high_hum_no_heat_multiscale_supported | score_2h/6h/12h=0.371/0.506/0.371 | rationale=main_scale_stronger_than_long_scale | short_window_confirms_local_response
- 2026-03-14 174006_unseal_heated | cooling=ext_high_hum_cooling_multiscale_long_confirmed_candidate | count_2h/6h/12h=9/23/18 | q75_12h=0.248 | rationale=main_segment_exists | long_window_confirms_cumulative_dAH | short_window_has_local_positive_dAH

### no-heat probe v3 样例

- 2026-03-06 160246_seal_unheated | probe=ext_high_hum_no_heat_probe_breathing_watch | early_resp=1.000 | late_resp=1.000 | late_ah_decay_per_headroom=-0.003 | rationale=late_persistence_with_low_ah_decay
- 2026-03-02 161335_seal_unheated | probe=ext_high_hum_no_heat_probe_negative | early_resp=0.000 | late_resp=0.000 | late_ah_decay_per_headroom=-0.025 | rationale=early_response_absent
- 2026-03-03 181049_unseal_unheated | probe=ext_high_hum_no_heat_probe_supported | early_resp=1.000 | late_resp=1.000 | late_ah_decay_per_headroom=-0.013 | rationale=early_response_present_without_persistent_breathing_pattern

## 建议现场优先展示的样例

- 2026-03-04 120007_seal_unheated-2026-03-04 163909_unseal_unheated | `transition_boost_alert` | features=delta_in_hum,delta_half_in_hum,max_hourly_hum_rise,std_out_hum,corr_AH | event=2026-03-04 12:00:00 -> 2026-03-05 08:00:00 | peak=2026-03-04 12:00:00
- 2026-03-08 172014_seal_unheated | `transition_boost_alert` | features=delta_in_hum,delta_half_in_hum,max_hourly_hum_rise,corr_AH | event=2026-03-09 23:00:00 -> 2026-03-11 19:00:00 | peak=2026-03-10 08:00:00

## 建议现场展示的保守案例

- 2026-03-02 161335_seal_unheated | `static_abstain_low_signal` | notes=threshold branch abstained | similarity_pred=0 | dynamic_vote_count=1 | hard_case_ratio=1.164 | no_heat_probe_v3=ext_high_hum_no_heat_probe_negative
- 2026-03-06 160246_seal_unheated | `static_hard_case_watch` | notes=threshold_pred=0 | similarity_pred=1 | dynamic_vote_count=5 | hard_case_ratio=0.547 | hard case watch overrides static alerting | no_heat_probe_v3=ext_high_hum_no_heat_probe_breathing_watch

## 讲解口径

- 强证据场景：直接进入 review，不拖成全局分类问题。
- 静态场景：只做辅助证据，不承诺全覆盖。
- 难例和干扰：主动进入 `watch / abstain`，不乱报。
