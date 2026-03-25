# 实验室第二阶段 相似性 / 记忆分支报告

- 分支结论：`FAIL`
- 最优训练视图：`top_info_windows`
- 记忆特征：`mean_dAH, std_dAH, mean_dT, std_dT, slope_AH_in, slope_dAH, delta_half_in_hum, delta_half_dAH, corr_AH, max_hourly_hum_rise`
- k：`5`

## 训练视图对照

- all_candidate_windows | window_auc=0.28615196078431376 | run_auc=0.11111111111111112 | run_balanced_accuracy=0.6666666666666666 | pass=False
- top_info_windows | window_auc=0.18833333333333332 | run_auc=0.22222222222222224 | run_balanced_accuracy=0.6666666666666666 | pass=False

## 判断

- 该分支只在静态高信息工况内验证，不替代转移分支。
- 若该分支优于当前阈值基线，才有资格进入后续轻量融合候选。
- 若未优于阈值基线，则当前主推荐仍保持不变。
