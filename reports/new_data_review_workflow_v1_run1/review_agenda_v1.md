# New Data Review Workflow v1

- 目的：把 `v3 guarded` 的复核链收成一个可直接执行的工作流，并生成最终人工复核 agenda。

- agenda_rows：`10`
- agenda_group_counts：`{'05_transition_secondary': 4, '01_transition_primary': 3, '02_guarded_positive': 1, '03_breathing_watch': 1, '04_confound_watch': 1}`
- prefilled_seed_rows：`5`
- pending_rows：`5`

## 当前执行顺序

- #1 | 120165524_20260304-120007_sealed_extHigh_intLow_noHeat_Change_20260304-1639_unsealed::post_change | stage=01_transition_primary | status=transition_primary_support | preferred=transition_positive | auto_seed=True | seal=密封 | change=不密封
- #2 | 120165524_20260308-172014_sealed_extHigh_intLow_noHeat_Change_20260310-1000_unsealed::post_change | stage=01_transition_primary | status=transition_primary_support | preferred=transition_positive | auto_seed=True | seal=密封 | change=不密封
- #3 | 120165524_20260323-213435_seal_extHigh_intLow_noHeat_Change_20260324-9000_unseal::post_change | stage=01_transition_primary | status=transition_primary_support | preferred=transition_positive | auto_seed=True | seal=密封 | change=不密封
- #4 | 120165524_20260303-181049_unsealed_extHigh_intLow_noHeat_noChange_na::full | stage=02_guarded_positive | status=static_review_weak_positive_guarded | preferred=uncertain | auto_seed=False | seal=非密封 | change=无
- #5 | 120165524_20260306-160246_sealed_extHigh_intLow_noHeat_noChange_na::full | stage=03_breathing_watch | status=static_watch_breathing_hardguard | preferred=breathing_watch | auto_seed=True | seal=密封 | change=无
- #6 | 120165524_20260321-170450_unseal_extHigh_intLow_Heat_Change_20260321-1800_noHeat::post_change | stage=04_confound_watch | status=static_watch_confound_hardguard | preferred=confound | auto_seed=True | seal=非密封 | change=不加热
- #7 | 120165519_20260309-102255_sealed_extLow_intHigh_noHeat_Change_20260310-1000_unsealed::post_change | stage=05_transition_secondary | status=transition_secondary_control | preferred=uncertain | auto_seed=False | seal=密封 | change=不密封
- #8 | 120165519_20260313-111811_sealed_extLow_intHigh_Heat_Change_20260315-1500_unsealed::post_change | stage=05_transition_secondary | status=transition_secondary_control | preferred=uncertain | auto_seed=False | seal=密封 | change=不密封
- #9 | 120165520_20260310-170038_sealed_extEq_intEq_Heat_Change_20260313-1002_unsealed::post_change | stage=05_transition_secondary | status=transition_secondary_control | preferred=uncertain | auto_seed=False | seal=密封 | change=不密封
- #10 | 120165520_20260318-090358_sealed_extEq_intEq_Heat_Change_20260319-1520_unsealed::post_change | stage=05_transition_secondary | status=transition_secondary_control | preferred=uncertain | auto_seed=False | seal=密封 | change=不密封

## 使用方式

- 直接编辑：`reports/new_data_review_workflow_v1_run1/segment_review_labels_working_v2.csv`
- 只需要填写或确认：`review_label / reviewer / review_note`。
- 已自动种子的高置信段保留预填内容；人工只需要补充其余段或修正个别结论。
