# 现场演示运行卡片

## 2026-03-02 161335_seal_unheated

- final_status: `static_abstain_low_signal`
- risk_level: `abstain`
- primary_evidence: `similarity_branch`
- dominant_route_role: `static_memory_candidate`
- primary_segment_id: `S001`
- needs_review: `False`
- notes: `threshold branch abstained | similarity_pred=0 | dynamic_vote_count=1 | hard_case_ratio=1.164 | no_heat_probe_v3=ext_high_hum_no_heat_probe_negative`

### 主证据段

- branch: `static_memory_branch`
- role: `static_memory_candidate`
- start_time: `2026-03-02 16:00:00`
- end_time: `2026-03-03 10:00:00`
- n_windows: `7`
- mean_info_score_v2: `0.294`
- max_info_score_v2: `0.756`
- mean_transition_score: `0.000`
- mean_delta_half_dAH: `-0.115`

### Static Multiview

- dynamic_vote_count: `1/6`
- dynamic_support: `False`
- dynamic_hit_features: `std_in_hum_run`
- hard_case_watch: `False`
- hard_case_ratio: `1.164`
- nearest_other_file: `2026-03-22 150919_unseal_unheated`
- nearest_other_distance: `5.179`

### 外部高湿响应 v2

- no_heat_status_v2: `ext_high_hum_no_heat_multiscale_negative`
- no_heat_rationale_v2: `main_and_long_low_signal`
- no_heat_hits_2h_6h_12h: `0/0/0`
- no_heat_scores_2h_6h_12h: `0.000/0.000/0.000`

### 无热源高湿 Probe v3

- probe_status_v3: `ext_high_hum_no_heat_probe_negative`
- probe_rationale_v3: `early_response_absent`
- onset_positive_v3: `False`
- late_persistence_v3: `False`
- breathing_bias_v3: `False`
- early_resp_ratio / early_rh_gain: `0.000 / -0.184`
- late_resp_ratio / late_rh_gain: `0.000 / -0.170`
- late_ah_decay_per_headroom: `-0.025`

## 2026-03-03 181049_unseal_unheated

- final_status: `static_dynamic_supported_alert`
- risk_level: `high`
- primary_evidence: `multiview_support+no_heat_probe`
- dominant_route_role: `static_memory_candidate`
- primary_segment_id: `S002`
- needs_review: `True`
- notes: `threshold_pred=0 | similarity_pred=0 | dynamic_vote_count=4 | hard_case_ratio=0.863 | multiview support recovers static miss | no_heat_probe_v3=ext_high_hum_no_heat_probe_supported | no_heat probe corroborates multiview-supported static alert`

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

### 无热源高湿 Probe v3

- probe_status_v3: `ext_high_hum_no_heat_probe_supported`
- probe_rationale_v3: `early_response_present_without_persistent_breathing_pattern`
- onset_positive_v3: `True`
- late_persistence_v3: `False`
- breathing_bias_v3: `False`
- early_resp_ratio / early_rh_gain: `1.000 / 0.181`
- late_resp_ratio / late_rh_gain: `1.000 / 0.400`
- late_ah_decay_per_headroom: `-0.013`

## 2026-03-06 160246_seal_unheated

- final_status: `static_hard_case_watch`
- risk_level: `watch`
- primary_evidence: `hard_case_multiview`
- dominant_route_role: `static_threshold_favored`
- primary_segment_id: `S001`
- needs_review: `True`
- notes: `threshold_pred=0 | similarity_pred=1 | dynamic_vote_count=5 | hard_case_ratio=0.547 | hard case watch overrides static alerting | no_heat_probe_v3=ext_high_hum_no_heat_probe_breathing_watch`

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

## 2026-03-04 120007_seal_unheated-2026-03-04 163909_unseal_unheated

- final_status: `transition_boost_alert`
- risk_level: `high`
- primary_evidence: `transition_branch+multiview`
- dominant_route_role: `transition_context`
- primary_segment_id: `S001`
- needs_review: `True`
- notes: `transition boost features=delta_in_hum,delta_half_in_hum,max_hourly_hum_rise,std_out_hum,corr_AH | transition evidence passed | transition_boost_count=5`

### 主证据段

- branch: `transition_branch`
- role: `transition_core`
- start_time: `2026-03-04 12:00:00`
- end_time: `2026-03-05 04:00:00`
- n_windows: `5`
- mean_info_score_v2: `3.830`
- max_info_score_v2: `5.138`
- mean_transition_score: `3.830`
- mean_delta_half_dAH: `0.036`

### Transition Boost

- transition_boost: `True`
- transition_boost_count: `5`
- transition_boost_features: `delta_in_hum,delta_half_in_hum,max_hourly_hum_rise,std_out_hum,corr_AH`

### Transition Event

- event_start: `2026-03-04 12:00:00`
- event_end: `2026-03-05 08:00:00`
- event_duration_h: `20.000`
- peak_time: `2026-03-04 12:00:00`
- peak_phase: `near_transition`
- peak_smooth_score_v3: `4.612`
- upper_threshold: `1.956`
- lower_threshold: `0.782`

## 2026-03-08 172014_seal_unheated

- final_status: `transition_boost_alert`
- risk_level: `high`
- primary_evidence: `transition_branch+multiview`
- dominant_route_role: `transition_context`
- primary_segment_id: `S002`
- needs_review: `True`
- notes: `transition boost features=delta_in_hum,delta_half_in_hum,max_hourly_hum_rise,corr_AH | transition evidence passed | transition_boost_count=4`

### 主证据段

- branch: `transition_branch`
- role: `transition_core`
- start_time: `2026-03-09 22:00:00`
- end_time: `2026-03-10 22:00:00`
- n_windows: `13`
- mean_info_score_v2: `1.968`
- max_info_score_v2: `2.726`
- mean_transition_score: `1.968`
- mean_delta_half_dAH: `0.008`

### Transition Boost

- transition_boost: `True`
- transition_boost_count: `4`
- transition_boost_features: `delta_in_hum,delta_half_in_hum,max_hourly_hum_rise,corr_AH`

### Transition Event

- event_start: `2026-03-09 23:00:00`
- event_end: `2026-03-11 19:00:00`
- event_duration_h: `44.000`
- peak_time: `2026-03-10 08:00:00`
- peak_phase: `near_transition`
- peak_smooth_score_v3: `2.687`
- upper_threshold: `0.912`
- lower_threshold: `0.365`

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

## 2026-03-22 150919_unseal_unheated

- final_status: `static_dynamic_supported_alert`
- risk_level: `high`
- primary_evidence: `threshold+similarity+multiview`
- dominant_route_role: `static_threshold_favored`
- primary_segment_id: `S002`
- needs_review: `True`
- notes: `threshold_pred=1 | similarity_pred=1 | dynamic_vote_count=5 | hard_case_ratio=1.745 | dynamic support agrees with static alert`

### 主证据段

- branch: `static_memory_branch`
- role: `static_memory_candidate`
- start_time: `2026-03-23 04:00:00`
- end_time: `2026-03-23 18:00:00`
- n_windows: `3`
- mean_info_score_v2: `0.465`
- max_info_score_v2: `0.521`
- mean_transition_score: `0.000`
- mean_delta_half_dAH: `-0.062`

### Static Multiview

- dynamic_vote_count: `5/6`
- dynamic_support: `True`
- dynamic_hit_features: `corr_out_hum_in_hum,frac_threshold_favored,frac_pos_delta_half_dAH,q90_delta_half_dAH_w,std_in_hum_run`
- hard_case_watch: `False`
- hard_case_ratio: `1.745`
- nearest_other_file: `2026-03-06 160246_seal_unheated`
- nearest_other_distance: `2.831`
