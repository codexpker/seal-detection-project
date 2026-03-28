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

from src.scripts.lab_phase1_acceptance import auc_pairwise


FALLBACK_FEATURES = [
    "best_lag_level_hum",
    "corr_headroom_in_hum",
    "corr_out_hum_in_hum",
    "late_rh_gain_per_out",
    "max_corr_level_hum",
    "best_lag_rh_h",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Segment memory bank similarity v2")
    parser.add_argument(
        "--current-inventory-csv",
        default="reports/new_data_segment_post_feedback_reanalysis_v1_run1/post_feedback_segment_inventory.csv",
    )
    parser.add_argument(
        "--old-feature-table-csv",
        default="reports/old_data_reassessment_v2_run1/old_data_feature_table_v2.csv",
    )
    parser.add_argument(
        "--old-projection-csv",
        default="reports/old_data_reassessment_v2_run1/old_data_projection_v2.csv",
    )
    parser.add_argument(
        "--guard-csv",
        default="reports/cross_dataset_feature_guard_v1_run1/cross_dataset_feature_guard.csv",
    )
    parser.add_argument("--output-dir", default="reports/segment_memory_bank_similarity_v2_run1")
    parser.add_argument("--top-k-features", type=int, default=6)
    parser.add_argument("--neighbor-k", type=int, default=2)
    return parser.parse_args()


def robust_scale(df: pd.DataFrame, features: List[str]) -> tuple[pd.Series, pd.Series]:
    center = df[features].median(numeric_only=True)
    spread = (df[features] - center).abs().median(numeric_only=True)
    spread = spread.replace(0.0, np.nan).fillna(1.0)
    return center, spread


def euclidean_distances(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    diff = a[:, None, :] - b[None, :, :]
    return np.sqrt(np.sum(diff * diff, axis=2))


def topk_mean_distance(query_x: np.ndarray, bank_x: np.ndarray, k: int) -> np.ndarray:
    if bank_x.shape[0] == 0:
        return np.full(query_x.shape[0], np.nan)
    k_eff = max(1, min(k, bank_x.shape[0]))
    dmat = euclidean_distances(query_x, bank_x)
    part = np.partition(dmat, kth=k_eff - 1, axis=1)[:, :k_eff]
    return part.mean(axis=1)


def choose_features(guard_df: pd.DataFrame, top_k: int) -> List[str]:
    if guard_df.empty:
        return FALLBACK_FEATURES[:top_k]
    chosen = [str(x) for x in guard_df["feature"].tolist()[:top_k]]
    return chosen if chosen else FALLBACK_FEATURES[:top_k]


def prepare_banks(
    current_df: pd.DataFrame,
    old_feature_df: pd.DataFrame,
    old_projection_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    health_df = current_df[current_df["provisional_role_v1"] == "negative_reference"].copy()
    anomaly_df = current_df[current_df["provisional_role_v1"].isin(["positive_reference", "transition_positive"])].copy()
    hard_df = current_df[current_df["provisional_role_v1"].isin(["breathing_watch", "confound"])].copy()

    old_hard_ids = old_projection_df[
        (old_projection_df["subgroup"] == "sealed_strict") & (old_projection_df["projection_status_v2"] == "old_positive_like")
    ]["file"].tolist()
    old_hard_df = old_feature_df[
        (old_feature_df["subgroup"] == "sealed_strict") & (old_feature_df["file"].isin(old_hard_ids))
    ].copy()
    if not old_hard_df.empty:
        old_hard_df["segment_id"] = "old::" + old_hard_df["file"].astype(str)
        old_hard_df["provisional_role_v1"] = "old_hard_negative"
        old_hard_df["data_origin_v2"] = "old_hard_negative"

    health_df["data_origin_v2"] = "current_health"
    anomaly_df["data_origin_v2"] = "current_anomaly"
    if "data_origin_v2" not in hard_df.columns:
        hard_df["data_origin_v2"] = "current_hard_negative"
    hard_df["data_origin_v2"] = hard_df["data_origin_v2"].fillna("current_hard_negative")
    return (
        health_df.reset_index(drop=True),
        anomaly_df.reset_index(drop=True),
        hard_df.reset_index(drop=True),
        old_hard_df.reset_index(drop=True),
    )


def expected_memory_role(row: pd.Series) -> str:
    role = str(row.get("provisional_role_v1", "") or "")
    if role == "negative_reference":
        return "health_core"
    if role in {"positive_reference", "transition_positive"}:
        return "anomaly_reference"
    return "hard_negative"


def build_query_df(current_df: pd.DataFrame, old_hard_eval_df: pd.DataFrame) -> pd.DataFrame:
    current_q = current_df.copy()
    current_q["query_origin_v2"] = "current_mainfield"
    current_q["expected_memory_role_v2"] = current_q.apply(expected_memory_role, axis=1)

    old_hard_q = old_hard_eval_df.copy()
    if not old_hard_q.empty:
        old_hard_q["query_origin_v2"] = "old_hard_negative"
        old_hard_q["expected_memory_role_v2"] = "hard_negative"

    return pd.concat([current_q, old_hard_q], ignore_index=True, sort=False).reset_index(drop=True)


def score_queries(
    query_df: pd.DataFrame,
    health_df: pd.DataFrame,
    anomaly_df: pd.DataFrame,
    hard_df: pd.DataFrame,
    features: List[str],
    k: int,
) -> pd.DataFrame:
    scale_source = pd.concat([health_df[features], anomaly_df[features], hard_df[features]], ignore_index=True)
    center, spread = robust_scale(scale_source, features)
    health_centroid = ((health_df[features] - center) / spread).median(numeric_only=True)
    anomaly_centroid = ((anomaly_df[features] - center) / spread).median(numeric_only=True)
    hard_centroid = ((hard_df[features] - center) / spread).median(numeric_only=True)

    rows: List[Dict[str, Any]] = []
    for _, query in query_df.iterrows():
        qv = ((pd.DataFrame([query[features]]) - center) / spread).iloc[0]

        def centroid_distance(vec: pd.Series, centroid: pd.Series) -> float:
            valid = vec.notna() & centroid.notna()
            if int(valid.sum()) == 0:
                return np.nan
            return float(np.linalg.norm(vec[valid] - centroid[valid]))

        d_health = centroid_distance(qv, health_centroid)
        d_anomaly = centroid_distance(qv, anomaly_centroid)
        d_hard = centroid_distance(qv, hard_centroid)

        dist_map = {
            "health_core": d_health,
            "anomaly_reference": d_anomaly,
            "hard_negative": d_hard,
        }
        valid_map = {k0: v0 for k0, v0 in dist_map.items() if pd.notna(v0)}
        predicted_role = min(valid_map, key=valid_map.get) if valid_map else "unknown"

        anomaly_adv = np.nan
        if pd.notna(d_anomaly):
            others = [x for x in [d_health, d_hard] if pd.notna(x)]
            anomaly_adv = (min(others) - d_anomaly) if others else np.nan

        health_only_risk = d_health
        rows.append(
            {
                "segment_id": query["segment_id"],
                "query_origin_v2": query["query_origin_v2"],
                "provisional_role_v1": query.get("provisional_role_v1", ""),
                "expected_memory_role_v2": query["expected_memory_role_v2"],
                "distance_health_core": d_health,
                "distance_anomaly_reference": d_anomaly,
                "distance_hard_negative": d_hard,
                "predicted_memory_role_v2": predicted_role,
                "memory_alignment_v2": predicted_role == query["expected_memory_role_v2"],
                "anomaly_advantage_v2": anomaly_adv,
                "health_only_risk_v2": health_only_risk,
            }
        )
    return pd.DataFrame(rows).sort_values(["query_origin_v2", "segment_id"]).reset_index(drop=True)


def summarize(
    features: List[str],
    health_df: pd.DataFrame,
    anomaly_df: pd.DataFrame,
    hard_df: pd.DataFrame,
    scored_df: pd.DataFrame,
) -> Dict[str, Any]:
    current_only = scored_df[scored_df["query_origin_v2"] == "current_mainfield"].copy()
    tri_acc = float(current_only["memory_alignment_v2"].mean()) if not current_only.empty else np.nan

    non_health = current_only[current_only["expected_memory_role_v2"] != "health_core"].copy()
    if not non_health.empty:
        non_health["label_anomaly"] = non_health["expected_memory_role_v2"].eq("anomaly_reference").astype(int)
        tri_auc = auc_pairwise(non_health["anomaly_advantage_v2"].fillna(0.0).tolist(), non_health["label_anomaly"].tolist())
        health_only_auc = auc_pairwise((-non_health["health_only_risk_v2"].fillna(0.0)).tolist(), non_health["label_anomaly"].tolist())
    else:
        tri_auc = None
        health_only_auc = None

    return {
        "selected_features": features,
        "health_core_segments": int(len(health_df)),
        "anomaly_reference_segments": int(len(anomaly_df)),
        "hard_negative_segments": int(len(hard_df)),
        "current_mainfield_alignment": tri_acc,
        "tri_memory_auc_anomaly_vs_hardnegative": tri_auc,
        "health_only_auc_anomaly_vs_hardnegative": health_only_auc,
        "top_segments": scored_df[[
            "segment_id",
            "query_origin_v2",
            "expected_memory_role_v2",
            "predicted_memory_role_v2",
            "anomaly_advantage_v2",
            "health_only_risk_v2",
        ]].head(12).to_dict(orient="records"),
    }


def fmt(value: Any) -> str:
    return "nan" if pd.isna(value) else f"{float(value):.3f}"


def write_markdown(path: str, summary: Dict[str, Any], scored_df: pd.DataFrame) -> None:
    lines = [
        "# Segment Memory Bank Similarity v2",
        "",
        "- 目的：把相似性支线从“单一健康库排序”升级为“健康参考 + 异常参考 + hard negative”三类记忆。",
        "",
        f"- selected_features: `{summary['selected_features']}`",
        f"- health_core_segments: `{summary['health_core_segments']}`",
        f"- anomaly_reference_segments: `{summary['anomaly_reference_segments']}`",
        f"- hard_negative_segments: `{summary['hard_negative_segments']}`",
        f"- current_mainfield_alignment: `{summary['current_mainfield_alignment']}`",
        f"- tri_memory_auc_anomaly_vs_hardnegative: `{summary['tri_memory_auc_anomaly_vs_hardnegative']}`",
        f"- health_only_auc_anomaly_vs_hardnegative: `{summary['health_only_auc_anomaly_vs_hardnegative']}`",
        "",
        "## 当前判断",
        "",
        "- 新数据对相似性支线的主要帮助，不是单纯扩健康库，而是第一次把 `健康参考 / 异常参考 / hard negative` 三类记忆补齐了。",
        "- 这使相似性支线不再只是判断“离健康有多远”，而可以显式判断“更像异常参考还是更像 hard negative”。",
        "- 当前这里采用的是小样本更稳的 `prototype centroid` 视角，不是直接做最近邻；因为你现在每类记忆库规模仍然很小。",
        "",
        "## 当前关键段的三类记忆结果",
        "",
    ]

    for _, row in scored_df.iterrows():
        lines.append(
            f"- {row['segment_id']} | origin={row['query_origin_v2']} | expected={row['expected_memory_role_v2']} | "
            f"predicted={row['predicted_memory_role_v2']} | d_health={fmt(row['distance_health_core'])} | "
            f"d_anomaly={fmt(row['distance_anomaly_reference'])} | d_hard={fmt(row['distance_hard_negative'])} | "
            f"anomaly_adv={fmt(row['anomaly_advantage_v2'])}"
        )

    lines.extend(
        [
            "",
            "## 结论",
            "",
            "1. 如果三类记忆能把 `breathing/confound` 从 anomaly 侧分开，说明新数据对相似性支线是实质性补强，而不是单纯加样本。",
            "2. 如果 `health_only` 无法区分 anomaly 与 hard negative，而 `tri_memory` 可以，说明后续相似性支线应升级为段级多记忆结构。",
            "3. 这条线后续应作为 `segment memory bank` 继续推进，而不是回到 run-level 单库排序。",
            "",
        ]
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    current_df = pd.read_csv(args.current_inventory_csv)
    old_feature_df = pd.read_csv(args.old_feature_table_csv)
    old_projection_df = pd.read_csv(args.old_projection_csv)
    guard_df = pd.read_csv(args.guard_csv)

    features = choose_features(guard_df, args.top_k_features)
    health_df, anomaly_df, hard_df, old_hard_eval_df = prepare_banks(current_df, old_feature_df, old_projection_df)
    query_df = build_query_df(current_df, old_hard_eval_df)
    scored_df = score_queries(query_df, health_df, anomaly_df, hard_df, features, args.neighbor_k)
    summary = summarize(features, health_df, anomaly_df, hard_df, scored_df)

    outputs = {
        "memory_bank_csv": os.path.join(args.output_dir, "segment_memory_banks.csv"),
        "scored_csv": os.path.join(args.output_dir, "segment_memory_similarity_scores.csv"),
        "report_md": os.path.join(args.output_dir, "segment_memory_bank_similarity_report.md"),
        "report_json": os.path.join(args.output_dir, "segment_memory_bank_similarity_report.json"),
    }

    bank_df = pd.concat(
        [
            health_df.assign(memory_bank_v2="health_core"),
            anomaly_df.assign(memory_bank_v2="anomaly_reference"),
            hard_df.assign(memory_bank_v2="hard_negative"),
            old_hard_eval_df.assign(memory_bank_v2="hard_negative_eval_only"),
        ],
        ignore_index=True,
        sort=False,
    )
    bank_df.to_csv(outputs["memory_bank_csv"], index=False, encoding="utf-8-sig")
    scored_df.to_csv(outputs["scored_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["report_md"], summary, scored_df)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
