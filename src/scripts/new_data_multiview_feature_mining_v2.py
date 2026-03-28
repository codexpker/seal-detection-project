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

ARTIFACT_LIKE_FEATURES = {
    "duration_h",
    "ah_ingress_count",
    "dew_ingress_count",
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
    "dew_vapor": [
        "dew_gap_mean",
        "dew_gap_q90",
        "dew_gap_area_pos",
        "dew_gap_pos_ratio",
        "amp_dew_in_p90_p10",
        "std_dew_in_run",
        "corr_out_dew_in_dew",
        "corr_dew_gap_in_dew",
        "max_corr_dew_change",
        "best_lag_dew_h",
        "max_corr_level_dew",
        "best_lag_level_dew",
        "early_dew_gain_per_out",
        "late_dew_gain_per_out",
        "late_minus_early_dew_gain",
        "dew_headroom_capture_ratio",
    ],
    "ingress_proxy": [
        "ah_gap_q90",
        "ah_gap_area_pos",
        "ah_ingress_slope",
        "ah_ingress_r2",
        "ah_ingress_count",
        "ah_pos_gain_per_area",
        "ah_neg_response_ratio",
        "dew_ingress_slope",
        "dew_ingress_r2",
        "dew_ingress_count",
        "dew_pos_gain_per_area",
        "dew_neg_response_ratio",
        "vpd_in_mean",
        "vpd_gap_mean",
        "late_minus_early_vpd_gap",
    ],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Expanded multiview feature mining v2 with dew point and ingress proxies")
    parser.add_argument("--input-zip", default="data/new_data.zip")
    parser.add_argument(
        "--segment-manifest-csv",
        default="reports/new_data_segment_pipeline_v1_run1/segment_pipeline_manifest.csv",
    )
    parser.add_argument("--output-dir", default="reports/new_data_multiview_feature_mining_v2_run1")
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


def dew_point_c(temp_c: pd.Series, rh_pct: pd.Series) -> pd.Series:
    temp = pd.to_numeric(temp_c, errors="coerce")
    rh = pd.to_numeric(rh_pct, errors="coerce").clip(lower=1e-3, upper=100.0)
    a = 17.62
    b = 243.12
    gamma = np.log(rh / 100.0) + (a * temp / (b + temp))
    dew = (b * gamma) / (a - gamma)
    return pd.Series(dew, index=temp.index)


def vapor_pressure_deficit_kpa(temp_c: pd.Series, rh_pct: pd.Series) -> pd.Series:
    temp = pd.to_numeric(temp_c, errors="coerce")
    rh = pd.to_numeric(rh_pct, errors="coerce").clip(lower=0.0, upper=100.0)
    sat = 0.6108 * np.exp((17.27 * temp) / (temp + 237.3))
    actual = sat * (rh / 100.0)
    return pd.Series(sat - actual, index=temp.index)


def safe_gain_ratio(delta_response: float, delta_drive: float, min_abs_drive: float = 0.2) -> float:
    if pd.isna(delta_response) or pd.isna(delta_drive) or abs(float(delta_drive)) < min_abs_drive:
        return np.nan
    return float(delta_response / delta_drive)


def summarize_generic_phase(
    phase_df: pd.DataFrame,
    drive_col: str,
    response_col: str,
    response_change_col: str,
    min_drive_delta: float = 0.2,
) -> Dict[str, float]:
    if phase_df.empty:
        return {
            "delta_drive": np.nan,
            "delta_response": np.nan,
            "gain_per_drive": np.nan,
            "respond_pos_ratio": np.nan,
        }

    drive = pd.to_numeric(phase_df[drive_col], errors="coerce")
    response = pd.to_numeric(phase_df[response_col], errors="coerce")
    response_change = pd.to_numeric(phase_df[response_change_col], errors="coerce")
    delta_drive = float(drive.iloc[-1] - drive.iloc[0])
    delta_response = float(response.iloc[-1] - response.iloc[0])
    active = drive.diff() > 0
    return {
        "delta_drive": delta_drive,
        "delta_response": delta_response,
        "gain_per_drive": safe_gain_ratio(delta_response, delta_drive, min_abs_drive=min_drive_delta),
        "respond_pos_ratio": float((response_change.loc[active] > 0).mean()) if active.any() else np.nan,
    }


def ingress_regression(
    drive_series: pd.Series,
    response_delta_series: pd.Series,
    min_drive: float = 0.05,
    min_points: int = 4,
) -> Dict[str, float]:
    x = pd.to_numeric(drive_series, errors="coerce").shift(1)
    y = pd.to_numeric(response_delta_series, errors="coerce")
    valid = x.notna() & y.notna() & (x > min_drive)
    if int(valid.sum()) < min_points:
        return {
            "slope": np.nan,
            "r2": np.nan,
            "count": float(valid.sum()),
            "pos_gain_per_area": np.nan,
            "neg_response_ratio": np.nan,
            "capture_ratio": np.nan,
        }

    x_valid = x.loc[valid].astype(float)
    y_valid = y.loc[valid].astype(float)
    slope, intercept = np.polyfit(x_valid, y_valid, 1)
    pred = slope * x_valid + intercept
    ss_res = float(((y_valid - pred) ** 2).sum())
    ss_tot = float(((y_valid - y_valid.mean()) ** 2).sum())
    r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 1e-9 else np.nan
    drive_area = float(x_valid.clip(lower=0.0).sum())
    return {
        "slope": float(slope),
        "r2": r2,
        "count": float(valid.sum()),
        "pos_gain_per_area": float(y_valid.clip(lower=0.0).sum() / max(drive_area, 1e-6)),
        "neg_response_ratio": float((y_valid < 0).mean()),
        "capture_ratio": float((y_valid > 0).mean()),
    }


def build_segment_feature_table(args: argparse.Namespace) -> pd.DataFrame:
    manifest_df = pd.read_csv(args.segment_manifest_csv)
    target_df = manifest_df[
        manifest_df["segment_role"].eq("mainfield_extHigh_intLow_noHeat")
        & manifest_df["segment_analyzable"].fillna(False)
    ].copy()

    if target_df.empty:
        return pd.DataFrame()

    rows: List[Dict[str, Any]] = []
    with zipfile.ZipFile(args.input_zip) as zf, tempfile.TemporaryDirectory(prefix="new_multiview_v2_") as tmp_dir:
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

                seg_df["dew_in"] = dew_point_c(seg_df["in_temp"], seg_df["in_hum"])
                seg_df["dew_out"] = dew_point_c(seg_df["out_temp"], seg_df["out_hum"])
                seg_df["vpd_in"] = vapor_pressure_deficit_kpa(seg_df["in_temp"], seg_df["in_hum"])
                seg_df["vpd_out"] = vapor_pressure_deficit_kpa(seg_df["out_temp"], seg_df["out_hum"])

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
                hourly["dew_in"] = dew_point_c(hourly["in_temp"], hourly["in_hum"])
                hourly["dew_out"] = dew_point_c(hourly["out_temp"], hourly["out_hum"])
                hourly["dew_gap"] = pd.to_numeric(hourly["dew_out"], errors="coerce") - pd.to_numeric(hourly["dew_in"], errors="coerce")
                hourly["d_dew_out"] = pd.to_numeric(hourly["dew_out"], errors="coerce").diff()
                hourly["d_dew_in"] = pd.to_numeric(hourly["dew_in"], errors="coerce").diff()
                hourly["vpd_in"] = vapor_pressure_deficit_kpa(hourly["in_temp"], hourly["in_hum"])
                hourly["vpd_out"] = vapor_pressure_deficit_kpa(hourly["out_temp"], hourly["out_hum"])
                hourly["vpd_gap"] = pd.to_numeric(hourly["vpd_out"], errors="coerce") - pd.to_numeric(hourly["vpd_in"], errors="coerce")
                hourly["d_vpd_gap"] = pd.to_numeric(hourly["vpd_gap"], errors="coerce").diff()

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
                        "dew_gap_mean": float(hourly["dew_gap"].mean()),
                        "dew_gap_q90": float(hourly["dew_gap"].quantile(0.90)),
                        "dew_gap_area_pos": dew_gap_area,
                        "dew_gap_pos_ratio": float(positive_dew_gap.mean()),
                        "amp_dew_in_p90_p10": quantile_span(seg_df["dew_in"]),
                        "std_dew_in_run": float(seg_df["dew_in"].std()),
                        "corr_out_dew_in_dew": safe_corr(seg_df["dew_out"], seg_df["dew_in"]),
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
                        "vpd_in_mean": float(seg_df["vpd_in"].mean()),
                        "vpd_gap_mean": float((seg_df["vpd_out"] - seg_df["vpd_in"]).mean()),
                        "late_minus_early_vpd_gap": float(hourly["vpd_gap"].iloc[-6:].mean() - hourly["vpd_gap"].iloc[:6].mean())
                        if len(hourly) >= 6
                        else np.nan,
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
    top_features = ranking_df[
        (~ranking_df["feature"].isin(["duration_h"]))
        & (ranking_df["group"].isin(["dew_vapor", "ingress_proxy", "coupling_lag", "response_persistence"]))
    ].head(15)["feature"].tolist()
    rows: List[Dict[str, Any]] = []
    for _, row in targets.iterrows():
        for feature in top_features:
            rank_row = ranking_df[ranking_df["feature"] == feature].iloc[0]
            value = row.get(feature, np.nan)
            rows.append(
                {
                    "segment_id": row["segment_id"],
                    "challenge_role": row["challenge_role"],
                    "feature": feature,
                    "group": rank_row["group"],
                    "value": value,
                    "direction": rank_row["direction"],
                    "sealed_median": rank_row["sealed_median"],
                    "unsealed_median": rank_row["unsealed_median"],
                    "tends_to_positive_side": bool(
                        pd.notna(value)
                        and (
                            (rank_row["direction"] == "pos" and float(value) >= float(rank_row["unsealed_median"]))
                            or (rank_row["direction"] == "neg" and float(value) <= float(rank_row["unsealed_median"]))
                        )
                    ),
                }
            )
    return pd.DataFrame(rows)


def build_challenge_usefulness(feature_df: pd.DataFrame, ranking_df: pd.DataFrame) -> pd.DataFrame:
    challenge_df = feature_df[feature_df["challenge_role"].isin(["weak_positive", "breathing_watch", "heatoff_confound"])].copy()
    expected = {
        "weak_positive": True,
        "breathing_watch": False,
        "heatoff_confound": False,
    }
    rows: List[Dict[str, Any]] = []
    for _, rank_row in ranking_df.iterrows():
        feature = str(rank_row["feature"])
        direction = str(rank_row["direction"])
        unsealed_median = float(rank_row["unsealed_median"])
        item: Dict[str, Any] = {
            "feature": feature,
            "group": rank_row["group"],
            "auc": float(rank_row["auc"]),
            "challenge_match": 0,
            "total_roles": 0,
        }
        for role, expected_positive in expected.items():
            role_row = challenge_df[challenge_df["challenge_role"] == role]
            if role_row.empty or feature not in role_row.columns:
                continue
            value = role_row.iloc[0][feature]
            toward_positive = bool(
                pd.notna(value)
                and (
                    (direction == "pos" and float(value) >= unsealed_median)
                    or (direction == "neg" and float(value) <= unsealed_median)
                )
            )
            item[f"{role}_toward_positive"] = toward_positive
            item["challenge_match"] += int(toward_positive == expected_positive)
            item["total_roles"] += 1
        rows.append(item)
    return pd.DataFrame(rows).sort_values(
        ["challenge_match", "auc", "feature"],
        ascending=[False, False, True],
    ).reset_index(drop=True)


def build_summary(feature_df: pd.DataFrame, ranking_df: pd.DataFrame, usefulness_df: pd.DataFrame) -> Dict[str, Any]:
    refs = feature_df[feature_df["static_bucket"].isin(["static_positive_reference", "static_negative_reference"])].copy()
    non_artifact = ranking_df[~ranking_df["feature"].isin(ARTIFACT_LIKE_FEATURES)].copy()
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
    new_groups = non_artifact[non_artifact["group"].isin(["dew_vapor", "ingress_proxy"])].copy()
    useful_non_artifact = usefulness_df[~usefulness_df["feature"].isin(ARTIFACT_LIKE_FEATURES)].copy()
    return {
        "mainfield_segment_count": int(len(feature_df)),
        "reference_count": int(len(refs)),
        "reference_class_counts": refs["segment_seal_state"].value_counts(dropna=False).to_dict(),
        "challenge_role_counts": feature_df["challenge_role"].value_counts(dropna=False).to_dict(),
        "top_non_artifact_features": non_artifact.head(12).to_dict(orient="records"),
        "top_beyond_legacy_features": beyond_legacy.head(12).to_dict(orient="records"),
        "top_new_dew_and_ingress_features": new_groups.head(12).to_dict(orient="records"),
        "top_challenge_useful_features": useful_non_artifact.head(12).to_dict(orient="records"),
    }


def write_markdown(
    path: str,
    summary: Dict[str, Any],
    ranking_df: pd.DataFrame,
    challenge_df: pd.DataFrame,
) -> None:
    lines = [
        "# 新补充数据 扩样本多视角特征挖掘报告 v2",
        "",
        f"- mainfield_segment_count: `{summary['mainfield_segment_count']}`",
        f"- reference_count: `{summary['reference_count']}`",
        f"- reference_class_counts: `{summary['reference_class_counts']}`",
        f"- challenge_role_counts: `{summary['challenge_role_counts']}`",
        "",
        "## 当前判断",
        "",
        "- 这轮专门补了 `露点温度` 和更稳的 `进湿/泄漏代理` 特征，目标不是堆模型，而是看它们能不能解释 `weak_positive / breathing_watch / heat-off confound`。",
        "- 原始的 `露点增益比` 这类分母很小会发散的特征没有保留；这里只保留了 `露点差面积`、`露点耦合`、`正驱动下的响应斜率`、`单位驱动面积的正向增益` 这类更稳的量。",
        "- 由于当前干净参考段仍只有 `5` 个，下面所有排名都只能理解为“特征优先级线索”，不能理解为已经证明通用有效。",
        "- `ingress_count` 这类有效驱动点个数本质上仍然带有时长/驱动覆盖率投影，所以这次不会把它当主结论。",
        "",
        "## 新增 Dew / Ingress 代理里值得继续追的特征",
        "",
    ]

    for item in summary["top_new_dew_and_ingress_features"]:
        lines.append(
            f"- {item['feature']} | group={item['group']} | auc={item['auc']:.3f} | "
            f"direction={item['direction']} | sealed_median={item['sealed_median']:.3f} | "
            f"unsealed_median={item['unsealed_median']:.3f}"
        )

    lines.extend(
        [
            "",
            "## 对真实难点更有用的特征",
            "",
        ]
    )
    for item in summary["top_challenge_useful_features"]:
        lines.append(
            f"- {item['feature']} | group={item['group']} | auc={item['auc']:.3f} | "
            f"challenge_match={int(item['challenge_match'])}/{int(item['total_roles'])}"
        )

    lines.extend(
        [
            "",
            "## 把 Dew / Ingress 代理和上一轮特征放在一起看",
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
            "- `weak_positive`：如果露点/耦合相关站得住，但累计面积和 ingress 斜率不够，说明它更像“跟随存在，但积湿不够持续”。",
            "- `breathing_watch`：如果漂移和部分相关性像正样本，但晚段 dew / ingress 持续性仍弱，说明更像材料呼吸而不是稳定进湿。",
            "- `heatoff_confound`：如果热源切换后露点或 RH 有回升，但 `AH/dew 正驱动面积` 和 `ingress slope` 站不住，就不能被提升成主战场正样本。",
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
                value = row["value"]
                value_str = "nan" if pd.isna(value) else f"{float(value):.3f}"
                lines.append(
                    f"- {row['feature']} | group={row['group']} | value={value_str} | direction={row['direction']} | "
                    f"seal_med={float(row['sealed_median']):.3f} | unseal_med={float(row['unsealed_median']):.3f} | "
                    f"toward_positive={bool(row['tends_to_positive_side'])}"
                )
            lines.append("")

    lines.extend(
        [
            "## 结论",
            "",
            "1. `露点温度` 这条线是有价值的，但真正有用的不是单独露点值，而是：`dew_gap_area_pos`、`corr_out_dew_in_dew`、`max_corr_dew_change`、`late_minus_early_dew_gain` 这类“外部驱动 -> 内部响应”的结构特征。",
            "2. `泄漏率` 目前更适合定义成 `ingress proxy`，不是物理绝对泄漏率。当前更稳的是：`ah_ingress_slope`、`ah_pos_gain_per_area`、`dew_ingress_slope`、`dew_pos_gain_per_area`。",
            "3. 单纯看参考段 AUC 会高估一部分特征；把 `weak_positive / breathing_watch / heat-off confound` 一起考虑后，`max_corr_level_dew / ah / hum` 这类 level-correlation 特征反而更像真正有助于难段分流的线索。",
            "4. 如果某个特征依赖很小的分母或明显依赖时长才显得很强，它就不该进主线程；所以这次故意剔除了原始高爆炸比值和 `ingress_count` 这类投影量。",
            "5. 下一步最合理的方向不是重开 whole-run 模型，而是把新增特征按用途接成三个子评分：",
            "   - `weak positive support`：提升像 `181049` 这种“耦合对了但累计偏弱”的段",
            "   - `breathing suppression`：压住像 `160246` 这种 sealed breathing 难例",
            "   - `confound reject`：继续压住 `heat-off/ext change` 混淆段",
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
    usefulness_df = build_challenge_usefulness(feature_df, ranking_df)
    summary = build_summary(feature_df, ranking_df, usefulness_df)

    outputs = {
        "feature_table_csv": os.path.join(args.output_dir, "new_data_multiview_feature_table_v2.csv"),
        "feature_ranking_csv": os.path.join(args.output_dir, "new_data_multiview_feature_ranking_v2.csv"),
        "challenge_profile_csv": os.path.join(args.output_dir, "new_data_multiview_challenge_profile_v2.csv"),
        "challenge_usefulness_csv": os.path.join(args.output_dir, "new_data_feature_challenge_usefulness_v2.csv"),
        "report_md": os.path.join(args.output_dir, "new_data_multiview_feature_report_v2.md"),
        "report_json": os.path.join(args.output_dir, "new_data_multiview_feature_report_v2.json"),
    }

    feature_df.to_csv(outputs["feature_table_csv"], index=False, encoding="utf-8-sig")
    ranking_df.to_csv(outputs["feature_ranking_csv"], index=False, encoding="utf-8-sig")
    challenge_df.to_csv(outputs["challenge_profile_csv"], index=False, encoding="utf-8-sig")
    usefulness_df.to_csv(outputs["challenge_usefulness_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["report_md"], summary, ranking_df, challenge_df)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
