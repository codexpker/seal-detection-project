# Segment Memory Bank Similarity v2

- 目的：把相似性支线从“单一健康库排序”升级为“健康参考 + 异常参考 + hard negative”三类记忆。

- selected_features: `['best_lag_level_hum', 'corr_headroom_in_hum', 'corr_out_hum_in_hum', 'late_rh_gain_per_out', 'max_corr_level_hum', 'best_lag_rh_h']`
- health_core_segments: `2`
- anomaly_reference_segments: `4`
- hard_negative_segments: `2`
- current_mainfield_alignment: `0.75`
- tri_memory_auc_anomaly_vs_hardnegative: `0.875`
- health_only_auc_anomaly_vs_hardnegative: `0.0`

## 当前判断

- 新数据对相似性支线的主要帮助，不是单纯扩健康库，而是第一次把 `健康参考 / 异常参考 / hard negative` 三类记忆补齐了。
- 这使相似性支线不再只是判断“离健康有多远”，而可以显式判断“更像异常参考还是更像 hard negative”。
- 当前这里采用的是小样本更稳的 `prototype centroid` 视角，不是直接做最近邻；因为你现在每类记忆库规模仍然很小。

## 当前关键段的三类记忆结果

- 120165524_20260302 161335_sealed_extHigh_intLow_noHeat_noChange_na::full | origin=current_mainfield | expected=health_core | predicted=health_core | d_health=76.680 | d_anomaly=152.872 | d_hard=150.010 | anomaly_adv=-76.192
- 120165524_20260303-181049_unsealed_extHigh_intLow_noHeat_noChange_na::full | origin=current_mainfield | expected=anomaly_reference | predicted=hard_negative | d_health=76.530 | d_anomaly=11.416 | d_hard=5.941 | anomaly_adv=-5.476
- 120165524_20260304-120007_sealed_extHigh_intLow_noHeat_Change_20260304-1639_unsealed::post_change | origin=current_mainfield | expected=anomaly_reference | predicted=anomaly_reference | d_health=76.725 | d_anomaly=3.265 | d_hard=6.795 | anomaly_adv=3.530
- 120165524_20260306-160246_sealed_extHigh_intLow_noHeat_noChange_na::full | origin=current_mainfield | expected=hard_negative | predicted=hard_negative | d_health=73.623 | d_anomaly=5.777 | d_hard=4.944 | anomaly_adv=-0.833
- 120165524_20260308-172014_sealed_extHigh_intLow_noHeat_Change_20260310-1000_unsealed::post_change | origin=current_mainfield | expected=anomaly_reference | predicted=anomaly_reference | d_health=76.957 | d_anomaly=3.744 | d_hard=10.291 | anomaly_adv=6.546
- 120165524_20260308-172014_sealed_extHigh_intLow_noHeat_Change_20260310-1000_unsealed::pre_change | origin=current_mainfield | expected=health_core | predicted=hard_negative | d_health=76.680 | d_anomaly=11.122 | d_hard=5.745 | anomaly_adv=-5.377
- 120165524_20260321-170450_unseal_extHigh_intLow_Heat_Change_20260321-1800_noHeat::post_change | origin=current_mainfield | expected=hard_negative | predicted=hard_negative | d_health=73.517 | d_anomaly=11.708 | d_hard=4.944 | anomaly_adv=-6.763
- 120165524_20260323-213435_seal_extHigh_intLow_noHeat_Change_20260324-9000_unseal::post_change | origin=current_mainfield | expected=anomaly_reference | predicted=anomaly_reference | d_health=74.651 | d_anomaly=8.173 | d_hard=10.717 | anomaly_adv=2.544
- old::2025-10-21 101019 | origin=old_hard_negative | expected=hard_negative | predicted=hard_negative | d_health=54.632 | d_anomaly=25.714 | d_hard=20.759 | anomaly_adv=-4.955
- old::2025-10-28 110628 | origin=old_hard_negative | expected=hard_negative | predicted=health_core | d_health=36.825 | d_anomaly=110.254 | d_hard=106.778 | anomaly_adv=-73.429
- old::2025-11-18 104042 | origin=old_hard_negative | expected=hard_negative | predicted=health_core | d_health=40.572 | d_anomaly=116.010 | d_hard=113.015 | anomaly_adv=-75.439

## 结论

1. 如果三类记忆能把 `breathing/confound` 从 anomaly 侧分开，说明新数据对相似性支线是实质性补强，而不是单纯加样本。
2. 如果 `health_only` 无法区分 anomaly 与 hard negative，而 `tri_memory` 可以，说明后续相似性支线应升级为段级多记忆结构。
3. 这条线后续应作为 `segment memory bank` 继续推进，而不是回到 run-level 单库排序。
