# Segment Review Label Template v2

- 目的：把 `segment_review_queue_v3` 压成可填写的段级真实复核模板，供 `segment feedback loop v2` 回灌使用。

- row_count：`10`
- review_priority_counts：`{7: 4, 0: 3, 2: 1, 3: 1, 5: 1}`
- support_status_counts：`{'transition_secondary_control': 4, 'transition_primary_support': 3, 'static_review_weak_positive_guarded': 1, 'static_watch_breathing_hardguard': 1, 'static_watch_confound_hardguard': 1}`

## 输出文件

- template_csv: `reports/new_data_segment_review_label_template_v2_run1/segment_review_labels_template_v2.csv`

## 填写要求

- 回灌脚本实际读取：`segment_id, review_label, reviewer, review_note`。
- 推荐标签：`positive_reference`、`negative_reference`、`transition_positive`、`breathing_watch`、`confound`、`uncertain`。
- `transition_primary_support` 优先标 `transition_positive`。
- `static_review_weak_positive_guarded` 当前默认不建议自动升为正参考；若无充分把握，优先标 `uncertain`。
- `static_watch_breathing_hardguard` 优先标 `breathing_watch`。
- `static_watch_confound_hardguard` 优先标 `confound`。
