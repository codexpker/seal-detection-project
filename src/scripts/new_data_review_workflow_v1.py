#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
from typing import Any, Dict, List

import pandas as pd


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.scripts.new_data_deep_analysis_v1 import load_readme


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the guarded new-data review workflow and generate a reviewer agenda")
    parser.add_argument("--readme-xlsx", default="/Users/xpker/Downloads/data_readme.xlsx")
    parser.add_argument(
        "--segment-manifest-csv",
        default="reports/new_data_segment_pipeline_v1_run1/segment_pipeline_manifest.csv",
    )
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
        default="reports/new_data_review_workflow_v1_run1",
    )
    parser.add_argument(
        "--labels-source",
        choices=["auto_seed", "template"],
        default="auto_seed",
    )
    return parser.parse_args()


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def run_py(script_path: str, args: List[str]) -> Dict[str, Any]:
    cmd = [sys.executable, script_path, *args]
    env = dict(os.environ)
    env.setdefault("MPLCONFIGDIR", "/tmp/mplconfig")
    completed = subprocess.run(cmd, cwd=ROOT_DIR, check=True, capture_output=True, text=True, env=env)
    stdout = completed.stdout.strip()
    if not stdout:
        return {}
    for idx in [pos for pos, ch in enumerate(stdout) if ch == "{"]:
        try:
            return json.loads(stdout[idx:])
        except json.JSONDecodeError:
            continue
    return {"stdout": stdout}


def merge_seed_into_template(template_df: pd.DataFrame, seed_df: pd.DataFrame) -> pd.DataFrame:
    merged = template_df.merge(
        seed_df[["segment_id", "review_label", "reviewer", "review_note"]],
        on="segment_id",
        how="left",
        suffixes=("", "_seed"),
    )
    for col in ["review_label", "reviewer", "review_note"]:
        seed_col = f"{col}_seed"
        merged[col] = merged[seed_col].fillna(merged[col])
        merged = merged.drop(columns=[seed_col])
    return merged


def build_review_agenda(
    template_df: pd.DataFrame,
    working_df: pd.DataFrame,
    merged_feedback_df: pd.DataFrame,
    pending_df: pd.DataFrame,
    readme_df: pd.DataFrame,
) -> pd.DataFrame:
    readme_keep = [
        "file",
        "device_id",
        "seal_state_cn",
        "ext_level_cn",
        "in_level_cn",
        "heat_state_cn",
        "change_flag_cn",
        "change_time",
        "changed_state_cn",
    ]
    review_df = working_df.copy()
    review_df = review_df.merge(
        readme_df[[col for col in readme_keep if col in readme_df.columns]].drop_duplicates("file"),
        on="file",
        how="left",
    )
    feedback_lookup = merged_feedback_df[
        [
            "segment_id",
            "review_status_v3",
            "feedback_action_v2",
        ]
    ].copy() if not merged_feedback_df.empty else pd.DataFrame(columns=["segment_id"])
    review_df = review_df.merge(feedback_lookup, on="segment_id", how="left")
    pending_lookup = pending_df[
        [
            "segment_id",
            "rerank_priority_v2",
            "memory_bonus_v2",
            "sort_anomaly_adv_v2",
            "sort_guard_v2",
        ]
    ].copy() if not pending_df.empty else pd.DataFrame(columns=["segment_id"])
    review_df = review_df.merge(pending_lookup, on="segment_id", how="left")
    review_df["agenda_group_v1"] = review_df["review_stage_v1"].fillna("99_other")
    review_df["agenda_rank_v1"] = review_df["review_rank_v1"].fillna(99).astype(int)
    review_df["filled_by_auto_seed_v2"] = review_df["reviewer"].fillna("").eq("codex_auto_seed_v2")
    review_df["review_status_v3"] = review_df["review_status_v3"].fillna("pending")
    review_df = review_df.sort_values(
        [
            "agenda_rank_v1",
            "review_priority_v3",
            "review_status_v3",
            "filled_by_auto_seed_v2",
            "sort_anomaly_adv_v2",
            "sort_guard_v2",
            "run_id",
            "segment_name",
        ],
        ascending=[True, True, True, False, False, False, True, True],
    ).reset_index(drop=True)
    review_df["agenda_seq_v1"] = range(1, len(review_df) + 1)
    return review_df


def build_summary(
    agenda_df: pd.DataFrame,
    feedback_summary: Dict[str, Any],
    template_path: str,
    working_path: str,
    agenda_path: str,
) -> Dict[str, Any]:
    return {
        "agenda_rows": int(len(agenda_df)),
        "agenda_group_counts": agenda_df["agenda_group_v1"].value_counts(dropna=False).to_dict() if not agenda_df.empty else {},
        "prefilled_seed_rows": int(agenda_df["filled_by_auto_seed_v2"].sum()) if not agenda_df.empty else 0,
        "pending_rows": int(agenda_df["review_status_v3"].eq("pending").sum()) if not agenda_df.empty else 0,
        "feedback_summary": feedback_summary,
        "template_csv": template_path,
        "working_csv": working_path,
        "agenda_csv": agenda_path,
    }


def write_markdown(path: str, summary: Dict[str, Any], agenda_df: pd.DataFrame) -> None:
    lines = [
        "# New Data Review Workflow v1",
        "",
        "- 目的：把 `v3 guarded` 的复核链收成一个可直接执行的工作流，并生成最终人工复核 agenda。",
        "",
        f"- agenda_rows：`{summary['agenda_rows']}`",
        f"- agenda_group_counts：`{summary['agenda_group_counts']}`",
        f"- prefilled_seed_rows：`{summary['prefilled_seed_rows']}`",
        f"- pending_rows：`{summary['pending_rows']}`",
        "",
        "## 当前执行顺序",
        "",
    ]
    for _, row in agenda_df.head(12).iterrows():
        lines.append(
            f"- #{int(row['agenda_seq_v1'])} | {row['segment_id']} | stage={row['agenda_group_v1']} | "
            f"status={row['support_status_v3']} | preferred={row.get('preferred_seed_label_v2', '') or 'manual'} | "
            f"auto_seed={row['filled_by_auto_seed_v2']} | seal={row.get('seal_state_cn', '')} | "
            f"change={row.get('changed_state_cn', '') if pd.notna(row.get('changed_state_cn', '')) else ''}"
        )

    lines.extend(
        [
            "",
            "## 使用方式",
            "",
            f"- 直接编辑：`{summary['working_csv']}`",
            "- 只需要填写或确认：`review_label / reviewer / review_note`。",
            "- 已自动种子的高置信段保留预填内容；人工只需要补充其余段或修正个别结论。",
            "",
        ]
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    ensure_dir(args.output_dir)

    template_dir = os.path.join(args.output_dir, "review_template_v2")
    auto_seed_dir = os.path.join(args.output_dir, "auto_seed_v2")
    feedback_dir = os.path.join(args.output_dir, "feedback_v2")
    ensure_dir(template_dir)
    ensure_dir(auto_seed_dir)
    ensure_dir(feedback_dir)

    run_py(
        os.path.join(ROOT_DIR, "src/scripts/new_data_segment_review_label_template_v2.py"),
        [
            "--review-queue-csv", args.review_queue_csv,
            "--segment-support-csv", args.segment_support_csv,
            "--segment-manifest-csv", args.segment_manifest_csv,
            "--output-dir", template_dir,
        ],
    )
    run_py(
        os.path.join(ROOT_DIR, "src/scripts/new_data_segment_auto_seed_labels_v2.py"),
        [
            "--review-queue-csv", args.review_queue_csv,
            "--output-dir", auto_seed_dir,
        ],
    )

    template_csv = os.path.join(template_dir, "segment_review_labels_template_v2.csv")
    auto_seed_csv = os.path.join(auto_seed_dir, "segment_review_labels_auto_seed_v2.csv")
    working_csv = os.path.join(args.output_dir, "segment_review_labels_working_v2.csv")

    template_df = pd.read_csv(template_csv)
    seed_df = pd.read_csv(auto_seed_csv)
    working_df = merge_seed_into_template(template_df, seed_df)
    working_df.to_csv(working_csv, index=False, encoding="utf-8-sig")

    feedback_labels_csv = auto_seed_csv if args.labels_source == "auto_seed" else working_csv
    feedback_payload = run_py(
        os.path.join(ROOT_DIR, "src/scripts/new_data_segment_feedback_loop_v2.py"),
        [
            "--labels-csv", feedback_labels_csv,
            "--segment-support-csv", args.segment_support_csv,
            "--review-queue-csv", args.review_queue_csv,
            "--output-dir", feedback_dir,
        ],
    )

    merged_feedback_csv = os.path.join(feedback_dir, "segment_review_feedback_merged_v2.csv")
    pending_csv = os.path.join(feedback_dir, "pending_segment_review_reranked_v2.csv")
    merged_feedback_df = pd.read_csv(merged_feedback_csv) if os.path.exists(merged_feedback_csv) else pd.DataFrame()
    pending_df = pd.read_csv(pending_csv) if os.path.exists(pending_csv) else pd.DataFrame()
    readme_df = load_readme(args.readme_xlsx)
    agenda_df = build_review_agenda(template_df, working_df, merged_feedback_df, pending_df, readme_df)

    agenda_csv = os.path.join(args.output_dir, "review_agenda_v1.csv")
    agenda_md = os.path.join(args.output_dir, "review_agenda_v1.md")
    report_json = os.path.join(args.output_dir, "review_workflow_report_v1.json")
    agenda_df.to_csv(agenda_csv, index=False, encoding="utf-8-sig")
    summary = build_summary(agenda_df, feedback_payload.get("summary", {}), template_csv, working_csv, agenda_csv)
    write_markdown(agenda_md, summary, agenda_df)
    with open(report_json, "w", encoding="utf-8") as f:
        json.dump({"summary": summary}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": {
        "template_csv": template_csv,
        "auto_seed_csv": auto_seed_csv,
        "working_csv": working_csv,
        "feedback_dir": feedback_dir,
        "agenda_csv": agenda_csv,
        "agenda_md": agenda_md,
        "report_json": report_json,
    }}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
