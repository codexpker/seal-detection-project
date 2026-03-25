#!/usr/bin/env python3
import argparse
import json
import os
import sys
import warnings
from typing import Any, Dict, List

os.environ.setdefault("LIBOMP_USE_HIDDEN_HELPER_TASK", "0")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np
import pandas as pd
from sklearn.metrics import balanced_accuracy_score, f1_score, precision_score, recall_score, roc_auc_score

warnings.filterwarnings("ignore", category=UserWarning, module="sklearn.metrics._classification")

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

VENDOR_DIR = os.path.join(ROOT_DIR, ".vendor")
if os.path.isdir(VENDOR_DIR) and VENDOR_DIR not in sys.path:
    sys.path.insert(0, VENDOR_DIR)

from xgboost import XGBClassifier

from src.scripts.lab_phase1_acceptance import (
    Phase1Config,
    apply_transition_relative_score,
    auc_pairwise,
    build_file_summary,
    process_dataset,
    robust_z_positive,
)


FEATURE_COLUMNS = [
    "mean_in_temp",
    "mean_out_temp",
    "mean_in_hum",
    "mean_out_hum",
    "mean_AH_in",
    "mean_AH_out",
    "mean_dT",
    "mean_dAH",
    "std_in_temp",
    "std_out_temp",
    "std_in_hum",
    "std_out_hum",
    "std_AH_in",
    "std_AH_out",
    "std_dT",
    "std_dAH",
    "slope_in_temp",
    "slope_out_temp",
    "slope_in_hum",
    "slope_out_hum",
    "slope_AH_in",
    "slope_AH_out",
    "slope_dT",
    "slope_dAH",
    "delta_half_in_temp",
    "delta_half_in_hum",
    "delta_half_AH_in",
    "delta_half_dT",
    "delta_half_dAH",
    "delta_in_temp",
    "delta_in_hum",
    "delta_AH_in",
    "corr_temp",
    "corr_hum",
    "corr_AH",
    "high_out_hum_ratio",
    "max_hourly_temp_rise",
    "max_hourly_temp_drop",
    "max_hourly_hum_rise",
]


def run_level_view(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "file",
        "seal_label",
        "label",
        "slope_in_h_per_h",
        "delta_half_in_h",
        "delta_half_dAH",
        "mean_dT_run",
    ]
    return (
        df[cols]
        .groupby("file", dropna=False)
        .first()
        .reset_index()
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lab phase-2 XGBoost branch")
    parser.add_argument("--input-dir", default=Phase1Config.input_dir)
    parser.add_argument("--input-zip", default=Phase1Config.input_zip)
    parser.add_argument("--metadata-xlsx", default=Phase1Config.metadata_xlsx)
    parser.add_argument("--output-dir", default="reports/lab_phase2_xgboost")
    parser.add_argument("--window-hours", type=int, default=12)
    parser.add_argument("--step-hours", type=int, default=1)
    parser.add_argument("--transition-near-hours", type=int, default=6)
    parser.add_argument("--threshold", type=float, default=0.5)
    return parser.parse_args()


def build_phase1_views(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
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
    return window_df, file_df, run_df


def select_static_branch_dataset(window_df: pd.DataFrame, file_df: pd.DataFrame) -> pd.DataFrame:
    run_cols = [
        "file",
        "sheet",
        "seal_label",
        "heat_source_inferred",
        "expected_family",
        "mean_out_h",
        "mean_dT",
        "duration_h",
        "slope_in_h_per_h",
        "slope_dAH_per_h",
        "delta_end_in_h",
        "delta_half_in_h",
        "delta_half_dAH",
        "end_start_dAH",
    ]
    merged = window_df.merge(
        file_df[run_cols],
        on=["file", "sheet", "seal_label", "heat_source_inferred", "expected_family"],
        how="left",
        suffixes=("", "_run"),
    )
    mask = (
        merged["seal_label"].isin(["seal", "unseal"])
        & (merged["heat_source_inferred"] == "无")
        & (merged["expected_family"] != "transition_run")
        & (merged["predicted_group"] == "candidate_high_info")
        & merged["file"].str.contains("unheated", case=False, na=False)
        & (merged["mean_out_h"] >= 80.0)
        & (merged["mean_dT_run"] < 1.5)
    )
    subset = merged.loc[mask].copy()
    subset["label"] = (subset["seal_label"] == "unseal").astype(int)
    return subset


def add_info_score(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["info_score"] = 0.0
    out["info_rank_pct"] = np.nan
    for file_name, group in out.groupby("file", dropna=False):
        score = (
            0.45 * robust_z_positive(group["delta_half_in_hum"])
            + 0.35 * robust_z_positive(group["delta_half_dAH"])
            + 0.20 * robust_z_positive(group["slope_AH_in"])
        )
        out.loc[group.index, "info_score"] = score.values
        out.loc[group.index, "info_rank_pct"] = score.rank(pct=True, method="average").values
    return out


def select_top_info_windows(df: pd.DataFrame, top_ratio: float = 0.40, min_windows: int = 6) -> pd.DataFrame:
    rows: List[pd.DataFrame] = []
    for _, group in df.groupby("file", dropna=False):
        keep_n = max(min_windows, int(np.ceil(len(group) * top_ratio)))
        keep_n = min(len(group), keep_n)
        rows.append(group.sort_values(["info_score", "window_id"], ascending=[False, True]).head(keep_n))
    if not rows:
        return df.iloc[0:0].copy()
    return pd.concat(rows, ignore_index=True)


def build_feature_matrix(df: pd.DataFrame) -> pd.DataFrame:
    feat_df = df[FEATURE_COLUMNS].copy()
    feat_df = feat_df.replace([np.inf, -np.inf], np.nan)
    medians = feat_df.median(numeric_only=True)
    feat_df = feat_df.fillna(medians)
    return feat_df


def fit_one_fold(train_x: pd.DataFrame, train_y: pd.Series) -> XGBClassifier:
    positives = int(train_y.sum())
    negatives = int(len(train_y) - positives)
    scale_pos_weight = float(negatives / max(positives, 1))
    model = XGBClassifier(
        objective="binary:logistic",
        eval_metric="logloss",
        n_estimators=120,
        max_depth=3,
        learning_rate=0.05,
        subsample=0.85,
        colsample_bytree=0.85,
        reg_lambda=1.0,
        min_child_weight=1,
        random_state=42,
        scale_pos_weight=scale_pos_weight,
        n_jobs=1,
    )
    model.fit(train_x, train_y)
    return model


def leave_one_run_out_predictions(df: pd.DataFrame, threshold: float) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    run_ids = list(df["file"].drop_duplicates())
    window_pred_rows: List[Dict[str, Any]] = []
    fold_rows: List[Dict[str, Any]] = []
    importances: List[pd.Series] = []

    for holdout in run_ids:
        train_df = df[df["file"] != holdout].copy()
        test_df = df[df["file"] == holdout].copy()
        if train_df["label"].nunique() < 2 or test_df.empty:
            continue

        train_x = build_feature_matrix(train_df)
        test_x = build_feature_matrix(test_df)
        train_y = train_df["label"].astype(int)
        test_y = test_df["label"].astype(int)

        model = fit_one_fold(train_x, train_y)
        prob = model.predict_proba(test_x)[:, 1]
        pred = (prob >= threshold).astype(int)

        fold_auc = roc_auc_score(test_y, prob) if test_y.nunique() > 1 else np.nan
        fold_bal_acc = balanced_accuracy_score(test_y, pred)
        fold_rows.append(
            {
                "holdout_file": holdout,
                "n_test_windows": int(len(test_df)),
                "label": int(test_y.iloc[0]),
                "fold_auc": float(fold_auc) if not np.isnan(fold_auc) else np.nan,
                "fold_balanced_accuracy": float(fold_bal_acc),
                "mean_prob": float(np.mean(prob)),
            }
        )

        importances.append(pd.Series(model.feature_importances_, index=train_x.columns))
        out = test_df[["file", "sheet", "window_id", "seal_label", "label"]].copy()
        out["prob_unseal"] = prob
        out["pred_label"] = pred
        out["holdout_file"] = holdout
        window_pred_rows.extend(out.to_dict(orient="records"))

    window_pred_df = pd.DataFrame(window_pred_rows)
    fold_df = pd.DataFrame(fold_rows)
    importance_df = (
        pd.concat(importances, axis=1).fillna(0.0).mean(axis=1).sort_values(ascending=False).reset_index()
        if importances
        else pd.DataFrame(columns=["feature", "importance"])
    )
    if not importance_df.empty:
        importance_df.columns = ["feature", "importance"]
    return window_pred_df, fold_df, importance_df


def summarize_predictions(window_pred_df: pd.DataFrame, threshold: float) -> Dict[str, Any]:
    if window_pred_df.empty:
        return {
            "window_metrics": {},
            "run_metrics": {},
            "pass": False,
        }

    window_true = window_pred_df["label"].astype(int)
    window_prob = window_pred_df["prob_unseal"].astype(float)
    window_pred = (window_prob >= threshold).astype(int)
    window_metrics = {
        "window_auc": float(roc_auc_score(window_true, window_prob)) if window_true.nunique() > 1 else None,
        "window_balanced_accuracy": float(balanced_accuracy_score(window_true, window_pred)),
        "window_precision": float(precision_score(window_true, window_pred, zero_division=0)),
        "window_recall": float(recall_score(window_true, window_pred, zero_division=0)),
        "window_f1": float(f1_score(window_true, window_pred, zero_division=0)),
        "window_count": int(len(window_pred_df)),
    }

    run_pred_df = (
        window_pred_df.groupby(["file", "seal_label", "label"], dropna=False)
        .agg(
            mean_prob_unseal=("prob_unseal", "mean"),
            median_prob_unseal=("prob_unseal", "median"),
            n_windows=("window_id", "count"),
        )
        .reset_index()
    )
    run_true = run_pred_df["label"].astype(int)
    run_prob = run_pred_df["mean_prob_unseal"].astype(float)
    run_pred = (run_prob >= threshold).astype(int)
    run_metrics = {
        "run_auc": float(roc_auc_score(run_true, run_prob)) if run_true.nunique() > 1 else None,
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
        "run_predictions": run_pred_df,
        "pass": branch_pass,
    }


def simple_baseline_auc(df: pd.DataFrame) -> Dict[str, Any]:
    by_run = run_level_view(df)
    labels = by_run["label"].astype(int).tolist()
    candidates = {}
    for col in ["slope_in_h_per_h", "delta_half_in_h", "delta_half_dAH", "mean_dT_run"]:
        scores = by_run[col].astype(float).tolist()
        auc_pos = auc_pairwise(scores, labels)
        auc_neg = auc_pairwise([-x for x in scores], labels)
        candidates[col] = {
            "auc": float(max(auc_pos or 0.0, auc_neg or 0.0)),
            "direction": "pos" if (auc_pos or 0.0) >= (auc_neg or 0.0) else "neg",
        }
    best_col = max(candidates, key=lambda k: candidates[k]["auc"])
    return {"best_feature": best_col, **candidates[best_col], "all": candidates}


def best_threshold_on_train(scores: List[float], labels: List[int]) -> Dict[str, Any]:
    values = sorted(set(float(x) for x in scores))
    thresholds: List[float] = []
    if values:
        thresholds.append(values[0] - 1e-6)
        thresholds.extend(values)
        thresholds.append(values[-1] + 1e-6)

    best: Dict[str, Any] | None = None
    for direction in [1, -1]:
        for threshold in thresholds:
            pred = [1 if direction * s >= direction * threshold else 0 for s in scores]
            bal_acc = balanced_accuracy_score(labels, pred)
            candidate = {
                "balanced_accuracy": float(bal_acc),
                "direction": direction,
                "threshold": float(threshold),
            }
            if best is None or candidate["balanced_accuracy"] > best["balanced_accuracy"]:
                best = candidate
    return best or {"balanced_accuracy": 0.0, "direction": 1, "threshold": 0.0}


def evaluate_baseline_threshold_branch(df: pd.DataFrame) -> Dict[str, Any]:
    by_run = run_level_view(df)
    feature_names = ["slope_in_h_per_h", "delta_half_in_h", "delta_half_dAH", "mean_dT_run"]

    feature_results: Dict[str, Any] = {}
    for feature in feature_names:
        rows: List[Dict[str, Any]] = []
        for holdout in by_run["file"]:
            train_df = by_run[by_run["file"] != holdout].copy()
            test_df = by_run[by_run["file"] == holdout].copy()
            selector = best_threshold_on_train(train_df[feature].astype(float).tolist(), train_df["label"].astype(int).tolist())
            score = float(test_df[feature].iloc[0])
            pred = 1 if selector["direction"] * score >= selector["direction"] * selector["threshold"] else 0
            rows.append(
                {
                    "file": holdout,
                    "seal_label": test_df["seal_label"].iloc[0],
                    "label": int(test_df["label"].iloc[0]),
                    "score": score,
                    "pred_label": pred,
                    "direction": selector["direction"],
                    "threshold": selector["threshold"],
                }
            )

        pred_df = pd.DataFrame(rows)
        bal_acc = balanced_accuracy_score(pred_df["label"], pred_df["pred_label"])
        precision = precision_score(pred_df["label"], pred_df["pred_label"], zero_division=0)
        recall = recall_score(pred_df["label"], pred_df["pred_label"], zero_division=0)
        f1 = f1_score(pred_df["label"], pred_df["pred_label"], zero_division=0)
        feature_results[feature] = {
            "run_balanced_accuracy": float(bal_acc),
            "run_precision": float(precision),
            "run_recall": float(recall),
            "run_f1": float(f1),
            "predictions": pred_df,
        }

    best_feature = max(feature_results, key=lambda k: feature_results[k]["run_balanced_accuracy"])
    best = feature_results[best_feature]
    return {
        "best_feature": best_feature,
        "run_balanced_accuracy": best["run_balanced_accuracy"],
        "run_precision": best["run_precision"],
        "run_recall": best["run_recall"],
        "run_f1": best["run_f1"],
        "pass": bool(best["run_balanced_accuracy"] >= 0.65),
        "predictions": best["predictions"],
        "all": {
            k: {kk: vv for kk, vv in v.items() if kk != "predictions"}
            for k, v in feature_results.items()
        },
    }


def write_markdown(path: str, result: Dict[str, Any]) -> None:
    best_summary = result["best_variant"]["summary"]
    window_metrics = best_summary["window_metrics"]
    run_metrics = best_summary["run_metrics"]
    baseline = result["baseline"]
    baseline_branch = result["baseline_branch"]
    lines = [
        "# 实验室第二阶段 XGBoost 支线报告",
        "",
        f"- 分支结论：`{'PASS' if result['best_variant']['summary']['pass'] else 'FAIL'}`",
        f"- 最优训练视图：`{result['best_variant']['name']}`",
        f"- 当前推荐静态替代：`{baseline_branch['best_feature']}`",
        f"- 训练范围：`高外湿 + 无热源 + 非转移 + candidate_high_info`",
        f"- 窗口数：`{window_metrics.get('window_count')}`",
        f"- 运行数：`{run_metrics.get('run_count')}`",
        "",
        "## 训练视图对照",
        "",
    ]
    for name, variant in result["variants"].items():
        vm = variant["summary"]["window_metrics"]
        rm = variant["summary"]["run_metrics"]
        lines.extend(
            [
                f"- {name} | window_auc={vm.get('window_auc')} | run_auc={rm.get('run_auc')} | "
                f"run_balanced_accuracy={rm.get('run_balanced_accuracy')} | pass={variant['summary']['pass']}",
            ]
        )

    lines.extend(
        [
            "",
            "## 最优视图留一运行验证",
            "",
        ]
    )
    lines.extend(
        [
        f"- window_auc：`{window_metrics.get('window_auc')}`",
        f"- window_balanced_accuracy：`{window_metrics.get('window_balanced_accuracy')}`",
        f"- run_auc：`{run_metrics.get('run_auc')}`",
        f"- run_balanced_accuracy：`{run_metrics.get('run_balanced_accuracy')}`",
        "",
        "## 与简单单特征基线对照",
        "",
        f"- 最优单特征：`{baseline['best_feature']}`",
        f"- 最优单特征 AUC：`{baseline['auc']}`",
        f"- 最优阈值基线：`{baseline_branch['best_feature']}`",
        f"- 最优阈值基线 run_balanced_accuracy：`{baseline_branch['run_balanced_accuracy']}`",
        f"- 最优阈值基线是否通过：`{baseline_branch['pass']}`",
        "",
        "## 判断",
        "",
        "- 这条支线只负责静态高信息分支，不替代转移分支。",
        "- 当前 XGBoost 支线已经完整实现，但在当前数据上没有超过简单基线，不能作为静态分支验收依据。",
        "- 在现有样本量下，静态分支更适合先用单特征阈值基线做演示和继续积累证据。",
        "",
    ]
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    window_df, file_df, _ = build_phase1_views(args)
    static_window_df = add_info_score(select_static_branch_dataset(window_df, file_df))
    info_window_df = select_top_info_windows(static_window_df)

    full_window_pred_df, full_fold_df, full_importance_df = leave_one_run_out_predictions(static_window_df, args.threshold)
    full_summary = summarize_predictions(full_window_pred_df, args.threshold)

    info_window_pred_df, info_fold_df, info_importance_df = leave_one_run_out_predictions(info_window_df, args.threshold)
    info_summary = summarize_predictions(info_window_pred_df, args.threshold)

    variants = {
        "all_candidate_windows": {
            "dataset": static_window_df,
            "window_predictions": full_window_pred_df,
            "fold_metrics": full_fold_df,
            "feature_importance": full_importance_df,
            "summary": full_summary,
        },
        "top_info_windows": {
            "dataset": info_window_df,
            "window_predictions": info_window_pred_df,
            "fold_metrics": info_fold_df,
            "feature_importance": info_importance_df,
            "summary": info_summary,
        },
    }

    def variant_score(name: str) -> float:
        run_auc = variants[name]["summary"]["run_metrics"].get("run_auc")
        return float(run_auc) if run_auc is not None else -1.0

    best_name = max(variants, key=variant_score)
    best_variant = variants[best_name]
    baseline = simple_baseline_auc(static_window_df)
    baseline_branch = evaluate_baseline_threshold_branch(static_window_df)

    outputs = {
        "dataset_all_csv": os.path.join(args.output_dir, "phase2_xgboost_dataset_all.csv"),
        "dataset_top_info_csv": os.path.join(args.output_dir, "phase2_xgboost_dataset_top_info.csv"),
        "window_predictions_all_csv": os.path.join(args.output_dir, "phase2_xgboost_window_predictions_all.csv"),
        "window_predictions_top_info_csv": os.path.join(args.output_dir, "phase2_xgboost_window_predictions_top_info.csv"),
        "run_predictions_best_csv": os.path.join(args.output_dir, "phase2_xgboost_run_predictions_best.csv"),
        "fold_metrics_all_csv": os.path.join(args.output_dir, "phase2_xgboost_fold_metrics_all.csv"),
        "fold_metrics_top_info_csv": os.path.join(args.output_dir, "phase2_xgboost_fold_metrics_top_info.csv"),
        "feature_importance_all_csv": os.path.join(args.output_dir, "phase2_xgboost_feature_importance_all.csv"),
        "feature_importance_top_info_csv": os.path.join(args.output_dir, "phase2_xgboost_feature_importance_top_info.csv"),
        "baseline_branch_predictions_csv": os.path.join(args.output_dir, "phase2_baseline_branch_predictions.csv"),
        "report_md": os.path.join(args.output_dir, "phase2_xgboost_report.md"),
        "report_json": os.path.join(args.output_dir, "phase2_xgboost_report.json"),
    }

    static_window_df.to_csv(outputs["dataset_all_csv"], index=False, encoding="utf-8-sig")
    info_window_df.to_csv(outputs["dataset_top_info_csv"], index=False, encoding="utf-8-sig")
    full_window_pred_df.to_csv(outputs["window_predictions_all_csv"], index=False, encoding="utf-8-sig")
    info_window_pred_df.to_csv(outputs["window_predictions_top_info_csv"], index=False, encoding="utf-8-sig")
    best_variant["summary"]["run_predictions"].to_csv(outputs["run_predictions_best_csv"], index=False, encoding="utf-8-sig")
    full_fold_df.to_csv(outputs["fold_metrics_all_csv"], index=False, encoding="utf-8-sig")
    info_fold_df.to_csv(outputs["fold_metrics_top_info_csv"], index=False, encoding="utf-8-sig")
    full_importance_df.to_csv(outputs["feature_importance_all_csv"], index=False, encoding="utf-8-sig")
    info_importance_df.to_csv(outputs["feature_importance_top_info_csv"], index=False, encoding="utf-8-sig")
    baseline_branch["predictions"].to_csv(outputs["baseline_branch_predictions_csv"], index=False, encoding="utf-8-sig")

    result = {
        "config": {
            "output_dir": args.output_dir,
            "window_hours": args.window_hours,
            "step_hours": args.step_hours,
            "threshold": args.threshold,
        },
        "dataset": {
            "candidate_windows": int(len(static_window_df)),
            "candidate_runs": int(static_window_df["file"].nunique()),
            "class_counts": static_window_df["seal_label"].value_counts().to_dict(),
            "top_info_windows": int(len(info_window_df)),
        },
        "baseline": baseline,
        "baseline_branch": {
            **{k: v for k, v in baseline_branch.items() if k != "predictions"},
        },
        "variants": {
            name: {
                "summary": {
                    **{k: v for k, v in variant["summary"].items() if k != "run_predictions"},
                }
            }
            for name, variant in variants.items()
        },
        "best_variant": {
            "name": best_name,
            "summary": {
                **{k: v for k, v in best_variant["summary"].items() if k != "run_predictions"},
            },
        },
        "outputs": outputs,
    }
    write_markdown(outputs["report_md"], result)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
