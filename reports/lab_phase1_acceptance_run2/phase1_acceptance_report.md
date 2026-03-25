# 实验室一阶段验收报告

- 验收结论：`PARTIAL_PASS`
- 第一阶段是否可判定顺利通过：`False`
- 演示版是否可用：`True`

## 工况 Gate

- 已知工况且可成窗文件数：`7`
- expected_match_ratio_mean：`0.9714285714285714`
- Gate 是否通过：`True`

## 转移分支

- 转移文件数：`2`
- 转移分支是否通过：`True`
- 2026-03-04 120007_seal_unheated-2026-03-04 163909_unseal_unheated | near_windows=5 | median_rank=0.943 | near_score=1.534 | non_near_score=0.291 | pass=True
- 2026-03-08 172014_seal_unheated | near_windows=13 | median_rank=0.863 | near_score=0.627 | non_near_score=0.263 | pass=True

## 静态高信息分支

- 候选运行数：`7`
- 类别分布：`{'seal': 4, 'unseal': 3}`
- 最优单特征：`slope_in_h_per_h`
- 最优 AUC：`0.75`
- 静态分支是否通过：`False`

## 结论

- 当前数据已经足够支撑“工况先筛 + 转移段相对打分”的演示闭环。
- 当前数据还不足以支撑“高外湿无热源静态 seal/unseal 稳定区分”这一条分支通过验收。
- 因此一阶段不能判定为顺利通过，只能判定为演示版可用、主目标需分支推进。
