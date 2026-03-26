## 2026-03-06 160246_seal_unheated

- final_status: `static_hard_case_watch`
- risk_level: `watch`
- primary_evidence: `hard_case_multiview`
- dominant_route_role: `static_threshold_favored`
- primary_segment_id: `S001`
- needs_review: `True`
- notes: `threshold_pred=0 | similarity_pred=1 | dynamic_vote_count=5 | hard_case_ratio=0.547 | hard case watch overrides static alerting`

### 主证据段

- branch: `static_threshold_branch`
- role: `static_threshold_favored`
- start_time: `2026-03-06 16:00:00`
- end_time: `2026-03-07 18:00:00`
- n_windows: `15`
- mean_info_score_v2: `1.313`
- max_info_score_v2: `2.376`
- mean_transition_score: `0.000`
- mean_delta_half_dAH: `0.241`

### Static Multiview

- dynamic_vote_count: `5/6`
- dynamic_support: `True`
- dynamic_hit_features: `corr_out_hum_in_hum,max_corr_outRH_inRH_change,frac_threshold_favored,frac_pos_delta_half_dAH,q90_delta_half_dAH_w`
- hard_case_watch: `True`
- hard_case_ratio: `0.547`
- nearest_other_file: `2026-03-04 163909_unseal_unheated`
- nearest_other_distance: `3.770`

### 外部高湿响应 v2

- no_heat_status_v2: `ext_high_hum_no_heat_multiscale_breathing_watch`
- no_heat_rationale_v2: `long_scale_not_weaker_than_main | short_scale_more_spiky_than_main`
- no_heat_hits_2h_6h_12h: `5/5/5`
- no_heat_scores_2h_6h_12h: `0.404/0.265/0.464`

### 无热源高湿 Probe v3

- probe_status_v3: `ext_high_hum_no_heat_probe_breathing_watch`
- probe_rationale_v3: `late_persistence_with_low_ah_decay`
- onset_positive_v3: `True`
- late_persistence_v3: `True`
- breathing_bias_v3: `True`
- early_resp_ratio / early_rh_gain: `1.000 / 0.138`
- late_resp_ratio / late_rh_gain: `1.000 / 0.499`
- late_ah_decay_per_headroom: `-0.003`
