## 2026-03-03 181049_unseal_unheated

- final_status: `static_dynamic_support_alert`
- risk_level: `medium`
- primary_evidence: `multiview_support`
- dominant_route_role: `static_memory_candidate`
- primary_segment_id: `S002`
- needs_review: `True`
- notes: `threshold_pred=0 | similarity_pred=0 | dynamic_vote_count=4 | hard_case_ratio=0.863 | multiview support recovers static miss`

### 主证据段

- branch: `static_memory_branch`
- role: `static_memory_candidate`
- start_time: `2026-03-03 19:00:00`
- end_time: `2026-03-04 08:00:00`
- n_windows: `2`
- mean_info_score_v2: `0.770`
- max_info_score_v2: `1.375`
- mean_transition_score: `0.000`
- mean_delta_half_dAH: `-0.090`

### Static Multiview

- dynamic_vote_count: `4/6`
- dynamic_support: `True`
- dynamic_hit_features: `corr_out_hum_in_hum,max_corr_outRH_inRH_change,q90_delta_half_dAH_w,std_in_hum_run`
- hard_case_watch: `False`
- hard_case_ratio: `0.863`
- nearest_other_file: `2026-03-23 213435_seal_unheated`
- nearest_other_distance: `5.601`

### 外部高湿响应 v2

- no_heat_status_v2: `ext_high_hum_no_heat_multiscale_supported`
- no_heat_rationale_v2: `main_scale_stronger_than_long_scale | short_window_confirms_local_response`
- no_heat_hits_2h_6h_12h: `6/6/5`
- no_heat_scores_2h_6h_12h: `0.371/0.506/0.371`
