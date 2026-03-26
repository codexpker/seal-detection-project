#!/usr/bin/env python3
import argparse
import json
import os
import sys
import tempfile
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.anomaly_v2 import condition_classifier_v1 as cc
from src.scripts.lab_ext_high_humidity_response_v1 import build_inputs, mark_cooling_windows
from src.scripts.lab_ext_high_humidity_response_v2 import run_multiscale_branch_v2
from src.scripts.lab_phase1_acceptance import Phase1Config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cooling residual probe v1 for ext-high-humidity heated runs")
    parser.add_argument("--input-dir", default=Phase1Config.input_dir)
    parser.add_argument("--input-zip", default=Phase1Config.input_zip)
    parser.add_argument("--metadata-xlsx", default=Phase1Config.metadata_xlsx)
    parser.add_argument("--output-dir", default="reports/lab_cooling_residual_probe_v1")
    parser.add_argument("--step-hours", type=int, default=1)
    parser.add_argument("--transition-near-hours", type=int, default=6)
    parser.add_argument("--similarity-k", type=int, default=5)
    parser.add_argument("--main-window-hours", type=int, default=6)
    parser.add_argument("--long-window-hours", type=int, default=12)
    parser.add_argument("--cooling-delta-temp-thresh", type=float, default=-0.3)
    parser.add_argument("--cooling-slope-temp-thresh", type=float, default=-0.01)
    parser.add_argument("--cooling-half-temp-thresh", type=float, default=-0.1)
    parser.add_argument("--heated-mean-dt-thresh", type=float, default=5.0)
    parser.add_argument("--residual-end-ah-thresh", type=float, default=0.15)
    parser.add_argument("--residual-area-ah-thresh", type=float, default=0.30)
    parser.add_argument("--residual-max-rh-thresh", type=float, default=1.0)
    parser.add_argument("--residual-headroom-thresh", type=float, default=0.20)
    parser.add_argument("--focus-hours", type=int, default=4)
    return parser.parse_args()


def make_window_args(args: argparse.Namespace, window_hours: int) -> argparse.Namespace:
    return argparse.Namespace(
        input_dir=args.input_dir,
        input_zip=args.input_zip,
        metadata_xlsx=args.metadata_xlsx,
        output_dir=args.output_dir,
        window_hours=window_hours,
        step_hours=args.step_hours,
        transition_near_hours=args.transition_near_hours,
        similarity_k=args.similarity_k,
        cooling_delta_temp_thresh=args.cooling_delta_temp_thresh,
        cooling_slope_temp_thresh=args.cooling_slope_temp_thresh,
        cooling_half_temp_thresh=args.cooling_half_temp_thresh,
        heated_mean_dt_thresh=args.heated_mean_dt_thresh,
    )


def collect_preprocessed_file_map(args: argparse.Namespace) -> Dict[str, pd.DataFrame]:
    cfg = cc.Config(
        input_dir=args.input_dir,
        input_zip=args.input_zip,
        metadata_xlsx=args.metadata_xlsx,
        output_dir=args.output_dir,
        window_hours=max(int(args.main_window_hours), 1),
        step_hours=max(int(args.step_hours), 1),
    )
    file_map: Dict[str, pd.DataFrame] = {}
    with tempfile.TemporaryDirectory(prefix="cooling_residual_probe_") as tmp_dir:
        files = cc.collect_input_files(cfg, tmp_dir)
        for path in files:
            file_name = cc.normalize_filename_token(os.path.basename(path))
            sheets = cc.load_excel_sheets(path)
            for _, raw_df in sheets:
                try:
                    df = cc.preprocess_df(raw_df)
                except Exception:
                    continue
                if not df.empty:
                    file_map[file_name] = df
                    break
    return file_map


def extract_contiguous_blocks(flagged_df: pd.DataFrame, step_hours: int) -> pd.DataFrame:
    if flagged_df.empty:
        return pd.DataFrame()
    work = flagged_df.sort_values("start_time").copy()
    start_ts = pd.to_datetime(work["start_time"], errors="coerce")
    gap_h = start_ts.diff().dt.total_seconds().div(3600.0)
    work["block_id"] = (gap_h.isna() | (gap_h > (step_hours + 0.1))).cumsum().astype(int)

    rows: List[Dict[str, Any]] = []
    for block_id, block in work.groupby("block_id", dropna=False):
        rows.append(
            {
                "block_id": int(block_id),
                "block_start": pd.to_datetime(block["start_time"], errors="coerce").min(),
                "block_end": pd.to_datetime(block["end_time"], errors="coerce").max(),
                "window_count": int(len(block)),
                "q75_delta_half_dAH": float(pd.to_numeric(block["delta_half_dAH"], errors="coerce").quantile(0.75)),
                "median_delta_half_dAH": float(pd.to_numeric(block["delta_half_dAH"], errors="coerce").median()),
                "median_delta_in_temp": float(pd.to_numeric(block["delta_in_temp"], errors="coerce").median()),
                "median_slope_in_temp": float(pd.to_numeric(block["slope_in_temp"], errors="coerce").median()),
                "mean_dT": float(pd.to_numeric(block["mean_dT"], errors="coerce").mean()),
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["q75_delta_half_dAH", "window_count", "block_start"],
        ascending=[False, False, True],
    ).reset_index(drop=True)


def resample_hourly(df: pd.DataFrame) -> pd.DataFrame:
    hourly = df.set_index("time").resample("1h").mean(numeric_only=True).interpolate(limit_direction="both")
    hourly = hourly.reset_index()
    return hourly


def sat_absolute_humidity(temp_c: pd.Series) -> pd.Series:
    return cc.calc_absolute_humidity(pd.to_numeric(temp_c, errors="coerce"), pd.Series(100.0, index=temp_c.index))


def integrate_positive_area(hours: pd.Series, values: pd.Series) -> float:
    x = pd.to_numeric(hours, errors="coerce").astype(float)
    y = pd.to_numeric(values, errors="coerce").astype(float).clip(lower=0.0)
    if len(x) < 2:
        return 0.0
    return float(np.trapezoid(y.values, x.values))


def compute_horizon_metrics(seg: pd.DataFrame, horizon_h: int) -> Dict[str, float]:
    horizon = seg[seg["elapsed_h"] <= float(horizon_h)].copy()
    if len(horizon) < 2:
        return {
            f"end_excess_ah_{horizon_h}h": np.nan,
            f"pos_area_excess_ah_{horizon_h}h": np.nan,
            f"max_excess_rh_{horizon_h}h": np.nan,
            f"pos_area_excess_rh_{horizon_h}h": np.nan,
            f"mean_out_headroom_ah_{horizon_h}h": np.nan,
            f"end_gain_ratio_ah_{horizon_h}h": np.nan,
            f"positive_excess_ah_ratio_{horizon_h}h": np.nan,
            f"end_excess_dah_{horizon_h}h": np.nan,
        }

    mean_out_headroom = float(horizon["out_headroom_ah"].clip(lower=0.0).mean())
    mean_out_headroom_raw = float(horizon["out_headroom_ah"].mean())
    end_excess_ah = float(horizon["excess_ah_const"].iloc[-1])
    return {
        f"end_excess_ah_{horizon_h}h": end_excess_ah,
        f"pos_area_excess_ah_{horizon_h}h": integrate_positive_area(horizon["elapsed_h"], horizon["excess_ah_const"]),
        f"max_excess_rh_{horizon_h}h": float(horizon["excess_rh_const_ah"].max()),
        f"pos_area_excess_rh_{horizon_h}h": integrate_positive_area(horizon["elapsed_h"], horizon["excess_rh_const_ah"]),
        f"mean_out_headroom_ah_{horizon_h}h": mean_out_headroom,
        f"mean_out_headroom_ah_raw_{horizon_h}h": mean_out_headroom_raw,
        f"end_gain_ratio_ah_{horizon_h}h": float(end_excess_ah / mean_out_headroom) if mean_out_headroom > 1e-6 else np.nan,
        f"positive_excess_ah_ratio_{horizon_h}h": float((horizon["excess_ah_const"] > 0).mean()),
        f"end_excess_dah_{horizon_h}h": float(horizon["excess_dah_const"].iloc[-1]),
    }


def compute_residual_segment(hourly_df: pd.DataFrame, onset: pd.Timestamp, focus_hours: int) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    seg = hourly_df[(hourly_df["time"] >= onset) & (hourly_df["time"] <= onset + pd.Timedelta(hours=focus_hours))].copy()
    if len(seg) < 2:
        return pd.DataFrame(), {}

    seg = seg.sort_values("time").reset_index(drop=True)
    seg["elapsed_h"] = (seg["time"] - seg["time"].iloc[0]).dt.total_seconds() / 3600.0

    base_ah = float(seg["AH_in"].iloc[0])
    base_dah = float(seg["dAH"].iloc[0])
    sat_ah = sat_absolute_humidity(seg["in_temp"])
    rh_pred = (100.0 * base_ah / sat_ah).clip(lower=0.0, upper=100.0)

    seg["rh_pred_const_ah"] = rh_pred
    seg["excess_rh_const_ah"] = pd.to_numeric(seg["in_hum"], errors="coerce") - seg["rh_pred_const_ah"]
    seg["excess_ah_const"] = pd.to_numeric(seg["AH_in"], errors="coerce") - base_ah
    seg["excess_dah_const"] = pd.to_numeric(seg["dAH"], errors="coerce") - base_dah
    seg["out_headroom_ah"] = pd.to_numeric(seg["AH_out"], errors="coerce") - base_ah

    summary: Dict[str, Any] = {
        "segment_start": pd.to_datetime(seg["time"].iloc[0]),
        "segment_end": pd.to_datetime(seg["time"].iloc[-1]),
        "segment_duration_h": float(seg["elapsed_h"].iloc[-1]),
        "base_ah_in": base_ah,
        "base_dah": base_dah,
        "temp_drop_total": float(pd.to_numeric(seg["in_temp"], errors="coerce").iloc[-1] - pd.to_numeric(seg["in_temp"], errors="coerce").iloc[0]),
    }
    for horizon_h in [1, 2, 4]:
        summary.update(compute_horizon_metrics(seg, horizon_h))
    return seg, summary


def residual_status(row: pd.Series, args: argparse.Namespace) -> str:
    if bool(row.get("has_cooling_block")) is False:
        return "cooling_residual_no_segment"
    end_excess = pd.to_numeric(pd.Series([row.get("end_excess_ah_4h")]), errors="coerce").iloc[0]
    pos_area = pd.to_numeric(pd.Series([row.get("pos_area_excess_ah_4h")]), errors="coerce").iloc[0]
    max_rh = pd.to_numeric(pd.Series([row.get("max_excess_rh_4h")]), errors="coerce").iloc[0]
    headroom = pd.to_numeric(pd.Series([row.get("mean_out_headroom_ah_4h")]), errors="coerce").iloc[0]

    if (
        pd.notna(end_excess)
        and pd.notna(pos_area)
        and pd.notna(max_rh)
        and pd.notna(headroom)
        and end_excess >= float(args.residual_end_ah_thresh)
        and pos_area >= float(args.residual_area_ah_thresh)
        and max_rh >= float(args.residual_max_rh_thresh)
        and headroom >= float(args.residual_headroom_thresh)
    ):
        return "cooling_residual_supported_candidate"
    if pd.notna(pos_area) and pos_area > 0.0:
        return "cooling_residual_weak_or_confounded"
    return "cooling_residual_negative"


def build_probe(args: argparse.Namespace) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    main_args = make_window_args(args, int(args.main_window_hours))
    _, window_df, decision_df = build_inputs(main_args)
    cooling_window_df = mark_cooling_windows(window_df, main_args)
    cooling_window_df = cooling_window_df[cooling_window_df["expected_family"] == "ext_high_hum_with_heat"].copy()

    multiscale = run_multiscale_branch_v2(args)
    cooling_v2_df = multiscale["cooling_df"].copy()
    raw_map = collect_preprocessed_file_map(args)

    rows: List[Dict[str, Any]] = []
    hourly_rows: List[pd.DataFrame] = []

    run_list = sorted(cooling_window_df["file"].dropna().unique().tolist())
    if not run_list and not cooling_v2_df.empty:
        run_list = sorted(cooling_v2_df["file"].dropna().unique().tolist())

    for file_name in run_list:
        run_windows = cooling_window_df[(cooling_window_df["file"] == file_name) & (cooling_window_df["cooling_response_flag"])].copy()
        blocks_df = extract_contiguous_blocks(run_windows, int(args.step_hours))
        top_block = blocks_df.iloc[0].to_dict() if not blocks_df.empty else {}

        row: Dict[str, Any] = {
            "file": file_name,
            "seal_label": str(run_windows["seal_label"].iloc[0]) if not run_windows.empty else "",
            "expected_family": str(run_windows["expected_family"].iloc[0]) if not run_windows.empty else "ext_high_hum_with_heat",
            "has_cooling_block": bool(not blocks_df.empty),
            "cooling_block_count": int(len(blocks_df)),
            "cooling_window_count_6h": int(len(run_windows)),
        }
        if top_block:
            row.update(top_block)
        else:
            row.update(
                {
                    "block_id": np.nan,
                    "block_start": pd.NaT,
                    "block_end": pd.NaT,
                    "window_count": 0,
                    "q75_delta_half_dAH": np.nan,
                    "median_delta_half_dAH": np.nan,
                    "median_delta_in_temp": np.nan,
                    "median_slope_in_temp": np.nan,
                    "mean_dT": np.nan,
                }
            )

        v2_row = cooling_v2_df.loc[cooling_v2_df["file"] == file_name]
        if not v2_row.empty:
            v2 = v2_row.iloc[0]
            if not row["seal_label"]:
                row["seal_label"] = str(v2.get("seal_label", "") or "")
            row["fused_cooling_status_v2"] = v2.get("fused_cooling_status_v2", "")
            row["fused_cooling_rationale_v2"] = v2.get("fused_cooling_rationale_v2", "")
            row["q75_dah_12h_v2"] = v2.get("q75_12h", np.nan)
            row["count_12h_v2"] = v2.get("count_12h", np.nan)
        else:
            row["fused_cooling_status_v2"] = ""
            row["fused_cooling_rationale_v2"] = ""
            row["q75_dah_12h_v2"] = np.nan
            row["count_12h_v2"] = np.nan

        hourly_df = raw_map.get(file_name)
        if hourly_df is None:
            row["residual_status_v1"] = "cooling_residual_missing_raw_data"
            rows.append(row)
            continue

        hourly = resample_hourly(hourly_df)
        row["raw_start"] = pd.to_datetime(hourly["time"].min())
        row["raw_end"] = pd.to_datetime(hourly["time"].max())
        row["raw_duration_h"] = float((hourly["time"].max() - hourly["time"].min()).total_seconds() / 3600.0)
        row["in_temp_start"] = float(hourly["in_temp"].iloc[0])
        row["in_temp_max"] = float(hourly["in_temp"].max())
        row["in_temp_end"] = float(hourly["in_temp"].iloc[-1])

        if top_block:
            seg, seg_summary = compute_residual_segment(hourly, pd.to_datetime(top_block["block_start"]), int(args.focus_hours))
            row.update(seg_summary)
            if not seg.empty:
                seg = seg.copy()
                seg["file"] = file_name
                hourly_rows.append(seg)

        row["residual_status_v1"] = residual_status(pd.Series(row), args)
        rows.append(row)

    run_df = pd.DataFrame(rows).sort_values(
        ["residual_status_v1", "file"],
        ascending=[True, True],
    ).reset_index(drop=True)
    hourly_segment_df = pd.concat(hourly_rows, ignore_index=True) if hourly_rows else pd.DataFrame()

    summary = {
        "run_count": int(len(run_df)),
        "status_counts": run_df["residual_status_v1"].value_counts(dropna=False).to_dict() if not run_df.empty else {},
        "candidate_runs": int(run_df["residual_status_v1"].eq("cooling_residual_supported_candidate").sum()) if not run_df.empty else 0,
        "validation_ready": bool(
            not run_df.empty
            and int(
                (
                    (run_df["seal_label"] == "seal")
                    & run_df["residual_status_v1"].isin(["cooling_residual_supported_candidate", "cooling_residual_weak_or_confounded", "cooling_residual_negative"])
                    & run_df["has_cooling_block"].fillna(False)
                ).sum()
            )
            >= 1
            and int(
                (
                    (run_df["seal_label"] == "unseal")
                    & run_df["residual_status_v1"].isin(["cooling_residual_supported_candidate", "cooling_residual_weak_or_confounded", "cooling_residual_negative"])
                    & run_df["has_cooling_block"].fillna(False)
                ).sum()
            )
            >= 1
        ),
        "sealed_with_cooling_block": int(((run_df["seal_label"] == "seal") & run_df["has_cooling_block"].fillna(False)).sum()) if not run_df.empty else 0,
        "unsealed_with_cooling_block": int(((run_df["seal_label"] == "unseal") & run_df["has_cooling_block"].fillna(False)).sum()) if not run_df.empty else 0,
    }
    return run_df, hourly_segment_df, summary


def write_report(path: str, run_df: pd.DataFrame, summary: Dict[str, Any]) -> None:
    lines = [
        "# Cooling Residual Probe v1",
        "",
        "- 目的：把 `外部高湿 + 热源停止后的冷却段` 从“直接看 RH 回升”改成“先扣除纯降温导致的 RH 理论回升，再看是否存在额外 AH/RH 残差”。",
        "",
        f"- run_count: `{summary['run_count']}`",
        f"- status_counts: `{summary['status_counts']}`",
        f"- candidate_runs: `{summary['candidate_runs']}`",
        f"- sealed_with_cooling_block: `{summary['sealed_with_cooling_block']}`",
        f"- unsealed_with_cooling_block: `{summary['unsealed_with_cooling_block']}`",
        f"- validation_ready: `{summary['validation_ready']}`",
        "",
        "## 物理定义",
        "",
        "- `RH_pred_const_AH`：以冷却起点的 `AH_in` 为常量，只根据内部温度下降推算理论 RH。",
        "- `excess_rh_const_ah`：实际 `RH_in - RH_pred_const_AH`，表示超出“纯降温效应”的额外 RH 回升。",
        "- `excess_ah_const`：实际 `AH_in - AH_in(start)`，表示冷却后内部是否真的获得了额外水汽，而不是只因温度下降导致 RH 表观回升。",
        "",
        "## 当前判断",
        "",
    ]

    if summary["validation_ready"]:
        lines.append("- 当前 sealed/unsealed 两侧都已经具备冷却残差参考，可继续推进为正式验证分支。")
    else:
        lines.append("- 当前还不能把冷却段升成已验收能力，因为 `sealed heated cooling` 参考仍然缺失或未形成可用冷却段。")

    lines.extend(["", "## 运行级结果", ""])
    for _, row in run_df.iterrows():
        lines.append(
            f"- {row['file']} | seal={row.get('seal_label', '')} | status={row.get('residual_status_v1', '')} | "
            f"has_block={bool(row.get('has_cooling_block', False))} | q75_delta_half_dAH_6h={row.get('q75_delta_half_dAH')} | "
            f"end_excess_ah_4h={row.get('end_excess_ah_4h')} | pos_area_excess_ah_4h={row.get('pos_area_excess_ah_4h')} | "
            f"max_excess_rh_4h={row.get('max_excess_rh_4h')} | headroom_raw_4h={row.get('mean_out_headroom_ah_raw_4h')} | "
            f"v2={row.get('fused_cooling_status_v2', '')}"
        )

    lines.extend(
        [
            "",
            "## 解释",
            "",
            "- 如果 `excess_ah_const` 为正，说明冷却段内部不只是“温度下降导致 RH 看起来升高”，而是真实获得了额外绝对湿度。",
            "- 如果 `excess_rh_const_ah` 为正但 `excess_ah_const` 不显著，说明更可能是温度效应、局部扰动或短时数值抖动，而不是稳健的进湿证据。",
            "- 如果 `mean_out_headroom_ah_raw` 为负，说明在该冷却段里外部绝对湿度本身就低于冷却起点的内部绝对湿度；这种情况下即便 `dAH` 变得更“好看”，也不应直接解释成外部进湿。",
            "- 当前最关键的缺口不是阈值，而是 sealed 侧缺少真正可用的高湿冷却参考段；因此这条线当前最适合作为物理解释探针，而不是主判定分支。",
            "",
        ]
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    run_df, hourly_segment_df, summary = build_probe(args)

    outputs = {
        "run_summary_csv": os.path.join(args.output_dir, "cooling_residual_run_summary.csv"),
        "hourly_segment_csv": os.path.join(args.output_dir, "cooling_residual_hourly_segments.csv"),
        "report_md": os.path.join(args.output_dir, "cooling_residual_probe_report.md"),
        "report_json": os.path.join(args.output_dir, "cooling_residual_probe_report.json"),
    }

    run_df.to_csv(outputs["run_summary_csv"], index=False, encoding="utf-8-sig")
    hourly_segment_df.to_csv(outputs["hourly_segment_csv"], index=False, encoding="utf-8-sig")
    write_report(outputs["report_md"], run_df, summary)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
