# 现场演示总览

## 当前主线

`分支感知路由 -> 转移段相对打分 -> evidence_fuser v2`

## 核心结论

- verdict: `PASS`
- transition_capture_rate: `1.0`
- transition_boost_capture_rate: `1.0`
- static_eval_balanced_accuracy: `1.0`
- static_prediction_coverage: `0.6666666666666666`

## 建议现场优先展示的样例

- 2026-03-04 120007_seal_unheated-2026-03-04 163909_unseal_unheated | `transition_boost_alert` | features=delta_in_hum,delta_half_in_hum,max_hourly_hum_rise,std_out_hum,corr_AH
- 2026-03-08 172014_seal_unheated | `transition_boost_alert` | features=delta_in_hum,delta_half_in_hum,max_hourly_hum_rise,corr_AH

## 建议现场展示的保守案例

- 2026-03-02 161335_seal_unheated | `static_abstain_low_signal` | notes=threshold branch abstained | similarity_pred=0 | dynamic_vote_count=1 | hard_case_ratio=1.164
- 2026-03-06 160246_seal_unheated | `static_hard_case_watch` | notes=threshold_pred=0 | similarity_pred=1 | dynamic_vote_count=5 | hard_case_ratio=0.547 | hard case watch overrides static alerting

## 讲解口径

- 强证据场景：直接进入 review，不拖成全局分类问题。
- 静态场景：只做辅助证据，不承诺全覆盖。
- 难例和干扰：主动进入 `watch / abstain`，不乱报。
