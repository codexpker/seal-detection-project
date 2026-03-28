#!/usr/bin/env python3
import argparse
import json
import os
import sys
import tempfile
import zipfile
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.anomaly_v2 import condition_classifier_v1 as cc
from src.scripts.lab_ext_high_humidity_no_heat_probe_v3 import summarize_phase
from src.scripts.lab_phase1_acceptance import auc_pairwise, compute_run_features
from src.scripts.new_data_multiview_feature_mining_v2 import (
    ARTIFACT_LIKE_FEATURES,
    dew_point_c,
    ingress_regression,
    lagged_corr,
    safe_corr,
    summarize_generic_phase,
    vapor_pressure_deficit_kpa,
)
from src.scripts.old_data_interference_analysis import infer_path_label, infer_subgroup, lag_response_features


OLD_DATA_ZIPS = [
    "data/old_data/sealed.zip",
    "data/old_data/unsealed.zip",
]

SUPPORT_SCORE_COLUMNS = {
    "weak_positive_support_score_v2",
    "breathing_suppression_score_v2",
    "confound_reject_score_v2",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reassess old_data under the updated mainfield feature space")
    parser.add_argument(
        "--current-inventory-csv",
        default="reports/new_data_segment_post_feedback_reanalysis_v1_run1/post_feedback_segment_inventory.csv",
    )
    parser.add_argument(
        "--current-ranking-csv",
        default="reports/new_data_segment_post_feedback_reanalysis_v1_run1/post_feedback_feature_ranking.csv",
    )
    parser.add_argument("--output-dir", default="reports/old_data_reassessment_v2_run1")
    parser.add_argument("--top-k", type=int, default=8)
    return parser.parse_args()


def quantile_span(series: pd.Series, q_low: float = 0.10, q_high: float = 0.90) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return np.nan
    return float(values.quantile(q_high) - values.quantile(q_low))


def hourly_feature_table(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    hourly = (
        df.set_index("time")
        .resample("1h")
        .mean(numeric_only=True)
        .interpolate(limit_direction="both")
        .reset_index()
    )
    hourly["headroom_ah"] = pd.to_numeric(hourly["AH_out"], errors="coerce") - pd.to_numeric(hourly["AH_in"], errors="coerce")
    hourly["d_out_h"] = pd.to_numeric(hourly["out_hum"], errors="coerce").diff()
    hourly["d_in_h"] = pd.to_numeric(hourly["in_hum"], errors="coerce").diff()
    hourly["d_ah_in"] = pd.to_numeric(hourly["AH_in"], errors="coerce").diff()
    hourly["dew_in"] = dew_point_c(hourly["in_temp"], hourly["in_hum"])
    hourly["dew_out"] = dew_point_c(hourly["out_temp"], hourly["out_hum"])
    hourly["dew_gap"] = pd.to_numeric(hourly["dew_out"], errors="coerce") - pd.to_numeric(hourly["dew_in"], errors="coerce")
    hourly["d_dew_out"] = pd.to_numeric(hourly["dew_out"], errors="coerce").diff()
    hourly["d_dew_in"] = pd.to_numeric(hourly["dew_in"], errors="coerce").diff()
    hourly["vpd_in"] = vapor_pressure_deficit_kpa(hourly["in_temp"], hourly["in_hum"])
    hourly["vpd_out"] = vapor_pressure_deficit_kpa(hourly["out_temp"], hourly["out_hum"])
    hourly["vpd_gap"] = pd.to_numeric(hourly["vpd_out"], errors="coerce") - pd.to_numeric(hourly["vpd_in"], errors="coerce")

    early_stats = summarize_phase(hourly.iloc[:6].copy())
    late_stats = summarize_phase(hourly.iloc[-6:].copy())
    early_dew = summarize_generic_phase(hourly.iloc[:6].copy(), "dew_out", "dew_in", "d_dew_in")
    late_dew = summarize_generic_phase(hourly.iloc[-6:].copy(), "dew_out", "dew_in", "d_dew_in")

    max_corr_level_hum, best_lag_level_hum = lagged_corr(hourly["out_hum"], hourly["in_hum"])
    max_corr_level_ah, best_lag_level_ah = lagged_corr(hourly["AH_out"], hourly["AH_in"])
    max_corr_level_dew, best_lag_level_dew = lagged_corr(hourly["dew_out"], hourly["dew_in"])
    max_corr_dew_change, best_lag_dew_h = lagged_corr(hourly["d_dew_out"], hourly["d_dew_in"])

    positive_headroom = hourly["headroom_ah"] > 0
    positive_drive = hourly["d_out_h"] > 0
    positive_dew_gap = hourly["dew_gap"] > 0.05
    headroom_area = float(np.trapezoid(hourly["headroom_ah"].clip(lower=0.0), dx=1))
    dew_gap_area = float(np.trapezoid(hourly["dew_gap"].clip(lower=0.0), dx=1))
    ah_gain = float(hourly["AH_in"].iloc[-1] - hourly["AH_in"].iloc[0])

    ah_proxy = ingress_regression(hourly["headroom_ah"], hourly["d_ah_in"], min_drive=0.05)
    dew_proxy = ingress_regression(hourly["dew_gap"], hourly["d_dew_in"], min_drive=0.05)
    dynamic_feat = lag_response_features(df)
    run_feat = compute_run_features(df)

    row: Dict[str, Any] = {
        "duration_h": run_feat["duration_h"],
        "mean_dT": run_feat["mean_dT"],
        "mean_dAH": run_feat["mean_dAH"],
        "delta_half_in_h": run_feat["delta_half_in_h"],
        "delta_half_dAH": run_feat["delta_half_dAH"],
        "slope_in_h_per_h": run_feat["slope_in_h_per_h"],
        "slope_dAH_per_h": run_feat["slope_dAH_per_h"],
        "end_start_dAH": run_feat["end_start_dAH"],
        "std_in_hum_run": float(df["in_hum"].std()),
        "std_AH_in_run": float(df["AH_in"].std()),
        "amp_in_hum_p90_p10": quantile_span(df["in_hum"]),
        "amp_AH_in_p90_p10": quantile_span(df["AH_in"]),
        "amp_headroom_p90_p10": quantile_span(hourly["headroom_ah"]),
        "corr_out_hum_in_hum": safe_corr(df["out_hum"], df["in_hum"]),
        "corr_out_AH_in_AH": safe_corr(df["AH_out"], df["AH_in"]),
        "corr_headroom_in_hum": safe_corr(hourly["headroom_ah"], hourly["in_hum"]),
        "corr_headroom_AH_in": safe_corr(hourly["headroom_ah"], hourly["AH_in"]),
        "max_corr_dAH_change": dynamic_feat["max_corr_dAH_change"],
        "best_lag_h": dynamic_feat["best_lag_h"],
        "gain_ratio_dAH_change": dynamic_feat["gain_ratio_dAH_change"],
        "max_corr_outRH_inRH_change": dynamic_feat["max_corr_outRH_inRH_change"],
        "best_lag_rh_h": dynamic_feat["best_lag_rh_h"],
        "max_corr_level_hum": max_corr_level_hum,
        "best_lag_level_hum": best_lag_level_hum,
        "max_corr_level_ah": max_corr_level_ah,
        "best_lag_level_ah": best_lag_level_ah,
        "positive_headroom_ratio": float(positive_headroom.mean()),
        "positive_drive_ratio": float(positive_drive.mean()),
        "positive_response_ratio": float((hourly.loc[positive_drive, "d_in_h"] > 0).mean()) if positive_drive.any() else np.nan,
        "positive_ah_response_ratio": float((hourly.loc[positive_drive, "d_ah_in"] > 0).mean()) if positive_drive.any() else np.nan,
        "headroom_area_pos": headroom_area,
        "headroom_gain_ratio": float(ah_gain / max(headroom_area, 1e-6)),
        "early_resp_ratio": early_stats["respond_in_h_pos_ratio"],
        "early_ah_resp_ratio": early_stats["respond_ah_pos_ratio"],
        "early_rh_gain_per_out": early_stats["rh_gain_per_out"],
        "late_resp_ratio": late_stats["respond_in_h_pos_ratio"],
        "late_ah_resp_ratio": late_stats["respond_ah_pos_ratio"],
        "late_rh_gain_per_out": late_stats["rh_gain_per_out"],
        "late_ah_decay_per_headroom": late_stats["ah_decay_per_headroom"],
        "late_minus_early_rh_gain": (
            late_stats["rh_gain_per_out"] - early_stats["rh_gain_per_out"]
            if pd.notna(late_stats["rh_gain_per_out"]) and pd.notna(early_stats["rh_gain_per_out"])
            else np.nan
        ),
        "late_minus_early_resp_ratio": (
            late_stats["respond_in_h_pos_ratio"] - early_stats["respond_in_h_pos_ratio"]
            if pd.notna(late_stats["respond_in_h_pos_ratio"]) and pd.notna(early_stats["respond_in_h_pos_ratio"])
            else np.nan
        ),
        "dew_gap_mean": float(hourly["dew_gap"].mean()),
        "dew_gap_q90": float(hourly["dew_gap"].quantile(0.90)),
        "dew_gap_area_pos": dew_gap_area,
        "dew_gap_pos_ratio": float(positive_dew_gap.mean()),
        "amp_dew_in_p90_p10": quantile_span(hourly["dew_in"]),
        "std_dew_in_run": float(hourly["dew_in"].std()),
        "corr_out_dew_in_dew": safe_corr(hourly["dew_out"], hourly["dew_in"]),
        "corr_dew_gap_in_dew": safe_corr(hourly["dew_gap"], hourly["dew_in"]),
        "max_corr_dew_change": max_corr_dew_change,
        "best_lag_dew_h": best_lag_dew_h,
        "max_corr_level_dew": max_corr_level_dew,
        "best_lag_level_dew": best_lag_level_dew,
        "early_dew_gain_per_out": early_dew["gain_per_drive"],
        "late_dew_gain_per_out": late_dew["gain_per_drive"],
        "late_minus_early_dew_gain": (
            late_dew["gain_per_drive"] - early_dew["gain_per_drive"]
            if pd.notna(late_dew["gain_per_drive"]) and pd.notna(early_dew["gain_per_drive"])
            else np.nan
        ),
        "dew_headroom_capture_ratio": dew_proxy["capture_ratio"],
        "ah_gap_q90": float(hourly["headroom_ah"].quantile(0.90)),
        "ah_gap_area_pos": headroom_area,
        "ah_ingress_slope": ah_proxy["slope"],
        "ah_ingress_r2": ah_proxy["r2"],
        "ah_ingress_count": ah_proxy["count"],
        "ah_pos_gain_per_area": ah_proxy["pos_gain_per_area"],
        "ah_neg_response_ratio": ah_proxy["neg_response_ratio"],
        "dew_ingress_slope": dew_proxy["slope"],
        "dew_ingress_r2": dew_proxy["r2"],
        "dew_ingress_count": dew_proxy["count"],
        "dew_pos_gain_per_area": dew_proxy["pos_gain_per_area"],
        "dew_neg_response_ratio": dew_proxy["neg_response_ratio"],
        "vpd_in_mean": float(df.assign(vpd_in=vapor_pressure_deficit_kpa(df["in_temp"], df["in_hum"]))["vpd_in"].mean()),
        "vpd_gap_mean": float((vapor_pressure_deficit_kpa(df["out_temp"], df["out_hum"]) - vapor_pressure_deficit_kpa(df["in_temp"], df["in_hum"])).mean()),
        "late_minus_early_vpd_gap": float(hourly["vpd_gap"].iloc[-6:].mean() - hourly["vpd_gap"].iloc[:6].mean())
        if len(hourly) >= 6
        else np.nan,
    }
    return hourly, row


def build_old_feature_table() -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for zip_path in OLD_DATA_ZIPS:
        with zipfile.ZipFile(zip_path) as zf, tempfile.TemporaryDirectory(prefix="old_reassess_") as tmp_dir:
            for inner_name in zf.namelist():
                if not inner_name.lower().endswith(".xlsx"):
                    continue
                target = os.path.join(tmp_dir, os.path.basename(inner_name))
                with zf.open(inner_name) as src, open(target, "wb") as out:
                    out.write(src.read())
                try:
                    sheets = cc.load_excel_sheets(target)
                except Exception:
                    continue
                for sheet_name, raw_df in sheets:
                    try:
                        df = cc.preprocess_df(raw_df)
                    except Exception:
                        continue
                    if df.empty:
                        continue
                    _, feat_row = hourly_feature_table(df)
                    feat_row.update(
                        {
                            "archive": os.path.basename(zip_path),
                            "inner_path": inner_name,
                            "path_label": infer_path_label(inner_name),
                            "subgroup": infer_subgroup(inner_name),
                            "file": os.path.basename(inner_name).rsplit(".", 1)[0],
                            "sheet": sheet_name,
                        }
                    )
                    rows.append(feat_row)
                    break
    return pd.DataFrame(rows).sort_values(["subgroup", "file"]).reset_index(drop=True)


def choose_common_features(current_inventory: pd.DataFrame, ranking_df: pd.DataFrame, old_df: pd.DataFrame, top_k: int) -> List[str]:
    candidates: List[str] = []
    for feat in ranking_df["feature"].tolist():
        if feat in ARTIFACT_LIKE_FEATURES or feat in SUPPORT_SCORE_COLUMNS:
            continue
        if feat not in current_inventory.columns or feat not in old_df.columns:
            continue
        if not pd.api.types.is_numeric_dtype(current_inventory[feat]) or not pd.api.types.is_numeric_dtype(old_df[feat]):
            continue
        candidates.append(feat)
        if len(candidates) >= top_k:
            break
    return candidates


def build_reference_maps(current_inventory: pd.DataFrame, ranking_df: pd.DataFrame, features: List[str]) -> Tuple[Dict[str, Dict[str, float]], pd.Series, pd.Series, pd.DataFrame]:
    positive_roles = {"positive_reference", "transition_positive"}
    refs = current_inventory[current_inventory["provisional_role_v1"].isin(positive_roles | {"negative_reference"})].copy()
    mapping: Dict[str, Dict[str, float]] = {}
    for feat in features:
        row = ranking_df[ranking_df["feature"] == feat]
        if row.empty:
            continue
        rr = row.iloc[0]
        mapping[feat] = {
            "direction": str(rr["direction"]),
            "positive_median": float(rr["positive_median"]),
            "negative_median": float(rr["negative_median"]),
        }
    stats = refs[features].agg(["median", "std"]).T
    stats["std"] = stats["std"].replace(0, np.nan).fillna(1.0)
    scaled = refs[["segment_id", "provisional_role_v1"] + features].copy()
    for feat in features:
        scaled[feat] = (pd.to_numeric(scaled[feat], errors="coerce") - stats.loc[feat, "median"]) / stats.loc[feat, "std"]
    pos_centroid = scaled[scaled["provisional_role_v1"].isin(positive_roles)][features].mean(numeric_only=True)
    neg_centroid = scaled[scaled["provisional_role_v1"] == "negative_reference"][features].mean(numeric_only=True)
    return mapping, pos_centroid, neg_centroid, stats.reset_index().rename(columns={"index": "feature"})


def compute_old_projection(
    old_df: pd.DataFrame,
    feature_map: Dict[str, Dict[str, float]],
    pos_centroid: pd.Series,
    neg_centroid: pd.Series,
    stats_df: pd.DataFrame,
) -> pd.DataFrame:
    stats_map = stats_df.set_index("feature")[["median", "std"]].to_dict(orient="index")
    features = list(feature_map.keys())
    rows: List[Dict[str, Any]] = []
    for _, row in old_df.iterrows():
        toward_positive = 0
        toward_negative = 0
        valid_votes = 0
        scaled_vec: Dict[str, float] = {}
        for feat in features:
            val = pd.to_numeric(pd.Series([row.get(feat)]), errors="coerce").iloc[0]
            if pd.isna(val):
                scaled_vec[feat] = np.nan
                continue
            info = feature_map[feat]
            is_positive_side = float(val) >= info["positive_median"] if info["direction"] == "pos" else float(val) <= info["positive_median"]
            toward_positive += int(is_positive_side)
            toward_negative += int(not is_positive_side)
            valid_votes += 1
            scaled_vec[feat] = float((val - stats_map[feat]["median"]) / stats_map[feat]["std"])

        vec = pd.Series(scaled_vec)
        valid = vec.notna() & pos_centroid.notna() & neg_centroid.notna()
        if int(valid.sum()) == 0:
            d_pos = np.nan
            d_neg = np.nan
        else:
            d_pos = float(np.linalg.norm(vec[valid] - pos_centroid[valid]))
            d_neg = float(np.linalg.norm(vec[valid] - neg_centroid[valid]))

        vote_ratio = float(toward_positive / valid_votes) if valid_votes else np.nan
        margin = (d_neg - d_pos) if pd.notna(d_pos) and pd.notna(d_neg) else np.nan
        if pd.notna(vote_ratio) and pd.notna(margin) and vote_ratio >= 0.625 and margin > 0:
            projection = "old_positive_like"
        elif pd.notna(vote_ratio) and pd.notna(margin) and vote_ratio <= 0.375 and margin < 0:
            projection = "old_negative_like"
        else:
            projection = "old_ambiguous"

        out = {
            "archive": row["archive"],
            "inner_path": row["inner_path"],
            "subgroup": row["subgroup"],
            "file": row["file"],
            "sheet": row["sheet"],
            "positive_vote_ratio": vote_ratio,
            "distance_to_positive_centroid": d_pos,
            "distance_to_negative_centroid": d_neg,
            "margin_positive_minus_negative": margin,
            "projection_status_v2": projection,
        }
        for feat in features:
            out[f"{feat}__value"] = row.get(feat, np.nan)
        rows.append(out)
    return pd.DataFrame(rows).sort_values(
        ["subgroup", "projection_status_v2", "margin_positive_minus_negative", "positive_vote_ratio"],
        ascending=[True, True, False, False],
    ).reset_index(drop=True)


def rank_old_against_subgroups(old_df: pd.DataFrame, features: List[str]) -> pd.DataFrame:
    subset = old_df[old_df["subgroup"].isin(["unsealed", "sealed_strict"])].copy()
    if subset.empty:
        return pd.DataFrame()
    rows: List[Dict[str, Any]] = []
    for feat in features:
        values = pd.to_numeric(subset[feat], errors="coerce")
        valid = values.notna()
        if int(valid.sum()) < 6:
            continue
        labels = subset.loc[valid, "subgroup"].eq("unsealed").astype(int).tolist()
        auc_pos = auc_pairwise(values.loc[valid].astype(float).tolist(), labels) or 0.0
        auc_neg = auc_pairwise((-values.loc[valid]).astype(float).tolist(), labels) or 0.0
        rows.append(
            {
                "feature": feat,
                "auc_unsealed_vs_strict": float(max(auc_pos, auc_neg)),
                "direction": "pos" if auc_pos >= auc_neg else "neg",
                "strict_median": float(pd.to_numeric(subset.loc[(subset["subgroup"] == "sealed_strict") & valid, feat], errors="coerce").median()),
                "unsealed_median": float(pd.to_numeric(subset.loc[(subset["subgroup"] == "unsealed") & valid, feat], errors="coerce").median()),
            }
        )
    return pd.DataFrame(rows).sort_values(["auc_unsealed_vs_strict", "feature"], ascending=[False, True]).reset_index(drop=True)


def build_summary(projection_df: pd.DataFrame, old_rank_df: pd.DataFrame, selected_features: List[str]) -> Dict[str, Any]:
    subgroup_proj = (
        projection_df.groupby(["subgroup", "projection_status_v2"]).size().unstack(fill_value=0).to_dict(orient="index")
        if not projection_df.empty
        else {}
    )
    strict_confusing = projection_df[
        (projection_df["subgroup"] == "sealed_strict") & (projection_df["projection_status_v2"] == "old_positive_like")
    ].copy()
    return {
        "old_run_count": int(len(projection_df)),
        "selected_features": selected_features,
        "subgroup_projection_counts": subgroup_proj,
        "strict_positive_like_count_v2": int(len(strict_confusing)),
        "strict_positive_like_top": strict_confusing.head(10)[
            ["file", "positive_vote_ratio", "margin_positive_minus_negative"]
        ].to_dict(orient="records"),
        "old_unsealed_vs_strict_top_features": old_rank_df.head(10).to_dict(orient="records"),
    }


def write_markdown(path: str, summary: Dict[str, Any], projection_df: pd.DataFrame) -> None:
    lines = [
        "# 历史旧数据在当前主战场特征空间下的重评估 v2",
        "",
        f"- old_run_count: `{summary['old_run_count']}`",
        f"- selected_features: `{summary['selected_features']}`",
        f"- subgroup_projection_counts: `{summary['subgroup_projection_counts']}`",
        f"- strict_positive_like_count_v2: `{summary['strict_positive_like_count_v2']}`",
        "",
        "## 当前判断",
        "",
        "- 这一步不是把旧数据重新并入主训练，而是检查：在当前已经确认过的主战场特征空间里，旧数据会不会继续污染主战场。",
        "- 评估方式不是重新训 whole-run 分类器，而是把旧数据直接投到“当前正/负参考池”的结构特征空间里，看它更靠近哪一侧。",
        "",
        "## 当前采用的主战场特征",
        "",
    ]
    for feat in summary["selected_features"]:
        lines.append(f"- {feat}")

    lines.extend(["", "## old_data 内部 unsealed vs strict sealed 仍然最有价值的特征", ""])
    for item in summary["old_unsealed_vs_strict_top_features"]:
        lines.append(
            f"- {item['feature']} | auc={item['auc_unsealed_vs_strict']:.3f} | direction={item['direction']} | "
            f"strict_median={item['strict_median']:.3f} | unsealed_median={item['unsealed_median']:.3f}"
        )

    lines.extend(["", "## 仍然最危险的 strict sealed 运行", ""])
    for item in summary["strict_positive_like_top"]:
        lines.append(
            f"- {item['file']} | positive_vote_ratio={item['positive_vote_ratio']:.3f} | margin={item['margin_positive_minus_negative']:.3f}"
        )
    if not summary["strict_positive_like_top"]:
        lines.append("- 无")

    lines.extend(["", "## 结论", ""])
    lines.extend(
        [
            "1. 旧数据值得重新评估，但重新评估的结果如果仍显示存在一批 `strict sealed` 会落到正侧，就说明它依旧不该并入主训练集。",
            "2. 如果某些新增结构特征能把 `strict sealed` 压回负侧，它们就更适合接入 `watch / confound suppress`，而不是直接拿来重开统一分类器。",
            "3. 因此这一步真正回答的是“旧数据在当前主战场里扮演什么角色”，而不是“旧数据能不能立刻拿来扩监督样本”。",
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
    old_df = build_old_feature_table()
    selected_features = choose_common_features(current_inventory, ranking_df, old_df, args.top_k)
    feature_map, pos_centroid, neg_centroid, stats_df = build_reference_maps(current_inventory, ranking_df, selected_features)
    projection_df = compute_old_projection(old_df, feature_map, pos_centroid, neg_centroid, stats_df)
    old_rank_df = rank_old_against_subgroups(old_df, selected_features)
    summary = build_summary(projection_df, old_rank_df, selected_features)

    outputs = {
        "old_feature_table_csv": os.path.join(args.output_dir, "old_data_feature_table_v2.csv"),
        "projection_csv": os.path.join(args.output_dir, "old_data_projection_v2.csv"),
        "old_rank_csv": os.path.join(args.output_dir, "old_data_feature_ranking_v2.csv"),
        "report_md": os.path.join(args.output_dir, "old_data_reassessment_report_v2.md"),
        "report_json": os.path.join(args.output_dir, "old_data_reassessment_report_v2.json"),
    }

    old_df.to_csv(outputs["old_feature_table_csv"], index=False, encoding="utf-8-sig")
    projection_df.to_csv(outputs["projection_csv"], index=False, encoding="utf-8-sig")
    old_rank_df.to_csv(outputs["old_rank_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["report_md"], summary, projection_df)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
