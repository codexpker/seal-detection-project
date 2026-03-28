# 新补充数据 扩样本多视角特征挖掘报告

- mainfield_segment_count: `8`
- reference_count: `5`
- reference_class_counts: `{'unsealed': 3, 'sealed': 2}`
- challenge_role_counts: `{'positive_reference': 3, 'negative_reference': 2, 'breathing_watch': 1, 'heatoff_confound': 1, 'weak_positive': 1}`

## 当前判断

- 扩样本后，主战场段级数据里确实出现了一批比“原有 4 个量 + AH”更值得追的特征。
- 这些新特征不是都应该直接进模型；更合理的是先把它们分成：`增强 weak positive`、`压制 breathing false positive`、`识别 heat-off confound` 三类用途。
- 因此下一步不是盲目堆更多特征，而是把这些特征按用途接进现有 `watch / review / static support` 框架。

## 排除实验设计投影后的高价值特征

- amp_in_hum_p90_p10 | group=amplitude_dispersion | auc=1.000 | direction=pos | sealed_median=1.462 | unsealed_median=5.072
- corr_headroom_in_hum | group=coupling_lag | auc=1.000 | direction=neg | sealed_median=-0.191 | unsealed_median=-0.916
- delta_half_dAH | group=legacy_static | auc=1.000 | direction=pos | sealed_median=-0.190 | unsealed_median=0.222
- delta_half_in_h | group=legacy_static | auc=1.000 | direction=pos | sealed_median=-0.315 | unsealed_median=3.160
- end_start_dAH | group=legacy_static | auc=1.000 | direction=pos | sealed_median=-2.232 | unsealed_median=0.448
- late_minus_early_rh_gain | group=response_persistence | auc=1.000 | direction=pos | sealed_median=-0.105 | unsealed_median=2.917
- late_rh_gain_per_out | group=response_persistence | auc=1.000 | direction=pos | sealed_median=0.209 | unsealed_median=4.556
- max_corr_outRH_inRH_change | group=coupling_lag | auc=1.000 | direction=pos | sealed_median=-0.052 | unsealed_median=0.756
- slope_dAH_per_h | group=legacy_static | auc=1.000 | direction=pos | sealed_median=-0.024 | unsealed_median=0.009
- slope_in_h_per_h | group=legacy_static | auc=1.000 | direction=pos | sealed_median=-0.059 | unsealed_median=0.089

## 明确超出原有静态 4 特征 + AH 的候选特征

- amp_in_hum_p90_p10 | group=amplitude_dispersion | auc=1.000 | direction=pos | sealed_median=1.462 | unsealed_median=5.072
- corr_headroom_in_hum | group=coupling_lag | auc=1.000 | direction=neg | sealed_median=-0.191 | unsealed_median=-0.916
- late_minus_early_rh_gain | group=response_persistence | auc=1.000 | direction=pos | sealed_median=-0.105 | unsealed_median=2.917
- late_rh_gain_per_out | group=response_persistence | auc=1.000 | direction=pos | sealed_median=0.209 | unsealed_median=4.556
- max_corr_outRH_inRH_change | group=coupling_lag | auc=1.000 | direction=pos | sealed_median=-0.052 | unsealed_median=0.756
- std_in_hum_run | group=amplitude_dispersion | auc=1.000 | direction=pos | sealed_median=0.555 | unsealed_median=1.860
- best_lag_h | group=coupling_lag | auc=0.833 | direction=pos | sealed_median=0.500 | unsealed_median=1.000
- best_lag_level_ah | group=coupling_lag | auc=0.833 | direction=pos | sealed_median=0.500 | unsealed_median=1.000
- best_lag_level_hum | group=coupling_lag | auc=0.833 | direction=neg | sealed_median=3.500 | unsealed_median=0.000
- early_rh_gain_per_out | group=response_persistence | auc=0.833 | direction=pos | sealed_median=0.314 | unsealed_median=1.639

## 三个关键难段怎么看

- `weak_positive`：重点看是否有较高的耦合/滞后相关，但累计响应和后段放大不够。
- `breathing_watch`：重点看是否在很多累计特征上像正样本，但后段放大和 headroom 响应结构不够像真正不密封。
- `heatoff_confound`：重点看相关性存在，但 `AH` 累计方向和净漂移与主战场正样本不一致。

### 120165524_20260303-181049_unsealed_extHigh_intLow_noHeat_noChange_na::full

- role: `weak_positive`
- amp_in_hum_p90_p10 | value=1.008 | direction=pos | seal_med=1.462 | unseal_med=5.072 | toward_positive=False
- corr_headroom_in_hum | value=0.882 | direction=neg | seal_med=-0.191 | unseal_med=-0.916 | toward_positive=False
- delta_half_dAH | value=-0.340 | direction=pos | seal_med=-0.190 | unseal_med=0.222 | toward_positive=False
- delta_half_in_h | value=0.616 | direction=pos | seal_med=-0.315 | unseal_med=3.160 | toward_positive=False
- duration_h | value=15.207 | direction=pos | seal_med=29.050 | unseal_med=53.386 | toward_positive=False
- end_start_dAH | value=-3.895 | direction=pos | seal_med=-2.232 | unseal_med=0.448 | toward_positive=False
- late_minus_early_rh_gain | value=0.219 | direction=pos | seal_med=-0.105 | unseal_med=2.917 | toward_positive=False
- late_rh_gain_per_out | value=0.400 | direction=pos | seal_med=0.209 | unseal_med=4.556 | toward_positive=False
- max_corr_outRH_inRH_change | value=0.986 | direction=pos | seal_med=-0.052 | unseal_med=0.756 | toward_positive=True
- slope_dAH_per_h | value=-0.063 | direction=pos | seal_med=-0.024 | unseal_med=0.009 | toward_positive=False
- slope_in_h_per_h | value=0.091 | direction=pos | seal_med=-0.059 | unseal_med=0.089 | toward_positive=True
- std_in_hum_run | value=0.469 | direction=pos | seal_med=0.555 | unseal_med=1.860 | toward_positive=False

### 120165524_20260306-160246_sealed_extHigh_intLow_noHeat_noChange_na::full

- role: `breathing_watch`
- amp_in_hum_p90_p10 | value=3.882 | direction=pos | seal_med=1.462 | unseal_med=5.072 | toward_positive=False
- corr_headroom_in_hum | value=-0.696 | direction=neg | seal_med=-0.191 | unseal_med=-0.916 | toward_positive=False
- delta_half_dAH | value=0.329 | direction=pos | seal_med=-0.190 | unseal_med=0.222 | toward_positive=True
- delta_half_in_h | value=2.265 | direction=pos | seal_med=-0.315 | unseal_med=3.160 | toward_positive=False
- duration_h | value=42.303 | direction=pos | seal_med=29.050 | unseal_med=53.386 | toward_positive=False
- end_start_dAH | value=-2.474 | direction=pos | seal_med=-2.232 | unseal_med=0.448 | toward_positive=False
- late_minus_early_rh_gain | value=0.361 | direction=pos | seal_med=-0.105 | unseal_med=2.917 | toward_positive=False
- late_rh_gain_per_out | value=0.499 | direction=pos | seal_med=0.209 | unseal_med=4.556 | toward_positive=False
- max_corr_outRH_inRH_change | value=0.865 | direction=pos | seal_med=-0.052 | unseal_med=0.756 | toward_positive=True
- slope_dAH_per_h | value=0.017 | direction=pos | seal_med=-0.024 | unseal_med=0.009 | toward_positive=True
- slope_in_h_per_h | value=0.112 | direction=pos | seal_med=-0.059 | unseal_med=0.089 | toward_positive=True
- std_in_hum_run | value=1.470 | direction=pos | seal_med=0.555 | unseal_med=1.860 | toward_positive=False

### 120165524_20260321-170450_unseal_extHigh_intLow_Heat_Change_20260321-1800_noHeat::post_change

- role: `heatoff_confound`
- amp_in_hum_p90_p10 | value=2.140 | direction=pos | seal_med=1.462 | unseal_med=5.072 | toward_positive=False
- corr_headroom_in_hum | value=0.828 | direction=neg | seal_med=-0.191 | unseal_med=-0.916 | toward_positive=False
- delta_half_dAH | value=-0.638 | direction=pos | seal_med=-0.190 | unseal_med=0.222 | toward_positive=False
- delta_half_in_h | value=1.422 | direction=pos | seal_med=-0.315 | unseal_med=3.160 | toward_positive=False
- duration_h | value=47.599 | direction=pos | seal_med=29.050 | unseal_med=53.386 | toward_positive=False
- end_start_dAH | value=-8.321 | direction=pos | seal_med=-2.232 | unseal_med=0.448 | toward_positive=False
- late_minus_early_rh_gain | value=0.000 | direction=pos | seal_med=-0.105 | unseal_med=2.917 | toward_positive=False
- late_rh_gain_per_out | value=1.304 | direction=pos | seal_med=0.209 | unseal_med=4.556 | toward_positive=False
- max_corr_outRH_inRH_change | value=0.732 | direction=pos | seal_med=-0.052 | unseal_med=0.756 | toward_positive=False
- slope_dAH_per_h | value=-0.032 | direction=pos | seal_med=-0.024 | unseal_med=0.009 | toward_positive=False
- slope_in_h_per_h | value=0.065 | direction=pos | seal_med=-0.059 | unseal_med=0.089 | toward_positive=False
- std_in_hum_run | value=0.989 | direction=pos | seal_med=0.555 | unseal_med=1.860 | toward_positive=False

## 结论

1. 真正值得继续追的新增特征主要分三类：
   - `耦合/滞后`：`max_corr_outRH_inRH_change`、`corr_out_hum_in_hum`、`max_corr_level_hum/ah`、`best_lag_level_hum/ah`
   - `响应持续性`：`late_rh_gain_per_out`、`late_minus_early_rh_gain`、`positive_ah_response_ratio`、`headroom_gain_ratio`
   - `波动/幅度`：`amp_in_hum_p90_p10`、`std_in_hum_run`、`amp_headroom_p90_p10`
2. `duration_h` 虽然在当前参考池里分离度很高，但更像实验设计投影，不建议直接当主特征。
3. `weak_positive` 更像“相关性对了，但累计响应和后段放大不够”；`breathing_watch` 更像“累计量像正样本，但持续性结构不像真正不密封”。
4. 下一步最合理的做法不是直接把这些特征全堆进 XGBoost，而是先把它们接成：
   - `weak positive support`
   - `breathing suppression`
   - `confound reject`
   三个子评分，再看是否真正改善当前主线程。
