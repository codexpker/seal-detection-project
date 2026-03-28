# seal_v4 在线模型改前改后对照报告

- run_count: `20`
- status_changed_count: `3`
- anomaly_changed_count: `3`
- ext_high_hum_no_heat_count: `7`
- ext_high_status_changed_count: `3`
- before_status_counts: `{'low_info_background': 6, 'heat_related_background': 7, 'static_abstain_low_signal': 1, 'static_dynamic_supported_alert': 4, 'static_hard_case_watch': 2}`
- after_status_counts: `{'low_info_background': 6, 'heat_related_background': 7, 'static_abstain_low_signal': 1, 'static_hard_case_watch': 5, 'static_dynamic_supported_alert': 1}`

## 当前结论

- 这次改动不是重训 whole-run 模型，而是把已验证有效的 `dew / lag / coupling / persistence` 结构特征接进当前在线 `seal_v4`。
- 主要目标是：减少 `ext_high_hum_no_heat` 主战场里 guarded positive 的误抬，并把 `breathing / confound` 更稳定地压回 `watch`。

## 状态发生变化的文件

- 120165524_20260303-181049_unsealed_extHigh_intLow_noHeat_noChange_na.xlsx | static_dynamic_supported_alert -> static_hard_case_watch | before_score=0.7992 | after_score=0.4967 | support=0.7024705111346778 | breathing_guard=0.5 | confound_guard=0.25
- 120165524_20260304-120007_sealed_extHigh_intLow_noHeat_Change_20260304-1639_unsealed.xlsx | static_dynamic_supported_alert -> static_hard_case_watch | before_score=0.8279 | after_score=0.5350 | support=0.68 | breathing_guard=0.75 | confound_guard=0.5
- 120165524_20260323-213435_seal_extHigh_intLow_noHeat_Change_20260324-9000_unseal.xlsx | static_dynamic_supported_alert -> static_hard_case_watch | before_score=0.8596 | after_score=0.5470 | support=0.5835959115962548 | breathing_guard=0.25 | confound_guard=0.5

## 全量结果

- 120165518_20260308-104441_sealed_extEq_intEq_noHeat_noChange_na.xlsx | branch=low_info | low_info_background -> low_info_background | anomaly=False->False | score=0.0800->0.0800
- 120165519_20260309-102255_sealed_extLow_intHigh_noHeat_Change_20260310-1000_unsealed.xlsx | branch=low_info | low_info_background -> low_info_background | anomaly=False->False | score=0.0800->0.0800
- 120165519_20260313-111811_sealed_extLow_intHigh_Heat_Change_20260315-1500_unsealed.xlsx | branch=low_info | low_info_background -> low_info_background | anomaly=False->False | score=0.0800->0.0800
- 120165520_20260310-170038_sealed_extEq_intEq_Heat_Change_20260313-1002_unsealed.xlsx | branch=low_info | low_info_background -> low_info_background | anomaly=False->False | score=0.0800->0.0800
- 120165520_20260315-140001_unsealed_extEq_intEq_noHeat_noChange_na.xlsx | branch=low_info | low_info_background -> low_info_background | anomaly=False->False | score=0.0800->0.0800
- 120165520_20260318-000055_sealed_extEq_intEq_noHeat_Change_20260318-0903_Heat.xlsx | branch=heat_related | heat_related_background -> heat_related_background | anomaly=False->False | score=0.1200->0.1200
- 120165520_20260318-090358_sealed_extEq_intEq_Heat_Change_20260319-1520_unsealed.xlsx | branch=heat_related | heat_related_background -> heat_related_background | anomaly=False->False | score=0.1200->0.1200
- 120165520_20260323-120048_unseal_extEq_intLow_Heat_Change_20260323-1545_extHigh.xlsx | branch=heat_related | heat_related_background -> heat_related_background | anomaly=False->False | score=0.1200->0.1200
- 120165520_20260324_080048_sealed_extEq_intEq_Heat_Change_20260324-2207_noHeat.xlsx | branch=low_info | low_info_background -> low_info_background | anomaly=False->False | score=0.0800->0.0800
- 120165524_20260302 161335_sealed_extHigh_intLow_noHeat_noChange_na.xlsx | branch=ext_high_hum_no_heat | static_abstain_low_signal -> static_abstain_low_signal | anomaly=False->False | score=0.2512->0.2512
- 120165524_20260303-101220_sealed_extHigh_intLow_Heat_noChange_na.xlsx | branch=heat_related | heat_related_background -> heat_related_background | anomaly=False->False | score=0.1200->0.1200
- 120165524_20260303-181049_unsealed_extHigh_intLow_noHeat_noChange_na.xlsx | branch=ext_high_hum_no_heat | static_dynamic_supported_alert -> static_hard_case_watch | anomaly=True->False | score=0.7992->0.4967
- 120165524_20260304-120007_sealed_extHigh_intLow_noHeat_Change_20260304-1639_unsealed.xlsx | branch=ext_high_hum_no_heat | static_dynamic_supported_alert -> static_hard_case_watch | anomaly=True->False | score=0.8279->0.5350
- 120165524_20260306-160246_sealed_extHigh_intLow_noHeat_noChange_na.xlsx | branch=ext_high_hum_no_heat | static_hard_case_watch -> static_hard_case_watch | anomaly=False->False | score=0.5292->0.5350
- 120165524_20260308-172014_sealed_extHigh_intLow_noHeat_Change_20260310-1000_unsealed.xlsx | branch=ext_high_hum_no_heat | static_dynamic_supported_alert -> static_dynamic_supported_alert | anomaly=True->True | score=0.8401->0.8456
- 120165524_20260313-080032_unsealed_extHigh_intLow_noHeat_Change_20260313-1001_Heat.xlsx | branch=heat_related | heat_related_background -> heat_related_background | anomaly=False->False | score=0.1200->0.1200
- 120165524_20260314-174006_unsealed_extHigh_intLow_Heat_noChange_na.xlsx | branch=heat_related | heat_related_background -> heat_related_background | anomaly=False->False | score=0.1200->0.1200
- 120165524_20260317-180258_seal_heated_extHigh_intLow_noHeat_Change_20260317-1830_Heat.xlsx | branch=heat_related | heat_related_background -> heat_related_background | anomaly=False->False | score=0.1200->0.1200
- 120165524_20260321-170450_unseal_extHigh_intLow_Heat_Change_20260321-1800_noHeat.xlsx | branch=ext_high_hum_no_heat | static_hard_case_watch -> static_hard_case_watch | anomaly=False->False | score=0.5714->0.5363
- 120165524_20260323-213435_seal_extHigh_intLow_noHeat_Change_20260324-9000_unseal.xlsx | branch=ext_high_hum_no_heat | static_dynamic_supported_alert -> static_hard_case_watch | anomaly=True->False | score=0.8596->0.5470