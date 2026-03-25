# 历史旧数据干扰回归测试卡片

## 2026-01-04 165808

- subgroup: `sealed_strict`
- demo_final_status: `strict_sealed_interference_watch`
- demo_risk_level: `watch`
- rationale: `strict sealed but candidate_high_info_ratio is high | RH response is relatively fast | absolute-humidity gain is relatively high`

### 关键特征

- candidate_high_info_ratio: `0.922`
- best_lag_rh_h: `1.000`
- best_lag_h: `1.000`
- gain_ratio_dAH_change: `1.149`
- max_corr_outRH_inRH_change: `0.732`
- heat_related_ratio: `0.031`

## 2025-12-15 230921

- subgroup: `sealed_strict`
- demo_final_status: `strict_sealed_negative_control_safe`
- demo_risk_level: `safe`
- rationale: `strict sealed and no persistent high-info routing`

### 关键特征

- candidate_high_info_ratio: `0.500`
- best_lag_rh_h: `6.000`
- best_lag_h: `1.000`
- gain_ratio_dAH_change: `0.799`
- max_corr_outRH_inRH_change: `0.141`
- heat_related_ratio: `0.350`

## 2025-10-18 165216

- subgroup: `sealed_no_screw_grease`
- demo_final_status: `weak_seal_watch`
- demo_risk_level: `watch`
- rationale: `weak sealing subgroup should not be treated as strict negative control`

### 关键特征

- candidate_high_info_ratio: `0.429`
- best_lag_rh_h: `0.000`
- best_lag_h: `2.000`
- gain_ratio_dAH_change: `1.818`
- max_corr_outRH_inRH_change: `0.933`
- heat_related_ratio: `0.571`

## 2025-11-03 193657

- subgroup: `unsealed`
- demo_final_status: `challenge_positive_like`
- demo_risk_level: `high`
- rationale: `persistent high-info routing with fast response or high gain`

### 关键特征

- candidate_high_info_ratio: `1.000`
- best_lag_rh_h: `1.000`
- best_lag_h: `1.000`
- gain_ratio_dAH_change: `0.621`
- max_corr_outRH_inRH_change: `-0.628`
- heat_related_ratio: `0.000`
