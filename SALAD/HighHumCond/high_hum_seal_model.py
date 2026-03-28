import numpy as np
import pandas as pd


def moving_average(x, win=5):
    x = np.asarray(x, dtype=float)
    if win <= 1 or len(x) < 3:
        return x.copy()
    return pd.Series(x).rolling(window=win, min_periods=1, center=True).mean().values


def downsample_mean(x, factor=10):
    x = np.asarray(x, dtype=float)
    if factor <= 1 or len(x) < factor:
        return x.copy()

    n = len(x) // factor
    if n == 0:
        return x.copy()

    x_cut = x[:n * factor]
    x_ds = x_cut.reshape(n, factor).mean(axis=1)
    return x_ds


def calc_slope(x):
    x = np.asarray(x, dtype=float)
    if len(x) < 2:
        return 0.0
    t = np.arange(len(x))
    return float(np.polyfit(t, x, 1)[0])


def calc_cum_rise(x):
    x = np.asarray(x, dtype=float)
    if len(x) < 2:
        return 0.0
    diff = np.diff(x)
    return float(np.sum(diff[diff > 0]))


def max_rise_run(x):
    x = np.asarray(x, dtype=float)
    if len(x) < 2:
        return 0

    diff = np.diff(x)
    max_run = 0
    cur_run = 0
    for d in diff:
        if d > 0:
            cur_run += 1
            max_run = max(max_run, cur_run)
        else:
            cur_run = 0
    return int(max_run)


def calc_forward_rise(x):
    x = np.asarray(x, dtype=float)
    if len(x) < 2:
        return 0.0

    min_val = x[0]
    max_rise = 0.0
    for v in x:
        if v < min_val:
            min_val = v
        rise = v - min_val
        if rise > max_rise:
            max_rise = rise
    return float(max_rise)


def calc_forward_drop(x):
    x = np.asarray(x, dtype=float)
    if len(x) < 2:
        return 0.0

    max_val = x[0]
    max_drop = 0.0
    for v in x:
        if v > max_val:
            max_val = v
        drop = max_val - v
        if drop > max_drop:
            max_drop = drop
    return float(max_drop)


def split_subwindows(x, sub_size=36, step=12):
    x = np.asarray(x, dtype=float)
    n = len(x)

    subwins = []
    for start in range(0, n - sub_size + 1, step):
        end = start + sub_size
        subwins.append((start, end, x[start:end]))

    if len(subwins) == 0 and n >= 2:
        subwins.append((0, n, x.copy()))

    return subwins


def is_rising_subwindow(
    sub_x,
    t_sub_net=0.10,
    t_sub_slope=0.002,
    t_sub_rise_ratio=0.60,
    t_sub_cum_rise=0.15,
    t_sub_forward_rise=0.12
):
    sub_x = np.asarray(sub_x, dtype=float)

    if len(sub_x) < 5:
        return False, {}

    diff = np.diff(sub_x)
    net_change = float(sub_x[-1] - sub_x[0])
    slope = calc_slope(sub_x)
    rise_ratio = float(np.mean(diff > 0)) if len(diff) > 0 else 0.0
    cum_rise = calc_cum_rise(sub_x)
    forward_rise = calc_forward_rise(sub_x)
    forward_drop = calc_forward_drop(sub_x)

    rising = (
        ((net_change > t_sub_net) and (slope > t_sub_slope)) or
        ((rise_ratio > t_sub_rise_ratio) and (cum_rise > t_sub_cum_rise)) or
        (forward_rise > t_sub_forward_rise and forward_rise > forward_drop)
    )

    feats = {
        "sub_net_change": net_change,
        "sub_slope": slope,
        "sub_rise_ratio": rise_ratio,
        "sub_cum_rise": cum_rise,
        "sub_forward_rise": forward_rise,
        "sub_forward_drop": forward_drop,
        "sub_is_rising": int(rising)
    }
    return rising, feats


def extract_window_rising_evidence(ah_in_ds, sub_size=36, step=12):
    ah_in_ds = np.asarray(ah_in_ds, dtype=float)
    n = len(ah_in_ds)

    if n < 5:
        return {
            "n_points_ds": n,
            "n_subwins": 0,
            "n_rising_subwins": 0,
            "rising_subwin_ratio": 0.0,
            "net_change_in": 0.0,
            "slope_in": 0.0,
            "rise_ratio_in": 0.0,
            "cum_rise_in": 0.0,
            "max_rise_run_in": 0,
            "max_sub_slope_in": 0.0,
            "mean_rising_sub_slope": 0.0,
            "max_rising_sub_cum_rise": 0.0,
            "forward_rise_in": 0.0,
            "forward_drop_in": 0.0,
            "has_rising_segment": 0
        }

    diff = np.diff(ah_in_ds)
    net_change = float(ah_in_ds[-1] - ah_in_ds[0])
    slope = calc_slope(ah_in_ds)
    rise_ratio = float(np.mean(diff > 0)) if len(diff) > 0 else 0.0
    cum_rise = calc_cum_rise(ah_in_ds)
    rise_run = max_rise_run(ah_in_ds)
    forward_rise = calc_forward_rise(ah_in_ds)
    forward_drop = calc_forward_drop(ah_in_ds)

    subwins = split_subwindows(ah_in_ds, sub_size=sub_size, step=step)

    n_subwins = len(subwins)
    n_rising_subwins = 0
    sub_slopes = []
    rising_sub_slopes = []
    rising_sub_cum_rises = []

    for _, _, sub_x in subwins:
        sub_slope = calc_slope(sub_x)
        sub_slopes.append(sub_slope)

        rising, sub_feats = is_rising_subwindow(sub_x)
        if rising:
            n_rising_subwins += 1
            rising_sub_slopes.append(sub_feats["sub_slope"])
            rising_sub_cum_rises.append(sub_feats["sub_cum_rise"])

    max_sub_slope = float(np.max(sub_slopes)) if len(sub_slopes) > 0 else 0.0
    mean_rising_sub_slope = float(np.mean(rising_sub_slopes)) if len(rising_sub_slopes) > 0 else 0.0
    max_rising_sub_cum_rise = float(np.max(rising_sub_cum_rises)) if len(rising_sub_cum_rises) > 0 else 0.0
    rising_subwin_ratio = float(n_rising_subwins / n_subwins) if n_subwins > 0 else 0.0

    return {
        "n_points_ds": n,
        "n_subwins": n_subwins,
        "n_rising_subwins": n_rising_subwins,
        "rising_subwin_ratio": rising_subwin_ratio,
        "net_change_in": net_change,
        "slope_in": slope,
        "rise_ratio_in": rise_ratio,
        "cum_rise_in": cum_rise,
        "max_rise_run_in": rise_run,
        "max_sub_slope_in": max_sub_slope,
        "mean_rising_sub_slope": mean_rising_sub_slope,
        "max_rising_sub_cum_rise": max_rising_sub_cum_rise,
        "forward_rise_in": forward_rise,
        "forward_drop_in": forward_drop,
        "has_rising_segment": int(n_rising_subwins > 0)
    }


def classify_window_seal_state(
    feats,
    t_n_rising_subwins=2,
    t_cum_rise=0.45,
    t_max_sub_slope=0.003,
    t_rise_run=12,
    t_forward_rise=0.25,
    t_net_change=0.25,
    score_threshold=3
):
    if feats["n_rising_subwins"] == 0:
        feats_out = feats.copy()
        feats_out["seal_score"] = 0
        feats_out["reason"] = "no_rising_subwindow"
        return "SEALED", feats_out

    if feats["forward_drop_in"] > feats["forward_rise_in"] * 1.2 and feats["net_change_in"] <= 0:
        feats_out = feats.copy()
        feats_out["seal_score"] = 0
        feats_out["reason"] = "falling_dominates"
        return "SEALED", feats_out

    hit_n_rising_subwins = feats["n_rising_subwins"] >= t_n_rising_subwins
    hit_cum_rise = feats["cum_rise_in"] >= t_cum_rise
    hit_max_sub_slope = feats["max_sub_slope_in"] >= t_max_sub_slope
    hit_rise_run = feats["max_rise_run_in"] >= t_rise_run
    hit_forward_rise = (
        feats["forward_rise_in"] >= t_forward_rise and
        feats["forward_rise_in"] > feats["forward_drop_in"] * 0.8
    )
    hit_net_change = feats["net_change_in"] >= t_net_change

    score = (
        int(hit_n_rising_subwins) +
        int(hit_cum_rise) +
        int(hit_max_sub_slope) +
        int(hit_rise_run) +
        int(hit_forward_rise) +
        int(hit_net_change)
    )

    label = "UNSEALED" if score >= score_threshold else "SEALED"

    feats_out = feats.copy()
    feats_out["seal_score"] = score
    feats_out["reason"] = "score_rule"
    feats_out["hit_n_rising_subwins"] = int(hit_n_rising_subwins)
    feats_out["hit_cum_rise"] = int(hit_cum_rise)
    feats_out["hit_max_sub_slope"] = int(hit_max_sub_slope)
    feats_out["hit_rise_run"] = int(hit_rise_run)
    feats_out["hit_forward_rise"] = int(hit_forward_rise)
    feats_out["hit_net_change"] = int(hit_net_change)

    return label, feats_out


def predict_seal_state(
    window_df,
    smooth_win=5,
    downsample_factor=10,
    sub_size=36,
    step=12,
    return_features=False
):
    """
    输入:
        window_df: DataFrame，至少包含 AH_in, AH_out 两列
    输出:
        'SEALED' 或 'UNSEALED'
    """
    required_cols = ["AH_in", "AH_out"]
    missing_cols = [c for c in required_cols if c not in window_df.columns]
    if missing_cols:
        raise ValueError(f"缺少列: {missing_cols}")

    df = window_df.copy()
    df = df.dropna(subset=["AH_in", "AH_out"])

    if len(df) < 10:
        label = "SEALED"
        feats = {"reason": "too_short"}
        return (label, feats) if return_features else label

    ah_in = df["AH_in"].values
    _ = df["AH_out"].values

    ah_in_smooth = moving_average(ah_in, win=smooth_win)
    ah_in_ds = downsample_mean(ah_in_smooth, factor=downsample_factor)

    feats = extract_window_rising_evidence(
        ah_in_ds=ah_in_ds,
        sub_size=sub_size,
        step=step
    )
    feats["n_points_raw"] = len(df)

    label, feats = classify_window_seal_state(feats)

    return (label, feats) if return_features else label