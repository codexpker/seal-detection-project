# 轻量融合准备度诊断

- 是否进入轻量融合：`False`
- 原因：Branches currently lack enough complementary errors; keep them as parallel candidates, not a fused primary path.

## 分支表现

- baseline run_balanced_accuracy=`0.6666666666666666`
- similarity run_balanced_accuracy=`0.6666666666666666`
- OR 规则 run_balanced_accuracy=`0.6666666666666666`
- AND 规则 run_balanced_accuracy=`0.6666666666666666`

## 互补性

- both_correct=`4`
- baseline_only_correct=`0`
- similarity_only_correct=`0`
- both_wrong=`2`
- prediction_disagreement=`0`
