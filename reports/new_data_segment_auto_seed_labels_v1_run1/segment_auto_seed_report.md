# New Data Segment Auto Seed Labels v1

- 目的：按当前离线分析结果，只对高置信段自动落第一批复核标签，其余继续保持 `pending`。

- row_count：`10`
- auto_labeled_rows：`6`
- label_counts：`{'transition_positive': 3, 'positive_reference': 1, 'breathing_watch': 1, 'confound': 1}`
- pending_rows：`4`

## 自动落标签原则

- `transition_primary_support` 的 `post_change` 段 -> `transition_positive`
- `static_supported_weak_positive` 且支持分达到最高置信 -> `positive_reference`
- `static_watch_breathing_confirmed` -> `breathing_watch`
- `static_watch_confound_confirmed` -> `confound`
- 其余段保留空白，继续人工复核

## 输出文件

- auto_seed_csv: `reports/new_data_segment_auto_seed_labels_v1_run1/segment_review_labels_auto_seed.csv`
