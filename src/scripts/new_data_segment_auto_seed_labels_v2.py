#!/usr/bin/env python3
import argparse
import json
import os
from typing import Any, Dict, List

import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate conservative auto-seed labels from segment_review_queue_v3")
    parser.add_argument(
        "--review-queue-csv",
        default="reports/new_data_segment_static_support_v3_run1/segment_review_queue_v3.csv",
    )
    parser.add_argument(
        "--output-dir",
        default="reports/new_data_segment_auto_seed_labels_v2_run1",
    )
    return parser.parse_args()


def build_seed_df(review_df: pd.DataFrame) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for _, row in review_df.iterrows():
        status = str(row.get("support_status_v3", "") or "")
        label = ""
        note = ""
        if status == "transition_primary_support":
            label = "transition_positive"
            note = "mainfield transition post-change segment with strongest evidence"
        elif status == "static_watch_breathing_hardguard":
            label = "breathing_watch"
            note = "guarded breathing hard case confirmed by tri-memory hard-negative side"
        elif status == "static_watch_confound_hardguard":
            label = "confound"
            note = "guarded confound segment confirmed by tri-memory hard-negative side"
        else:
            label = ""
            note = ""

        rows.append(
            {
                "run_id": row.get("run_id", ""),
                "segment_id": row.get("segment_id", ""),
                "segment_name": row.get("segment_name", ""),
                "support_status_v3": status,
                "support_risk_v3": row.get("support_risk_v3", ""),
                "guard_feature_score_v3": row.get("guard_feature_score_v3", ""),
                "memory_role_v2": row.get("memory_role_v2", ""),
                "anomaly_advantage_v2": row.get("anomaly_advantage_v2", ""),
                "support_reason_v3": row.get("support_reason_v3", ""),
                "review_priority_v3": row.get("review_priority_v3", ""),
                "review_label": label,
                "reviewer": "codex_auto_seed_v2" if label else "",
                "review_note": note,
            }
        )
    return pd.DataFrame(rows)


def build_summary(seed_df: pd.DataFrame) -> Dict[str, Any]:
    labeled = seed_df[seed_df["review_label"].astype(str) != ""].copy()
    return {
        "row_count": int(len(seed_df)),
        "seeded_rows": int(len(labeled)),
        "seed_label_counts": labeled["review_label"].value_counts(dropna=False).to_dict() if not labeled.empty else {},
    }


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    review_df = pd.read_csv(args.review_queue_csv)
    seed_df = build_seed_df(review_df)
    summary = build_summary(seed_df)

    outputs = {
        "seed_csv": os.path.join(args.output_dir, "segment_review_labels_auto_seed_v2.csv"),
        "report_json": os.path.join(args.output_dir, "segment_auto_seed_report_v2.json"),
    }
    seed_df.to_csv(outputs["seed_csv"], index=False, encoding="utf-8-sig")
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
