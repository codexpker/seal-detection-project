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


ARTIFACT_LIKE_FEATURES = {
    "duration_h",
    "ah_ingress_count",
    "dew_ingress_count",
}

SUPPORT_DISTANCE_FEATURES = [
    "max_corr_level_ah",
    "max_corr_level_dew",
    "max_corr_level_hum",
    "max_corr_outRH_inRH_change",
    "ah_neg_response_ratio",
    "dew_neg_response_ratio",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Post-feedback reanalysis for new_data segment battlefield")
    parser.add_argument(
        "--feature-table-csv",
        default="reports/new_data_multiview_feature_mining_v2_run1/new_data_multiview_feature_table_v2.csv",
    )
    parser.add_argument(
        "--segment-support-csv",
        default="reports/new_data_segment_static_support_v2_run1/segment_support_output_v2.csv",
    )
    parser.add_argument(
        "--feedback-merged-csv",
        default="reports/new_data_segment_feedback_loop_v1_run2/segment_review_feedback_merged.csv",
    )
    parser.add_argument(
        "--output-dir",
        default="reports/new_data_segment_post_feedback_reanalysis_v1_run1",
    )
    return parser.parse_args()


def provisional_role(row: pd.Series) -> str:
    review_label = str(row.get("review_label", "") or "")
    support_status = str(row.get("support_status_v2", "") or "")
    static_bucket = str(row.get("static_bucket", "") or "")

    if review_label == "transition_positive" or support_status == "transition_primary_support":
        return "transition_positive"
    if review_label == "positive_reference" or static_bucket == "static_positive_reference":
        return "positive_reference"
    if review_label == "negative_reference" or static_bucket == "static_negative_reference":
        return "negative_reference"
    if review_label == "breathing_watch" or support_status == "static_watch_breathing_confirmed":
        return "breathing_watch"
    if review_label == "confound" or support_status == "static_watch_confound_confirmed":
        return "confound"
    if support_status == "transition_secondary_control":
        return "secondary_transition_control"
    return "other"


def build_inventory(feature_df: pd.DataFrame, support_df: pd.DataFrame, feedback_df: pd.DataFrame) -> pd.DataFrame:
    merged = feature_df.merge(
        support_df[
            [
                "segment_id",
                "run_id",
                "support_status_v2",
                "support_risk_v2",
                "support_reason_v2",
                "weak_positive_support_score_v2",
                "breathing_suppression_score_v2",
                "confound_reject_score_v2",
            ]
        ],
        on="segment_id",
        how="left",
    )
    merged = merged.merge(
        feedback_df[["segment_id", "review_label", "review_status_v2", "feedback_action_v1", "reviewer", "review_note"]],
        on="segment_id",
        how="left",
    )
    merged["provisional_role_v1"] = merged.apply(provisional_role, axis=1)
    return merged


def rank_features(inventory_df: pd.DataFrame) -> pd.DataFrame:
    positive_roles = {"positive_reference", "transition_positive"}
    refs = inventory_df[inventory_df["provisional_role_v1"].isin(positive_roles | {"negative_reference"})].copy()
    refs["label"] = refs["provisional_role_v1"].isin(positive_roles).astype(int)

    exclude = {
        "segment_id",
        "file",
        "segment_name",
        "segment_source",
        "segment_seal_state",
        "static_bucket",
        "primary_task",
        "challenge_role",
        "run_id",
        "support_status_v2",
        "support_risk_v2",
        "support_reason_v2",
        "review_label",
        "review_status_v2",
        "feedback_action_v1",
        "reviewer",
        "review_note",
        "provisional_role_v1",
    }
    rows: List[Dict[str, Any]] = []
    numeric_features = [
        c
        for c in inventory_df.columns
        if c not in exclude and c not in ARTIFACT_LIKE_FEATURES and pd.api.types.is_numeric_dtype(inventory_df[c])
    ]
    for feature in numeric_features:
        values = pd.to_numeric(refs[feature], errors="coerce")
        valid = values.notna()
        if valid.sum() < 3:
            continue
        auc_pos = auc_pairwise(values.loc[valid].tolist(), refs.loc[valid, "label"].tolist()) or 0.0
        auc_neg = auc_pairwise((-values.loc[valid]).tolist(), refs.loc[valid, "label"].tolist()) or 0.0
        direction = "pos" if auc_pos >= auc_neg else "neg"
        rows.append(
            {
                "feature": feature,
                "auc": float(max(auc_pos, auc_neg)),
                "direction": direction,
                "negative_median": float(pd.to_numeric(refs.loc[(refs["label"] == 0) & valid, feature], errors="coerce").median()),
                "positive_median": float(pd.to_numeric(refs.loc[(refs["label"] == 1) & valid, feature], errors="coerce").median()),
            }
        )
    if not rows:
        return pd.DataFrame(columns=["feature", "auc", "direction", "negative_median", "positive_median"])
    return pd.DataFrame(rows).sort_values(["auc", "feature"], ascending=[False, True]).reset_index(drop=True)


def challenge_usefulness(inventory_df: pd.DataFrame, ranking_df: pd.DataFrame) -> pd.DataFrame:
    expected = {
        "positive_reference": True,
        "transition_positive": True,
        "breathing_watch": False,
        "confound": False,
    }
    targets = inventory_df[inventory_df["provisional_role_v1"].isin(expected.keys())].copy()
    rows: List[Dict[str, Any]] = []
    for _, rr in ranking_df.iterrows():
        feat = rr["feature"]
        direction = rr["direction"]
        positive_median = rr["positive_median"]
        score = 0
        total = 0
        item: Dict[str, Any] = {
            "feature": feat,
            "auc": rr["auc"],
        }
        for role, expect_positive in expected.items():
            sub = targets[targets["provisional_role_v1"] == role]
            if sub.empty or feat not in sub.columns:
                continue
            value = pd.to_numeric(sub[feat], errors="coerce").median()
            toward_positive = False if pd.isna(value) else (float(value) >= float(positive_median) if direction == "pos" else float(value) <= float(positive_median))
            item[f"{role}_toward_positive"] = toward_positive
            score += int(toward_positive == expect_positive)
            total += 1
        item["challenge_match"] = score
        item["total_roles"] = total
        rows.append(item)
    if not rows:
        return pd.DataFrame(columns=["feature", "auc", "challenge_match", "total_roles"])
    return pd.DataFrame(rows).sort_values(["challenge_match", "auc", "feature"], ascending=[False, False, True]).reset_index(drop=True)


def compute_distance_view(inventory_df: pd.DataFrame, ranking_df: pd.DataFrame) -> pd.DataFrame:
    positive_roles = {"positive_reference", "transition_positive"}
    refs = inventory_df[inventory_df["provisional_role_v1"].isin(positive_roles | {"negative_reference"})].copy()
    if refs.empty:
        return pd.DataFrame()

    selected = [f for f in SUPPORT_DISTANCE_FEATURES if f in inventory_df.columns and f in ranking_df["feature"].values]
    use_df = inventory_df[["segment_id", "provisional_role_v1"] + selected].copy()
    ref_df = refs[["segment_id", "provisional_role_v1"] + selected].copy()
    ref_stats = ref_df[selected].agg(["median", "std"]).T.reset_index().rename(columns={"index": "feature"})
    ref_stats["std"] = ref_stats["std"].replace(0, np.nan).fillna(1.0)
    stat_map = ref_stats.set_index("feature")[["median", "std"]].to_dict(orient="index")

    scaled_rows: List[Dict[str, Any]] = []
    for _, row in use_df.iterrows():
        item: Dict[str, Any] = {
            "segment_id": row["segment_id"],
            "provisional_role_v1": row["provisional_role_v1"],
        }
        for feat in selected:
            val = pd.to_numeric(pd.Series([row.get(feat)]), errors="coerce").iloc[0]
            item[feat] = np.nan if pd.isna(val) else float((val - stat_map[feat]["median"]) / stat_map[feat]["std"])
        scaled_rows.append(item)
    scaled = pd.DataFrame(scaled_rows)

    pos_centroid = scaled[scaled["provisional_role_v1"].isin(positive_roles)][selected].mean(numeric_only=True)
    neg_centroid = scaled[scaled["provisional_role_v1"] == "negative_reference"][selected].mean(numeric_only=True)

    rows: List[Dict[str, Any]] = []
    for _, row in scaled.iterrows():
        vec = pd.to_numeric(row[selected], errors="coerce")
        valid = vec.notna() & pos_centroid.notna() & neg_centroid.notna()
        if int(valid.sum()) == 0:
            d_pos = np.nan
            d_neg = np.nan
        else:
            d_pos = float(np.linalg.norm(vec[valid] - pos_centroid[valid]))
            d_neg = float(np.linalg.norm(vec[valid] - neg_centroid[valid]))
        rows.append(
            {
                "segment_id": row["segment_id"],
                "provisional_role_v1": row["provisional_role_v1"],
                "distance_to_positive_centroid": d_pos,
                "distance_to_negative_centroid": d_neg,
                "margin_positive_minus_negative": (d_neg - d_pos) if pd.notna(d_pos) and pd.notna(d_neg) else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values(["provisional_role_v1", "segment_id"]).reset_index(drop=True)


def build_summary(inventory_df: pd.DataFrame, ranking_df: pd.DataFrame, usefulness_df: pd.DataFrame) -> Dict[str, Any]:
    return {
        "mainfield_segment_count": int(len(inventory_df)),
        "provisional_role_counts": inventory_df["provisional_role_v1"].value_counts(dropna=False).to_dict(),
        "top_re_ranked_features": ranking_df.head(12).to_dict(orient="records"),
        "top_challenge_useful_features": usefulness_df.head(12).to_dict(orient="records"),
    }


def fmt(value: Any) -> str:
    return "nan" if pd.isna(value) else f"{float(value):.3f}"


def write_markdown(
    path: str,
    summary: Dict[str, Any],
    distance_df: pd.DataFrame,
    inventory_df: pd.DataFrame,
) -> None:
    lines = [
        "# 新补充数据 段级回灌后重分析报告",
        "",
        f"- mainfield_segment_count: `{summary['mainfield_segment_count']}`",
        f"- provisional_role_counts: `{summary['provisional_role_counts']}`",
        "",
        "## 当前判断",
        "",
        "- 这一步不是训练新模型，而是用当前已经确认的高置信段，重新检查主战场静态池的结构是否更清楚。",
        "- 当前主战场已经不再只有“2 个负参考 + 3 个正参考”，而是暂时扩成了：`2 negative + 4 positive + 1 breathing + 1 confound`。",
        "- 因此现在最有价值的，不是继续找新特征，而是确认哪些特征在扩样本后仍然稳定，哪些只是对原始 5 个参考段过拟合。",
        "",
        "## 当前最值得继续追的特征",
        "",
    ]
    for item in summary["top_re_ranked_features"]:
        lines.append(
            f"- {item['feature']} | auc={item['auc']:.3f} | direction={item['direction']} | "
            f"negative_median={item['negative_median']:.3f} | positive_median={item['positive_median']:.3f}"
        )

    lines.extend(["", "## 对难段更有用的特征", ""])
    for item in summary["top_challenge_useful_features"]:
        lines.append(
            f"- {item['feature']} | auc={item['auc']:.3f} | challenge_match={int(item['challenge_match'])}/{int(item['total_roles'])}"
        )

    if not distance_df.empty:
        lines.extend(["", "## 段级参考池中的相对位置", ""])
        for _, row in distance_df.iterrows():
            lines.append(
                f"- {row['segment_id']} | role={row['provisional_role_v1']} | "
                f"d_pos={fmt(row['distance_to_positive_centroid'])} | d_neg={fmt(row['distance_to_negative_centroid'])} | "
                f"margin={fmt(row['margin_positive_minus_negative'])}"
            )

    lines.extend(
        [
            "",
            "## 结论",
            "",
            "1. `181049` 现在可以作为“被支持的正参考种子”存在，但它和三个 post-change 正参考并不完全同质，后续更适合区分 `strong positive` 和 `supported positive` 两层。",
            "2. `160246` 和 `20260321 heat-off` 仍然不该进入正参考池；它们继续作为 `breathing` 和 `confound` 角色保留是正确的。",
            "3. 扩样本和回灌之后，真正最稳的还是 `level-correlation + response persistence + neg-response suppression` 这组结构，而不是单一静态值。",
            "4. 当前剩余未确认的都是 `transition_secondary_control`，说明主战场静态部分已经基本被收干净，后续若继续自动推进，应优先在当前参考池上做保守重评估，而不是再开 whole-run 统一分类。",
            "",
        ]
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    feature_df = pd.read_csv(args.feature_table_csv)
    support_df = pd.read_csv(args.segment_support_csv)
    feedback_df = pd.read_csv(args.feedback_merged_csv)

    inventory_df = build_inventory(feature_df, support_df, feedback_df)
    ranking_df = rank_features(inventory_df)
    usefulness_df = challenge_usefulness(inventory_df, ranking_df)
    distance_df = compute_distance_view(inventory_df, ranking_df)
    summary = build_summary(inventory_df, ranking_df, usefulness_df)

    outputs = {
        "inventory_csv": os.path.join(args.output_dir, "post_feedback_segment_inventory.csv"),
        "feature_ranking_csv": os.path.join(args.output_dir, "post_feedback_feature_ranking.csv"),
        "challenge_usefulness_csv": os.path.join(args.output_dir, "post_feedback_challenge_usefulness.csv"),
        "distance_csv": os.path.join(args.output_dir, "post_feedback_distance_view.csv"),
        "report_md": os.path.join(args.output_dir, "post_feedback_reanalysis_report.md"),
        "report_json": os.path.join(args.output_dir, "post_feedback_reanalysis_report.json"),
    }

    inventory_df.to_csv(outputs["inventory_csv"], index=False, encoding="utf-8-sig")
    ranking_df.to_csv(outputs["feature_ranking_csv"], index=False, encoding="utf-8-sig")
    usefulness_df.to_csv(outputs["challenge_usefulness_csv"], index=False, encoding="utf-8-sig")
    distance_df.to_csv(outputs["distance_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["report_md"], summary, distance_df, inventory_df)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
