# Segment Review Label Template v1

- 目的：把 `segment_review_queue_v2` 压成可填写的段级真实复核模板，供后续 `segment feedback loop` 回灌使用。

- row_count：`10`
- review_priority_counts：`{7: 4, 0: 3, 1: 1, 3: 1, 5: 1}`
- support_status_counts：`{'transition_secondary_control': 4, 'transition_primary_support': 3, 'static_supported_weak_positive': 1, 'static_watch_breathing_confirmed': 1, 'static_watch_confound_confirmed': 1}`

## 输出文件

- template_csv: `reports/new_data_segment_review_label_template_v1_run1/segment_review_labels_template.csv`

## 填写要求

- 回灌脚本实际读取：`segment_id, review_label, reviewer, review_note`。
- 推荐标签：`positive_reference`、`negative_reference`、`transition_positive`、`breathing_watch`、`confound`、`uncertain`。
- `transition_primary_support` 优先标 `transition_positive`。
- `static_supported_weak_positive` 优先在 `positive_reference` 和 `uncertain` 之间确认。
- `static_watch_breathing_confirmed` 优先标 `breathing_watch`。
- `static_watch_confound_confirmed` 优先标 `confound`。
