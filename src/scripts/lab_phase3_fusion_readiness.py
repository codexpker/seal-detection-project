#!/usr/bin/env python3
import argparse
import json
import os
import sys
from typing import Any, Dict

import pandas as pd
from sklearn.metrics import balanced_accuracy_score, f1_score, precision_score, recall_score

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fusion readiness diagnostic for static branches")
    parser.add_argument(
        "--baseline-csv",
        default="reports/lab_phase2_xgboost_run3/phase2_baseline_branch_predictions.csv",
    )
    parser.add_argument(
        "--similarity-csv",
        default="reports/lab_phase2_similarity_run3/phase2_similarity_run_predictions_best.csv",
    )
    parser.add_argument("--output-dir", default="reports/lab_phase3_fusion_readiness")
    return parser.parse_args()


def metrics_from_pred(df: pd.DataFrame, pred_col: str) -> Dict[str, Any]:
    y_true = df["label"].astype(int)
    y_pred = df[pred_col].astype(int)
    return {
        "run_balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
        "run_precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "run_recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "run_f1": float(f1_score(y_true, y_pred, zero_division=0)),
    }


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    baseline_df = pd.read_csv(args.baseline_csv).rename(
        columns={
            "pred_label": "pred_baseline",
            "score": "score_baseline",
            "direction": "direction_baseline",
            "threshold": "threshold_baseline",
        }
    )
    similarity_df = pd.read_csv(args.similarity_csv).rename(
        columns={
            "pred_label": "pred_similarity",
            "mean_score": "score_similarity",
            "direction": "direction_similarity",
            "threshold": "threshold_similarity",
            "directed_score": "directed_score_similarity",
        }
    )

    merged = baseline_df.merge(
        similarity_df[
            [
                "file",
                "label",
                "pred_similarity",
                "score_similarity",
                "direction_similarity",
                "threshold_similarity",
                "directed_score_similarity",
            ]
        ],
        on=["file", "label"],
        how="inner",
    )
    merged["correct_baseline"] = (merged["pred_baseline"] == merged["label"]).astype(int)
    merged["correct_similarity"] = (merged["pred_similarity"] == merged["label"]).astype(int)
    merged["error_baseline"] = 1 - merged["correct_baseline"]
    merged["error_similarity"] = 1 - merged["correct_similarity"]
    merged["pred_or"] = ((merged["pred_baseline"] == 1) | (merged["pred_similarity"] == 1)).astype(int)
    merged["pred_and"] = ((merged["pred_baseline"] == 1) & (merged["pred_similarity"] == 1)).astype(int)

    both_correct = int(((merged["correct_baseline"] == 1) & (merged["correct_similarity"] == 1)).sum())
    baseline_only = int(((merged["correct_baseline"] == 1) & (merged["correct_similarity"] == 0)).sum())
    similarity_only = int(((merged["correct_baseline"] == 0) & (merged["correct_similarity"] == 1)).sum())
    both_wrong = int(((merged["correct_baseline"] == 0) & (merged["correct_similarity"] == 0)).sum())
    disagreement = int((merged["pred_baseline"] != merged["pred_similarity"]).sum())

    baseline_metrics = metrics_from_pred(merged, "pred_baseline")
    similarity_metrics = metrics_from_pred(merged, "pred_similarity")
    or_metrics = metrics_from_pred(merged, "pred_or")
    and_metrics = metrics_from_pred(merged, "pred_and")

    fusion_ready = bool(
        disagreement >= 2
        and (baseline_only > 0 or similarity_only > 0)
        and both_wrong < max(1, disagreement)
    )

    merged.to_csv(os.path.join(args.output_dir, "phase3_fusion_readiness_detail.csv"), index=False, encoding="utf-8-sig")

    result = {
        "inputs": {
            "baseline_csv": args.baseline_csv,
            "similarity_csv": args.similarity_csv,
        },
        "branch_metrics": {
            "baseline": baseline_metrics,
            "similarity": similarity_metrics,
            "or_rule": or_metrics,
            "and_rule": and_metrics,
        },
        "complementarity": {
            "both_correct": both_correct,
            "baseline_only_correct": baseline_only,
            "similarity_only_correct": similarity_only,
            "both_wrong": both_wrong,
            "prediction_disagreement": disagreement,
            "fusion_ready": fusion_ready,
        },
        "decision": {
            "go_to_light_fusion": fusion_ready,
            "reason": (
                "Branches show usable disagreement/complementarity."
                if fusion_ready
                else "Branches currently lack enough complementary errors; keep them as parallel candidates, not a fused primary path."
            ),
        },
        "outputs": {
            "detail_csv": os.path.join(args.output_dir, "phase3_fusion_readiness_detail.csv"),
            "report_md": os.path.join(args.output_dir, "phase3_fusion_readiness_report.md"),
            "report_json": os.path.join(args.output_dir, "phase3_fusion_readiness_report.json"),
        },
    }

    lines = [
        "# 轻量融合准备度诊断",
        "",
        f"- 是否进入轻量融合：`{result['decision']['go_to_light_fusion']}`",
        f"- 原因：{result['decision']['reason']}",
        "",
        "## 分支表现",
        "",
        f"- baseline run_balanced_accuracy=`{baseline_metrics['run_balanced_accuracy']}`",
        f"- similarity run_balanced_accuracy=`{similarity_metrics['run_balanced_accuracy']}`",
        f"- OR 规则 run_balanced_accuracy=`{or_metrics['run_balanced_accuracy']}`",
        f"- AND 规则 run_balanced_accuracy=`{and_metrics['run_balanced_accuracy']}`",
        "",
        "## 互补性",
        "",
        f"- both_correct=`{both_correct}`",
        f"- baseline_only_correct=`{baseline_only}`",
        f"- similarity_only_correct=`{similarity_only}`",
        f"- both_wrong=`{both_wrong}`",
        f"- prediction_disagreement=`{disagreement}`",
        "",
    ]
    with open(result["outputs"]["report_md"], "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    with open(result["outputs"]["report_json"], "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
