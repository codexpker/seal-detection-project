# -*- coding: utf-8 -*-
"""
test_salad_model.py

功能：
1. 读取 input.xlsx
2. 按24小时窗口、1小时步长滑动切分
3. 调用 salad_model_router.run_salad_model 逐窗口预测
4. 输出并保存结果
"""

import os
import math
import pandas as pd

from salad_model_router import run_salad_model, RouterConfig


def read_input_excel(file_path: str) -> pd.DataFrame:
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"文件不存在: {file_path}")

    df = pd.read_excel(file_path)

    required_cols = ["time", "in_temp", "in_hum", "out_temp", "out_hum"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"input.xlsx 缺少必要字段: {missing}")

    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df = df.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)

    for c in ["in_temp", "in_hum", "out_temp", "out_hum"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["in_temp", "in_hum", "out_temp", "out_hum"]).reset_index(drop=True)

    if df.empty:
        raise ValueError("有效数据为空。")

    return df


def infer_median_interval_seconds(df: pd.DataFrame) -> float:
    dt = df["time"].diff().dt.total_seconds().dropna()
    if len(dt) == 0:
        return 60.0
    return float(dt.median())


def pad_head_if_shorter_than_24h(df: pd.DataFrame, window_hours: int = 24) -> pd.DataFrame:
    """
    如果整段数据不足24小时，则在头部补齐。
    补齐的数据值与第一条记录相同，仅时间向前推。
    """
    if df.empty:
        return df

    first_time = df["time"].min()
    last_time = df["time"].max()
    span = last_time - first_time
    target_span = pd.Timedelta(hours=window_hours)

    if span >= target_span:
        return df

    interval_sec = max(infer_median_interval_seconds(df), 1.0)
    missing_sec = (target_span - span).total_seconds()
    n_pad = int(math.ceil(missing_sec / interval_sec))

    if n_pad <= 0:
        return df

    first_row = df.iloc[0].copy()
    pad_times = [
        first_time - pd.Timedelta(seconds=interval_sec * i)
        for i in range(n_pad, 0, -1)
    ]

    pad_df = pd.DataFrame([first_row.to_dict() for _ in range(n_pad)])
    pad_df["time"] = pad_times

    out = pd.concat([pad_df, df], ignore_index=True)
    out = out.sort_values("time").reset_index(drop=True)

    print(f"[INFO] 数据不足24小时，已在头部补齐 {n_pad} 条。")
    return out


def split_sliding_windows(
    df: pd.DataFrame,
    window_hours: int = 24,
    step_hours: int = 1,
    min_window_coverage_ratio: float = 0.6
):
    """
    按时间滑窗切分：
    - 窗口长度：24h
    - 步长：1h
    """
    start_time = df["time"].min()
    end_time = df["time"].max()

    window_delta = pd.Timedelta(hours=window_hours)
    step_delta = pd.Timedelta(hours=step_hours)

    interval_sec = max(infer_median_interval_seconds(df), 1.0)
    expected_count = max(1, int(window_delta.total_seconds() / interval_sec))
    min_count = max(1, int(expected_count * min_window_coverage_ratio))

    windows = []
    cur = start_time

    while cur + window_delta <= end_time:
        w_end = cur + window_delta
        wdf = df[(df["time"] >= cur) & (df["time"] < w_end)].copy()

        if len(wdf) >= min_count:
            windows.append((cur, w_end, wdf))

        cur += step_delta

    return windows


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    input_path = os.path.join(base_dir, "./test_data/internal_moist.xlsx")
    output_path = os.path.join(base_dir, "./test_output/window_result.xlsx")

    cfg = RouterConfig(
        enable_debug=True,
        smooth_win=5,
        downsample_factor=10,
        sub_size=36,
        step=12,
        time_col="time",
        hum_col="in_hum",
        hum_threshold=82.0,
        min_duration_hours=2.0
    )

    try:
        print(f"[INFO] 读取文件: {input_path}")
        df = read_input_excel(input_path)

        df = pad_head_if_shorter_than_24h(df, window_hours=24)

        windows = split_sliding_windows(
            df,
            window_hours=24,
            step_hours=1,
            min_window_coverage_ratio=0.6
        )

        if not windows:
            print("[WARN] 未生成有效24小时窗口。")
            return

        print(f"[INFO] 共生成 {len(windows)} 个窗口。")

        results = []

        for i, (w_start, w_end, wdf) in enumerate(windows, start=1):
            print(f"[INFO] 处理窗口 W{i:04d}: {w_start} ~ {w_end}")

            try:
                result = run_salad_model(wdf, cfg)

                row = {
                    "window_id": f"W{i:04d}",
                    "start_time": w_start,
                    "end_time": w_end,
                    "n_samples": len(wdf),
                    "condition": result["condition"],
                    "model": result["model"],
                    "label": result["label"],
                }

            except Exception as e:
                row = {
                    "window_id": f"W{i:04d}",
                    "start_time": w_start,
                    "end_time": w_end,
                    "n_samples": len(wdf),
                    "condition": "unknown",
                    "model": "unknown",
                    "label": "unknown",
                    "error": str(e),
                }

            results.append(row)

        result_df = pd.DataFrame(results)
        result_df.to_excel(output_path, index=False)

        print("\n=== 预测完成 ===")
        print(result_df[["window_id", "start_time", "end_time", "condition", "model", "label"]])
        print(f"\n结果已保存到: {output_path}")

    except Exception as e:
        print("[ERROR] 程序运行失败")
        print(str(e))


if __name__ == "__main__":
    main()