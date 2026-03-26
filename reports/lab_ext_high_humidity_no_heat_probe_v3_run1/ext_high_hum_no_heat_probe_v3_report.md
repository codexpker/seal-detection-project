# External High-Humidity No-Heat Probe v3

- 目的：把 `外部高湿-无热源` 从“长窗静态差异”进一步收敛成 `早段响应 + 晚段持续性` 的三态解释。

- run_count: `3`
- status_counts: `{'ext_high_hum_no_heat_probe_breathing_watch': 1, 'ext_high_hum_no_heat_probe_negative': 1, 'ext_high_hum_no_heat_probe_supported': 1}`
- onset_positive_count: `2`
- late_persistence_count: `1`
- breathing_bias_count: `1`

## 规则解释

- `onset_positive_v3`: 前 `6` 小时里，外部 RH 上升时，内部 RH 是否也同步上升，并且 `rh_gain_per_out > 0.00`。
- `late_persistence_v3`: 后 `6` 小时里，这种同步性是否仍然持续，且 `6h` 主尺度不再明显强于 `12h` 长尺度。
- `breathing_bias_v3`: 后段 `RH` 响应更强，同时 `AH` 衰减/驱动力 比例接近 0，提示更像 `呼吸/释湿` 而不是单纯前段进湿响应。

## 当前判断

- 这一步没有引入新模型，而是把当前 `supported / negative / breathing_watch` 三态进一步物理化。
- 如果后续继续接回主流程，建议优先把它作为 `review / demo` 的补充解释，而不是直接替换全局默认判定。

## 运行级结果

- 2026-03-06 160246_seal_unheated | seal=seal | probe=ext_high_hum_no_heat_probe_breathing_watch | early_resp_ratio=1.000 | early_rh_gain=0.138 | late_resp_ratio=1.000 | late_rh_gain=0.499 | late_ah_decay_per_headroom=-0.003 | v2=ext_high_hum_no_heat_multiscale_breathing_watch | rationale=late_persistence_with_low_ah_decay
- 2026-03-02 161335_seal_unheated | seal=seal | probe=ext_high_hum_no_heat_probe_negative | early_resp_ratio=0.000 | early_rh_gain=-0.184 | late_resp_ratio=0.000 | late_rh_gain=-0.170 | late_ah_decay_per_headroom=-0.025 | v2=ext_high_hum_no_heat_multiscale_negative | rationale=early_response_absent
- 2026-03-03 181049_unseal_unheated | seal=unseal | probe=ext_high_hum_no_heat_probe_supported | early_resp_ratio=1.000 | early_rh_gain=0.181 | late_resp_ratio=1.000 | late_rh_gain=0.400 | late_ah_decay_per_headroom=-0.013 | v2=ext_high_hum_no_heat_multiscale_supported | rationale=early_response_present_without_persistent_breathing_pattern