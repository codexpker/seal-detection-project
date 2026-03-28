#!/usr/bin/env python3
import argparse
import json
import os
import sys
from typing import Any, Dict, List

import pandas as pd

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.scripts.new_data_multiview_feature_mining_v2 import ARTIFACT_LIKE_FEATURES


SUPPORT_SCORE_COLUMNS = {
    "weak_positive_support_score_v2",
    "breathing_suppression_score_v2",
    "confound_reject_score_v2",
}

NON_ACTIONABLE_GUARD_FEATURES = {
    "dew_gap_pos_ratio",
    "positive_headroom_ratio",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cross-dataset feature guard analysis")
    parser.add_argument(
        "--current-inventory-csv",
        default="reports/new_data_segment_post_feedback_reanalysis_v1_run1/post_feedback_segment_inventory.csv",
    )
    parser.add_argument(
        "--current-ranking-csv",
        default="reports/new_data_segment_post_feedback_reanalysis_v1_run1/post_feedback_feature_ranking.csv",
    )
    parser.add_argument(
        "--old-feature-table-csv",
        default="reports/old_data_reassessment_v2_run1/old_data_feature_table_v2.csv",
    )
    parser.add_argument(
        "--old-projection-csv",
        default="reports/old_data_reassessment_v2_run1/old_data_projection_v2.csv",
    )
    parser.add_argument("--output-dir", default="reports/cross_dataset_feature_guard_v1_run1")
    return parser.parse_args()


def evaluate_feature(
    feature: str,
    direction: str,
    positive_median: float,
    pos_df: pd.DataFrame,
    neg_df: pd.DataFrame,
) -> Dict[str, Any]:
    pos_values = pd.to_numeric(pos_df[feature], errors="coerce") if feature in pos_df.columns else pd.Series(dtype=float)
    neg_values = pd.to_numeric(neg_df[feature], errors="coerce") if feature in neg_df.columns else pd.Series(dtype=float)

    pos_valid = pos_values.notna()
    neg_valid = neg_values.notna()

    pos_match = 0
    neg_match = 0
    pos_total = int(pos_valid.sum())
    neg_total = int(neg_valid.sum())

    if direction == "pos":
        pos_match = int((pos_values.loc[pos_valid] >= positive_median).sum())
        neg_match = int((neg_values.loc[neg_valid] < positive_median).sum())
    else:
        pos_match = int((pos_values.loc[pos_valid] <= positive_median).sum())
        neg_match = int((neg_values.loc[neg_valid] > positive_median).sum())

    total = pos_total + neg_total
    match = pos_match + neg_match
    return {
        "feature": feature,
        "direction": direction,
        "positive_median": float(positive_median),
        "positive_match": pos_match,
        "positive_total": pos_total,
        "negative_match": neg_match,
        "negative_total": neg_total,
        "guard_match": match,
        "guard_total": total,
        "guard_match_ratio": float(match / total) if total else float("nan"),
    }


def write_markdown(path: str, summary: Dict[str, Any]) -> None:
    lines = [
        "# 跨数据集特征守门分析 v1",
        "",
        f"- positive_count: `{summary['positive_count']}`",
        f"- negative_count: `{summary['negative_count']}`",
        f"- old_hard_negative_count: `{summary['old_hard_negative_count']}`",
        "",
        "## 当前判断",
        "",
        "- 这一步不是继续找新特征，而是检查：哪些特征在新数据主战场里看起来很强，但一碰到旧数据 hard negative 就会失真。",
        "- 只有同时能托住当前正池、又能压住当前 breathing/confound 和旧数据 hard negative 的特征，才值得继续往 `support v3` 里推进。",
        "",
        "## 当前最稳的跨数据集守门特征",
        "",
    ]
    for item in summary["top_guard_features"]:
        lines.append(
            f"- {item['feature']} | match={item['guard_match']}/{item['guard_total']} | "
            f"ratio={item['guard_match_ratio']:.3f} | direction={item['direction']} | positive_median={item['positive_median']:.3f}"
        )

    lines.extend(["", "## 结论", ""])
    lines.extend(
        [
            "1. 如果某个特征在当前主战场里 AUC 很高，但在旧数据 hard negative 上守不住，它就不该直接进入下一轮支持层。",
            "2. 真正值得继续保留的特征，应优先来自 `response persistence / coupling / dew-driven early response` 这几类结构，而不是单纯依赖累计漂移。",
            "3. 这一步的目标是为后续 `segment static support v3` 收窄特征集合，而不是重启统一分类器。",
            "",
        ]
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    current_inventory = pd.read_csv(args.current_inventory_csv)
    ranking_df = pd.read_csv(args.current_ranking_csv)
    old_feature_df = pd.read_csv(args.old_feature_table_csv)
    old_projection_df = pd.read_csv(args.old_projection_csv)

    pos_df = current_inventory[current_inventory["provisional_role_v1"].isin(["positive_reference", "transition_positive"])].copy()
    cur_neg_df = current_inventory[current_inventory["provisional_role_v1"].isin(["breathing_watch", "confound"])].copy()
    old_hard_ids = old_projection_df[
        (old_projection_df["subgroup"] == "sealed_strict") & (old_projection_df["projection_status_v2"] == "old_positive_like")
    ]["file"].tolist()
    old_neg_df = old_feature_df[
        (old_feature_df["subgroup"] == "sealed_strict") & (old_feature_df["file"].isin(old_hard_ids))
    ].copy()
    neg_df = pd.concat([cur_neg_df, old_neg_df], ignore_index=True, sort=False)

    rows: List[Dict[str, Any]] = []
    for _, rr in ranking_df.iterrows():
        feature = str(rr["feature"])
        if feature in ARTIFACT_LIKE_FEATURES or feature in SUPPORT_SCORE_COLUMNS or feature in NON_ACTIONABLE_GUARD_FEATURES:
            continue
        if feature not in pos_df.columns or feature not in neg_df.columns:
            continue
        if not pd.api.types.is_numeric_dtype(pos_df[feature]) or not pd.api.types.is_numeric_dtype(neg_df[feature]):
            continue
        combined = pd.concat(
            [pd.to_numeric(pos_df[feature], errors="coerce"), pd.to_numeric(neg_df[feature], errors="coerce")],
            ignore_index=True,
        ).dropna()
        if len(combined) < 4:
            continue
        if combined.nunique(dropna=True) < 3:
            continue
        if abs(float(combined.quantile(0.9) - combined.quantile(0.1))) < 1e-6:
            continue
        rows.append(
            evaluate_feature(
                feature=feature,
                direction=str(rr["direction"]),
                positive_median=float(rr["positive_median"]),
                pos_df=pos_df,
                neg_df=neg_df,
            )
        )

    guard_df = pd.DataFrame(rows).sort_values(
        ["guard_match_ratio", "guard_match", "feature"],
        ascending=[False, False, True],
    ).reset_index(drop=True)

    outputs = {
        "guard_csv": os.path.join(args.output_dir, "cross_dataset_feature_guard.csv"),
        "report_md": os.path.join(args.output_dir, "cross_dataset_feature_guard_report.md"),
        "report_json": os.path.join(args.output_dir, "cross_dataset_feature_guard_report.json"),
    }
    guard_df.to_csv(outputs["guard_csv"], index=False, encoding="utf-8-sig")

    summary = {
        "positive_count": int(len(pos_df)),
        "negative_count": int(len(neg_df)),
        "old_hard_negative_count": int(len(old_neg_df)),
        "top_guard_features": guard_df.head(12).to_dict(orient="records"),
    }
    write_markdown(outputs["report_md"], summary)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
