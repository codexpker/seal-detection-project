#!/usr/bin/env python3
import argparse
import json
import os
from typing import Any, Dict

import pandas as pd


POSITIVE_LABELS = {"positive_reference", "positive", "static_positive", "unsealed"}
NEGATIVE_LABELS = {"negative_reference", "negative", "static_negative", "sealed", "healthy"}
TRANSITION_LABELS = {"transition_positive", "transition", "transition_mainfield"}
BREATHING_LABELS = {"breathing_watch", "breathing", "hard_case"}
CONFOUND_LABELS = {"confound", "heatoff_confound", "heat_off_confound"}
UNCERTAIN_LABELS = {"uncertain", "skip", "watch"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Feedback loop v2 for new_data segment review labels on v3 guarded queue")
    parser.add_argument("--labels-csv", required=True)
    parser.add_argument(
        "--segment-support-csv",
        default="reports/new_data_segment_static_support_v3_run1/segment_support_output_v3.csv",
    )
    parser.add_argument(
        "--review-queue-csv",
        default="reports/new_data_segment_static_support_v3_run1/segment_review_queue_v3.csv",
    )
    parser.add_argument(
        "--output-dir",
        default="reports/new_data_segment_feedback_loop_v2_run1",
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

    merged["review_status_v3"] = "pending"
    merged.loc[merged["review_label"].isin(["positive_reference", "negative_reference", "transition_positive", "breathing_watch", "confound"]), "review_status_v3"] = "reviewed"
    merged.loc[merged["review_label"].eq("uncertain"), "review_status_v3"] = "reviewed_uncertain"
    merged["feedback_action_v2"] = "no_change"
    merged.loc[merged["review_label"].eq("positive_reference"), "feedback_action_v2"] = "promote_static_positive"
    merged.loc[merged["review_label"].eq("negative_reference"), "feedback_action_v2"] = "promote_static_negative"
    merged.loc[merged["review_label"].eq("transition_positive"), "feedback_action_v2"] = "confirm_transition_primary"
    merged.loc[merged["review_label"].eq("breathing_watch"), "feedback_action_v2"] = "confirm_breathing_watch"
    merged.loc[merged["review_label"].eq("confound"), "feedback_action_v2"] = "confirm_confound_watch"
    merged.loc[merged["review_label"].eq("uncertain"), "feedback_action_v2"] = "keep_pending_uncertain"
    return merged


def build_reference_sets(segment_df: pd.DataFrame, merged_review_df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    merged = segment_df.merge(
        merged_review_df[["segment_id", "review_label", "review_status_v3", "feedback_action_v2", "reviewer", "review_note"]],
        on="segment_id",
        how="left",
    )
    return {
        "merged_df": merged,
        "positive_df": merged[merged["review_label"].eq("positive_reference")].copy(),
        "negative_df": merged[merged["review_label"].eq("negative_reference")].copy(),
        "transition_df": merged[merged["review_label"].eq("transition_positive")].copy(),
        "breathing_df": merged[merged["review_label"].eq("breathing_watch")].copy(),
        "confound_df": merged[merged["review_label"].eq("confound")].copy(),
    }


def rerank_pending(merged_review_df: pd.DataFrame, segment_df: pd.DataFrame) -> pd.DataFrame:
    pending = merged_review_df[merged_review_df["review_status_v3"].eq("pending")].copy()
    if pending.empty:
        return pending

    required_cols = [
        "support_status_v3",
        "support_risk_v3",
        "guard_feature_score_v3",
        "memory_role_v2",
        "anomaly_advantage_v2",
    ]
    missing_cols = [c for c in required_cols if c not in pending.columns]
    if missing_cols:
        support = segment_df[
            [
                "segment_id",
                "run_id",
                "support_status_v3",
                "support_risk_v3",
                "guard_feature_score_v3",
                "predicted_memory_role_v2",
                "anomaly_advantage_v2",
            ]
        ].copy()
        support = support.rename(columns={"predicted_memory_role_v2": "memory_role_v2"})
        pending = pending.merge(support, on=["segment_id", "run_id"], how="left")

    priority_map = {
        "transition_primary_support": 0,
        "static_review_weak_positive_guarded": 2,
        "static_watch_breathing_hardguard": 3,
        "static_watch_confound_hardguard": 5,
        "transition_secondary_control": 7,
    }
    memory_bonus = {"anomaly_reference": 0, "hard_negative": 1, "health_core": 2}
    pending["rerank_priority_v2"] = pending["support_status_v3"].map(priority_map).fillna(99)
    pending["memory_bonus_v2"] = pending["memory_role_v2"].map(memory_bonus).fillna(9)
    pending["sort_anomaly_adv_v2"] = pending["anomaly_advantage_v2"].fillna(-999.0)
    pending["sort_guard_v2"] = pending["guard_feature_score_v3"].fillna(-1.0)
    pending = pending.sort_values(
        ["rerank_priority_v2", "memory_bonus_v2", "sort_anomaly_adv_v2", "sort_guard_v2"],
        ascending=[True, True, False, False],
    ).reset_index(drop=True)
    return pending


def build_summary(merged_review_df: pd.DataFrame, ref_sets: Dict[str, pd.DataFrame], reranked_pending_df: pd.DataFrame) -> Dict[str, Any]:
    return {
        "review_rows": int(len(merged_review_df)),
        "reviewed_rows": int(merged_review_df["review_status_v3"].isin(["reviewed", "reviewed_uncertain"]).sum()),
        "positive_reference_segments": int(len(ref_sets["positive_df"])),
        "negative_reference_segments": int(len(ref_sets["negative_df"])),
        "transition_positive_segments": int(len(ref_sets["transition_df"])),
        "breathing_watch_segments": int(len(ref_sets["breathing_df"])),
        "confound_segments": int(len(ref_sets["confound_df"])),
        "pending_segments": int(len(reranked_pending_df)),
        "top_pending_segments": reranked_pending_df[["segment_id", "support_status_v3", "memory_role_v2"]].head(5).to_dict(orient="records")
        if not reranked_pending_df.empty
        else [],
    }


def write_markdown(path: str, summary: Dict[str, Any], reranked_pending_df: pd.DataFrame) -> None:
    lines = [
        "# New Data Segment Feedback Loop v2",
        "",
        "- 目的：把 `segment_review_queue_v3` 的人工复核结果沉淀成段级参考池，并按 `tri-memory + guard` 结果重排剩余待复核段。",
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
            f"- {row['segment_id']} | support_status={row['support_status_v3']} | "
            f"memory={row['memory_role_v2'] if pd.notna(row['memory_role_v2']) else 'nan'} | "
            f"anomaly_adv={row['anomaly_advantage_v2'] if pd.notna(row['anomaly_advantage_v2']) else 'nan'} | "
            f"guard={row['guard_feature_score_v3'] if pd.notna(row['guard_feature_score_v3']) else 'nan'}"
        )

    lines.extend(
        [
            "",
            "## 当前判断",
            "",
            "- 这一步不改主判定链，只把你的人工判断沉淀成更稳的段级参考池和难例池。",
            "- 剩余 pending 会优先参考 `tri-memory` 和 `guard` 结果做重排，而不是只看局部静态分数。",
            "- 这一步服务的是“把第二阶段闭环跑稳”，不是继续堆新模型。",
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
        "merged_review_csv": os.path.join(args.output_dir, "segment_review_feedback_merged_v2.csv"),
        "positive_reference_csv": os.path.join(args.output_dir, "confirmed_positive_reference_segments_v2.csv"),
        "negative_reference_csv": os.path.join(args.output_dir, "confirmed_negative_reference_segments_v2.csv"),
        "transition_positive_csv": os.path.join(args.output_dir, "confirmed_transition_segments_v2.csv"),
        "breathing_watch_csv": os.path.join(args.output_dir, "confirmed_breathing_segments_v2.csv"),
        "confound_csv": os.path.join(args.output_dir, "confirmed_confound_segments_v2.csv"),
        "reranked_pending_csv": os.path.join(args.output_dir, "pending_segment_review_reranked_v2.csv"),
        "report_md": os.path.join(args.output_dir, "segment_feedback_report_v2.md"),
        "report_json": os.path.join(args.output_dir, "segment_feedback_report_v2.json"),
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
