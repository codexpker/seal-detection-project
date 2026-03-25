# 实验室第二阶段 相似性 / 记忆分支报告

- 分支结论：`PASS`
- 最优训练视图：`all_candidate_windows`
- 记忆特征：`mean_dAH, std_dAH, mean_dT, std_dT, slope_AH_in, slope_dAH, delta_half_in_hum, delta_half_dAH, corr_AH, max_hourly_hum_rise`
- k：`5`

## 训练视图对照

- all_candidate_windows | window_auc=0.7138480392156863 | run_auc=0.888888888888889 | run_balanced_accuracy=0.6666666666666666 | pass=True
- top_info_windows | window_auc=0.8116666666666666 | run_auc=0.7777777777777778 | run_balanced_accuracy=0.6666666666666666 | pass=False

## 判断

- 该分支只在静态高信息工况内验证，不替代转移分支。
- 若该分支优于当前阈值基线，才有资格进入后续轻量融合候选。
- 若未优于阈值基线，则当前主推荐仍保持不变。
