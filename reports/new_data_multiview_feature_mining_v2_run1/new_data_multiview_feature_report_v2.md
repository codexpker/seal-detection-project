# 新补充数据 扩样本多视角特征挖掘报告 v2

- mainfield_segment_count: `8`
- reference_count: `5`
- reference_class_counts: `{'unsealed': 3, 'sealed': 2}`
- challenge_role_counts: `{'positive_reference': 3, 'negative_reference': 2, 'breathing_watch': 1, 'heatoff_confound': 1, 'weak_positive': 1}`

## 当前判断

- 这轮专门补了 `露点温度` 和更稳的 `进湿/泄漏代理` 特征，目标不是堆模型，而是看它们能不能解释 `weak_positive / breathing_watch / heat-off confound`。
- 原始的 `露点增益比` 这类分母很小会发散的特征没有保留；这里只保留了 `露点差面积`、`露点耦合`、`正驱动下的响应斜率`、`单位驱动面积的正向增益` 这类更稳的量。
- 由于当前干净参考段仍只有 `5` 个，下面所有排名都只能理解为“特征优先级线索”，不能理解为已经证明通用有效。
- `ingress_count` 这类有效驱动点个数本质上仍然带有时长/驱动覆盖率投影，所以这次不会把它当主结论。

## 新增 Dew / Ingress 代理里值得继续追的特征

- dew_ingress_r2 | group=ingress_proxy | auc=1.000 | direction=neg | sealed_median=0.686 | unsealed_median=0.430
- early_dew_gain_per_out | group=dew_vapor | auc=1.000 | direction=pos | sealed_median=0.321 | unsealed_median=1.085
- late_minus_early_vpd_gap | group=ingress_proxy | auc=1.000 | direction=pos | sealed_median=-0.062 | unsealed_median=0.055
- vpd_in_mean | group=ingress_proxy | auc=1.000 | direction=neg | sealed_median=0.811 | unsealed_median=0.667
- ah_neg_response_ratio | group=ingress_proxy | auc=0.833 | direction=neg | sealed_median=0.674 | unsealed_median=0.254
- best_lag_level_dew | group=dew_vapor | auc=0.833 | direction=pos | sealed_median=0.500 | unsealed_median=1.000
- dew_headroom_capture_ratio | group=dew_vapor | auc=0.833 | direction=pos | sealed_median=0.326 | unsealed_median=0.732
- dew_neg_response_ratio | group=ingress_proxy | auc=0.833 | direction=neg | sealed_median=0.674 | unsealed_median=0.268
- ah_gap_area_pos | group=ingress_proxy | auc=0.667 | direction=pos | sealed_median=128.330 | unsealed_median=177.088
- ah_gap_q90 | group=ingress_proxy | auc=0.667 | direction=neg | sealed_median=4.533 | unsealed_median=4.386
- ah_ingress_r2 | group=ingress_proxy | auc=0.667 | direction=neg | sealed_median=0.464 | unsealed_median=0.437
- ah_ingress_slope | group=ingress_proxy | auc=0.667 | direction=pos | sealed_median=-0.143 | unsealed_median=0.071

## 对真实难点更有用的特征

- max_corr_level_ah | group=coupling_lag | auc=0.667 | challenge_match=3/3
- max_corr_level_dew | group=dew_vapor | auc=0.667 | challenge_match=3/3
- max_corr_level_hum | group=coupling_lag | auc=0.500 | challenge_match=3/3
- amp_in_hum_p90_p10 | group=amplitude_dispersion | auc=1.000 | challenge_match=2/3
- corr_headroom_in_hum | group=coupling_lag | auc=1.000 | challenge_match=2/3
- delta_half_in_h | group=legacy_static | auc=1.000 | challenge_match=2/3
- end_start_dAH | group=legacy_static | auc=1.000 | challenge_match=2/3
- late_minus_early_rh_gain | group=response_persistence | auc=1.000 | challenge_match=2/3
- late_rh_gain_per_out | group=response_persistence | auc=1.000 | challenge_match=2/3
- max_corr_outRH_inRH_change | group=coupling_lag | auc=1.000 | challenge_match=2/3
- slope_in_h_per_h | group=legacy_static | auc=1.000 | challenge_match=2/3
- std_in_hum_run | group=amplitude_dispersion | auc=1.000 | challenge_match=2/3

## 把 Dew / Ingress 代理和上一轮特征放在一起看

- amp_in_hum_p90_p10 | group=amplitude_dispersion | auc=1.000 | direction=pos | sealed_median=1.462 | unsealed_median=5.072
- corr_headroom_in_hum | group=coupling_lag | auc=1.000 | direction=neg | sealed_median=-0.191 | unsealed_median=-0.916
- dew_ingress_r2 | group=ingress_proxy | auc=1.000 | direction=neg | sealed_median=0.686 | unsealed_median=0.430
- early_dew_gain_per_out | group=dew_vapor | auc=1.000 | direction=pos | sealed_median=0.321 | unsealed_median=1.085
- late_minus_early_rh_gain | group=response_persistence | auc=1.000 | direction=pos | sealed_median=-0.105 | unsealed_median=2.917
- late_minus_early_vpd_gap | group=ingress_proxy | auc=1.000 | direction=pos | sealed_median=-0.062 | unsealed_median=0.055
- late_rh_gain_per_out | group=response_persistence | auc=1.000 | direction=pos | sealed_median=0.209 | unsealed_median=4.556
- max_corr_outRH_inRH_change | group=coupling_lag | auc=1.000 | direction=pos | sealed_median=-0.052 | unsealed_median=0.756
- std_in_hum_run | group=amplitude_dispersion | auc=1.000 | direction=pos | sealed_median=0.555 | unsealed_median=1.860
- vpd_in_mean | group=ingress_proxy | auc=1.000 | direction=neg | sealed_median=0.811 | unsealed_median=0.667
- ah_neg_response_ratio | group=ingress_proxy | auc=0.833 | direction=neg | sealed_median=0.674 | unsealed_median=0.254
- best_lag_h | group=coupling_lag | auc=0.833 | direction=pos | sealed_median=0.500 | unsealed_median=1.000

## 三个关键难段怎么看

- `weak_positive`：如果露点/耦合相关站得住，但累计面积和 ingress 斜率不够，说明它更像“跟随存在，但积湿不够持续”。
- `breathing_watch`：如果漂移和部分相关性像正样本，但晚段 dew / ingress 持续性仍弱，说明更像材料呼吸而不是稳定进湿。
- `heatoff_confound`：如果热源切换后露点或 RH 有回升，但 `AH/dew 正驱动面积` 和 `ingress slope` 站不住，就不能被提升成主战场正样本。

### 120165524_20260303-181049_unsealed_extHigh_intLow_noHeat_noChange_na::full

- role: `weak_positive`
- ah_ingress_count | group=ingress_proxy | value=15.000 | direction=pos | seal_med=28.500 | unseal_med=53.000 | toward_positive=False
- corr_headroom_in_hum | group=coupling_lag | value=0.882 | direction=neg | seal_med=-0.191 | unseal_med=-0.916 | toward_positive=False
- dew_ingress_count | group=ingress_proxy | value=15.000 | direction=pos | seal_med=28.500 | unseal_med=53.000 | toward_positive=False
- dew_ingress_r2 | group=ingress_proxy | value=0.997 | direction=neg | seal_med=0.686 | unseal_med=0.430 | toward_positive=False
- early_dew_gain_per_out | group=dew_vapor | value=nan | direction=pos | seal_med=0.321 | unseal_med=1.085 | toward_positive=False
- late_minus_early_rh_gain | group=response_persistence | value=0.219 | direction=pos | seal_med=-0.105 | unseal_med=2.917 | toward_positive=False
- late_minus_early_vpd_gap | group=ingress_proxy | value=0.061 | direction=pos | seal_med=-0.062 | unseal_med=0.055 | toward_positive=True
- late_rh_gain_per_out | group=response_persistence | value=0.400 | direction=pos | seal_med=0.209 | unseal_med=4.556 | toward_positive=False
- max_corr_outRH_inRH_change | group=coupling_lag | value=0.986 | direction=pos | seal_med=-0.052 | unseal_med=0.756 | toward_positive=True
- vpd_in_mean | group=ingress_proxy | value=0.797 | direction=neg | seal_med=0.811 | unseal_med=0.667 | toward_positive=False
- ah_neg_response_ratio | group=ingress_proxy | value=1.000 | direction=neg | seal_med=0.674 | unseal_med=0.254 | toward_positive=False
- best_lag_h | group=coupling_lag | value=5.000 | direction=pos | seal_med=0.500 | unseal_med=1.000 | toward_positive=True
- best_lag_level_ah | group=coupling_lag | value=3.000 | direction=pos | seal_med=0.500 | unseal_med=1.000 | toward_positive=True
- best_lag_level_dew | group=dew_vapor | value=3.000 | direction=pos | seal_med=0.500 | unseal_med=1.000 | toward_positive=True
- best_lag_level_hum | group=coupling_lag | value=0.000 | direction=neg | seal_med=3.500 | unseal_med=0.000 | toward_positive=True

### 120165524_20260306-160246_sealed_extHigh_intLow_noHeat_noChange_na::full

- role: `breathing_watch`
- ah_ingress_count | group=ingress_proxy | value=42.000 | direction=pos | seal_med=28.500 | unseal_med=53.000 | toward_positive=False
- corr_headroom_in_hum | group=coupling_lag | value=-0.696 | direction=neg | seal_med=-0.191 | unseal_med=-0.916 | toward_positive=False
- dew_ingress_count | group=ingress_proxy | value=42.000 | direction=pos | seal_med=28.500 | unseal_med=53.000 | toward_positive=False
- dew_ingress_r2 | group=ingress_proxy | value=0.035 | direction=neg | seal_med=0.686 | unseal_med=0.430 | toward_positive=True
- early_dew_gain_per_out | group=dew_vapor | value=-0.281 | direction=pos | seal_med=0.321 | unseal_med=1.085 | toward_positive=False
- late_minus_early_rh_gain | group=response_persistence | value=0.361 | direction=pos | seal_med=-0.105 | unseal_med=2.917 | toward_positive=False
- late_minus_early_vpd_gap | group=ingress_proxy | value=0.099 | direction=pos | seal_med=-0.062 | unseal_med=0.055 | toward_positive=True
- late_rh_gain_per_out | group=response_persistence | value=0.499 | direction=pos | seal_med=0.209 | unseal_med=4.556 | toward_positive=False
- max_corr_outRH_inRH_change | group=coupling_lag | value=0.865 | direction=pos | seal_med=-0.052 | unseal_med=0.756 | toward_positive=True
- vpd_in_mean | group=ingress_proxy | value=0.870 | direction=neg | seal_med=0.811 | unseal_med=0.667 | toward_positive=False
- ah_neg_response_ratio | group=ingress_proxy | value=0.905 | direction=neg | seal_med=0.674 | unseal_med=0.254 | toward_positive=False
- best_lag_h | group=coupling_lag | value=1.000 | direction=pos | seal_med=0.500 | unseal_med=1.000 | toward_positive=True
- best_lag_level_ah | group=coupling_lag | value=0.000 | direction=pos | seal_med=0.500 | unseal_med=1.000 | toward_positive=False
- best_lag_level_dew | group=dew_vapor | value=0.000 | direction=pos | seal_med=0.500 | unseal_med=1.000 | toward_positive=False
- best_lag_level_hum | group=coupling_lag | value=0.000 | direction=neg | seal_med=3.500 | unseal_med=0.000 | toward_positive=True

### 120165524_20260321-170450_unseal_extHigh_intLow_Heat_Change_20260321-1800_noHeat::post_change

- role: `heatoff_confound`
- ah_ingress_count | group=ingress_proxy | value=46.000 | direction=pos | seal_med=28.500 | unseal_med=53.000 | toward_positive=False
- corr_headroom_in_hum | group=coupling_lag | value=0.828 | direction=neg | seal_med=-0.191 | unseal_med=-0.916 | toward_positive=False
- dew_ingress_count | group=ingress_proxy | value=46.000 | direction=pos | seal_med=28.500 | unseal_med=53.000 | toward_positive=False
- dew_ingress_r2 | group=ingress_proxy | value=0.997 | direction=neg | seal_med=0.686 | unseal_med=0.430 | toward_positive=False
- early_dew_gain_per_out | group=dew_vapor | value=2.372 | direction=pos | seal_med=0.321 | unseal_med=1.085 | toward_positive=True
- late_minus_early_rh_gain | group=response_persistence | value=0.000 | direction=pos | seal_med=-0.105 | unseal_med=2.917 | toward_positive=False
- late_minus_early_vpd_gap | group=ingress_proxy | value=0.471 | direction=pos | seal_med=-0.062 | unseal_med=0.055 | toward_positive=True
- late_rh_gain_per_out | group=response_persistence | value=1.304 | direction=pos | seal_med=0.209 | unseal_med=4.556 | toward_positive=False
- max_corr_outRH_inRH_change | group=coupling_lag | value=0.732 | direction=pos | seal_med=-0.052 | unseal_med=0.756 | toward_positive=False
- vpd_in_mean | group=ingress_proxy | value=0.776 | direction=neg | seal_med=0.811 | unseal_med=0.667 | toward_positive=False
- ah_neg_response_ratio | group=ingress_proxy | value=0.652 | direction=neg | seal_med=0.674 | unseal_med=0.254 | toward_positive=False
- best_lag_h | group=coupling_lag | value=4.000 | direction=pos | seal_med=0.500 | unseal_med=1.000 | toward_positive=True
- best_lag_level_ah | group=coupling_lag | value=3.000 | direction=pos | seal_med=0.500 | unseal_med=1.000 | toward_positive=True
- best_lag_level_dew | group=dew_vapor | value=2.000 | direction=pos | seal_med=0.500 | unseal_med=1.000 | toward_positive=True
- best_lag_level_hum | group=coupling_lag | value=1.000 | direction=neg | seal_med=3.500 | unseal_med=0.000 | toward_positive=False

## 结论

1. `露点温度` 这条线是有价值的，但真正有用的不是单独露点值，而是：`dew_gap_area_pos`、`corr_out_dew_in_dew`、`max_corr_dew_change`、`late_minus_early_dew_gain` 这类“外部驱动 -> 内部响应”的结构特征。
2. `泄漏率` 目前更适合定义成 `ingress proxy`，不是物理绝对泄漏率。当前更稳的是：`ah_ingress_slope`、`ah_pos_gain_per_area`、`dew_ingress_slope`、`dew_pos_gain_per_area`。
3. 单纯看参考段 AUC 会高估一部分特征；把 `weak_positive / breathing_watch / heat-off confound` 一起考虑后，`max_corr_level_dew / ah / hum` 这类 level-correlation 特征反而更像真正有助于难段分流的线索。
4. 如果某个特征依赖很小的分母或明显依赖时长才显得很强，它就不该进主线程；所以这次故意剔除了原始高爆炸比值和 `ingress_count` 这类投影量。
5. 下一步最合理的方向不是重开 whole-run 模型，而是把新增特征按用途接成三个子评分：
   - `weak positive support`：提升像 `181049` 这种“耦合对了但累计偏弱”的段
   - `breathing suppression`：压住像 `160246` 这种 sealed breathing 难例
   - `confound reject`：继续压住 `heat-off/ext change` 混淆段
