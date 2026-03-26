# Cooling Residual Probe v2

- 目的：把冷却段候选从“按 `delta_half_dAH` 最强块”改成“最早出现且外部确实有 AH 余量的块”，优先排除没有外部进湿条件的伪候选。

- run_count: `3`
- status_counts: `{'cooling_residual_v2_no_segment': 2, 'cooling_residual_v2_no_external_headroom': 1}`
- selected_block_count: `0`
- headroom_gate_block_count: `0`
- validation_ready: `False`

## 当前判断

- v2 不再默认使用 `q75_delta_half_dAH` 最强块，而是优先选择最早出现、且 `外部 AH 余量` 满足硬门控的块。
- 如果所有块都不满足 `positive_headroom_ratio` 和 `max_out_headroom_ah_raw` 的条件，则直接输出 `cooling_residual_v2_no_external_headroom`。

## 运行级结果

- 2026-03-14 174006_unseal_heated | seal=unseal | status=cooling_residual_v2_no_external_headroom | selected_reason=no_block_passes_external_headroom_gate | block_start=2026-03-14 17:00:00 | positive_headroom_ratio_4h=0.2 | max_out_headroom_ah_raw_4h=0.15363373392444046 | end_excess_ah_4h=-0.43501683945794767 | pos_area_excess_ah_4h=0.0 | v2_multiscale=ext_high_hum_cooling_multiscale_long_confirmed_candidate
- 2026-03-03 101220_seal_heated | seal=seal | status=cooling_residual_v2_no_segment | selected_reason=no_cooling_block | block_start=NaT | positive_headroom_ratio_4h=nan | max_out_headroom_ah_raw_4h=nan | end_excess_ah_4h=nan | pos_area_excess_ah_4h=nan | v2_multiscale=ext_high_hum_cooling_multiscale_no_segment
- 2026-03-13 080032_unseal_heated | seal=unseal | status=cooling_residual_v2_no_segment | selected_reason=no_cooling_block | block_start=NaT | positive_headroom_ratio_4h=nan | max_out_headroom_ah_raw_4h=nan | end_excess_ah_4h=nan | pos_area_excess_ah_4h=nan | v2_multiscale=ext_high_hum_cooling_multiscale_no_segment

## 块级诊断

- 2026-03-14 174006_unseal_heated | block=1 | start=2026-03-14 17:00:00 | positive_headroom_ratio_4h=0.2 | max_out_headroom_ah_raw_4h=0.15363373392444046 | end_excess_ah_4h=-0.43501683945794767 | headroom_gate_pass=False
- 2026-03-14 174006_unseal_heated | block=2 | start=2026-03-15 06:00:00 | positive_headroom_ratio_4h=0.0 | max_out_headroom_ah_raw_4h=-0.6932673547629449 | end_excess_ah_4h=-0.22387362800407473 | headroom_gate_pass=False
- 2026-03-14 174006_unseal_heated | block=3 | start=2026-03-16 20:00:00 | positive_headroom_ratio_4h=0.0 | max_out_headroom_ah_raw_4h=-0.5962434077882328 | end_excess_ah_4h=-0.23980126519848355 | headroom_gate_pass=False

## 解释

- `外部 AH 余量` 为负，表示该冷却段里外部绝对湿度低于段起点内部绝对湿度；这时即便 `dAH` 相对改善，也不应直接解释为外部高湿空气进入。
- 这一步的目标不是把 candidate 数量抬高，而是更早地识别“没有外部进湿物理前提”的冷却伪证据。
- 因此，若 v2 仍没有产出有效块，当前正确结论应是：冷却段还不具备升主分支条件，而不是继续调阈值强行抬分。
