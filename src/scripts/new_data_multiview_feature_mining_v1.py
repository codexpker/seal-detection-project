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
from src.scripts.old_data_interference_analysis import lag_response_features


EXCLUDE_COLUMNS = {
    "segment_id",
    "file",
    "segment_name",
    "segment_source",
    "segment_seal_state",
    "static_bucket",
    "primary_task",
    "challenge_role",
}

FEATURE_GROUPS: Dict[str, List[str]] = {
    "coupling_lag": [
        "corr_out_hum_in_hum",
        "corr_out_AH_in_AH",
        "corr_headroom_in_hum",
        "corr_headroom_AH_in",
        "max_corr_outRH_inRH_change",
        "max_corr_dAH_change",
        "best_lag_h",
        "best_lag_rh_h",
        "max_corr_level_hum",
        "best_lag_level_hum",
        "max_corr_level_ah",
        "best_lag_level_ah",
        "gain_ratio_dAH_change",
    ],
    "response_persistence": [
        "early_resp_ratio",
        "early_ah_resp_ratio",
        "early_rh_gain_per_out",
        "late_resp_ratio",
        "late_ah_resp_ratio",
        "late_rh_gain_per_out",
        "late_ah_decay_per_headroom",
        "late_minus_early_rh_gain",
        "late_minus_early_resp_ratio",
        "positive_response_ratio",
        "positive_ah_response_ratio",
        "positive_headroom_ratio",
        "positive_drive_ratio",
        "headroom_area_pos",
        "headroom_gain_ratio",
    ],
    "amplitude_dispersion": [
        "amp_in_hum_p90_p10",
        "amp_AH_in_p90_p10",
        "amp_headroom_p90_p10",
        "std_in_hum_run",
        "std_AH_in_run",
    ],
    "legacy_static": [
        "mean_dT",
        "mean_dAH",
        "delta_half_in_h",
        "delta_half_dAH",
        "slope_in_h_per_h",
        "slope_dAH_per_h",
        "end_start_dAH",
        "duration_h",
    ],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Expanded multiview feature mining for new_data mainfield segments")
    parser.add_argument("--input-zip", default="data/new_data.zip")
    parser.add_argument(
        "--segment-manifest-csv",
        default="reports/new_data_segment_pipeline_v1_run1/segment_pipeline_manifest.csv",
    )
    parser.add_argument("--output-dir", default="reports/new_data_multiview_feature_mining_v1_run1")
    return parser.parse_args()


def safe_corr(a: pd.Series, b: pd.Series) -> float:
    a_num = pd.to_numeric(a, errors="coerce")
    b_num = pd.to_numeric(b, errors="coerce")
    valid = a_num.notna() & b_num.notna()
    if valid.sum() < 3:
        return np.nan
    value = np.corrcoef(a_num[valid], b_num[valid])[0, 1]
    return float(value) if not np.isnan(value) else np.nan


def quantile_span(series: pd.Series, q_low: float = 0.10, q_high: float = 0.90) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return np.nan
    return float(values.quantile(q_high) - values.quantile(q_low))


def lagged_corr(x: pd.Series, y: pd.Series, max_lag: int = 6) -> Tuple[float, float]:
    best_corr = -2.0
    best_lag = np.nan
    x_num = pd.to_numeric(x, errors="coerce")
    y_num = pd.to_numeric(y, errors="coerce")
    for lag in range(max_lag + 1):
        pair = pd.concat([x_num, y_num.shift(-lag)], axis=1).dropna()
        if len(pair) < 6:
            continue
        corr_val = pair.iloc[:, 0].corr(pair.iloc[:, 1])
        if pd.notna(corr_val) and corr_val > best_corr:
            best_corr = float(corr_val)
            best_lag = float(lag)
    return (best_corr if best_corr > -1.5 else np.nan, best_lag)


def build_segment_feature_table(args: argparse.Namespace) -> pd.DataFrame:
    manifest_df = pd.read_csv(args.segment_manifest_csv)
    target_df = manifest_df[
        manifest_df["segment_role"].eq("mainfield_extHigh_intLow_noHeat")
        & manifest_df["segment_analyzable"].fillna(False)
    ].copy()

    if target_df.empty:
        return pd.DataFrame()

    rows: List[Dict[str, Any]] = []
    with zipfile.ZipFile(args.input_zip) as zf, tempfile.TemporaryDirectory(prefix="new_multiview_") as tmp_dir:
        for member in zf.namelist():
            if not member.lower().endswith(".xlsx"):
                continue
            file_name = cc.normalize_filename_token(os.path.basename(member))
            file_target_df = target_df[target_df["file"] == file_name].copy()
            if file_target_df.empty:
                continue

            target = os.path.join(tmp_dir, os.path.basename(member))
            with zf.open(member) as src, open(target, "wb") as out:
                out.write(src.read())

            source_df = None
            for _, raw_df in cc.load_excel_sheets(target):
                try:
                    candidate = cc.preprocess_df(raw_df)
                except Exception:
                    continue
                if not candidate.empty:
                    source_df = candidate
                    break
            if source_df is None:
                continue

            for _, meta_row in file_target_df.iterrows():
                seg_start = pd.to_datetime(meta_row["segment_start"])
                seg_end = pd.to_datetime(meta_row["segment_end"])
                seg_df = source_df[(source_df["time"] >= seg_start) & (source_df["time"] <= seg_end)].copy()
                if seg_df.empty:
                    continue

                run_feat = compute_run_features(seg_df)
                dynamic_feat = lag_response_features(seg_df)
                hourly = (
                    seg_df.set_index("time")
                    .resample("1h")
                    .mean(numeric_only=True)
                    .interpolate(limit_direction="both")
                    .reset_index()
                )
                hourly["headroom_ah"] = pd.to_numeric(hourly["AH_out"], errors="coerce") - pd.to_numeric(hourly["AH_in"], errors="coerce")
                hourly["d_out_h"] = pd.to_numeric(hourly["out_hum"], errors="coerce").diff()
                hourly["d_in_h"] = pd.to_numeric(hourly["in_hum"], errors="coerce").diff()
                hourly["d_ah_in"] = pd.to_numeric(hourly["AH_in"], errors="coerce").diff()

                early_stats = summarize_phase(hourly.iloc[:6].copy())
                late_stats = summarize_phase(hourly.iloc[-6:].copy())
                max_corr_level_hum, best_lag_level_hum = lagged_corr(hourly["out_hum"], hourly["in_hum"])
                max_corr_level_ah, best_lag_level_ah = lagged_corr(hourly["AH_out"], hourly["AH_in"])
                positive_headroom = hourly["headroom_ah"] > 0
                positive_drive = hourly["d_out_h"] > 0
                headroom_area = float(np.trapezoid(hourly["headroom_ah"].clip(lower=0.0), dx=1))
                ah_gain = float(hourly["AH_in"].iloc[-1] - hourly["AH_in"].iloc[0])

                static_bucket = str(meta_row.get("static_bucket", "") or "")
                challenge_role = ""
                if static_bucket == "static_positive_eval_only":
                    challenge_role = "weak_positive"
                elif static_bucket == "static_breathing_watch":
                    challenge_role = "breathing_watch"
                elif static_bucket == "static_heatoff_confound_challenge":
                    challenge_role = "heatoff_confound"
                elif static_bucket == "static_positive_reference":
                    challenge_role = "positive_reference"
                elif static_bucket == "static_negative_reference":
                    challenge_role = "negative_reference"

                rows.append(
                    {
                        "segment_id": meta_row["segment_id"],
                        "file": file_name,
                        "segment_name": meta_row["segment_name"],
                        "segment_source": meta_row["segment_source"],
                        "segment_seal_state": meta_row["segment_seal_state"],
                        "static_bucket": static_bucket,
                        "primary_task": meta_row["primary_task"],
                        "challenge_role": challenge_role,
                        "duration_h": run_feat["duration_h"],
                        "mean_dT": run_feat["mean_dT"],
                        "mean_dAH": run_feat["mean_dAH"],
                        "delta_half_in_h": run_feat["delta_half_in_h"],
                        "delta_half_dAH": run_feat["delta_half_dAH"],
                        "slope_in_h_per_h": run_feat["slope_in_h_per_h"],
                        "slope_dAH_per_h": run_feat["slope_dAH_per_h"],
                        "end_start_dAH": run_feat["end_start_dAH"],
                        "std_in_hum_run": float(seg_df["in_hum"].std()),
                        "std_AH_in_run": float(seg_df["AH_in"].std()),
                        "amp_in_hum_p90_p10": quantile_span(seg_df["in_hum"]),
                        "amp_AH_in_p90_p10": quantile_span(seg_df["AH_in"]),
                        "amp_headroom_p90_p10": quantile_span(hourly["headroom_ah"]),
                        "corr_out_hum_in_hum": safe_corr(seg_df["out_hum"], seg_df["in_hum"]),
                        "corr_out_AH_in_AH": safe_corr(seg_df["AH_out"], seg_df["AH_in"]),
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
                    }
                )

    return pd.DataFrame(rows).sort_values(["static_bucket", "segment_id"]).reset_index(drop=True)


def rank_features(feature_df: pd.DataFrame) -> pd.DataFrame:
    refs = feature_df[feature_df["static_bucket"].isin(["static_positive_reference", "static_negative_reference"])].copy()
    refs["label"] = (refs["segment_seal_state"] == "unsealed").astype(int)

    rows: List[Dict[str, Any]] = []
    for feature in [c for c in feature_df.columns if c not in EXCLUDE_COLUMNS]:
        values = pd.to_numeric(refs[feature], errors="coerce")
        valid = values.notna()
        if valid.sum() < 4:
            continue
        auc_pos = auc_pairwise(values.loc[valid].tolist(), refs.loc[valid, "label"].tolist()) or 0.0
        auc_neg = auc_pairwise((-values.loc[valid]).tolist(), refs.loc[valid, "label"].tolist()) or 0.0
        direction = "pos" if auc_pos >= auc_neg else "neg"
        rows.append(
            {
                "feature": feature,
                "group": next((group for group, cols in FEATURE_GROUPS.items() if feature in cols), "other"),
                "auc": float(max(auc_pos, auc_neg)),
                "direction": direction,
                "sealed_median": float(pd.to_numeric(refs.loc[(refs["label"] == 0) & valid, feature], errors="coerce").median()),
                "unsealed_median": float(pd.to_numeric(refs.loc[(refs["label"] == 1) & valid, feature], errors="coerce").median()),
            }
        )
    return pd.DataFrame(rows).sort_values(["auc", "feature"], ascending=[False, True]).reset_index(drop=True)


def build_challenge_profile(feature_df: pd.DataFrame, ranking_df: pd.DataFrame) -> pd.DataFrame:
    targets = feature_df[feature_df["challenge_role"].isin(["weak_positive", "breathing_watch", "heatoff_confound"])].copy()
    top_features = ranking_df.head(12)["feature"].tolist()
    rows: List[Dict[str, Any]] = []
    for _, row in targets.iterrows():
        for feature in top_features:
            rank_row = ranking_df[ranking_df["feature"] == feature].iloc[0]
            rows.append(
                {
                    "segment_id": row["segment_id"],
                    "challenge_role": row["challenge_role"],
                    "feature": feature,
                    "value": row.get(feature, np.nan),
                    "direction": rank_row["direction"],
                    "sealed_median": rank_row["sealed_median"],
                    "unsealed_median": rank_row["unsealed_median"],
                    "tends_to_positive_side": bool(
                        pd.notna(row.get(feature))
                        and (
                            (rank_row["direction"] == "pos" and float(row[feature]) >= float(rank_row["unsealed_median"]))
                            or (rank_row["direction"] == "neg" and float(row[feature]) <= float(rank_row["unsealed_median"]))
                        )
                    ),
                }
            )
    return pd.DataFrame(rows)


def build_summary(feature_df: pd.DataFrame, ranking_df: pd.DataFrame) -> Dict[str, Any]:
    refs = feature_df[feature_df["static_bucket"].isin(["static_positive_reference", "static_negative_reference"])].copy()
    non_artifact = ranking_df[~ranking_df["feature"].isin(["duration_h"])].copy()
    beyond_legacy = non_artifact[
        ~non_artifact["feature"].isin(
            [
                "mean_dT",
                "mean_dAH",
                "delta_half_in_h",
                "delta_half_dAH",
                "slope_in_h_per_h",
                "slope_dAH_per_h",
                "end_start_dAH",
            ]
        )
    ].copy()
    return {
        "mainfield_segment_count": int(len(feature_df)),
        "reference_count": int(len(refs)),
        "reference_class_counts": refs["segment_seal_state"].value_counts(dropna=False).to_dict(),
        "top_non_artifact_features": non_artifact.head(10).to_dict(orient="records"),
        "top_beyond_legacy_features": beyond_legacy.head(10).to_dict(orient="records"),
        "challenge_role_counts": feature_df["challenge_role"].value_counts(dropna=False).to_dict(),
    }


def write_markdown(path: str, summary: Dict[str, Any], ranking_df: pd.DataFrame, challenge_df: pd.DataFrame) -> None:
    lines = [
        "# 新补充数据 扩样本多视角特征挖掘报告",
        "",
        f"- mainfield_segment_count: `{summary['mainfield_segment_count']}`",
        f"- reference_count: `{summary['reference_count']}`",
        f"- reference_class_counts: `{summary['reference_class_counts']}`",
        f"- challenge_role_counts: `{summary['challenge_role_counts']}`",
        "",
        "## 当前判断",
        "",
        "- 扩样本后，主战场段级数据里确实出现了一批比“原有 4 个量 + AH”更值得追的特征。",
        "- 这些新特征不是都应该直接进模型；更合理的是先把它们分成：`增强 weak positive`、`压制 breathing false positive`、`识别 heat-off confound` 三类用途。",
        "- 因此下一步不是盲目堆更多特征，而是把这些特征按用途接进现有 `watch / review / static support` 框架。",
        "",
        "## 排除实验设计投影后的高价值特征",
        "",
    ]

    for item in summary["top_non_artifact_features"]:
        lines.append(
            f"- {item['feature']} | group={item['group']} | auc={item['auc']:.3f} | "
            f"direction={item['direction']} | sealed_median={item['sealed_median']:.3f} | "
            f"unsealed_median={item['unsealed_median']:.3f}"
        )

    lines.extend(
        [
            "",
            "## 明确超出原有静态 4 特征 + AH 的候选特征",
            "",
        ]
    )
    for item in summary["top_beyond_legacy_features"]:
        lines.append(
            f"- {item['feature']} | group={item['group']} | auc={item['auc']:.3f} | "
            f"direction={item['direction']} | sealed_median={item['sealed_median']:.3f} | "
            f"unsealed_median={item['unsealed_median']:.3f}"
        )

    lines.extend(
        [
            "",
            "## 三个关键难段怎么看",
            "",
            "- `weak_positive`：重点看是否有较高的耦合/滞后相关，但累计响应和后段放大不够。",
            "- `breathing_watch`：重点看是否在很多累计特征上像正样本，但后段放大和 headroom 响应结构不够像真正不密封。",
            "- `heatoff_confound`：重点看相关性存在，但 `AH` 累计方向和净漂移与主战场正样本不一致。",
            "",
        ]
    )

    if not challenge_df.empty:
        for segment_id, group in challenge_df.groupby("segment_id", dropna=False):
            role = str(group["challenge_role"].iloc[0])
            lines.append(f"### {segment_id}")
            lines.append("")
            lines.append(f"- role: `{role}`")
            for _, row in group.iterrows():
                lines.append(
                    f"- {row['feature']} | value={float(row['value']):.3f} | direction={row['direction']} | "
                    f"seal_med={float(row['sealed_median']):.3f} | unseal_med={float(row['unsealed_median']):.3f} | "
                    f"toward_positive={bool(row['tends_to_positive_side'])}"
                )
            lines.append("")

    lines.extend(
        [
            "## 结论",
            "",
            "1. 真正值得继续追的新增特征主要分三类：",
            "   - `耦合/滞后`：`max_corr_outRH_inRH_change`、`corr_out_hum_in_hum`、`max_corr_level_hum/ah`、`best_lag_level_hum/ah`",
            "   - `响应持续性`：`late_rh_gain_per_out`、`late_minus_early_rh_gain`、`positive_ah_response_ratio`、`headroom_gain_ratio`",
            "   - `波动/幅度`：`amp_in_hum_p90_p10`、`std_in_hum_run`、`amp_headroom_p90_p10`",
            "2. `duration_h` 虽然在当前参考池里分离度很高，但更像实验设计投影，不建议直接当主特征。",
            "3. `weak_positive` 更像“相关性对了，但累计响应和后段放大不够”；`breathing_watch` 更像“累计量像正样本，但持续性结构不像真正不密封”。",
            "4. 下一步最合理的做法不是直接把这些特征全堆进 XGBoost，而是先把它们接成：",
            "   - `weak positive support`",
            "   - `breathing suppression`",
            "   - `confound reject`",
            "   三个子评分，再看是否真正改善当前主线程。",
            "",
        ]
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    feature_df = build_segment_feature_table(args)
    ranking_df = rank_features(feature_df)
    challenge_df = build_challenge_profile(feature_df, ranking_df)
    summary = build_summary(feature_df, ranking_df)

    outputs = {
        "feature_table_csv": os.path.join(args.output_dir, "new_data_multiview_feature_table.csv"),
        "feature_ranking_csv": os.path.join(args.output_dir, "new_data_multiview_feature_ranking.csv"),
        "challenge_profile_csv": os.path.join(args.output_dir, "new_data_multiview_challenge_profile.csv"),
        "report_md": os.path.join(args.output_dir, "new_data_multiview_feature_report.md"),
        "report_json": os.path.join(args.output_dir, "new_data_multiview_feature_report.json"),
    }

    feature_df.to_csv(outputs["feature_table_csv"], index=False, encoding="utf-8-sig")
    ranking_df.to_csv(outputs["feature_ranking_csv"], index=False, encoding="utf-8-sig")
    challenge_df.to_csv(outputs["challenge_profile_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["report_md"], summary, ranking_df, challenge_df)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
