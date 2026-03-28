# seal_v4 Transition 事件级改前改后对照

- file_count: `7`
- primary_count: `3`
- secondary_count: `4`
- primary_before_any_hit: `2`
- primary_after_any_hit: `2`
- secondary_before_any_hit: `0`
- secondary_after_any_hit: `0`

## 当前结论

- 这份对照只看 transition 运行的全扫描事件命中，不看最终尾窗一帧。
- 如果 `after_any_transition_hit` 仍然保留，就说明这次 `dew / lag / coupling` 接入主要影响的是尾窗保守性，而不是把整段 transition 事件完全打没。

## 主战场 transition

- 120165524_20260304-120007_sealed_extHigh_intLow_noHeat_Change_20260304-1639_unsealed | hit=2->2 | any_hit=True->True | latest=static_dynamic_supported_alert->static_hard_case_watch | peak_score=0.3035->0.3035
- 120165524_20260308-172014_sealed_extHigh_intLow_noHeat_Change_20260310-1000_unsealed | hit=2->2 | any_hit=True->True | latest=static_dynamic_supported_alert->static_hard_case_watch | peak_score=1.0000->1.0000
- 120165524_20260323-213435_seal_extHigh_intLow_noHeat_Change_20260324-9000_unseal | hit=0->0 | any_hit=False->False | latest=static_dynamic_supported_alert->static_hard_case_watch | peak_score=1.0000->1.0000

## Secondary control

- 120165519_20260309-102255_sealed_extLow_intHigh_noHeat_Change_20260310-1000_unsealed | hit=0->0 | any_hit=False->False | latest=low_info_background->low_info_background | peak_score=0.0000->0.0000
- 120165519_20260313-111811_sealed_extLow_intHigh_Heat_Change_20260315-1500_unsealed | hit=0->0 | any_hit=False->False | latest=low_info_background->low_info_background | peak_score=0.0000->0.0000
- 120165520_20260310-170038_sealed_extEq_intEq_Heat_Change_20260313-1002_unsealed | hit=0->0 | any_hit=False->False | latest=low_info_background->low_info_background | peak_score=0.0000->0.0000
- 120165520_20260318-090358_sealed_extEq_intEq_Heat_Change_20260319-1520_unsealed | hit=0->0 | any_hit=False->False | latest=heat_related_background->heat_related_background | peak_score=0.0000->0.0000