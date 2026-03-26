#!/usr/bin/env python3
import argparse
import json
import os
import sys
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.scripts.lab_cooling_residual_probe_v1 import (
    collect_preprocessed_file_map,
    compute_residual_segment,
    extract_contiguous_blocks,
    make_window_args,
    resample_hourly,
)
from src.scripts.lab_ext_high_humidity_response_v1 import build_inputs, mark_cooling_windows
from src.scripts.lab_ext_high_humidity_response_v2 import run_multiscale_branch_v2
from src.scripts.lab_phase1_acceptance import Phase1Config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cooling residual probe v2 with onset-first and external-headroom gating")
    parser.add_argument("--input-dir", default=Phase1Config.input_dir)
    parser.add_argument("--input-zip", default=Phase1Config.input_zip)
    parser.add_argument("--metadata-xlsx", default=Phase1Config.metadata_xlsx)
    parser.add_argument("--output-dir", default="reports/lab_cooling_residual_probe_v2")
    parser.add_argument("--step-hours", type=int, default=1)
    parser.add_argument("--transition-near-hours", type=int, default=6)
    parser.add_argument("--similarity-k", type=int, default=5)
    parser.add_argument("--main-window-hours", type=int, default=6)
    parser.add_argument("--cooling-delta-temp-thresh", type=float, default=-0.3)
    parser.add_argument("--cooling-slope-temp-thresh", type=float, default=-0.01)
    parser.add_argument("--cooling-half-temp-thresh", type=float, default=-0.1)
    parser.add_argument("--heated-mean-dt-thresh", type=float, default=5.0)
    parser.add_argument("--focus-hours", type=int, default=4)
    parser.add_argument("--min-headroom-positive-ratio", type=float, default=0.25)
    parser.add_argument("--min-headroom-max-ah", type=float, default=0.20)
    parser.add_argument("--residual-end-ah-thresh", type=float, default=0.10)
    parser.add_argument("--residual-area-ah-thresh", type=float, default=0.10)
    parser.add_argument("--residual-max-rh-thresh", type=float, default=0.20)
    return parser.parse_args()


def compute_block_probe(
    hourly_df: pd.DataFrame,
    file_name: str,
    seal_label: str,
    block_row: pd.Series,
    args: argparse.Namespace,
) -> Dict[str, Any]:
    seg, summary = compute_residual_segment(hourly_df, pd.to_datetime(block_row["block_start"]), int(args.focus_hours))
    result: Dict[str, Any] = {
        "file": file_name,
        "seal_label": seal_label,
        "block_id": int(block_row["block_id"]),
        "block_start": pd.to_datetime(block_row["block_start"]),
        "block_end": pd.to_datetime(block_row["block_end"]),
        "window_count": int(block_row["window_count"]),
        "q75_delta_half_dAH": float(block_row["q75_delta_half_dAH"]),
        "median_delta_half_dAH": float(block_row["median_delta_half_dAH"]),
        "median_delta_in_temp": float(block_row["median_delta_in_temp"]),
        "mean_dT": float(block_row["mean_dT"]),
    }
    result.update(summary)

    if seg.empty:
        result["positive_headroom_ratio_4h"] = np.nan
        result["max_out_headroom_ah_raw_4h"] = np.nan
        result["start_out_headroom_ah"] = np.nan
        result["end_out_headroom_ah"] = np.nan
        result["headroom_gate_pass"] = False
        return result

    headroom = pd.to_numeric(seg["out_headroom_ah"], errors="coerce")
    result["positive_headroom_ratio_4h"] = float((headroom > 0).mean())
    result["max_out_headroom_ah_raw_4h"] = float(headroom.max())
    result["start_out_headroom_ah"] = float(headroom.iloc[0])
    result["end_out_headroom_ah"] = float(headroom.iloc[-1])
    result["headroom_gate_pass"] = bool(
        result["positive_headroom_ratio_4h"] >= float(args.min_headroom_positive_ratio)
        and result["max_out_headroom_ah_raw_4h"] >= float(args.min_headroom_max_ah)
    )
    return result


def residual_status_v2(row: pd.Series, args: argparse.Namespace) -> str:
    if not bool(row.get("has_any_cooling_block", False)):
        return "cooling_residual_v2_no_segment"
    if not bool(row.get("selected_block_exists", False)):
        return "cooling_residual_v2_no_external_headroom"

    end_excess = pd.to_numeric(pd.Series([row.get("end_excess_ah_4h")]), errors="coerce").iloc[0]
    pos_area = pd.to_numeric(pd.Series([row.get("pos_area_excess_ah_4h")]), errors="coerce").iloc[0]
    max_rh = pd.to_numeric(pd.Series([row.get("max_excess_rh_4h")]), errors="coerce").iloc[0]
    if (
        pd.notna(end_excess)
        and pd.notna(pos_area)
        and pd.notna(max_rh)
        and end_excess >= float(args.residual_end_ah_thresh)
        and pos_area >= float(args.residual_area_ah_thresh)
        and max_rh >= float(args.residual_max_rh_thresh)
    ):
        return "cooling_residual_v2_supported_candidate"
    return "cooling_residual_v2_weak_residual"


def build_probe(args: argparse.Namespace) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    main_args = make_window_args(args, int(args.main_window_hours))
    _, window_df, _ = build_inputs(main_args)
    cooling_window_df = mark_cooling_windows(window_df, main_args)
    cooling_window_df = cooling_window_df[cooling_window_df["expected_family"] == "ext_high_hum_with_heat"].copy()

    multiscale = run_multiscale_branch_v2(args)
    cooling_v2_df = multiscale["cooling_df"].copy()
    raw_map = collect_preprocessed_file_map(args)

    run_rows: List[Dict[str, Any]] = []
    block_rows: List[Dict[str, Any]] = []

    run_list = sorted(
        set(cooling_window_df["file"].dropna().tolist()) | set(cooling_v2_df["file"].dropna().tolist())
    )

    for file_name in run_list:
        run_windows = cooling_window_df[(cooling_window_df["file"] == file_name) & (cooling_window_df["cooling_response_flag"])].copy()
        seal_label = str(run_windows["seal_label"].iloc[0]) if not run_windows.empty else ""

        v2_row = cooling_v2_df.loc[cooling_v2_df["file"] == file_name]
        fused_status = ""
        fused_rationale = ""
        if not v2_row.empty:
            fused = v2_row.iloc[0]
            fused_status = str(fused.get("fused_cooling_status_v2", "") or "")
            fused_rationale = str(fused.get("fused_cooling_rationale_v2", "") or "")
            if not seal_label:
                seal_label = str(fused.get("seal_label", "") or "")

        blocks_df = extract_contiguous_blocks(run_windows, int(args.step_hours))
        hourly_df = raw_map.get(file_name)
        probe_rows: List[Dict[str, Any]] = []
        if hourly_df is not None and not blocks_df.empty:
            hourly = resample_hourly(hourly_df)
            for _, block_row in blocks_df.iterrows():
                probe = compute_block_probe(hourly, file_name, seal_label, block_row, args)
                block_rows.append(probe)
                probe_rows.append(probe)

        selected_probe: Dict[str, Any] | None = None
        selected_reason = "no_cooling_block"
        if probe_rows:
            valid = [row for row in probe_rows if bool(row.get("headroom_gate_pass", False))]
            if valid:
                valid.sort(key=lambda row: (pd.to_datetime(row["block_start"]), -float(row["max_out_headroom_ah_raw_4h"])))
                selected_probe = valid[0]
                selected_reason = "earliest_block_with_external_headroom"
            else:
                probe_rows.sort(key=lambda row: pd.to_datetime(row["block_start"]))
                selected_probe = probe_rows[0]
                selected_reason = "no_block_passes_external_headroom_gate"

        run_row: Dict[str, Any] = {
            "file": file_name,
            "seal_label": seal_label,
            "has_any_cooling_block": bool(len(probe_rows) > 0),
            "cooling_block_count": int(len(probe_rows)),
            "selected_block_exists": bool(selected_probe is not None and bool(selected_probe.get("headroom_gate_pass", False))),
            "selected_block_reason_v2": selected_reason,
            "fused_cooling_status_v2": fused_status,
            "fused_cooling_rationale_v2": fused_rationale,
        }
        if selected_probe is not None:
            run_row.update(selected_probe)
        run_row["residual_status_v2"] = residual_status_v2(pd.Series(run_row), args)
        run_rows.append(run_row)

    run_df = pd.DataFrame(run_rows).sort_values(["residual_status_v2", "file"]).reset_index(drop=True)
    block_df = pd.DataFrame(block_rows).sort_values(["file", "block_start"]).reset_index(drop=True) if block_rows else pd.DataFrame()

    summary = {
        "run_count": int(len(run_df)),
        "status_counts": run_df["residual_status_v2"].value_counts(dropna=False).to_dict() if not run_df.empty else {},
        "selected_block_count": int(run_df["selected_block_exists"].fillna(False).sum()) if not run_df.empty else 0,
        "headroom_gate_block_count": int(block_df["headroom_gate_pass"].fillna(False).sum()) if not block_df.empty else 0,
        "validation_ready": bool(
            not run_df.empty
            and int(((run_df["seal_label"] == "seal") & run_df["selected_block_exists"].fillna(False)).sum()) >= 1
            and int(((run_df["seal_label"] == "unseal") & run_df["selected_block_exists"].fillna(False)).sum()) >= 1
        ),
    }
    return run_df, block_df, summary


def write_report(path: str, run_df: pd.DataFrame, block_df: pd.DataFrame, summary: Dict[str, Any]) -> None:
    lines = [
        "# Cooling Residual Probe v2",
        "",
        "- 目的：把冷却段候选从“按 `delta_half_dAH` 最强块”改成“最早出现且外部确实有 AH 余量的块”，优先排除没有外部进湿条件的伪候选。",
        "",
        f"- run_count: `{summary['run_count']}`",
        f"- status_counts: `{summary['status_counts']}`",
        f"- selected_block_count: `{summary['selected_block_count']}`",
        f"- headroom_gate_block_count: `{summary['headroom_gate_block_count']}`",
        f"- validation_ready: `{summary['validation_ready']}`",
        "",
        "## 当前判断",
        "",
        "- v2 不再默认使用 `q75_delta_half_dAH` 最强块，而是优先选择最早出现、且 `外部 AH 余量` 满足硬门控的块。",
        "- 如果所有块都不满足 `positive_headroom_ratio` 和 `max_out_headroom_ah_raw` 的条件，则直接输出 `cooling_residual_v2_no_external_headroom`。",
        "",
        "## 运行级结果",
        "",
    ]

    for _, row in run_df.iterrows():
        lines.append(
            f"- {row['file']} | seal={row.get('seal_label', '')} | status={row.get('residual_status_v2', '')} | "
            f"selected_reason={row.get('selected_block_reason_v2', '')} | block_start={row.get('block_start')} | "
            f"positive_headroom_ratio_4h={row.get('positive_headroom_ratio_4h')} | max_out_headroom_ah_raw_4h={row.get('max_out_headroom_ah_raw_4h')} | "
            f"end_excess_ah_4h={row.get('end_excess_ah_4h')} | pos_area_excess_ah_4h={row.get('pos_area_excess_ah_4h')} | "
            f"v2_multiscale={row.get('fused_cooling_status_v2', '')}"
        )

    if not block_df.empty:
        lines.extend(["", "## 块级诊断", ""])
        for _, row in block_df.iterrows():
            lines.append(
                f"- {row['file']} | block={int(row['block_id'])} | start={row['block_start']} | "
                f"positive_headroom_ratio_4h={row.get('positive_headroom_ratio_4h')} | "
                f"max_out_headroom_ah_raw_4h={row.get('max_out_headroom_ah_raw_4h')} | "
                f"end_excess_ah_4h={row.get('end_excess_ah_4h')} | headroom_gate_pass={bool(row.get('headroom_gate_pass', False))}"
            )

    lines.extend(
        [
            "",
            "## 解释",
            "",
            "- `外部 AH 余量` 为负，表示该冷却段里外部绝对湿度低于段起点内部绝对湿度；这时即便 `dAH` 相对改善，也不应直接解释为外部高湿空气进入。",
            "- 这一步的目标不是把 candidate 数量抬高，而是更早地识别“没有外部进湿物理前提”的冷却伪证据。",
            "- 因此，若 v2 仍没有产出有效块，当前正确结论应是：冷却段还不具备升主分支条件，而不是继续调阈值强行抬分。",
            "",
        ]
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    run_df, block_df, summary = build_probe(args)
    outputs = {
        "run_summary_csv": os.path.join(args.output_dir, "cooling_residual_v2_run_summary.csv"),
        "block_csv": os.path.join(args.output_dir, "cooling_residual_v2_blocks.csv"),
        "report_md": os.path.join(args.output_dir, "cooling_residual_probe_v2_report.md"),
        "report_json": os.path.join(args.output_dir, "cooling_residual_probe_v2_report.json"),
    }

    run_df.to_csv(outputs["run_summary_csv"], index=False, encoding="utf-8-sig")
    block_df.to_csv(outputs["block_csv"], index=False, encoding="utf-8-sig")
    write_report(outputs["report_md"], run_df, block_df, summary)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
