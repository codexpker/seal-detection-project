# 历史旧数据在当前主战场特征空间下的重评估 v2

- old_run_count: `34`
- selected_features: `['delta_half_in_h', 'early_dew_gain_per_out', 'late_dew_gain_per_out', 'late_minus_early_dew_gain', 'late_minus_early_rh_gain', 'late_minus_early_vpd_gap', 'max_corr_outRH_inRH_change', 'slope_in_h_per_h']`
- subgroup_projection_counts: `{'sealed_no_screw_grease': {'old_ambiguous': 3, 'old_negative_like': 3, 'old_positive_like': 1}, 'sealed_strict': {'old_ambiguous': 10, 'old_negative_like': 6, 'old_positive_like': 3}, 'unsealed': {'old_ambiguous': 6, 'old_negative_like': 1, 'old_positive_like': 1}}`
- strict_positive_like_count_v2: `3`

## 当前判断

- 这一步不是把旧数据重新并入主训练，而是检查：在当前已经确认过的主战场特征空间里，旧数据会不会继续污染主战场。
- 评估方式不是重新训 whole-run 分类器，而是把旧数据直接投到“当前正/负参考池”的结构特征空间里，看它更靠近哪一侧。

## 当前采用的主战场特征

- delta_half_in_h
- early_dew_gain_per_out
- late_dew_gain_per_out
- late_minus_early_dew_gain
- late_minus_early_rh_gain
- late_minus_early_vpd_gap
- max_corr_outRH_inRH_change
- slope_in_h_per_h

## old_data 内部 unsealed vs strict sealed 仍然最有价值的特征

- late_minus_early_rh_gain | auc=0.730 | direction=pos | strict_median=-0.228 | unsealed_median=0.355
- late_minus_early_dew_gain | auc=0.639 | direction=neg | strict_median=0.000 | unsealed_median=-0.607
- early_dew_gain_per_out | auc=0.625 | direction=pos | strict_median=0.459 | unsealed_median=1.199
- late_minus_early_vpd_gap | auc=0.583 | direction=neg | strict_median=0.258 | unsealed_median=0.278
- delta_half_in_h | auc=0.566 | direction=neg | strict_median=0.927 | unsealed_median=0.204
- slope_in_h_per_h | auc=0.539 | direction=neg | strict_median=0.061 | unsealed_median=0.045
- max_corr_outRH_inRH_change | auc=0.524 | direction=neg | strict_median=0.427 | unsealed_median=0.718
- late_dew_gain_per_out | auc=0.521 | direction=neg | strict_median=0.474 | unsealed_median=0.459

## 仍然最危险的 strict sealed 运行

- 2025-10-28 110628 | positive_vote_ratio=0.750 | margin=3.630
- 2025-10-21 101019 | positive_vote_ratio=0.857 | margin=2.274
- 2025-11-18 104042 | positive_vote_ratio=0.750 | margin=2.151

## 结论

1. 旧数据值得重新评估，但重新评估的结果如果仍显示存在一批 `strict sealed` 会落到正侧，就说明它依旧不该并入主训练集。
2. 如果某些新增结构特征能把 `strict sealed` 压回负侧，它们就更适合接入 `watch / confound suppress`，而不是直接拿来重开统一分类器。
3. 因此这一步真正回答的是“旧数据在当前主战场里扮演什么角色”，而不是“旧数据能不能立刻拿来扩监督样本”。
