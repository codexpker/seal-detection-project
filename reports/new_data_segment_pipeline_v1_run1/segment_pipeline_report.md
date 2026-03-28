# 新补充数据 段级管线 v1 报告

## 核心结论

- analyzable_segment_count: `24`
- primary_task_counts: `{'control_challenge': 10, 'transition_context': 10, 'short_context_only': 7, 'static_mainfield_primary': 5, 'static_eval_only': 1}`
- static_bucket_counts: `{'static_positive_reference': 3, 'static_negative_reference': 2, 'static_breathing_watch': 1, 'static_heatoff_confound_challenge': 1, 'static_positive_eval_only': 1}`
- transition_bucket_counts: `{'transition_secondary_control': 4, 'transition_primary_mainfield': 3}`
- clean_static_reference_count: `5`
- control_challenge_count: `18`

## 当前最重要的判断

- 这批 `new_data` 现在已经可以被稳定拆成 `主战场静态段 / transition 段 / 控制挑战段`，不应该再按 whole-run 一把混进主训练。
- 真正适合拿来推进主线的是：`外部高湿-无热源` 主战场里的少数干净段，以及 `seal->unseal` 的 change-run。
- `heat_on / heat_off / ext_humidity_up` 和一部分 `sealed but response-like` 段，应该进入 `watch / abstain / control challenge`，而不是直接并入正样本训练。

## 主战场静态段建议

- 120165524_20260306-160246_sealed_extHigh_intLow_noHeat_noChange_na | segment=full | bucket=static_breathing_watch | use=challenge_only | votes=4 | hits=delta_half_in_h,delta_half_dAH,slope_in_h_per_h,slope_dAH_per_h | rationale=sealed mainfield segment shows response-like behavior and should be kept as a hard case
- 120165524_20260321-170450_unseal_extHigh_intLow_Heat_Change_20260321-1800_noHeat | segment=post_change | bucket=static_heatoff_confound_challenge | use=challenge_only | votes=1 | hits=slope_in_h_per_h | rationale=post-heat-off segment enters the no-heat battlefield but remains confounded by prior heating
- 120165524_20260302 161335_sealed_extHigh_intLow_noHeat_noChange_na | segment=full | bucket=static_negative_reference | use=train_eval_primary | votes=0 | hits= | rationale=sealed no-heat mainfield segment stays below segment-level response thresholds
- 120165524_20260308-172014_sealed_extHigh_intLow_noHeat_Change_20260310-1000_unsealed | segment=pre_change | bucket=static_negative_reference | use=train_eval_primary | votes=1 | hits=end_start_dAH | rationale=sealed no-heat mainfield segment stays below segment-level response thresholds
- 120165524_20260303-181049_unsealed_extHigh_intLow_noHeat_noChange_na | segment=full | bucket=static_positive_eval_only | use=eval_only_review | votes=1 | hits=slope_in_h_per_h | rationale=unsealed mainfield segment has weak static evidence and should be kept for review rather than primary training
- 120165524_20260304-120007_sealed_extHigh_intLow_noHeat_Change_20260304-1639_unsealed | segment=post_change | bucket=static_positive_reference | use=train_eval_primary | votes=5 | hits=delta_half_in_h,delta_half_dAH,slope_in_h_per_h,slope_dAH_per_h,end_start_dAH | rationale=post-change unsealed mainfield segment shows sustained positive response on segment features
- 120165524_20260308-172014_sealed_extHigh_intLow_noHeat_Change_20260310-1000_unsealed | segment=post_change | bucket=static_positive_reference | use=train_eval_primary | votes=5 | hits=delta_half_in_h,delta_half_dAH,slope_in_h_per_h,slope_dAH_per_h,end_start_dAH | rationale=post-change unsealed mainfield segment shows sustained positive response on segment features
- 120165524_20260323-213435_seal_extHigh_intLow_noHeat_Change_20260324-9000_unseal | segment=post_change | bucket=static_positive_reference | use=train_eval_primary | votes=5 | hits=delta_half_in_h,delta_half_dAH,slope_in_h_per_h,slope_dAH_per_h,end_start_dAH | rationale=post-change unsealed mainfield segment shows sustained positive response on segment features

## Transition 段建议

- 120165524_20260304-120007_sealed_extHigh_intLow_noHeat_Change_20260304-1639_unsealed | bucket=transition_primary_mainfield | use=transition_train_eval_primary | pre_analyzable=False | post_analyzable=True | rationale=seal-to-unsealed run stays inside the main battlefield and is suitable for transition event evaluation
- 120165524_20260308-172014_sealed_extHigh_intLow_noHeat_Change_20260310-1000_unsealed | bucket=transition_primary_mainfield | use=transition_train_eval_primary | pre_analyzable=True | post_analyzable=True | rationale=seal-to-unsealed run stays inside the main battlefield and is suitable for transition event evaluation
- 120165524_20260323-213435_seal_extHigh_intLow_noHeat_Change_20260324-9000_unseal | bucket=transition_primary_mainfield | use=transition_train_eval_primary | pre_analyzable=False | post_analyzable=True | rationale=seal-to-unsealed run stays inside the main battlefield and is suitable for transition event evaluation
- 120165519_20260309-102255_sealed_extLow_intHigh_noHeat_Change_20260310-1000_unsealed | bucket=transition_secondary_control | use=transition_challenge_secondary | pre_analyzable=True | post_analyzable=True | rationale=seal-to-unsealed run is valuable for transition scoring but belongs to a control/secondary condition family
- 120165519_20260313-111811_sealed_extLow_intHigh_Heat_Change_20260315-1500_unsealed | bucket=transition_secondary_control | use=transition_challenge_secondary | pre_analyzable=True | post_analyzable=True | rationale=seal-to-unsealed run is valuable for transition scoring but belongs to a control/secondary condition family
- 120165520_20260310-170038_sealed_extEq_intEq_Heat_Change_20260313-1002_unsealed | bucket=transition_secondary_control | use=transition_challenge_secondary | pre_analyzable=True | post_analyzable=True | rationale=seal-to-unsealed run is valuable for transition scoring but belongs to a control/secondary condition family
- 120165520_20260318-090358_sealed_extEq_intEq_Heat_Change_20260319-1520_unsealed | bucket=transition_secondary_control | use=transition_challenge_secondary | pre_analyzable=True | post_analyzable=True | rationale=seal-to-unsealed run is valuable for transition scoring but belongs to a control/secondary condition family

## 控制 / 干扰挑战段

- 120165518_20260308-104441_sealed_extEq_intEq_noHeat_noChange_na | segment=full | role=balanced_control | source=full_run | primary=control_challenge | secondary= | static_bucket=nan
- 120165520_20260310-170038_sealed_extEq_intEq_Heat_Change_20260313-1002_unsealed | segment=post_change | role=balanced_control | source=seal_change_to_unsealed | primary=transition_context | secondary=control_challenge | static_bucket=nan
- 120165520_20260310-170038_sealed_extEq_intEq_Heat_Change_20260313-1002_unsealed | segment=pre_change | role=balanced_control | source=seal_change_to_unsealed | primary=transition_context | secondary=control_challenge | static_bucket=nan
- 120165520_20260315-140001_unsealed_extEq_intEq_noHeat_noChange_na | segment=full | role=balanced_control | source=full_run | primary=control_challenge | secondary= | static_bucket=nan
- 120165520_20260318-000055_sealed_extEq_intEq_noHeat_Change_20260318-0903_Heat | segment=post_change | role=balanced_control | source=heat_on | primary=control_challenge | secondary= | static_bucket=nan
- 120165520_20260318-090358_sealed_extEq_intEq_Heat_Change_20260319-1520_unsealed | segment=post_change | role=balanced_control | source=seal_change_to_unsealed | primary=transition_context | secondary=control_challenge | static_bucket=nan
- 120165520_20260318-090358_sealed_extEq_intEq_Heat_Change_20260319-1520_unsealed | segment=pre_change | role=balanced_control | source=seal_change_to_unsealed | primary=transition_context | secondary=control_challenge | static_bucket=nan
- 120165520_20260324_080048_sealed_extEq_intEq_Heat_Change_20260324-2207_noHeat | segment=post_change | role=balanced_control | source=heat_off | primary=control_challenge | secondary= | static_bucket=nan
- 120165520_20260324_080048_sealed_extEq_intEq_Heat_Change_20260324-2207_noHeat | segment=pre_change | role=balanced_control | source=heat_off | primary=control_challenge | secondary= | static_bucket=nan
- 120165524_20260313-080032_unsealed_extHigh_intLow_noHeat_Change_20260313-1001_Heat | segment=post_change | role=highhum_heated | source=heat_on | primary=control_challenge | secondary= | static_bucket=nan
- 120165524_20260314-174006_unsealed_extHigh_intLow_Heat_noChange_na | segment=full | role=highhum_heated | source=full_run | primary=control_challenge | secondary= | static_bucket=nan
- 120165524_20260317-180258_seal_heated_extHigh_intLow_noHeat_Change_20260317-1830_Heat | segment=post_change | role=highhum_heated | source=heat_on | primary=control_challenge | secondary= | static_bucket=nan
- 120165519_20260309-102255_sealed_extLow_intHigh_noHeat_Change_20260310-1000_unsealed | segment=post_change | role=internal_moisture_control | source=seal_change_to_unsealed | primary=transition_context | secondary=control_challenge | static_bucket=nan
- 120165519_20260309-102255_sealed_extLow_intHigh_noHeat_Change_20260310-1000_unsealed | segment=pre_change | role=internal_moisture_control | source=seal_change_to_unsealed | primary=transition_context | secondary=control_challenge | static_bucket=nan
- 120165519_20260313-111811_sealed_extLow_intHigh_Heat_Change_20260315-1500_unsealed | segment=post_change | role=internal_moisture_control | source=seal_change_to_unsealed | primary=transition_context | secondary=control_challenge | static_bucket=nan
- 120165519_20260313-111811_sealed_extLow_intHigh_Heat_Change_20260315-1500_unsealed | segment=pre_change | role=internal_moisture_control | source=seal_change_to_unsealed | primary=transition_context | secondary=control_challenge | static_bucket=nan
- 120165524_20260306-160246_sealed_extHigh_intLow_noHeat_noChange_na | segment=full | role=mainfield_extHigh_intLow_noHeat | source=full_run | primary=control_challenge | secondary= | static_bucket=static_breathing_watch
- 120165524_20260321-170450_unseal_extHigh_intLow_Heat_Change_20260321-1800_noHeat | segment=post_change | role=mainfield_extHigh_intLow_noHeat | source=heat_off | primary=control_challenge | secondary= | static_bucket=static_heatoff_confound_challenge

## 建模前建议

1. 先用 `static_negative_reference + static_positive_reference` 形成第一版段级静态参考池，不要把 `breathing_watch / heat_off confound / weak positive` 直接并进去。
2. `transition_primary_mainfield` 先用于事件级验证，`transition_secondary_control` 只作为辅助挑战集。
3. `control_challenge` 段优先用于检验误报控制和 `watch / abstain`，而不是拿来提升正样本数量。
4. 如果后面继续建模，应优先做段级 baseline，而不是 whole-run XGBoost/GRU。
