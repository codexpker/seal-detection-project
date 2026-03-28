#!/usr/bin/env python3
import argparse
import json
import os
from typing import Any, Dict, List

import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate high-confidence auto seed labels for new_data segment review queue")
    parser.add_argument(
        "--review-queue-csv",
        default="reports/new_data_segment_static_support_v2_run1/segment_review_queue_v2.csv",
    )
    parser.add_argument(
        "--segment-support-csv",
        default="reports/new_data_segment_static_support_v2_run1/segment_support_output_v2.csv",
    )
    parser.add_argument(
        "--output-dir",
        default="reports/new_data_segment_auto_seed_labels_v1_run1",
    )
    return parser.parse_args()


def auto_seed_label(row: pd.Series) -> tuple[str, str]:
    status = str(row.get("support_status_v2", "") or "")
    segment_name = str(row.get("segment_name", "") or "")
    support_score = row.get("weak_positive_support_score_v2", pd.NA)
    segment_seal_state = str(row.get("segment_seal_state", "") or "")
    segment_source = str(row.get("segment_source", "") or "")

    if status == "transition_primary_support" and segment_name == "post_change":
        return ("transition_positive", "mainfield transition post-change segment with strongest evidence")
    if (
        status == "static_supported_weak_positive"
        and segment_source == "full_run"
        and segment_seal_state == "unsealed"
        and pd.notna(support_score)
        and float(support_score) >= 1.0
    ):
        return ("positive_reference", "full-run unsealed weak-positive segment upgraded by multiview support score 1.00")
    if status == "static_watch_breathing_confirmed":
        return ("breathing_watch", "sealed segment remains a confirmed breathing hard case")
    if status == "static_watch_confound_confirmed":
        return ("confound", "heat-off post-change segment remains a confirmed confound challenge")
    return ("", "")


def build_auto_seed(review_df: pd.DataFrame, segment_df: pd.DataFrame) -> pd.DataFrame:
    merged = review_df.merge(
        segment_df[
            [
                "segment_id",
                "segment_source",
                "segment_seal_state",
                "segment_hours",
                "support_status_v2",
                "weak_positive_support_score_v2",
                "breathing_suppression_score_v2",
                "confound_reject_score_v2",
            ]
        ],
        on="segment_id",
        how="left",
        suffixes=("", "_segment"),
    )
    labels: List[str] = []
    notes: List[str] = []
    for _, row in merged.iterrows():
        label, note = auto_seed_label(row)
        labels.append(label)
        notes.append(note)

    merged["review_label"] = labels
    merged["reviewer"] = merged["review_label"].map(lambda x: "codex_auto_seed_v1" if str(x).strip() else "")
    merged["review_note"] = notes
    return merged


def build_summary(seed_df: pd.DataFrame) -> Dict[str, Any]:
    labeled = seed_df[seed_df["review_label"].astype(str) != ""].copy()
    return {
        "row_count": int(len(seed_df)),
        "auto_labeled_rows": int(len(labeled)),
        "label_counts": labeled["review_label"].value_counts(dropna=False).to_dict() if not labeled.empty else {},
        "pending_rows": int((seed_df["review_label"].astype(str) == "").sum()),
    }


def write_markdown(path: str, summary: Dict[str, Any], outputs: Dict[str, str]) -> None:
    lines = [
        "# New Data Segment Auto Seed Labels v1",
        "",
        "- 目的：按当前离线分析结果，只对高置信段自动落第一批复核标签，其余继续保持 `pending`。",
        "",
        f"- row_count：`{summary['row_count']}`",
        f"- auto_labeled_rows：`{summary['auto_labeled_rows']}`",
        f"- label_counts：`{summary['label_counts']}`",
        f"- pending_rows：`{summary['pending_rows']}`",
        "",
        "## 自动落标签原则",
        "",
        "- `transition_primary_support` 的 `post_change` 段 -> `transition_positive`",
        "- `static_supported_weak_positive` 且支持分达到最高置信 -> `positive_reference`",
        "- `static_watch_breathing_confirmed` -> `breathing_watch`",
        "- `static_watch_confound_confirmed` -> `confound`",
        "- 其余段保留空白，继续人工复核",
        "",
        "## 输出文件",
        "",
        f"- auto_seed_csv: `{outputs['auto_seed_csv']}`",
        "",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    review_df = pd.read_csv(args.review_queue_csv)
    segment_df = pd.read_csv(args.segment_support_csv)
    seed_df = build_auto_seed(review_df, segment_df)
    summary = build_summary(seed_df)

    outputs = {
        "auto_seed_csv": os.path.join(args.output_dir, "segment_review_labels_auto_seed.csv"),
        "report_md": os.path.join(args.output_dir, "segment_auto_seed_report.md"),
        "report_json": os.path.join(args.output_dir, "segment_auto_seed_report.json"),
    }
    seed_df.to_csv(outputs["auto_seed_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["report_md"], summary, outputs)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
