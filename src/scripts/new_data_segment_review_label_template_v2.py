#!/usr/bin/env python3
import argparse
import json
import os
from typing import Any, Dict, Tuple

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
    parser = argparse.ArgumentParser(description="Generate segment-level review label template from segment_review_queue_v3")
    parser.add_argument(
        "--review-queue-csv",
        default="reports/new_data_segment_static_support_v3_run1/segment_review_queue_v3.csv",
    )
    parser.add_argument(
        "--segment-support-csv",
        default="reports/new_data_segment_static_support_v3_run1/segment_support_output_v3.csv",
    )
    parser.add_argument(
        "--segment-manifest-csv",
        default="reports/new_data_segment_pipeline_v1_run1/segment_pipeline_manifest.csv",
    )
    parser.add_argument(
        "--output-dir",
        default="reports/new_data_segment_review_label_template_v2_run1",
    )
    return parser.parse_args()


def review_stage_and_rank(status: str) -> Tuple[str, int]:
    mapping = {
        "transition_primary_support": ("01_transition_primary", 1),
        "static_review_weak_positive_guarded": ("02_guarded_positive", 2),
        "static_watch_breathing_hardguard": ("03_breathing_watch", 3),
        "static_watch_confound_hardguard": ("04_confound_watch", 4),
        "transition_secondary_control": ("05_transition_secondary", 5),
    }
    return mapping.get(str(status or "").strip(), ("99_other", 99))


def preferred_seed_label(status: str) -> str:
    mapping = {
        "transition_primary_support": "transition_positive",
        "static_review_weak_positive_guarded": "uncertain",
        "static_watch_breathing_hardguard": "breathing_watch",
        "static_watch_confound_hardguard": "confound",
        "transition_secondary_control": "uncertain",
    }
    return mapping.get(str(status or "").strip(), "")


def build_template(review_df: pd.DataFrame, segment_df: pd.DataFrame, manifest_df: pd.DataFrame) -> pd.DataFrame:
    merged = review_df.merge(
        segment_df[
            [
                "segment_id",
                "primary_task",
                "segment_role",
                "segment_source",
                "segment_seal_state",
                "segment_hours",
                "transition_bucket",
                "guard_feature_score_v3",
                "predicted_memory_role_v2",
                "anomaly_advantage_v2",
            ]
        ],
        on="segment_id",
        how="left",
        suffixes=("", "_segment"),
    )
    if not manifest_df.empty:
        manifest_keep = [
            "segment_id",
            "file",
            "device_id",
            "change_type",
            "initial_role",
            "post_role",
            "segment_heat_state",
            "segment_ext_level",
        ]
        merged = merged.merge(
            manifest_df[[col for col in manifest_keep if col in manifest_df.columns]].drop_duplicates("segment_id"),
            on="segment_id",
            how="left",
        )
    merged["review_label"] = ""
    merged["reviewer"] = ""
    merged["review_note"] = ""
    merged["label_options"] = "|".join(LABEL_OPTIONS)
    stage_rank = merged["support_status_v3"].map(review_stage_and_rank)
    merged["review_stage_v1"] = stage_rank.map(lambda x: x[0])
    merged["review_rank_v1"] = stage_rank.map(lambda x: x[1])
    merged["preferred_seed_label_v2"] = merged["support_status_v3"].map(preferred_seed_label)
    merged["recommended_focus"] = merged["support_status_v3"].map(
        {
            "transition_primary_support": "优先确认是否为主战场 transition 正样本",
            "static_review_weak_positive_guarded": "局部正向证据存在，但未通过 hard-negative 守门；优先在 positive_reference 和 uncertain 之间确认",
            "static_watch_breathing_hardguard": "优先确认是否属于密封呼吸/材料呼吸难例",
            "static_watch_confound_hardguard": "优先确认是否属于 heat-off 或类似混淆段",
            "transition_secondary_control": "优先确认是否仅作控制 transition，不进入主战场",
        }
    ).fillna("按段级证据人工复核")

    cols = [
        "segment_id",
        "run_id",
        "review_label",
        "reviewer",
        "review_note",
        "segment_name",
        "support_status_v3",
        "support_risk_v3",
        "support_reason_v3",
        "review_stage_v1",
        "review_rank_v1",
        "preferred_seed_label_v2",
        "guard_feature_score_v3",
        "predicted_memory_role_v2",
        "anomaly_advantage_v2",
        "review_priority_v3",
        "file",
        "device_id",
        "change_type",
        "initial_role",
        "post_role",
        "segment_heat_state",
        "segment_ext_level",
        "primary_task",
        "segment_role",
        "segment_source",
        "segment_seal_state",
        "segment_hours",
        "transition_bucket",
        "label_options",
        "recommended_focus",
    ]
    keep = [c for c in cols if c in merged.columns]
    return merged[keep].sort_values(["review_rank_v1", "review_priority_v3", "run_id", "segment_name"]).reset_index(drop=True)


def build_summary(template_df: pd.DataFrame) -> Dict[str, Any]:
    return {
        "row_count": int(len(template_df)),
        "review_priority_counts": template_df["review_priority_v3"].value_counts(dropna=False).to_dict()
        if "review_priority_v3" in template_df.columns and not template_df.empty
        else {},
        "support_status_counts": template_df["support_status_v3"].value_counts(dropna=False).to_dict()
        if "support_status_v3" in template_df.columns and not template_df.empty
        else {},
        "review_stage_counts": template_df["review_stage_v1"].value_counts(dropna=False).to_dict()
        if "review_stage_v1" in template_df.columns and not template_df.empty
        else {},
    }


def write_markdown(path: str, summary: Dict[str, Any], outputs: Dict[str, str]) -> None:
    lines = [
        "# Segment Review Label Template v2",
        "",
        "- 目的：把 `segment_review_queue_v3` 压成可填写的段级真实复核模板，供 `segment feedback loop v2` 回灌使用。",
        "",
        f"- row_count：`{summary['row_count']}`",
        f"- review_priority_counts：`{summary['review_priority_counts']}`",
        f"- support_status_counts：`{summary['support_status_counts']}`",
        f"- review_stage_counts：`{summary['review_stage_counts']}`",
        "",
        "## 输出文件",
        "",
        f"- template_csv: `{outputs['template_csv']}`",
        "",
        "## 填写要求",
        "",
        "- 回灌脚本实际读取：`segment_id, review_label, reviewer, review_note`。",
        "- `preferred_seed_label_v2` 是保守推荐，不等于最终人工结论。",
        "- `review_stage_v1` 与 `review_rank_v1` 表示建议复核顺序。",
        "- 推荐标签：`positive_reference`、`negative_reference`、`transition_positive`、`breathing_watch`、`confound`、`uncertain`。",
        "- `transition_primary_support` 优先标 `transition_positive`。",
        "- `static_review_weak_positive_guarded` 当前默认不建议自动升为正参考；若无充分把握，优先标 `uncertain`。",
        "- `static_watch_breathing_hardguard` 优先标 `breathing_watch`。",
        "- `static_watch_confound_hardguard` 优先标 `confound`。",
        "",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    review_df = pd.read_csv(args.review_queue_csv)
    segment_df = pd.read_csv(args.segment_support_csv)
    manifest_df = pd.read_csv(args.segment_manifest_csv) if os.path.exists(args.segment_manifest_csv) else pd.DataFrame()
    template_df = build_template(review_df, segment_df, manifest_df)
    summary = build_summary(template_df)

    outputs = {
        "template_csv": os.path.join(args.output_dir, "segment_review_labels_template_v2.csv"),
        "report_md": os.path.join(args.output_dir, "segment_review_label_template_report_v2.md"),
        "report_json": os.path.join(args.output_dir, "segment_review_label_template_report_v2.json"),
    }
    template_df.to_csv(outputs["template_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["report_md"], summary, outputs)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
