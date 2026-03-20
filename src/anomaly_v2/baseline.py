from statistics import median
from typing import Any, Dict, List, Optional


def safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def compute_features(points: List[Dict[str, Any]], min_points: int) -> Optional[Dict[str, Any]]:
    if len(points) < min_points:
        return None

    latest = points[-1]
    prev = points[-2]

    t_in = safe_float(latest.get("in_temp"))
    t_out = safe_float(latest.get("out_temp"))
    h_in = safe_float(latest.get("in_hum"))
    h_out = safe_float(latest.get("out_hum"))

    p_h_in = safe_float(prev.get("in_hum"))
    p_h_out = safe_float(prev.get("out_hum"))

    if None in (t_in, t_out, h_in, h_out, p_h_in, p_h_out):
        return None

    eps = 1e-6
    delta_t = t_in - t_out
    delta_h = h_in - h_out
    delta_h_prev = p_h_in - p_h_out

    dt = max(1.0, (int(latest.get("ts", 0)) - int(prev.get("ts", 0))) / 1000.0)
    slope_delta_h = (delta_h - delta_h_prev) / dt

    tail = points[-5:]
    tail_delta_h = []
    for p in tail:
        p_in = safe_float(p.get("in_hum"))
        p_out = safe_float(p.get("out_hum"))
        if p_in is None or p_out is None:
            continue
        tail_delta_h.append(p_in - p_out)

    if len(tail_delta_h) < 2:
        return None

    tail_mean = sum(tail_delta_h) / len(tail_delta_h)
    vol_5 = (sum((x - tail_mean) ** 2 for x in tail_delta_h) / len(tail_delta_h)) ** 0.5

    return {
        "delta_t": delta_t,
        "delta_h": delta_h,
        "delta_h_norm": delta_h / (abs(h_out) + eps),
        "slope_delta_h": slope_delta_h,
        "vol_5": vol_5,
        "dt": dt,
    }


def robust_z_score(values: List[float], current: float) -> float:
    if not values:
        return 0.0
    med = median(values)
    abs_dev = [abs(v - med) for v in values]
    mad = median(abs_dev) if abs_dev else 0.0
    if mad < 1e-9:
        return 0.0
    z = 0.6745 * (current - med) / mad
    return abs(float(z))


def compute_stat_score(points: List[Dict[str, Any]], features: Dict[str, Any]) -> float:
    keys = ["delta_h", "delta_h_norm", "slope_delta_h", "vol_5"]
    z_list: List[float] = []
    for key in keys:
        history: List[float] = []
        for p in points[:-1]:
            if key == "delta_h":
                p_in = safe_float(p.get("in_hum"))
                p_out = safe_float(p.get("out_hum"))
                if p_in is None or p_out is None:
                    continue
                history.append(p_in - p_out)
            elif key == "delta_h_norm":
                p_in = safe_float(p.get("in_hum"))
                p_out = safe_float(p.get("out_hum"))
                if p_in is None or p_out is None:
                    continue
                history.append((p_in - p_out) / (abs(p_out) + 1e-6))

        current = safe_float(features.get(key))
        if current is None:
            continue

        if key in ("slope_delta_h", "vol_5"):
            history = []
            for idx in range(1, len(points) - 1):
                a = points[idx]
                b = points[idx - 1]
                a_in = safe_float(a.get("in_hum"))
                a_out = safe_float(a.get("out_hum"))
                b_in = safe_float(b.get("in_hum"))
                b_out = safe_float(b.get("out_hum"))
                if None in (a_in, a_out, b_in, b_out):
                    continue
                delta_a = a_in - a_out
                delta_b = b_in - b_out
                dt = max(1.0, (int(a.get("ts", 0)) - int(b.get("ts", 0))) / 1000.0)
                slope = (delta_a - delta_b) / dt
                if key == "slope_delta_h":
                    history.append(slope)
            if key == "vol_5":
                for idx in range(4, len(points) - 1):
                    vals = []
                    for p in points[idx - 4 : idx + 1]:
                        p_in = safe_float(p.get("in_hum"))
                        p_out = safe_float(p.get("out_hum"))
                        if p_in is None or p_out is None:
                            continue
                        vals.append(p_in - p_out)
                    if len(vals) >= 2:
                        m = sum(vals) / len(vals)
                        history.append((sum((x - m) ** 2 for x in vals) / len(vals)) ** 0.5)

        if history:
            z_list.append(robust_z_score(history, current))

    if not z_list:
        return 0.0
    score_raw = sum(z_list) / len(z_list)
    return max(0.0, min(1.0, score_raw / 8.0))


def compute_window_vector(points: List[Dict[str, Any]], features: Dict[str, Any]) -> Optional[Dict[str, float]]:
    if len(points) < 5:
        return None

    delta_h_vals: List[float] = []
    delta_t_vals: List[float] = []
    for p in points:
        in_h = safe_float(p.get("in_hum"))
        out_h = safe_float(p.get("out_hum"))
        in_t = safe_float(p.get("in_temp"))
        out_t = safe_float(p.get("out_temp"))
        if None in (in_h, out_h, in_t, out_t):
            continue
        delta_h_vals.append(float(in_h - out_h))
        delta_t_vals.append(float(in_t - out_t))

    if len(delta_h_vals) < 5 or len(delta_t_vals) < 5:
        return None

    m_dh = sum(delta_h_vals) / len(delta_h_vals)
    std_dh = (sum((x - m_dh) ** 2 for x in delta_h_vals) / len(delta_h_vals)) ** 0.5
    m_dt = sum(delta_t_vals) / len(delta_t_vals)
    slope = float(features.get("slope_delta_h", 0.0))
    vol_5 = float(features.get("vol_5", 0.0))

    return {
        "mean_delta_h": m_dh,
        "std_delta_h": std_dh,
        "mean_delta_t": m_dt,
        "slope_delta_h": slope,
        "vol_5_mean": vol_5,
    }


def _window_distance(a: Dict[str, float], b: Dict[str, float]) -> float:
    keys = ["mean_delta_h", "std_delta_h", "mean_delta_t", "slope_delta_h", "vol_5_mean"]
    return sum((float(a.get(k, 0.0)) - float(b.get(k, 0.0))) ** 2 for k in keys) ** 0.5


def compute_similarity_score(
    refs_by_dev: Dict[str, List[Dict[str, float]]],
    dev_num: str,
    window_vec: Optional[Dict[str, float]],
    sim_k: int,
) -> Dict[str, float]:
    if not window_vec:
        return {"score_sim": 0.0, "sim_topk_dist_mean": 0.0, "sim_reference_count": 0.0}

    refs = refs_by_dev.setdefault(dev_num, [])
    if len(refs) < max(10, sim_k):
        refs.append(window_vec)
        if len(refs) > 2000:
            del refs[0 : len(refs) - 2000]
        return {"score_sim": 0.0, "sim_topk_dist_mean": 0.0, "sim_reference_count": float(len(refs))}

    distances = sorted(_window_distance(window_vec, r) for r in refs)
    k = max(1, min(sim_k, len(distances)))
    topk = distances[:k]
    d_mean = sum(topk) / len(topk)
    scale_idx = max(0, min(len(distances) - 1, int(0.9 * (len(distances) - 1))))
    d_scale = max(1e-6, distances[scale_idx])
    score_sim = max(0.0, min(1.0, d_mean / d_scale))

    refs.append(window_vec)
    if len(refs) > 2000:
        del refs[0 : len(refs) - 2000]

    return {
        "score_sim": float(score_sim),
        "sim_topk_dist_mean": float(d_mean),
        "sim_reference_count": float(len(refs)),
    }


def fuse_scores(score_stat: float, score_sim: float, sim_enabled: bool, sim_weight: float) -> float:
    w = max(0.0, min(1.0, sim_weight if sim_enabled else 0.0))
    return max(0.0, min(1.0, (1.0 - w) * score_stat + w * score_sim))
