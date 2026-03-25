# Dynamic Response Probe v1

- old_ok_runs = `34`
- current_runs = `15`
- current_static_runs = `6`

## 旧数据结论

- 旧数据里的 `strict sealed` 与 `unsealed`，静态特征分离度有限，但动态响应特征开始出现工程价值。
- 当前旧数据里最强的动态线索仍然是 `best_lag_rh_h`，说明外部 RH 变化到内部 RH 变化的响应滞后值得继续跟。

### old unsealed vs sealed_strict Top Features

- best_lag_rh_h | auc=0.792 | direction=neg
- candidate_high_info_ratio | auc=0.701 | direction=pos
- gain_ratio_dAH_change | auc=0.667 | direction=pos
- heat_related_ratio | auc=0.661 | direction=pos
- max_corr_dAH_change | auc=0.619 | direction=neg
- best_lag_h | auc=0.601 | direction=neg

## 当前分工况数据检查

- 只抽取当前 `static routed` 运行做对照，不把转移和热相关运行混进来。
- 当前样本量很小，这一步只看方向，不做通过验收。

### current static runs

- 2026-03-02 161335_seal_unheated | group=current_static_seal | best_lag_h=0.0 | best_lag_rh_h=0.0 | gain_ratio_dAH_change=0.41766653523253455
- 2026-03-06 160246_seal_unheated | group=current_static_seal | best_lag_h=1.0 | best_lag_rh_h=0.0 | gain_ratio_dAH_change=0.3027590808755177
- 2026-03-23 213435_seal_unheated | group=current_static_seal | best_lag_h=2.0 | best_lag_rh_h=2.0 | gain_ratio_dAH_change=0.7289469571758896
- 2026-03-03 181049_unseal_unheated | group=current_static_unseal | best_lag_h=5.0 | best_lag_rh_h=0.0 | gain_ratio_dAH_change=0.17701507095625685
- 2026-03-04 163909_unseal_unheated | group=current_static_unseal | best_lag_h=1.0 | best_lag_rh_h=0.0 | gain_ratio_dAH_change=0.4826478918834303
- 2026-03-22 150919_unseal_unheated | group=current_static_unseal | best_lag_h=1.0 | best_lag_rh_h=6.0 | gain_ratio_dAH_change=0.5419414824987419

### current static unseal vs seal Top Features

- max_corr_outRH_inRH_change | auc=0.889 | direction=pos
- best_lag_h | auc=0.667 | direction=pos
- max_corr_dAH_change | auc=0.667 | direction=pos
- candidate_high_info_ratio | auc=0.667 | direction=neg
- heat_related_ratio | auc=0.667 | direction=pos
- best_lag_rh_h | auc=0.556 | direction=pos

## 方向一致性

- lag_rh_unsealed_faster_in_old = `True`
- lag_rh_unsealed_faster_in_current = `False`
- gain_unsealed_higher_in_old = `True`
- gain_unsealed_higher_in_current = `True`

## 当前判断

- `dynamic response` 这条线在旧数据上更像“干扰识别线索”，而不是成熟主分类器。
- 在当前分工况小样本里，这些特征方向只有部分一致，还不足以替代现有主路线。
- 因此下一步最合理的定位是：把它做成 `interference/watch` 辅助探针，而不是立即升级为主判别分支。
