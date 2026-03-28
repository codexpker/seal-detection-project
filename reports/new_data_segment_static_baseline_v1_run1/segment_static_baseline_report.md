# 新补充数据 段级静态基线 v1 报告

## 核心结论

- reference_count: `5`
- apparent_coverage: `0.8`
- apparent_precision_on_resolved: `1.0`
- loo_coverage: `0.8`
- loo_precision_on_resolved: `1.0`
- raw_label_counts: `{'positive': 4, 'negative': 3, 'watch': 1}`
- final_assessment_counts: `{'confirmed_positive_reference': 3, 'confirmed_negative_reference': 2, 'review_weak_positive': 1, 'watch_breathing': 1, 'watch_confound': 1}`

## 当前判断

- 这版 `segment-level static baseline v1` 不是新的主模型，而是用 `5` 个干净静态参考段形成一个严格受控的段级静态评分器。
- 它的目标不是替代当前 `transition + evidence fuser` 主线，而是回答：新数据切成段以后，主战场静态段能不能形成一个最小可用的段级静态参考池。
- 当前结果表明：可以形成参考池，但仍然需要 `watch / challenge` 层来压住 sealed 难例和 heat-off 混淆段。

## 参考段自检

- apparent 结果按全参考池计算；leave-one-reference-out 结果用于看这 5 个参考段本身稳不稳。
- 如果 `loo` 覆盖率不满，优先解释为“参考池仍小且边界段存在”，而不是立即上更复杂模型。

### apparent reference results

- 120165524_20260302 161335_sealed_extHigh_intLow_noHeat_noChange_na::full | actual=negative | raw=negative | votes=0 | margin=-3.584 | resolved=True | correct=True
- 120165524_20260308-172014_sealed_extHigh_intLow_noHeat_Change_20260310-1000_unsealed::pre_change | actual=negative | raw=watch | votes=3 | margin=-0.273 | resolved=False | correct=False
- 120165524_20260304-120007_sealed_extHigh_intLow_noHeat_Change_20260304-1639_unsealed::post_change | actual=positive | raw=positive | votes=5 | margin=2.173 | resolved=True | correct=True
- 120165524_20260308-172014_sealed_extHigh_intLow_noHeat_Change_20260310-1000_unsealed::post_change | actual=positive | raw=positive | votes=5 | margin=3.261 | resolved=True | correct=True
- 120165524_20260323-213435_seal_extHigh_intLow_noHeat_Change_20260324-9000_unseal::post_change | actual=positive | raw=positive | votes=5 | margin=3.659 | resolved=True | correct=True

### leave-one-reference-out results

- 120165524_20260302 161335_sealed_extHigh_intLow_noHeat_noChange_na::full | actual=negative | raw=negative | votes=0 | margin=-3.274 | resolved=True | correct=True
- 120165524_20260308-172014_sealed_extHigh_intLow_noHeat_Change_20260310-1000_unsealed::pre_change | actual=negative | raw=watch | votes=3 | margin=1.391 | resolved=False | correct=False
- 120165524_20260304-120007_sealed_extHigh_intLow_noHeat_Change_20260304-1639_unsealed::post_change | actual=positive | raw=positive | votes=5 | margin=1.620 | resolved=True | correct=True
- 120165524_20260308-172014_sealed_extHigh_intLow_noHeat_Change_20260310-1000_unsealed::post_change | actual=positive | raw=positive | votes=5 | margin=2.946 | resolved=True | correct=True
- 120165524_20260323-213435_seal_extHigh_intLow_noHeat_Change_20260324-9000_unseal::post_change | actual=positive | raw=positive | votes=5 | margin=3.445 | resolved=True | correct=True

## 全部主战场静态段结果

- 120165524_20260302 161335_sealed_extHigh_intLow_noHeat_noChange_na::full | bucket=static_negative_reference | raw=negative | final=confirmed_negative_reference | votes=0 | margin=-3.584 | reason=segment is a clean negative reference for segment-level static modeling
- 120165524_20260308-172014_sealed_extHigh_intLow_noHeat_Change_20260310-1000_unsealed::pre_change | bucket=static_negative_reference | raw=watch | final=confirmed_negative_reference | votes=3 | margin=-0.273 | reason=segment is a clean negative reference for segment-level static modeling
- 120165524_20260304-120007_sealed_extHigh_intLow_noHeat_Change_20260304-1639_unsealed::post_change | bucket=static_positive_reference | raw=positive | final=confirmed_positive_reference | votes=5 | margin=2.173 | reason=segment is a clean post-change positive reference for segment-level static modeling
- 120165524_20260308-172014_sealed_extHigh_intLow_noHeat_Change_20260310-1000_unsealed::post_change | bucket=static_positive_reference | raw=positive | final=confirmed_positive_reference | votes=5 | margin=3.261 | reason=segment is a clean post-change positive reference for segment-level static modeling
- 120165524_20260323-213435_seal_extHigh_intLow_noHeat_Change_20260324-9000_unseal::post_change | bucket=static_positive_reference | raw=positive | final=confirmed_positive_reference | votes=5 | margin=3.659 | reason=segment is a clean post-change positive reference for segment-level static modeling
- 120165524_20260303-181049_unsealed_extHigh_intLow_noHeat_noChange_na::full | bucket=static_positive_eval_only | raw=negative | final=review_weak_positive | votes=1 | margin=-2.249 | reason=segment carries positive label but remains weak on the current static baseline
- 120165524_20260306-160246_sealed_extHigh_intLow_noHeat_noChange_na::full | bucket=static_breathing_watch | raw=positive | final=watch_breathing | votes=4 | margin=2.043 | reason=raw static score looks positive-like, but segment pipeline marks it as a sealed hard case
- 120165524_20260321-170450_unseal_extHigh_intLow_Heat_Change_20260321-1800_noHeat::post_change | bucket=static_heatoff_confound_challenge | raw=negative | final=watch_confound | votes=1 | margin=-2.214 | reason=segment enters the no-heat battlefield after heat-off and should not be treated as a clean static positive

## 结论

1. 当前新数据已经足够形成第一版段级静态参考池，但这个参考池仍然很小，不能直接重启 whole-run 分类器。
2. `breathing_watch` 段会被纯静态基线打成正样本倾向，说明 `watch / abstain` 仍然是必须保留的主线机制。
3. `weak positive` 段当前仍可能落到负样本一侧，说明静态主线还不能替代 transition 主线，只能补充主战场的强静态段。
4. 下一步如果继续建模，应直接在这批段级参考上做段级 baseline，对照 challenge 段，而不是把新数据退回 whole-run 训练。
