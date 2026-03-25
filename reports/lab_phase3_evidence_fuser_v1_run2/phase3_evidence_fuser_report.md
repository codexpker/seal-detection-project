# 实验室第三阶段 状态段级证据融合 v1 报告

- 结论：`PARTIAL_PASS`
- review_queue_runs：`5`
- transition_capture_rate：`1.0`
- static_eval_balanced_accuracy：`0.5833333333333333`
- threshold_abstain_runs：`1`

## 融合原则

- 转移段优先级最高，只要转移证据通过，就直接进入 review 队列。
- 静态高信息运行采用 `threshold branch + similarity branch` 的弱证据融合，并允许阈值分支 abstain。
- 低信息和热相关运行不强判，只输出 gated 结果。

## 运行级结果分布

- final_status_counts = `{'gated_background': 5, 'gated_heat_related': 3, 'static_low_risk': 2, 'transition_alert': 2, 'static_consensus_alert': 2, 'static_abstain_low_signal': 1, 'static_disagreement_watch': 1}`
- risk_level_counts = `{'abstain': 9, 'high': 4, 'low': 2, 'watch': 1}`

## 验收判断

- transition_evidence_captured = `True`
- threshold_abstain_enabled = `True`
- all_runs_resolved_to_status = `True`
- static_review_quality_ready = `False`

## 需要复核的运行

- 2026-03-06 160246_seal_unheated | status=static_disagreement_watch | evidence=similarity_branch | segment=S001 | notes=threshold_pred=0 | similarity_pred=1
- 2026-03-04 120007_seal_unheated-2026-03-04 163909_unseal_unheated | status=transition_alert | evidence=transition_branch | segment=S001 | notes=transition evidence passed
- 2026-03-08 172014_seal_unheated | status=transition_alert | evidence=transition_branch | segment=S002 | notes=transition evidence passed
- 2026-03-04 163909_unseal_unheated | status=static_consensus_alert | evidence=threshold+similarity | segment=S001 | notes=threshold_pred=1 | similarity_pred=1
- 2026-03-22 150919_unseal_unheated | status=static_consensus_alert | evidence=threshold+similarity | segment=S002 | notes=threshold_pred=1 | similarity_pred=1

## 当前判断

- 这一步已经把“模型输出”改造成了“证据驱动决策输出”，更适合演示和后续现场迁移。
- 当前最强证据仍然是转移段；静态分支主要价值是提供辅助风险和显式 abstain。
- 当前结构已经成立，但静态 review 队列质量还没有到稳定通过线；接下来应优先优化 review 队列质量和证据展示，而不是继续增加孤立模型支线。
