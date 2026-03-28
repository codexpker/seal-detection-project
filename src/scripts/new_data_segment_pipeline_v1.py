#!/usr/bin/env python3
import argparse
import json
import os
import sys
from typing import Any, Dict, List

import numpy as np
import pandas as pd

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.scripts.new_data_deep_analysis_v1 import build_run_and_segment_tables, load_readme


STATIC_FEATURES: List[str] = [
    "delta_half_in_h",
    "delta_half_dAH",
    "slope_in_h_per_h",
    "slope_dAH_per_h",
    "end_start_dAH",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Segment-based pipeline v1 for new_data.zip")
    parser.add_argument("--input-zip", default="data/new_data.zip")
    parser.add_argument("--readme-xlsx", default="/Users/xpker/Downloads/data_readme.xlsx")
    parser.add_argument("--output-dir", default="reports/new_data_segment_pipeline_v1")
    parser.add_argument("--window-hours", type=int, default=12)
    parser.add_argument("--step-hours", type=int, default=1)
    parser.add_argument("--segment-min-hours", type=float, default=12.0)
    parser.add_argument("--static-strong-votes", type=int, default=4)
    parser.add_argument("--static-min-votes", type=int, default=2)
    return parser.parse_args()


def make_segment_id(row: pd.Series) -> str:
    return f"{row['file']}::{row['segment_name']}"


def build_static_thresholds(seg_df: pd.DataFrame) -> Dict[str, float]:
    pool = seg_df[
        seg_df["segment_analyzable"]
        & seg_df["segment_role"].eq("mainfield_extHigh_intLow_noHeat")
        & seg_df["segment_heat_state"].eq("heat_off")
        & seg_df["segment_ext_level"].eq("high")
        & seg_df["segment_source"].isin(["full_run", "seal_change_to_unsealed"])
    ].copy()
    thresholds: Dict[str, float] = {}
    for feature in STATIC_FEATURES:
        sealed = pd.to_numeric(
            pool.loc[pool["segment_seal_state"] == "sealed", feature],
            errors="coerce",
        ).dropna()
        unsealed = pd.to_numeric(
            pool.loc[pool["segment_seal_state"] == "unsealed", feature],
            errors="coerce",
        ).dropna()
        if sealed.empty or unsealed.empty:
            thresholds[feature] = np.nan
            continue
        thresholds[feature] = float((sealed.median() + unsealed.median()) / 2.0)
    return thresholds


def build_static_segment_table(seg_df: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    thresholds = build_static_thresholds(seg_df)
    mainfield = seg_df[
        seg_df["segment_analyzable"]
        & seg_df["segment_role"].eq("mainfield_extHigh_intLow_noHeat")
        & seg_df["segment_heat_state"].eq("heat_off")
        & seg_df["segment_ext_level"].eq("high")
    ].copy()

    rows: List[Dict[str, Any]] = []
    for _, row in mainfield.iterrows():
        vote_hits: List[str] = []
        threshold_snapshot: Dict[str, float] = {}
        for feature in STATIC_FEATURES:
            cutoff = thresholds.get(feature, np.nan)
            value = pd.to_numeric(pd.Series([row.get(feature)]), errors="coerce").iloc[0]
            if pd.isna(cutoff) or pd.isna(value):
                continue
            threshold_snapshot[feature] = cutoff
            if float(value) > float(cutoff):
                vote_hits.append(feature)

        vote_count = len(vote_hits)
        segment_source = str(row["segment_source"])
        seal_state = str(row["segment_seal_state"])
        segment_name = str(row["segment_name"])

        static_bucket = "static_holdout"
        recommended_use = "holdout_only"
        rationale = "not enough evidence for static training use"

        if segment_source == "heat_off":
            static_bucket = "static_heatoff_confound_challenge"
            recommended_use = "challenge_only"
            rationale = "post-heat-off segment enters the no-heat battlefield but remains confounded by prior heating"
        elif seal_state == "sealed":
            if vote_count <= 1 and float(pd.to_numeric(pd.Series([row.get('delta_half_dAH')]), errors='coerce').iloc[0]) <= float(
                thresholds.get("delta_half_dAH", np.inf)
            ):
                static_bucket = "static_negative_reference"
                recommended_use = "train_eval_primary"
                rationale = "sealed no-heat mainfield segment stays below segment-level response thresholds"
            else:
                static_bucket = "static_breathing_watch"
                recommended_use = "challenge_only"
                rationale = "sealed mainfield segment shows response-like behavior and should be kept as a hard case"
        elif seal_state == "unsealed":
            if (
                segment_source == "seal_change_to_unsealed"
                and segment_name == "post_change"
                and vote_count >= int(args.static_strong_votes)
                and float(pd.to_numeric(pd.Series([row.get('delta_half_dAH')]), errors='coerce').iloc[0])
                > float(thresholds.get("delta_half_dAH", -np.inf))
                and float(pd.to_numeric(pd.Series([row.get('end_start_dAH')]), errors='coerce').iloc[0])
                > float(thresholds.get("end_start_dAH", -np.inf))
            ):
                static_bucket = "static_positive_reference"
                recommended_use = "train_eval_primary"
                rationale = "post-change unsealed mainfield segment shows sustained positive response on segment features"
            elif vote_count >= int(args.static_min_votes):
                static_bucket = "static_positive_eval_only"
                recommended_use = "eval_only_review"
                rationale = "unsealed mainfield segment is labeled positive but weaker than transition-derived post-change references"
            else:
                static_bucket = "static_positive_eval_only"
                recommended_use = "eval_only_review"
                rationale = "unsealed mainfield segment has weak static evidence and should be kept for review rather than primary training"

        rows.append(
            {
                "segment_id": make_segment_id(row),
                "run_id": row["file"],
                "segment_name": segment_name,
                "segment_source": segment_source,
                "segment_hours": row["segment_hours"],
                "segment_seal_state": seal_state,
                "static_vote_count": vote_count,
                "static_vote_hits": ",".join(vote_hits),
                "static_thresholds": json.dumps(threshold_snapshot, ensure_ascii=False),
                "static_bucket": static_bucket,
                "recommended_use": recommended_use,
                "rationale": rationale,
                **{feature: row.get(feature, np.nan) for feature in STATIC_FEATURES},
            }
        )

    return pd.DataFrame(rows).sort_values(["static_bucket", "run_id", "segment_name"]).reset_index(drop=True)


def build_transition_table(run_df: pd.DataFrame, seg_df: pd.DataFrame) -> pd.DataFrame:
    change_runs = run_df[run_df["change_type"] == "seal_change_to_unsealed"].copy()
    rows: List[Dict[str, Any]] = []
    for _, run in change_runs.iterrows():
        file_name = str(run["file"])
        seg_rows = seg_df[seg_df["file"] == file_name].copy()
        pre = seg_rows[seg_rows["segment_name"] == "pre_change"].head(1)
        post = seg_rows[seg_rows["segment_name"] == "post_change"].head(1)

        pre_row = pre.iloc[0] if not pre.empty else {}
        post_row = post.iloc[0] if not post.empty else {}
        mainfield_transition = (
            str(run.get("initial_role", "")) == "mainfield_extHigh_intLow_noHeat"
            and str(run.get("post_role", "")) == "mainfield_extHigh_intLow_noHeat"
        )

        if mainfield_transition:
            transition_bucket = "transition_primary_mainfield"
            recommended_use = "transition_train_eval_primary"
            rationale = "seal-to-unsealed run stays inside the main battlefield and is suitable for transition event evaluation"
        else:
            transition_bucket = "transition_secondary_control"
            recommended_use = "transition_challenge_secondary"
            rationale = "seal-to-unsealed run is valuable for transition scoring but belongs to a control/secondary condition family"

        rows.append(
            {
                "run_id": file_name,
                "change_type": run.get("change_type", ""),
                "initial_role": run.get("initial_role", ""),
                "post_role": run.get("post_role", ""),
                "change_in_range": bool(run.get("change_in_range", False)),
                "pre_segment_id": make_segment_id(pre_row) if isinstance(pre_row, pd.Series) else "",
                "post_segment_id": make_segment_id(post_row) if isinstance(post_row, pd.Series) else "",
                "pre_hours": run.get("pre_hours", np.nan),
                "post_hours": run.get("post_hours", np.nan),
                "pre_analyzable": bool(pre_row.get("segment_analyzable", False)) if isinstance(pre_row, pd.Series) else False,
                "post_analyzable": bool(post_row.get("segment_analyzable", False)) if isinstance(post_row, pd.Series) else False,
                "transition_bucket": transition_bucket,
                "recommended_use": recommended_use,
                "rationale": rationale,
            }
        )

    return pd.DataFrame(rows).sort_values(["transition_bucket", "run_id"]).reset_index(drop=True)


def build_canonical_segment_manifest(
    run_df: pd.DataFrame,
    seg_df: pd.DataFrame,
    static_df: pd.DataFrame,
    transition_df: pd.DataFrame,
) -> pd.DataFrame:
    out = seg_df.copy()
    out["segment_id"] = out.apply(make_segment_id, axis=1)
    out = out.merge(
        run_df[
            [
                "file",
                "device_id",
                "change_type",
                "initial_role",
                "post_role",
                "change_ts",
                "candidate_high_info_ratio",
                "dominant_label",
            ]
        ],
        on="file",
        how="left",
    )
    out = out.merge(
        static_df[
            [
                "segment_id",
                "static_bucket",
                "static_vote_count",
                "static_vote_hits",
                "recommended_use",
                "rationale",
            ]
        ].rename(
            columns={
                "recommended_use": "static_recommended_use",
                "rationale": "static_rationale",
            }
        ),
        on="segment_id",
        how="left",
    )

    transition_pre = transition_df[["pre_segment_id", "transition_bucket"]].copy()
    transition_pre = transition_pre[transition_pre["pre_segment_id"].astype(str) != ""].rename(
        columns={"pre_segment_id": "segment_id", "transition_bucket": "transition_bucket"}
    )
    transition_post = transition_df[["post_segment_id", "transition_bucket"]].copy()
    transition_post = transition_post[transition_post["post_segment_id"].astype(str) != ""].rename(
        columns={"post_segment_id": "segment_id", "transition_bucket": "transition_bucket"}
    )
    transition_map = pd.concat([transition_pre, transition_post], ignore_index=True).drop_duplicates()
    out = out.merge(transition_map, on="segment_id", how="left")

    out["use_for_static_primary"] = out["static_recommended_use"].eq("train_eval_primary")
    out["use_for_static_eval_only"] = out["static_recommended_use"].eq("eval_only_review")
    out["use_for_transition_context"] = out["transition_bucket"].notna()
    out["use_for_control_challenge"] = (
        out["segment_analyzable"].fillna(False)
        & ~out["use_for_static_primary"]
        & (
            out["static_bucket"].isin(["static_breathing_watch", "static_heatoff_confound_challenge"])
            | out["segment_role"].isin(["balanced_control", "internal_moisture_control", "highhum_heated"])
            | out["segment_source"].isin(["heat_on", "heat_off", "ext_humidity_up"])
        )
    )

    def choose_primary_task(row: pd.Series) -> str:
        if bool(row["use_for_static_primary"]):
            return "static_mainfield_primary"
        if bool(row["use_for_transition_context"]):
            return "transition_context"
        if bool(row["use_for_static_eval_only"]):
            return "static_eval_only"
        if not bool(row["segment_analyzable"]):
            return "short_context_only"
        if bool(row["use_for_control_challenge"]):
            return "control_challenge"
        return "holdout"

    out["primary_task"] = out.apply(choose_primary_task, axis=1)
    out["secondary_tasks"] = out.apply(
        lambda row: ",".join(
            task
            for task, enabled in [
                ("transition_context", bool(row["use_for_transition_context"]) and row["primary_task"] != "transition_context"),
                ("control_challenge", bool(row["use_for_control_challenge"]) and row["primary_task"] != "control_challenge"),
                ("static_eval_only", bool(row["use_for_static_eval_only"]) and row["primary_task"] != "static_eval_only"),
            ]
            if enabled
        ),
        axis=1,
    )
    return out.sort_values(["primary_task", "segment_role", "file", "segment_name"]).reset_index(drop=True)


def build_summary(
    manifest_df: pd.DataFrame,
    static_df: pd.DataFrame,
    transition_df: pd.DataFrame,
) -> Dict[str, Any]:
    clean_static = static_df[static_df["recommended_use"] == "train_eval_primary"].copy()
    return {
        "segment_count": int(len(manifest_df)),
        "analyzable_segment_count": int(manifest_df["segment_analyzable"].fillna(False).sum()),
        "primary_task_counts": manifest_df["primary_task"].value_counts(dropna=False).to_dict(),
        "static_bucket_counts": static_df["static_bucket"].value_counts(dropna=False).to_dict() if not static_df.empty else {},
        "transition_bucket_counts": transition_df["transition_bucket"].value_counts(dropna=False).to_dict()
        if not transition_df.empty
        else {},
        "clean_static_reference_count": int(len(clean_static)),
        "clean_static_positive_count": int(clean_static["static_bucket"].eq("static_positive_reference").sum()),
        "clean_static_negative_count": int(clean_static["static_bucket"].eq("static_negative_reference").sum()),
        "control_challenge_count": int(manifest_df["use_for_control_challenge"].fillna(False).sum()),
        "transition_run_count": int(len(transition_df)),
        "transition_primary_count": int(transition_df["transition_bucket"].eq("transition_primary_mainfield").sum())
        if not transition_df.empty
        else 0,
    }


def write_markdown(
    path: str,
    summary: Dict[str, Any],
    static_df: pd.DataFrame,
    transition_df: pd.DataFrame,
    manifest_df: pd.DataFrame,
) -> None:
    lines = [
        "# 新补充数据 段级管线 v1 报告",
        "",
        "## 核心结论",
        "",
        f"- analyzable_segment_count: `{summary['analyzable_segment_count']}`",
        f"- primary_task_counts: `{summary['primary_task_counts']}`",
        f"- static_bucket_counts: `{summary['static_bucket_counts']}`",
        f"- transition_bucket_counts: `{summary['transition_bucket_counts']}`",
        f"- clean_static_reference_count: `{summary['clean_static_reference_count']}`",
        f"- control_challenge_count: `{summary['control_challenge_count']}`",
        "",
        "## 当前最重要的判断",
        "",
        "- 这批 `new_data` 现在已经可以被稳定拆成 `主战场静态段 / transition 段 / 控制挑战段`，不应该再按 whole-run 一把混进主训练。",
        "- 真正适合拿来推进主线的是：`外部高湿-无热源` 主战场里的少数干净段，以及 `seal->unseal` 的 change-run。",
        "- `heat_on / heat_off / ext_humidity_up` 和一部分 `sealed but response-like` 段，应该进入 `watch / abstain / control challenge`，而不是直接并入正样本训练。",
        "",
        "## 主战场静态段建议",
        "",
    ]

    for _, row in static_df.iterrows():
        lines.append(
            f"- {row['run_id']} | segment={row['segment_name']} | bucket={row['static_bucket']} | "
            f"use={row['recommended_use']} | votes={int(row['static_vote_count'])} | "
            f"hits={row['static_vote_hits']} | rationale={row['rationale']}"
        )

    lines.extend(
        [
            "",
            "## Transition 段建议",
            "",
        ]
    )

    for _, row in transition_df.iterrows():
        lines.append(
            f"- {row['run_id']} | bucket={row['transition_bucket']} | use={row['recommended_use']} | "
            f"pre_analyzable={bool(row['pre_analyzable'])} | post_analyzable={bool(row['post_analyzable'])} | "
            f"rationale={row['rationale']}"
        )

    challenge_df = manifest_df[manifest_df["use_for_control_challenge"]].copy()
    if not challenge_df.empty:
        lines.extend(
            [
                "",
                "## 控制 / 干扰挑战段",
                "",
            ]
        )
        for _, row in challenge_df[
            [
                "file",
                "segment_name",
                "segment_role",
                "segment_source",
                "primary_task",
                "secondary_tasks",
                "static_bucket",
            ]
        ].sort_values(["segment_role", "file", "segment_name"]).iterrows():
            lines.append(
                f"- {row['file']} | segment={row['segment_name']} | role={row['segment_role']} | "
                f"source={row['segment_source']} | primary={row['primary_task']} | "
                f"secondary={row['secondary_tasks']} | static_bucket={row['static_bucket']}"
            )

    lines.extend(
        [
            "",
            "## 建模前建议",
            "",
            "1. 先用 `static_negative_reference + static_positive_reference` 形成第一版段级静态参考池，不要把 `breathing_watch / heat_off confound / weak positive` 直接并进去。",
            "2. `transition_primary_mainfield` 先用于事件级验证，`transition_secondary_control` 只作为辅助挑战集。",
            "3. `control_challenge` 段优先用于检验误报控制和 `watch / abstain`，而不是拿来提升正样本数量。",
            "4. 如果后面继续建模，应优先做段级 baseline，而不是 whole-run XGBoost/GRU。",
            "",
        ]
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    readme_df = load_readme(args.readme_xlsx)
    run_df, seg_df = build_run_and_segment_tables(args, readme_df)
    static_df = build_static_segment_table(seg_df, args)
    transition_df = build_transition_table(run_df, seg_df)
    manifest_df = build_canonical_segment_manifest(run_df, seg_df, static_df, transition_df)
    summary = build_summary(manifest_df, static_df, transition_df)

    outputs = {
        "segment_manifest_csv": os.path.join(args.output_dir, "segment_pipeline_manifest.csv"),
        "static_candidates_csv": os.path.join(args.output_dir, "segment_static_candidates.csv"),
        "transition_candidates_csv": os.path.join(args.output_dir, "segment_transition_candidates.csv"),
        "control_challenges_csv": os.path.join(args.output_dir, "segment_control_challenges.csv"),
        "report_md": os.path.join(args.output_dir, "segment_pipeline_report.md"),
        "report_json": os.path.join(args.output_dir, "segment_pipeline_report.json"),
    }

    manifest_df.to_csv(outputs["segment_manifest_csv"], index=False, encoding="utf-8-sig")
    static_df.to_csv(outputs["static_candidates_csv"], index=False, encoding="utf-8-sig")
    transition_df.to_csv(outputs["transition_candidates_csv"], index=False, encoding="utf-8-sig")
    manifest_df[manifest_df["use_for_control_challenge"]].to_csv(
        outputs["control_challenges_csv"],
        index=False,
        encoding="utf-8-sig",
    )
    write_markdown(outputs["report_md"], summary, static_df, transition_df, manifest_df)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
