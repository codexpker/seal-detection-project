# seal_v4 transition 个案调优记录 v1

## 样本

- 目标样本：`120165524_20260323-213435_seal_extHigh_intLow_noHeat_Change_20260324-9000_unseal.xlsx`
- 当前角色：`transition_primary_mainfield`
- 问题表现：整段 `post_change` 已被静态支线识别为 `positive_reference`，但旧版在线 `transition` 逻辑没有显式打出 `transition_boost_alert`

## 个案诊断

- 在变更点邻域 `2026-03-24 07:00 ~ 13:00`，该样本的 `delta_in_h` 持续抬升到 `0.55 ~ 0.59`
- 同期 `delta_ah_in` 已达到 `0.08 ~ 0.14`
- `headroom_ratio` 持续为 `1.0`
- 旧版 miss 的直接原因不是 `score` 不够，而是 `moderate_shape` 要求 `delta_in_h >= 0.6`，该样本长期停在门槛下方，属于“慢爬升 transition”

## 调优动作

- 保持原有 `strong_shape / moderate_shape` 不变
- 新增一个更保守的 `sustained_slow_shape`：
  - `delta_in_h >= 0.55`
  - `delta_ah_in >= 0.08`
  - `headroom_ratio >= 0.5`
  - `score >= 0.28`
  - 连续满足 `3` 个窗口后才升级成 `transition_boost_alert`

## 回归结果

- `new_data.zip` 的 transition 事件级对照：
  - `primary_before_any_hit = 2`
  - `primary_after_any_hit = 3`
  - `20260323-213435` 的 `transition_hit_delta = +11`
  - `secondary_before_any_hit = 0`
  - `secondary_after_any_hit = 0`
- `new_data.zip` 的最终尾窗分布没有被进一步放松，最终状态变化数量仍是 `3`
- 旧数据侧额外做了真实分支口径回归：
  - `old_data/sealed.zip` 未新增命中
  - `old_data/unsealed.zip` 未新增命中

## 当前结论

- 这次补丁不是回滚“保守尾窗”，而是只给 `20260323` 这类慢爬升主战场 transition 补了一个事件级出口
- 当前在线模型更准确的理解是：
  - 尾窗仍然保守
  - `181049` 这类 guarded positive 仍会被压回 `watch`
  - 主战场 transition 从 `2/3` 补到了 `3/3`
