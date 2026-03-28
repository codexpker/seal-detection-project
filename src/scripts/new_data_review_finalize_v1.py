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

from src.scripts.new_data_segment_feedback_loop_v2 import normalize_label


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Finalize reviewed new-data labels by rerunning feedback and refreshing tuning outputs")
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
        "--working-labels-csv",
        default="reports/new_data_review_workflow_v1_run1/segment_review_labels_working_v2.csv",
    )
    parser.add_argument(
        "--auto-seed-csv",
        default="reports/new_data_segment_auto_seed_labels_v2_run1/segment_review_labels_auto_seed_v2.csv",
    )
    parser.add_argument(
        "--output-dir",
        default="reports/new_data_review_finalize_v1_run1",
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


def sanitize_for_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: sanitize_for_json(val) for key, val in value.items()}
    if isinstance(value, list):
        return [sanitize_for_json(item) for item in value]
    if pd.isna(value):
        return None
    return value


def build_review_snapshot(working_df: pd.DataFrame) -> pd.DataFrame:
    snapshot_df = working_df.copy()
    snapshot_df["normalized_review_label_v1"] = snapshot_df["review_label"].map(normalize_label)
    snapshot_df["review_fill_state_v1"] = "blank_or_invalid"
    snapshot_df.loc[snapshot_df["normalized_review_label_v1"].isin(
        ["positive_reference", "negative_reference", "transition_positive", "breathing_watch", "confound"]
    ), "review_fill_state_v1"] = "confirmed"
    snapshot_df.loc[snapshot_df["normalized_review_label_v1"].eq("uncertain"), "review_fill_state_v1"] = "uncertain"
    snapshot_df["is_auto_seed_v2"] = snapshot_df["reviewer"].fillna("").eq("codex_auto_seed_v2")
    snapshot_df["is_manual_fill_v1"] = snapshot_df["normalized_review_label_v1"].ne("") & snapshot_df["normalized_review_label_v1"].ne("unknown") & ~snapshot_df["is_auto_seed_v2"]
    return snapshot_df


def build_summary(snapshot_df: pd.DataFrame, feedback_summary: Dict[str, Any], tuning_summary: Dict[str, Any], outputs: Dict[str, str]) -> Dict[str, Any]:
    normalized = snapshot_df["normalized_review_label_v1"] if not snapshot_df.empty else pd.Series(dtype=str)
    return {
        "total_rows": int(len(snapshot_df)),
        "filled_rows": int(normalized.ne("").sum()) if not snapshot_df.empty else 0,
        "confirmed_rows": int(snapshot_df["review_fill_state_v1"].eq("confirmed").sum()) if not snapshot_df.empty else 0,
        "uncertain_rows": int(snapshot_df["review_fill_state_v1"].eq("uncertain").sum()) if not snapshot_df.empty else 0,
        "blank_or_invalid_rows": int(snapshot_df["review_fill_state_v1"].eq("blank_or_invalid").sum()) if not snapshot_df.empty else 0,
        "manual_rows": int(snapshot_df["is_manual_fill_v1"].sum()) if not snapshot_df.empty else 0,
        "auto_seed_rows": int(snapshot_df["is_auto_seed_v2"].sum()) if not snapshot_df.empty else 0,
        "label_counts": normalized[normalized.ne("")].value_counts(dropna=False).to_dict() if not snapshot_df.empty else {},
        "feedback_summary": feedback_summary,
        "tuning_summary": tuning_summary,
        "outputs": outputs,
    }


def write_markdown(path: str, summary: Dict[str, Any]) -> None:
    feedback = summary.get("feedback_summary", {})
    tuning = summary.get("tuning_summary", {})
    lines = [
        "# New Data Review Finalize v1",
        "",
        "- 目的：在人工编辑 `segment_review_labels_working_v2.csv` 后，自动重跑回灌、刷新 pending 排序，并同步生成最新调优建议。",
        "",
        "## 当前复核填充状态",
        "",
        f"- total_rows：`{summary['total_rows']}`",
        f"- filled_rows：`{summary['filled_rows']}`",
        f"- confirmed_rows：`{summary['confirmed_rows']}`",
        f"- uncertain_rows：`{summary['uncertain_rows']}`",
        f"- blank_or_invalid_rows：`{summary['blank_or_invalid_rows']}`",
        f"- manual_rows：`{summary['manual_rows']}`",
        f"- auto_seed_rows：`{summary['auto_seed_rows']}`",
        f"- label_counts：`{summary['label_counts']}`",
        "",
        "## 回灌结果",
        "",
        f"- reviewed_rows：`{feedback.get('reviewed_rows', 0)}`",
        f"- positive_reference_segments：`{feedback.get('positive_reference_segments', 0)}`",
        f"- negative_reference_segments：`{feedback.get('negative_reference_segments', 0)}`",
        f"- transition_positive_segments：`{feedback.get('transition_positive_segments', 0)}`",
        f"- breathing_watch_segments：`{feedback.get('breathing_watch_segments', 0)}`",
        f"- confound_segments：`{feedback.get('confound_segments', 0)}`",
        f"- pending_segments：`{feedback.get('pending_segments', 0)}`",
        "",
        "## 当前动作建议",
        "",
    ]

    pending_items = feedback.get("top_pending_segments", []) or []
    if pending_items:
        for row in pending_items:
            lines.append(
                f"- pending | {row.get('segment_id', '')} | status={row.get('support_status_v3', '')} | memory={row.get('memory_role_v2', '')}"
            )
    else:
        lines.append("- 当前没有剩余 pending，可直接进入下一轮段级基准维护。")

    lines.extend(
        [
            "",
            f"- 当前 tuning 口径仍是：`{tuning.get('transition_primary_segment_count', 0)}` 条 transition 主段优先，guarded positive 仅人工确认后升级。",
            "",
            "## 关键输出",
            "",
            f"- working_labels_csv：`{summary['outputs']['working_labels_csv']}`",
            f"- feedback_report_md：`{summary['outputs']['feedback_report_md']}`",
            f"- pending_csv：`{summary['outputs']['pending_csv']}`",
            f"- tuning_report_md：`{summary['outputs']['tuning_report_md']}`",
            f"- finalize_report_json：`{summary['outputs']['finalize_report_json']}`",
            "",
        ]
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    ensure_dir(args.output_dir)

    feedback_dir = os.path.join(args.output_dir, "feedback_v2")
    tuning_dir = os.path.join(args.output_dir, "tuning_plan_v1")
    ensure_dir(feedback_dir)
    ensure_dir(tuning_dir)

    working_df = pd.read_csv(args.working_labels_csv)
    snapshot_df = build_review_snapshot(working_df)
    snapshot_csv = os.path.join(args.output_dir, "segment_review_labels_snapshot_v1.csv")
    snapshot_df.to_csv(snapshot_csv, index=False, encoding="utf-8-sig")

    feedback_payload = run_py(
        os.path.join(ROOT_DIR, "src/scripts/new_data_segment_feedback_loop_v2.py"),
        [
            "--labels-csv", args.working_labels_csv,
            "--segment-support-csv", args.segment_support_csv,
            "--review-queue-csv", args.review_queue_csv,
            "--output-dir", feedback_dir,
        ],
    )
    pending_csv = os.path.join(feedback_dir, "pending_segment_review_reranked_v2.csv")
    tuning_payload = run_py(
        os.path.join(ROOT_DIR, "src/scripts/new_data_model_tuning_plan_v1.py"),
        [
            "--readme-xlsx", args.readme_xlsx,
            "--segment-manifest-csv", args.segment_manifest_csv,
            "--segment-support-csv", args.segment_support_csv,
            "--review-template-csv", args.working_labels_csv,
            "--auto-seed-csv", args.auto_seed_csv,
            "--pending-csv", pending_csv,
            "--output-dir", tuning_dir,
        ],
    )

    outputs = {
        "working_labels_csv": args.working_labels_csv,
        "snapshot_csv": snapshot_csv,
        "feedback_dir": feedback_dir,
        "feedback_report_md": os.path.join(feedback_dir, "segment_feedback_report_v2.md"),
        "pending_csv": pending_csv,
        "tuning_report_md": os.path.join(tuning_dir, "new_data_model_tuning_plan_v1.md"),
        "finalize_report_md": os.path.join(args.output_dir, "new_data_review_finalize_v1.md"),
        "finalize_report_json": os.path.join(args.output_dir, "new_data_review_finalize_v1.json"),
    }
    summary = build_summary(
        snapshot_df,
        feedback_payload.get("summary", {}),
        tuning_payload.get("summary", {}),
        outputs,
    )
    summary = sanitize_for_json(summary)

    write_markdown(outputs["finalize_report_md"], summary)
    with open(outputs["finalize_report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
