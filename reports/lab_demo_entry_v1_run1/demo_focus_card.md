## 2026-03-04 163909_unseal_unheated

- final_status: `static_dynamic_supported_alert`
- risk_level: `high`
- primary_evidence: `threshold+similarity+multiview`
- dominant_route_role: `static_threshold_favored`
- primary_segment_id: `S001`
- needs_review: `True`
- notes: `threshold_pred=1 | similarity_pred=1 | dynamic_vote_count=5 | hard_case_ratio=1.091 | dynamic support agrees with static alert`

### 主证据段

- branch: `static_threshold_branch`
- role: `static_threshold_favored`
- start_time: `2026-03-04 16:00:00`
- end_time: `2026-03-05 15:00:00`
- n_windows: `12`
- mean_info_score_v2: `0.852`
- max_info_score_v2: `1.433`
- mean_transition_score: `0.000`
- mean_delta_half_dAH: `0.111`

### Static Multiview

- dynamic_vote_count: `5/6`
- dynamic_support: `True`
- dynamic_hit_features: `corr_out_hum_in_hum,max_corr_outRH_inRH_change,frac_threshold_favored,frac_pos_delta_half_dAH,q90_delta_half_dAH_w`
- hard_case_watch: `False`
- hard_case_ratio: `1.091`
- nearest_other_file: `2026-03-06 160246_seal_unheated`
- nearest_other_distance: `1.867`
