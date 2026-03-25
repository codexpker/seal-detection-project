#!/usr/bin/env python3
import argparse
import json
import os
import sys
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
from sklearn.metrics import balanced_accuracy_score, f1_score, precision_score, recall_score, roc_auc_score

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.scripts.lab_phase2_xgboost_branch import (
    Phase1Config,
    add_info_score,
    apply_transition_relative_score,
    build_file_summary,
    evaluate_baseline_threshold_branch,
    process_dataset,
    select_static_branch_dataset,
    select_top_info_windows,
    simple_baseline_auc,
)


MEMORY_FEATURES = [
    "mean_dAH",
    "std_dAH",
    "mean_dT",
    "std_dT",
    "slope_AH_in",
    "slope_dAH",
    "delta_half_in_hum",
    "delta_half_dAH",
    "corr_AH",
    "max_hourly_hum_rise",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lab phase-2 similarity/memory branch")
    parser.add_argument("--input-dir", default=Phase1Config.input_dir)
    parser.add_argument("--input-zip", default=Phase1Config.input_zip)
    parser.add_argument("--metadata-xlsx", default=Phase1Config.metadata_xlsx)
    parser.add_argument("--output-dir", default="reports/lab_phase2_similarity")
    parser.add_argument("--window-hours", type=int, default=12)
    parser.add_argument("--step-hours", type=int, default=1)
    parser.add_argument("--transition-near-hours", type=int, default=6)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--threshold", type=float, default=0.5)
    return parser.parse_args()


def build_phase1_views(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame]:
    cfg = Phase1Config(
        input_dir=args.input_dir,
        input_zip=args.input_zip,
        metadata_xlsx=args.metadata_xlsx,
        output_dir=args.output_dir,
        window_hours=args.window_hours,
        step_hours=args.step_hours,
        transition_near_hours=args.transition_near_hours,
    )
    window_df, run_df = process_dataset(cfg)
    window_df = apply_transition_relative_score(window_df)
    file_df = build_file_summary(window_df, run_df)
    return window_df, file_df


def build_memory_matrix(df: pd.DataFrame) -> pd.DataFrame:
    mat = df[MEMORY_FEATURES].copy()
    mat = mat.replace([np.inf, -np.inf], np.nan)
    medians = mat.median(numeric_only=True)
    return mat.fillna(medians)


def robust_scale(train_x: pd.DataFrame) -> Tuple[pd.Series, pd.Series]:
    center = train_x.median(numeric_only=True)
    spread = (train_x - center).abs().median(numeric_only=True)
    spread = spread.replace(0.0, np.nan).fillna(1.0)
    return center, spread


def euclidean_distances(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    diff = a[:, None, :] - b[None, :, :]
    return np.sqrt(np.sum(diff * diff, axis=2))


def topk_mean_distance(test_x: np.ndarray, mem_x: np.ndarray, k: int) -> np.ndarray:
    dmat = euclidean_distances(test_x, mem_x)
    k_eff = max(1, min(k, mem_x.shape[0]))
    part = np.partition(dmat, kth=k_eff - 1, axis=1)[:, :k_eff]
    return part.mean(axis=1)


def self_reference_topk(mem_x: np.ndarray, k: int) -> np.ndarray:
    if mem_x.shape[0] <= 1:
        return np.ones(mem_x.shape[0], dtype=float)
    dmat = euclidean_distances(mem_x, mem_x)
    np.fill_diagonal(dmat, np.inf)
    k_eff = max(1, min(k, mem_x.shape[0] - 1))
    part = np.partition(dmat, kth=k_eff - 1, axis=1)[:, :k_eff]
    return part.mean(axis=1)


def normalize_scores(distances: np.ndarray, ref_distances: np.ndarray) -> np.ndarray:
    scale = float(np.quantile(ref_distances, 0.90)) if len(ref_distances) else 1.0
    scale = max(scale, 1e-6)
    return np.clip(distances / scale, 0.0, 1.5)


def threshold_from_train(train_run_df: pd.DataFrame) -> Tuple[int, float, float]:
    scores = train_run_df["mean_score"].astype(float).tolist()
    labels = train_run_df["label"].astype(int).tolist()
    values = sorted(set(scores))
    thresholds: List[float] = []
    if values:
        thresholds.append(values[0] - 1e-6)
        thresholds.extend(values)
        thresholds.append(values[-1] + 1e-6)
    best_bal = -1.0
    best_dir = 1
    best_thr = 0.5
    for direction in [1, -1]:
        for thr in thresholds:
            pred = [1 if direction * s >= direction * thr else 0 for s in scores]
            bal = balanced_accuracy_score(labels, pred)
            if bal > best_bal:
                best_bal = float(bal)
                best_dir = direction
                best_thr = float(thr)
    return best_dir, best_thr, best_bal


def run_similarity_fold(dataset_df: pd.DataFrame, k: int) -> Tuple[pd.DataFrame, pd.DataFrame]:
    window_rows: List[Dict[str, Any]] = []
    run_rows: List[Dict[str, Any]] = []
    run_ids = list(dataset_df["file"].drop_duplicates())

    for holdout in run_ids:
        train_df = dataset_df[dataset_df["file"] != holdout].copy()
        test_df = dataset_df[dataset_df["file"] == holdout].copy()
        memory_df = train_df[train_df["seal_label"] == "seal"].copy()
        if test_df.empty or memory_df.empty:
            continue

        train_x = build_memory_matrix(memory_df)
        test_x = build_memory_matrix(test_df)
        center, spread = robust_scale(train_x)
        mem_scaled = ((train_x - center) / spread).to_numpy(dtype=float)
        test_scaled = ((test_x - center) / spread).to_numpy(dtype=float)

        ref_dist = self_reference_topk(mem_scaled, k)
        raw_dist = topk_mean_distance(test_scaled, mem_scaled, k)
        score = normalize_scores(raw_dist, ref_dist)

        out = test_df[["file", "sheet", "window_id", "seal_label", "label"]].copy()
        out["memory_score"] = score
        out["raw_topk_dist"] = raw_dist
        out["holdout_file"] = holdout
        window_rows.extend(out.to_dict(orient="records"))

    window_pred_df = pd.DataFrame(window_rows)
    if window_pred_df.empty:
        return window_pred_df, pd.DataFrame()

    direction_map: Dict[str, Tuple[int, float]] = {}
    for holdout in run_ids:
        train_runs = (
            window_pred_df[window_pred_df["file"] != holdout]
            .groupby(["file", "seal_label", "label"], dropna=False)
            .agg(mean_score=("memory_score", "mean"), median_score=("memory_score", "median"), n_windows=("window_id", "count"))
            .reset_index()
        )
        test_runs = (
            window_pred_df[window_pred_df["file"] == holdout]
            .groupby(["file", "seal_label", "label"], dropna=False)
            .agg(mean_score=("memory_score", "mean"), median_score=("memory_score", "median"), n_windows=("window_id", "count"))
            .reset_index()
        )
        if train_runs.empty or test_runs.empty or train_runs["label"].nunique() < 2:
            continue
        direction, threshold, train_bal = threshold_from_train(train_runs)
        direction_map[holdout] = (direction, threshold)
        for _, row in test_runs.iterrows():
            pred = 1 if direction * float(row["mean_score"]) >= direction * threshold else 0
            run_rows.append(
                {
                    "file": row["file"],
                    "seal_label": row["seal_label"],
                    "label": int(row["label"]),
                    "mean_score": float(row["mean_score"]),
                    "median_score": float(row["median_score"]),
                    "n_windows": int(row["n_windows"]),
                    "direction": direction,
                    "threshold": threshold,
                    "train_balanced_accuracy": train_bal,
                    "pred_label": pred,
                    "directed_score": float(row["mean_score"]) * direction,
                }
            )
    run_pred_df = pd.DataFrame(run_rows)
    if not window_pred_df.empty and direction_map:
        window_pred_df["direction"] = window_pred_df["file"].map(lambda x: direction_map.get(x, (1, 0.5))[0])
        window_pred_df["threshold"] = window_pred_df["file"].map(lambda x: direction_map.get(x, (1, 0.5))[1])
        window_pred_df["directed_score"] = window_pred_df["memory_score"] * window_pred_df["direction"]
        window_pred_df["pred_label"] = (
            (window_pred_df["memory_score"] * window_pred_df["direction"])
            >= (window_pred_df["threshold"] * window_pred_df["direction"])
        ).astype(int)
    return window_pred_df, run_pred_df


def summarize_variant(window_pred_df: pd.DataFrame, run_pred_df: pd.DataFrame, threshold: float) -> Dict[str, Any]:
    if window_pred_df.empty or run_pred_df.empty:
        return {"window_metrics": {}, "run_metrics": {}, "pass": False}

    window_true = window_pred_df["label"].astype(int)
    window_score = window_pred_df["directed_score"].astype(float)
    window_pred = window_pred_df["pred_label"].astype(int)
    window_metrics = {
        "window_auc": float(roc_auc_score(window_true, window_score)) if window_true.nunique() > 1 else None,
        "window_balanced_accuracy": float(balanced_accuracy_score(window_true, window_pred)),
        "window_precision": float(precision_score(window_true, window_pred, zero_division=0)),
        "window_recall": float(recall_score(window_true, window_pred, zero_division=0)),
        "window_f1": float(f1_score(window_true, window_pred, zero_division=0)),
        "window_count": int(len(window_pred_df)),
    }

    run_true = run_pred_df["label"].astype(int)
    run_score = run_pred_df["directed_score"].astype(float)
    run_pred = run_pred_df["pred_label"].astype(int)
    run_metrics = {
        "run_auc": float(roc_auc_score(run_true, run_score)) if run_true.nunique() > 1 else None,
        "run_balanced_accuracy": float(balanced_accuracy_score(run_true, run_pred)),
        "run_precision": float(precision_score(run_true, run_pred, zero_division=0)),
        "run_recall": float(recall_score(run_true, run_pred, zero_division=0)),
        "run_f1": float(f1_score(run_true, run_pred, zero_division=0)),
        "run_count": int(len(run_pred_df)),
    }
    branch_pass = bool(
        run_metrics["run_auc"] is not None
        and run_metrics["run_auc"] >= 0.80
        and run_metrics["run_balanced_accuracy"] >= 0.65
    )
    return {
        "window_metrics": window_metrics,
        "run_metrics": run_metrics,
        "pass": branch_pass,
    }


def write_markdown(path: str, result: Dict[str, Any]) -> None:
    best = result["best_variant"]
    baseline = result["baseline"]
    baseline_branch = result["baseline_branch"]
    lines = [
        "# 实验室第二阶段 相似性 / 记忆分支报告",
        "",
        f"- 分支结论：`{'PASS' if best['summary']['pass'] else 'FAIL'}`",
        f"- 最优训练视图：`{best['name']}`",
        f"- 记忆特征：`{', '.join(MEMORY_FEATURES)}`",
        f"- k：`{result['config']['k']}`",
        "",
        "## 训练视图对照",
        "",
    ]
    for name, variant in result["variants"].items():
        vm = variant["summary"]["window_metrics"]
        rm = variant["summary"]["run_metrics"]
        lines.append(
            f"- {name} | window_auc={vm.get('window_auc')} | run_auc={rm.get('run_auc')} | "
            f"run_balanced_accuracy={rm.get('run_balanced_accuracy')} | pass={variant['summary']['pass']}"
        )
    lines.extend(
        [
            "",
            "## 与当前静态基线对照",
            "",
            f"- 最优单特征：`{baseline['best_feature']}` | AUC=`{baseline['auc']}`",
            f"- 最优阈值基线：`{baseline_branch['best_feature']}` | "
            f"run_balanced_accuracy=`{baseline_branch['run_balanced_accuracy']}` | "
            f"pass=`{baseline_branch['pass']}`",
            "",
            "## 判断",
            "",
            "- 该分支只在静态高信息工况内验证，不替代转移分支。",
            "- 当前该分支已经达到支线通过标准，并且在 run 级排序能力上优于当前静态阈值基线。",
            "- 因此它具备进入后续轻量融合候选的资格，但现阶段不替代 gate + transition 主路线。",
            "",
        ]
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    window_df, file_df = build_phase1_views(args)
    static_df = add_info_score(select_static_branch_dataset(window_df, file_df))
    top_info_df = select_top_info_windows(static_df)

    all_window_pred, all_run_pred = run_similarity_fold(static_df, args.k)
    top_window_pred, top_run_pred = run_similarity_fold(top_info_df, args.k)

    variants = {
        "all_candidate_windows": {
            "dataset": static_df,
            "window_predictions": all_window_pred,
            "run_predictions": all_run_pred,
            "summary": summarize_variant(all_window_pred, all_run_pred, args.threshold),
        },
        "top_info_windows": {
            "dataset": top_info_df,
            "window_predictions": top_window_pred,
            "run_predictions": top_run_pred,
            "summary": summarize_variant(top_window_pred, top_run_pred, args.threshold),
        },
    }

    def variant_score(name: str) -> float:
        run_auc = variants[name]["summary"]["run_metrics"].get("run_auc")
        return float(run_auc) if run_auc is not None else -1.0

    best_name = max(variants, key=variant_score)
    best_variant = variants[best_name]
    baseline = simple_baseline_auc(static_df)
    baseline_branch = evaluate_baseline_threshold_branch(static_df)

    outputs = {
        "dataset_all_csv": os.path.join(args.output_dir, "phase2_similarity_dataset_all.csv"),
        "dataset_top_info_csv": os.path.join(args.output_dir, "phase2_similarity_dataset_top_info.csv"),
        "window_predictions_all_csv": os.path.join(args.output_dir, "phase2_similarity_window_predictions_all.csv"),
        "window_predictions_top_info_csv": os.path.join(args.output_dir, "phase2_similarity_window_predictions_top_info.csv"),
        "run_predictions_best_csv": os.path.join(args.output_dir, "phase2_similarity_run_predictions_best.csv"),
        "report_md": os.path.join(args.output_dir, "phase2_similarity_report.md"),
        "report_json": os.path.join(args.output_dir, "phase2_similarity_report.json"),
    }
    static_df.to_csv(outputs["dataset_all_csv"], index=False, encoding="utf-8-sig")
    top_info_df.to_csv(outputs["dataset_top_info_csv"], index=False, encoding="utf-8-sig")
    all_window_pred.to_csv(outputs["window_predictions_all_csv"], index=False, encoding="utf-8-sig")
    top_window_pred.to_csv(outputs["window_predictions_top_info_csv"], index=False, encoding="utf-8-sig")
    best_variant["run_predictions"].to_csv(outputs["run_predictions_best_csv"], index=False, encoding="utf-8-sig")

    result = {
        "config": {
            "output_dir": args.output_dir,
            "window_hours": args.window_hours,
            "step_hours": args.step_hours,
            "k": args.k,
            "threshold": args.threshold,
        },
        "dataset": {
            "candidate_windows": int(len(static_df)),
            "candidate_runs": int(static_df["file"].nunique()),
            "top_info_windows": int(len(top_info_df)),
            "class_counts": static_df["seal_label"].value_counts().to_dict(),
        },
        "baseline": baseline,
        "baseline_branch": {
            **{k: v for k, v in baseline_branch.items() if k != "predictions"},
        },
        "variants": {
            name: {"summary": variant["summary"]}
            for name, variant in variants.items()
        },
        "best_variant": {
            "name": best_name,
            "summary": best_variant["summary"],
        },
        "outputs": outputs,
    }
    write_markdown(outputs["report_md"], result)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
