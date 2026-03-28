# 跨数据集特征守门分析 v1

- positive_count: `4`
- negative_count: `5`
- old_hard_negative_count: `3`

## 当前判断

- 这一步不是继续找新特征，而是检查：哪些特征在新数据主战场里看起来很强，但一碰到旧数据 hard negative 就会失真。
- 只有同时能托住当前正池、又能压住当前 breathing/confound 和旧数据 hard negative 的特征，才值得继续往 `support v3` 里推进。

## 当前最稳的跨数据集守门特征

- best_lag_level_hum | match=7/9 | ratio=0.778 | direction=neg | positive_median=0.000
- corr_headroom_in_hum | match=7/9 | ratio=0.778 | direction=neg | positive_median=-0.913
- corr_out_hum_in_hum | match=7/9 | ratio=0.778 | direction=pos | positive_median=0.990
- late_rh_gain_per_out | match=7/9 | ratio=0.778 | direction=pos | positive_median=2.946
- max_corr_level_hum | match=7/9 | ratio=0.778 | direction=pos | positive_median=0.994
- best_lag_rh_h | match=6/8 | ratio=0.750 | direction=neg | positive_median=0.000
- early_ah_resp_ratio | match=5/7 | ratio=0.714 | direction=pos | positive_median=0.900
- best_lag_dew_h | match=6/9 | ratio=0.667 | direction=pos | positive_median=1.500
- corr_dew_gap_in_dew | match=6/9 | ratio=0.667 | direction=neg | positive_median=-0.947
- dew_gap_area_pos | match=6/9 | ratio=0.667 | direction=pos | positive_median=256.166
- end_start_dAH | match=6/9 | ratio=0.667 | direction=pos | positive_median=0.363
- headroom_gain_ratio | match=6/9 | ratio=0.667 | direction=pos | positive_median=0.001

## 结论

1. 如果某个特征在当前主战场里 AUC 很高，但在旧数据 hard negative 上守不住，它就不该直接进入下一轮支持层。
2. 真正值得继续保留的特征，应优先来自 `response persistence / coupling / dew-driven early response` 这几类结构，而不是单纯依赖累计漂移。
3. 这一步的目标是为后续 `segment static support v3` 收窄特征集合，而不是重启统一分类器。
