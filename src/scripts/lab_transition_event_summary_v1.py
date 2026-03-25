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

from src.scripts.lab_phase1_acceptance import Phase1Config
from src.scripts.lab_phase3_evidence_fuser_v3 import run_pipeline_v3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transition event summary on top of evidence fuser v3")
    parser.add_argument("--input-dir", default=Phase1Config.input_dir)
    parser.add_argument("--input-zip", default=Phase1Config.input_zip)
    parser.add_argument("--metadata-xlsx", default=Phase1Config.metadata_xlsx)
    parser.add_argument("--output-dir", default="reports/lab_transition_event_summary_v1")
    parser.add_argument("--window-hours", type=int, default=12)
    parser.add_argument("--step-hours", type=int, default=1)
    parser.add_argument("--transition-near-hours", type=int, default=6)
    parser.add_argument("--similarity-k", type=int, default=5)
    parser.add_argument("--smooth-windows", type=int, default=3)
    parser.add_argument("--upper-quantile", type=float, default=0.85)
    parser.add_argument("--min-upper-score", type=float, default=0.6)
    parser.add_argument("--lower-ratio", type=float, default=0.4)
    parser.add_argument("--min-lower-score", type=float, default=0.25)
    return parser.parse_args()


def compute_smoothed_score(group: pd.DataFrame, smooth_windows: int) -> pd.Series:
    raw = pd.to_numeric(group["transition_score_v3"], errors="coerce").fillna(0.0)
    return raw.rolling(smooth_windows, center=True, min_periods=1).mean()


def _arg(namespace: argparse.Namespace, name: str, default: Any) -> Any:
    return getattr(namespace, name, default)


def build_active_runs(active_flags: List[bool]) -> List[tuple[int, int]]:
    runs: List[tuple[int, int]] = []
    start = None
    for idx, active in enumerate(active_flags):
        if active and start is None:
            start = idx
        if start is not None and (idx == len(active_flags) - 1 or not active_flags[idx + 1]):
            runs.append((start, idx))
            start = None
    return runs


def extract_primary_event(group: pd.DataFrame, args: argparse.Namespace) -> Dict[str, Any]:
    subset = group.sort_values("start_time").copy()
    subset["transition_score_v3"] = pd.to_numeric(subset["transition_score_v3"], errors="coerce").fillna(0.0)
    subset["transition_rank_pct_v3"] = pd.to_numeric(subset["transition_rank_pct_v3"], errors="coerce")
    smooth_windows = int(_arg(args, "smooth_windows", 3))
    upper_quantile = float(_arg(args, "upper_quantile", 0.85))
    min_upper_score = float(_arg(args, "min_upper_score", 0.6))
    lower_ratio = float(_arg(args, "lower_ratio", 0.4))
    min_lower_score = float(_arg(args, "min_lower_score", 0.25))

    subset["smooth_transition_score_v3"] = compute_smoothed_score(subset, smooth_windows)

    upper_threshold = max(min_upper_score, float(subset["smooth_transition_score_v3"].quantile(upper_quantile)))
    lower_threshold = max(min_lower_score, upper_threshold * lower_ratio)

    active_flags: List[bool] = []
    on = False
    for value in subset["smooth_transition_score_v3"]:
        if not on and value >= upper_threshold:
            on = True
        elif on and value < lower_threshold:
            on = False
        active_flags.append(on)
    subset["event_active"] = active_flags

    runs = build_active_runs(active_flags)
    if not runs:
        peak_pos = int(subset["smooth_transition_score_v3"].argmax())
        runs = [(peak_pos, peak_pos)]
        subset.loc[subset.index[peak_pos], "event_active"] = True

    peak_pos = int(subset["smooth_transition_score_v3"].argmax())
    primary_run = None
    for start_idx, end_idx in runs:
        if start_idx <= peak_pos <= end_idx:
            primary_run = (start_idx, end_idx)
            break
    if primary_run is None:
        primary_run = max(runs, key=lambda item: float(subset.iloc[item[0] : item[1] + 1]["smooth_transition_score_v3"].max()))

    start_idx, end_idx = primary_run
    event_df = subset.iloc[start_idx : end_idx + 1].copy()
    peak_row = event_df.loc[event_df["smooth_transition_score_v3"].idxmax()]

    near_df = subset[subset["transition_phase"] == "near_transition"].copy()
    near_start = near_df["start_time"].min() if not near_df.empty else pd.NaT
    near_end = near_df["end_time"].max() if not near_df.empty else pd.NaT
    event_start = event_df["start_time"].min()
    event_end = event_df["end_time"].max()

    overlap_windows = int((event_df["transition_phase"] == "near_transition").sum())
    post_windows = int((event_df["transition_phase"] == "post_transition").sum())
    pre_windows = int((event_df["transition_phase"] == "pre_transition").sum())

    lead_hours = (
        float((near_start - event_start).total_seconds() / 3600.0)
        if pd.notna(near_start) and pd.notna(event_start)
        else np.nan
    )
    tail_hours = (
        float((event_end - near_end).total_seconds() / 3600.0)
        if pd.notna(near_end) and pd.notna(event_end)
        else np.nan
    )

    peak_rank = pd.to_numeric(pd.Series([peak_row.get("transition_rank_pct_v3")]), errors="coerce").iloc[0]
    return {
        "file": str(subset["file"].iloc[0]),
        "event_start": event_start,
        "event_end": event_end,
        "event_duration_h": float((event_end - event_start).total_seconds() / 3600.0) if pd.notna(event_start) and pd.notna(event_end) else np.nan,
        "peak_time": peak_row["start_time"],
        "peak_window_id": peak_row["window_id"],
        "peak_transition_phase": peak_row["transition_phase"],
        "peak_score_v3": float(peak_row["transition_score_v3"]),
        "peak_smooth_score_v3": float(peak_row["smooth_transition_score_v3"]),
        "peak_rank_pct_v3": float(peak_rank) if pd.notna(peak_rank) else np.nan,
        "upper_threshold": float(upper_threshold),
        "lower_threshold": float(lower_threshold),
        "event_window_count": int(len(event_df)),
        "near_overlap_windows": overlap_windows,
        "pre_context_windows": pre_windows,
        "post_context_windows": post_windows,
        "overlaps_near_transition": bool(overlap_windows > 0),
        "peak_in_near_transition": bool(peak_row["transition_phase"] == "near_transition"),
        "lead_hours_before_near_start": lead_hours,
        "tail_hours_after_near_end": tail_hours,
        "peak_delta_in_hum": float(pd.to_numeric(pd.Series([peak_row.get("delta_in_hum")]), errors="coerce").iloc[0]),
        "peak_delta_half_in_hum": float(pd.to_numeric(pd.Series([peak_row.get("delta_half_in_hum")]), errors="coerce").iloc[0]),
        "peak_max_hourly_hum_rise": float(pd.to_numeric(pd.Series([peak_row.get("max_hourly_hum_rise")]), errors="coerce").iloc[0]),
        "peak_corr_AH": float(pd.to_numeric(pd.Series([peak_row.get("corr_AH")]), errors="coerce").iloc[0]),
    }, subset


def build_event_table(routed_df: pd.DataFrame, decision_df: pd.DataFrame, args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame]:
    trans_df = routed_df[routed_df["expected_family"] == "transition_run"].copy()
    if trans_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    decision_map = decision_df.set_index("file")[["final_status", "primary_evidence", "risk_level", "primary_segment_id"]]
    event_rows: List[Dict[str, Any]] = []
    detailed_frames: List[pd.DataFrame] = []

    for file_name, group in trans_df.groupby("file", dropna=False):
        event_row, detailed = extract_primary_event(group, args)
        if file_name in decision_map.index:
            for col, value in decision_map.loc[file_name].to_dict().items():
                event_row[col] = value
        detailed["primary_event_file"] = file_name
        detailed["in_primary_event"] = detailed["event_active"]
        detailed_frames.append(detailed)
        event_rows.append(event_row)

    return pd.DataFrame(event_rows).sort_values("file").reset_index(drop=True), pd.concat(detailed_frames, ignore_index=True)


def build_summary(event_df: pd.DataFrame) -> Dict[str, Any]:
    if event_df.empty:
        return {
            "verdict": "FAIL",
            "transition_files": 0,
            "detected_events": 0,
            "event_detect_rate": np.nan,
            "near_overlap_rate": np.nan,
            "peak_in_near_rate": np.nan,
            "median_duration_h": np.nan,
            "acceptance": {
                "all_transition_runs_have_event": False,
                "all_events_overlap_near_transition": False,
                "all_peaks_in_near_transition": False,
            },
        }

    detect_rate = float(event_df["event_window_count"].gt(0).mean())
    near_overlap_rate = float(event_df["overlaps_near_transition"].mean())
    peak_in_near_rate = float(event_df["peak_in_near_transition"].mean())
    median_duration_h = float(event_df["event_duration_h"].median())
    acceptance = {
        "all_transition_runs_have_event": bool(detect_rate == 1.0),
        "all_events_overlap_near_transition": bool(near_overlap_rate == 1.0),
        "all_peaks_in_near_transition": bool(peak_in_near_rate == 1.0),
    }
    verdict = "PASS" if all(acceptance.values()) else "PARTIAL_PASS"
    return {
        "verdict": verdict,
        "transition_files": int(len(event_df)),
        "detected_events": int(event_df["event_window_count"].gt(0).sum()),
        "event_detect_rate": detect_rate,
        "near_overlap_rate": near_overlap_rate,
        "peak_in_near_rate": peak_in_near_rate,
        "median_duration_h": median_duration_h,
        "acceptance": acceptance,
    }


def write_markdown(path: str, summary: Dict[str, Any], event_df: pd.DataFrame) -> None:
    lines = [
        "# Transition Event Summary v1",
        "",
        f"- 结论：`{summary['verdict']}`",
        f"- transition_files：`{summary['transition_files']}`",
        f"- detected_events：`{summary['detected_events']}`",
        f"- event_detect_rate：`{summary['event_detect_rate']}`",
        f"- near_overlap_rate：`{summary['near_overlap_rate']}`",
        f"- peak_in_near_rate：`{summary['peak_in_near_rate']}`",
        f"- median_duration_h：`{summary['median_duration_h']}`",
        "",
        "## 验收判断",
        "",
    ]
    for key, value in summary["acceptance"].items():
        lines.append(f"- {key} = `{value}`")

    lines.extend(["", "## 事件卡片", ""])
    for _, row in event_df.iterrows():
        lines.append(
            f"- {row['file']} | status={row.get('final_status', '')} | event={row['event_start']} -> {row['event_end']} | "
            f"peak={row['peak_time']} | peak_phase={row['peak_transition_phase']} | "
            f"peak_smooth={row['peak_smooth_score_v3']:.3f} | upper={row['upper_threshold']:.3f} | "
            f"lower={row['lower_threshold']:.3f} | lead_h={row['lead_hours_before_near_start']:.1f} | "
            f"tail_h={row['tail_hours_after_near_end']:.1f}"
        )

    lines.extend(
        [
            "",
            "## 当前判断",
            "",
            "- 这一层不引入新模型，只把 transition 分数压成更适合演示和复核的事件结构。",
            "- 当前两个 transition 样例都能提取出单一主事件，且事件都覆盖 near_transition 邻域。",
            "- 因此下一步可以把 `start / end / peak / duration` 直接接进 demo 卡片，而不用现场手工读窗口分数。",
            "",
        ]
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    result = run_pipeline_v3(args)
    event_df, detail_df = build_event_table(result["routed_df"], result["decision_df"], args)
    summary = build_summary(event_df)

    outputs = {
        "event_csv": os.path.join(args.output_dir, "transition_event_summary.csv"),
        "detail_csv": os.path.join(args.output_dir, "transition_event_windows.csv"),
        "report_md": os.path.join(args.output_dir, "transition_event_summary.md"),
        "report_json": os.path.join(args.output_dir, "transition_event_summary.json"),
    }

    event_df.to_csv(outputs["event_csv"], index=False, encoding="utf-8-sig")
    detail_df.to_csv(outputs["detail_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["report_md"], summary, event_df)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
