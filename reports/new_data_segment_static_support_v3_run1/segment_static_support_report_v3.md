# 新补充数据 Segment Static Support v3

## 核心结论

- segment_support_counts_v3: `{'control_challenge_support': 8, 'transition_secondary_control': 8, 'short_context_only': 7, 'static_positive_reference_support': 3, 'static_negative_reference_support': 2, 'transition_primary_support': 2, 'static_review_weak_positive_guarded': 1, 'static_watch_breathing_hardguard': 1, 'static_watch_confound_hardguard': 1}`
- run_support_counts_v3: `{'control_challenge_support': 7, 'transition_secondary_control': 4, 'transition_primary_support': 3, 'short_context_only': 2, 'static_negative_reference_support': 1, 'static_review_weak_positive_guarded': 1, 'static_watch_breathing_hardguard': 1, 'static_watch_confound_hardguard': 1}`
- old_hard_negative_anomaly_false_positive_count_v3: `0`
- weak_positive_guarded_runs_v3: `0`
- weak_positive_memory_unresolved_runs_v3: `1`
- breathing_hardguard_runs_v3: `1`
- confound_hardguard_runs_v3: `1`

## 当前判断

- 这一步不是继续放大静态支持，而是给 `v2` 加上跨数据集守门和 old hard negative 约束。
- 只有守门特征和 tri-memory 同时站得住，弱正样本才允许继续保留支持；否则回到 review。
- `breathing_watch / confound` 如果在 tri-memory 下仍靠近 hard negative，就继续压实为 watch，不允许被重新抬成正侧。

## 运行级支持结果

- 120165518_20260308-104441_sealed_extEq_intEq_noHeat_noChange_na | status=control_challenge_support | risk=none | primary_segment=full | guard=nan | memory=nan | anomaly_adv=nan | needs_review=False | reason=segment belongs to the control/challenge pool and is used to constrain false positives
- 120165520_20260315-140001_unsealed_extEq_intEq_noHeat_noChange_na | status=control_challenge_support | risk=none | primary_segment=full | guard=nan | memory=nan | anomaly_adv=nan | needs_review=False | reason=segment belongs to the control/challenge pool and is used to constrain false positives
- 120165520_20260318-000055_sealed_extEq_intEq_noHeat_Change_20260318-0903_Heat | status=control_challenge_support | risk=none | primary_segment=post_change | guard=nan | memory=nan | anomaly_adv=nan | needs_review=False | reason=segment belongs to the control/challenge pool and is used to constrain false positives
- 120165520_20260324_080048_sealed_extEq_intEq_Heat_Change_20260324-2207_noHeat | status=control_challenge_support | risk=none | primary_segment=pre_change | guard=nan | memory=nan | anomaly_adv=nan | needs_review=False | reason=segment belongs to the control/challenge pool and is used to constrain false positives
- 120165524_20260313-080032_unsealed_extHigh_intLow_noHeat_Change_20260313-1001_Heat | status=control_challenge_support | risk=none | primary_segment=post_change | guard=nan | memory=nan | anomaly_adv=nan | needs_review=False | reason=segment belongs to the control/challenge pool and is used to constrain false positives
- 120165524_20260314-174006_unsealed_extHigh_intLow_Heat_noChange_na | status=control_challenge_support | risk=none | primary_segment=full | guard=nan | memory=nan | anomaly_adv=nan | needs_review=False | reason=segment belongs to the control/challenge pool and is used to constrain false positives
- 120165524_20260317-180258_seal_heated_extHigh_intLow_noHeat_Change_20260317-1830_Heat | status=control_challenge_support | risk=none | primary_segment=post_change | guard=nan | memory=nan | anomaly_adv=nan | needs_review=False | reason=segment belongs to the control/challenge pool and is used to constrain false positives
- 120165520_20260323-120048_unseal_extEq_intLow_Heat_Change_20260323-1545_extHigh | status=short_context_only | risk=none | primary_segment=post_change | guard=nan | memory=nan | anomaly_adv=nan | needs_review=False | reason=segment is too short for analyzable segment-level use and only keeps local context
- 120165524_20260303-101220_sealed_extHigh_intLow_Heat_noChange_na | status=short_context_only | risk=none | primary_segment=full | guard=nan | memory=nan | anomaly_adv=nan | needs_review=False | reason=segment is too short for analyzable segment-level use and only keeps local context
- 120165524_20260302 161335_sealed_extHigh_intLow_noHeat_noChange_na | status=static_negative_reference_support | risk=none | primary_segment=full | guard=0.22 | memory=health_core | anomaly_adv=-76.19 | needs_review=False | reason=segment remains a clean static negative reference in the main battlefield
- 120165524_20260303-181049_unsealed_extHigh_intLow_noHeat_noChange_na | status=static_review_weak_positive_guarded | risk=watch | primary_segment=full | guard=0.54 | memory=hard_negative | anomaly_adv=-5.48 | needs_review=True | reason=weak positive keeps local support but does not pass cross-dataset hard-negative guard; guard=0.54, memory=hard_negative, anomaly_adv=-5.48
- 120165524_20260306-160246_sealed_extHigh_intLow_noHeat_noChange_na | status=static_watch_breathing_hardguard | risk=watch | primary_segment=full | guard=0.41 | memory=hard_negative | anomaly_adv=-0.83 | needs_review=True | reason=breathing watch is reinforced by tri-memory hard_negative with anomaly_adv -0.83 and suppression 1.00
- 120165524_20260321-170450_unseal_extHigh_intLow_Heat_Change_20260321-1800_noHeat | status=static_watch_confound_hardguard | risk=watch | primary_segment=post_change | guard=0.48 | memory=hard_negative | anomaly_adv=-6.76 | needs_review=True | reason=confound watch is reinforced by tri-memory hard_negative with anomaly_adv -6.76 and reject score 1.00
- 120165524_20260304-120007_sealed_extHigh_intLow_noHeat_Change_20260304-1639_unsealed | status=transition_primary_support | risk=high | primary_segment=post_change | guard=0.23 | memory=anomaly_reference | anomaly_adv=3.53 | needs_review=True | reason=run contains a mainfield seal-to-unsealed transition and should stay transition-led
- 120165524_20260308-172014_sealed_extHigh_intLow_noHeat_Change_20260310-1000_unsealed | status=transition_primary_support | risk=high | primary_segment=post_change | guard=0.59 | memory=anomaly_reference | anomaly_adv=6.55 | needs_review=True | reason=run contains a mainfield seal-to-unsealed transition and should stay transition-led
- 120165524_20260323-213435_seal_extHigh_intLow_noHeat_Change_20260324-9000_unseal | status=transition_primary_support | risk=high | primary_segment=post_change | guard=0.71 | memory=anomaly_reference | anomaly_adv=2.54 | needs_review=True | reason=run contains a mainfield seal-to-unsealed transition and should stay transition-led
- 120165519_20260309-102255_sealed_extLow_intHigh_noHeat_Change_20260310-1000_unsealed | status=transition_secondary_control | risk=watch | primary_segment=post_change | guard=nan | memory=nan | anomaly_adv=nan | needs_review=True | reason=segment belongs to a seal-change run outside the main battlefield and should stay as a transition challenge
- 120165519_20260313-111811_sealed_extLow_intHigh_Heat_Change_20260315-1500_unsealed | status=transition_secondary_control | risk=watch | primary_segment=post_change | guard=nan | memory=nan | anomaly_adv=nan | needs_review=True | reason=segment belongs to a seal-change run outside the main battlefield and should stay as a transition challenge
- 120165520_20260310-170038_sealed_extEq_intEq_Heat_Change_20260313-1002_unsealed | status=transition_secondary_control | risk=watch | primary_segment=post_change | guard=nan | memory=nan | anomaly_adv=nan | needs_review=True | reason=segment belongs to a seal-change run outside the main battlefield and should stay as a transition challenge
- 120165520_20260318-090358_sealed_extEq_intEq_Heat_Change_20260319-1520_unsealed | status=transition_secondary_control | risk=watch | primary_segment=post_change | guard=nan | memory=nan | anomaly_adv=nan | needs_review=True | reason=segment belongs to a seal-change run outside the main battlefield and should stay as a transition challenge

## 建议复核队列

- 120165524_20260304-120007_sealed_extHigh_intLow_noHeat_Change_20260304-1639_unsealed | segment=post_change | status=transition_primary_support | priority=0 | memory=anomaly_reference | reason=run contains a mainfield seal-to-unsealed transition and should stay transition-led
- 120165524_20260308-172014_sealed_extHigh_intLow_noHeat_Change_20260310-1000_unsealed | segment=post_change | status=transition_primary_support | priority=0 | memory=anomaly_reference | reason=run contains a mainfield seal-to-unsealed transition and should stay transition-led
- 120165524_20260323-213435_seal_extHigh_intLow_noHeat_Change_20260324-9000_unseal | segment=post_change | status=transition_primary_support | priority=0 | memory=anomaly_reference | reason=run contains a mainfield seal-to-unsealed transition and should stay transition-led
- 120165524_20260303-181049_unsealed_extHigh_intLow_noHeat_noChange_na | segment=full | status=static_review_weak_positive_guarded | priority=2 | memory=hard_negative | reason=weak positive keeps local support but does not pass cross-dataset hard-negative guard; guard=0.54, memory=hard_negative, anomaly_adv=-5.48
- 120165524_20260306-160246_sealed_extHigh_intLow_noHeat_noChange_na | segment=full | status=static_watch_breathing_hardguard | priority=3 | memory=hard_negative | reason=breathing watch is reinforced by tri-memory hard_negative with anomaly_adv -0.83 and suppression 1.00
- 120165524_20260321-170450_unseal_extHigh_intLow_Heat_Change_20260321-1800_noHeat | segment=post_change | status=static_watch_confound_hardguard | priority=5 | memory=hard_negative | reason=confound watch is reinforced by tri-memory hard_negative with anomaly_adv -6.76 and reject score 1.00
- 120165519_20260309-102255_sealed_extLow_intHigh_noHeat_Change_20260310-1000_unsealed | segment=post_change | status=transition_secondary_control | priority=7 | memory=nan | reason=segment belongs to a seal-change run outside the main battlefield and should stay as a transition challenge
- 120165519_20260313-111811_sealed_extLow_intHigh_Heat_Change_20260315-1500_unsealed | segment=post_change | status=transition_secondary_control | priority=7 | memory=nan | reason=segment belongs to a seal-change run outside the main battlefield and should stay as a transition challenge
- 120165520_20260310-170038_sealed_extEq_intEq_Heat_Change_20260313-1002_unsealed | segment=post_change | status=transition_secondary_control | priority=7 | memory=nan | reason=segment belongs to a seal-change run outside the main battlefield and should stay as a transition challenge
- 120165520_20260318-090358_sealed_extEq_intEq_Heat_Change_20260319-1520_unsealed | segment=post_change | status=transition_secondary_control | priority=7 | memory=nan | reason=segment belongs to a seal-change run outside the main battlefield and should stay as a transition challenge

## Old Hard Negative 守门结果

- old::2025-10-21 101019 | predicted=hard_negative | anomaly_adv=-4.95 | health_only_risk=54.63
- old::2025-10-28 110628 | predicted=health_core | anomaly_adv=-73.43 | health_only_risk=36.83
- old::2025-11-18 104042 | predicted=health_core | anomaly_adv=-75.44 | health_only_risk=40.57

## 结论

1. `v3` 的主要目标是验证“old hard negatives 不会被静态支持层重新推成 anomaly-like”，不是继续追求更高的静态覆盖率。
2. 如果 `weak positive` 在 tri-memory 下仍然落到 hard negative 一侧，就说明它当前只能保留为 review 支持，而不能安全升级成更强的正参考。
3. `breathing_watch / confound` 若在 tri-memory 下继续靠近 hard negative，说明当前主线程里的 `watch` 处理是正确的。
4. 下一步若继续推进，应优先把这套 guarded 结果接到 review/rerank，而不是接到默认 `final_status`。
