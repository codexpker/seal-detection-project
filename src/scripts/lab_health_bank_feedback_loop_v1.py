#!/usr/bin/env python3
import argparse
import json
import os
import sys
from typing import Any, Dict, List

import pandas as pd

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.scripts.lab_health_window_bank_similarity_v1 import (
    BANKABLE_LABELS,
    aggregate_runs,
    build_health_bank,
    build_summary as build_similarity_summary,
    load_or_build_interface,
    prepare_window_view,
    score_windows,
    summarize_bank,
)
from src.scripts.lab_phase1_acceptance import Phase1Config


HEALTHY_LABELS = {"healthy", "normal", "sealed", "seal", "false", "fp"}
ANOMALY_LABELS = {"anomaly", "abnormal", "unsealed", "unseal", "true", "tp", "leak"}
UNCERTAIN_LABELS = {"uncertain", "watch", "skip", ""}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Feedback loop for health bank review labels")
    parser.add_argument("--labels-csv", required=True, help="CSV with run_id,review_label,reviewer,review_note")
    parser.add_argument("--run-manifest-csv", default="")
    parser.add_argument("--window-table-csv", default="")
    parser.add_argument("--review-output-csv", default="")
    parser.add_argument("--input-dir", default=Phase1Config.input_dir)
    parser.add_argument("--input-zip", default=Phase1Config.input_zip)
    parser.add_argument("--metadata-xlsx", default=Phase1Config.metadata_xlsx)
    parser.add_argument("--output-dir", default="reports/lab_health_bank_feedback_loop_v1")
    parser.add_argument("--window-hours", type=int, default=12)
    parser.add_argument("--step-hours", type=int, default=1)
    parser.add_argument("--transition-near-hours", type=int, default=6)
    parser.add_argument("--similarity-k", type=int, default=5)
    parser.add_argument("--min-bank-windows", type=int, default=5)
    return parser.parse_args()


def normalize_review_label(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in HEALTHY_LABELS:
        return "healthy"
    if text in ANOMALY_LABELS:
        return "anomaly"
    if text in UNCERTAIN_LABELS:
        return "uncertain"
    return "unknown"


def merge_labels(review_df: pd.DataFrame, labels_df: pd.DataFrame) -> pd.DataFrame:
    labels = labels_df.copy()
    labels["review_label"] = labels["review_label"].map(normalize_review_label)
    merged = review_df.merge(
        labels[["run_id", "review_label", "reviewer", "review_note"]],
        on="run_id",
        how="left",
        suffixes=("", "_new"),
    )
    for col in ["review_label", "reviewer", "review_note"]:
        new_col = f"{col}_new"
        if new_col in merged.columns:
            merged[col] = merged[new_col].where(merged[new_col].notna(), merged[col])
            merged = merged.drop(columns=[new_col])

    merged["feedback_action"] = "no_change"
    merged.loc[merged["review_label"] == "healthy", "feedback_action"] = "promote_to_health_candidate"
    merged.loc[merged["review_label"] == "anomaly", "feedback_action"] = "mark_as_anomaly_reference"
    merged.loc[merged["review_label"] == "uncertain", "feedback_action"] = "keep_pending_uncertain"

    merged["review_status"] = merged["review_status"].astype(str)
    merged.loc[merged["review_label"].isin(["healthy", "anomaly"]), "review_status"] = "reviewed"
    merged.loc[merged["review_label"] == "uncertain", "review_status"] = "reviewed_uncertain"
    return merged


def build_promoted_health_windows(window_df: pd.DataFrame, merged_review_df: pd.DataFrame) -> pd.DataFrame:
    approved_runs = merged_review_df[
        (merged_review_df["review_label"] == "healthy")
        & (~merged_review_df["condition_family_manual"].eq("transition_run"))
    ]["run_id"].dropna().tolist()
    promoted = window_df[
        window_df["run_id"].isin(approved_runs)
        & window_df["label_coarse"].isin(BANKABLE_LABELS)
    ].copy()
    if promoted.empty:
        return promoted
    promoted["bank_source"] = "review_promoted"
    return promoted


def build_anomaly_reference_runs(merged_review_df: pd.DataFrame) -> pd.DataFrame:
    anomaly_runs = merged_review_df[merged_review_df["review_label"] == "anomaly"].copy()
    if anomaly_runs.empty:
        return anomaly_runs
    anomaly_runs["reference_type"] = "review_confirmed_anomaly"
    return anomaly_runs


def refresh_similarity_after_feedback(
    window_df: pd.DataFrame,
    run_manifest_df: pd.DataFrame,
    merged_review_df: pd.DataFrame,
    promoted_windows_df: pd.DataFrame,
    args: argparse.Namespace,
) -> Dict[str, pd.DataFrame]:
    base_bank_df = build_health_bank(window_df)
    updated_bank_df = pd.concat([base_bank_df, promoted_windows_df], ignore_index=True)
    if not updated_bank_df.empty:
        updated_bank_df = updated_bank_df.drop_duplicates(subset=["run_id", "window_id"], keep="last").reset_index(drop=True)

    pending_run_ids = merged_review_df.loc[merged_review_df["review_status"] == "pending", "run_id"].dropna().tolist()
    query_window_df = window_df[window_df["run_id"].isin(pending_run_ids)].copy()
    scored_window_df = score_windows(query_window_df, updated_bank_df, k=args.similarity_k, min_bank_windows=args.min_bank_windows)

    reranked_run_df = aggregate_runs(scored_window_df, run_manifest_df, merged_review_df)
    return {
        "updated_bank_df": updated_bank_df,
        "reranked_window_df": scored_window_df,
        "reranked_run_df": reranked_run_df,
    }


def build_summary(
    merged_review_df: pd.DataFrame,
    promoted_windows_df: pd.DataFrame,
    anomaly_runs_df: pd.DataFrame,
    feedback_outputs: Dict[str, pd.DataFrame],
) -> Dict[str, Any]:
    updated_bank_df = feedback_outputs["updated_bank_df"]
    reranked_run_df = feedback_outputs["reranked_run_df"]
    similarity_summary = build_similarity_summary(updated_bank_df, feedback_outputs["reranked_window_df"], reranked_run_df)
    return {
        "review_rows": int(len(merged_review_df)),
        "reviewed_rows": int(merged_review_df["review_status"].isin(["reviewed", "reviewed_uncertain"]).sum()),
        "promoted_health_runs": int(promoted_windows_df["run_id"].nunique()) if not promoted_windows_df.empty else 0,
        "promoted_health_windows": int(len(promoted_windows_df)),
        "anomaly_reference_runs": int(len(anomaly_runs_df)),
        "updated_health_bank_runs": int(updated_bank_df["run_id"].nunique()) if not updated_bank_df.empty else 0,
        "updated_health_bank_windows": int(len(updated_bank_df)),
        "reranked_pending_runs": int(len(reranked_run_df)),
        "top_reranked_runs": (
            reranked_run_df[["run_id", "rank_score", "final_status"]].head(5).to_dict(orient="records")
            if not reranked_run_df.empty
            else []
        ),
        "similarity_summary": similarity_summary,
    }


def write_markdown(path: str, summary: Dict[str, Any], reranked_run_df: pd.DataFrame) -> None:
    lines = [
        "# Health Bank Feedback Loop v1",
        "",
        "- 目的：把 `review_output` 的人工复核结果真正回灌到健康窗口库和后续相似性排序中，形成增量闭环。",
        "",
        f"- review_rows：`{summary['review_rows']}`",
        f"- reviewed_rows：`{summary['reviewed_rows']}`",
        f"- promoted_health_runs：`{summary['promoted_health_runs']}`",
        f"- promoted_health_windows：`{summary['promoted_health_windows']}`",
        f"- anomaly_reference_runs：`{summary['anomaly_reference_runs']}`",
        f"- updated_health_bank_runs：`{summary['updated_health_bank_runs']}`",
        f"- updated_health_bank_windows：`{summary['updated_health_bank_windows']}`",
        f"- reranked_pending_runs：`{summary['reranked_pending_runs']}`",
        "",
        "## 回灌后待复核风险排序",
        "",
    ]
    for _, row in reranked_run_df.head(8).iterrows():
        lines.append(
            f"- {row['run_id']} | rank_score={row['rank_score']:.3f} | final_status={row['final_status']} | "
            f"review_status={row['review_status']}"
        )

    lines.extend(
        [
            "",
            "## 当前判断",
            "",
            "- 这一步不改变现有主判定链，只把人工复核结果沉淀成健康参考或异常参考。",
            "- 后续只要持续补充 `healthy` 复核样本，健康窗口库就可以按设备逐步扩容；相似性排序也会随之变得更稳。",
            "- 因此这条线已经具备了从实验室过渡到现场“历史健康窗口库”闭环的最小工程结构。",
            "",
        ]
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    run_manifest_df, window_table_df, review_df = load_or_build_interface(args)
    window_df = prepare_window_view(run_manifest_df, window_table_df, review_df)
    labels_df = pd.read_csv(args.labels_csv)
    merged_review_df = merge_labels(review_df, labels_df)
    promoted_windows_df = build_promoted_health_windows(window_df, merged_review_df)
    anomaly_runs_df = build_anomaly_reference_runs(merged_review_df)
    feedback_outputs = refresh_similarity_after_feedback(window_df, run_manifest_df, merged_review_df, promoted_windows_df, args)
    summary = build_summary(merged_review_df, promoted_windows_df, anomaly_runs_df, feedback_outputs)

    outputs = {
        "merged_review_csv": os.path.join(args.output_dir, "review_feedback_merged.csv"),
        "promoted_health_windows_csv": os.path.join(args.output_dir, "promoted_health_windows.csv"),
        "anomaly_reference_runs_csv": os.path.join(args.output_dir, "anomaly_reference_runs.csv"),
        "updated_health_bank_csv": os.path.join(args.output_dir, "updated_health_window_bank.csv"),
        "reranked_window_csv": os.path.join(args.output_dir, "feedback_window_similarity_ranking.csv"),
        "reranked_run_csv": os.path.join(args.output_dir, "feedback_run_similarity_ranking.csv"),
        "report_md": os.path.join(args.output_dir, "health_bank_feedback_report.md"),
        "report_json": os.path.join(args.output_dir, "health_bank_feedback_report.json"),
    }

    merged_review_df.to_csv(outputs["merged_review_csv"], index=False, encoding="utf-8-sig")
    promoted_windows_df.to_csv(outputs["promoted_health_windows_csv"], index=False, encoding="utf-8-sig")
    anomaly_runs_df.to_csv(outputs["anomaly_reference_runs_csv"], index=False, encoding="utf-8-sig")
    feedback_outputs["updated_bank_df"].to_csv(outputs["updated_health_bank_csv"], index=False, encoding="utf-8-sig")
    feedback_outputs["reranked_window_df"].to_csv(outputs["reranked_window_csv"], index=False, encoding="utf-8-sig")
    feedback_outputs["reranked_run_df"].to_csv(outputs["reranked_run_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["report_md"], summary, feedback_outputs["reranked_run_df"])
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
