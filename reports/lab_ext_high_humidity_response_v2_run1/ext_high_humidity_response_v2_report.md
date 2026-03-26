# 外部高湿响应分支 v2 报告

- 目的：验证 `2h 短窗增强 + 6h 主判定 + 12h 长窗确认` 是否真的比单一窗口更适合当前外部高湿响应分析。

- short_window_hours：`2`
- main_window_hours：`6`
- long_window_hours：`12`
- no_heat_status_counts：`{'ext_high_hum_no_heat_multiscale_breathing_watch': 1, 'ext_high_hum_no_heat_multiscale_negative': 1, 'ext_high_hum_no_heat_multiscale_supported': 1}`
- no_heat_three_state_ready：`True`
- short_window_overreacts：`True`
- cooling_status_counts：`{'ext_high_hum_cooling_multiscale_no_segment': 2, 'ext_high_hum_cooling_multiscale_long_confirmed_candidate': 1}`
- cooling_long_confirmation_helpful：`True`
- cooling_validation_ready：`False`

## 无热源高湿分支的结论

- 当前多尺度有价值，但价值不在“把所有尺度一起喂给统一模型”，而在“用 `6h` 做主判定，再用 `12h` 判断它是持续进湿还是更像慢性呼吸效应”。
- `2h` 当前不适合做主判定，因为它会把原本低信号的 sealed 运行也放大成 watch；因此短窗只能做局部增强，不能做结论主导。

- 2026-03-06 160246_seal_unheated | seal=seal | fused=ext_high_hum_no_heat_multiscale_breathing_watch | hits(2h/6h/12h)=5/5/5 | score(2h/6h/12h)=0.404/0.265/0.464 | gap_main_long=-0.199 | rationale=long_scale_not_weaker_than_main | short_scale_more_spiky_than_main
- 2026-03-02 161335_seal_unheated | seal=seal | fused=ext_high_hum_no_heat_multiscale_negative | hits(2h/6h/12h)=0/0/0 | score(2h/6h/12h)=0.000/0.000/0.000 | gap_main_long=0.000 | rationale=main_and_long_low_signal
- 2026-03-03 181049_unseal_unheated | seal=unseal | fused=ext_high_hum_no_heat_multiscale_supported | hits(2h/6h/12h)=6/6/5 | score(2h/6h/12h)=0.371/0.506/0.371 | gap_main_long=0.135 | rationale=main_scale_stronger_than_long_scale | short_window_confirms_local_response

## 冷却响应分支的结论

- 冷却响应更像“累计型响应”，不是短时尖峰；因此 `12h` 的价值大于 `2h`。
- 这里的多尺度正确用法不是让 `2h` 决策，而是让 `6h` 先提出候选，再由 `12h` 去确认是否存在累计的 `delta_half_dAH` 正向响应。

- 2026-03-14 174006_unseal_heated | seal=unseal | fused=ext_high_hum_cooling_multiscale_long_confirmed_candidate | count(2h/6h/12h)=9/23/18 | q75_dAH(2h/6h/12h)=0.03654364153140843/0.08885630595080884/0.24756131017628408 | rationale=main_segment_exists | long_window_confirms_cumulative_dAH | short_window_has_local_positive_dAH
- 2026-03-03 101220_seal_heated | seal=seal | fused=ext_high_hum_cooling_multiscale_no_segment | count(2h/6h/12h)=0/0/0 | q75_dAH(2h/6h/12h)=nan/nan/nan | rationale=main_and_long_no_cooling_segment
- 2026-03-13 080032_unseal_heated | seal=unseal | fused=ext_high_hum_cooling_multiscale_no_segment | count(2h/6h/12h)=0/0/0 | q75_dAH(2h/6h/12h)=nan/nan/nan | rationale=main_and_long_no_cooling_segment

## 当前判断

- 多尺度对当前流程有价值，但只适合做“分支内的层级证据”，不适合现在就做“全流程统一多尺度融合模型”。
- 对 `外部高湿-无热源`，`6h 主判定 + 12h 长窗确认` 是有价值的；`2h` 只能做增强，不应直接主导结论。
- 对 `外部高湿-冷却段`，`12h` 的累计确认比 `2h` 更有价值；当前短窗没有证明自己能带来额外判别力。
- 因此，如果后续真的接回主流程，推荐的收口方式应是：`6h 主判定 + 2h onset 提示 + 12h 累计确认`，而不是把所有尺度直接堆进一个统一分类器。
