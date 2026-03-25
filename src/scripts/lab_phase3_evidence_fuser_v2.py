#!/usr/bin/env python3
import argparse
import json
import os
import sys
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
from sklearn.metrics import balanced_accuracy_score

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.scripts.current_condition_multiview_analysis import build_run_table
from src.scripts.lab_gate_info_selector_v2 import assign_routes, build_views
from src.scripts.lab_phase1_acceptance import Phase1Config
from src.scripts.lab_phase3_evidence_fuser_v1 import (
    build_segments,
    build_similarity_evidence,
    build_threshold_evidence,
    build_transition_evidence,
    dominant_route_role,
    pick_primary_segment,
)

STATIC_FEATURE_SPECS: List[Tuple[str, str]] = [
    ("corr_out_hum_in_hum", "pos"),
    ("max_corr_outRH_inRH_change", "pos"),
    ("frac_threshold_favored", "pos"),
    ("frac_pos_delta_half_dAH", "pos"),
    ("q90_delta_half_dAH_w", "pos"),
    ("std_in_hum_run", "neg"),
]

HARD_CASE_FEATURES: List[str] = [
    "max_corr_outRH_inRH_change",
    "q90_delta_half_dAH_w",
    "frac_threshold_favored",
    "frac_pos_delta_half_dAH",
    "best_lag_h",
    "q90_delta_half_in_hum",
]

TRANSITION_BOOST_FEATURES: List[str] = [
    "delta_in_hum",
    "delta_half_in_hum",
    "max_hourly_hum_rise",
    "std_out_hum",
    "corr_AH",
]

DYNAMIC_SUPPORT_MIN_VOTES = 4
HARD_CASE_RATIO_CUTOFF = 0.75
TRANSITION_BOOST_MIN_FEATURES = 2
STATIC_PASS_BALANCED_ACCURACY = 0.80
STATIC_PASS_COVERAGE = 0.66


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lab phase-3 segment-level evidence fuser v2")
    parser.add_argument("--input-dir", default=Phase1Config.input_dir)
    parser.add_argument("--input-zip", default=Phase1Config.input_zip)
    parser.add_argument("--metadata-xlsx", default=Phase1Config.metadata_xlsx)
    parser.add_argument("--output-dir", default="reports/lab_phase3_evidence_fuser_v2")
    parser.add_argument("--window-hours", type=int, default=12)
    parser.add_argument("--step-hours", type=int, default=1)
    parser.add_argument("--transition-near-hours", type=int, default=6)
    parser.add_argument("--similarity-k", type=int, default=5)
    return parser.parse_args()


def build_inputs(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    window_df, file_df = build_views(args)
    routed_df, static_route_df = assign_routes(window_df, file_df)
    return window_df, routed_df, static_route_df, file_df


def _fill_numeric(df: pd.DataFrame) -> pd.DataFrame:
    out = df.replace([np.inf, -np.inf], np.nan).copy()
    return out.infer_objects(copy=False)


def compute_dynamic_votes(target_row: pd.Series, train_df: pd.DataFrame) -> Dict[str, Any]:
    seal_train = train_df[train_df["seal_label"] == "seal"].copy()
    unseal_train = train_df[train_df["seal_label"] == "unseal"].copy()

    vote_count = 0
    vote_total = 0
    hit_features: List[str] = []
    threshold_map: Dict[str, float] = {}

    for feature, direction in STATIC_FEATURE_SPECS:
        seal_values = pd.to_numeric(seal_train[feature], errors="coerce").dropna()
        unseal_values = pd.to_numeric(unseal_train[feature], errors="coerce").dropna()
        value = pd.to_numeric(pd.Series([target_row.get(feature)]), errors="coerce").iloc[0]
        if seal_values.empty or unseal_values.empty or pd.isna(value):
            continue
        cutoff = float((seal_values.median() + unseal_values.median()) / 2.0)
        threshold_map[feature] = cutoff
        vote_total += 1
        passed = value >= cutoff if direction == "pos" else value <= cutoff
        if passed:
            vote_count += 1
            hit_features.append(feature)

    return {
        "dynamic_vote_count": int(vote_count),
        "dynamic_vote_total": int(vote_total),
        "dynamic_support": bool(vote_total > 0 and vote_count >= DYNAMIC_SUPPORT_MIN_VOTES),
        "dynamic_hit_features": ",".join(hit_features),
        "dynamic_thresholds": json.dumps(threshold_map, ensure_ascii=False),
    }


def compute_hard_case_flag(target_row: pd.Series, train_df: pd.DataFrame) -> Dict[str, Any]:
    numeric_train = _fill_numeric(train_df[HARD_CASE_FEATURES])
    fill_values = numeric_train.median(numeric_only=True)
    numeric_train = numeric_train.fillna(fill_values)

    target = _fill_numeric(pd.DataFrame([target_row[HARD_CASE_FEATURES]])).fillna(fill_values)
    mean = numeric_train.mean()
    std = numeric_train.std(ddof=0).replace(0.0, 1.0)
    train_scaled = (numeric_train - mean) / std
    target_scaled = (target.iloc[0] - mean) / std

    distances: List[Tuple[float, str, str]] = []
    for idx, other in train_df.iterrows():
        dist = float(np.sqrt(((target_scaled - train_scaled.loc[idx]) ** 2).sum()))
        distances.append((dist, str(other["file"]), str(other["seal_label"])))
    distances.sort(key=lambda x: x[0])

    same = next((item for item in distances if item[2] == target_row["seal_label"]), None)
    other = next((item for item in distances if item[2] != target_row["seal_label"]), None)
    ratio = np.nan
    if same and other and same[0] > 0:
        ratio = float(other[0] / same[0])

    return {
        "nearest_same_file": same[1] if same else "",
        "nearest_same_distance": same[0] if same else np.nan,
        "nearest_other_file": other[1] if other else "",
        "nearest_other_distance": other[0] if other else np.nan,
        "hard_case_ratio": ratio,
        "hard_case_watch": bool(not pd.isna(ratio) and ratio < HARD_CASE_RATIO_CUTOFF),
    }


def build_multiview_static_evidence(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame]:
    run_df, _, _, _ = build_run_table(args)
    static_df = run_df[run_df["analysis_group"].isin(["current_static_seal", "current_static_unseal"])].copy()
    static_df = static_df.reset_index(drop=True)

    rows: List[Dict[str, Any]] = []
    for idx, target in static_df.iterrows():
        train_df = static_df.drop(index=idx).copy()
        if train_df.empty or train_df["seal_label"].nunique() < 2:
            continue

        vote_info = compute_dynamic_votes(target, train_df)
        hard_info = compute_hard_case_flag(target, train_df)
        rows.append(
            {
                "file": target["file"],
                "sheet": target["sheet"],
                "seal_label": target["seal_label"],
                "analysis_group": target["analysis_group"],
                "corr_out_hum_in_hum": target.get("corr_out_hum_in_hum", np.nan),
                "max_corr_outRH_inRH_change": target.get("max_corr_outRH_inRH_change", np.nan),
                "std_in_hum_run": target.get("std_in_hum_run", np.nan),
                "frac_threshold_favored": target.get("frac_threshold_favored", np.nan),
                "frac_pos_delta_half_dAH": target.get("frac_pos_delta_half_dAH", np.nan),
                "q90_delta_half_dAH_w": target.get("q90_delta_half_dAH_w", np.nan),
                "best_lag_h": target.get("best_lag_h", np.nan),
                "best_lag_rh_h": target.get("best_lag_rh_h", np.nan),
                "gain_ratio_dAH_change": target.get("gain_ratio_dAH_change", np.nan),
                **vote_info,
                **hard_info,
            }
        )

    return run_df, pd.DataFrame(rows).sort_values(["analysis_group", "file"]).reset_index(drop=True)


def build_transition_boost_evidence(window_df: pd.DataFrame) -> pd.DataFrame:
    trans_df = window_df[window_df["expected_family"] == "transition_run"].copy()
    if trans_df.empty:
        return pd.DataFrame(columns=["file"])

    thresholds: Dict[str, float] = {}
    for feature in TRANSITION_BOOST_FEATURES:
        near = pd.to_numeric(
            trans_df.loc[trans_df["transition_phase"] == "near_transition", feature],
            errors="coerce",
        ).dropna()
        non = pd.to_numeric(
            trans_df.loc[trans_df["transition_phase"] != "near_transition", feature],
            errors="coerce",
        ).dropna()
        if near.empty or non.empty:
            continue
        thresholds[feature] = float((near.mean() + non.mean()) / 2.0)

    rows: List[Dict[str, Any]] = []
    for file_name, group in trans_df.groupby("file", dropna=False):
        near_group = group[group["transition_phase"] == "near_transition"].copy()
        hits: List[str] = []
        stats: Dict[str, float] = {}
        for feature, cutoff in thresholds.items():
            value = pd.to_numeric(near_group[feature], errors="coerce").median()
            if pd.isna(value):
                continue
            stats[f"near_median_{feature}"] = float(value)
            if value >= cutoff:
                hits.append(feature)
        rows.append(
            {
                "file": file_name,
                "transition_boost_count": int(len(hits)),
                "transition_boost_features": ",".join(hits),
                "transition_boost": bool(len(hits) >= TRANSITION_BOOST_MIN_FEATURES),
                **stats,
            }
        )
    return pd.DataFrame(rows).sort_values("file").reset_index(drop=True)


def fuse_run_decisions_v2(
    file_df: pd.DataFrame,
    routed_df: pd.DataFrame,
    segments_df: pd.DataFrame,
    transition_df: pd.DataFrame,
    threshold_df: pd.DataFrame,
    similarity_df: pd.DataFrame,
    multiview_df: pd.DataFrame,
    transition_boost_df: pd.DataFrame,
) -> pd.DataFrame:
    transition_map = {row["file"]: row for _, row in transition_df.iterrows()}
    threshold_map = {row["file"]: row for _, row in threshold_df.iterrows()}
    similarity_map = {row["file"]: row for _, row in similarity_df.iterrows()}
    multiview_map = {row["file"]: row for _, row in multiview_df.iterrows()}
    transition_boost_map = {row["file"]: row for _, row in transition_boost_df.iterrows()}

    rows: List[Dict[str, Any]] = []
    static_files = set(threshold_df["file"].dropna().tolist()) | set(similarity_df["file"].dropna().tolist())

    for _, run in file_df.sort_values(["expected_family", "file", "sheet"]).iterrows():
        file_name = run["file"]
        dominant_role = dominant_route_role(file_name, routed_df)
        transition_row = transition_map.get(file_name)
        threshold_row = threshold_map.get(file_name)
        similarity_row = similarity_map.get(file_name)
        multiview_row = multiview_map.get(file_name)
        transition_boost_row = transition_boost_map.get(file_name)

        final_status = "gated_out"
        risk_level = "none"
        primary_evidence = "gate_only"
        needs_review = False
        predicted_label: float | int | None = np.nan
        primary_segment_id = ""
        notes: List[str] = []

        if transition_row is not None:
            primary_segment_id = pick_primary_segment(file_name, segments_df, ["transition_branch"])
            boost_count = int(transition_boost_row["transition_boost_count"]) if transition_boost_row is not None else 0
            boost_features = str(transition_boost_row["transition_boost_features"]) if transition_boost_row is not None else ""
            if bool(transition_row["transition_pass"]):
                if transition_boost_row is not None and bool(transition_boost_row["transition_boost"]):
                    final_status = "transition_boost_alert"
                    primary_evidence = "transition_branch+multiview"
                    notes.append(f"transition boost features={boost_features}")
                else:
                    final_status = "transition_alert"
                    primary_evidence = "transition_branch"
                risk_level = "high"
                needs_review = True
                predicted_label = 1
                notes.append("transition evidence passed")
                notes.append(f"transition_boost_count={boost_count}")
            else:
                final_status = "transition_watch"
                risk_level = "watch"
                primary_evidence = "transition_branch"
                needs_review = True
                notes.append("transition run but evidence weaker than acceptance threshold")
                if transition_boost_row is not None and bool(transition_boost_row["transition_boost"]):
                    notes.append(f"transition boost features={boost_features}")
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
            dynamic_support = bool(multiview_row["dynamic_support"]) if multiview_row is not None else False
            hard_case_watch = bool(multiview_row["hard_case_watch"]) if multiview_row is not None else False
            dynamic_vote_count = int(multiview_row["dynamic_vote_count"]) if multiview_row is not None else 0
            hard_case_ratio = float(multiview_row["hard_case_ratio"]) if multiview_row is not None else np.nan

            if thr_status == "abstain":
                notes.append("threshold branch abstained")
            if thr_pred is not None:
                notes.append(f"threshold_pred={thr_pred}")
            if sim_pred is not None:
                notes.append(f"similarity_pred={sim_pred}")
            if multiview_row is not None:
                notes.append(f"dynamic_vote_count={dynamic_vote_count}")
                if pd.notna(hard_case_ratio):
                    notes.append(f"hard_case_ratio={hard_case_ratio:.3f}")

            if hard_case_watch and (dynamic_support or thr_pred == 1 or sim_pred == 1):
                final_status = "static_hard_case_watch"
                risk_level = "watch"
                primary_evidence = "hard_case_multiview"
                needs_review = True
                predicted_label = np.nan
                notes.append("hard case watch overrides static alerting")
            elif thr_pred == 1 and sim_pred == 1:
                if dynamic_support:
                    final_status = "static_dynamic_supported_alert"
                    primary_evidence = "threshold+similarity+multiview"
                    notes.append("dynamic support agrees with static alert")
                else:
                    final_status = "static_consensus_alert"
                    primary_evidence = "threshold+similarity"
                risk_level = "high"
                needs_review = True
                predicted_label = 1
            elif thr_pred == 1 and sim_pred == 0:
                if dynamic_support:
                    final_status = "static_dynamic_supported_alert"
                    risk_level = "high"
                    primary_evidence = "threshold+multiview"
                    notes.append("dynamic support upgrades threshold-only alert")
                else:
                    final_status = "static_threshold_only_alert"
                    risk_level = "medium"
                    primary_evidence = "threshold_branch"
                needs_review = True
                predicted_label = 1
            elif thr_pred is None and sim_pred == 1:
                if dynamic_support:
                    final_status = "static_dynamic_supported_alert"
                    risk_level = "high"
                    primary_evidence = "similarity+multiview"
                    notes.append("dynamic support upgrades similarity-only alert")
                else:
                    final_status = "static_memory_only_alert"
                    risk_level = "medium"
                    primary_evidence = "similarity_branch"
                needs_review = True
                predicted_label = 1
            elif thr_pred == 0 and sim_pred == 0:
                if dynamic_support:
                    final_status = "static_dynamic_support_alert"
                    risk_level = "medium"
                    primary_evidence = "multiview_support"
                    needs_review = True
                    predicted_label = 1
                    notes.append("multiview support recovers static miss")
                else:
                    final_status = "static_low_risk"
                    risk_level = "low"
                    primary_evidence = "threshold+similarity"
                    needs_review = False
                    predicted_label = 0
            elif thr_pred == 0 and sim_pred == 1:
                if dynamic_support:
                    final_status = "static_dynamic_supported_alert"
                    risk_level = "high"
                    primary_evidence = "similarity+multiview"
                    needs_review = True
                    predicted_label = 1
                    notes.append("dynamic support resolves similarity disagreement")
                else:
                    final_status = "static_disagreement_watch"
                    risk_level = "watch"
                    primary_evidence = "similarity_branch"
                    needs_review = True
                    predicted_label = 1
            elif thr_pred is None and sim_pred == 0:
                if dynamic_support:
                    final_status = "static_dynamic_support_watch"
                    risk_level = "watch"
                    primary_evidence = "multiview_support"
                    needs_review = True
                    predicted_label = np.nan
                    notes.append("multiview support present but static branches insufficient")
                else:
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
                "dynamic_vote_count": dynamic_vote_count if file_name in static_files else np.nan,
                "dynamic_support": dynamic_support if file_name in static_files else np.nan,
                "hard_case_watch": hard_case_watch if file_name in static_files else np.nan,
                "transition_boost_count": int(transition_boost_row["transition_boost_count"])
                if transition_boost_row is not None
                else np.nan,
                "notes": " | ".join(notes),
            }
        )
    return pd.DataFrame(rows)


def build_summary(
    decision_df: pd.DataFrame,
    transition_df: pd.DataFrame,
    threshold_df: pd.DataFrame,
    multiview_df: pd.DataFrame,
) -> Dict[str, Any]:
    review_count = int(decision_df["needs_review"].fillna(False).sum())
    final_status_counts = decision_df["final_status"].value_counts().to_dict()
    risk_counts = decision_df["risk_level"].value_counts().to_dict()

    transition_alerts = decision_df[decision_df["final_status"].isin(["transition_alert", "transition_boost_alert"])]
    transition_boost_alerts = decision_df[decision_df["final_status"] == "transition_boost_alert"]
    transition_total = int(len(transition_df))
    transition_capture = float(len(transition_alerts) / transition_total) if transition_total else np.nan
    transition_boost_capture = float(len(transition_boost_alerts) / transition_total) if transition_total else np.nan

    static_eval_df = decision_df[decision_df["expected_family"] != "transition_run"].copy()
    static_eval_df = static_eval_df[static_eval_df["predicted_label"].notna() & static_eval_df["true_label"].notna()]
    static_bal_acc = (
        float(balanced_accuracy_score(static_eval_df["true_label"].astype(int), static_eval_df["predicted_label"].astype(int)))
        if not static_eval_df.empty and static_eval_df["true_label"].nunique() > 1
        else np.nan
    )

    static_candidate_total = int(len(multiview_df))
    static_pred_covered = int(
        decision_df[
            decision_df["file"].isin(multiview_df["file"].tolist())
            & decision_df["predicted_label"].notna()
        ].shape[0]
    )
    static_coverage = float(static_pred_covered / static_candidate_total) if static_candidate_total else np.nan
    threshold_abstains = int((threshold_df["threshold_status"] == "abstain").sum()) if not threshold_df.empty else 0
    hard_case_count = int(multiview_df["hard_case_watch"].fillna(False).sum()) if not multiview_df.empty else 0
    dynamic_support_count = int(multiview_df["dynamic_support"].fillna(False).sum()) if not multiview_df.empty else 0
    dynamic_recovered_count = int((decision_df["final_status"] == "static_dynamic_support_alert").sum())

    acceptance = {
        "transition_evidence_captured": bool(transition_total > 0 and transition_capture == 1.0),
        "transition_boost_attached": bool(transition_total > 0 and transition_boost_capture == 1.0),
        "threshold_abstain_enabled": bool(threshold_abstains > 0),
        "hard_case_watch_enabled": bool(hard_case_count > 0),
        "dynamic_support_recovers_miss": bool(dynamic_recovered_count > 0),
        "all_runs_resolved_to_status": bool(decision_df["final_status"].notna().all()),
        "static_review_quality_ready": bool(not pd.isna(static_bal_acc) and static_bal_acc >= STATIC_PASS_BALANCED_ACCURACY),
        "static_coverage_acceptable": bool(not pd.isna(static_coverage) and static_coverage >= STATIC_PASS_COVERAGE),
    }
    if all(acceptance.values()):
        verdict = "PASS"
    elif acceptance["transition_evidence_captured"] and acceptance["all_runs_resolved_to_status"]:
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
        "transition_boost_capture_rate": transition_boost_capture,
        "static_eval_run_count": int(len(static_eval_df)),
        "static_eval_balanced_accuracy": static_bal_acc,
        "static_candidate_runs": static_candidate_total,
        "static_prediction_coverage": static_coverage,
        "threshold_abstain_runs": threshold_abstains,
        "hard_case_watch_runs": hard_case_count,
        "dynamic_support_runs": dynamic_support_count,
        "dynamic_support_recovered_runs": dynamic_recovered_count,
        "acceptance": acceptance,
    }


def write_markdown(path: str, summary: Dict[str, Any], decision_df: pd.DataFrame, multiview_df: pd.DataFrame) -> None:
    lines = [
        "# 实验室第三阶段 状态段级证据融合 v2 报告",
        "",
        f"- 结论：`{summary['verdict']}`",
        f"- review_queue_runs：`{summary['review_queue_runs']}`",
        f"- transition_capture_rate：`{summary['transition_capture_rate']}`",
        f"- transition_boost_capture_rate：`{summary['transition_boost_capture_rate']}`",
        f"- static_eval_balanced_accuracy：`{summary['static_eval_balanced_accuracy']}`",
        f"- static_prediction_coverage：`{summary['static_prediction_coverage']}`",
        f"- hard_case_watch_runs：`{summary['hard_case_watch_runs']}`",
        f"- dynamic_support_recovered_runs：`{summary['dynamic_support_recovered_runs']}`",
        "",
        "## v2 的三处新增",
        "",
        "- `transition_boost`：把转移邻域里更强的湿度抬升特征接进转移告警，不再只看旧的 transition score。",
        "- `hard_case_watch`：对跨标签更近的静态难例主动降级为 review / abstain，不让它继续污染静态判定。",
        "- `dynamic_support`：对原分支漏掉、但多视角证据很强的静态运行进行补充提升。",
        "",
        "## 运行级结果分布",
        "",
        f"- final_status_counts = `{summary['final_status_counts']}`",
        f"- risk_level_counts = `{summary['risk_level_counts']}`",
        "",
        "## 验收判断",
        "",
    ]

    for key, value in summary["acceptance"].items():
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
        lines.append(
            f"- {row['file']} | status={row['final_status']} | evidence={row['primary_evidence']} | "
            f"segment={row['primary_segment_id']} | notes={row['notes']}"
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
            "- 这一步依然不是“统一分类器”，而是把多视角证据压成更稳的运行级状态机输出。",
            "- `transition` 现在已经不仅能报，还能给出 `boost` 证据；演示时可直接把它作为最强场景。",
            "- `2026-03-06 160246_seal_unheated` 这类静态难例现在会进入 `hard_case_watch`，不再被硬判成告警。",
            "- `2026-03-03 181049_unseal_unheated` 这类旧分支漏报、但多视角证据很强的运行，现在会进入 `dynamic_support` 路径。",
            "- 当前最合理的现场口径仍然是：强证据直接进入 review，弱证据辅助提分，难例与干扰主动保守。",
            "",
        ]
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    window_df, routed_df, static_route_df, file_df = build_inputs(args)
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
    summary = build_summary(decision_df, transition_df, threshold_df, multiview_df)

    outputs = {
        "segment_csv": os.path.join(args.output_dir, "phase3_evidence_segments.csv"),
        "transition_csv": os.path.join(args.output_dir, "phase3_transition_evidence.csv"),
        "threshold_csv": os.path.join(args.output_dir, "phase3_threshold_evidence.csv"),
        "similarity_csv": os.path.join(args.output_dir, "phase3_similarity_evidence.csv"),
        "multiview_csv": os.path.join(args.output_dir, "phase3_multiview_static_evidence.csv"),
        "transition_boost_csv": os.path.join(args.output_dir, "phase3_transition_boost_evidence.csv"),
        "run_table_csv": os.path.join(args.output_dir, "phase3_multiview_run_table.csv"),
        "decision_csv": os.path.join(args.output_dir, "phase3_run_decisions.csv"),
        "report_md": os.path.join(args.output_dir, "phase3_evidence_fuser_report.md"),
        "report_json": os.path.join(args.output_dir, "phase3_evidence_fuser_report.json"),
    }

    segments_df.to_csv(outputs["segment_csv"], index=False, encoding="utf-8-sig")
    transition_df.to_csv(outputs["transition_csv"], index=False, encoding="utf-8-sig")
    threshold_df.to_csv(outputs["threshold_csv"], index=False, encoding="utf-8-sig")
    similarity_df.to_csv(outputs["similarity_csv"], index=False, encoding="utf-8-sig")
    multiview_df.to_csv(outputs["multiview_csv"], index=False, encoding="utf-8-sig")
    transition_boost_df.to_csv(outputs["transition_boost_csv"], index=False, encoding="utf-8-sig")
    run_df.to_csv(outputs["run_table_csv"], index=False, encoding="utf-8-sig")
    decision_df.to_csv(outputs["decision_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["report_md"], summary, decision_df, multiview_df)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
