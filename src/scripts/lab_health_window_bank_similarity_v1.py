#!/usr/bin/env python3
import argparse
import json
import os
import sys
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.scripts.lab_phase1_acceptance import Phase1Config
from src.scripts.lab_transition_event_summary_v1 import build_event_table
from src.scripts.lab_phase3_evidence_fuser_v3 import run_pipeline_v3
from src.scripts.lab_unified_data_interface_v1 import (
    build_review_output,
    build_run_manifest,
    build_window_table,
    collect_source_path_map,
)


SIMILARITY_FEATURES = [
    "info_score",
    "transition_score_v3",
    "static_context_score_v3",
    "legacy_info_score",
    "delta_half_in_hum",
    "delta_half_dAH",
    "max_hourly_hum_rise",
    "corr_AH",
]

BANKABLE_LABELS = {"candidate_high_info", "exclude_low_info"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Health window bank + similarity ranking v1")
    parser.add_argument("--run-manifest-csv", default="")
    parser.add_argument("--window-table-csv", default="")
    parser.add_argument("--review-output-csv", default="")
    parser.add_argument("--input-dir", default=Phase1Config.input_dir)
    parser.add_argument("--input-zip", default=Phase1Config.input_zip)
    parser.add_argument("--metadata-xlsx", default=Phase1Config.metadata_xlsx)
    parser.add_argument("--output-dir", default="reports/lab_health_window_bank_similarity_v1")
    parser.add_argument("--window-hours", type=int, default=12)
    parser.add_argument("--step-hours", type=int, default=1)
    parser.add_argument("--transition-near-hours", type=int, default=6)
    parser.add_argument("--similarity-k", type=int, default=5)
    parser.add_argument("--min-bank-windows", type=int, default=5)
    return parser.parse_args()


def load_or_build_interface(args: argparse.Namespace) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if args.run_manifest_csv and args.window_table_csv and args.review_output_csv:
        return (
            pd.read_csv(args.run_manifest_csv),
            pd.read_csv(args.window_table_csv),
            pd.read_csv(args.review_output_csv),
        )

    result = run_pipeline_v3(args)
    event_df, _ = build_event_table(result["routed_df"], result["decision_df"], args)
    source_map = collect_source_path_map(args)
    run_manifest_df = build_run_manifest(result["file_df"], result["decision_df"], event_df, source_map)
    window_table_df = build_window_table(result["routed_df"], args)
    review_df = build_review_output(result["decision_df"], event_df, run_manifest_df)
    return run_manifest_df, window_table_df, review_df


def robust_scale(train_x: pd.DataFrame) -> Tuple[pd.Series, pd.Series]:
    center = train_x.median(numeric_only=True)
    spread = (train_x - center).abs().median(numeric_only=True)
    spread = spread.replace(0.0, np.nan).fillna(1.0)
    return center, spread


def build_feature_matrix(df: pd.DataFrame) -> pd.DataFrame:
    mat = df[SIMILARITY_FEATURES].copy()
    mat = mat.replace([np.inf, -np.inf], np.nan)
    medians = mat.median(numeric_only=True)
    return mat.fillna(medians)


def euclidean_distances(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    diff = a[:, None, :] - b[None, :, :]
    return np.sqrt(np.sum(diff * diff, axis=2))


def topk_mean_distance(test_x: np.ndarray, mem_x: np.ndarray, k: int) -> np.ndarray:
    dmat = euclidean_distances(test_x, mem_x)
    k_eff = max(1, min(k, mem_x.shape[0]))
    part = np.partition(dmat, kth=k_eff - 1, axis=1)[:, :k_eff]
    return part.mean(axis=1)


def self_reference_topk(mem_x: np.ndarray, k: int) -> np.ndarray:
    if mem_x.shape[0] <= 1:
        return np.ones(mem_x.shape[0], dtype=float)
    dmat = euclidean_distances(mem_x, mem_x)
    np.fill_diagonal(dmat, np.inf)
    k_eff = max(1, min(k, mem_x.shape[0] - 1))
    part = np.partition(dmat, kth=k_eff - 1, axis=1)[:, :k_eff]
    return part.mean(axis=1)


def normalize_scores(distances: np.ndarray, ref_distances: np.ndarray) -> np.ndarray:
    scale = float(np.quantile(ref_distances, 0.90)) if len(ref_distances) else 1.0
    scale = max(scale, 1e-6)
    return np.clip(distances / scale, 0.0, 3.0)


def prepare_window_view(run_manifest_df: pd.DataFrame, window_table_df: pd.DataFrame, review_df: pd.DataFrame) -> pd.DataFrame:
    run_cols = [
        "run_id",
        "seal_state_global",
        "has_transition",
        "condition_family_manual",
        "heat_state_manual",
        "ext_humidity_regime_manual",
        "final_status",
        "risk_level",
        "needs_review",
    ]
    review_cols = ["run_id", "review_status", "review_priority"]
    df = window_table_df.merge(run_manifest_df[run_cols], on="run_id", how="left")
    df = df.merge(review_df[review_cols], on="run_id", how="left")
    df["label_coarse"] = df["label_coarse"].fillna("")
    df["candidate_condition"] = df["candidate_condition"].fillna("")
    return df


def build_health_bank(window_df: pd.DataFrame) -> pd.DataFrame:
    bank_runs = window_df[
        (window_df["seal_state_global"] == "sealed")
        & (window_df["has_transition"].fillna(False) == False)
        & (window_df["needs_review"].fillna(False) == False)
        & (window_df["label_coarse"].isin(BANKABLE_LABELS))
    ].copy()
    if bank_runs.empty:
        return bank_runs

    bank_runs["bank_key_strict"] = (
        bank_runs["condition_family_manual"].fillna("unknown").astype(str)
        + "|"
        + bank_runs["heat_state_manual"].fillna("mixed").astype(str)
        + "|"
        + bank_runs["label_coarse"].fillna("").astype(str)
    )
    bank_runs["bank_key_relaxed"] = (
        bank_runs["heat_state_manual"].fillna("mixed").astype(str)
        + "|"
        + bank_runs["label_coarse"].fillna("").astype(str)
    )
    bank_runs["bank_key_global"] = bank_runs["label_coarse"].fillna("").astype(str)
    return bank_runs.reset_index(drop=True)


def select_bank_subset(query: pd.Series, bank_df: pd.DataFrame, min_bank_windows: int) -> Tuple[pd.DataFrame, str]:
    if bank_df.empty:
        return bank_df, "no_bank"

    bank_df = bank_df[bank_df["run_id"] != query["run_id"]].copy()
    if bank_df.empty:
        return bank_df, "no_bank"

    strict = bank_df[
        (bank_df["condition_family_manual"] == query["condition_family_manual"])
        & (bank_df["heat_state_manual"] == query["heat_state_manual"])
        & (bank_df["label_coarse"] == query["label_coarse"])
    ].copy()
    if len(strict) >= min_bank_windows:
        return strict, "strict_condition"

    relaxed = bank_df[
        (bank_df["heat_state_manual"] == query["heat_state_manual"])
        & (bank_df["label_coarse"] == query["label_coarse"])
    ].copy()
    if len(relaxed) >= min_bank_windows:
        return relaxed, "relaxed_heat_label"

    global_same = bank_df[bank_df["label_coarse"] == query["label_coarse"]].copy()
    if len(global_same) >= max(3, min_bank_windows // 2):
        return global_same, "global_label"

    return bank_df, "global_all"


def score_windows(window_df: pd.DataFrame, bank_df: pd.DataFrame, k: int, min_bank_windows: int) -> pd.DataFrame:
    bank_run_ids = set(bank_df["run_id"].dropna().tolist())
    target_df = window_df[
        window_df["label_coarse"].isin(BANKABLE_LABELS)
        & ~window_df["run_id"].isin(bank_run_ids)
    ].copy()
    rows: List[Dict[str, Any]] = []

    for _, query in target_df.iterrows():
        bank_subset, bank_scope = select_bank_subset(query, bank_df, min_bank_windows)
        if bank_subset.empty:
            rows.append(
                {
                    "run_id": query["run_id"],
                    "window_id": query["window_id"],
                    "bank_scope": "no_bank",
                    "bank_window_count": 0,
                    "similarity_risk": np.nan,
                    "raw_topk_distance": np.nan,
                }
            )
            continue

        bank_x = build_feature_matrix(bank_subset)
        query_x = build_feature_matrix(pd.DataFrame([query]))
        center, spread = robust_scale(bank_x)
        mem_scaled = ((bank_x - center) / spread).to_numpy(dtype=float)
        test_scaled = ((query_x - center) / spread).to_numpy(dtype=float)
        ref_dist = self_reference_topk(mem_scaled, k)
        raw_dist = float(topk_mean_distance(test_scaled, mem_scaled, k)[0])
        risk = float(normalize_scores(np.array([raw_dist]), ref_dist)[0])

        rows.append(
            {
                "run_id": query["run_id"],
                "window_id": query["window_id"],
                "bank_scope": bank_scope,
                "bank_window_count": int(len(bank_subset)),
                "similarity_risk": risk,
                "raw_topk_distance": raw_dist,
            }
        )

    score_df = pd.DataFrame(rows)
    if score_df.empty:
        return score_df
    return target_df.merge(score_df, on=["run_id", "window_id"], how="left")


def aggregate_runs(scored_window_df: pd.DataFrame, run_manifest_df: pd.DataFrame, review_df: pd.DataFrame) -> pd.DataFrame:
    if scored_window_df.empty:
        return pd.DataFrame()

    rows: List[Dict[str, Any]] = []
    for run_id, group in scored_window_df.groupby("run_id", dropna=False):
        scores = pd.to_numeric(group["similarity_risk"], errors="coerce").dropna().sort_values(ascending=False)
        if scores.empty:
            continue
        top_n = min(5, len(scores))
        top5_mean = float(scores.head(top_n).mean()) if top_n else np.nan
        q90 = float(scores.quantile(0.90)) if len(scores) else np.nan
        mean_score = float(scores.mean()) if len(scores) else np.nan
        max_score = float(scores.max()) if len(scores) else np.nan
        bank_scope_mode = group["bank_scope"].mode().iloc[0] if not group["bank_scope"].dropna().empty else ""
        rank_score = float(0.7 * top5_mean + 0.3 * q90) if pd.notna(top5_mean) and pd.notna(q90) else mean_score
        rows.append(
            {
                "run_id": run_id,
                "scored_windows": int(len(scores)),
                "mean_similarity_risk": mean_score,
                "q90_similarity_risk": q90,
                "top5_mean_similarity_risk": top5_mean,
                "max_similarity_risk": max_score,
                "rank_score": rank_score,
                "dominant_bank_scope": bank_scope_mode,
                "candidate_label_mix": "|".join(sorted(group["label_coarse"].dropna().astype(str).unique().tolist())),
            }
        )

    run_score_df = pd.DataFrame(rows)
    run_score_df = run_score_df.merge(run_manifest_df, on="run_id", how="left")
    run_score_df = run_score_df.merge(
        review_df[["run_id", "review_status", "review_priority"]],
        on="run_id",
        how="left",
    )
    return run_score_df.sort_values(["rank_score", "max_similarity_risk"], ascending=[False, False]).reset_index(drop=True)


def auc_pairwise(scores: List[float], labels: List[int]) -> float | None:
    positives = [float(s) for s, y in zip(scores, labels) if y == 1]
    negatives = [float(s) for s, y in zip(scores, labels) if y == 0]
    if not positives or not negatives:
        return None
    wins = 0.0
    total = float(len(positives) * len(negatives))
    for pos in positives:
        for neg in negatives:
            if pos > neg:
                wins += 1.0
            elif pos == neg:
                wins += 0.5
    return wins / total


def summarize_bank(bank_df: pd.DataFrame) -> pd.DataFrame:
    if bank_df.empty:
        return pd.DataFrame()
    return (
        bank_df.groupby(["condition_family_manual", "heat_state_manual", "label_coarse"], dropna=False)
        .agg(
            bank_window_count=("window_id", "count"),
            bank_run_count=("run_id", "nunique"),
            mean_info_score=("info_score", "mean"),
            mean_delta_half_dAH=("delta_half_dAH", "mean"),
        )
        .reset_index()
        .sort_values(["label_coarse", "condition_family_manual", "heat_state_manual"])
        .reset_index(drop=True)
    )


def build_summary(bank_df: pd.DataFrame, scored_window_df: pd.DataFrame, run_score_df: pd.DataFrame) -> Dict[str, Any]:
    pending_mask = run_score_df["needs_review"].fillna(False)
    pending_scores = run_score_df.loc[pending_mask, "rank_score"].dropna().tolist()
    non_pending_scores = run_score_df.loc[~pending_mask, "rank_score"].dropna().tolist()

    review_auc = auc_pairwise(
        run_score_df["rank_score"].fillna(0.0).tolist(),
        run_score_df["needs_review"].fillna(False).astype(int).tolist(),
    ) if not run_score_df.empty else None

    state_mask = run_score_df["seal_state_global"].isin(["sealed", "unsealed", "mixed"])
    state_eval = run_score_df.loc[state_mask].copy()
    state_eval["label"] = state_eval["seal_state_global"].isin(["unsealed", "mixed"]).astype(int)
    state_auc = auc_pairwise(
        state_eval["rank_score"].fillna(0.0).tolist(),
        state_eval["label"].tolist(),
    ) if not state_eval.empty else None

    top_runs = (
        run_score_df[["run_id", "rank_score", "final_status", "review_status"]]
        .head(5)
        .to_dict(orient="records")
        if not run_score_df.empty
        else []
    )

    return {
        "health_bank_windows": int(len(bank_df)),
        "health_bank_runs": int(bank_df["run_id"].nunique()) if not bank_df.empty else 0,
        "scored_windows": int(len(scored_window_df)),
        "scored_runs": int(len(run_score_df)),
        "pending_mean_rank_score": float(np.mean(pending_scores)) if pending_scores else np.nan,
        "non_pending_mean_rank_score": float(np.mean(non_pending_scores)) if non_pending_scores else np.nan,
        "run_auc_vs_review_queue": review_auc,
        "run_auc_vs_nonsealed_or_mixed": state_auc,
        "top_ranked_runs": top_runs,
    }


def write_markdown(path: str, summary: Dict[str, Any], bank_summary_df: pd.DataFrame, run_score_df: pd.DataFrame) -> None:
    lines = [
        "# Health Window Bank + Similarity Ranking v1",
        "",
        "- 目的：在不新增黑盒模型的前提下，把当前实验室主路线进一步推进成“健康窗口库 + 相似性风险排序”的现场迁移骨架。",
        "",
        f"- health_bank_windows：`{summary['health_bank_windows']}`",
        f"- health_bank_runs：`{summary['health_bank_runs']}`",
        f"- scored_windows：`{summary['scored_windows']}`",
        f"- scored_runs：`{summary['scored_runs']}`",
        f"- pending_mean_rank_score：`{summary['pending_mean_rank_score']}`",
        f"- non_pending_mean_rank_score：`{summary['non_pending_mean_rank_score']}`",
        f"- run_auc_vs_review_queue：`{summary['run_auc_vs_review_queue']}`",
        f"- run_auc_vs_nonsealed_or_mixed：`{summary['run_auc_vs_nonsealed_or_mixed']}`",
        "",
        "## 健康窗口库概览",
        "",
    ]

    if bank_summary_df.empty:
        lines.append("- 当前没有可用健康窗口库。")
    else:
        for _, row in bank_summary_df.iterrows():
            lines.append(
                f"- {row['condition_family_manual']} | heat={row['heat_state_manual']} | coarse={row['label_coarse']} | "
                f"bank_runs={int(row['bank_run_count'])} | bank_windows={int(row['bank_window_count'])}"
            )

    lines.extend(["", "## 当前风险排序前列", ""])
    for _, row in run_score_df.head(8).iterrows():
        lines.append(
            f"- {row['run_id']} | rank_score={row['rank_score']:.3f} | final_status={row['final_status']} | "
            f"review_status={row['review_status']} | dominant_bank_scope={row['dominant_bank_scope']}"
        )

    lines.extend(
        [
            "",
            "## 当前判断",
            "",
            "- 这一步的目标不是做二分类，而是为后续现场任务先提供健康窗口库和风险排序接口。",
            "- 当前健康库仍然偏小，因此它更适合作为迁移骨架和排序器，而不是替代现有实验室主判定链。",
            "- 后续只要现场数据能继续按 `run_manifest / window_table / review_output` 接入，就可以逐步把健康库从实验室扩到设备级历史窗口库。",
            "",
        ]
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    run_manifest_df, window_table_df, review_df = load_or_build_interface(args)
    window_df = prepare_window_view(run_manifest_df, window_table_df, review_df)
    bank_df = build_health_bank(window_df)
    scored_window_df = score_windows(window_df, bank_df, k=args.similarity_k, min_bank_windows=args.min_bank_windows)
    run_score_df = aggregate_runs(scored_window_df, run_manifest_df, review_df)
    bank_summary_df = summarize_bank(bank_df)
    summary = build_summary(bank_df, scored_window_df, run_score_df)

    outputs = {
        "health_bank_csv": os.path.join(args.output_dir, "health_window_bank.csv"),
        "health_bank_summary_csv": os.path.join(args.output_dir, "health_window_bank_summary.csv"),
        "window_similarity_csv": os.path.join(args.output_dir, "window_similarity_ranking.csv"),
        "run_similarity_csv": os.path.join(args.output_dir, "run_similarity_ranking.csv"),
        "report_md": os.path.join(args.output_dir, "health_window_bank_report.md"),
        "report_json": os.path.join(args.output_dir, "health_window_bank_report.json"),
    }

    bank_df.to_csv(outputs["health_bank_csv"], index=False, encoding="utf-8-sig")
    bank_summary_df.to_csv(outputs["health_bank_summary_csv"], index=False, encoding="utf-8-sig")
    scored_window_df.to_csv(outputs["window_similarity_csv"], index=False, encoding="utf-8-sig")
    run_score_df.to_csv(outputs["run_similarity_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["report_md"], summary, bank_summary_df, run_score_df)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
