from typing import Any, Dict, Optional, Tuple


def update_event_state(
    dev_num: str,
    device_timestamp: int,
    score_smooth: float,
    state: Dict[str, Any],
    warn_threshold: float,
    recover_threshold: float,
    event_start_count: int,
    event_end_count: int,
    event_min_duration_sec: int,
    event_cooldown_sec: int,
    shadow_mode: bool,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    event_record = None

    in_event = bool(state.get("in_event", False))
    above_count = int(state.get("above_warn_count", 0))
    below_count = int(state.get("below_recover_count", 0))
    event_start_ts = int(state.get("event_start_ts", 0))
    event_peak_score = float(state.get("event_peak_score", 0.0))
    last_event_end_ts = int(state.get("last_event_end_ts", 0))

    cooldown_ok = True
    if last_event_end_ts > 0:
        cooldown_ok = (device_timestamp - last_event_end_ts) >= event_cooldown_sec * 1000

    if not in_event:
        if score_smooth >= warn_threshold:
            above_count += 1
        else:
            above_count = 0

        if cooldown_ok and above_count >= event_start_count:
            in_event = True
            event_start_ts = device_timestamp
            event_peak_score = score_smooth
            below_count = 0
            above_count = 0
    else:
        event_peak_score = max(event_peak_score, score_smooth)
        duration_sec = max(0, int((device_timestamp - event_start_ts) / 1000))

        # 进行中事件也持续落库快照，便于 Top-K 复核抽样
        if duration_sec >= event_min_duration_sec:
            event_level = "critical" if event_peak_score >= 0.8 else "warn"
            event_record = {
                "event_id": f"{dev_num}_{event_start_ts}",
                "dev_num": dev_num,
                "start_ts": event_start_ts,
                "end_ts": device_timestamp,
                "peak_score": event_peak_score,
                "duration_sec": duration_sec,
                "event_level": event_level,
                "decision_reason": "ewma_hysteresis_v2_ongoing",
                "shadow_mode": shadow_mode,
            }

        if score_smooth < recover_threshold:
            below_count += 1
        else:
            below_count = 0

        if below_count >= event_end_count:
            if duration_sec >= event_min_duration_sec:
                event_level = "critical" if event_peak_score >= 0.8 else "warn"
                event_record = {
                    "event_id": f"{dev_num}_{event_start_ts}",
                    "dev_num": dev_num,
                    "start_ts": event_start_ts,
                    "end_ts": device_timestamp,
                    "peak_score": event_peak_score,
                    "duration_sec": duration_sec,
                    "event_level": event_level,
                    "decision_reason": "ewma_hysteresis_v2_closed",
                    "shadow_mode": shadow_mode,
                }
                last_event_end_ts = device_timestamp
            in_event = False
            below_count = 0
            event_start_ts = 0
            event_peak_score = 0.0

    new_state = {
        "score_smooth": score_smooth,
        "in_event": in_event,
        "above_warn_count": above_count,
        "below_recover_count": below_count,
        "event_start_ts": event_start_ts,
        "event_peak_score": event_peak_score,
        "last_event_end_ts": last_event_end_ts,
    }
    return new_state, event_record
