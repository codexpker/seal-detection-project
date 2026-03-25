# 历史旧数据干扰分析报告

- 可用运行数：`34`
- 子集合分布：`{'sealed_strict': 19, 'unsealed': 8, 'sealed_no_screw_grease': 7}`
- 状态分布：`{'ok': 34, 'empty_after_preprocess': 2}`

## 首要发现

- 压缩包文件名与包内目录标签是反的，后续分析必须以包内目录为准，不能直接按 zip 文件名做监督标签。
- 这批历史数据至少不是二分类，而是三类集合：`非密封`、`严格密封`、`没拧螺丝和黄油但没打孔`。
- `严格密封` 里存在一批会被当前规则长时间打成 `candidate_high_info` 的运行，这说明旧数据更适合作为干扰挑战集，而不是直接并入主训练集。

## 分组中位数

| subgroup               |   duration_h |   mean_out_h |    mean_dT |   candidate_high_info_ratio |   heat_related_ratio |   complex_ratio |   best_lag_h |   best_lag_rh_h |   gain_ratio_dAH_change |
|:-----------------------|-------------:|-------------:|-----------:|----------------------------:|---------------------:|----------------:|-------------:|----------------:|------------------------:|
| sealed_no_screw_grease |      13.3719 |      64.0896 | -0.0318246 |                    0        |             0        |               0 |          1.5 |             0.5 |                0.391051 |
| sealed_strict          |      23.6025 |      44.1466 | -0.23777   |                    0        |             0        |               0 |          1   |             5.5 |                0.643068 |
| unsealed               |      22.6954 |      40.8983 | -0.248427  |                    0.655263 |             0.225564 |               0 |          0   |             1   |                0.982612 |

## 最容易误导当前路线的严格密封运行

- 数量：`9`
- 2026-01-04 165808 | candidate_high_info_ratio=0.922 | ext_high_hum_ratio=0.922 | mean_out_h=84.60 | best_lag_rh_h=1.0
- 2025-12-26 121522 | candidate_high_info_ratio=0.846 | ext_high_hum_ratio=0.846 | mean_out_h=48.99 | best_lag_rh_h=1.0
- 2025-12-28 120304 | candidate_high_info_ratio=0.829 | ext_high_hum_ratio=0.829 | mean_out_h=35.62 | best_lag_rh_h=6.0
- 2025-12-05 170640 | candidate_high_info_ratio=0.775 | ext_high_hum_ratio=0.775 | mean_out_h=70.92 | best_lag_rh_h=6.0
- 2025-12-18 180011 | candidate_high_info_ratio=0.734 | ext_high_hum_ratio=0.734 | mean_out_h=22.97 | best_lag_rh_h=5.0
- 2025-11-18 104042 | candidate_high_info_ratio=0.600 | ext_high_hum_ratio=0.600 | mean_out_h=28.66 | best_lag_rh_h=2.0
- 2025-12-17 111715 | candidate_high_info_ratio=0.579 | ext_high_hum_ratio=0.579 | mean_out_h=22.95 | best_lag_rh_h=6.0
- 2025-12-12 162037 | candidate_high_info_ratio=0.571 | ext_high_hum_ratio=0.571 | mean_out_h=29.66 | best_lag_rh_h=6.0

## 可分性线索

- `unsealed vs sealed_strict` 的静态简单特征分离度并不高，当前最好的几个单特征 AUC 只在中等水平，说明旧数据确实会把主任务打乱。
- 当前更有前景的不是继续堆静态均值/斜率，而是看动态响应特征：`外部变化 -> 内部变化` 的增益和滞后。

### unsealed vs sealed_strict Top Features

- best_lag_rh_h | auc=0.792 | direction=neg
- candidate_high_info_ratio | auc=0.701 | direction=pos
- gain_ratio_dAH_change | auc=0.667 | direction=pos
- heat_related_ratio | auc=0.661 | direction=pos
- max_corr_dAH_change | auc=0.619 | direction=neg
- best_lag_h | auc=0.601 | direction=neg

### unsealed vs sealed_no_screw_grease Top Features

- candidate_high_info_ratio | auc=0.893 | direction=pos
- mean_out_h | auc=0.857 | direction=neg
- best_lag_h | auc=0.821 | direction=neg
- gain_ratio_dAH_change | auc=0.714 | direction=pos
- max_corr_outRH_inRH_change | auc=0.714 | direction=neg
- heat_related_ratio | auc=0.652 | direction=pos

## 结论

- 这批旧数据不适合直接并入当前 `seal/unseal` 主训练集，否则会把大量严格密封运行也推成高风险模式。
- 这批旧数据最合适的角色是：`干扰挑战集 + 负控制集 + 动态响应特征发现集`。
- 如果要继续利用它们，下一步不应先建更复杂分类器，而应先验证动态响应特征，例如 `best_lag_rh_h`、`best_lag_h`、`gain_ratio_dAH_change` 是否能稳定刻画外部激励到内部响应的差异。
