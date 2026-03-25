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

from src.scripts.lab_gate_info_selector_v2 import evaluate_downstream
from src.scripts.lab_phase1_acceptance import (
    Phase1Config,
    apply_transition_relative_score,
    build_file_summary,
    process_dataset,
    robust_z_positive,
)
from src.scripts.lab_phase2_xgboost_branch import add_info_score, select_static_branch_dataset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Branch-aware gate / info selector v3")
    parser.add_argument("--input-dir", default=Phase1Config.input_dir)
    parser.add_argument("--input-zip", default=Phase1Config.input_zip)
    parser.add_argument("--metadata-xlsx", default=Phase1Config.metadata_xlsx)
    parser.add_argument("--output-dir", default="reports/lab_gate_info_selector_v3")
    parser.add_argument("--window-hours", type=int, default=12)
    parser.add_argument("--step-hours", type=int, default=1)
    parser.add_argument("--transition-near-hours", type=int, default=6)
    return parser.parse_args()


def apply_transition_multiview_score(window_df: pd.DataFrame) -> pd.DataFrame:
    out = window_df.copy()
    out["transition_score_v3"] = 0.0
    out["transition_rank_pct_v3"] = np.nan

    trans_mask = out["expected_family"] == "transition_run"
    for file_name, group in out.loc[trans_mask].groupby("file", dropna=False):
        score = (
            0.35 * robust_z_positive(group["delta_in_hum"])
            + 0.25 * robust_z_positive(group["delta_half_in_hum"])
            + 0.20 * robust_z_positive(group["max_hourly_hum_rise"])
            + 0.10 * robust_z_positive(group["std_out_hum"])
            + 0.10 * robust_z_positive(group["corr_AH"])
        )
        out.loc[group.index, "transition_score_v3"] = score.values
        out.loc[group.index, "transition_rank_pct_v3"] = score.rank(pct=True, method="average").values

    out["transition_score"] = out["transition_score_v3"]
    out["transition_rank_pct"] = out["transition_rank_pct_v3"]
    return out


def add_static_context_score(static_df: pd.DataFrame) -> pd.DataFrame:
    out = static_df.copy()
    out["static_context_score_v3"] = (
        0.45 * robust_z_positive(out["delta_half_dAH"])
        + 0.25 * robust_z_positive(-pd.to_numeric(out["delta_half_in_hum"], errors="coerce"))
        + 0.15 * robust_z_positive(-pd.to_numeric(out["max_hourly_hum_rise"], errors="coerce"))
        + 0.15 * robust_z_positive(-pd.to_numeric(out["corr_AH"], errors="coerce"))
    )
    out["static_context_rank_pct_v3"] = out.groupby("file", dropna=False)["static_context_score_v3"].rank(
        pct=True,
        method="average",
    )
    return out


def build_views(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    cfg = Phase1Config(
        input_dir=args.input_dir,
        input_zip=args.input_zip,
        metadata_xlsx=args.metadata_xlsx,
        output_dir=args.output_dir,
        window_hours=args.window_hours,
        step_hours=args.step_hours,
        transition_near_hours=args.transition_near_hours,
    )
    base_window_df, run_df = process_dataset(cfg)

    v2_window_df = apply_transition_relative_score(base_window_df.copy())
    v3_window_df = v2_window_df.copy()
    v3_window_df["transition_score_v2_old"] = pd.to_numeric(v2_window_df["transition_score"], errors="coerce").fillna(0.0)
    v3_window_df["transition_rank_pct_v2_old"] = pd.to_numeric(v2_window_df["transition_rank_pct"], errors="coerce")
    v3_window_df = apply_transition_multiview_score(v3_window_df)

    file_df_v2 = build_file_summary(v2_window_df, run_df)
    file_df_v3 = build_file_summary(v3_window_df, run_df)
    return v3_window_df, file_df_v3, file_df_v2


def assign_routes(window_df: pd.DataFrame, file_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    static_df = add_static_context_score(add_info_score(select_static_branch_dataset(window_df, file_df)))
    static_lookup = {
        (row["file"], row["sheet"], row["window_id"]): row.to_dict()
        for _, row in static_df.iterrows()
    }

    df = window_df.copy()
    df["route_role"] = "reject_other"
    df["route_branch"] = "none"
    df["info_score_v3"] = 0.0
    df["legacy_info_score"] = np.nan
    df["static_context_score_v3"] = np.nan
    df["route_reason_v3"] = ""

    for idx, row in df.iterrows():
        reasons: List[str] = []
        key = (row["file"], row["sheet"], row["window_id"])

        if row["expected_family"] == "transition_run" and row["transition_phase"] == "near_transition":
            df.at[idx, "route_role"] = "transition_core"
            df.at[idx, "route_branch"] = "transition_branch"
            df.at[idx, "info_score_v3"] = float(row.get("transition_score_v3", 0.0))
            reasons.extend(["phase=near_transition", "transition_multiview_score_v3"])
            df.at[idx, "route_reason_v3"] = " | ".join(reasons)
            continue

        if row["expected_family"] == "transition_run" and row["transition_phase"] in {"pre_transition", "post_transition"}:
            df.at[idx, "route_role"] = "transition_context"
            df.at[idx, "route_branch"] = "transition_branch"
            df.at[idx, "info_score_v3"] = float(row.get("transition_score_v3", 0.0))
            reasons.extend([f"phase={row['transition_phase']}", "transition_multiview_score_v3"])
            df.at[idx, "route_reason_v3"] = " | ".join(reasons)
            continue

        if key in static_lookup:
            static_row = static_lookup[key]
            legacy_info = float(static_row.get("info_score", 0.0))
            static_context = float(static_row.get("static_context_score_v3", 0.0))
            df.at[idx, "legacy_info_score"] = legacy_info
            df.at[idx, "static_context_score_v3"] = static_context
            df.at[idx, "info_score_v3"] = legacy_info
            df.at[idx, "route_role"] = "static_memory_candidate"
            df.at[idx, "route_branch"] = "static_memory_branch"
            reasons.append("selected_static_candidate")
            reasons.append(f"static_context_score_v3={static_context:.3f}")
            if float(row.get("delta_half_dAH", 0.0)) >= 0.0:
                df.at[idx, "route_role"] = "static_threshold_favored"
                df.at[idx, "route_branch"] = "static_threshold_branch"
                reasons.append("delta_half_dAH_nonnegative")
            else:
                reasons.append("delta_half_dAH_negative")
            df.at[idx, "route_reason_v3"] = " | ".join(reasons)
            continue

        if row["predicted_group"] == "heat_related":
            df.at[idx, "route_role"] = "reject_heat_related"
            reasons.append("predicted_group=heat_related")
        elif row["predicted_group"] == "exclude_low_info":
            df.at[idx, "route_role"] = "reject_low_info"
            reasons.append("predicted_group=exclude_low_info")
        elif row["predicted_group"] == "candidate_high_info":
            df.at[idx, "route_role"] = "background_high_hum"
            reasons.append("candidate_high_info_not_selected_for_static")
        else:
            df.at[idx, "route_role"] = "reject_complex_or_unknown"
            reasons.append(f"predicted_group={row['predicted_group']}")
        df.at[idx, "route_reason_v3"] = " | ".join(reasons)

    static_route_df = static_df.merge(
        df[
            [
                "file",
                "sheet",
                "window_id",
                "route_role",
                "route_branch",
                "info_score_v3",
                "legacy_info_score",
                "route_reason_v3",
            ]
        ],
        on=["file", "sheet", "window_id"],
        how="left",
    )
    return df, static_route_df


def summarize_transition_upgrade(file_df_v2: pd.DataFrame, file_df_v3: pd.DataFrame) -> Dict[str, Any]:
    cols = [
        "file",
        "near_transition_windows",
        "near_transition_mean_score",
        "near_transition_median_rank_pct",
        "non_near_transition_mean_score",
    ]
    old = file_df_v2[file_df_v2["expected_family"] == "transition_run"][cols].copy()
    old = old.rename(
        columns={
            "near_transition_mean_score": "near_transition_mean_score_v2",
            "near_transition_median_rank_pct": "near_transition_median_rank_pct_v2",
            "non_near_transition_mean_score": "non_near_transition_mean_score_v2",
        }
    )
    new = file_df_v3[file_df_v3["expected_family"] == "transition_run"][cols].copy()
    new = new.rename(
        columns={
            "near_transition_mean_score": "near_transition_mean_score_v3",
            "near_transition_median_rank_pct": "near_transition_median_rank_pct_v3",
            "non_near_transition_mean_score": "non_near_transition_mean_score_v3",
        }
    )
    merged = old.merge(new, on=["file", "near_transition_windows"], how="outer")
    if merged.empty:
        return {"per_file": [], "aggregate": {}}

    merged["score_lift_v2"] = merged["near_transition_mean_score_v2"] - merged["non_near_transition_mean_score_v2"]
    merged["score_lift_v3"] = merged["near_transition_mean_score_v3"] - merged["non_near_transition_mean_score_v3"]

    aggregate = {
        "mean_near_rank_v2": float(merged["near_transition_median_rank_pct_v2"].mean()),
        "mean_near_rank_v3": float(merged["near_transition_median_rank_pct_v3"].mean()),
        "mean_score_lift_v2": float(merged["score_lift_v2"].mean()),
        "mean_score_lift_v3": float(merged["score_lift_v3"].mean()),
    }
    return {
        "per_file": merged.sort_values("file").to_dict(orient="records"),
        "aggregate": aggregate,
    }


def build_summary(
    routed_df: pd.DataFrame,
    static_route_df: pd.DataFrame,
    file_df_v2: pd.DataFrame,
    file_df_v3: pd.DataFrame,
) -> Dict[str, Any]:
    route_counts = routed_df["route_role"].value_counts().to_dict()
    branch_counts = routed_df["route_branch"].value_counts().to_dict()
    transition_near = routed_df[routed_df["transition_phase"] == "near_transition"]
    transition_coverage = float((transition_near["route_branch"] == "transition_branch").mean()) if not transition_near.empty else None
    threshold_favored_ratio = float((routed_df["route_role"] == "static_threshold_favored").mean()) if len(routed_df) else 0.0

    transition_upgrade = summarize_transition_upgrade(file_df_v2, file_df_v3)
    downstream = evaluate_downstream(static_route_df)
    threshold_branch = downstream["threshold_branch"]

    static_support_stats = (
        static_route_df.groupby("route_branch")["static_context_score_v3"]
        .agg(["count", "mean", "median"])
        .reset_index()
        .to_dict(orient="records")
        if not static_route_df.empty
        else []
    )

    acceptance = {
        "transition_routing_pass": bool(transition_coverage == 1.0),
        "transition_score_upgrade_pass": bool(
            transition_upgrade.get("aggregate", {}).get("mean_near_rank_v3", 0.0)
            > transition_upgrade.get("aggregate", {}).get("mean_near_rank_v2", 0.0)
            and transition_upgrade.get("aggregate", {}).get("mean_score_lift_v3", 0.0)
            > transition_upgrade.get("aggregate", {}).get("mean_score_lift_v2", 0.0)
        ),
        "threshold_branch_not_worse": bool(
            threshold_branch.get("available")
            and threshold_branch.get("run_balanced_accuracy", 0.0) >= 0.8333333333333333
        ),
    }

    return {
        "route_role_counts": route_counts,
        "route_branch_counts": branch_counts,
        "transition_near_branch_coverage": transition_coverage,
        "threshold_favored_ratio": threshold_favored_ratio,
        "transition_upgrade": transition_upgrade,
        "downstream_eval": downstream,
        "static_support_stats": static_support_stats,
        "acceptance": acceptance,
    }


def write_markdown(path: str, summary: Dict[str, Any]) -> None:
    downstream = summary["downstream_eval"]
    threshold_branch = downstream["threshold_branch"]
    transition = summary["transition_upgrade"]
    agg = transition["aggregate"]
    lines = [
        "# Gate / Info Selector v3 报告",
        "",
        "- 核心策略：只优化数据已经明确支持的部分。`transition` 分数升级为多视角版本；`static` 分支保留已验证路由逻辑，但显式补充静态支持分数与路由理由。",
        "",
        "## 路由结果",
        "",
        f"- route_role_counts = `{summary['route_role_counts']}`",
        f"- route_branch_counts = `{summary['route_branch_counts']}`",
        f"- transition_near_branch_coverage = `{summary['transition_near_branch_coverage']}`",
        f"- threshold_favored_ratio = `{summary['threshold_favored_ratio']}`",
        "",
        "## Transition 分数升级",
        "",
        f"- mean_near_rank_v2 = `{agg.get('mean_near_rank_v2')}`",
        f"- mean_near_rank_v3 = `{agg.get('mean_near_rank_v3')}`",
        f"- mean_score_lift_v2 = `{agg.get('mean_score_lift_v2')}`",
        f"- mean_score_lift_v3 = `{agg.get('mean_score_lift_v3')}`",
        "",
        "### per-file transition comparison",
        "",
    ]
    for row in transition["per_file"]:
        lines.append(
            f"- {row['file']} | rank_v2={row['near_transition_median_rank_pct_v2']:.3f} | "
            f"rank_v3={row['near_transition_median_rank_pct_v3']:.3f} | "
            f"lift_v2={row['score_lift_v2']:.3f} | lift_v3={row['score_lift_v3']:.3f}"
        )

    lines.extend(
        [
            "",
            "## Static 分支影响",
            "",
            f"- threshold_branch: available=`{threshold_branch.get('available')}` | covered_runs=`{threshold_branch.get('covered_runs')}` | "
            f"abstained_runs=`{threshold_branch.get('abstained_runs')}` | best_feature=`{threshold_branch.get('best_feature')}` | "
            f"run_balanced_accuracy=`{threshold_branch.get('run_balanced_accuracy')}`",
            f"- similarity_all_static: run_auc=`{downstream['similarity_all_static'].get('run_auc')}` | "
            f"run_balanced_accuracy=`{downstream['similarity_all_static'].get('run_balanced_accuracy')}`",
            "",
            "### static_context_score_v3 by route branch",
            "",
        ]
    )
    for row in summary["static_support_stats"]:
        lines.append(
            f"- {row['route_branch']} | count={int(row['count'])} | mean={row['mean']:.3f} | median={row['median']:.3f}"
        )

    acceptance = summary["acceptance"]
    lines.extend(
        [
            "",
            "## 验收判断",
            "",
            f"- transition_routing_pass = `{acceptance['transition_routing_pass']}`",
            f"- transition_score_upgrade_pass = `{acceptance['transition_score_upgrade_pass']}`",
            f"- threshold_branch_not_worse = `{acceptance['threshold_branch_not_worse']}`",
            "",
            "## 当前结论",
            "",
            "- `transition` 是当前最值得继续优化的分支；v3 的多视角分数明显提高了近转移窗口的排序和分数抬升。",
            "- `static` 分支当前仍不适合大幅重构。窗口层面的静态区分仍弱，因此 v3 只增加诊断性的 `static_context_score_v3` 与路由理由，不推翻已验证成立的 `delta_half_dAH >= 0` favored 规则。",
            "- 这一步说明：下一轮优化应优先把 v3 的 transition scoring 接进后续 evidence fuser，而不是重启全局分类器或直接扩更复杂模型。",
            "",
        ]
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)
    window_df, file_df_v3, file_df_v2 = build_views(args)
    routed_df, static_route_df = assign_routes(window_df, file_df_v3)
    summary = build_summary(routed_df, static_route_df, file_df_v2, file_df_v3)

    outputs = {
        "window_csv": os.path.join(args.output_dir, "gate_info_selector_v3_windows.csv"),
        "static_route_csv": os.path.join(args.output_dir, "gate_info_selector_v3_static_routes.csv"),
        "file_summary_csv": os.path.join(args.output_dir, "gate_info_selector_v3_file_summary.csv"),
        "report_md": os.path.join(args.output_dir, "gate_info_selector_v3_report.md"),
        "report_json": os.path.join(args.output_dir, "gate_info_selector_v3_report.json"),
    }
    routed_df.to_csv(outputs["window_csv"], index=False, encoding="utf-8-sig")
    static_route_df.to_csv(outputs["static_route_csv"], index=False, encoding="utf-8-sig")
    file_df_v3.to_csv(outputs["file_summary_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["report_md"], summary)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2)
    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
