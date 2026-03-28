# New Data Segment Feedback Loop v1

- 目的：把 `segment_review_queue_v2` 的人工复核结果沉淀成段级正参考、负参考、breathing hard case、confound challenge，并对剩余段重新排序。

- review_rows：`10`
- reviewed_rows：`0`
- positive_reference_segments：`0`
- negative_reference_segments：`0`
- transition_positive_segments：`0`
- breathing_watch_segments：`0`
- confound_segments：`0`
- pending_segments：`10`

## 回灌后剩余待复核段

- 120165524_20260308-172014_sealed_extHigh_intLow_noHeat_Change_20260310-1000_unsealed::post_change | support_status=transition_primary_support | weak_support=1.0 | breathing=0.0 | confound=0.4
- 120165524_20260323-213435_seal_extHigh_intLow_noHeat_Change_20260324-9000_unseal::post_change | support_status=transition_primary_support | weak_support=0.6666666666666666 | breathing=0.0 | confound=0.6
- 120165524_20260304-120007_sealed_extHigh_intLow_noHeat_Change_20260304-1639_unsealed::post_change | support_status=transition_primary_support | weak_support=0.6666666666666666 | breathing=1.0 | confound=0.4
- 120165524_20260303-181049_unsealed_extHigh_intLow_noHeat_noChange_na::full | support_status=static_supported_weak_positive | weak_support=1.0 | breathing=1.0 | confound=0.75
- 120165524_20260306-160246_sealed_extHigh_intLow_noHeat_noChange_na::full | support_status=static_watch_breathing_confirmed | weak_support=0.1666666666666666 | breathing=1.0 | confound=0.6
- 120165524_20260321-170450_unseal_extHigh_intLow_Heat_Change_20260321-1800_noHeat::post_change | support_status=static_watch_confound_confirmed | weak_support=0.3333333333333333 | breathing=0.8 | confound=1.0
- 120165519_20260309-102255_sealed_extLow_intHigh_noHeat_Change_20260310-1000_unsealed::post_change | support_status=transition_secondary_control | weak_support=nan | breathing=nan | confound=nan
- 120165519_20260313-111811_sealed_extLow_intHigh_Heat_Change_20260315-1500_unsealed::post_change | support_status=transition_secondary_control | weak_support=nan | breathing=nan | confound=nan

## 当前判断

- 这一步不改主判定链，只把你的人工判断沉淀成段级参考池和难例池。
- 之后你每确认一批 `positive_reference / negative_reference / breathing_watch / confound`，静态支持层就会越来越稳。
- 所以这一步是把当前第二阶段真正跑成“可持续复核闭环”，而不是继续离线堆特征。
