# 新补充数据 Segment Static Support v2

## 核心结论

- segment_support_counts_v2: `{'control_challenge_support': 8, 'transition_secondary_control': 8, 'short_context_only': 7, 'static_positive_reference_support': 3, 'static_negative_reference_support': 2, 'transition_primary_support': 2, 'static_supported_weak_positive': 1, 'static_watch_breathing_confirmed': 1, 'static_watch_confound_confirmed': 1}`
- run_support_counts_v2: `{'control_challenge_support': 7, 'transition_secondary_control': 4, 'transition_primary_support': 3, 'short_context_only': 2, 'static_negative_reference_support': 1, 'static_supported_weak_positive': 1, 'static_watch_breathing_confirmed': 1, 'static_watch_confound_confirmed': 1}`
- weak_positive_upgraded_runs_v2: `1`
- breathing_confirmed_runs_v2: `1`
- confound_confirmed_runs_v2: `1`

## 当前判断

- 这一步不是重开 whole-run 模型，而是把新增 `dew / ingress` 特征克制地接成三个子评分。
- `transition_primary_support` 仍然优先，不会被静态支持层抢走主导权。
- `v2` 只做三类事：提升真正的 weak positive、压实 breathing watch、压实 heat-off confound。

## 运行级支持结果

- 120165518_20260308-104441_sealed_extEq_intEq_noHeat_noChange_na | status=control_challenge_support | risk=none | primary_segment=full | weak_support=nan | breathing_suppress=nan | confound_reject=nan | needs_review=False | reason=segment belongs to the control/challenge pool and is used to constrain false positives
- 120165520_20260315-140001_unsealed_extEq_intEq_noHeat_noChange_na | status=control_challenge_support | risk=none | primary_segment=full | weak_support=nan | breathing_suppress=nan | confound_reject=nan | needs_review=False | reason=segment belongs to the control/challenge pool and is used to constrain false positives
- 120165520_20260318-000055_sealed_extEq_intEq_noHeat_Change_20260318-0903_Heat | status=control_challenge_support | risk=none | primary_segment=post_change | weak_support=nan | breathing_suppress=nan | confound_reject=nan | needs_review=False | reason=segment belongs to the control/challenge pool and is used to constrain false positives
- 120165520_20260324_080048_sealed_extEq_intEq_Heat_Change_20260324-2207_noHeat | status=control_challenge_support | risk=none | primary_segment=pre_change | weak_support=nan | breathing_suppress=nan | confound_reject=nan | needs_review=False | reason=segment belongs to the control/challenge pool and is used to constrain false positives
- 120165524_20260313-080032_unsealed_extHigh_intLow_noHeat_Change_20260313-1001_Heat | status=control_challenge_support | risk=none | primary_segment=post_change | weak_support=nan | breathing_suppress=nan | confound_reject=nan | needs_review=False | reason=segment belongs to the control/challenge pool and is used to constrain false positives
- 120165524_20260314-174006_unsealed_extHigh_intLow_Heat_noChange_na | status=control_challenge_support | risk=none | primary_segment=full | weak_support=nan | breathing_suppress=nan | confound_reject=nan | needs_review=False | reason=segment belongs to the control/challenge pool and is used to constrain false positives
- 120165524_20260317-180258_seal_heated_extHigh_intLow_noHeat_Change_20260317-1830_Heat | status=control_challenge_support | risk=none | primary_segment=post_change | weak_support=nan | breathing_suppress=nan | confound_reject=nan | needs_review=False | reason=segment belongs to the control/challenge pool and is used to constrain false positives
- 120165520_20260323-120048_unseal_extEq_intLow_Heat_Change_20260323-1545_extHigh | status=short_context_only | risk=none | primary_segment=post_change | weak_support=nan | breathing_suppress=nan | confound_reject=nan | needs_review=False | reason=segment is too short for analyzable segment-level use and only keeps local context
- 120165524_20260303-101220_sealed_extHigh_intLow_Heat_noChange_na | status=short_context_only | risk=none | primary_segment=full | weak_support=nan | breathing_suppress=nan | confound_reject=nan | needs_review=False | reason=segment is too short for analyzable segment-level use and only keeps local context
- 120165524_20260302 161335_sealed_extHigh_intLow_noHeat_noChange_na | status=static_negative_reference_support | risk=none | primary_segment=full | weak_support=0.33 | breathing_suppress=1.00 | confound_reject=0.60 | needs_review=False | reason=segment remains a clean static negative reference in the main battlefield
- 120165524_20260303-181049_unsealed_extHigh_intLow_noHeat_noChange_na | status=static_supported_weak_positive | risk=medium | primary_segment=full | weak_support=1.00 | breathing_suppress=1.00 | confound_reject=0.75 | needs_review=True | reason=raw static baseline stayed weak but multiview support score rose to 1.00
- 120165524_20260306-160246_sealed_extHigh_intLow_noHeat_noChange_na | status=static_watch_breathing_confirmed | risk=watch | primary_segment=full | weak_support=0.17 | breathing_suppress=1.00 | confound_reject=0.60 | needs_review=True | reason=raw positive tendency is suppressed by breathing pattern score 1.00 with low support 0.17
- 120165524_20260321-170450_unseal_extHigh_intLow_Heat_Change_20260321-1800_noHeat | status=static_watch_confound_confirmed | risk=watch | primary_segment=post_change | weak_support=0.33 | breathing_suppress=0.80 | confound_reject=1.00 | needs_review=True | reason=segment matches heat-off confound pattern score 1.00 with low support 0.33
- 120165524_20260304-120007_sealed_extHigh_intLow_noHeat_Change_20260304-1639_unsealed | status=transition_primary_support | risk=high | primary_segment=post_change | weak_support=0.67 | breathing_suppress=1.00 | confound_reject=0.40 | needs_review=True | reason=run contains a mainfield seal-to-unsealed transition and should stay transition-led
- 120165524_20260308-172014_sealed_extHigh_intLow_noHeat_Change_20260310-1000_unsealed | status=transition_primary_support | risk=high | primary_segment=post_change | weak_support=1.00 | breathing_suppress=0.00 | confound_reject=0.40 | needs_review=True | reason=run contains a mainfield seal-to-unsealed transition and should stay transition-led
- 120165524_20260323-213435_seal_extHigh_intLow_noHeat_Change_20260324-9000_unseal | status=transition_primary_support | risk=high | primary_segment=post_change | weak_support=0.67 | breathing_suppress=0.00 | confound_reject=0.60 | needs_review=True | reason=run contains a mainfield seal-to-unsealed transition and should stay transition-led
- 120165519_20260309-102255_sealed_extLow_intHigh_noHeat_Change_20260310-1000_unsealed | status=transition_secondary_control | risk=watch | primary_segment=post_change | weak_support=nan | breathing_suppress=nan | confound_reject=nan | needs_review=True | reason=segment belongs to a seal-change run outside the main battlefield and should stay as a transition challenge
- 120165519_20260313-111811_sealed_extLow_intHigh_Heat_Change_20260315-1500_unsealed | status=transition_secondary_control | risk=watch | primary_segment=post_change | weak_support=nan | breathing_suppress=nan | confound_reject=nan | needs_review=True | reason=segment belongs to a seal-change run outside the main battlefield and should stay as a transition challenge
- 120165520_20260310-170038_sealed_extEq_intEq_Heat_Change_20260313-1002_unsealed | status=transition_secondary_control | risk=watch | primary_segment=post_change | weak_support=nan | breathing_suppress=nan | confound_reject=nan | needs_review=True | reason=segment belongs to a seal-change run outside the main battlefield and should stay as a transition challenge
- 120165520_20260318-090358_sealed_extEq_intEq_Heat_Change_20260319-1520_unsealed | status=transition_secondary_control | risk=watch | primary_segment=post_change | weak_support=nan | breathing_suppress=nan | confound_reject=nan | needs_review=True | reason=segment belongs to a seal-change run outside the main battlefield and should stay as a transition challenge

## 建议复核队列

- 120165524_20260304-120007_sealed_extHigh_intLow_noHeat_Change_20260304-1639_unsealed | segment=post_change | status=transition_primary_support | priority=0 | reason=run contains a mainfield seal-to-unsealed transition and should stay transition-led
- 120165524_20260308-172014_sealed_extHigh_intLow_noHeat_Change_20260310-1000_unsealed | segment=post_change | status=transition_primary_support | priority=0 | reason=run contains a mainfield seal-to-unsealed transition and should stay transition-led
- 120165524_20260323-213435_seal_extHigh_intLow_noHeat_Change_20260324-9000_unseal | segment=post_change | status=transition_primary_support | priority=0 | reason=run contains a mainfield seal-to-unsealed transition and should stay transition-led
- 120165524_20260303-181049_unsealed_extHigh_intLow_noHeat_noChange_na | segment=full | status=static_supported_weak_positive | priority=1 | reason=raw static baseline stayed weak but multiview support score rose to 1.00
- 120165524_20260306-160246_sealed_extHigh_intLow_noHeat_noChange_na | segment=full | status=static_watch_breathing_confirmed | priority=3 | reason=raw positive tendency is suppressed by breathing pattern score 1.00 with low support 0.17
- 120165524_20260321-170450_unseal_extHigh_intLow_Heat_Change_20260321-1800_noHeat | segment=post_change | status=static_watch_confound_confirmed | priority=5 | reason=segment matches heat-off confound pattern score 1.00 with low support 0.33
- 120165519_20260309-102255_sealed_extLow_intHigh_noHeat_Change_20260310-1000_unsealed | segment=post_change | status=transition_secondary_control | priority=7 | reason=segment belongs to a seal-change run outside the main battlefield and should stay as a transition challenge
- 120165519_20260313-111811_sealed_extLow_intHigh_Heat_Change_20260315-1500_unsealed | segment=post_change | status=transition_secondary_control | priority=7 | reason=segment belongs to a seal-change run outside the main battlefield and should stay as a transition challenge
- 120165520_20260310-170038_sealed_extEq_intEq_Heat_Change_20260313-1002_unsealed | segment=post_change | status=transition_secondary_control | priority=7 | reason=segment belongs to a seal-change run outside the main battlefield and should stay as a transition challenge
- 120165520_20260318-090358_sealed_extEq_intEq_Heat_Change_20260319-1520_unsealed | segment=post_change | status=transition_secondary_control | priority=7 | reason=segment belongs to a seal-change run outside the main battlefield and should stay as a transition challenge

## 结论

1. `transition_primary_support` 仍然是主证据，不被静态支持层替代。
2. `static_supported_weak_positive` 表示原始基线偏弱，但多视角结构特征已经给出足够的正向支持。
3. `static_watch_breathing_confirmed / static_watch_confound_confirmed` 表示这些 watch 状态不是偶然噪声，而是被新增结构特征进一步压实。
4. 下一步如果继续推进，应优先把这三个子评分接进真实复核队列，而不是再开新的 whole-run 模型线。
