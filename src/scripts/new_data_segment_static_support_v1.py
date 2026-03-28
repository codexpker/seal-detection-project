#!/usr/bin/env python3
import argparse
import json
import os
from typing import Any, Dict, List

import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Segment static support v1 for new_data segment pipeline")
    parser.add_argument(
        "--segment-manifest-csv",
        default="reports/new_data_segment_pipeline_v1_run1/segment_pipeline_manifest.csv",
    )
    parser.add_argument(
        "--static-predictions-csv",
        default="reports/new_data_segment_static_baseline_v1_run1/segment_static_baseline_predictions.csv",
    )
    parser.add_argument(
        "--transition-candidates-csv",
        default="reports/new_data_segment_pipeline_v1_run1/segment_transition_candidates.csv",
    )
    parser.add_argument("--output-dir", default="reports/new_data_segment_static_support_v1_run1")
    return parser.parse_args()


def segment_support_status(row: pd.Series) -> tuple[str, str, str, bool]:
    static_final = str(row.get("final_assessment_v1", "") or "")
    transition_bucket = str(row.get("transition_bucket", "") or "")
    primary_task = str(row.get("primary_task", "") or "")

    if static_final == "confirmed_positive_reference":
        return (
            "static_positive_reference_support",
            "high",
            "segment is a clean static positive reference in the main battlefield",
            False,
        )
    if static_final == "confirmed_negative_reference":
        return (
            "static_negative_reference_support",
            "none",
            "segment is a clean static negative reference in the main battlefield",
            False,
        )
    if static_final == "review_weak_positive":
        return (
            "static_review_weak_positive",
            "watch",
            "segment carries positive label but static evidence remains weak and should be reviewed instead of promoted",
            True,
        )
    if static_final == "watch_breathing":
        return (
            "static_watch_breathing",
            "watch",
            "segment looks positive-like to the raw static baseline but remains a sealed breathing hard case",
            True,
        )
    if static_final == "watch_confound":
        return (
            "static_watch_confound",
            "watch",
            "segment enters the battlefield after heat-off and should not be treated as a clean static positive",
            True,
        )
    if transition_bucket == "transition_primary_mainfield":
        return (
            "transition_primary_support",
            "high",
            "segment belongs to a mainfield seal-to-unsealed transition run",
            True,
        )
    if transition_bucket == "transition_secondary_control":
        return (
            "transition_secondary_control",
            "watch",
            "segment belongs to a seal-change run outside the main battlefield and should stay as a transition challenge",
            True,
        )
    if primary_task == "control_challenge":
        return (
            "control_challenge_support",
            "none",
            "segment belongs to the control/challenge pool and is used to constrain false positives",
            False,
        )
    if primary_task == "short_context_only":
        return (
            "short_context_only",
            "none",
            "segment is too short for analyzable segment-level use and only keeps local context",
            False,
        )
    return (
        "holdout_support",
        "none",
        "segment currently remains outside primary support and challenge sets",
        False,
    )


def build_segment_support(
    manifest_df: pd.DataFrame,
    static_pred_df: pd.DataFrame,
    transition_df: pd.DataFrame,
) -> pd.DataFrame:
    manifest = manifest_df.copy()
    if "run_id" not in manifest.columns and "file" in manifest.columns:
        manifest["run_id"] = manifest["file"]

    transition_pre = transition_df[["pre_segment_id", "transition_bucket", "recommended_use"]].copy()
    transition_pre = transition_pre[transition_pre["pre_segment_id"].astype(str) != ""].rename(
        columns={"pre_segment_id": "segment_id", "recommended_use": "transition_recommended_use"}
    )
    transition_post = transition_df[["post_segment_id", "transition_bucket", "recommended_use"]].copy()
    transition_post = transition_post[transition_post["post_segment_id"].astype(str) != ""].rename(
        columns={"post_segment_id": "segment_id", "recommended_use": "transition_recommended_use"}
    )
    transition_map = pd.concat([transition_pre, transition_post], ignore_index=True)
    transition_map = transition_map.drop_duplicates(subset=["segment_id"], keep="first")

    static_keep = [
        "segment_id",
        "run_id",
        "final_assessment_v1",
        "final_reason_v1",
        "raw_label_v1",
        "raw_confidence_v1",
        "static_vote_count_v1",
        "static_vote_ratio_v1",
        "static_vote_hits_v1",
        "distance_negative_v1",
        "distance_positive_v1",
        "prototype_margin_v1",
    ]
    merged = manifest.merge(static_pred_df[static_keep], on=["segment_id", "run_id"], how="left")
    merged = merged.merge(transition_map, on="segment_id", how="left", suffixes=("", "_transition"))

    rows: List[Dict[str, Any]] = []
    for _, row in merged.iterrows():
        status, risk, reason, needs_review = segment_support_status(row)
        rows.append(
            {
                "segment_id": row["segment_id"],
                "run_id": row["run_id"],
                "segment_name": row["segment_name"],
                "segment_role": row["segment_role"],
                "segment_source": row["segment_source"],
                "segment_hours": row["segment_hours"],
                "segment_analyzable": bool(row["segment_analyzable"]),
                "segment_seal_state": row["segment_seal_state"],
                "primary_task": row["primary_task"],
                "secondary_tasks": row["secondary_tasks"],
                "static_bucket": row.get("static_bucket", ""),
                "final_assessment_v1": row.get("final_assessment_v1", ""),
                "raw_label_v1": row.get("raw_label_v1", ""),
                "raw_confidence_v1": row.get("raw_confidence_v1", ""),
                "static_vote_count_v1": row.get("static_vote_count_v1", pd.NA),
                "prototype_margin_v1": row.get("prototype_margin_v1", pd.NA),
                "transition_bucket": row.get("transition_bucket", ""),
                "transition_recommended_use": row.get("transition_recommended_use", ""),
                "transition_anchor_v1": bool(str(row.get("transition_bucket", "") or "") != ""),
                "support_status_v1": status,
                "support_risk_v1": risk,
                "support_reason_v1": reason,
                "needs_review_v1": needs_review,
            }
        )
    return pd.DataFrame(rows).sort_values(["support_status_v1", "run_id", "segment_name"]).reset_index(drop=True)


def aggregate_run_support(segment_df: pd.DataFrame) -> pd.DataFrame:
    priority = {
        "static_review_weak_positive": 1,
        "static_watch_breathing": 2,
        "static_watch_confound": 3,
        "static_positive_reference_support": 5,
        "static_negative_reference_support": 6,
        "transition_secondary_control": 7,
        "control_challenge_support": 8,
        "short_context_only": 9,
        "holdout_support": 10,
    }
    rows: List[Dict[str, Any]] = []
    for run_id, group in segment_df.groupby("run_id", dropna=False):
        transition_primary_group = group[group["transition_bucket"] == "transition_primary_mainfield"].copy()
        transition_secondary_group = group[group["transition_bucket"] == "transition_secondary_control"].copy()

        if not transition_primary_group.empty:
            ranked = transition_primary_group.copy()
            ranked["post_rank"] = ranked["segment_name"].eq("post_change").map({True: 0, False: 1})
            ranked = ranked.sort_values(["post_rank", "segment_hours"], ascending=[True, False])
            top = ranked.iloc[0]
            run_status = "transition_primary_support"
            run_risk = "high"
            run_reason = "run contains a mainfield seal-to-unsealed transition and should stay transition-led"
        else:
            ranked = group.copy()
            ranked["priority"] = ranked["support_status_v1"].map(priority).fillna(99)
            ranked = ranked.sort_values(["priority", "segment_hours"], ascending=[True, False])
            top = ranked.iloc[0]
            run_status = str(top["support_status_v1"])
            run_risk = str(top["support_risk_v1"])
            run_reason = str(top["support_reason_v1"])
            if run_status == "transition_secondary_control" and not transition_secondary_group.empty:
                ranked = transition_secondary_group.copy()
                ranked["post_rank"] = ranked["segment_name"].eq("post_change").map({True: 0, False: 1})
                ranked = ranked.sort_values(["post_rank", "segment_hours"], ascending=[True, False])
                top = ranked.iloc[0]

        review_count = int(group["needs_review_v1"].fillna(False).sum())
        rows.append(
            {
                "run_id": run_id,
                "run_support_status_v1": run_status,
                "run_support_risk_v1": run_risk,
                "primary_segment_id_v1": top["segment_id"],
                "primary_segment_name_v1": top["segment_name"],
                "primary_task_v1": top["primary_task"],
                "support_reason_v1": run_reason,
                "needs_review_v1": bool(review_count > 0 or run_status in {"transition_primary_support", "transition_secondary_control"}),
                "review_segment_count_v1": review_count,
                "segment_status_counts_v1": json.dumps(
                    group["support_status_v1"].value_counts(dropna=False).to_dict(),
                    ensure_ascii=False,
                ),
            }
        )
    return pd.DataFrame(rows).sort_values(["run_support_status_v1", "run_id"]).reset_index(drop=True)


def build_review_queue(segment_df: pd.DataFrame, run_df: pd.DataFrame) -> pd.DataFrame:
    priority = {
        "transition_primary_support": 0,
        "static_review_weak_positive": 1,
        "static_watch_breathing": 2,
        "static_watch_confound": 3,
        "transition_secondary_control": 4,
    }
    rows: List[Dict[str, Any]] = []
    for _, run in run_df[run_df["needs_review_v1"]].iterrows():
        run_id = run["run_id"]
        group = segment_df[segment_df["run_id"] == run_id].copy()
        run_status = str(run["run_support_status_v1"])

        if run_status == "transition_primary_support":
            anchor = group[group["transition_bucket"] == "transition_primary_mainfield"].copy()
            anchor["post_rank"] = anchor["segment_name"].eq("post_change").map({True: 0, False: 1})
            anchor = anchor.sort_values(["post_rank", "segment_hours"], ascending=[True, False])
            top = anchor.iloc[0]
        elif run_status == "transition_secondary_control":
            anchor = group[group["transition_bucket"] == "transition_secondary_control"].copy()
            anchor["post_rank"] = anchor["segment_name"].eq("post_change").map({True: 0, False: 1})
            anchor = anchor.sort_values(["post_rank", "segment_hours"], ascending=[True, False])
            top = anchor.iloc[0]
        else:
            anchor = group[group["support_status_v1"] == run_status].copy()
            if anchor.empty:
                anchor = group[group["needs_review_v1"]].copy()
            anchor = anchor.sort_values(["segment_hours"], ascending=[False])
            top = anchor.iloc[0]

        rows.append(
            {
                "run_id": run_id,
                "segment_id": top["segment_id"],
                "segment_name": top["segment_name"],
                "support_status_v1": run_status,
                "support_risk_v1": run["run_support_risk_v1"],
                "support_reason_v1": run["support_reason_v1"],
                "review_priority_v1": int(priority.get(run_status, 99)),
                "review_segment_count_v1": run["review_segment_count_v1"],
            }
        )

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["review_priority_v1", "run_id"]).reset_index(drop=True)


def build_summary(segment_df: pd.DataFrame, run_df: pd.DataFrame, review_df: pd.DataFrame) -> Dict[str, Any]:
    return {
        "segment_support_counts": segment_df["support_status_v1"].value_counts(dropna=False).to_dict(),
        "run_support_counts": run_df["run_support_status_v1"].value_counts(dropna=False).to_dict(),
        "review_segment_count": int(len(review_df)),
        "review_run_count": int(review_df["run_id"].nunique()) if not review_df.empty else 0,
        "transition_primary_runs": int(run_df["run_support_status_v1"].eq("transition_primary_support").sum()),
        "static_positive_reference_runs": int(run_df["run_support_status_v1"].eq("static_positive_reference_support").sum()),
        "static_negative_reference_runs": int(run_df["run_support_status_v1"].eq("static_negative_reference_support").sum()),
        "watch_runs": int(run_df["run_support_status_v1"].isin(["static_review_weak_positive", "static_watch_breathing", "static_watch_confound"]).sum()),
    }


def write_markdown(path: str, summary: Dict[str, Any], run_df: pd.DataFrame, review_df: pd.DataFrame) -> None:
    lines = [
        "# 新补充数据 Segment Static Support v1",
        "",
        "## 核心结论",
        "",
        f"- segment_support_counts: `{summary['segment_support_counts']}`",
        f"- run_support_counts: `{summary['run_support_counts']}`",
        f"- review_segment_count: `{summary['review_segment_count']}`",
        f"- review_run_count: `{summary['review_run_count']}`",
        "",
        "## 当前判断",
        "",
        "- 这一步不是替换现有 whole-run 主链，而是给新补充数据增加一个段级支持层。",
        "- 它把 `静态参考段 / transition 主证据 / watch / control challenge` 收成统一输出，方便后续复核、讲解和与主链对齐。",
        "- 当前最值得优先看的仍然是 `transition_primary_support`、`static_review_weak_positive` 和 `static_watch_breathing`。",
        "",
        "## 运行级支持结果",
        "",
    ]

    for _, row in run_df.iterrows():
        lines.append(
            f"- {row['run_id']} | status={row['run_support_status_v1']} | risk={row['run_support_risk_v1']} | "
            f"primary_segment={row['primary_segment_name_v1']} | needs_review={bool(row['needs_review_v1'])} | "
            f"reason={row['support_reason_v1']}"
        )

    if not review_df.empty:
        lines.extend(["", "## 建议复核队列", ""])
        for _, row in review_df.iterrows():
            lines.append(
                f"- {row['run_id']} | segment={row['segment_name']} | status={row['support_status_v1']} | "
                f"priority={int(row['review_priority_v1'])} | reason={row['support_reason_v1']}"
            )

    lines.extend(
        [
            "",
            "## 结论",
            "",
            "1. `transition_primary_support` 仍然是当前最强主证据，应优先用于事件级验证和演示。",
            "2. `static_positive_reference_support / static_negative_reference_support` 可以作为新数据段级静态参考池，不应被回退成 whole-run 标签样本。",
            "3. `static_review_weak_positive / static_watch_breathing / static_watch_confound` 说明静态主线仍然离不开 review/watch 机制。",
            "4. `control_challenge_support` 继续保留为误报约束，不进入正样本训练。",
            "",
        ]
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    manifest_df = pd.read_csv(args.segment_manifest_csv)
    static_pred_df = pd.read_csv(args.static_predictions_csv)
    transition_df = pd.read_csv(args.transition_candidates_csv)

    segment_df = build_segment_support(manifest_df, static_pred_df, transition_df)
    run_df = aggregate_run_support(segment_df)
    review_df = build_review_queue(segment_df, run_df)
    summary = build_summary(segment_df, run_df, review_df)

    outputs = {
        "segment_support_csv": os.path.join(args.output_dir, "segment_support_output.csv"),
        "run_support_csv": os.path.join(args.output_dir, "run_support_output.csv"),
        "review_queue_csv": os.path.join(args.output_dir, "segment_review_queue.csv"),
        "report_md": os.path.join(args.output_dir, "segment_static_support_report.md"),
        "report_json": os.path.join(args.output_dir, "segment_static_support_report.json"),
    }

    segment_df.to_csv(outputs["segment_support_csv"], index=False, encoding="utf-8-sig")
    run_df.to_csv(outputs["run_support_csv"], index=False, encoding="utf-8-sig")
    review_df.to_csv(outputs["review_queue_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["report_md"], summary, run_df, review_df)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
