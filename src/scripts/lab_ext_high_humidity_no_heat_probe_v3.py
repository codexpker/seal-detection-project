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
from src.scripts.lab_ext_high_humidity_response_v2 import run_multiscale_branch_v2
from src.scripts.lab_phase1_acceptance import Phase1Config


DEFAULT_NO_HEAT_PROBE_V3_CONFIG: Dict[str, Any] = {
    "input_dir": Phase1Config.input_dir,
    "input_zip": Phase1Config.input_zip,
    "metadata_xlsx": Phase1Config.metadata_xlsx,
    "output_dir": "reports/lab_ext_high_humidity_no_heat_probe_v3",
    "early_hours": 6,
    "late_hours": 6,
    "step_hours": 1,
    "transition_near_hours": 6,
    "similarity_k": 5,
    "onset_response_ratio_thresh": 0.75,
    "onset_rh_gain_thresh": 0.0,
    "late_ah_decay_floor": -0.01,
    "main_long_gap_thresh": 0.05,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="External high-humidity no-heat probe v3 with onset and persistence features")
    parser.add_argument("--input-dir", default=Phase1Config.input_dir)
    parser.add_argument("--input-zip", default=Phase1Config.input_zip)
    parser.add_argument("--metadata-xlsx", default=Phase1Config.metadata_xlsx)
    parser.add_argument("--output-dir", default="reports/lab_ext_high_humidity_no_heat_probe_v3")
    parser.add_argument("--early-hours", type=int, default=6)
    parser.add_argument("--late-hours", type=int, default=6)
    parser.add_argument("--step-hours", type=int, default=1)
    parser.add_argument("--transition-near-hours", type=int, default=6)
    parser.add_argument("--similarity-k", type=int, default=5)
    parser.add_argument("--onset-response-ratio-thresh", type=float, default=0.75)
    parser.add_argument("--onset-rh-gain-thresh", type=float, default=0.0)
    parser.add_argument("--late-ah-decay-floor", type=float, default=-0.01)
    parser.add_argument("--main-long-gap-thresh", type=float, default=0.05)
    return parser.parse_args()


def ensure_no_heat_probe_args(args: argparse.Namespace) -> argparse.Namespace:
    payload = {
        key: getattr(args, key, value)
        for key, value in DEFAULT_NO_HEAT_PROBE_V3_CONFIG.items()
    }
    return argparse.Namespace(**payload)


def collect_no_heat_hourly_runs(args: argparse.Namespace) -> Dict[str, pd.DataFrame]:
    cfg = cc.Config(
        input_dir=args.input_dir,
        input_zip=args.input_zip,
        metadata_xlsx=args.metadata_xlsx,
        output_dir=args.output_dir,
        window_hours=12,
        step_hours=max(int(args.step_hours), 1),
    )
    metadata_df = cc.load_metadata_manifest(args.metadata_xlsx)
    metadata_map = {row["data_file_name"]: row.to_dict() for _, row in metadata_df.iterrows()}

    run_map: Dict[str, pd.DataFrame] = {}
    with tempfile.TemporaryDirectory(prefix="no_heat_probe_v3_") as tmp_dir:
        files = cc.collect_input_files(cfg, tmp_dir)
        for path in files:
            file_name = cc.normalize_filename_token(os.path.basename(path))
            meta_row = dict(metadata_map.get(file_name, {}))
            if cc.expected_family_from_manifest(meta_row) != "ext_high_hum_no_heat":
                continue
            sheets = cc.load_excel_sheets(path)
            for _, raw_df in sheets:
                try:
                    df = cc.preprocess_df(raw_df)
                except Exception:
                    continue
                if df.empty:
                    continue
                hourly = (
                    df.set_index("time")
                    .resample("1h")
                    .mean(numeric_only=True)
                    .interpolate(limit_direction="both")
                    .reset_index()
                )
                run_map[file_name] = hourly
                break
    return run_map


def summarize_phase(phase_df: pd.DataFrame) -> Dict[str, float]:
    if phase_df.empty:
        return {
            "hours": 0,
            "delta_out_h": np.nan,
            "delta_in_h": np.nan,
            "delta_ah_in": np.nan,
            "headroom_area": np.nan,
            "respond_in_h_pos_ratio": np.nan,
            "respond_ah_pos_ratio": np.nan,
            "rh_gain_per_out": np.nan,
            "ah_decay_per_headroom": np.nan,
        }

    drive = pd.to_numeric(phase_df["d_out_h"], errors="coerce") > 0
    delta_out_h = float(phase_df["out_hum"].iloc[-1] - phase_df["out_hum"].iloc[0])
    delta_in_h = float(phase_df["in_hum"].iloc[-1] - phase_df["in_hum"].iloc[0])
    delta_ah_in = float(phase_df["AH_in"].iloc[-1] - phase_df["AH_in"].iloc[0])
    headroom_area = float(np.trapezoid(pd.to_numeric(phase_df["headroom_ah"], errors="coerce").clip(lower=0.0), dx=1))

    return {
        "hours": int(len(phase_df)),
        "delta_out_h": delta_out_h,
        "delta_in_h": delta_in_h,
        "delta_ah_in": delta_ah_in,
        "headroom_area": headroom_area,
        "respond_in_h_pos_ratio": float((phase_df.loc[drive, "d_in_h"] > 0).mean()) if drive.any() else np.nan,
        "respond_ah_pos_ratio": float((phase_df.loc[drive, "d_ah_in"] > 0).mean()) if drive.any() else np.nan,
        "rh_gain_per_out": float(delta_in_h / delta_out_h) if abs(delta_out_h) > 1e-6 else np.nan,
        "ah_decay_per_headroom": float(delta_ah_in / max(headroom_area, 1e-6)),
    }


def build_probe_table(args: argparse.Namespace) -> pd.DataFrame:
    run_map = collect_no_heat_hourly_runs(args)
    multiscale = run_multiscale_branch_v2(args)
    no_heat_v2 = multiscale["no_heat_df"].copy()

    rows: List[Dict[str, Any]] = []
    for file_name, hourly in run_map.items():
        hr = hourly.copy()
        hr["headroom_ah"] = pd.to_numeric(hr["AH_out"], errors="coerce") - pd.to_numeric(hr["AH_in"], errors="coerce")
        hr["d_out_h"] = pd.to_numeric(hr["out_hum"], errors="coerce").diff()
        hr["d_in_h"] = pd.to_numeric(hr["in_hum"], errors="coerce").diff()
        hr["d_ah_in"] = pd.to_numeric(hr["AH_in"], errors="coerce").diff()

        early = hr.iloc[: max(int(args.early_hours), 2)].copy()
        late = hr.iloc[-max(int(args.late_hours), 2) :].copy()
        early_stats = summarize_phase(early)
        late_stats = summarize_phase(late)

        row: Dict[str, Any] = {
            "file": file_name,
            "duration_h": float((hr["time"].iloc[-1] - hr["time"].iloc[0]).total_seconds() / 3600.0),
        }
        for prefix, stats in [("early", early_stats), ("late", late_stats)]:
            for key, value in stats.items():
                row[f"{prefix}_{key}"] = value

        v2_row = no_heat_v2.loc[no_heat_v2["file"] == file_name]
        if not v2_row.empty:
            v2 = v2_row.iloc[0]
            row["seal_label"] = str(v2.get("seal_label", "") or "")
            row["fused_no_heat_status_v2"] = str(v2.get("fused_no_heat_status_v2", "") or "")
            row["fused_no_heat_rationale_v2"] = str(v2.get("fused_no_heat_rationale_v2", "") or "")
            row["score_6h"] = float(v2.get("score_6h", np.nan))
            row["score_12h"] = float(v2.get("score_12h", np.nan))
            row["score_main_minus_long"] = float(v2.get("score_main_minus_long", np.nan))
        else:
            row["seal_label"] = ""
            row["fused_no_heat_status_v2"] = ""
            row["fused_no_heat_rationale_v2"] = ""
            row["score_6h"] = np.nan
            row["score_12h"] = np.nan
            row["score_main_minus_long"] = np.nan

        onset_positive = bool(
            pd.notna(row["early_respond_in_h_pos_ratio"])
            and row["early_respond_in_h_pos_ratio"] >= float(args.onset_response_ratio_thresh)
            and pd.notna(row["early_rh_gain_per_out"])
            and row["early_rh_gain_per_out"] > float(args.onset_rh_gain_thresh)
        )
        # Keep the persistence rule explicit instead of collapsing into a black-box score.
        late_persistence = bool(
            pd.notna(row["late_respond_in_h_pos_ratio"])
            and row["late_respond_in_h_pos_ratio"] >= float(args.onset_response_ratio_thresh)
            and pd.notna(row["score_main_minus_long"])
            and row["score_main_minus_long"] < float(args.main_long_gap_thresh)
        )
        breathing_bias = bool(
            pd.notna(row["late_rh_gain_per_out"])
            and pd.notna(row["early_rh_gain_per_out"])
            and row["late_rh_gain_per_out"] > row["early_rh_gain_per_out"]
            and pd.notna(row["late_ah_decay_per_headroom"])
            and row["late_ah_decay_per_headroom"] >= float(args.late_ah_decay_floor)
        )

        if not onset_positive:
            status = "ext_high_hum_no_heat_probe_negative"
            rationale = "early_response_absent"
        elif late_persistence and breathing_bias:
            status = "ext_high_hum_no_heat_probe_breathing_watch"
            rationale = "late_persistence_with_low_ah_decay"
        else:
            status = "ext_high_hum_no_heat_probe_supported"
            rationale = "early_response_present_without_persistent_breathing_pattern"

        row["onset_positive_v3"] = onset_positive
        row["late_persistence_v3"] = late_persistence
        row["breathing_bias_v3"] = breathing_bias
        row["probe_status_v3"] = status
        row["probe_rationale_v3"] = rationale
        rows.append(row)

    return pd.DataFrame(rows).sort_values(["probe_status_v3", "file"]).reset_index(drop=True)


def build_summary(probe_df: pd.DataFrame) -> Dict[str, Any]:
    return {
        "run_count": int(len(probe_df)),
        "status_counts": probe_df["probe_status_v3"].value_counts(dropna=False).to_dict() if not probe_df.empty else {},
        "onset_positive_count": int(probe_df["onset_positive_v3"].fillna(False).sum()) if not probe_df.empty else 0,
        "late_persistence_count": int(probe_df["late_persistence_v3"].fillna(False).sum()) if not probe_df.empty else 0,
        "breathing_bias_count": int(probe_df["breathing_bias_v3"].fillna(False).sum()) if not probe_df.empty else 0,
    }


def run_no_heat_probe_v3(args: argparse.Namespace) -> Dict[str, Any]:
    cfg = ensure_no_heat_probe_args(args)
    probe_df = build_probe_table(cfg)
    summary = build_summary(probe_df)
    return {
        "probe_df": probe_df,
        "summary": summary,
    }


def write_report(path: str, probe_df: pd.DataFrame, summary: Dict[str, Any], args: argparse.Namespace) -> None:
    lines = [
        "# External High-Humidity No-Heat Probe v3",
        "",
        "- 目的：把 `外部高湿-无热源` 从“长窗静态差异”进一步收敛成 `早段响应 + 晚段持续性` 的三态解释。",
        "",
        f"- run_count: `{summary['run_count']}`",
        f"- status_counts: `{summary['status_counts']}`",
        f"- onset_positive_count: `{summary['onset_positive_count']}`",
        f"- late_persistence_count: `{summary['late_persistence_count']}`",
        f"- breathing_bias_count: `{summary['breathing_bias_count']}`",
        "",
        "## 规则解释",
        "",
        f"- `onset_positive_v3`: 前 `{int(args.early_hours)}` 小时里，外部 RH 上升时，内部 RH 是否也同步上升，并且 `rh_gain_per_out > {float(args.onset_rh_gain_thresh):.2f}`。",
        f"- `late_persistence_v3`: 后 `{int(args.late_hours)}` 小时里，这种同步性是否仍然持续，且 `6h` 主尺度不再明显强于 `12h` 长尺度。",
        f"- `breathing_bias_v3`: 后段 `RH` 响应更强，同时 `AH` 衰减/驱动力 比例接近 0，提示更像 `呼吸/释湿` 而不是单纯前段进湿响应。",
        "",
        "## 当前判断",
        "",
        "- 这一步没有引入新模型，而是把当前 `supported / negative / breathing_watch` 三态进一步物理化。",
        "- 如果后续继续接回主流程，建议优先把它作为 `review / demo` 的补充解释，而不是直接替换全局默认判定。",
        "",
        "## 运行级结果",
        "",
    ]

    for _, row in probe_df.iterrows():
        lines.append(
            f"- {row['file']} | seal={row['seal_label']} | probe={row['probe_status_v3']} | "
            f"early_resp_ratio={row['early_respond_in_h_pos_ratio']:.3f} | early_rh_gain={row['early_rh_gain_per_out']:.3f} | "
            f"late_resp_ratio={row['late_respond_in_h_pos_ratio']:.3f} | late_rh_gain={row['late_rh_gain_per_out']:.3f} | "
            f"late_ah_decay_per_headroom={row['late_ah_decay_per_headroom']:.3f} | v2={row['fused_no_heat_status_v2']} | "
            f"rationale={row['probe_rationale_v3']}"
        )

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = ensure_no_heat_probe_args(parse_args())
    os.makedirs(args.output_dir, exist_ok=True)

    result = run_no_heat_probe_v3(args)
    probe_df = result["probe_df"]
    summary = result["summary"]

    outputs = {
        "probe_csv": os.path.join(args.output_dir, "ext_high_hum_no_heat_probe_v3.csv"),
        "report_md": os.path.join(args.output_dir, "ext_high_hum_no_heat_probe_v3_report.md"),
        "report_json": os.path.join(args.output_dir, "ext_high_hum_no_heat_probe_v3_report.json"),
    }

    probe_df.to_csv(outputs["probe_csv"], index=False, encoding="utf-8-sig")
    write_report(outputs["report_md"], probe_df, summary, args)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
