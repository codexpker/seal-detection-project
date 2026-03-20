from typing import Any, Callable, Dict, List, Optional

from src.anomaly_v2 import baseline as v2_baseline
from src.anomaly_v2 import state_machine as v2_state_machine


def run_v2_pipeline(
    *,
    dev_num: str,
    device_timestamp: int,
    points: List[Dict[str, Any]],
    runtime: Dict[str, Any],
    state_by_dev: Dict[str, Dict[str, Any]],
    refs_by_dev: Dict[str, List[Dict[str, float]]],
    save_score: Callable[[str, int, float, float, Dict[str, Any]], None],
    save_event: Callable[[Dict[str, Any]], None],
    default_enabled: bool,
    default_min_points: int,
    default_alpha: float,
    default_warn_threshold: float,
    default_recover_threshold: float,
    default_event_start_count: int,
    default_event_end_count: int,
    default_event_min_duration_sec: int,
    default_event_cooldown_sec: int,
    default_shadow_mode: bool,
) -> Optional[Dict[str, Any]]:
    enabled = bool(runtime.get("enabled", default_enabled))
    if not enabled:
        return None

    min_points = int(runtime.get("min_points", default_min_points))
    features = v2_baseline.compute_features(points, min_points)
    if not features:
        return None

    alpha = float(runtime.get("alpha", default_alpha))
    warn_threshold = float(runtime.get("warn_threshold", default_warn_threshold))
    recover_threshold = float(runtime.get("recover_threshold", default_recover_threshold))
    event_start_count = int(runtime.get("event_start_count", default_event_start_count))
    event_end_count = int(runtime.get("event_end_count", default_event_end_count))
    event_min_duration_sec = int(runtime.get("event_min_duration_sec", default_event_min_duration_sec))
    event_cooldown_sec = int(runtime.get("event_cooldown_sec", default_event_cooldown_sec))
    shadow_mode = bool(runtime.get("shadow_mode", default_shadow_mode))

    score_stat = v2_baseline.compute_stat_score(points, features)
    sim_enabled = bool(runtime.get("sim_enabled", False))
    sim_weight = float(runtime.get("sim_weight", 0.3))
    sim_k = int(runtime.get("sim_k", 5))

    window_vec = v2_baseline.compute_window_vector(points, features)
    sim_meta = (
        v2_baseline.compute_similarity_score(refs_by_dev, dev_num, window_vec, sim_k)
        if sim_enabled
        else {
            "score_sim": 0.0,
            "sim_topk_dist_mean": 0.0,
            "sim_reference_count": float(len(refs_by_dev.get(dev_num, []))),
        }
    )

    score_sim = float(sim_meta.get("score_sim", 0.0))
    score_raw = v2_baseline.fuse_scores(score_stat, score_sim, sim_enabled, sim_weight)

    state = state_by_dev.get(dev_num, {})
    prev_smooth = float(state.get("score_smooth", score_raw))
    score_smooth = (alpha * score_raw) + ((1 - alpha) * prev_smooth)

    # 先写回当前平滑分，避免 state_machine 读取旧 score_smooth 导致 in_event 分支丢失
    state_for_machine = dict(state)
    state_for_machine["score_smooth"] = score_smooth

    features_to_save = dict(features)
    features_to_save.update(
        {
            "score_stat": score_stat,
            "score_sim": score_sim,
            "score_final": score_raw,
            "sim_enabled": sim_enabled,
            "sim_weight": max(0.0, min(1.0, sim_weight if sim_enabled else 0.0)),
            "sim_k": sim_k,
            "sim_topk_dist_mean": float(sim_meta.get("sim_topk_dist_mean", 0.0)),
            "sim_reference_count": float(sim_meta.get("sim_reference_count", 0.0)),
        }
    )

    save_score(dev_num, device_timestamp, score_raw, score_smooth, features_to_save)

    state_before = {
        "in_event": bool(state_for_machine.get("in_event", False)),
        "above_warn_count": int(state_for_machine.get("above_warn_count", 0)),
        "below_recover_count": int(state_for_machine.get("below_recover_count", 0)),
        "event_start_ts": int(state_for_machine.get("event_start_ts", 0)),
    }

    new_state, event_record = v2_state_machine.update_event_state(
        dev_num=dev_num,
        device_timestamp=device_timestamp,
        score_smooth=score_smooth,
        state=state_for_machine,
        warn_threshold=warn_threshold,
        recover_threshold=recover_threshold,
        event_start_count=event_start_count,
        event_end_count=event_end_count,
        event_min_duration_sec=event_min_duration_sec,
        event_cooldown_sec=event_cooldown_sec,
        shadow_mode=shadow_mode,
    )
    state_by_dev[dev_num] = new_state

    if event_record:
        save_event(event_record)

    debug_trace = bool(runtime.get("debug_trace", False))
    debug_info = None
    if debug_trace:
        debug_info = {
            "dev_num": dev_num,
            "device_timestamp": device_timestamp,
            "score_raw": score_raw,
            "score_smooth": score_smooth,
            "state_before": state_before,
            "state_after": {
                "in_event": bool(new_state.get("in_event", False)),
                "above_warn_count": int(new_state.get("above_warn_count", 0)),
                "below_recover_count": int(new_state.get("below_recover_count", 0)),
                "event_start_ts": int(new_state.get("event_start_ts", 0)),
                "last_event_end_ts": int(new_state.get("last_event_end_ts", 0)),
            },
            "event_record_generated": event_record is not None,
            "event_id": event_record.get("event_id") if event_record else None,
        }

    return {
        "enabled": True,
        "shadow_mode": shadow_mode,
        "score_raw": score_raw,
        "score_smooth": score_smooth,
        "score_stat": score_stat,
        "score_sim": score_sim,
        "sim_enabled": sim_enabled,
        "features": features_to_save,
        "event": event_record,
        "debug": debug_info,
    }
