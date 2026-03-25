# Transition Event Summary v1

- 结论：`PASS`
- transition_files：`2`
- detected_events：`2`
- event_detect_rate：`1.0`
- near_overlap_rate：`1.0`
- peak_in_near_rate：`1.0`
- median_duration_h：`32.0`

## 验收判断

- all_transition_runs_have_event = `True`
- all_events_overlap_near_transition = `True`
- all_peaks_in_near_transition = `True`

## 事件卡片

- 2026-03-04 120007_seal_unheated-2026-03-04 163909_unseal_unheated | status=transition_boost_alert | event=2026-03-04 12:00:00 -> 2026-03-05 08:00:00 | peak=2026-03-04 12:00:00 | peak_phase=near_transition | peak_smooth=4.612 | upper=1.956 | lower=0.782 | lead_h=0.0 | tail_h=4.0
- 2026-03-08 172014_seal_unheated | status=transition_boost_alert | event=2026-03-09 23:00:00 -> 2026-03-11 19:00:00 | peak=2026-03-10 08:00:00 | peak_phase=near_transition | peak_smooth=2.687 | upper=0.912 | lower=0.365 | lead_h=-1.0 | tail_h=21.0

## 当前判断

- 这一层不引入新模型，只把 transition 分数压成更适合演示和复核的事件结构。
- 当前两个 transition 样例都能提取出单一主事件，且事件都覆盖 near_transition 邻域。
- 因此下一步可以把 `start / end / peak / duration` 直接接进 demo 卡片，而不用现场手工读窗口分数。
