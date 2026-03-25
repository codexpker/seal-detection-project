# 新工况数据多视角深入分析报告

- 总运行数：`15`
- 分组分布：`{'current_heat_related': 5, 'current_static_seal': 3, 'current_static_unseal': 3, 'current_other': 2, 'current_transition': 2}`
- 静态候选运行数：`6`
- 静态候选类别分布：`{'seal': 3, 'unseal': 3}`

## 为什么不能只画图和看 5 个信息

- 当前数据里，相对湿度本身强烈混入了温度效应；只看 `Tin/Tout/Hin/Hout/AH` 的原始曲线，容易把温度驱动和水汽传递混在一起。
- 有些真正有价值的线索并不在“绝对水平”，而在 `高分位窗口特征`、`动态响应相关性`、`路由后的持续性` 上。
- 因此这一步不再只看曲线形态，而是同时看：静态运行级、动态响应、窗口分位数、路由持久性、转移邻域抬升。

## 温度-湿度耦合中位数

| seal_label   |   corr_in_temp_in_hum |   corr_in_temp_AH_in |   corr_out_hum_in_hum |   corr_out_AH_in_AH |
|:-------------|----------------------:|---------------------:|----------------------:|--------------------:|
| seal         |              0.513118 |             0.991655 |              0.73826  |            0.837007 |
| unseal       |             -0.951725 |             0.942909 |              0.989594 |            0.905793 |

## Static Seal vs Unseal：值得继续追的潜在线索

- corr_out_hum_in_hum | auc=1.000 | direction=pos | seal_median=0.738 | unseal_median=0.990
- max_corr_outRH_inRH_change | auc=0.889 | direction=pos | seal_median=-0.680 | unseal_median=0.907
- std_in_hum_run | auc=0.889 | direction=neg | seal_median=1.041 | unseal_median=0.469
- frac_threshold_favored | auc=0.722 | direction=pos | seal_median=0.222 | unseal_median=0.774
- frac_pos_delta_half_dAH | auc=0.722 | direction=pos | seal_median=0.222 | unseal_median=0.774
- max_corr_dAH_change | auc=0.667 | direction=pos | seal_median=0.725 | unseal_median=0.961
- q90_delta_half_in_hum | auc=0.667 | direction=neg | seal_median=1.319 | unseal_median=0.524
- q90_delta_half_dAH_w | auc=0.667 | direction=pos | seal_median=0.002 | unseal_median=0.094

## 需要谨慎看待的“伪区分”特征

- mean_out_h | auc=0.778 | direction=pos
- candidate_high_info_ratio | auc=0.667 | direction=neg
- heat_related_ratio | auc=0.667 | direction=pos
- 这类特征更像实验条件差异或当前路由结果的投影，不能直接当成可迁移主特征。

## 当前最关键的混淆样本

- 2026-03-06 160246_seal_unheated | label=seal | nearest_other=2026-03-04 163909_unseal_unheated | nearest_other_distance=2.031 | cross_label_closer=True

## Transition 邻域更强的特征

- delta_in_hum | near_mean=1.600 | non_near_mean=0.847 | diff=0.753
- delta_half_in_hum | near_mean=0.793 | non_near_mean=0.422 | diff=0.372
- max_hourly_hum_rise | near_mean=0.404 | non_near_mean=0.084 | diff=0.320
- std_out_hum | near_mean=0.397 | non_near_mean=0.145 | diff=0.252
- corr_AH | near_mean=0.822 | non_near_mean=0.744 | diff=0.078
- slope_AH_in | near_mean=0.009 | non_near_mean=0.006 | diff=0.003

## 结论

- 当前新工况数据确实不止 5 个信息可看，真正值得继续追的方向至少有四类：`动态响应相关性`、`窗口高分位漂移特征`、`阈值 favored 持续性`、`转移邻域湿度抬升速度`。
- 当前最值得继续做静态分支探索的不是 `mean_out_h` 这类容易受实验条件影响的量，而是：`corr_out_hum_in_hum`、`max_corr_outRH_inRH_change`、`q90_delta_half_dAH_w`、`frac_threshold_favored`、`frac_pos_delta_half_dAH`。
- Transition 场景里，这批数据提示 `max_hourly_hum_rise` 和 `delta_in_hum` 可能比单纯 `delta_half_dAH` 更值得重视。
- 当前仍存在明显难例，尤其是 `2026-03-06 160246_seal_unheated`，说明全局统一静态分类器仍然风险很高。
- 因此下一步最合理的做法不是直接堆更复杂模型，而是把这些多视角特征接进现有 `watch / abstain / review` 框架里，先验证哪些能稳定改善难例处理。
