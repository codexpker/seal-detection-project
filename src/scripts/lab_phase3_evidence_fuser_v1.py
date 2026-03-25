#!/usr/bin/env python3
import argparse
import json
import os
import sys
from typing import Any, Dict, List

import numpy as np
import pandas as pd
from sklearn.metrics import balanced_accuracy_score

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.scripts.lab_gate_info_selector_v2 import assign_routes, build_views
from src.scripts.lab_phase1_acceptance import Phase1Config
from src.scripts.lab_phase2_similarity_branch import run_similarity_fold
from src.scripts.lab_phase2_xgboost_branch import evaluate_baseline_threshold_branch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lab phase-3 segment-level evidence fuser v1")
    parser.add_argument("--input-dir", default=Phase1Config.input_dir)
    parser.add_argument("--input-zip", default=Phase1Config.input_zip)
    parser.add_argument("--metadata-xlsx", default=Phase1Config.metadata_xlsx)
    parser.add_argument("--output-dir", default="reports/lab_phase3_evidence_fuser_v1")
    parser.add_argument("--window-hours", type=int, default=12)
    parser.add_argument("--step-hours", type=int, default=1)
    parser.add_argument("--transition-near-hours", type=int, default=6)
    parser.add_argument("--similarity-k", type=int, default=5)
    return parser.parse_args()


def build_inputs(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    window_df, file_df = build_views(args)
    routed_df, static_route_df = assign_routes(window_df, file_df)
    return routed_df, static_route_df, file_df


def build_segments(routed_df: pd.DataFrame) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    if routed_df.empty:
        return pd.DataFrame(rows)

    sort_cols = ["file", "sheet", "start_time", "end_time", "window_id"]
    for (file_name, sheet_name), group in routed_df.sort_values(sort_cols).groupby(["file", "sheet"], dropna=False):
        current_rows: List[Dict[str, Any]] = []
        current_role = None
        segment_id = 0

        def flush_segment(seg_rows: List[Dict[str, Any]], seg_id: int) -> None:
            if not seg_rows:
                return
            seg_df = pd.DataFrame(seg_rows)
            rows.append(
                {
                    "file": file_name,
                    "sheet": sheet_name,
                    "segment_id": f"S{seg_id:03d}",
                    "route_role": seg_df["route_role"].iloc[0],
                    "route_branch": seg_df["route_branch"].iloc[0],
                    "start_time": seg_df["start_time"].min(),
                    "end_time": seg_df["end_time"].max(),
                    "n_windows": int(len(seg_df)),
                    "mean_info_score_v2": float(seg_df["info_score_v2"].fillna(0.0).mean()),
                    "max_info_score_v2": float(seg_df["info_score_v2"].fillna(0.0).max()),
                    "mean_transition_score": float(seg_df.get("transition_score", pd.Series(dtype=float)).fillna(0.0).mean()),
                    "mean_delta_half_dAH": float(seg_df.get("delta_half_dAH", pd.Series(dtype=float)).fillna(0.0).mean()),
                    "mean_slope_AH_in": float(seg_df.get("slope_AH_in", pd.Series(dtype=float)).fillna(0.0).mean()),
                }
            )

        for row in group.to_dict(orient="records"):
            role = row["route_role"]
            if current_role is None:
                segment_id += 1
                current_role = role
                current_rows = [row]
                continue
            if role == current_role:
                current_rows.append(row)
                continue
            flush_segment(current_rows, segment_id)
            segment_id += 1
            current_role = role
            current_rows = [row]
        flush_segment(current_rows, segment_id)

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["file", "sheet", "start_time", "segment_id"]).reset_index(drop=True)


def build_transition_evidence(file_df: pd.DataFrame) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    trans = file_df[file_df["expected_family"] == "transition_run"].copy()
    for _, row in trans.iterrows():
        median_rank = float(row.get("near_transition_median_rank_pct", np.nan))
        near_score = float(row.get("near_transition_mean_score", np.nan))
        non_near_score = float(row.get("non_near_transition_mean_score", np.nan))
        score_lift = (
            float(near_score - non_near_score)
            if not pd.isna(near_score) and not pd.isna(non_near_score)
            else np.nan
        )
        passed = bool(
            not pd.isna(median_rank)
            and median_rank >= 0.80
            and not pd.isna(score_lift)
            and score_lift > 0.20
        )
        rows.append(
            {
                "file": row["file"],
                "near_transition_windows": int(row.get("near_transition_windows", 0)),
                "near_transition_median_rank_pct": median_rank,
                "near_transition_mean_score": near_score,
                "non_near_transition_mean_score": non_near_score,
                "transition_score_lift": score_lift,
                "transition_pass": passed,
            }
        )
    return pd.DataFrame(rows)


def build_threshold_evidence(static_route_df: pd.DataFrame) -> pd.DataFrame:
    static_files = sorted(static_route_df["file"].dropna().unique().tolist())
    threshold_df = static_route_df[static_route_df["route_branch"] == "static_threshold_branch"].copy()
    covered_predictions = pd.DataFrame()
    if not threshold_df.empty and threshold_df["file"].nunique() >= 4:
        result = evaluate_baseline_threshold_branch(threshold_df)
        covered_predictions = result["predictions"].copy()
        covered_predictions["threshold_feature"] = result["best_feature"]

    rows: List[Dict[str, Any]] = []
    pred_map = {
        row["file"]: row
        for _, row in covered_predictions.iterrows()
    }
    for file_name in static_files:
        row = pred_map.get(file_name)
        if row is None:
            rows.append(
                {
                    "file": file_name,
                    "threshold_status": "abstain",
                    "threshold_pred_label": np.nan,
                    "threshold_score": np.nan,
                    "threshold_cutoff": np.nan,
                    "threshold_feature": "",
                }
            )
            continue
        rows.append(
            {
                "file": file_name,
                "threshold_status": "covered",
                "threshold_pred_label": int(row["pred_label"]),
                "threshold_score": float(row["score"]),
                "threshold_cutoff": float(row["threshold"]),
                "threshold_feature": row["threshold_feature"],
            }
        )
    return pd.DataFrame(rows)


def build_similarity_evidence(static_route_df: pd.DataFrame, k: int) -> pd.DataFrame:
    _, run_pred_df = run_similarity_fold(static_route_df, k=k)
    if run_pred_df.empty:
        return pd.DataFrame(columns=["file"])
    out = run_pred_df.copy()
    out = out.rename(
        columns={
            "pred_label": "similarity_pred_label",
            "mean_score": "similarity_mean_score",
            "threshold": "similarity_cutoff",
        }
    )
    return out[
        [
            "file",
            "similarity_pred_label",
            "similarity_mean_score",
            "similarity_cutoff",
            "direction",
            "directed_score",
            "n_windows",
        ]
    ].copy()


def pick_primary_segment(file_name: str, segments_df: pd.DataFrame, preferred_branches: List[str]) -> str:
    subset = segments_df[(segments_df["file"] == file_name) & (segments_df["route_branch"].isin(preferred_branches))].copy()
    if subset.empty:
        return ""
    subset = subset.sort_values(
        ["max_info_score_v2", "mean_transition_score", "mean_delta_half_dAH", "n_windows"],
        ascending=[False, False, False, False],
    )
    return str(subset.iloc[0]["segment_id"])


def dominant_route_role(file_name: str, routed_df: pd.DataFrame) -> str:
    subset = routed_df[routed_df["file"] == file_name]
    if subset.empty:
        return ""
    counts = subset["route_role"].value_counts()
    return str(counts.idxmax())


def fuse_run_decisions(
    file_df: pd.DataFrame,
    routed_df: pd.DataFrame,
    segments_df: pd.DataFrame,
    transition_df: pd.DataFrame,
    threshold_df: pd.DataFrame,
    similarity_df: pd.DataFrame,
) -> pd.DataFrame:
    transition_map = {row["file"]: row for _, row in transition_df.iterrows()}
    threshold_map = {row["file"]: row for _, row in threshold_df.iterrows()}
    similarity_map = {row["file"]: row for _, row in similarity_df.iterrows()}

    rows: List[Dict[str, Any]] = []
    static_files = set(threshold_df["file"].dropna().tolist()) | set(similarity_df["file"].dropna().tolist())

    for _, run in file_df.sort_values(["expected_family", "file", "sheet"]).iterrows():
        file_name = run["file"]
        dominant_role = dominant_route_role(file_name, routed_df)
        transition_row = transition_map.get(file_name)
        threshold_row = threshold_map.get(file_name)
        similarity_row = similarity_map.get(file_name)

        final_status = "gated_out"
        risk_level = "none"
        primary_evidence = "gate_only"
        needs_review = False
        predicted_label = np.nan
        primary_segment_id = ""
        notes: List[str] = []

        if transition_row is not None:
            primary_segment_id = pick_primary_segment(file_name, segments_df, ["transition_branch"])
            if bool(transition_row["transition_pass"]):
                final_status = "transition_alert"
                risk_level = "high"
                primary_evidence = "transition_branch"
                needs_review = True
                predicted_label = 1
                notes.append("transition evidence passed")
            else:
                final_status = "transition_watch"
                risk_level = "watch"
                primary_evidence = "transition_branch"
                needs_review = True
                notes.append("transition run but evidence weaker than acceptance threshold")
        elif file_name in static_files:
            primary_segment_id = pick_primary_segment(
                file_name,
                segments_df,
                ["static_threshold_branch", "static_memory_branch"],
            )
            thr_status = str(threshold_row["threshold_status"]) if threshold_row is not None else "abstain"
            thr_pred = (
                int(threshold_row["threshold_pred_label"])
                if threshold_row is not None and thr_status == "covered" and not pd.isna(threshold_row["threshold_pred_label"])
                else None
            )
            sim_pred = (
                int(similarity_row["similarity_pred_label"])
                if similarity_row is not None and not pd.isna(similarity_row["similarity_pred_label"])
                else None
            )

            if thr_pred == 1 and sim_pred == 1:
                final_status = "static_consensus_alert"
                risk_level = "high"
                primary_evidence = "threshold+similarity"
                needs_review = True
                predicted_label = 1
            elif thr_pred == 1 and sim_pred == 0:
                final_status = "static_threshold_only_alert"
                risk_level = "medium"
                primary_evidence = "threshold_branch"
                needs_review = True
                predicted_label = 1
            elif thr_pred is None and sim_pred == 1:
                final_status = "static_memory_only_alert"
                risk_level = "medium"
                primary_evidence = "similarity_branch"
                needs_review = True
                predicted_label = 1
            elif thr_pred == 0 and sim_pred == 0:
                final_status = "static_low_risk"
                risk_level = "low"
                primary_evidence = "threshold+similarity"
                needs_review = False
                predicted_label = 0
            elif thr_pred == 0 and sim_pred == 1:
                final_status = "static_disagreement_watch"
                risk_level = "watch"
                primary_evidence = "similarity_branch"
                needs_review = True
                predicted_label = 1
            elif thr_pred is None and sim_pred == 0:
                final_status = "static_abstain_low_signal"
                risk_level = "abstain"
                primary_evidence = "similarity_branch"
                needs_review = False
                predicted_label = np.nan
            else:
                final_status = "static_unresolved"
                risk_level = "watch"
                primary_evidence = "static_branch"
                needs_review = True

            if thr_status == "abstain":
                notes.append("threshold branch abstained")
            if thr_pred is not None:
                notes.append(f"threshold_pred={thr_pred}")
            if sim_pred is not None:
                notes.append(f"similarity_pred={sim_pred}")
        else:
            if dominant_role == "reject_heat_related":
                final_status = "gated_heat_related"
                risk_level = "abstain"
                notes.append("heat-related windows dominate")
            elif dominant_role == "reject_low_info":
                final_status = "gated_low_info"
                risk_level = "abstain"
                notes.append("low-information windows dominate")
            else:
                final_status = "gated_background"
                risk_level = "abstain"
                notes.append("no routed evidence branch")

        rows.append(
            {
                "file": file_name,
                "sheet": run["sheet"],
                "expected_family": run["expected_family"],
                "seal_label": run["seal_label"],
                "dominant_route_role": dominant_role,
                "primary_segment_id": primary_segment_id,
                "primary_evidence": primary_evidence,
                "final_status": final_status,
                "risk_level": risk_level,
                "needs_review": needs_review,
                "predicted_label": predicted_label,
                "true_label": 1 if run["seal_label"] == "unseal" else 0 if run["seal_label"] == "seal" else np.nan,
                "notes": " | ".join(notes),
            }
        )
    return pd.DataFrame(rows)


def build_summary(decision_df: pd.DataFrame, transition_df: pd.DataFrame, threshold_df: pd.DataFrame) -> Dict[str, Any]:
    review_count = int(decision_df["needs_review"].fillna(False).sum())
    final_status_counts = decision_df["final_status"].value_counts().to_dict()
    risk_counts = decision_df["risk_level"].value_counts().to_dict()
    transition_alerts = decision_df[decision_df["final_status"] == "transition_alert"]
    transition_total = int(len(transition_df))
    transition_capture = float(len(transition_alerts) / transition_total) if transition_total else np.nan

    static_eval_df = decision_df[
        decision_df["expected_family"] != "transition_run"
    ].copy()
    static_eval_df = static_eval_df[static_eval_df["predicted_label"].notna() & static_eval_df["true_label"].notna()]
    static_bal_acc = (
        float(balanced_accuracy_score(static_eval_df["true_label"].astype(int), static_eval_df["predicted_label"].astype(int)))
        if not static_eval_df.empty and static_eval_df["true_label"].nunique() > 1
        else np.nan
    )
    threshold_abstains = int((threshold_df["threshold_status"] == "abstain").sum()) if not threshold_df.empty else 0

    acceptance = {
        "transition_evidence_captured": bool(transition_total > 0 and transition_capture == 1.0),
        "threshold_abstain_enabled": bool(threshold_abstains > 0),
        "all_runs_resolved_to_status": bool(decision_df["final_status"].notna().all()),
        "static_review_quality_ready": bool(not pd.isna(static_bal_acc) and static_bal_acc >= 0.65),
    }
    structural_ready = bool(
        acceptance["transition_evidence_captured"]
        and acceptance["threshold_abstain_enabled"]
        and acceptance["all_runs_resolved_to_status"]
    )
    if structural_ready and acceptance["static_review_quality_ready"]:
        verdict = "PASS"
    elif structural_ready:
        verdict = "PARTIAL_PASS"
    else:
        verdict = "FAIL"

    return {
        "verdict": verdict,
        "review_queue_runs": review_count,
        "final_status_counts": final_status_counts,
        "risk_level_counts": risk_counts,
        "transition_files": transition_total,
        "transition_capture_rate": transition_capture,
        "static_eval_run_count": int(len(static_eval_df)),
        "static_eval_balanced_accuracy": static_bal_acc,
        "threshold_abstain_runs": threshold_abstains,
        "acceptance": acceptance,
    }


def write_markdown(path: str, summary: Dict[str, Any], decision_df: pd.DataFrame) -> None:
    lines = [
        "# 实验室第三阶段 状态段级证据融合 v1 报告",
        "",
        f"- 结论：`{summary['verdict']}`",
        f"- review_queue_runs：`{summary['review_queue_runs']}`",
        f"- transition_capture_rate：`{summary['transition_capture_rate']}`",
        f"- static_eval_balanced_accuracy：`{summary['static_eval_balanced_accuracy']}`",
        f"- threshold_abstain_runs：`{summary['threshold_abstain_runs']}`",
        "",
        "## 融合原则",
        "",
        "- 转移段优先级最高，只要转移证据通过，就直接进入 review 队列。",
        "- 静态高信息运行采用 `threshold branch + similarity branch` 的弱证据融合，并允许阈值分支 abstain。",
        "- 低信息和热相关运行不强判，只输出 gated 结果。",
        "",
        "## 运行级结果分布",
        "",
        f"- final_status_counts = `{summary['final_status_counts']}`",
        f"- risk_level_counts = `{summary['risk_level_counts']}`",
        "",
        "## 验收判断",
        "",
        f"- transition_evidence_captured = `{summary['acceptance']['transition_evidence_captured']}`",
        f"- threshold_abstain_enabled = `{summary['acceptance']['threshold_abstain_enabled']}`",
        f"- all_runs_resolved_to_status = `{summary['acceptance']['all_runs_resolved_to_status']}`",
        f"- static_review_quality_ready = `{summary['acceptance']['static_review_quality_ready']}`",
        "",
        "## 需要复核的运行",
        "",
    ]

    review_df = decision_df[decision_df["needs_review"]].copy()
    for _, row in review_df.iterrows():
        lines.append(
            f"- {row['file']} | status={row['final_status']} | evidence={row['primary_evidence']} | "
            f"segment={row['primary_segment_id']} | notes={row['notes']}"
        )

    lines.extend(
        [
            "",
        "## 当前判断",
        "",
        "- 这一步已经把“模型输出”改造成了“证据驱动决策输出”，更适合演示和后续现场迁移。",
        "- 当前最强证据仍然是转移段；静态分支主要价值是提供辅助风险和显式 abstain。",
        "- 当前结构已经成立，但静态 review 队列质量还没有到稳定通过线；接下来应优先优化 review 队列质量和证据展示，而不是继续增加孤立模型支线。",
        "",
    ]
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    routed_df, static_route_df, file_df = build_inputs(args)
    segments_df = build_segments(routed_df)
    transition_df = build_transition_evidence(file_df)
    threshold_df = build_threshold_evidence(static_route_df)
    similarity_df = build_similarity_evidence(static_route_df, k=args.similarity_k)
    decision_df = fuse_run_decisions(
        file_df=file_df,
        routed_df=routed_df,
        segments_df=segments_df,
        transition_df=transition_df,
        threshold_df=threshold_df,
        similarity_df=similarity_df,
    )
    summary = build_summary(decision_df, transition_df, threshold_df)

    outputs = {
        "segment_csv": os.path.join(args.output_dir, "phase3_evidence_segments.csv"),
        "transition_csv": os.path.join(args.output_dir, "phase3_transition_evidence.csv"),
        "threshold_csv": os.path.join(args.output_dir, "phase3_threshold_evidence.csv"),
        "similarity_csv": os.path.join(args.output_dir, "phase3_similarity_evidence.csv"),
        "decision_csv": os.path.join(args.output_dir, "phase3_run_decisions.csv"),
        "report_md": os.path.join(args.output_dir, "phase3_evidence_fuser_report.md"),
        "report_json": os.path.join(args.output_dir, "phase3_evidence_fuser_report.json"),
    }

    segments_df.to_csv(outputs["segment_csv"], index=False, encoding="utf-8-sig")
    transition_df.to_csv(outputs["transition_csv"], index=False, encoding="utf-8-sig")
    threshold_df.to_csv(outputs["threshold_csv"], index=False, encoding="utf-8-sig")
    similarity_df.to_csv(outputs["similarity_csv"], index=False, encoding="utf-8-sig")
    decision_df.to_csv(outputs["decision_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["report_md"], summary, decision_df)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
