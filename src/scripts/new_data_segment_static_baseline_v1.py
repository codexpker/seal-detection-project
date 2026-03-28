#!/usr/bin/env python3
import argparse
import json
import os
from typing import Any, Dict, List

import numpy as np
import pandas as pd


FEATURES: List[str] = [
    "delta_half_in_h",
    "delta_half_dAH",
    "slope_in_h_per_h",
    "slope_dAH_per_h",
    "end_start_dAH",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Segment-level static baseline v1 for new_data mainfield segments")
    parser.add_argument(
        "--static-candidates-csv",
        default="reports/new_data_segment_pipeline_v1_run1/segment_static_candidates.csv",
    )
    parser.add_argument(
        "--segment-manifest-csv",
        default="reports/new_data_segment_pipeline_v1_run1/segment_pipeline_manifest.csv",
    )
    parser.add_argument("--output-dir", default="reports/new_data_segment_static_baseline_v1_run1")
    parser.add_argument("--positive-vote-min", type=int, default=4)
    parser.add_argument("--negative-vote-max", type=int, default=1)
    return parser.parse_args()


def build_reference_model(ref_df: pd.DataFrame) -> Dict[str, Any]:
    thresholds: Dict[str, float] = {}
    for feature in FEATURES:
        neg = pd.to_numeric(ref_df.loc[ref_df["segment_seal_state"] == "sealed", feature], errors="coerce").dropna()
        pos = pd.to_numeric(ref_df.loc[ref_df["segment_seal_state"] == "unsealed", feature], errors="coerce").dropna()
        thresholds[feature] = float((neg.median() + pos.median()) / 2.0)

    X = ref_df[FEATURES].astype(float)
    mean = X.mean()
    std = X.std(ddof=0).replace(0.0, 1.0)
    Xt = (X - mean) / std
    neg_proto = Xt[ref_df["segment_seal_state"] == "sealed"].mean()
    pos_proto = Xt[ref_df["segment_seal_state"] == "unsealed"].mean()
    return {
        "thresholds": thresholds,
        "mean": mean,
        "std": std,
        "neg_proto": neg_proto,
        "pos_proto": pos_proto,
    }


def score_segment(row: pd.Series, model: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    vote_hits: List[str] = []
    for feature in FEATURES:
        value = pd.to_numeric(pd.Series([row.get(feature)]), errors="coerce").iloc[0]
        cutoff = model["thresholds"][feature]
        if pd.isna(value):
            continue
        if float(value) > float(cutoff):
            vote_hits.append(feature)

    vote_count = len(vote_hits)
    x = ((row[FEATURES].astype(float) - model["mean"]) / model["std"]).astype(float)
    d_neg = float(np.sqrt(((x - model["neg_proto"]) ** 2).sum()))
    d_pos = float(np.sqrt(((x - model["pos_proto"]) ** 2).sum()))
    prototype_margin = float(d_neg - d_pos)
    vote_ratio = float(vote_count / len(FEATURES))

    raw_label = "watch"
    if vote_count >= int(args.positive_vote_min) and prototype_margin > 0:
        raw_label = "positive"
    elif vote_count <= int(args.negative_vote_max) and prototype_margin < 0:
        raw_label = "negative"

    confidence = "low"
    if raw_label != "watch" and abs(prototype_margin) >= 2.0:
        confidence = "high"
    elif raw_label != "watch" and abs(prototype_margin) >= 0.5:
        confidence = "medium"

    return {
        "static_vote_count_v1": int(vote_count),
        "static_vote_ratio_v1": vote_ratio,
        "static_vote_hits_v1": ",".join(vote_hits),
        "distance_negative_v1": d_neg,
        "distance_positive_v1": d_pos,
        "prototype_margin_v1": prototype_margin,
        "raw_label_v1": raw_label,
        "raw_confidence_v1": confidence,
    }


def evaluate_reference_pool(ref_df: pd.DataFrame, args: argparse.Namespace) -> Dict[str, Any]:
    model = build_reference_model(ref_df)
    rows: List[Dict[str, Any]] = []
    resolved_correct = 0
    resolved_count = 0

    for _, row in ref_df.iterrows():
        score = score_segment(row, model, args)
        actual = "positive" if str(row["segment_seal_state"]) == "unsealed" else "negative"
        resolved = score["raw_label_v1"] != "watch"
        correct = resolved and score["raw_label_v1"] == actual
        if resolved:
            resolved_count += 1
            resolved_correct += int(correct)
        rows.append(
            {
                "segment_id": row["segment_id"],
                "actual_label": actual,
                **score,
                "resolved_v1": resolved,
                "correct_v1": bool(correct),
            }
        )

    apparent_df = pd.DataFrame(rows)

    loo_rows: List[Dict[str, Any]] = []
    loo_resolved = 0
    loo_correct = 0
    for idx, row in ref_df.reset_index(drop=True).iterrows():
        train = ref_df.reset_index(drop=True).drop(index=idx)
        model_i = build_reference_model(train)
        score = score_segment(row, model_i, args)
        actual = "positive" if str(row["segment_seal_state"]) == "unsealed" else "negative"
        resolved = score["raw_label_v1"] != "watch"
        correct = resolved and score["raw_label_v1"] == actual
        if resolved:
            loo_resolved += 1
            loo_correct += int(correct)
        loo_rows.append(
            {
                "segment_id": row["segment_id"],
                "actual_label": actual,
                **score,
                "resolved_v1": resolved,
                "correct_v1": bool(correct),
            }
        )

    loo_df = pd.DataFrame(loo_rows)
    return {
        "reference_model": model,
        "apparent_df": apparent_df,
        "loo_df": loo_df,
        "apparent_coverage": float(resolved_count / len(ref_df)) if len(ref_df) else np.nan,
        "apparent_precision_on_resolved": float(resolved_correct / resolved_count) if resolved_count else np.nan,
        "loo_coverage": float(loo_resolved / len(ref_df)) if len(ref_df) else np.nan,
        "loo_precision_on_resolved": float(loo_correct / loo_resolved) if loo_resolved else np.nan,
    }


def build_prediction_table(static_df: pd.DataFrame, manifest_df: pd.DataFrame, model: Dict[str, Any], args: argparse.Namespace) -> pd.DataFrame:
    merged = static_df.merge(
        manifest_df[
            [
                "segment_id",
                "primary_task",
                "secondary_tasks",
                "segment_role",
            ]
        ],
        on="segment_id",
        how="left",
    )

    rows: List[Dict[str, Any]] = []
    for _, row in merged.iterrows():
        score = score_segment(row, model, args)
        final_assessment = score["raw_label_v1"]
        final_reason = "baseline raw decision"

        static_bucket = str(row.get("static_bucket", "") or "")
        if static_bucket == "static_breathing_watch":
            final_assessment = "watch_breathing"
            final_reason = "raw static score looks positive-like, but segment pipeline marks it as a sealed hard case"
        elif static_bucket == "static_heatoff_confound_challenge":
            final_assessment = "watch_confound"
            final_reason = "segment enters the no-heat battlefield after heat-off and should not be treated as a clean static positive"
        elif static_bucket == "static_positive_eval_only":
            final_assessment = "review_weak_positive"
            final_reason = "segment carries positive label but remains weak on the current static baseline"
        elif static_bucket == "static_positive_reference":
            final_assessment = "confirmed_positive_reference"
            final_reason = "segment is a clean post-change positive reference for segment-level static modeling"
        elif static_bucket == "static_negative_reference":
            final_assessment = "confirmed_negative_reference"
            final_reason = "segment is a clean negative reference for segment-level static modeling"

        rows.append(
            {
                "segment_id": row["segment_id"],
                "run_id": row["run_id"],
                "segment_name": row["segment_name"],
                "segment_source": row["segment_source"],
                "segment_seal_state": row["segment_seal_state"],
                "static_bucket": static_bucket,
                "recommended_use": row["recommended_use"],
                "primary_task": row.get("primary_task", ""),
                "secondary_tasks": row.get("secondary_tasks", ""),
                **score,
                "final_assessment_v1": final_assessment,
                "final_reason_v1": final_reason,
            }
        )
    return pd.DataFrame(rows).sort_values(["final_assessment_v1", "run_id", "segment_name"]).reset_index(drop=True)


def build_summary(reference_eval: Dict[str, Any], pred_df: pd.DataFrame) -> Dict[str, Any]:
    return {
        "reference_count": int(len(reference_eval["apparent_df"])),
        "apparent_coverage": reference_eval["apparent_coverage"],
        "apparent_precision_on_resolved": reference_eval["apparent_precision_on_resolved"],
        "loo_coverage": reference_eval["loo_coverage"],
        "loo_precision_on_resolved": reference_eval["loo_precision_on_resolved"],
        "raw_label_counts": pred_df["raw_label_v1"].value_counts(dropna=False).to_dict(),
        "final_assessment_counts": pred_df["final_assessment_v1"].value_counts(dropna=False).to_dict(),
        "watch_like_count": int(pred_df["final_assessment_v1"].isin(["watch_breathing", "watch_confound", "review_weak_positive"]).sum()),
    }


def write_markdown(
    path: str,
    summary: Dict[str, Any],
    ref_eval: Dict[str, Any],
    pred_df: pd.DataFrame,
) -> None:
    lines = [
        "# 新补充数据 段级静态基线 v1 报告",
        "",
        "## 核心结论",
        "",
        f"- reference_count: `{summary['reference_count']}`",
        f"- apparent_coverage: `{summary['apparent_coverage']}`",
        f"- apparent_precision_on_resolved: `{summary['apparent_precision_on_resolved']}`",
        f"- loo_coverage: `{summary['loo_coverage']}`",
        f"- loo_precision_on_resolved: `{summary['loo_precision_on_resolved']}`",
        f"- raw_label_counts: `{summary['raw_label_counts']}`",
        f"- final_assessment_counts: `{summary['final_assessment_counts']}`",
        "",
        "## 当前判断",
        "",
        "- 这版 `segment-level static baseline v1` 不是新的主模型，而是用 `5` 个干净静态参考段形成一个严格受控的段级静态评分器。",
        "- 它的目标不是替代当前 `transition + evidence fuser` 主线，而是回答：新数据切成段以后，主战场静态段能不能形成一个最小可用的段级静态参考池。",
        "- 当前结果表明：可以形成参考池，但仍然需要 `watch / challenge` 层来压住 sealed 难例和 heat-off 混淆段。",
        "",
        "## 参考段自检",
        "",
        "- apparent 结果按全参考池计算；leave-one-reference-out 结果用于看这 5 个参考段本身稳不稳。",
        "- 如果 `loo` 覆盖率不满，优先解释为“参考池仍小且边界段存在”，而不是立即上更复杂模型。",
        "",
        "### apparent reference results",
        "",
    ]

    for _, row in ref_eval["apparent_df"].iterrows():
        lines.append(
            f"- {row['segment_id']} | actual={row['actual_label']} | raw={row['raw_label_v1']} | "
            f"votes={int(row['static_vote_count_v1'])} | margin={row['prototype_margin_v1']:.3f} | "
            f"resolved={bool(row['resolved_v1'])} | correct={bool(row['correct_v1'])}"
        )

    lines.extend(
        [
            "",
            "### leave-one-reference-out results",
            "",
        ]
    )

    for _, row in ref_eval["loo_df"].iterrows():
        lines.append(
            f"- {row['segment_id']} | actual={row['actual_label']} | raw={row['raw_label_v1']} | "
            f"votes={int(row['static_vote_count_v1'])} | margin={row['prototype_margin_v1']:.3f} | "
            f"resolved={bool(row['resolved_v1'])} | correct={bool(row['correct_v1'])}"
        )

    lines.extend(
        [
            "",
            "## 全部主战场静态段结果",
            "",
        ]
    )

    for _, row in pred_df.iterrows():
        lines.append(
            f"- {row['segment_id']} | bucket={row['static_bucket']} | raw={row['raw_label_v1']} | "
            f"final={row['final_assessment_v1']} | votes={int(row['static_vote_count_v1'])} | "
            f"margin={row['prototype_margin_v1']:.3f} | reason={row['final_reason_v1']}"
        )

    lines.extend(
        [
            "",
            "## 结论",
            "",
            "1. 当前新数据已经足够形成第一版段级静态参考池，但这个参考池仍然很小，不能直接重启 whole-run 分类器。",
            "2. `breathing_watch` 段会被纯静态基线打成正样本倾向，说明 `watch / abstain` 仍然是必须保留的主线机制。",
            "3. `weak positive` 段当前仍可能落到负样本一侧，说明静态主线还不能替代 transition 主线，只能补充主战场的强静态段。",
            "4. 下一步如果继续建模，应直接在这批段级参考上做段级 baseline，对照 challenge 段，而不是把新数据退回 whole-run 训练。",
            "",
        ]
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    static_df = pd.read_csv(args.static_candidates_csv)
    manifest_df = pd.read_csv(args.segment_manifest_csv)
    ref_df = static_df[static_df["recommended_use"] == "train_eval_primary"].copy().reset_index(drop=True)

    ref_eval = evaluate_reference_pool(ref_df, args)
    pred_df = build_prediction_table(static_df, manifest_df, ref_eval["reference_model"], args)
    summary = build_summary(ref_eval, pred_df)

    outputs = {
        "predictions_csv": os.path.join(args.output_dir, "segment_static_baseline_predictions.csv"),
        "apparent_refs_csv": os.path.join(args.output_dir, "segment_static_baseline_reference_apparent.csv"),
        "loo_refs_csv": os.path.join(args.output_dir, "segment_static_baseline_reference_loo.csv"),
        "report_md": os.path.join(args.output_dir, "segment_static_baseline_report.md"),
        "report_json": os.path.join(args.output_dir, "segment_static_baseline_report.json"),
    }

    pred_df.to_csv(outputs["predictions_csv"], index=False, encoding="utf-8-sig")
    ref_eval["apparent_df"].to_csv(outputs["apparent_refs_csv"], index=False, encoding="utf-8-sig")
    ref_eval["loo_df"].to_csv(outputs["loo_refs_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["report_md"], summary, ref_eval, pred_df)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
