# -*- coding: utf-8 -*-
"""
Created on Wed Mar 25 21:43:34 2026

@author: wang
"""

import pandas as pd
import numpy as np


def find_valid_tail_start(hum_values, hum_threshold=85.0):
    """
    查找有效起点：
    从该点开始到结束始终 > hum_threshold，
    如果中途掉到阈值以下，则从后面重新搜索。

    参数
    ----
    hum_values : array-like
        湿度序列
    hum_threshold : float
        湿度阈值

    返回
    ----
    int or None
        有效起点索引；若不存在则返回 None
    """
    hum_values = np.asarray(hum_values, dtype=float)
    n = len(hum_values)
    i = 0

    while i < n:
        while i < n and hum_values[i] <= hum_threshold:
            i += 1

        if i >= n:
            return None

        tail = hum_values[i:]
        bad_pos = np.where(tail <= hum_threshold)[0]

        if len(bad_pos) == 0:
            return i
        else:
            i = i + bad_pos[0] + 1

    return None


def detect_window_state(
    window_df: pd.DataFrame,
    time_col: str = "time",
    hum_col: str = "in_hum",
    hum_threshold: float = 85.0,
    min_duration_hours: float = 2.0
):
    """
    判定单个窗口状态：

    1. MOISTURE_ACCUMULATION
       整个窗口湿度都 > hum_threshold

    2. MOISTURE_INGRESS
       - 存在某个起点开始到窗口结束始终 > hum_threshold
       - 持续时间 >= min_duration_hours
       - 该尾段整体趋势上升（线性拟合斜率 > 0）
       表示当前窗口内仍在持续进湿

    3. SEALED
       未满足上述异常条件

    4. UNKNOWN
       数据异常或无法判断

    返回
    ----
    dict
        检测结果
    """
    result = {
        "state": "SEALED",
        "start_time_over_85": None,
        "end_time": None,
        "duration_hours": 0.0,
        "slope": None,
        "reason": ""
    }

    if window_df is None or len(window_df) == 0:
        result["state"] = "UNKNOWN"
        result["reason"] = "empty dataframe"
        return result

    df = window_df.copy()

    if time_col not in df.columns or hum_col not in df.columns:
        result["state"] = "UNKNOWN"
        result["reason"] = f"missing required columns: {time_col} or {hum_col}"
        return result

    df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
    df[hum_col] = pd.to_numeric(df[hum_col], errors="coerce")
    df = df.dropna(subset=[time_col, hum_col]).sort_values(time_col).reset_index(drop=True)

    if len(df) == 0:
        result["state"] = "UNKNOWN"
        result["reason"] = "no valid time or humidity data"
        return result

    hum = df[hum_col].to_numpy(dtype=float)

    # 1. 内部积湿：整个窗口都 > hum_threshold
    if np.all(hum > hum_threshold):
        result["state"] = "MOISTURE_ACCUMULATION"
        result["start_time_over_85"] = str(df[time_col].iloc[0])
        result["end_time"] = str(df[time_col].iloc[-1])
        result["duration_hours"] = round(
            (df[time_col].iloc[-1] - df[time_col].iloc[0]).total_seconds() / 3600.0, 3
        )
        result["reason"] = f"humidity remains above {hum_threshold}% throughout the whole window"
        return result

    # 2. 查找有效高湿尾段
    start_idx = find_valid_tail_start(hum, hum_threshold)

    if start_idx is None:
        result["state"] = "SEALED"
        result["reason"] = f"no valid tail segment stays above {hum_threshold}% until the end"
        return result

    tail_df = df.iloc[start_idx:].copy()
    tail_hum = tail_df[hum_col].to_numpy(dtype=float)

    start_time = tail_df[time_col].iloc[0]
    end_time = tail_df[time_col].iloc[-1]
    duration_hours = (end_time - start_time).total_seconds() / 3600.0

    result["start_time_over_85"] = str(start_time)
    result["end_time"] = str(end_time)
    result["duration_hours"] = round(duration_hours, 3)

    cond_keep_over_85 = np.all(tail_hum > hum_threshold)
    cond_duration = duration_hours >= min_duration_hours

    # 整体趋势判定：线性拟合斜率 > 0
    if len(tail_hum) >= 2:
        x = np.arange(len(tail_hum), dtype=float)
        slope = np.polyfit(x, tail_hum, 1)[0]
    else:
        slope = 0.0

    result["slope"] = float(slope)
    cond_rising = slope > 0

    if cond_keep_over_85 and cond_duration and cond_rising:
        result["state"] = "MOISTURE_INGRESS"
        result["reason"] = (
            f"from {start_time} to the end, humidity stays above {hum_threshold}%, "
            f"lasts at least {min_duration_hours} hours, and shows an increasing trend"
        )
        return result

    fail_reasons = []
    if not cond_keep_over_85:
        fail_reasons.append("humidity does not stay above threshold until the end")
    if not cond_duration:
        fail_reasons.append(f"duration is shorter than {min_duration_hours} hours")
    if not cond_rising:
        fail_reasons.append("humidity trend is not increasing")

    result["state"] = "SEALED"
    result["reason"] = "; ".join(fail_reasons) if fail_reasons else "no abnormal moisture ingress detected"
    return result