# Health Window Bank + Similarity Ranking v1

- 目的：在不新增黑盒模型的前提下，把当前实验室主路线进一步推进成“健康窗口库 + 相似性风险排序”的现场迁移骨架。

- health_bank_windows：`21`
- health_bank_runs：`3`
- scored_windows：`319`
- scored_runs：`4`
- pending_mean_rank_score：`0.5770970899426613`
- non_pending_mean_rank_score：`nan`
- run_auc_vs_review_queue：`None`
- run_auc_vs_nonsealed_or_mixed：`0.0`

## 健康窗口库概览

- ext_high_hum_no_heat | heat=off | coarse=candidate_high_info | bank_runs=1 | bank_windows=7
- unknown | heat=off | coarse=candidate_high_info | bank_runs=1 | bank_windows=9
- unknown | heat=on | coarse=exclude_low_info | bank_runs=1 | bank_windows=5

## 当前风险排序前列

- 2026-03-06 160246_seal_unheated | rank_score=1.457 | final_status=static_hard_case_watch | review_status=pending | dominant_bank_scope=strict_condition
- 2026-03-04 163909_unseal_unheated | rank_score=0.338 | final_status=static_dynamic_supported_alert | review_status=pending | dominant_bank_scope=strict_condition
- 2026-03-22 150919_unseal_unheated | rank_score=0.263 | final_status=static_dynamic_supported_alert | review_status=pending | dominant_bank_scope=strict_condition
- 2026-03-03 181049_unseal_unheated | rank_score=0.251 | final_status=static_dynamic_support_alert | review_status=pending | dominant_bank_scope=strict_condition

## 当前判断

- 这一步的目标不是做二分类，而是为后续现场任务先提供健康窗口库和风险排序接口。
- 当前健康库仍然偏小，因此它更适合作为迁移骨架和排序器，而不是替代现有实验室主判定链。
- 后续只要现场数据能继续按 `run_manifest / window_table / review_output` 接入，就可以逐步把健康库从实验室扩到设备级历史窗口库。
