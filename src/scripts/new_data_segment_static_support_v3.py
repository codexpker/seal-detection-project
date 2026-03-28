#!/usr/bin/env python3
import argparse
import json
import os
from typing import Any, Dict, List

import numpy as np
import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Segment static support v3 with cross-dataset guard features and old hard-negative constraints"
    )
    parser.add_argument(
        "--segment-support-csv",
        default="reports/new_data_segment_static_support_v2_run1/segment_support_output_v2.csv",
    )
    parser.add_argument(
        "--feature-table-csv",
        default="reports/new_data_multiview_feature_mining_v2_run1/new_data_multiview_feature_table_v2.csv",
    )
    parser.add_argument(
        "--memory-scores-csv",
        default="reports/segment_memory_bank_similarity_v2_run1/segment_memory_similarity_scores.csv",
    )
    parser.add_argument(
        "--guard-csv",
        default="reports/cross_dataset_feature_guard_v1_run1/cross_dataset_feature_guard.csv",
    )
    parser.add_argument("--output-dir", default="reports/new_data_segment_static_support_v3_run1")
    parser.add_argument("--guard-score-thresh", type=float, default=0.66)
    parser.add_argument("--weak-support-thresh", type=float, default=0.75)
    parser.add_argument("--hard-negative-margin-thresh", type=float, default=0.0)
    return parser.parse_args()


def toward_positive(value: Any, direction: str, positive_median: float) -> bool | None:
    if pd.isna(value):
        return None
    if direction == "pos":
        return bool(float(value) >= float(positive_median))
    return bool(float(value) <= float(positive_median))


def guard_score(row: pd.Series, guard_df: pd.DataFrame) -> float:
    flags: List[float] = []
    for _, item in guard_df.iterrows():
        feature = str(item["feature"])
        state = toward_positive(row.get(feature, np.nan), str(item["direction"]), float(item["positive_median"]))
        if state is None:
            continue
        flags.append(float(state))
    return float(np.mean(flags)) if flags else np.nan


def fmt_score(value: Any) -> str:
    return "nan" if pd.isna(value) else f"{float(value):.2f}"


def segment_status_v3(row: pd.Series, args: argparse.Namespace) -> tuple[str, str, str, bool]:
    status_v2 = str(row.get("support_status_v2", "") or "")
    risk_v2 = str(row.get("support_risk_v2", "") or "")
    reason_v2 = str(row.get("support_reason_v2", "") or "")
    memory_role = str(row.get("predicted_memory_role_v2", "") or "")
    anom_adv = float(row.get("anomaly_advantage_v2", np.nan))
    weak_support = float(row.get("weak_positive_support_score_v2", np.nan))
    guard = float(row.get("guard_feature_score_v3", np.nan))
    breathing = float(row.get("breathing_suppression_score_v2", np.nan))
    confound = float(row.get("confound_reject_score_v2", np.nan))

    if status_v2 in {
        "transition_primary_support",
        "transition_secondary_control",
        "static_positive_reference_support",
        "static_negative_reference_support",
        "control_challenge_support",
        "short_context_only",
        "holdout_support",
    }:
        return status_v2, risk_v2, reason_v2, bool(row.get("needs_review_v2", False))

    if status_v2 == "static_supported_weak_positive":
        if (
            pd.notna(weak_support)
            and weak_support >= float(args.weak_support_thresh)
            and pd.notna(guard)
            and guard >= float(args.guard_score_thresh)
            and memory_role == "anomaly_reference"
            and pd.notna(anom_adv)
            and anom_adv > float(args.hard_negative_margin_thresh)
        ):
            return (
                "static_supported_weak_positive_guarded",
                "medium",
                f"weak positive keeps support because guard score {guard:.2f} is high and tri-memory also stays on anomaly side ({anom_adv:.2f})",
                True,
            )
        return (
            "static_review_weak_positive_guarded",
            "watch",
            (
                "weak positive keeps local support but does not pass cross-dataset hard-negative guard; "
                f"guard={fmt_score(guard)}, memory={memory_role or 'na'}, anomaly_adv={fmt_score(anom_adv)}"
            ),
            True,
        )

    if status_v2 == "static_watch_breathing_confirmed":
        if memory_role in {"hard_negative", "health_core"} and pd.notna(anom_adv) and anom_adv <= float(args.hard_negative_margin_thresh):
            return (
                "static_watch_breathing_hardguard",
                "watch",
                f"breathing watch is reinforced by tri-memory {memory_role} with anomaly_adv {anom_adv:.2f} and suppression {breathing:.2f}",
                True,
            )
        return status_v2, risk_v2, reason_v2, True

    if status_v2 == "static_watch_confound_confirmed":
        if memory_role in {"hard_negative", "health_core"} and pd.notna(anom_adv) and anom_adv <= float(args.hard_negative_margin_thresh):
            return (
                "static_watch_confound_hardguard",
                "watch",
                f"confound watch is reinforced by tri-memory {memory_role} with anomaly_adv {anom_adv:.2f} and reject score {confound:.2f}",
                True,
            )
        return status_v2, risk_v2, reason_v2, True

    return status_v2, risk_v2, reason_v2, bool(row.get("needs_review_v2", False))


def aggregate_run_support(segment_df: pd.DataFrame) -> pd.DataFrame:
    priority = {
        "transition_primary_support": 0,
        "static_supported_weak_positive_guarded": 1,
        "static_review_weak_positive_guarded": 2,
        "static_watch_breathing_hardguard": 3,
        "static_watch_breathing_confirmed": 4,
        "static_watch_confound_hardguard": 5,
        "static_watch_confound_confirmed": 6,
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
            ranked["priority"] = ranked["support_status_v3"].map(priority).fillna(99)
            ranked = ranked.sort_values(["priority", "segment_hours"], ascending=[True, False])
            top = ranked.iloc[0]
            run_status = str(top["support_status_v3"])
            run_risk = str(top["support_risk_v3"])
            run_reason = str(top["support_reason_v3"])
            if run_status == "transition_secondary_control" and not transition_secondary_group.empty:
                ranked = transition_secondary_group.copy()
                ranked["post_rank"] = ranked["segment_name"].eq("post_change").map({True: 0, False: 1})
                ranked = ranked.sort_values(["post_rank", "segment_hours"], ascending=[True, False])
                top = ranked.iloc[0]

        review_count = int(group["needs_review_v3"].fillna(False).sum())
        rows.append(
            {
                "run_id": run_id,
                "run_support_status_v3": run_status,
                "run_support_risk_v3": run_risk,
                "primary_segment_id_v3": top["segment_id"],
                "primary_segment_name_v3": top["segment_name"],
                "primary_task_v3": top["primary_task"],
                "guard_feature_score_v3": top["guard_feature_score_v3"],
                "weak_positive_support_score_v2": top["weak_positive_support_score_v2"],
                "memory_role_v2": top["predicted_memory_role_v2"],
                "anomaly_advantage_v2": top["anomaly_advantage_v2"],
                "support_reason_v3": run_reason,
                "needs_review_v3": bool(review_count > 0 or run_status in {"transition_primary_support", "transition_secondary_control"}),
                "review_segment_count_v3": review_count,
                "segment_status_counts_v3": json.dumps(
                    group["support_status_v3"].value_counts(dropna=False).to_dict(),
                    ensure_ascii=False,
                ),
            }
        )
    return pd.DataFrame(rows).sort_values(["run_support_status_v3", "run_id"]).reset_index(drop=True)


def build_review_queue(segment_df: pd.DataFrame, run_df: pd.DataFrame) -> pd.DataFrame:
    priority = {
        "transition_primary_support": 0,
        "static_supported_weak_positive_guarded": 1,
        "static_review_weak_positive_guarded": 2,
        "static_watch_breathing_hardguard": 3,
        "static_watch_breathing_confirmed": 4,
        "static_watch_confound_hardguard": 5,
        "static_watch_confound_confirmed": 6,
        "transition_secondary_control": 7,
    }
    rows: List[Dict[str, Any]] = []
    for _, run in run_df[run_df["needs_review_v3"]].iterrows():
        run_id = run["run_id"]
        group = segment_df[segment_df["run_id"] == run_id].copy()
        run_status = str(run["run_support_status_v3"])

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
            anchor = group[group["support_status_v3"] == run_status].copy()
            if anchor.empty:
                anchor = group[group["needs_review_v3"]].copy()
            anchor = anchor.sort_values(["segment_hours"], ascending=[False])
            top = anchor.iloc[0]

        rows.append(
            {
                "run_id": run_id,
                "segment_id": top["segment_id"],
                "segment_name": top["segment_name"],
                "support_status_v3": run_status,
                "support_risk_v3": run["run_support_risk_v3"],
                "guard_feature_score_v3": run["guard_feature_score_v3"],
                "memory_role_v2": run["memory_role_v2"],
                "anomaly_advantage_v2": run["anomaly_advantage_v2"],
                "support_reason_v3": run["support_reason_v3"],
                "review_priority_v3": int(priority.get(run_status, 99)),
                "review_segment_count_v3": run["review_segment_count_v3"],
            }
        )

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["review_priority_v3", "run_id"]).reset_index(drop=True)


def write_markdown(
    path: str,
    summary: Dict[str, Any],
    run_df: pd.DataFrame,
    review_df: pd.DataFrame,
    old_eval_df: pd.DataFrame,
) -> None:
    lines = [
        "# 新补充数据 Segment Static Support v3",
        "",
        "## 核心结论",
        "",
        f"- segment_support_counts_v3: `{summary['segment_support_counts_v3']}`",
        f"- run_support_counts_v3: `{summary['run_support_counts_v3']}`",
        f"- old_hard_negative_anomaly_false_positive_count_v3: `{summary['old_hard_negative_anomaly_false_positive_count_v3']}`",
        f"- weak_positive_guarded_runs_v3: `{summary['weak_positive_guarded_runs_v3']}`",
        f"- weak_positive_memory_unresolved_runs_v3: `{summary['weak_positive_memory_unresolved_runs_v3']}`",
        f"- breathing_hardguard_runs_v3: `{summary['breathing_hardguard_runs_v3']}`",
        f"- confound_hardguard_runs_v3: `{summary['confound_hardguard_runs_v3']}`",
        "",
        "## 当前判断",
        "",
        "- 这一步不是继续放大静态支持，而是给 `v2` 加上跨数据集守门和 old hard negative 约束。",
        "- 只有守门特征和 tri-memory 同时站得住，弱正样本才允许继续保留支持；否则回到 review。",
        "- `breathing_watch / confound` 如果在 tri-memory 下仍靠近 hard negative，就继续压实为 watch，不允许被重新抬成正侧。",
        "",
        "## 运行级支持结果",
        "",
    ]

    for _, row in run_df.iterrows():
        lines.append(
            f"- {row['run_id']} | status={row['run_support_status_v3']} | risk={row['run_support_risk_v3']} | "
            f"primary_segment={row['primary_segment_name_v3']} | guard={fmt_score(row['guard_feature_score_v3'])} | "
            f"memory={row['memory_role_v2']} | anomaly_adv={fmt_score(row['anomaly_advantage_v2'])} | "
            f"needs_review={bool(row['needs_review_v3'])} | reason={row['support_reason_v3']}"
        )

    if not review_df.empty:
        lines.extend(["", "## 建议复核队列", ""])
        for _, row in review_df.iterrows():
            lines.append(
                f"- {row['run_id']} | segment={row['segment_name']} | status={row['support_status_v3']} | "
                f"priority={int(row['review_priority_v3'])} | memory={row['memory_role_v2']} | reason={row['support_reason_v3']}"
            )

    if not old_eval_df.empty:
        lines.extend(["", "## Old Hard Negative 守门结果", ""])
        for _, row in old_eval_df.iterrows():
            lines.append(
                f"- {row['segment_id']} | predicted={row['predicted_memory_role_v2']} | anomaly_adv={fmt_score(row['anomaly_advantage_v2'])} | "
                f"health_only_risk={fmt_score(row['health_only_risk_v2'])}"
            )

    lines.extend(
        [
            "",
            "## 结论",
            "",
            "1. `v3` 的主要目标是验证“old hard negatives 不会被静态支持层重新推成 anomaly-like”，不是继续追求更高的静态覆盖率。",
            "2. 如果 `weak positive` 在 tri-memory 下仍然落到 hard negative 一侧，就说明它当前只能保留为 review 支持，而不能安全升级成更强的正参考。",
            "3. `breathing_watch / confound` 若在 tri-memory 下继续靠近 hard negative，说明当前主线程里的 `watch` 处理是正确的。",
            "4. 下一步若继续推进，应优先把这套 guarded 结果接到 review/rerank，而不是接到默认 `final_status`。",
            "",
        ]
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    segment_df = pd.read_csv(args.segment_support_csv)
    feature_df = pd.read_csv(args.feature_table_csv)
    memory_df = pd.read_csv(args.memory_scores_csv)
    guard_df = pd.read_csv(args.guard_csv)

    guard_features = guard_df["feature"].tolist()
    current_memory = memory_df[memory_df["query_origin_v2"] == "current_mainfield"].copy()
    old_eval_df = memory_df[memory_df["query_origin_v2"] == "old_hard_negative"].copy()

    merged = segment_df.merge(
        feature_df[["segment_id"] + guard_features],
        on="segment_id",
        how="left",
    )
    merged = merged.merge(
        current_memory[
            [
                "segment_id",
                "predicted_memory_role_v2",
                "anomaly_advantage_v2",
                "health_only_risk_v2",
                "distance_health_core",
                "distance_anomaly_reference",
                "distance_hard_negative",
            ]
        ],
        on="segment_id",
        how="left",
    )
    merged["guard_feature_score_v3"] = merged.apply(lambda row: guard_score(row, guard_df), axis=1)

    rows: List[Dict[str, Any]] = []
    for _, row in merged.iterrows():
        status_v3, risk_v3, reason_v3, needs_review_v3 = segment_status_v3(row, args)
        row_dict = row.to_dict()
        row_dict.update(
            {
                "support_status_v3": status_v3,
                "support_risk_v3": risk_v3,
                "support_reason_v3": reason_v3,
                "needs_review_v3": needs_review_v3,
            }
        )
        rows.append(row_dict)

    segment_v3 = pd.DataFrame(rows).sort_values(["support_status_v3", "run_id", "segment_name"]).reset_index(drop=True)
    run_v3 = aggregate_run_support(segment_v3)
    review_v3 = build_review_queue(segment_v3, run_v3)

    summary = {
        "segment_support_counts_v3": segment_v3["support_status_v3"].value_counts(dropna=False).to_dict(),
        "run_support_counts_v3": run_v3["run_support_status_v3"].value_counts(dropna=False).to_dict(),
        "review_segment_count_v3": int(len(review_v3)),
        "review_run_count_v3": int(review_v3["run_id"].nunique()) if not review_v3.empty else 0,
        "old_hard_negative_count_v3": int(len(old_eval_df)),
        "old_hard_negative_anomaly_false_positive_count_v3": int(
            old_eval_df["predicted_memory_role_v2"].eq("anomaly_reference").sum()
        ),
        "weak_positive_guarded_runs_v3": int(run_v3["run_support_status_v3"].eq("static_supported_weak_positive_guarded").sum()),
        "weak_positive_memory_unresolved_runs_v3": int(
            run_v3["run_support_status_v3"].eq("static_review_weak_positive_guarded").sum()
        ),
        "breathing_hardguard_runs_v3": int(run_v3["run_support_status_v3"].eq("static_watch_breathing_hardguard").sum()),
        "confound_hardguard_runs_v3": int(run_v3["run_support_status_v3"].eq("static_watch_confound_hardguard").sum()),
    }

    outputs = {
        "segment_support_csv": os.path.join(args.output_dir, "segment_support_output_v3.csv"),
        "run_support_csv": os.path.join(args.output_dir, "run_support_output_v3.csv"),
        "review_queue_csv": os.path.join(args.output_dir, "segment_review_queue_v3.csv"),
        "old_hard_eval_csv": os.path.join(args.output_dir, "old_hard_negative_eval_v3.csv"),
        "report_md": os.path.join(args.output_dir, "segment_static_support_report_v3.md"),
        "report_json": os.path.join(args.output_dir, "segment_static_support_report_v3.json"),
    }

    segment_v3.to_csv(outputs["segment_support_csv"], index=False, encoding="utf-8-sig")
    run_v3.to_csv(outputs["run_support_csv"], index=False, encoding="utf-8-sig")
    review_v3.to_csv(outputs["review_queue_csv"], index=False, encoding="utf-8-sig")
    old_eval_df.to_csv(outputs["old_hard_eval_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["report_md"], summary, run_v3, review_v3, old_eval_df)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
