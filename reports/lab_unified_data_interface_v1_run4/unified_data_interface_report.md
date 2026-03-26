# Unified Data Interface v1

- 目的：把当前 `evidence_fuser v4` 主路线统一收口为三张正式表，供后续现场迁移、人工复核和历史库建设复用。
- 当前默认主路线：`gate/info selector v3 -> evidence_fuser v4 -> transition event summary`。
- 本次补充：保守接入 `no_heat probe v3` 到无热源高湿静态支线，同时继续在 `review_output` 中保留 `外部高湿响应分支 v2` 的多尺度解释字段。

- run_count：`16`
- window_count：`361`
- review_pending_rows：`6`
- condition_family_counts：`{'unknown': 8, 'ext_high_hum_no_heat': 3, 'ext_high_hum_with_heat': 3, 'transition_run': 2}`
- label_coarse_counts：`{'candidate_high_info': 247, 'exclude_low_info': 93, 'transition_neighbor': 18, 'holdout_complex': 3}`
- final_status_counts：`{'gated_background': 5, 'static_dynamic_supported_alert': 3, 'gated_heat_related': 3, 'transition_boost_alert': 2, 'static_abstain_low_signal': 1, 'static_hard_case_watch': 1, 'static_low_risk': 1}`

## 输出文件

- run_manifest: `reports/lab_unified_data_interface_v1_run4/run_manifest.csv`
- window_table: `reports/lab_unified_data_interface_v1_run4/window_table.csv`
- review_output: `reports/lab_unified_data_interface_v1_run4/review_output.csv`

## 当前判断

- 这一步没有引入新模型，只把当前已验证主路线整理成统一数据接口。
- 后续现场数据、健康窗口库、人工复核结果都应优先复用这三张表，而不是继续从零拼接不同报告。
