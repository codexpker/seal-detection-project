# Health Bank Feedback Loop v1

- 目的：把 `review_output` 的人工复核结果真正回灌到健康窗口库和后续相似性排序中，形成增量闭环。

- review_rows：`16`
- reviewed_rows：`3`
- promoted_health_runs：`1`
- promoted_health_windows：`32`
- anomaly_reference_runs：`2`
- updated_health_bank_runs：`4`
- updated_health_bank_windows：`53`
- reranked_pending_runs：`3`

## 回灌后待复核风险排序

- 2026-03-03 181049_unseal_unheated | rank_score=0.426 | final_status=static_dynamic_support_alert | review_status=pending
- 2026-03-04 163909_unseal_unheated | rank_score=0.338 | final_status=static_dynamic_supported_alert | review_status=pending
- 2026-03-22 150919_unseal_unheated | rank_score=0.263 | final_status=static_dynamic_supported_alert | review_status=pending

## 当前判断

- 这一步不改变现有主判定链，只把人工复核结果沉淀成健康参考或异常参考。
- 后续只要持续补充 `healthy` 复核样本，健康窗口库就可以按设备逐步扩容；相似性排序也会随之变得更稳。
- 因此这条线已经具备了从实验室过渡到现场“历史健康窗口库”闭环的最小工程结构。
