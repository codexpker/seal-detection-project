#!/usr/bin/env python3
import argparse
import json
import os
from typing import Any, Dict

import pandas as pd


LABEL_OPTIONS = [
    "positive_reference",
    "negative_reference",
    "transition_positive",
    "breathing_watch",
    "confound",
    "uncertain",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate segment-level review label template from segment_review_queue_v2")
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
        default="reports/new_data_segment_review_label_template_v1_run1",
    )
    return parser.parse_args()


def build_template(review_df: pd.DataFrame, segment_df: pd.DataFrame) -> pd.DataFrame:
    merged = review_df.merge(
        segment_df[
            [
                "segment_id",
                "static_bucket",
                "primary_task",
                "segment_role",
                "segment_source",
                "segment_seal_state",
                "segment_hours",
                "transition_bucket",
            ]
        ],
        on="segment_id",
        how="left",
    )
    merged["review_label"] = ""
    merged["reviewer"] = ""
    merged["review_note"] = ""
    merged["label_options"] = "|".join(LABEL_OPTIONS)
    merged["recommended_focus"] = merged["support_status_v2"].map(
        {
            "transition_primary_support": "先确认是否为真实主战场 transition 正样本",
            "static_supported_weak_positive": "先确认是否可升级为段级正参考",
            "static_watch_breathing_confirmed": "先确认是否属于密封呼吸难例",
            "static_watch_confound_confirmed": "先确认是否属于 heat-off 混淆段",
            "transition_secondary_control": "先确认是否仅作控制 transition，不进入主战场",
        }
    ).fillna("按段级证据人工复核")

    cols = [
        "segment_id",
        "run_id",
        "review_label",
        "reviewer",
        "review_note",
        "segment_name",
        "support_status_v2",
        "support_risk_v2",
        "support_reason_v2",
        "weak_positive_support_score_v2",
        "breathing_suppression_score_v2",
        "confound_reject_score_v2",
        "review_priority_v2",
        "primary_task",
        "segment_role",
        "segment_source",
        "segment_seal_state",
        "segment_hours",
        "static_bucket",
        "transition_bucket",
        "label_options",
        "recommended_focus",
    ]
    keep = [c for c in cols if c in merged.columns]
    return merged[keep].sort_values(["review_priority_v2", "run_id", "segment_name"]).reset_index(drop=True)


def build_summary(template_df: pd.DataFrame) -> Dict[str, Any]:
    return {
        "row_count": int(len(template_df)),
        "review_priority_counts": template_df["review_priority_v2"].value_counts(dropna=False).to_dict()
        if "review_priority_v2" in template_df.columns and not template_df.empty
        else {},
        "support_status_counts": template_df["support_status_v2"].value_counts(dropna=False).to_dict()
        if "support_status_v2" in template_df.columns and not template_df.empty
        else {},
    }


def write_markdown(path: str, summary: Dict[str, Any], outputs: Dict[str, str]) -> None:
    lines = [
        "# Segment Review Label Template v1",
        "",
        "- 目的：把 `segment_review_queue_v2` 压成可填写的段级真实复核模板，供后续 `segment feedback loop` 回灌使用。",
        "",
        f"- row_count：`{summary['row_count']}`",
        f"- review_priority_counts：`{summary['review_priority_counts']}`",
        f"- support_status_counts：`{summary['support_status_counts']}`",
        "",
        "## 输出文件",
        "",
        f"- template_csv: `{outputs['template_csv']}`",
        "",
        "## 填写要求",
        "",
        "- 回灌脚本实际读取：`segment_id, review_label, reviewer, review_note`。",
        "- 推荐标签：`positive_reference`、`negative_reference`、`transition_positive`、`breathing_watch`、`confound`、`uncertain`。",
        "- `transition_primary_support` 优先标 `transition_positive`。",
        "- `static_supported_weak_positive` 优先在 `positive_reference` 和 `uncertain` 之间确认。",
        "- `static_watch_breathing_confirmed` 优先标 `breathing_watch`。",
        "- `static_watch_confound_confirmed` 优先标 `confound`。",
        "",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    review_df = pd.read_csv(args.review_queue_csv)
    segment_df = pd.read_csv(args.segment_support_csv)
    template_df = build_template(review_df, segment_df)
    summary = build_summary(template_df)

    outputs = {
        "template_csv": os.path.join(args.output_dir, "segment_review_labels_template.csv"),
        "report_md": os.path.join(args.output_dir, "segment_review_label_template_report.md"),
        "report_json": os.path.join(args.output_dir, "segment_review_label_template_report.json"),
    }
    template_df.to_csv(outputs["template_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["report_md"], summary, outputs)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
