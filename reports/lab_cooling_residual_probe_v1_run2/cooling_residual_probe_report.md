# Cooling Residual Probe v1

- 目的：把 `外部高湿 + 热源停止后的冷却段` 从“直接看 RH 回升”改成“先扣除纯降温导致的 RH 理论回升，再看是否存在额外 AH/RH 残差”。

- run_count: `3`
- status_counts: `{'cooling_residual_no_segment': 2, 'cooling_residual_weak_or_confounded': 1}`
- candidate_runs: `0`
- sealed_with_cooling_block: `0`
- unsealed_with_cooling_block: `1`
- validation_ready: `False`

## 物理定义

- `RH_pred_const_AH`：以冷却起点的 `AH_in` 为常量，只根据内部温度下降推算理论 RH。
- `excess_rh_const_ah`：实际 `RH_in - RH_pred_const_AH`，表示超出“纯降温效应”的额外 RH 回升。
- `excess_ah_const`：实际 `AH_in - AH_in(start)`，表示冷却后内部是否真的获得了额外水汽，而不是只因温度下降导致 RH 表观回升。

## 当前判断

- 当前还不能把冷却段升成已验收能力，因为 `sealed heated cooling` 参考仍然缺失或未形成可用冷却段。

## 运行级结果

- 2026-03-03 101220_seal_heated | seal=seal | status=cooling_residual_no_segment | has_block=False | q75_delta_half_dAH_6h=nan | end_excess_ah_4h=nan | pos_area_excess_ah_4h=nan | max_excess_rh_4h=nan | headroom_raw_4h=nan | v2=ext_high_hum_cooling_multiscale_no_segment
- 2026-03-13 080032_unseal_heated | seal=unseal | status=cooling_residual_no_segment | has_block=False | q75_delta_half_dAH_6h=nan | end_excess_ah_4h=nan | pos_area_excess_ah_4h=nan | max_excess_rh_4h=nan | headroom_raw_4h=nan | v2=ext_high_hum_cooling_multiscale_no_segment
- 2026-03-14 174006_unseal_heated | seal=unseal | status=cooling_residual_weak_or_confounded | has_block=True | q75_delta_half_dAH_6h=0.12703555778361658 | end_excess_ah_4h=-0.23980126519848355 | pos_area_excess_ah_4h=0.024338944039232757 | max_excess_rh_4h=0.06428388098034787 | headroom_raw_4h=-0.8946899707250922 | v2=ext_high_hum_cooling_multiscale_long_confirmed_candidate

## 解释

- 如果 `excess_ah_const` 为正，说明冷却段内部不只是“温度下降导致 RH 看起来升高”，而是真实获得了额外绝对湿度。
- 如果 `excess_rh_const_ah` 为正但 `excess_ah_const` 不显著，说明更可能是温度效应、局部扰动或短时数值抖动，而不是稳健的进湿证据。
- 如果 `mean_out_headroom_ah_raw` 为负，说明在该冷却段里外部绝对湿度本身就低于冷却起点的内部绝对湿度；这种情况下即便 `dAH` 变得更“好看”，也不应直接解释成外部进湿。
- 当前最关键的缺口不是阈值，而是 sealed 侧缺少真正可用的高湿冷却参考段；因此这条线当前最适合作为物理解释探针，而不是主判定分支。
