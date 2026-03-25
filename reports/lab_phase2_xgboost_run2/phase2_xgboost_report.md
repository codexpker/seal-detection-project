# 实验室第二阶段 XGBoost 支线报告

- 分支结论：`FAIL`
- 最优训练视图：`all_candidate_windows`
- 训练范围：`高外湿 + 无热源 + 非转移 + candidate_high_info`
- 窗口数：`99`
- 运行数：`6`

## 训练视图对照

- all_candidate_windows | window_auc=0.39052287581699346 | run_auc=0.4444444444444445 | run_balanced_accuracy=0.5 | pass=False
- top_info_windows | window_auc=0.19833333333333336 | run_auc=0.11111111111111112 | run_balanced_accuracy=0.3333333333333333 | pass=False

## 最优视图留一运行验证

- window_auc：`0.39052287581699346`
- window_balanced_accuracy：`0.42830882352941174`
- run_auc：`0.4444444444444445`
- run_balanced_accuracy：`0.5`

## 与简单单特征基线对照

- 最优单特征：`delta_half_dAH`
- 最优单特征 AUC：`0.7777777777777778`

## 判断

- 这条支线只负责静态高信息分支，不替代转移分支。
- 如果 run_auc 和 run_balanced_accuracy 都过线，则说明第二阶段的 XGBoost 判别支线可以进入演示或并行评估。
- 如果不过线，则第二阶段已完成实现，但这条支线还不能作为静态分支验收依据。
