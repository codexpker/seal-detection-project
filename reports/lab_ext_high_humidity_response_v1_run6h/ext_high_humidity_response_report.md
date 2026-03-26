# 外部高湿响应分支 v1 报告

- 目的：把 `外部高湿驱动` 从混合静态逻辑里显式拆成 `无热源响应` 和 `冷却响应` 两条分支，直接回答“理论上该能分，为什么现在还没稳定分出来”。

- no_heat_runs：`3`
- no_heat_status_counts：`{'ext_high_hum_no_heat_response_supported': 1, 'ext_high_hum_no_heat_breathing_watch': 1, 'ext_high_hum_no_heat_response_negative': 1}`
- no_heat_supported_unsealed：`1`
- no_heat_negative_sealed：`1`
- no_heat_breathing_watch_sealed：`1`
- cooling_family_runs：`3`
- cooling_status_counts：`{'ext_high_hum_cooling_no_segment': 2, 'ext_high_hum_cooling_response_weak': 1}`
- cooling_runs_with_segments：`1`
- cooling_sealed_reference_runs：`0`
- cooling_unsealed_reference_runs：`1`
- cooling_validation_ready：`False`

## 外部高湿-无热源响应

- 这条分支的物理假设是：在外部持续高湿、内部无热源时，不密封运行应表现出更强的 `外部湿度驱动 -> 内部湿度响应`。
- 当前结果说明：这条逻辑不是无效，而是已经能把 `低信号 sealed`、`response-supported unsealed` 和 `response-like sealed hard case` 三种状态分开。

- 2026-03-03 181049_unseal_unheated | seal=unseal | status=ext_high_hum_no_heat_response_supported | hits=6/6 | score=0.506 | features=corr_out_hum_in_hum,max_corr_outRH_inRH_change,frac_threshold_favored,frac_pos_delta_half_dAH,q90_delta_half_dAH_w,std_in_hum_run | final_status=static_dynamic_support_alert
- 2026-03-06 160246_seal_unheated | seal=seal | status=ext_high_hum_no_heat_breathing_watch | hits=5/6 | score=0.265 | features=corr_out_hum_in_hum,max_corr_outRH_inRH_change,frac_threshold_favored,frac_pos_delta_half_dAH,q90_delta_half_dAH_w | final_status=static_hard_case_watch
- 2026-03-02 161335_seal_unheated | seal=seal | status=ext_high_hum_no_heat_response_negative | hits=0/6 | score=0.000 | features= | final_status=static_abstain_low_signal

## 外部高湿-冷却响应

- 这条分支的物理假设是：热源停止后的冷却段若出现进湿，不应只表现为 RH 回升，而应伴随更明确的 `delta_half_dAH` 正向响应。
- 当前先用 `delta_in_temp < 0` 或 `slope_in_temp < 0 且 delta_half_in_temp < 0` 抽取冷却窗口，再看这些窗口里的 `delta_half_dAH` 是否持续为正。

- 2026-03-14 174006_unseal_heated | seal=unseal | cooling_windows=23 | status=ext_high_hum_cooling_response_weak | frac_pos_dAH=0.6521739130434783 | q75_dAH=0.08885630595080884 | final_status=gated_heat_related
- 2026-03-03 101220_seal_heated | seal=seal | cooling_windows=0 | status=ext_high_hum_cooling_no_segment | frac_pos_dAH=nan | q75_dAH=nan | final_status=gated_heat_related
- 2026-03-13 080032_unseal_heated | seal=unseal | cooling_windows=0 | status=ext_high_hum_cooling_no_segment | frac_pos_dAH=nan | q75_dAH=nan | final_status=gated_heat_related

## 当前解释

- 外部高湿驱动并不是“筛不出来”，而是已经能筛成一个有价值主战场；问题出在这个主战场内部仍然存在 `sealed 但表现出 response-like` 的难例。
- 这类难例最合理的解释不是“物理假设失效”，而是 `材料吸放湿 / 内部残余湿气 / 初始状态差异 / 结构呼吸效应` 让 sealed 运行也出现了类似外部驱动的响应。
- 冷却响应当前还不能稳定验收，不是因为物理机制不成立，而是因为当前数据里缺少足够的 `高湿 + 有热源 + 明确冷却段 + sealed 对照` 参考窗口。
- 因此下一步真正该改的是：把高湿无热源和高湿冷却从“长窗静态判别”改成“受激响应段判别”，而不是继续试图用整段均值去做统一分类。
