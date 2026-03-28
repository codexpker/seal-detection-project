# New Data Segment Feedback Loop v1

- 目的：把 `segment_review_queue_v2` 的人工复核结果沉淀成段级正参考、负参考、breathing hard case、confound challenge，并对剩余段重新排序。

- review_rows：`10`
- reviewed_rows：`6`
- positive_reference_segments：`1`
- negative_reference_segments：`0`
- transition_positive_segments：`3`
- breathing_watch_segments：`1`
- confound_segments：`1`
- pending_segments：`4`

## 回灌后剩余待复核段

- 120165519_20260309-102255_sealed_extLow_intHigh_noHeat_Change_20260310-1000_unsealed::post_change | support_status=transition_secondary_control | weak_support=nan | breathing=nan | confound=nan
- 120165519_20260313-111811_sealed_extLow_intHigh_Heat_Change_20260315-1500_unsealed::post_change | support_status=transition_secondary_control | weak_support=nan | breathing=nan | confound=nan
- 120165520_20260310-170038_sealed_extEq_intEq_Heat_Change_20260313-1002_unsealed::post_change | support_status=transition_secondary_control | weak_support=nan | breathing=nan | confound=nan
- 120165520_20260318-090358_sealed_extEq_intEq_Heat_Change_20260319-1520_unsealed::post_change | support_status=transition_secondary_control | weak_support=nan | breathing=nan | confound=nan

## 当前判断

- 这一步不改主判定链，只把你的人工判断沉淀成段级参考池和难例池。
- 之后你每确认一批 `positive_reference / negative_reference / breathing_watch / confound`，静态支持层就会越来越稳。
- 所以这一步是把当前第二阶段真正跑成“可持续复核闭环”，而不是继续离线堆特征。
