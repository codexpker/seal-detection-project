# 新补充数据深度分析报告

## 核心结论

- 总运行数：`20`
- 可用运行数：`20`
- change_type_counts：`{'no_change': 7, 'seal_change_to_unsealed': 7, 'heat_on': 3, 'heat_off': 2, 'ext_humidity_up': 1}`
- initial_role_counts：`{'mainfield_extHigh_intLow_noHeat': 8, 'balanced_control': 6, 'highhum_heated': 3, 'internal_moisture_control': 2, 'other': 1}`
- dominant_label_counts：`{'外部高湿驱动工况': 7, '热源稳定工况': 4, '复杂耦合工况': 3, '': 2, '内部积湿工况': 2, '冷却窗口': 1, '热源启动窗口': 1}`

## 先说最关键的判断

- 这批 `new_data` 不是简单地“在旧数据上多加了几条同分布样本”，而是明显扩展成了 `seal 变化 + heat 变化 + 外部湿度变化 + no-change` 混合数据集。
- 所以如果继续按“整文件 seal/unseal 直接建模”的口径使用它，很多运行会天然变成混合样本，反而会污染当前主任务。
- 这批数据真正的新价值，不主要是增加了多少 whole-run 静态样本，而是提供了更多 **已知改变时刻** 的段级样本和更多 **非密封以外的对照变化**。

## 这批新数据实际补强了什么

- `mainfield_extHigh_intLow_noHeat` whole-run 数量：`8`
- 主战场 full-run 可分析段数量：`3`
- 主战场 split-run 可分析段数量：`5`
- 主战场可分析的 `unsealed` 段数量：`5`
- 主战场可分析段 seal/unseal 分布：`{'unsealed': 5, 'sealed': 3}`
- 对照/干扰可分析段数量：`16`

### 对主战场的意义

- 如果只看 whole-run，这批数据对 `外部高湿-无热源` 静态 seal/unseal 的直接补充并不算多。
- 但如果按说明表里的 `改变时间` 做段级切分，就能把一部分 `seal->unseal` 运行拆成 `pre sealed` 和 `post unsealed` 两段，从而真正增加可用静态样本和 transition 样本。

### 对干扰建模的意义

- `heat_on / heat_off / ext_humidity_up` 这些变化，不应当被当成新的异常正样本，而应被当成 **反事实对照** 或 **干扰控制组**。
- 这批运行最适合用来验证：当前路由是否会把“热源变化”或“外界湿度变化”误当成泄漏证据。

## 当前高价值运行

- 120165524_20260302 161335_sealed_extHigh_intLow_noHeat_noChange_na | role=mainfield_extHigh_intLow_noHeat | change=no_change | candidate_high_info_ratio=1.000 | heat_related_ratio=0.000 | internal_moisture_ratio=0.000 | dominant_label=外部高湿驱动工况
- 120165524_20260304-120007_sealed_extHigh_intLow_noHeat_Change_20260304-1639_unsealed | role=mainfield_extHigh_intLow_noHeat | change=seal_change_to_unsealed | candidate_high_info_ratio=1.000 | heat_related_ratio=0.000 | internal_moisture_ratio=0.000 | dominant_label=外部高湿驱动工况
- 120165524_20260306-160246_sealed_extHigh_intLow_noHeat_noChange_na | role=mainfield_extHigh_intLow_noHeat | change=no_change | candidate_high_info_ratio=1.000 | heat_related_ratio=0.000 | internal_moisture_ratio=0.000 | dominant_label=外部高湿驱动工况
- 120165524_20260308-172014_sealed_extHigh_intLow_noHeat_Change_20260310-1000_unsealed | role=mainfield_extHigh_intLow_noHeat | change=seal_change_to_unsealed | candidate_high_info_ratio=1.000 | heat_related_ratio=0.000 | internal_moisture_ratio=0.000 | dominant_label=外部高湿驱动工况
- 120165524_20260323-213435_seal_extHigh_intLow_noHeat_Change_20260324-9000_unseal | role=mainfield_extHigh_intLow_noHeat | change=seal_change_to_unsealed | candidate_high_info_ratio=1.000 | heat_related_ratio=0.000 | internal_moisture_ratio=0.000 | dominant_label=外部高湿驱动工况
- 120165524_20260321-170450_unseal_extHigh_intLow_Heat_Change_20260321-1800_noHeat | role=highhum_heated | change=heat_off | candidate_high_info_ratio=0.816 | heat_related_ratio=0.184 | internal_moisture_ratio=0.000 | dominant_label=外部高湿驱动工况
- 120165524_20260303-181049_unsealed_extHigh_intLow_noHeat_noChange_na | role=mainfield_extHigh_intLow_noHeat | change=no_change | candidate_high_info_ratio=0.800 | heat_related_ratio=0.200 | internal_moisture_ratio=0.000 | dominant_label=外部高湿驱动工况
- 120165524_20260314-174006_unsealed_extHigh_intLow_Heat_noChange_na | role=highhum_heated | change=no_change | candidate_high_info_ratio=0.000 | heat_related_ratio=1.000 | internal_moisture_ratio=0.000 | dominant_label=热源稳定工况

## 对后续建模最重要的建议

1. 不要把这批新数据直接并到当前 whole-run 监督训练集里。
2. 先做 `segment_manifest`：把 `pre_change / post_change` 从整文件里拆出来，再决定哪些段能进入主任务。
3. `seal_change_to_unsealed` 的 `pre/post` 段应优先进入两类任务：
   - `transition event detection`
   - `extHigh_intLow_noHeat` 静态段对照
4. `heat_on / heat_off / ext_humidity_up` 应优先进入 `watch / abstain` 和路由鲁棒性验证，不应直接当成 anomaly 正样本。
5. 如果后面继续建模，应优先从“段级建模”而不是“整文件建模”开始。

## 当前最合理的下一步

- 第一步：把这批数据先标准化成 `segment_manifest`，而不是直接重训模型。
- 第二步：只在 `extHigh_intLow_noHeat` 的稳定段和 `seal->unseal` 转移段上更新现有主线。
- 第三步：把 `heat_on / heat_off / ext_humidity_up` 作为新的挑战集，专门验证误报控制。

## 主战场可分析段

- 120165524_20260302 161335_sealed_extHigh_intLow_noHeat_noChange_na | segment=full | seal=sealed | hours=17.5 | source=full_run | delta_half_in_h=-1.137 | delta_half_dAH=-0.304
- 120165524_20260306-160246_sealed_extHigh_intLow_noHeat_noChange_na | segment=full | seal=sealed | hours=42.3 | source=full_run | delta_half_in_h=2.265 | delta_half_dAH=0.329
- 120165524_20260308-172014_sealed_extHigh_intLow_noHeat_Change_20260310-1000_unsealed | segment=pre_change | seal=sealed | hours=40.6 | source=seal_change_to_unsealed | delta_half_in_h=0.507 | delta_half_dAH=-0.077
- 120165524_20260303-181049_unsealed_extHigh_intLow_noHeat_noChange_na | segment=full | seal=unsealed | hours=15.2 | source=full_run | delta_half_in_h=0.616 | delta_half_dAH=-0.340
- 120165524_20260304-120007_sealed_extHigh_intLow_noHeat_Change_20260304-1639_unsealed | segment=post_change | seal=unsealed | hours=40.6 | source=seal_change_to_unsealed | delta_half_in_h=1.596 | delta_half_dAH=0.148
- 120165524_20260308-172014_sealed_extHigh_intLow_noHeat_Change_20260310-1000_unsealed | segment=post_change | seal=unsealed | hours=72.0 | source=seal_change_to_unsealed | delta_half_in_h=3.160 | delta_half_dAH=0.222
- 120165524_20260321-170450_unseal_extHigh_intLow_Heat_Change_20260321-1800_noHeat | segment=post_change | seal=unsealed | hours=47.6 | source=heat_off | delta_half_in_h=1.422 | delta_half_dAH=-0.638
- 120165524_20260323-213435_seal_extHigh_intLow_noHeat_Change_20260324-9000_unseal | segment=post_change | seal=unsealed | hours=53.4 | source=seal_change_to_unsealed | delta_half_in_h=3.627 | delta_half_dAH=0.386