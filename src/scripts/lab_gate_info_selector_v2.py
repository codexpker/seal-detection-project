#!/usr/bin/env python3
import argparse
import json
import os
import sys
from typing import Any, Dict

import numpy as np
import pandas as pd

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.scripts.lab_phase1_acceptance import Phase1Config, process_dataset, apply_transition_relative_score, build_file_summary
from src.scripts.lab_phase2_xgboost_branch import (
    add_info_score,
    evaluate_baseline_threshold_branch,
    select_static_branch_dataset,
)
from src.scripts.lab_phase2_similarity_branch import run_similarity_fold, summarize_variant


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Branch-aware gate / info selector v2")
    parser.add_argument("--input-dir", default=Phase1Config.input_dir)
    parser.add_argument("--input-zip", default=Phase1Config.input_zip)
    parser.add_argument("--metadata-xlsx", default=Phase1Config.metadata_xlsx)
    parser.add_argument("--output-dir", default="reports/lab_gate_info_selector_v2")
    parser.add_argument("--window-hours", type=int, default=12)
    parser.add_argument("--step-hours", type=int, default=1)
    parser.add_argument("--transition-near-hours", type=int, default=6)
    return parser.parse_args()


def build_views(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame]:
    cfg = Phase1Config(
        input_dir=args.input_dir,
        input_zip=args.input_zip,
        metadata_xlsx=args.metadata_xlsx,
        output_dir=args.output_dir,
        window_hours=args.window_hours,
        step_hours=args.step_hours,
        transition_near_hours=args.transition_near_hours,
    )
    window_df, run_df = process_dataset(cfg)
    window_df = apply_transition_relative_score(window_df)
    file_df = build_file_summary(window_df, run_df)
    return window_df, file_df


def assign_routes(window_df: pd.DataFrame, file_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    static_df = add_info_score(select_static_branch_dataset(window_df, file_df))
    static_keys = set(zip(static_df["file"], static_df["sheet"], static_df["window_id"]))

    df = window_df.copy()
    df["route_role"] = "reject_other"
    df["route_branch"] = "none"
    df["info_score_v2"] = 0.0

    for idx, row in df.iterrows():
        key = (row["file"], row["sheet"], row["window_id"])
        if row["expected_family"] == "transition_run" and row["transition_phase"] == "near_transition":
            df.at[idx, "route_role"] = "transition_core"
            df.at[idx, "route_branch"] = "transition_branch"
            df.at[idx, "info_score_v2"] = float(row.get("transition_score", 0.0))
            continue

        if row["expected_family"] == "transition_run" and row["transition_phase"] in {"pre_transition", "post_transition"}:
            df.at[idx, "route_role"] = "transition_context"
            df.at[idx, "route_branch"] = "transition_branch"
            df.at[idx, "info_score_v2"] = float(row.get("transition_score", 0.0))
            continue

        if key in static_keys:
            info_score = float(static_df.loc[
                (static_df["file"] == row["file"])
                & (static_df["sheet"] == row["sheet"])
                & (static_df["window_id"] == row["window_id"]),
                "info_score",
            ].iloc[0])
            df.at[idx, "info_score_v2"] = info_score
            df.at[idx, "route_role"] = "static_memory_candidate"
            df.at[idx, "route_branch"] = "static_memory_branch"
            if float(row.get("delta_half_dAH", 0.0)) > 0:
                df.at[idx, "route_role"] = "static_threshold_favored"
                df.at[idx, "route_branch"] = "static_threshold_branch"
            continue

        if row["predicted_group"] == "heat_related":
            df.at[idx, "route_role"] = "reject_heat_related"
        elif row["predicted_group"] == "exclude_low_info":
            df.at[idx, "route_role"] = "reject_low_info"
        elif row["predicted_group"] == "candidate_high_info":
            df.at[idx, "route_role"] = "background_high_hum"
        else:
            df.at[idx, "route_role"] = "reject_complex_or_unknown"

    static_route_df = static_df.merge(
        df[["file", "sheet", "window_id", "route_role", "route_branch", "info_score_v2"]],
        on=["file", "sheet", "window_id"],
        how="left",
    )
    return df, static_route_df


def evaluate_downstream(static_route_df: pd.DataFrame) -> Dict[str, Any]:
    baseline_all = evaluate_baseline_threshold_branch(static_route_df)

    threshold_df = static_route_df[static_route_df["route_branch"] == "static_threshold_branch"].copy()
    threshold_eval: Dict[str, Any] = {
        "covered_runs": int(threshold_df["file"].nunique()),
        "covered_windows": int(len(threshold_df)),
        "abstained_runs": int(static_route_df["file"].nunique() - threshold_df["file"].nunique()),
        "available": bool(not threshold_df.empty and threshold_df["file"].nunique() >= 4),
    }
    if threshold_eval["available"]:
        threshold_branch = evaluate_baseline_threshold_branch(threshold_df)
        threshold_eval.update(
            {
                "best_feature": threshold_branch["best_feature"],
                "run_balanced_accuracy": float(threshold_branch["run_balanced_accuracy"]),
                "gain_vs_all_static": float(threshold_branch["run_balanced_accuracy"] - baseline_all["run_balanced_accuracy"]),
            }
        )

    sim_window_all, sim_run_all = run_similarity_fold(static_route_df, k=5)
    sim_summary_all = summarize_variant(sim_window_all, sim_run_all, threshold=0.5)
    memory_only_df = static_route_df[static_route_df["route_branch"] == "static_memory_branch"].copy()
    if not memory_only_df.empty and memory_only_df["file"].nunique() >= 4:
        sim_window_mem, sim_run_mem = run_similarity_fold(memory_only_df, k=5)
        sim_summary_mem = summarize_variant(sim_window_mem, sim_run_mem, threshold=0.5)
    else:
        sim_summary_mem = {"window_metrics": {}, "run_metrics": {}, "pass": False}

    return {
        "baseline_all_static": {
            "best_feature": baseline_all["best_feature"],
            "run_balanced_accuracy": float(baseline_all["run_balanced_accuracy"]),
        },
        "threshold_branch": threshold_eval,
        "similarity_all_static": sim_summary_all["run_metrics"],
        "similarity_memory_only": sim_summary_mem["run_metrics"],
    }


def build_summary(routed_df: pd.DataFrame, static_route_df: pd.DataFrame) -> Dict[str, Any]:
    route_counts = routed_df["route_role"].value_counts().to_dict()
    branch_counts = routed_df["route_branch"].value_counts().to_dict()

    transition_near = routed_df[routed_df["transition_phase"] == "near_transition"]
    transition_coverage = float((transition_near["route_branch"] == "transition_branch").mean()) if not transition_near.empty else None

    static_mask = routed_df["route_branch"].isin(["static_memory_branch", "static_threshold_branch"])
    static_runs = int(routed_df.loc[static_mask, "file"].nunique())
    static_windows = int(static_mask.sum())
    threshold_favored = routed_df["route_role"] == "static_threshold_favored"
    threshold_favored_ratio = float(threshold_favored.mean()) if len(routed_df) else 0.0
    downstream = evaluate_downstream(static_route_df)
    threshold_branch = downstream["threshold_branch"]

    acceptance = {
        "transition_routing_pass": bool(transition_coverage == 1.0),
        "threshold_branch_gain_pass": bool(threshold_branch.get("available") and threshold_branch.get("gain_vs_all_static", 0.0) > 0.0),
        "threshold_branch_abstention_required": bool(threshold_branch.get("abstained_runs", 0) > 0),
    }

    return {
        "route_role_counts": route_counts,
        "route_branch_counts": branch_counts,
        "transition_near_branch_coverage": transition_coverage,
        "static_routed_runs": static_runs,
        "static_routed_windows": static_windows,
        "threshold_favored_ratio": threshold_favored_ratio,
        "downstream_eval": downstream,
        "acceptance": acceptance,
    }


def write_markdown(path: str, summary: Dict[str, Any]) -> None:
    downstream = summary["downstream_eval"]
    threshold_branch = downstream["threshold_branch"]
    similarity_all = downstream["similarity_all_static"]
    similarity_mem = downstream["similarity_memory_only"]
    acceptance = summary["acceptance"]
    lines = [
        "# Gate / Info Selector v2 报告",
        "",
        "- 核心思路：不再用单一全局 info_score 裁决所有窗口，而是做分支感知路由。",
        "",
        "## 路由结果",
        "",
        f"- route_role_counts = `{summary['route_role_counts']}`",
        f"- route_branch_counts = `{summary['route_branch_counts']}`",
        f"- transition_near_branch_coverage = `{summary['transition_near_branch_coverage']}`",
        f"- static_routed_runs = `{summary['static_routed_runs']}`",
        f"- static_routed_windows = `{summary['static_routed_windows']}`",
        f"- threshold_favored_ratio = `{summary['threshold_favored_ratio']}`",
        "",
        "## 下游影响",
        "",
        f"- baseline_all_static: feature=`{downstream['baseline_all_static']['best_feature']}` | run_balanced_accuracy=`{downstream['baseline_all_static']['run_balanced_accuracy']}`",
        f"- threshold_branch: available=`{threshold_branch.get('available')}` | covered_runs=`{threshold_branch.get('covered_runs')}` | "
        f"abstained_runs=`{threshold_branch.get('abstained_runs')}` | best_feature=`{threshold_branch.get('best_feature')}` | "
        f"run_balanced_accuracy=`{threshold_branch.get('run_balanced_accuracy')}` | gain_vs_all_static=`{threshold_branch.get('gain_vs_all_static')}`",
        f"- similarity_all_static: run_auc=`{similarity_all.get('run_auc')}` | run_balanced_accuracy=`{similarity_all.get('run_balanced_accuracy')}`",
        f"- similarity_memory_only: run_auc=`{similarity_mem.get('run_auc')}` | run_balanced_accuracy=`{similarity_mem.get('run_balanced_accuracy')}`",
        "",
        "## 验收判断",
        "",
        f"- transition_routing_pass = `{acceptance['transition_routing_pass']}`",
        f"- threshold_branch_gain_pass = `{acceptance['threshold_branch_gain_pass']}`",
        f"- threshold_branch_abstention_required = `{acceptance['threshold_branch_abstention_required']}`",
        "",
        "## 当前结论",
        "",
        "- 转移窗口应单独路由到 transition 分支，不再和静态高湿窗口混在一起。",
        "- 静态高湿窗口不再强行统一裁切；记忆分支保留全量 candidate windows，阈值分支只重点关注 delta_half_dAH 为正的窗口。",
        "- 这次优化对相似性分支没有明显增益，但对阈值分支有纯化价值；阈值分支应允许对无 favored window 的运行显式放弃判定。",
        "- 第一阶段的优化方向不是继续缩窗口，而是把窗口分配给正确的后续分支，并允许低把握度分支 abstain。",
        "",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)
    window_df, file_df = build_views(args)
    routed_df, static_route_df = assign_routes(window_df, file_df)
    summary = build_summary(routed_df, static_route_df)

    outputs = {
        "window_csv": os.path.join(args.output_dir, "gate_info_selector_v2_windows.csv"),
        "static_route_csv": os.path.join(args.output_dir, "gate_info_selector_v2_static_routes.csv"),
        "report_md": os.path.join(args.output_dir, "gate_info_selector_v2_report.md"),
        "report_json": os.path.join(args.output_dir, "gate_info_selector_v2_report.json"),
    }
    routed_df.to_csv(outputs["window_csv"], index=False, encoding="utf-8-sig")
    static_route_df.to_csv(outputs["static_route_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["report_md"], summary)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2)
    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
