# 新补充数据 Segment Static Support v1

## 核心结论

- segment_support_counts: `{'control_challenge_support': 8, 'transition_secondary_control': 8, 'short_context_only': 7, 'static_positive_reference_support': 3, 'static_negative_reference_support': 2, 'transition_primary_support': 2, 'static_review_weak_positive': 1, 'static_watch_breathing': 1, 'static_watch_confound': 1}`
- run_support_counts: `{'control_challenge_support': 7, 'transition_secondary_control': 4, 'transition_primary_support': 3, 'short_context_only': 2, 'static_negative_reference_support': 1, 'static_review_weak_positive': 1, 'static_watch_breathing': 1, 'static_watch_confound': 1}`
- review_segment_count: `10`
- review_run_count: `10`

## 当前判断

- 这一步不是替换现有 whole-run 主链，而是给新补充数据增加一个段级支持层。
- 它把 `静态参考段 / transition 主证据 / watch / control challenge` 收成统一输出，方便后续复核、讲解和与主链对齐。
- 当前最值得优先看的仍然是 `transition_primary_support`、`static_review_weak_positive` 和 `static_watch_breathing`。

## 运行级支持结果

- 120165518_20260308-104441_sealed_extEq_intEq_noHeat_noChange_na | status=control_challenge_support | risk=none | primary_segment=full | needs_review=False | reason=segment belongs to the control/challenge pool and is used to constrain false positives
- 120165520_20260315-140001_unsealed_extEq_intEq_noHeat_noChange_na | status=control_challenge_support | risk=none | primary_segment=full | needs_review=False | reason=segment belongs to the control/challenge pool and is used to constrain false positives
- 120165520_20260318-000055_sealed_extEq_intEq_noHeat_Change_20260318-0903_Heat | status=control_challenge_support | risk=none | primary_segment=post_change | needs_review=False | reason=segment belongs to the control/challenge pool and is used to constrain false positives
- 120165520_20260324_080048_sealed_extEq_intEq_Heat_Change_20260324-2207_noHeat | status=control_challenge_support | risk=none | primary_segment=pre_change | needs_review=False | reason=segment belongs to the control/challenge pool and is used to constrain false positives
- 120165524_20260313-080032_unsealed_extHigh_intLow_noHeat_Change_20260313-1001_Heat | status=control_challenge_support | risk=none | primary_segment=post_change | needs_review=False | reason=segment belongs to the control/challenge pool and is used to constrain false positives
- 120165524_20260314-174006_unsealed_extHigh_intLow_Heat_noChange_na | status=control_challenge_support | risk=none | primary_segment=full | needs_review=False | reason=segment belongs to the control/challenge pool and is used to constrain false positives
- 120165524_20260317-180258_seal_heated_extHigh_intLow_noHeat_Change_20260317-1830_Heat | status=control_challenge_support | risk=none | primary_segment=post_change | needs_review=False | reason=segment belongs to the control/challenge pool and is used to constrain false positives
- 120165520_20260323-120048_unseal_extEq_intLow_Heat_Change_20260323-1545_extHigh | status=short_context_only | risk=none | primary_segment=post_change | needs_review=False | reason=segment is too short for analyzable segment-level use and only keeps local context
- 120165524_20260303-101220_sealed_extHigh_intLow_Heat_noChange_na | status=short_context_only | risk=none | primary_segment=full | needs_review=False | reason=segment is too short for analyzable segment-level use and only keeps local context
- 120165524_20260302 161335_sealed_extHigh_intLow_noHeat_noChange_na | status=static_negative_reference_support | risk=none | primary_segment=full | needs_review=False | reason=segment is a clean static negative reference in the main battlefield
- 120165524_20260303-181049_unsealed_extHigh_intLow_noHeat_noChange_na | status=static_review_weak_positive | risk=watch | primary_segment=full | needs_review=True | reason=segment carries positive label but static evidence remains weak and should be reviewed instead of promoted
- 120165524_20260306-160246_sealed_extHigh_intLow_noHeat_noChange_na | status=static_watch_breathing | risk=watch | primary_segment=full | needs_review=True | reason=segment looks positive-like to the raw static baseline but remains a sealed breathing hard case
- 120165524_20260321-170450_unseal_extHigh_intLow_Heat_Change_20260321-1800_noHeat | status=static_watch_confound | risk=watch | primary_segment=post_change | needs_review=True | reason=segment enters the battlefield after heat-off and should not be treated as a clean static positive
- 120165524_20260304-120007_sealed_extHigh_intLow_noHeat_Change_20260304-1639_unsealed | status=transition_primary_support | risk=high | primary_segment=post_change | needs_review=True | reason=run contains a mainfield seal-to-unsealed transition and should stay transition-led
- 120165524_20260308-172014_sealed_extHigh_intLow_noHeat_Change_20260310-1000_unsealed | status=transition_primary_support | risk=high | primary_segment=post_change | needs_review=True | reason=run contains a mainfield seal-to-unsealed transition and should stay transition-led
- 120165524_20260323-213435_seal_extHigh_intLow_noHeat_Change_20260324-9000_unseal | status=transition_primary_support | risk=high | primary_segment=post_change | needs_review=True | reason=run contains a mainfield seal-to-unsealed transition and should stay transition-led
- 120165519_20260309-102255_sealed_extLow_intHigh_noHeat_Change_20260310-1000_unsealed | status=transition_secondary_control | risk=watch | primary_segment=post_change | needs_review=True | reason=segment belongs to a seal-change run outside the main battlefield and should stay as a transition challenge
- 120165519_20260313-111811_sealed_extLow_intHigh_Heat_Change_20260315-1500_unsealed | status=transition_secondary_control | risk=watch | primary_segment=post_change | needs_review=True | reason=segment belongs to a seal-change run outside the main battlefield and should stay as a transition challenge
- 120165520_20260310-170038_sealed_extEq_intEq_Heat_Change_20260313-1002_unsealed | status=transition_secondary_control | risk=watch | primary_segment=post_change | needs_review=True | reason=segment belongs to a seal-change run outside the main battlefield and should stay as a transition challenge
- 120165520_20260318-090358_sealed_extEq_intEq_Heat_Change_20260319-1520_unsealed | status=transition_secondary_control | risk=watch | primary_segment=post_change | needs_review=True | reason=segment belongs to a seal-change run outside the main battlefield and should stay as a transition challenge

## 建议复核队列

- 120165524_20260304-120007_sealed_extHigh_intLow_noHeat_Change_20260304-1639_unsealed | segment=post_change | status=transition_primary_support | priority=0 | reason=run contains a mainfield seal-to-unsealed transition and should stay transition-led
- 120165524_20260308-172014_sealed_extHigh_intLow_noHeat_Change_20260310-1000_unsealed | segment=post_change | status=transition_primary_support | priority=0 | reason=run contains a mainfield seal-to-unsealed transition and should stay transition-led
- 120165524_20260323-213435_seal_extHigh_intLow_noHeat_Change_20260324-9000_unseal | segment=post_change | status=transition_primary_support | priority=0 | reason=run contains a mainfield seal-to-unsealed transition and should stay transition-led
- 120165524_20260303-181049_unsealed_extHigh_intLow_noHeat_noChange_na | segment=full | status=static_review_weak_positive | priority=1 | reason=segment carries positive label but static evidence remains weak and should be reviewed instead of promoted
- 120165524_20260306-160246_sealed_extHigh_intLow_noHeat_noChange_na | segment=full | status=static_watch_breathing | priority=2 | reason=segment looks positive-like to the raw static baseline but remains a sealed breathing hard case
- 120165524_20260321-170450_unseal_extHigh_intLow_Heat_Change_20260321-1800_noHeat | segment=post_change | status=static_watch_confound | priority=3 | reason=segment enters the battlefield after heat-off and should not be treated as a clean static positive
- 120165519_20260309-102255_sealed_extLow_intHigh_noHeat_Change_20260310-1000_unsealed | segment=post_change | status=transition_secondary_control | priority=4 | reason=segment belongs to a seal-change run outside the main battlefield and should stay as a transition challenge
- 120165519_20260313-111811_sealed_extLow_intHigh_Heat_Change_20260315-1500_unsealed | segment=post_change | status=transition_secondary_control | priority=4 | reason=segment belongs to a seal-change run outside the main battlefield and should stay as a transition challenge
- 120165520_20260310-170038_sealed_extEq_intEq_Heat_Change_20260313-1002_unsealed | segment=post_change | status=transition_secondary_control | priority=4 | reason=segment belongs to a seal-change run outside the main battlefield and should stay as a transition challenge
- 120165520_20260318-090358_sealed_extEq_intEq_Heat_Change_20260319-1520_unsealed | segment=post_change | status=transition_secondary_control | priority=4 | reason=segment belongs to a seal-change run outside the main battlefield and should stay as a transition challenge

## 结论

1. `transition_primary_support` 仍然是当前最强主证据，应优先用于事件级验证和演示。
2. `static_positive_reference_support / static_negative_reference_support` 可以作为新数据段级静态参考池，不应被回退成 whole-run 标签样本。
3. `static_review_weak_positive / static_watch_breathing / static_watch_confound` 说明静态主线仍然离不开 review/watch 机制。
4. `control_challenge_support` 继续保留为误报约束，不进入正样本训练。
