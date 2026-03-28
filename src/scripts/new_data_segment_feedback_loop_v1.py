#!/usr/bin/env python3
import argparse
import json
import os
from typing import Any, Dict, List

import pandas as pd


POSITIVE_LABELS = {"positive_reference", "positive", "static_positive", "unsealed"}
NEGATIVE_LABELS = {"negative_reference", "negative", "static_negative", "sealed", "healthy"}
TRANSITION_LABELS = {"transition_positive", "transition", "transition_mainfield"}
BREATHING_LABELS = {"breathing_watch", "breathing", "hard_case"}
CONFOUND_LABELS = {"confound", "heatoff_confound", "heat_off_confound"}
UNCERTAIN_LABELS = {"uncertain", "skip", "watch"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Feedback loop for new_data segment review labels")
    parser.add_argument("--labels-csv", required=True)
    parser.add_argument(
        "--segment-support-csv",
        default="reports/new_data_segment_static_support_v2_run1/segment_support_output_v2.csv",
    )
    parser.add_argument(
        "--review-queue-csv",
        default="reports/new_data_segment_static_support_v2_run1/segment_review_queue_v2.csv",
    )
    parser.add_argument(
        "--output-dir",
        default="reports/new_data_segment_feedback_loop_v1_run1",
    )
    return parser.parse_args()


def normalize_label(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value or "").strip().lower()
    if text == "":
        return ""
    if text in POSITIVE_LABELS:
        return "positive_reference"
    if text in NEGATIVE_LABELS:
        return "negative_reference"
    if text in TRANSITION_LABELS:
        return "transition_positive"
    if text in BREATHING_LABELS:
        return "breathing_watch"
    if text in CONFOUND_LABELS:
        return "confound"
    if text in UNCERTAIN_LABELS:
        return "uncertain"
    return "unknown"


def merge_labels(review_df: pd.DataFrame, labels_df: pd.DataFrame) -> pd.DataFrame:
    labels = labels_df.copy()
    labels["review_label"] = labels["review_label"].map(normalize_label)
    merged = review_df.merge(
        labels[["segment_id", "review_label", "reviewer", "review_note"]],
        on="segment_id",
        how="left",
        suffixes=("", "_new"),
    )
    for col in ["review_label", "reviewer", "review_note"]:
        new_col = f"{col}_new"
        if new_col in merged.columns:
            merged[col] = merged[new_col]
            merged = merged.drop(columns=[new_col])

    merged["review_status_v2"] = "pending"
    merged.loc[merged["review_label"].isin(["positive_reference", "negative_reference", "transition_positive", "breathing_watch", "confound"]), "review_status_v2"] = "reviewed"
    merged.loc[merged["review_label"].eq("uncertain"), "review_status_v2"] = "reviewed_uncertain"
    merged["feedback_action_v1"] = "no_change"
    merged.loc[merged["review_label"].eq("positive_reference"), "feedback_action_v1"] = "promote_static_positive"
    merged.loc[merged["review_label"].eq("negative_reference"), "feedback_action_v1"] = "promote_static_negative"
    merged.loc[merged["review_label"].eq("transition_positive"), "feedback_action_v1"] = "confirm_transition_primary"
    merged.loc[merged["review_label"].eq("breathing_watch"), "feedback_action_v1"] = "confirm_breathing_watch"
    merged.loc[merged["review_label"].eq("confound"), "feedback_action_v1"] = "confirm_confound_watch"
    merged.loc[merged["review_label"].eq("uncertain"), "feedback_action_v1"] = "keep_pending_uncertain"
    return merged


def build_reference_sets(segment_df: pd.DataFrame, merged_review_df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    merged = segment_df.merge(
        merged_review_df[["segment_id", "review_label", "review_status_v2", "feedback_action_v1", "reviewer", "review_note"]],
        on="segment_id",
        how="left",
    )

    positive_df = merged[merged["review_label"].eq("positive_reference")].copy()
    negative_df = merged[merged["review_label"].eq("negative_reference")].copy()
    transition_df = merged[merged["review_label"].eq("transition_positive")].copy()
    breathing_df = merged[merged["review_label"].eq("breathing_watch")].copy()
    confound_df = merged[merged["review_label"].eq("confound")].copy()
    return {
        "merged_df": merged,
        "positive_df": positive_df,
        "negative_df": negative_df,
        "transition_df": transition_df,
        "breathing_df": breathing_df,
        "confound_df": confound_df,
    }


def rerank_pending(merged_review_df: pd.DataFrame, segment_df: pd.DataFrame) -> pd.DataFrame:
    pending = merged_review_df[merged_review_df["review_status_v2"].eq("pending")].copy()
    if pending.empty:
        return pending

    required_cols = [
        "support_status_v2",
        "support_risk_v2",
        "weak_positive_support_score_v2",
        "breathing_suppression_score_v2",
        "confound_reject_score_v2",
    ]
    missing_cols = [c for c in required_cols if c not in pending.columns]
    if missing_cols:
        support = segment_df[
            [
                "segment_id",
                "run_id",
                "support_status_v2",
                "support_risk_v2",
                "weak_positive_support_score_v2",
                "breathing_suppression_score_v2",
                "confound_reject_score_v2",
            ]
        ].copy()
        pending = pending.merge(support, on=["segment_id", "run_id"], how="left")

    priority_map = {
        "transition_primary_support": 0,
        "static_supported_weak_positive": 1,
        "static_review_weak_positive": 2,
        "static_watch_breathing_confirmed": 3,
        "static_watch_breathing": 4,
        "static_watch_confound_confirmed": 5,
        "static_watch_confound": 6,
        "transition_secondary_control": 7,
    }
    pending["rerank_priority_v1"] = pending["support_status_v2"].map(priority_map).fillna(99)
    pending["sort_weak_support"] = pending["weak_positive_support_score_v2"].fillna(-1.0)
    pending["sort_breathing"] = pending["breathing_suppression_score_v2"].fillna(-1.0)
    pending["sort_confound"] = pending["confound_reject_score_v2"].fillna(-1.0)
    pending = pending.sort_values(
        ["rerank_priority_v1", "sort_weak_support", "sort_confound", "sort_breathing"],
        ascending=[True, False, False, False],
    ).reset_index(drop=True)
    return pending


def build_summary(
    merged_review_df: pd.DataFrame,
    ref_sets: Dict[str, pd.DataFrame],
    reranked_pending_df: pd.DataFrame,
) -> Dict[str, Any]:
    return {
        "review_rows": int(len(merged_review_df)),
        "reviewed_rows": int(merged_review_df["review_status_v2"].isin(["reviewed", "reviewed_uncertain"]).sum()),
        "positive_reference_segments": int(len(ref_sets["positive_df"])),
        "negative_reference_segments": int(len(ref_sets["negative_df"])),
        "transition_positive_segments": int(len(ref_sets["transition_df"])),
        "breathing_watch_segments": int(len(ref_sets["breathing_df"])),
        "confound_segments": int(len(ref_sets["confound_df"])),
        "pending_segments": int(len(reranked_pending_df)),
        "top_pending_segments": reranked_pending_df[["segment_id", "support_status_v2"]].head(5).to_dict(orient="records")
        if not reranked_pending_df.empty
        else [],
    }


def write_markdown(path: str, summary: Dict[str, Any], reranked_pending_df: pd.DataFrame) -> None:
    lines = [
        "# New Data Segment Feedback Loop v1",
        "",
        "- 目的：把 `segment_review_queue_v2` 的人工复核结果沉淀成段级正参考、负参考、breathing hard case、confound challenge，并对剩余段重新排序。",
        "",
        f"- review_rows：`{summary['review_rows']}`",
        f"- reviewed_rows：`{summary['reviewed_rows']}`",
        f"- positive_reference_segments：`{summary['positive_reference_segments']}`",
        f"- negative_reference_segments：`{summary['negative_reference_segments']}`",
        f"- transition_positive_segments：`{summary['transition_positive_segments']}`",
        f"- breathing_watch_segments：`{summary['breathing_watch_segments']}`",
        f"- confound_segments：`{summary['confound_segments']}`",
        f"- pending_segments：`{summary['pending_segments']}`",
        "",
        "## 回灌后剩余待复核段",
        "",
    ]
    for _, row in reranked_pending_df.head(8).iterrows():
        lines.append(
            f"- {row['segment_id']} | support_status={row['support_status_v2']} | "
            f"weak_support={row['weak_positive_support_score_v2'] if pd.notna(row['weak_positive_support_score_v2']) else 'nan'} | "
            f"breathing={row['breathing_suppression_score_v2'] if pd.notna(row['breathing_suppression_score_v2']) else 'nan'} | "
            f"confound={row['confound_reject_score_v2'] if pd.notna(row['confound_reject_score_v2']) else 'nan'}"
        )

    lines.extend(
        [
            "",
            "## 当前判断",
            "",
            "- 这一步不改主判定链，只把你的人工判断沉淀成段级参考池和难例池。",
            "- 之后你每确认一批 `positive_reference / negative_reference / breathing_watch / confound`，静态支持层就会越来越稳。",
            "- 所以这一步是把当前第二阶段真正跑成“可持续复核闭环”，而不是继续离线堆特征。",
            "",
        ]
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    labels_df = pd.read_csv(args.labels_csv)
    segment_df = pd.read_csv(args.segment_support_csv)
    review_df = pd.read_csv(args.review_queue_csv)

    merged_review_df = merge_labels(review_df, labels_df)
    ref_sets = build_reference_sets(segment_df, merged_review_df)
    reranked_pending_df = rerank_pending(merged_review_df, segment_df)
    summary = build_summary(merged_review_df, ref_sets, reranked_pending_df)

    outputs = {
        "merged_review_csv": os.path.join(args.output_dir, "segment_review_feedback_merged.csv"),
        "positive_reference_csv": os.path.join(args.output_dir, "confirmed_positive_reference_segments.csv"),
        "negative_reference_csv": os.path.join(args.output_dir, "confirmed_negative_reference_segments.csv"),
        "transition_positive_csv": os.path.join(args.output_dir, "confirmed_transition_segments.csv"),
        "breathing_watch_csv": os.path.join(args.output_dir, "confirmed_breathing_segments.csv"),
        "confound_csv": os.path.join(args.output_dir, "confirmed_confound_segments.csv"),
        "reranked_pending_csv": os.path.join(args.output_dir, "pending_segment_review_reranked.csv"),
        "report_md": os.path.join(args.output_dir, "segment_feedback_report.md"),
        "report_json": os.path.join(args.output_dir, "segment_feedback_report.json"),
    }

    merged_review_df.to_csv(outputs["merged_review_csv"], index=False, encoding="utf-8-sig")
    ref_sets["positive_df"].to_csv(outputs["positive_reference_csv"], index=False, encoding="utf-8-sig")
    ref_sets["negative_df"].to_csv(outputs["negative_reference_csv"], index=False, encoding="utf-8-sig")
    ref_sets["transition_df"].to_csv(outputs["transition_positive_csv"], index=False, encoding="utf-8-sig")
    ref_sets["breathing_df"].to_csv(outputs["breathing_watch_csv"], index=False, encoding="utf-8-sig")
    ref_sets["confound_df"].to_csv(outputs["confound_csv"], index=False, encoding="utf-8-sig")
    reranked_pending_df.to_csv(outputs["reranked_pending_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["report_md"], summary, reranked_pending_df)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
