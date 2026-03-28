#!/usr/bin/env python3
import argparse
import json
import os
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd


WEAK_SUPPORT_FEATURES = [
    "max_corr_level_ah",
    "max_corr_level_dew",
    "max_corr_level_hum",
    "best_lag_level_ah",
    "best_lag_level_dew",
    "max_corr_outRH_inRH_change",
]

BREATHING_SUPPRESSION_PATTERN = [
    ("ah_neg_response_ratio", False),
    ("dew_neg_response_ratio", False),
    ("early_dew_gain_per_out", False),
    ("dew_headroom_capture_ratio", False),
    ("late_minus_early_rh_gain", False),
]

CONFOUND_REJECT_PATTERN = [
    ("early_dew_gain_per_out", True),
    ("late_minus_early_vpd_gap", True),
    ("max_corr_outRH_inRH_change", False),
    ("late_minus_early_rh_gain", False),
    ("vpd_in_mean", False),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Segment static support v2 with multiview support/suppression scores")
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
    parser.add_argument(
        "--feature-table-csv",
        default="reports/new_data_multiview_feature_mining_v2_run1/new_data_multiview_feature_table_v2.csv",
    )
    parser.add_argument(
        "--feature-ranking-csv",
        default="reports/new_data_multiview_feature_mining_v2_run1/new_data_multiview_feature_ranking_v2.csv",
    )
    parser.add_argument("--output-dir", default="reports/new_data_segment_static_support_v2_run1")
    parser.add_argument("--weak-support-thresh", type=float, default=0.75)
    parser.add_argument("--breathing-suppress-thresh", type=float, default=0.80)
    parser.add_argument("--confound-reject-thresh", type=float, default=0.80)
    parser.add_argument("--low-support-thresh", type=float, default=0.50)
    return parser.parse_args()


def toward_positive(value: Any, feature: str, ranking_map: Dict[str, Dict[str, Any]]) -> bool | None:
    if feature not in ranking_map or pd.isna(value):
        return None
    direction = str(ranking_map[feature]["direction"])
    unsealed_median = float(ranking_map[feature]["unsealed_median"])
    return bool(value >= unsealed_median) if direction == "pos" else bool(value <= unsealed_median)


def score_pattern(
    row: pd.Series,
    pattern: List[Tuple[str, bool]],
    ranking_map: Dict[str, Dict[str, Any]],
) -> float:
    flags: List[float] = []
    for feature, expected_positive in pattern:
        value = row.get(feature, np.nan)
        actual_positive = toward_positive(value, feature, ranking_map)
        if actual_positive is None:
            continue
        flags.append(float(actual_positive == expected_positive))
    return float(np.mean(flags)) if flags else np.nan


def weak_support_score(row: pd.Series, ranking_map: Dict[str, Dict[str, Any]]) -> float:
    flags: List[float] = []
    for feature in WEAK_SUPPORT_FEATURES:
        state = toward_positive(row.get(feature, np.nan), feature, ranking_map)
        if state is None:
            continue
        flags.append(float(state))
    return float(np.mean(flags)) if flags else np.nan


def segment_support_status(row: pd.Series, args: argparse.Namespace) -> tuple[str, str, str, bool]:
    static_final = str(row.get("final_assessment_v1", "") or "")
    transition_bucket = str(row.get("transition_bucket", "") or "")
    primary_task = str(row.get("primary_task", "") or "")
    weak_score = float(row.get("weak_positive_support_score_v2", np.nan))
    breathing_score = float(row.get("breathing_suppression_score_v2", np.nan))
    confound_score = float(row.get("confound_reject_score_v2", np.nan))

    if static_final == "confirmed_positive_reference":
        return (
            "static_positive_reference_support",
            "high",
            "segment remains a clean static positive reference in the main battlefield",
            False,
        )
    if static_final == "confirmed_negative_reference":
        return (
            "static_negative_reference_support",
            "none",
            "segment remains a clean static negative reference in the main battlefield",
            False,
        )
    if static_final == "review_weak_positive":
        if pd.notna(weak_score) and weak_score >= float(args.weak_support_thresh):
            return (
                "static_supported_weak_positive",
                "medium",
                f"raw static baseline stayed weak but multiview support score rose to {weak_score:.2f}",
                True,
            )
        return (
            "static_review_weak_positive",
            "watch",
            "segment carries positive label but static evidence remains weak and should still be reviewed",
            True,
        )
    if static_final == "watch_breathing":
        if (
            pd.notna(breathing_score)
            and breathing_score >= float(args.breathing_suppress_thresh)
            and pd.notna(weak_score)
            and weak_score < float(args.low_support_thresh)
        ):
            return (
                "static_watch_breathing_confirmed",
                "watch",
                f"raw positive tendency is suppressed by breathing pattern score {breathing_score:.2f} with low support {weak_score:.2f}",
                True,
            )
        return (
            "static_watch_breathing",
            "watch",
            "segment looks positive-like to the raw static baseline but remains a sealed breathing hard case",
            True,
        )
    if static_final == "watch_confound":
        if (
            pd.notna(confound_score)
            and confound_score >= float(args.confound_reject_thresh)
            and pd.notna(weak_score)
            and weak_score < float(args.low_support_thresh)
        ):
            return (
                "static_watch_confound_confirmed",
                "watch",
                f"segment matches heat-off confound pattern score {confound_score:.2f} with low support {weak_score:.2f}",
                True,
            )
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
    feature_df: pd.DataFrame,
    ranking_df: pd.DataFrame,
    args: argparse.Namespace,
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
    feature_keep = [
        "segment_id",
        "max_corr_level_ah",
        "max_corr_level_dew",
        "max_corr_level_hum",
        "best_lag_level_ah",
        "best_lag_level_dew",
        "max_corr_outRH_inRH_change",
        "ah_neg_response_ratio",
        "dew_neg_response_ratio",
        "early_dew_gain_per_out",
        "dew_headroom_capture_ratio",
        "late_minus_early_rh_gain",
        "late_minus_early_vpd_gap",
        "vpd_in_mean",
    ]
    ranking_map = ranking_df.set_index("feature")[["direction", "unsealed_median"]].to_dict(orient="index")

    merged = manifest.merge(static_pred_df[static_keep], on=["segment_id", "run_id"], how="left")
    merged = merged.merge(transition_map, on="segment_id", how="left", suffixes=("", "_transition"))
    merged = merged.merge(feature_df[feature_keep], on="segment_id", how="left")

    rows: List[Dict[str, Any]] = []
    for _, row in merged.iterrows():
        weak_score = weak_support_score(row, ranking_map)
        breathing_score = score_pattern(row, BREATHING_SUPPRESSION_PATTERN, ranking_map)
        confound_score = score_pattern(row, CONFOUND_REJECT_PATTERN, ranking_map)
        status, risk, reason, needs_review = segment_support_status(
            pd.Series(
                {
                    **row.to_dict(),
                    "weak_positive_support_score_v2": weak_score,
                    "breathing_suppression_score_v2": breathing_score,
                    "confound_reject_score_v2": confound_score,
                }
            ),
            args,
        )
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
                "prototype_margin_v1": row.get("prototype_margin_v1", pd.NA),
                "transition_bucket": row.get("transition_bucket", ""),
                "transition_recommended_use": row.get("transition_recommended_use", ""),
                "weak_positive_support_score_v2": weak_score,
                "breathing_suppression_score_v2": breathing_score,
                "confound_reject_score_v2": confound_score,
                "support_status_v2": status,
                "support_risk_v2": risk,
                "support_reason_v2": reason,
                "needs_review_v2": needs_review,
            }
        )
    return pd.DataFrame(rows).sort_values(["support_status_v2", "run_id", "segment_name"]).reset_index(drop=True)


def aggregate_run_support(segment_df: pd.DataFrame) -> pd.DataFrame:
    priority = {
        "static_supported_weak_positive": 1,
        "static_review_weak_positive": 2,
        "static_watch_breathing_confirmed": 3,
        "static_watch_breathing": 4,
        "static_watch_confound_confirmed": 5,
        "static_watch_confound": 6,
        "static_positive_reference_support": 7,
        "static_negative_reference_support": 8,
        "transition_secondary_control": 9,
        "control_challenge_support": 10,
        "short_context_only": 11,
        "holdout_support": 12,
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
            ranked["priority"] = ranked["support_status_v2"].map(priority).fillna(99)
            ranked = ranked.sort_values(["priority", "segment_hours"], ascending=[True, False])
            top = ranked.iloc[0]
            run_status = str(top["support_status_v2"])
            run_risk = str(top["support_risk_v2"])
            run_reason = str(top["support_reason_v2"])
            if run_status == "transition_secondary_control" and not transition_secondary_group.empty:
                ranked = transition_secondary_group.copy()
                ranked["post_rank"] = ranked["segment_name"].eq("post_change").map({True: 0, False: 1})
                ranked = ranked.sort_values(["post_rank", "segment_hours"], ascending=[True, False])
                top = ranked.iloc[0]

        review_count = int(group["needs_review_v2"].fillna(False).sum())
        rows.append(
            {
                "run_id": run_id,
                "run_support_status_v2": run_status,
                "run_support_risk_v2": run_risk,
                "primary_segment_id_v2": top["segment_id"],
                "primary_segment_name_v2": top["segment_name"],
                "primary_task_v2": top["primary_task"],
                "weak_positive_support_score_v2": top["weak_positive_support_score_v2"],
                "breathing_suppression_score_v2": top["breathing_suppression_score_v2"],
                "confound_reject_score_v2": top["confound_reject_score_v2"],
                "support_reason_v2": run_reason,
                "needs_review_v2": bool(review_count > 0 or run_status in {"transition_primary_support", "transition_secondary_control"}),
                "review_segment_count_v2": review_count,
                "segment_status_counts_v2": json.dumps(
                    group["support_status_v2"].value_counts(dropna=False).to_dict(),
                    ensure_ascii=False,
                ),
            }
        )
    return pd.DataFrame(rows).sort_values(["run_support_status_v2", "run_id"]).reset_index(drop=True)


def build_review_queue(segment_df: pd.DataFrame, run_df: pd.DataFrame) -> pd.DataFrame:
    priority = {
        "transition_primary_support": 0,
        "static_supported_weak_positive": 1,
        "static_review_weak_positive": 2,
        "static_watch_breathing_confirmed": 3,
        "static_watch_breathing": 4,
        "static_watch_confound_confirmed": 5,
        "static_watch_confound": 6,
        "transition_secondary_control": 7,
    }
    rows: List[Dict[str, Any]] = []
    for _, run in run_df[run_df["needs_review_v2"]].iterrows():
        run_id = run["run_id"]
        group = segment_df[segment_df["run_id"] == run_id].copy()
        run_status = str(run["run_support_status_v2"])

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
            anchor = group[group["support_status_v2"] == run_status].copy()
            if anchor.empty:
                anchor = group[group["needs_review_v2"]].copy()
            anchor = anchor.sort_values(["segment_hours"], ascending=[False])
            top = anchor.iloc[0]

        rows.append(
            {
                "run_id": run_id,
                "segment_id": top["segment_id"],
                "segment_name": top["segment_name"],
                "support_status_v2": run_status,
                "support_risk_v2": run["run_support_risk_v2"],
                "support_reason_v2": run["support_reason_v2"],
                "weak_positive_support_score_v2": run["weak_positive_support_score_v2"],
                "breathing_suppression_score_v2": run["breathing_suppression_score_v2"],
                "confound_reject_score_v2": run["confound_reject_score_v2"],
                "review_priority_v2": int(priority.get(run_status, 99)),
                "review_segment_count_v2": run["review_segment_count_v2"],
            }
        )

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["review_priority_v2", "run_id"]).reset_index(drop=True)


def build_summary(segment_df: pd.DataFrame, run_df: pd.DataFrame, review_df: pd.DataFrame) -> Dict[str, Any]:
    return {
        "segment_support_counts_v2": segment_df["support_status_v2"].value_counts(dropna=False).to_dict(),
        "run_support_counts_v2": run_df["run_support_status_v2"].value_counts(dropna=False).to_dict(),
        "review_segment_count_v2": int(len(review_df)),
        "review_run_count_v2": int(review_df["run_id"].nunique()) if not review_df.empty else 0,
        "transition_primary_runs_v2": int(run_df["run_support_status_v2"].eq("transition_primary_support").sum()),
        "weak_positive_upgraded_runs_v2": int(run_df["run_support_status_v2"].eq("static_supported_weak_positive").sum()),
        "breathing_confirmed_runs_v2": int(run_df["run_support_status_v2"].eq("static_watch_breathing_confirmed").sum()),
        "confound_confirmed_runs_v2": int(run_df["run_support_status_v2"].eq("static_watch_confound_confirmed").sum()),
    }


def fmt_score(value: Any) -> str:
    return "nan" if pd.isna(value) else f"{float(value):.2f}"


def write_markdown(path: str, summary: Dict[str, Any], run_df: pd.DataFrame, review_df: pd.DataFrame) -> None:
    lines = [
        "# 新补充数据 Segment Static Support v2",
        "",
        "## 核心结论",
        "",
        f"- segment_support_counts_v2: `{summary['segment_support_counts_v2']}`",
        f"- run_support_counts_v2: `{summary['run_support_counts_v2']}`",
        f"- weak_positive_upgraded_runs_v2: `{summary['weak_positive_upgraded_runs_v2']}`",
        f"- breathing_confirmed_runs_v2: `{summary['breathing_confirmed_runs_v2']}`",
        f"- confound_confirmed_runs_v2: `{summary['confound_confirmed_runs_v2']}`",
        "",
        "## 当前判断",
        "",
        "- 这一步不是重开 whole-run 模型，而是把新增 `dew / ingress` 特征克制地接成三个子评分。",
        "- `transition_primary_support` 仍然优先，不会被静态支持层抢走主导权。",
        "- `v2` 只做三类事：提升真正的 weak positive、压实 breathing watch、压实 heat-off confound。",
        "",
        "## 运行级支持结果",
        "",
    ]

    for _, row in run_df.iterrows():
        lines.append(
            f"- {row['run_id']} | status={row['run_support_status_v2']} | risk={row['run_support_risk_v2']} | "
            f"primary_segment={row['primary_segment_name_v2']} | weak_support={fmt_score(row['weak_positive_support_score_v2'])} | "
            f"breathing_suppress={fmt_score(row['breathing_suppression_score_v2'])} | "
            f"confound_reject={fmt_score(row['confound_reject_score_v2'])} | "
            f"needs_review={bool(row['needs_review_v2'])} | reason={row['support_reason_v2']}"
        )

    if not review_df.empty:
        lines.extend(["", "## 建议复核队列", ""])
        for _, row in review_df.iterrows():
            lines.append(
                f"- {row['run_id']} | segment={row['segment_name']} | status={row['support_status_v2']} | "
                f"priority={int(row['review_priority_v2'])} | reason={row['support_reason_v2']}"
            )

    lines.extend(
        [
            "",
            "## 结论",
            "",
            "1. `transition_primary_support` 仍然是主证据，不被静态支持层替代。",
            "2. `static_supported_weak_positive` 表示原始基线偏弱，但多视角结构特征已经给出足够的正向支持。",
            "3. `static_watch_breathing_confirmed / static_watch_confound_confirmed` 表示这些 watch 状态不是偶然噪声，而是被新增结构特征进一步压实。",
            "4. 下一步如果继续推进，应优先把这三个子评分接进真实复核队列，而不是再开新的 whole-run 模型线。",
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
    feature_df = pd.read_csv(args.feature_table_csv)
    ranking_df = pd.read_csv(args.feature_ranking_csv)

    segment_df = build_segment_support(manifest_df, static_pred_df, transition_df, feature_df, ranking_df, args)
    run_df = aggregate_run_support(segment_df)
    review_df = build_review_queue(segment_df, run_df)
    summary = build_summary(segment_df, run_df, review_df)

    outputs = {
        "segment_support_csv": os.path.join(args.output_dir, "segment_support_output_v2.csv"),
        "run_support_csv": os.path.join(args.output_dir, "run_support_output_v2.csv"),
        "review_queue_csv": os.path.join(args.output_dir, "segment_review_queue_v2.csv"),
        "report_md": os.path.join(args.output_dir, "segment_static_support_report_v2.md"),
        "report_json": os.path.join(args.output_dir, "segment_static_support_report_v2.json"),
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
