# -*- coding: utf-8 -*-
"""
方案A：批量训练 + 批量评分

训练：按“完整文件”训练短上下文 GRU
评分：按“24h窗口（步长1h）”评分
"""
from __future__ import annotations

import argparse
import os
from typing import List

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch

from seal_model_core_v24a import (
    FEATURE_NAMES,
    GRUForecast,
    RobustScaler,
    attach_accumulation_metrics,
    build_features,
    compute_residual_series,
    df_to_scaled_array,
    fit_window_baseline,
    load_dir_as_series,
    load_model_bundle,
    make_24h_windows,
    read_timeseries,
    resample_df,
    save_json,
    set_seed,
    split_series_by_file,
    summarize_24h_window,
    train_model,
)


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def plot_history(history: dict, out_path: str) -> None:
    plt.figure()
    plt.plot(history["train"], label="train")
    if history.get("val"):
        plt.plot(history["val"], label="val")
    plt.xlabel("epoch")
    plt.ylabel("weighted_MAE")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()


def train_main(args) -> None:
    set_seed(args.seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[INFO] device={device}")

    ensure_dir(args.out_dir)
    model_dir = os.path.join(args.out_dir, "model")
    ensure_dir(model_dir)

    series = load_dir_as_series(
        dir_path=args.train_dir,
        time_col=args.time_col,
        rule=args.rule,
        smooth_ddah_window=args.smooth_ddah_window,
        csv_encoding=args.csv_encoding,
        min_points=args.min_points,
    )
    print(f"[INFO] 有效训练文件数: {len(series)}")

    train_series, val_series = split_series_by_file(series, val_ratio=args.val_ratio, seed=args.seed)
    print(f"[INFO] train files: {len(train_series)}, val files: {len(val_series)}")

    X_fit = np.concatenate([df[FEATURE_NAMES].to_numpy(dtype=np.float32) for _, df in train_series], axis=0)
    scaler = RobustScaler()
    scaler.fit(X_fit)

    train_arrays = [df_to_scaled_array(df, FEATURE_NAMES, scaler) for _, df in train_series]
    val_arrays = [df_to_scaled_array(df, FEATURE_NAMES, scaler) for _, df in val_series] if val_series else []

    history = train_model(
        train_arrays=train_arrays,
        val_arrays=val_arrays,
        feature_names=FEATURE_NAMES,
        out_dir=model_dir,
        W=args.W,
        H=args.H,
        stride=args.inner_stride,
        hidden=args.hidden,
        layers=args.layers,
        dropout=args.dropout,
        batch_size=args.batch_size,
        lr=args.lr,
        epochs=args.epochs,
        device=device,
        seed=args.seed,
    )
    plot_history(history, os.path.join(model_dir, "loss_curve.png"))

    model = GRUForecast(d_in=len(FEATURE_NAMES), hidden=args.hidden, num_layers=args.layers, H=args.H, dropout=args.dropout)
    model.load_state_dict(torch.load(os.path.join(model_dir, "best_model.pt"), map_location=device))
    model.to(device).eval()

    baseline = fit_window_baseline(
        model=model,
        train_arrays=train_arrays,
        feature_names=FEATURE_NAMES,
        W=args.W,
        H=args.H,
        stride=args.inner_stride,
        device=device,
        alpha=args.ewma_alpha,
        cusum_k=args.cusum_k,
    )

    save_json(scaler.to_dict(), os.path.join(model_dir, "scaler.json"))
    save_json(FEATURE_NAMES, os.path.join(model_dir, "feature_names.json"))
    save_json(baseline, os.path.join(model_dir, "window_baseline.json"))
    save_json({
        "W": args.W,
        "H": args.H,
        "inner_stride": args.inner_stride,
        "hidden": args.hidden,
        "layers": args.layers,
        "dropout": args.dropout,
        "rule": args.rule,
        "time_col": args.time_col,
        "smooth_ddah_window": args.smooth_ddah_window,
        "window_step_hours": args.window_step_hours,
    }, os.path.join(model_dir, "config.json"))
    print(f"[DONE] 训练完成，模型目录: {model_dir}")


def save_plot(score_df: pd.DataFrame, y_col: str, thr: float, out_path: str, title: str) -> None:
    plt.figure(figsize=(10, 4))
    plt.plot(score_df.index, score_df[y_col], label=y_col)
    plt.axhline(thr, linestyle="--", label="threshold")
    plt.xticks(rotation=45, ha="right")
    plt.title(title)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()


def score_windows_in_file(file_path: str, model, scaler, baseline, feature_names: List[str], config: dict, out_dir: str, csv_encoding=None):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    rule = config["rule"]
    time_col = config["time_col"]
    W = int(config["W"])
    H = int(config["H"])
    inner_stride = int(config["inner_stride"])
    smooth_ddah_window = int(config["smooth_ddah_window"])
    window_step_hours = int(config.get("window_step_hours", 1))
    rule_minutes = int(rule.replace("min", ""))

    df = read_timeseries(file_path, time_col=time_col, csv_encoding=csv_encoding)
    df = resample_df(df, rule=rule)
    df = build_features(df, rule_minutes=rule_minutes, smooth_ddah_window=smooth_ddah_window)
    windows = make_24h_windows(
        df,
        rule_minutes,
        window_hours=24,
        step_hours=window_step_hours,
        allow_short_last=True,
    )
    if not windows:
        raise RuntimeError("预处理后无可用窗口")

    base = os.path.splitext(os.path.basename(file_path))[0]
    file_dir = os.path.join(out_dir, base)
    ensure_dir(file_dir)

    summary_rows = []
    for idx, (start, end, sub) in enumerate(windows, start=1):
        seq = df_to_scaled_array(sub, feature_names, scaler)
    
        # 即使允许短窗口，也必须保证至少能形成一次 W->H 预测
        if len(seq) < (W + H + 1):
            print(
                f"[SKIP WINDOW] {os.path.basename(file_path)} | "
                f"window_{idx:03d} 长度不足，len={len(seq)} < {W + H + 1}"
            )
            continue
        score_df = compute_residual_series(model, seq, W, H, inner_stride, feature_names, device=device)
        score_df = attach_accumulation_metrics(
            score_df,
            resid_mean=baseline["resid_mean"],
            resid_std=baseline["resid_std"],
            alpha=baseline["alpha"],
            cusum_k=baseline["cusum_k"],
        )
        times = sub.index.to_list()
        score_df["time"] = score_df["pos"].apply(lambda p: times[int(p)] if int(p) < len(times) else times[-1])
        score_df = score_df.drop(columns=["pos"]).set_index("time")

        summary = summarize_24h_window(score_df, baseline)
        summary_rows.append({
            "file": os.path.basename(file_path),
            "window_id": idx,
            "window_start": str(start),
            "window_end": str(end),
            "window_points": len(sub),
            "window_hours_actual": len(sub) * rule_minutes / 60.0,
            "is_short_window": len(sub) < int(24 * 60 / rule_minutes),
            **summary,
        })

        csv_path = os.path.join(file_dir, f"window_{idx:03d}_scores.csv")
        score_df.to_csv(csv_path, encoding="utf-8-sig")
        save_json(summary, os.path.join(file_dir, f"window_{idx:03d}_summary.json"))

        save_plot(score_df, "score_dAH", baseline["thr_score_dAH"], os.path.join(file_dir, f"window_{idx:03d}_score_dAH.png"), f"{base} window {idx} dAH residual")
        save_plot(score_df, "ewma_abs", baseline["thr_ewma_abs"], os.path.join(file_dir, f"window_{idx:03d}_ewma_abs.png"), f"{base} window {idx} EWMA")
        save_plot(score_df, "cusum_abs", baseline["thr_cusum_abs"], os.path.join(file_dir, f"window_{idx:03d}_cusum_abs.png"), f"{base} window {idx} CUSUM")

    if not summary_rows:
        raise RuntimeError("窗口评分为空")

    df_summary = pd.DataFrame(summary_rows)
    df_summary.to_csv(os.path.join(file_dir, f"{base}_window_summary.csv"), index=False, encoding="utf-8-sig")
    return df_summary


def score_main(args) -> None:
    model, scaler, baseline, feature_names, config = load_model_bundle(args.model_dir)
    ensure_dir(args.out_dir)
    score_dir = os.path.join(args.out_dir, "scores")
    ensure_dir(score_dir)

    if os.path.isdir(args.test_path):
        files = []
        for pat in ["*.xlsx", "*.xls", "*.csv"]:
            files.extend(sorted([os.path.join(args.test_path, x) for x in os.listdir(args.test_path) if x.lower().endswith(pat[1:])]))
        # 简化去重
        files = sorted(set(files))
    else:
        files = [args.test_path]

    all_rows = []
    for fp in files:
        try:
            df_summary = score_windows_in_file(fp, model, scaler, baseline, feature_names, config, score_dir, csv_encoding=args.csv_encoding)
            all_rows.append(df_summary)
            abnormal_n = int((df_summary["status"] == "abnormal").sum())
            warning_n = int((df_summary["status"] == "warning").sum())
            print(f"[SCORED] {os.path.basename(fp)} | abnormal_windows={abnormal_n}, warning_windows={warning_n}")
        except Exception as e:
            print(f"[SKIP SCORE] {os.path.basename(fp)}: {e}")

    if all_rows:
        pd.concat(all_rows, axis=0, ignore_index=True).to_csv(os.path.join(score_dir, "all_window_summary.csv"), index=False, encoding="utf-8-sig")
    print(f"[DONE] 评分完成，输出目录: {score_dir}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)

    tr = sub.add_parser("train")
    tr.add_argument("--train_dir", type=str, required=True)
    tr.add_argument("--out_dir", type=str, default="./out_batch_v24a")
    tr.add_argument("--time_col", type=str, default="time")
    tr.add_argument("--rule", type=str, default="5min")
    tr.add_argument("--W", type=int, default=48)
    tr.add_argument("--H", type=int, default=6)
    tr.add_argument("--inner_stride", type=int, default=1)
    tr.add_argument("--window_step_hours", type=int, default=1)
    tr.add_argument("--hidden", type=int, default=64)
    tr.add_argument("--layers", type=int, default=2)
    tr.add_argument("--dropout", type=float, default=0.1)
    tr.add_argument("--batch_size", type=int, default=128)
    tr.add_argument("--lr", type=float, default=1e-3)
    tr.add_argument("--epochs", type=int, default=30)
    tr.add_argument("--val_ratio", type=float, default=0.2)
    tr.add_argument("--seed", type=int, default=42)
    tr.add_argument("--smooth_ddah_window", type=int, default=3)
    tr.add_argument("--csv_encoding", type=str, default=None)
    tr.add_argument("--ewma_alpha", type=float, default=0.2)
    tr.add_argument("--cusum_k", type=float, default=0.5)
    tr.add_argument("--min_points", type=int, default=120)

    sc = sub.add_parser("score")
    sc.add_argument("--model_dir", type=str, required=True)
    sc.add_argument("--test_path", type=str, required=True)
    sc.add_argument("--out_dir", type=str, default="./out_batch_v24a")
    sc.add_argument("--csv_encoding", type=str, default=None)
    return ap


def main() -> None:
    ap = build_parser()
    args = ap.parse_args()
    if args.mode == "train":
        train_main(args)
    elif args.mode == "score":
        score_main(args)


if __name__ == "__main__":
    main()
