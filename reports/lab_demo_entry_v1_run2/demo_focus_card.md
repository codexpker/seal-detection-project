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
