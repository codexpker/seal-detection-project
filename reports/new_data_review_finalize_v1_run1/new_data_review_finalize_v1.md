# New Data Review Finalize v1

- 目的：在人工编辑 `segment_review_labels_working_v2.csv` 后，自动重跑回灌、刷新 pending 排序，并同步生成最新调优建议。

## 当前复核填充状态

- total_rows：`10`
- filled_rows：`5`
- confirmed_rows：`5`
- uncertain_rows：`0`
- blank_or_invalid_rows：`5`
- manual_rows：`0`
- auto_seed_rows：`5`
- label_counts：`{'transition_positive': 3, 'breathing_watch': 1, 'confound': 1}`

## 回灌结果

- reviewed_rows：`5`
- positive_reference_segments：`0`
- negative_reference_segments：`0`
- transition_positive_segments：`3`
- breathing_watch_segments：`1`
- confound_segments：`1`
- pending_segments：`5`

## 当前动作建议

- pending | 120165524_20260303-181049_unsealed_extHigh_intLow_noHeat_noChange_na::full | status=static_review_weak_positive_guarded | memory=hard_negative
- pending | 120165519_20260309-102255_sealed_extLow_intHigh_noHeat_Change_20260310-1000_unsealed::post_change | status=transition_secondary_control | memory=None
- pending | 120165519_20260313-111811_sealed_extLow_intHigh_Heat_Change_20260315-1500_unsealed::post_change | status=transition_secondary_control | memory=None
- pending | 120165520_20260310-170038_sealed_extEq_intEq_Heat_Change_20260313-1002_unsealed::post_change | status=transition_secondary_control | memory=None
- pending | 120165520_20260318-090358_sealed_extEq_intEq_Heat_Change_20260319-1520_unsealed::post_change | status=transition_secondary_control | memory=None

- 当前 tuning 口径仍是：`3` 条 transition 主段优先，guarded positive 仅人工确认后升级。

## 关键输出

- working_labels_csv：`reports/new_data_review_workflow_v1_run1/segment_review_labels_working_v2.csv`
- feedback_report_md：`reports/new_data_review_finalize_v1_run1/feedback_v2/segment_feedback_report_v2.md`
- pending_csv：`reports/new_data_review_finalize_v1_run1/feedback_v2/pending_segment_review_reranked_v2.csv`
- tuning_report_md：`reports/new_data_review_finalize_v1_run1/tuning_plan_v1/new_data_model_tuning_plan_v1.md`
- finalize_report_json：`reports/new_data_review_finalize_v1_run1/new_data_review_finalize_v1.json`
