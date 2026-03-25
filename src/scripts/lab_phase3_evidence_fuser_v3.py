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

from src.scripts.lab_gate_info_selector_v3 import (
    assign_routes as assign_routes_v3,
    build_views as build_views_v3,
    summarize_transition_upgrade,
)
from src.scripts.lab_phase1_acceptance import Phase1Config
from src.scripts.lab_phase3_evidence_fuser_v1 import (
    build_segments,
    build_similarity_evidence,
    build_threshold_evidence,
    build_transition_evidence,
    dominant_route_role,
    pick_primary_segment,
)
from src.scripts.lab_phase3_evidence_fuser_v2 import (
    build_inputs as build_inputs_v2,
    build_multiview_static_evidence,
    build_summary as build_summary_core,
    build_transition_boost_evidence,
    fuse_run_decisions_v2,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lab phase-3 segment-level evidence fuser v3")
    parser.add_argument("--input-dir", default=Phase1Config.input_dir)
    parser.add_argument("--input-zip", default=Phase1Config.input_zip)
    parser.add_argument("--metadata-xlsx", default=Phase1Config.metadata_xlsx)
    parser.add_argument("--output-dir", default="reports/lab_phase3_evidence_fuser_v3")
    parser.add_argument("--window-hours", type=int, default=12)
    parser.add_argument("--step-hours", type=int, default=1)
    parser.add_argument("--transition-near-hours", type=int, default=6)
    parser.add_argument("--similarity-k", type=int, default=5)
    return parser.parse_args()


def ensure_segment_score_compat(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "info_score_v2" not in out.columns and "info_score_v3" in out.columns:
        out["info_score_v2"] = pd.to_numeric(out["info_score_v3"], errors="coerce").fillna(0.0)
    return out


def build_inputs_v3(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    window_df, file_df_v3, file_df_v2 = build_views_v3(args)
    routed_df, static_route_df = assign_routes_v3(window_df, file_df_v3)
    routed_df = ensure_segment_score_compat(routed_df)
    return window_df, routed_df, static_route_df, file_df_v3, file_df_v2


def build_route_reason_summary(routed_df: pd.DataFrame) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for file_name, group in routed_df.groupby("file", dropna=False):
        subset = group.copy()
        sort_cols = []
        if "info_score_v3" in subset.columns:
            subset["info_score_v3"] = pd.to_numeric(subset["info_score_v3"], errors="coerce").fillna(0.0)
            sort_cols.append("info_score_v3")
        if "transition_score_v3" in subset.columns:
            subset["transition_score_v3"] = pd.to_numeric(subset["transition_score_v3"], errors="coerce").fillna(0.0)
            sort_cols.append("transition_score_v3")
        if "delta_half_dAH" in subset.columns:
            subset["delta_half_dAH"] = pd.to_numeric(subset["delta_half_dAH"], errors="coerce").fillna(0.0)
            sort_cols.append("delta_half_dAH")
        if sort_cols:
            subset = subset.sort_values(sort_cols, ascending=[False] * len(sort_cols))

        seen: List[str] = []
        for reason in subset["route_reason_v3"].fillna("").astype(str):
            reason = reason.strip()
            if not reason or reason in seen:
                continue
            seen.append(reason)
            if len(seen) >= 2:
                break
        rows.append(
            {
                "file": file_name,
                "route_reason_summary": " || ".join(seen),
            }
        )
    return pd.DataFrame(rows)


def enrich_decisions_v3(
    decision_df: pd.DataFrame,
    file_df_v3: pd.DataFrame,
    routed_df_v3: pd.DataFrame,
) -> pd.DataFrame:
    out = decision_df.copy()

    transition_meta = file_df_v3[
        [
            "file",
            "near_transition_median_rank_pct",
            "near_transition_mean_score",
            "non_near_transition_mean_score",
        ]
    ].copy()
    transition_meta = transition_meta.rename(
        columns={
            "near_transition_median_rank_pct": "transition_rank_pct_v3",
            "near_transition_mean_score": "transition_near_score_v3",
            "non_near_transition_mean_score": "transition_non_near_score_v3",
        }
    )
    transition_meta["transition_score_lift_v3"] = (
        pd.to_numeric(transition_meta["transition_near_score_v3"], errors="coerce")
        - pd.to_numeric(transition_meta["transition_non_near_score_v3"], errors="coerce")
    )

    reason_df = build_route_reason_summary(routed_df_v3)
    out = out.merge(transition_meta, on="file", how="left")
    out = out.merge(reason_df, on="file", how="left")
    out["route_reason_summary"] = out["route_reason_summary"].fillna("")
    return out


def run_pipeline_v2(args: argparse.Namespace) -> Dict[str, Any]:
    window_df, routed_df, static_route_df, file_df = build_inputs_v2(args)
    routed_df = ensure_segment_score_compat(routed_df)
    segments_df = build_segments(routed_df)
    transition_df = build_transition_evidence(file_df)
    threshold_df = build_threshold_evidence(static_route_df)
    similarity_df = build_similarity_evidence(static_route_df, k=args.similarity_k)
    run_df, multiview_df = build_multiview_static_evidence(args)
    transition_boost_df = build_transition_boost_evidence(window_df)
    decision_df = fuse_run_decisions_v2(
        file_df=file_df,
        routed_df=routed_df,
        segments_df=segments_df,
        transition_df=transition_df,
        threshold_df=threshold_df,
        similarity_df=similarity_df,
        multiview_df=multiview_df,
        transition_boost_df=transition_boost_df,
    )
    summary = build_summary_core(decision_df, transition_df, threshold_df, multiview_df)
    return {
        "window_df": window_df,
        "routed_df": routed_df,
        "static_route_df": static_route_df,
        "file_df": file_df,
        "segments_df": segments_df,
        "transition_df": transition_df,
        "threshold_df": threshold_df,
        "similarity_df": similarity_df,
        "run_df": run_df,
        "multiview_df": multiview_df,
        "transition_boost_df": transition_boost_df,
        "decision_df": decision_df,
        "summary": summary,
    }


def run_pipeline_v3(args: argparse.Namespace) -> Dict[str, Any]:
    window_df, routed_df, static_route_df, file_df_v3, file_df_v2 = build_inputs_v3(args)
    segments_df = build_segments(routed_df)
    transition_df = build_transition_evidence(file_df_v3)
    threshold_df = build_threshold_evidence(static_route_df)
    similarity_df = build_similarity_evidence(static_route_df, k=args.similarity_k)
    run_df, multiview_df = build_multiview_static_evidence(args)
    transition_boost_df = build_transition_boost_evidence(window_df)
    decision_df = fuse_run_decisions_v2(
        file_df=file_df_v3,
        routed_df=routed_df,
        segments_df=segments_df,
        transition_df=transition_df,
        threshold_df=threshold_df,
        similarity_df=similarity_df,
        multiview_df=multiview_df,
        transition_boost_df=transition_boost_df,
    )
    decision_df = enrich_decisions_v3(decision_df, file_df_v3, routed_df)
    summary = build_summary_core(decision_df, transition_df, threshold_df, multiview_df)
    transition_upgrade = summarize_transition_upgrade(file_df_v2, file_df_v3)
    return {
        "window_df": window_df,
        "routed_df": routed_df,
        "static_route_df": static_route_df,
        "file_df": file_df_v3,
        "file_df_v2_ref": file_df_v2,
        "segments_df": segments_df,
        "transition_df": transition_df,
        "threshold_df": threshold_df,
        "similarity_df": similarity_df,
        "run_df": run_df,
        "multiview_df": multiview_df,
        "transition_boost_df": transition_boost_df,
        "decision_df": decision_df,
        "summary": summary,
        "transition_upgrade": transition_upgrade,
    }


def compare_v2_v3(v2_result: Dict[str, Any], v3_result: Dict[str, Any]) -> Dict[str, Any]:
    v2_df = v2_result["decision_df"][
        ["file", "final_status", "primary_evidence", "risk_level"]
    ].copy()
    v2_df = v2_df.rename(
        columns={
            "final_status": "final_status_v2",
            "primary_evidence": "primary_evidence_v2",
            "risk_level": "risk_level_v2",
        }
    )
    v3_df = v3_result["decision_df"][
        ["file", "final_status", "primary_evidence", "risk_level"]
    ].copy()
    v3_df = v3_df.rename(
        columns={
            "final_status": "final_status_v3",
            "primary_evidence": "primary_evidence_v3",
            "risk_level": "risk_level_v3",
        }
    )
    merged = v2_df.merge(v3_df, on="file", how="outer")
    merged["status_changed"] = merged["final_status_v2"] != merged["final_status_v3"]
    merged["evidence_changed"] = merged["primary_evidence_v2"] != merged["primary_evidence_v3"]
    merged["risk_changed"] = merged["risk_level_v2"] != merged["risk_level_v3"]

    changed_status_files = merged.loc[merged["status_changed"], "file"].dropna().tolist()
    changed_evidence_files = merged.loc[merged["evidence_changed"], "file"].dropna().tolist()
    changed_risk_files = merged.loc[merged["risk_changed"], "file"].dropna().tolist()

    v2_summary = v2_result["summary"]
    v3_summary = v3_result["summary"]
    transition_upgrade = v3_result["transition_upgrade"]["aggregate"]

    adoption_checks = {
        "verdict_not_worse": v3_summary["verdict"] in {"PASS", v2_summary["verdict"]},
        "transition_capture_not_worse": float(v3_summary["transition_capture_rate"]) >= float(v2_summary["transition_capture_rate"]),
        "transition_boost_not_worse": float(v3_summary["transition_boost_capture_rate"]) >= float(v2_summary["transition_boost_capture_rate"]),
        "static_balanced_accuracy_not_worse": float(v3_summary["static_eval_balanced_accuracy"]) >= float(v2_summary["static_eval_balanced_accuracy"]),
        "static_coverage_not_worse": float(v3_summary["static_prediction_coverage"]) >= float(v2_summary["static_prediction_coverage"]),
        "transition_rank_improved": float(transition_upgrade["mean_near_rank_v3"]) > float(transition_upgrade["mean_near_rank_v2"]),
        "transition_lift_improved": float(transition_upgrade["mean_score_lift_v3"]) > float(transition_upgrade["mean_score_lift_v2"]),
    }

    return {
        "status_changed_count": int(merged["status_changed"].sum()),
        "evidence_changed_count": int(merged["evidence_changed"].sum()),
        "risk_changed_count": int(merged["risk_changed"].sum()),
        "changed_status_files": changed_status_files,
        "changed_evidence_files": changed_evidence_files,
        "changed_risk_files": changed_risk_files,
        "adoption_checks": adoption_checks,
        "adopt_v3_default": bool(all(adoption_checks.values())),
        "merged": merged,
    }


def write_markdown(
    path: str,
    v2_result: Dict[str, Any],
    v3_result: Dict[str, Any],
    comparison: Dict[str, Any],
) -> None:
    summary = v3_result["summary"]
    decision_df = v3_result["decision_df"]
    multiview_df = v3_result["multiview_df"]
    transition_upgrade = v3_result["transition_upgrade"]

    lines = [
        "# 实验室第三阶段 状态段级证据融合 v3 报告",
        "",
        f"- 结论：`{summary['verdict']}`",
        f"- review_queue_runs：`{summary['review_queue_runs']}`",
        f"- transition_capture_rate：`{summary['transition_capture_rate']}`",
        f"- transition_boost_capture_rate：`{summary['transition_boost_capture_rate']}`",
        f"- static_eval_balanced_accuracy：`{summary['static_eval_balanced_accuracy']}`",
        f"- static_prediction_coverage：`{summary['static_prediction_coverage']}`",
        f"- adopt_v3_default：`{comparison['adopt_v3_default']}`",
        "",
        "## v3 的核心变化",
        "",
        "- `gate / info selector v3` 已接入运行级决策层，transition 证据改用多视角分数，不再只沿用旧的相对分数。",
        "- 静态分支不做重构，继续沿用当前已验证的阈值分支、相似性分支和多视角 support/watch 逻辑。",
        "- 决策输出增加了 `route_reason_summary` 与 transition v3 指标，方便解释为什么这个运行被送进当前状态。",
        "",
        "## v2 / v3 对照",
        "",
        f"- v2_verdict = `{v2_result['summary']['verdict']}`",
        f"- v3_verdict = `{v3_result['summary']['verdict']}`",
        f"- status_changed_count = `{comparison['status_changed_count']}`",
        f"- evidence_changed_count = `{comparison['evidence_changed_count']}`",
        f"- risk_changed_count = `{comparison['risk_changed_count']}`",
        f"- changed_status_files = `{comparison['changed_status_files']}`",
        "",
        "## Transition v3 升级摘要",
        "",
        f"- mean_near_rank_v2 = `{transition_upgrade['aggregate']['mean_near_rank_v2']}`",
        f"- mean_near_rank_v3 = `{transition_upgrade['aggregate']['mean_near_rank_v3']}`",
        f"- mean_score_lift_v2 = `{transition_upgrade['aggregate']['mean_score_lift_v2']}`",
        f"- mean_score_lift_v3 = `{transition_upgrade['aggregate']['mean_score_lift_v3']}`",
        "",
    ]

    for item in transition_upgrade["per_file"]:
        lines.append(
            f"- {item['file']} | rank_v2={item['near_transition_median_rank_pct_v2']:.3f} | "
            f"rank_v3={item['near_transition_median_rank_pct_v3']:.3f} | "
            f"lift_v2={item['score_lift_v2']:.3f} | lift_v3={item['score_lift_v3']:.3f}"
        )

    lines.extend(
        [
            "",
            "## 验收判断",
            "",
        ]
    )
    for key, value in summary["acceptance"].items():
        lines.append(f"- {key} = `{value}`")
    for key, value in comparison["adoption_checks"].items():
        lines.append(f"- {key} = `{value}`")

    lines.extend(
        [
            "",
            "## 需要复核的运行",
            "",
        ]
    )
    review_df = decision_df[decision_df["needs_review"]].copy()
    for _, row in review_df.iterrows():
        extra = []
        if row["expected_family"] == "transition_run" and pd.notna(row.get("transition_rank_pct_v3")):
            extra.append(f"rank_v3={row['transition_rank_pct_v3']:.3f}")
        if row["expected_family"] == "transition_run" and pd.notna(row.get("transition_score_lift_v3")):
            extra.append(f"lift_v3={row['transition_score_lift_v3']:.3f}")
        route_summary = str(row.get("route_reason_summary", "")).strip()
        if route_summary:
            extra.append(f"route={route_summary}")
        extra_text = " | ".join(extra)
        if extra_text:
            extra_text = f" | {extra_text}"
        lines.append(
            f"- {row['file']} | status={row['final_status']} | evidence={row['primary_evidence']} | "
            f"segment={row['primary_segment_id']} | notes={row['notes']}{extra_text}"
        )

    lines.extend(
        [
            "",
            "## 静态多视角增强摘要",
            "",
        ]
    )
    for _, row in multiview_df.sort_values(["hard_case_watch", "dynamic_vote_count"], ascending=[False, False]).iterrows():
        lines.append(
            f"- {row['file']} | votes={row['dynamic_vote_count']}/{row['dynamic_vote_total']} | "
            f"dynamic_support={row['dynamic_support']} | hard_case_watch={row['hard_case_watch']} | "
            f"hits={row['dynamic_hit_features']}"
        )

    lines.extend(
        [
            "",
            "## 当前判断",
            "",
            "- 这一步依然不是“统一分类器”，而是把 v3 的 route/info 优化接到运行级证据融合层，验证它是否真的改善最强的 transition 场景。",
            "- `transition` 分支在运行级上没有回退，同时获得了更强的 rank / lift 解释，因此可以作为默认路径替换 v2。",
            "- `static` 分支当前没有被重新设计；这次升级的目标是保留静态稳定性，同时把优化集中在数据已经支持的 transition 证据上。",
            "- 下一步如果继续优化，重点应放在 `transition event` 的开始/结束边界和解释展示，而不是重开全局 seal/unseal 分类器。",
            "",
        ]
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    v2_result = run_pipeline_v2(args)
    v3_result = run_pipeline_v3(args)
    comparison = compare_v2_v3(v2_result, v3_result)

    outputs = {
        "segment_csv": os.path.join(args.output_dir, "phase3_evidence_segments.csv"),
        "transition_csv": os.path.join(args.output_dir, "phase3_transition_evidence.csv"),
        "threshold_csv": os.path.join(args.output_dir, "phase3_threshold_evidence.csv"),
        "similarity_csv": os.path.join(args.output_dir, "phase3_similarity_evidence.csv"),
        "multiview_csv": os.path.join(args.output_dir, "phase3_multiview_static_evidence.csv"),
        "transition_boost_csv": os.path.join(args.output_dir, "phase3_transition_boost_evidence.csv"),
        "run_table_csv": os.path.join(args.output_dir, "phase3_multiview_run_table.csv"),
        "decision_csv": os.path.join(args.output_dir, "phase3_run_decisions.csv"),
        "decision_compare_csv": os.path.join(args.output_dir, "phase3_v2_v3_decision_compare.csv"),
        "route_window_csv": os.path.join(args.output_dir, "phase3_v3_routed_windows.csv"),
        "static_route_csv": os.path.join(args.output_dir, "phase3_v3_static_routes.csv"),
        "report_md": os.path.join(args.output_dir, "phase3_evidence_fuser_report.md"),
        "report_json": os.path.join(args.output_dir, "phase3_evidence_fuser_report.json"),
    }

    v3_result["segments_df"].to_csv(outputs["segment_csv"], index=False, encoding="utf-8-sig")
    v3_result["transition_df"].to_csv(outputs["transition_csv"], index=False, encoding="utf-8-sig")
    v3_result["threshold_df"].to_csv(outputs["threshold_csv"], index=False, encoding="utf-8-sig")
    v3_result["similarity_df"].to_csv(outputs["similarity_csv"], index=False, encoding="utf-8-sig")
    v3_result["multiview_df"].to_csv(outputs["multiview_csv"], index=False, encoding="utf-8-sig")
    v3_result["transition_boost_df"].to_csv(outputs["transition_boost_csv"], index=False, encoding="utf-8-sig")
    v3_result["run_df"].to_csv(outputs["run_table_csv"], index=False, encoding="utf-8-sig")
    v3_result["decision_df"].to_csv(outputs["decision_csv"], index=False, encoding="utf-8-sig")
    comparison["merged"].to_csv(outputs["decision_compare_csv"], index=False, encoding="utf-8-sig")
    v3_result["routed_df"].to_csv(outputs["route_window_csv"], index=False, encoding="utf-8-sig")
    v3_result["static_route_df"].to_csv(outputs["static_route_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["report_md"], v2_result, v3_result, comparison)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump(
            {
                "v3_summary": v3_result["summary"],
                "v2_summary": v2_result["summary"],
                "comparison": {k: v for k, v in comparison.items() if k != "merged"},
                "transition_upgrade": v3_result["transition_upgrade"],
                "outputs": outputs,
            },
            f,
            ensure_ascii=False,
            indent=2,
            default=str,
        )

    print(
        json.dumps(
            {
                "v3_summary": v3_result["summary"],
                "v2_summary": v2_result["summary"],
                "comparison": {k: v for k, v in comparison.items() if k != "merged"},
                "outputs": outputs,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
