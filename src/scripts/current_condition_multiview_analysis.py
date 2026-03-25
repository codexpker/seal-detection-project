#!/usr/bin/env python3
import argparse
import json
import os
import sys
import tempfile
from typing import Any, Dict, List

import numpy as np
import pandas as pd

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.anomaly_v2 import condition_classifier_v1 as cc
from src.scripts.lab_gate_info_selector_v2 import assign_routes, build_views
from src.scripts.lab_phase1_acceptance import (
    Phase1Config,
    auc_pairwise,
    compute_run_features,
    infer_heat_source,
    infer_seal_label,
)
from src.scripts.old_data_interference_analysis import lag_response_features


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Current condition data multiview analysis")
    parser.add_argument("--input-dir", default=Phase1Config.input_dir)
    parser.add_argument("--input-zip", default=Phase1Config.input_zip)
    parser.add_argument("--metadata-xlsx", default=Phase1Config.metadata_xlsx)
    parser.add_argument("--output-dir", default="reports/current_condition_multiview_analysis")
    parser.add_argument("--window-hours", type=int, default=12)
    parser.add_argument("--step-hours", type=int, default=1)
    parser.add_argument("--transition-near-hours", type=int, default=6)
    return parser.parse_args()


def safe_corr(a: pd.Series, b: pd.Series) -> float:
    if len(a) < 3:
        return np.nan
    value = np.corrcoef(a.astype(float), b.astype(float))[0, 1]
    return float(value) if not np.isnan(value) else np.nan


def quantile_span(series: pd.Series, q_low: float = 0.05, q_high: float = 0.95) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return np.nan
    return float(values.quantile(q_high) - values.quantile(q_low))


def infer_analysis_group(file_name: str, expected_family: str, seal_label: str, heat_source: str, static_file_set: set[str]) -> str:
    if file_name in static_file_set and seal_label in {"seal", "unseal"}:
        return f"current_static_{seal_label}"
    if expected_family == "transition_run":
        return "current_transition"
    if heat_source == "有":
        return "current_heat_related"
    if expected_family in {"balanced_no_heat", "balanced_with_heat", "internal_moist_no_heat", "internal_moist_with_heat"}:
        return "current_control_or_lowinfo"
    return "current_other"


def build_run_table(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    window_df, file_df = build_views(args)
    routed_df, static_route_df = assign_routes(window_df, file_df)
    static_file_set = set(static_route_df["file"].dropna().tolist())

    metadata_df = cc.load_metadata_manifest(args.metadata_xlsx)
    metadata_map = {row["data_file_name"]: row.to_dict() for _, row in metadata_df.iterrows()}

    route_role_share = (
        routed_df.groupby(["file", "route_role"]).size().unstack(fill_value=0)
        if not routed_df.empty
        else pd.DataFrame()
    )
    route_branch_share = (
        routed_df.groupby(["file", "route_branch"]).size().unstack(fill_value=0)
        if not routed_df.empty
        else pd.DataFrame()
    )
    if not route_role_share.empty:
        route_role_share = route_role_share.div(route_role_share.sum(axis=1), axis=0)
    if not route_branch_share.empty:
        route_branch_share = route_branch_share.div(route_branch_share.sum(axis=1), axis=0)

    rows: List[Dict[str, Any]] = []
    cfg = cc.Config(
        input_dir=args.input_dir,
        input_zip=args.input_zip,
        metadata_xlsx=args.metadata_xlsx,
        output_dir=args.output_dir,
        window_hours=args.window_hours,
        step_hours=args.step_hours,
    )

    with tempfile.TemporaryDirectory(prefix="current_multiview_") as tmp_dir:
        files = cc.collect_input_files(cfg, tmp_dir)
        for file_path in files:
            file_name = cc.normalize_filename_token(os.path.basename(file_path))
            meta_row = dict(metadata_map.get(file_name, {}))
            expected_family = cc.expected_family_from_manifest(meta_row)
            seal_label = infer_seal_label(meta_row, file_name)
            heat_source = infer_heat_source(meta_row, file_name)
            analysis_group = infer_analysis_group(file_name, expected_family, seal_label, heat_source, static_file_set)

            sheets = cc.load_excel_sheets(file_path)
            for sheet_name, raw_df in sheets:
                try:
                    df = cc.preprocess_df(raw_df)
                except Exception:
                    continue
                if df.empty:
                    continue

                run_feat = compute_run_features(df)
                dynamic_feat = lag_response_features(df)

                win = window_df[(window_df["file"] == file_name) & (window_df["sheet"] == sheet_name)].copy()
                static_win = static_route_df[(static_route_df["file"] == file_name) & (static_route_df["sheet"] == sheet_name)].copy()
                if not static_win.empty:
                    static_threshold_ratio = float((static_win["route_branch"] == "static_threshold_branch").mean())
                    top3_info_mean = float(static_win["info_score_v2"].sort_values(ascending=False).head(3).mean())
                else:
                    static_threshold_ratio = np.nan
                    top3_info_mean = np.nan

                route_role_row = route_role_share.loc[file_name] if file_name in route_role_share.index else pd.Series(dtype=float)
                route_branch_row = route_branch_share.loc[file_name] if file_name in route_branch_share.index else pd.Series(dtype=float)

                std_in_hum = float(df["in_hum"].std())
                std_ah_in = float(df["AH_in"].std())

                row = {
                    "file": file_name,
                    "sheet": sheet_name,
                    "analysis_group": analysis_group,
                    "expected_family": expected_family,
                    "seal_label": seal_label,
                    "heat_source_inferred": heat_source,
                    "duration_h": float(run_feat["duration_h"]),
                    "mean_out_h": float(run_feat["mean_out_h"]),
                    "mean_dT": float(run_feat["mean_dT"]),
                    "mean_dAH": float(run_feat["mean_dAH"]),
                    "mean_dH": float(run_feat["mean_dH"]),
                    "delta_end_in_h": float(run_feat["delta_end_in_h"]),
                    "delta_half_in_h": float(run_feat["delta_half_in_h"]),
                    "delta_half_dAH": float(run_feat["delta_half_dAH"]),
                    "slope_in_h_per_h": float(run_feat["slope_in_h_per_h"]),
                    "slope_dAH_per_h": float(run_feat["slope_dAH_per_h"]),
                    "end_start_dAH": float(run_feat["end_start_dAH"]),
                    "std_in_hum_run": std_in_hum,
                    "std_AH_in_run": std_ah_in,
                    "amp_in_hum_p95_p05": quantile_span(df["in_hum"]),
                    "amp_AH_in_p95_p05": quantile_span(df["AH_in"]),
                    "amp_dAH_p95_p05": quantile_span(df["dAH"]),
                    "rh_ah_ratio": float(std_in_hum / max(std_ah_in, 1e-6)),
                    "net_rh_drift_ratio": float(abs(run_feat["delta_end_in_h"]) / max(std_in_hum, 1e-6)),
                    "net_ah_drift_ratio": float(abs(run_feat["end_start_dAH"]) / max(std_ah_in, 1e-6)),
                    "corr_in_temp_in_hum": safe_corr(df["in_temp"], df["in_hum"]),
                    "corr_in_temp_AH_in": safe_corr(df["in_temp"], df["AH_in"]),
                    "corr_out_hum_in_hum": safe_corr(df["out_hum"], df["in_hum"]),
                    "corr_out_AH_in_AH": safe_corr(df["AH_out"], df["AH_in"]),
                    "dAH_positive_ratio": float((df["dAH"] > 0).mean()),
                    "out_hum_high_ratio_90": float((df["out_hum"] >= 90.0).mean()),
                    "in_hum_high_ratio_90": float((df["in_hum"] >= 90.0).mean()),
                    "candidate_high_info_ratio": float((win["predicted_group"] == "candidate_high_info").mean()) if not win.empty else np.nan,
                    "heat_related_ratio": float((win["predicted_group"] == "heat_related").mean()) if not win.empty else np.nan,
                    "exclude_low_info_ratio": float((win["predicted_group"] == "exclude_low_info").mean()) if not win.empty else np.nan,
                    "q90_delta_half_in_hum": float(win["delta_half_in_hum"].quantile(0.9)) if not win.empty else np.nan,
                    "q90_delta_half_dAH_w": float(win["delta_half_dAH"].quantile(0.9)) if not win.empty else np.nan,
                    "q90_slope_AH_in": float(win["slope_AH_in"].quantile(0.9)) if not win.empty else np.nan,
                    "q90_max_hourly_hum_rise": float(win["max_hourly_hum_rise"].quantile(0.9)) if not win.empty else np.nan,
                    "frac_pos_delta_half_dAH": float((win["delta_half_dAH"] > 0).mean()) if not win.empty else np.nan,
                    "top3_info_mean": top3_info_mean,
                    "frac_threshold_favored": static_threshold_ratio,
                    "route_transition_ratio": float(route_branch_row.get("transition_branch", np.nan)),
                    "route_static_threshold_ratio": float(route_branch_row.get("static_threshold_branch", np.nan)),
                    "route_static_memory_ratio": float(route_branch_row.get("static_memory_branch", np.nan)),
                    "route_background_ratio": float(route_role_row.get("background_high_hum", np.nan)),
                    "route_heat_reject_ratio": float(route_role_row.get("reject_heat_related", np.nan)),
                    **dynamic_feat,
                }
                rows.append(row)

    run_df = pd.DataFrame(rows).sort_values(["analysis_group", "file"]).reset_index(drop=True)
    return run_df, window_df, routed_df, static_route_df


def rank_features(df: pd.DataFrame, positive_group: str, negative_group: str, feature_groups: Dict[str, List[str]]) -> pd.DataFrame:
    subset = df[df["analysis_group"].isin([positive_group, negative_group])].copy()
    subset["label"] = (subset["analysis_group"] == positive_group).astype(int)

    rows: List[Dict[str, Any]] = []
    for category, features in feature_groups.items():
        for feature in features:
            scores = pd.to_numeric(subset[feature], errors="coerce")
            valid = scores.notna()
            if valid.sum() < 4:
                continue
            values = scores.loc[valid].astype(float).tolist()
            labels = subset.loc[valid, "label"].astype(int).tolist()
            auc_pos = auc_pairwise(values, labels) or 0.0
            auc_neg = auc_pairwise([-x for x in values], labels) or 0.0
            direction = "pos" if auc_pos >= auc_neg else "neg"
            seal_med = float(subset.loc[(subset["analysis_group"] == negative_group) & valid, feature].median())
            unseal_med = float(subset.loc[(subset["analysis_group"] == positive_group) & valid, feature].median())
            rows.append(
                {
                    "category": category,
                    "feature": feature,
                    "auc": float(max(auc_pos, auc_neg)),
                    "direction": direction,
                    "seal_median": seal_med,
                    "unseal_median": unseal_med,
                }
            )
    return pd.DataFrame(rows).sort_values(["category", "auc"], ascending=[True, False]).reset_index(drop=True)


def analyze_hard_cases(static_df: pd.DataFrame) -> pd.DataFrame:
    core_features = [
        "max_corr_outRH_inRH_change",
        "q90_delta_half_dAH_w",
        "frac_threshold_favored",
        "frac_pos_delta_half_dAH",
        "best_lag_h",
        "q90_delta_half_in_hum",
    ]
    work = static_df[["file", "seal_label", *core_features]].copy()
    numeric = work[core_features].replace([np.inf, -np.inf], np.nan)
    numeric = numeric.fillna(numeric.median(numeric_only=True))
    scaled = (numeric - numeric.mean()) / numeric.std(ddof=0).replace(0.0, 1.0)

    rows: List[Dict[str, Any]] = []
    for idx, row in work.iterrows():
        dist_rows: List[tuple[float, str, str]] = []
        for jdx, other in work.iterrows():
            if idx == jdx:
                continue
            dist = float(np.sqrt(((scaled.loc[idx] - scaled.loc[jdx]) ** 2).sum()))
            dist_rows.append((dist, other["file"], other["seal_label"]))
        dist_rows.sort(key=lambda x: x[0])
        nearest_same = next((item for item in dist_rows if item[2] == row["seal_label"]), None)
        nearest_other = next((item for item in dist_rows if item[2] != row["seal_label"]), None)
        rows.append(
            {
                "file": row["file"],
                "seal_label": row["seal_label"],
                "nearest_same_file": nearest_same[1] if nearest_same else "",
                "nearest_same_distance": nearest_same[0] if nearest_same else np.nan,
                "nearest_other_file": nearest_other[1] if nearest_other else "",
                "nearest_other_distance": nearest_other[0] if nearest_other else np.nan,
                "cross_label_closer": bool(nearest_same and nearest_other and nearest_other[0] < nearest_same[0]),
            }
        )
    return pd.DataFrame(rows).sort_values(["cross_label_closer", "nearest_other_distance"], ascending=[False, True]).reset_index(drop=True)


def analyze_transition_lifts(window_df: pd.DataFrame) -> pd.DataFrame:
    trans = window_df[window_df["expected_family"] == "transition_run"].copy()
    features = [
        "delta_in_hum",
        "delta_half_in_hum",
        "max_hourly_hum_rise",
        "std_out_hum",
        "corr_AH",
        "slope_AH_in",
        "delta_half_dAH",
        "mean_dAH",
        "mean_out_hum",
        "q90_dummy",
    ]
    rows: List[Dict[str, Any]] = []
    for feature in features:
        if feature == "q90_dummy" or feature not in trans.columns:
            continue
        near = pd.to_numeric(trans.loc[trans["transition_phase"] == "near_transition", feature], errors="coerce").dropna()
        non = pd.to_numeric(trans.loc[trans["transition_phase"] != "near_transition", feature], errors="coerce").dropna()
        if near.empty or non.empty:
            continue
        rows.append(
            {
                "feature": feature,
                "near_mean": float(near.mean()),
                "non_near_mean": float(non.mean()),
                "diff": float(near.mean() - non.mean()),
            }
        )
    return pd.DataFrame(rows).sort_values("diff", ascending=False).reset_index(drop=True)


def summarize_correlations(static_df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "corr_in_temp_in_hum",
        "corr_in_temp_AH_in",
        "corr_out_hum_in_hum",
        "corr_out_AH_in_AH",
    ]
    summary = (
        static_df.groupby("seal_label")[cols]
        .median()
        .reset_index()
    )
    return summary


def build_report(run_df: pd.DataFrame, ranking_df: pd.DataFrame, hard_df: pd.DataFrame, transition_df: pd.DataFrame) -> Dict[str, Any]:
    static_df = run_df[run_df["analysis_group"].isin(["current_static_seal", "current_static_unseal"])].copy()
    group_counts = run_df["analysis_group"].value_counts().to_dict()
    hard_cases = hard_df[hard_df["cross_label_closer"]].copy()

    potential_features = ranking_df[
        ranking_df["feature"].isin(
            [
                "corr_out_hum_in_hum",
                "max_corr_outRH_inRH_change",
                "std_in_hum_run",
                "max_corr_dAH_change",
                "q90_delta_half_dAH_w",
                "frac_threshold_favored",
                "frac_pos_delta_half_dAH",
                "q90_delta_half_in_hum",
            ]
        )
    ].sort_values("auc", ascending=False)
    caution_features = ranking_df[
        ranking_df["feature"].isin(["mean_out_h", "candidate_high_info_ratio", "heat_related_ratio"])
    ].sort_values("auc", ascending=False)

    return {
        "total_runs": int(len(run_df)),
        "group_counts": group_counts,
        "static_runs": int(len(static_df)),
        "static_class_counts": static_df["seal_label"].value_counts().to_dict(),
        "potential_features": potential_features.to_dict(orient="records"),
        "caution_features": caution_features.to_dict(orient="records"),
        "hard_case_count": int(len(hard_cases)),
        "hard_cases": hard_cases.to_dict(orient="records"),
        "transition_top_features": transition_df.head(6).to_dict(orient="records"),
        "corr_summary": summarize_correlations(static_df).to_dict(orient="records"),
    }


def write_markdown(path: str, summary: Dict[str, Any], ranking_df: pd.DataFrame) -> None:
    lines = [
        "# 新工况数据多视角深入分析报告",
        "",
        f"- 总运行数：`{summary['total_runs']}`",
        f"- 分组分布：`{summary['group_counts']}`",
        f"- 静态候选运行数：`{summary['static_runs']}`",
        f"- 静态候选类别分布：`{summary['static_class_counts']}`",
        "",
        "## 为什么不能只画图和看 5 个信息",
        "",
        "- 当前数据里，相对湿度本身强烈混入了温度效应；只看 `Tin/Tout/Hin/Hout/AH` 的原始曲线，容易把温度驱动和水汽传递混在一起。",
        "- 有些真正有价值的线索并不在“绝对水平”，而在 `高分位窗口特征`、`动态响应相关性`、`路由后的持续性` 上。",
        "- 因此这一步不再只看曲线形态，而是同时看：静态运行级、动态响应、窗口分位数、路由持久性、转移邻域抬升。",
        "",
        "## 温度-湿度耦合中位数",
        "",
    ]

    corr_df = pd.DataFrame(summary["corr_summary"])
    if not corr_df.empty:
        lines.append(corr_df.to_markdown(index=False))
        lines.append("")

    lines.extend(
        [
            "## Static Seal vs Unseal：值得继续追的潜在线索",
            "",
        ]
    )
    for item in summary["potential_features"][:8]:
        lines.append(
            f"- {item['feature']} | auc={item['auc']:.3f} | direction={item['direction']} | "
            f"seal_median={item['seal_median']:.3f} | unseal_median={item['unseal_median']:.3f}"
        )

    lines.extend(
        [
            "",
            "## 需要谨慎看待的“伪区分”特征",
            "",
        ]
    )
    for item in summary["caution_features"][:6]:
        lines.append(
            f"- {item['feature']} | auc={item['auc']:.3f} | direction={item['direction']}"
        )
    lines.extend(
        [
            "- 这类特征更像实验条件差异或当前路由结果的投影，不能直接当成可迁移主特征。",
            "",
            "## 当前最关键的混淆样本",
            "",
        ]
    )
    for item in summary["hard_cases"][:6]:
        lines.append(
            f"- {item['file']} | label={item['seal_label']} | nearest_other={item['nearest_other_file']} | "
            f"nearest_other_distance={item['nearest_other_distance']:.3f} | cross_label_closer={item['cross_label_closer']}"
        )

    lines.extend(
        [
            "",
            "## Transition 邻域更强的特征",
            "",
        ]
    )
    for item in summary["transition_top_features"]:
        lines.append(
            f"- {item['feature']} | near_mean={item['near_mean']:.3f} | non_near_mean={item['non_near_mean']:.3f} | diff={item['diff']:.3f}"
        )

    lines.extend(
        [
            "",
            "## 结论",
            "",
            "- 当前新工况数据确实不止 5 个信息可看，真正值得继续追的方向至少有四类：`动态响应相关性`、`窗口高分位漂移特征`、`阈值 favored 持续性`、`转移邻域湿度抬升速度`。",
            "- 当前最值得继续做静态分支探索的不是 `mean_out_h` 这类容易受实验条件影响的量，而是：`corr_out_hum_in_hum`、`max_corr_outRH_inRH_change`、`q90_delta_half_dAH_w`、`frac_threshold_favored`、`frac_pos_delta_half_dAH`。",
            "- Transition 场景里，这批数据提示 `max_hourly_hum_rise` 和 `delta_in_hum` 可能比单纯 `delta_half_dAH` 更值得重视。",
            "- 当前仍存在明显难例，尤其是 `2026-03-06 160246_seal_unheated`，说明全局统一静态分类器仍然风险很高。",
            "- 因此下一步最合理的做法不是直接堆更复杂模型，而是把这些多视角特征接进现有 `watch / abstain / review` 框架里，先验证哪些能稳定改善难例处理。",
            "",
        ]
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    run_df, window_df, routed_df, static_route_df = build_run_table(args)
    static_feature_groups = {
        "dynamic_response": [
            "max_corr_outRH_inRH_change",
            "max_corr_dAH_change",
            "best_lag_h",
            "best_lag_rh_h",
            "gain_ratio_dAH_change",
            "corr_out_AH_in_AH",
            "corr_out_hum_in_hum",
        ],
        "window_tail": [
            "q90_delta_half_in_hum",
            "q90_delta_half_dAH_w",
            "q90_slope_AH_in",
            "q90_max_hourly_hum_rise",
            "top3_info_mean",
        ],
        "run_physical": [
            "mean_out_h",
            "mean_dT",
            "mean_dAH",
            "delta_half_in_h",
            "delta_half_dAH",
            "slope_in_h_per_h",
            "slope_dAH_per_h",
            "std_in_hum_run",
            "amp_dAH_p95_p05",
            "dAH_positive_ratio",
        ],
        "route_persistence": [
            "candidate_high_info_ratio",
            "heat_related_ratio",
            "frac_threshold_favored",
            "frac_pos_delta_half_dAH",
            "route_background_ratio",
            "route_heat_reject_ratio",
        ],
    }
    ranking_df = rank_features(
        run_df,
        positive_group="current_static_unseal",
        negative_group="current_static_seal",
        feature_groups=static_feature_groups,
    )
    static_df = run_df[run_df["analysis_group"].isin(["current_static_seal", "current_static_unseal"])].copy()
    hard_df = analyze_hard_cases(static_df)
    transition_df = analyze_transition_lifts(window_df)
    summary = build_report(run_df, ranking_df, hard_df, transition_df)

    outputs = {
        "run_table_csv": os.path.join(args.output_dir, "current_multiview_run_table.csv"),
        "static_ranking_csv": os.path.join(args.output_dir, "current_static_feature_ranking.csv"),
        "hard_cases_csv": os.path.join(args.output_dir, "current_static_hard_cases.csv"),
        "transition_lifts_csv": os.path.join(args.output_dir, "current_transition_feature_lifts.csv"),
        "report_md": os.path.join(args.output_dir, "current_condition_multiview_report.md"),
        "report_json": os.path.join(args.output_dir, "current_condition_multiview_report.json"),
    }

    run_df.to_csv(outputs["run_table_csv"], index=False, encoding="utf-8-sig")
    ranking_df.to_csv(outputs["static_ranking_csv"], index=False, encoding="utf-8-sig")
    hard_df.to_csv(outputs["hard_cases_csv"], index=False, encoding="utf-8-sig")
    transition_df.to_csv(outputs["transition_lifts_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["report_md"], summary, ranking_df)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
