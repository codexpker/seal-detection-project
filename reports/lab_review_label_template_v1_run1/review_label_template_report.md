# Review Label Template v1

- 目的：把当前 `review_output` 直接压成可填写的真实复核标签模板，字段与 `lab_health_bank_feedback_loop_v1.py` 完全兼容。

- row_count：`6`
- include_reviewed：`False`
- review_priority_counts：`{'P1_static_alert': 3, 'P0_transition': 2, 'P2_hard_case_watch': 1}`

## 输出文件

- template_csv: `reports/lab_review_label_template_v1_run1/review_labels_template.csv`

## 填写要求

- 真正会被回灌脚本读取的只有四列：`run_id, review_label, reviewer, review_note`。
- 其他列都是辅助上下文，保留即可，不影响脚本读取。
- 推荐直接使用标准标签：`healthy`、`anomaly`、`uncertain`。
