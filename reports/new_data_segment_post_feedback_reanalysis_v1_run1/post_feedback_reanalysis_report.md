# 新补充数据 段级回灌后重分析报告

- mainfield_segment_count: `8`
- provisional_role_counts: `{'transition_positive': 3, 'negative_reference': 2, 'breathing_watch': 1, 'confound': 1, 'positive_reference': 1}`

## 当前判断

- 这一步不是训练新模型，而是用当前已经确认的高置信段，重新检查主战场静态池的结构是否更清楚。
- 当前主战场已经不再只有“2 个负参考 + 3 个正参考”，而是暂时扩成了：`2 negative + 4 positive + 1 breathing + 1 confound`。
- 因此现在最有价值的，不是继续找新特征，而是确认哪些特征在扩样本后仍然稳定，哪些只是对原始 5 个参考段过拟合。

## 当前最值得继续追的特征

- delta_half_in_h | auc=1.000 | direction=pos | negative_median=-0.315 | positive_median=2.378
- early_dew_gain_per_out | auc=1.000 | direction=pos | negative_median=0.321 | positive_median=1.085
- late_dew_gain_per_out | auc=1.000 | direction=neg | negative_median=1.486 | positive_median=0.830
- late_minus_early_dew_gain | auc=1.000 | direction=neg | negative_median=1.165 | positive_median=-0.341
- late_minus_early_rh_gain | auc=1.000 | direction=pos | negative_median=-0.105 | positive_median=1.766
- late_minus_early_vpd_gap | auc=1.000 | direction=pos | negative_median=-0.062 | positive_median=0.058
- max_corr_outRH_inRH_change | auc=1.000 | direction=pos | negative_median=-0.052 | positive_median=0.831
- slope_in_h_per_h | auc=1.000 | direction=pos | negative_median=-0.059 | positive_median=0.090
- weak_positive_support_score_v2 | auc=1.000 | direction=pos | negative_median=0.417 | positive_median=0.833
- amp_in_hum_p90_p10 | auc=0.875 | direction=pos | negative_median=1.462 | positive_median=3.816
- best_lag_h | auc=0.875 | direction=pos | negative_median=0.500 | positive_median=1.500
- best_lag_level_ah | auc=0.875 | direction=pos | negative_median=0.500 | positive_median=1.500

## 对难段更有用的特征

- delta_half_in_h | auc=1.000 | challenge_match=3/4
- late_minus_early_rh_gain | auc=1.000 | challenge_match=3/4
- weak_positive_support_score_v2 | auc=1.000 | challenge_match=3/4
- best_lag_level_hum | auc=0.875 | challenge_match=3/4
- end_start_dAH | auc=0.875 | challenge_match=3/4
- late_rh_gain_per_out | auc=0.875 | challenge_match=3/4
- vpd_in_mean | auc=0.875 | challenge_match=3/4
- ah_gap_q90 | auc=0.750 | challenge_match=3/4
- breathing_suppression_score_v2 | auc=0.750 | challenge_match=3/4
- confound_reject_score_v2 | auc=0.750 | challenge_match=3/4
- corr_headroom_in_hum | auc=0.750 | challenge_match=3/4
- positive_drive_ratio | auc=0.750 | challenge_match=3/4

## 段级参考池中的相对位置

- 120165524_20260306-160246_sealed_extHigh_intLow_noHeat_noChange_na::full | role=breathing_watch | d_pos=2.180 | d_neg=2.477 | margin=0.298
- 120165524_20260321-170450_unseal_extHigh_intLow_Heat_Change_20260321-1800_noHeat::post_change | role=confound | d_pos=1.753 | d_neg=2.255 | margin=0.502
- 120165524_20260302 161335_sealed_extHigh_intLow_noHeat_noChange_na::full | role=negative_reference | d_pos=3.900 | d_neg=2.264 | margin=-1.636
- 120165524_20260308-172014_sealed_extHigh_intLow_noHeat_Change_20260310-1000_unsealed::pre_change | role=negative_reference | d_pos=1.723 | d_neg=2.264 | margin=0.541
- 120165524_20260303-181049_unsealed_extHigh_intLow_noHeat_noChange_na::full | role=positive_reference | d_pos=2.165 | d_neg=2.654 | margin=0.489
- 120165524_20260304-120007_sealed_extHigh_intLow_noHeat_Change_20260304-1639_unsealed::post_change | role=transition_positive | d_pos=1.547 | d_neg=2.307 | margin=0.760
- 120165524_20260308-172014_sealed_extHigh_intLow_noHeat_Change_20260310-1000_unsealed::post_change | role=transition_positive | d_pos=1.492 | d_neg=2.659 | margin=1.167
- 120165524_20260323-213435_seal_extHigh_intLow_noHeat_Change_20260324-9000_unseal::post_change | role=transition_positive | d_pos=2.272 | d_neg=3.299 | margin=1.028

## 结论

1. `181049` 现在可以作为“被支持的正参考种子”存在，但它和三个 post-change 正参考并不完全同质，后续更适合区分 `strong positive` 和 `supported positive` 两层。
2. `160246` 和 `20260321 heat-off` 仍然不该进入正参考池；它们继续作为 `breathing` 和 `confound` 角色保留是正确的。
3. 扩样本和回灌之后，真正最稳的还是 `level-correlation + response persistence + neg-response suppression` 这组结构，而不是单一静态值。
4. 当前剩余未确认的都是 `transition_secondary_control`，说明主战场静态部分已经基本被收干净，后续若继续自动推进，应优先在当前参考池上做保守重评估，而不是再开 whole-run 统一分类。
