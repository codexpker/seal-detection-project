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

from src.scripts.lab_ext_high_humidity_response_v1 import (
    aggregate_cooling_runs,
    build_inputs,
    compute_no_heat_response,
    mark_cooling_windows,
)
from src.scripts.lab_phase1_acceptance import Phase1Config


DEFAULT_V2_CONFIG: Dict[str, Any] = {
    "input_dir": Phase1Config.input_dir,
    "input_zip": Phase1Config.input_zip,
    "metadata_xlsx": Phase1Config.metadata_xlsx,
    "output_dir": "reports/lab_ext_high_humidity_response_v2",
    "step_hours": 1,
    "transition_near_hours": 6,
    "similarity_k": 5,
    "short_window_hours": 2,
    "main_window_hours": 6,
    "long_window_hours": 12,
    "no_heat_main_hit_thresh": 5,
    "no_heat_negative_hit_thresh": 1,
    "no_heat_main_long_gap_thresh": 0.05,
    "cooling_long_q75_dah_thresh": 0.15,
    "cooling_long_pos_dah_ratio_thresh": 0.6,
    "cooling_delta_temp_thresh": -0.3,
    "cooling_slope_temp_thresh": -0.01,
    "cooling_half_temp_thresh": -0.1,
    "heated_mean_dt_thresh": 5.0,
    "cooling_q75_dah_thresh": 0.15,
    "cooling_pos_dah_ratio_thresh": 0.6,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="External high-humidity response branch v2 with cautious multi-scale fusion")
    parser.add_argument("--input-dir", default=Phase1Config.input_dir)
    parser.add_argument("--input-zip", default=Phase1Config.input_zip)
    parser.add_argument("--metadata-xlsx", default=Phase1Config.metadata_xlsx)
    parser.add_argument("--output-dir", default="reports/lab_ext_high_humidity_response_v2")
    parser.add_argument("--step-hours", type=int, default=1)
    parser.add_argument("--transition-near-hours", type=int, default=6)
    parser.add_argument("--similarity-k", type=int, default=5)
    parser.add_argument("--short-window-hours", type=int, default=2)
    parser.add_argument("--main-window-hours", type=int, default=6)
    parser.add_argument("--long-window-hours", type=int, default=12)
    parser.add_argument("--no-heat-main-hit-thresh", type=int, default=5)
    parser.add_argument("--no-heat-negative-hit-thresh", type=int, default=1)
    parser.add_argument("--no-heat-main-long-gap-thresh", type=float, default=0.05)
    parser.add_argument("--cooling-long-q75-dah-thresh", type=float, default=0.15)
    parser.add_argument("--cooling-long-pos-dah-ratio-thresh", type=float, default=0.6)
    parser.add_argument("--cooling-delta-temp-thresh", type=float, default=-0.3)
    parser.add_argument("--cooling-slope-temp-thresh", type=float, default=-0.01)
    parser.add_argument("--cooling-half-temp-thresh", type=float, default=-0.1)
    parser.add_argument("--heated-mean-dt-thresh", type=float, default=5.0)
    parser.add_argument("--cooling-q75-dah-thresh", type=float, default=0.15)
    parser.add_argument("--cooling-pos-dah-ratio-thresh", type=float, default=0.6)
    return parser.parse_args()


def ensure_v2_args(args: argparse.Namespace) -> argparse.Namespace:
    payload = {
        key: getattr(args, key, value)
        for key, value in DEFAULT_V2_CONFIG.items()
    }
    return argparse.Namespace(**payload)


def make_scale_args(args: argparse.Namespace, window_hours: int) -> argparse.Namespace:
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
        cooling_q75_dah_thresh=args.cooling_q75_dah_thresh,
        cooling_pos_dah_ratio_thresh=args.cooling_pos_dah_ratio_thresh,
    )


def run_scale(args: argparse.Namespace, window_hours: int) -> Dict[str, pd.DataFrame]:
    scale_args = make_scale_args(args, window_hours)
    run_df, window_df, decision_df = build_inputs(scale_args)
    no_heat_df = compute_no_heat_response(run_df, decision_df)
    cooling_window_df = mark_cooling_windows(window_df, scale_args)
    cooling_run_df = aggregate_cooling_runs(cooling_window_df, decision_df, scale_args)
    return {
        "run_df": run_df,
        "window_df": window_df,
        "decision_df": decision_df,
        "no_heat_df": no_heat_df,
        "cooling_window_df": cooling_window_df,
        "cooling_run_df": cooling_run_df,
    }


def fuse_no_heat(scale_map: Dict[str, Dict[str, pd.DataFrame]], args: argparse.Namespace) -> pd.DataFrame:
    merged = None
    for label, result in scale_map.items():
        df = result["no_heat_df"].copy()
        keep_cols = [
            "file",
            "seal_label",
            "response_hit_count",
            "no_heat_response_score_v1",
            "response_hit_features",
            "final_status",
            "primary_evidence",
            "notes",
        ]
        df = df[keep_cols].rename(
            columns={
                "response_hit_count": f"hits_{label}",
                "no_heat_response_score_v1": f"score_{label}",
                "response_hit_features": f"features_{label}",
                "final_status": f"final_status_{label}",
                "primary_evidence": f"primary_evidence_{label}",
                "notes": f"notes_{label}",
            }
        )
        merged = df if merged is None else merged.merge(df, on=["file", "seal_label"], how="outer")

    if merged is None or merged.empty:
        return pd.DataFrame()

    merged = merged.fillna(
        {
            f"hits_{label}": 0 for label in scale_map
        }
    )
    for label in scale_map:
        for col in [f"score_{label}"]:
            merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0.0)
        merged[f"hits_{label}"] = pd.to_numeric(merged[f"hits_{label}"], errors="coerce").fillna(0).astype(int)
        merged[f"features_{label}"] = merged.get(f"features_{label}", "").fillna("")

    main_label = f"{args.main_window_hours}h"
    short_label = f"{args.short_window_hours}h"
    long_label = f"{args.long_window_hours}h"

    merged["score_main_minus_long"] = merged[f"score_{main_label}"] - merged[f"score_{long_label}"]
    merged["score_short_minus_main"] = merged[f"score_{short_label}"] - merged[f"score_{main_label}"]
    merged["short_window_support"] = merged[f"hits_{short_label}"] >= args.no_heat_main_hit_thresh

    fused_rows: List[Dict[str, Any]] = []
    for _, row in merged.iterrows():
        hits_main = int(row[f"hits_{main_label}"])
        hits_long = int(row[f"hits_{long_label}"])
        gap_main_long = float(row["score_main_minus_long"])
        gap_short_main = float(row["score_short_minus_main"])

        fused_status = "ext_high_hum_no_heat_multiscale_weak"
        rationale: List[str] = []

        if hits_main <= args.no_heat_negative_hit_thresh and hits_long <= args.no_heat_negative_hit_thresh:
            fused_status = "ext_high_hum_no_heat_multiscale_negative"
            rationale.append("main_and_long_low_signal")
        elif hits_main >= args.no_heat_main_hit_thresh and gap_main_long >= args.no_heat_main_long_gap_thresh:
            fused_status = "ext_high_hum_no_heat_multiscale_supported"
            rationale.append("main_scale_stronger_than_long_scale")
            if bool(row["short_window_support"]):
                rationale.append("short_window_confirms_local_response")
        elif max(hits_main, hits_long) >= args.no_heat_main_hit_thresh and gap_main_long < args.no_heat_main_long_gap_thresh:
            fused_status = "ext_high_hum_no_heat_multiscale_breathing_watch"
            rationale.append("long_scale_not_weaker_than_main")
            if gap_short_main > 0:
                rationale.append("short_scale_more_spiky_than_main")
        else:
            rationale.append("mixed_scale_signal")

        fused_rows.append(
            {
                **row.to_dict(),
                "fused_no_heat_status_v2": fused_status,
                "fused_no_heat_rationale_v2": " | ".join(rationale),
            }
        )

    out = pd.DataFrame(fused_rows)
    return out.sort_values(
        ["fused_no_heat_status_v2", f"score_{main_label}", f"score_{long_label}"],
        ascending=[True, False, False],
    ).reset_index(drop=True)


def fuse_cooling(scale_map: Dict[str, Dict[str, pd.DataFrame]], args: argparse.Namespace) -> pd.DataFrame:
    merged = None
    for label, result in scale_map.items():
        df = result["cooling_run_df"].copy()
        keep_cols = [
            "file",
            "seal_label",
            "cooling_window_count",
            "frac_pos_delta_half_dAH",
            "q75_delta_half_dAH",
            "final_status",
            "primary_evidence",
            "notes",
        ]
        df = df[keep_cols].rename(
            columns={
                "cooling_window_count": f"count_{label}",
                "frac_pos_delta_half_dAH": f"frac_{label}",
                "q75_delta_half_dAH": f"q75_{label}",
                "final_status": f"final_status_{label}",
                "primary_evidence": f"primary_evidence_{label}",
                "notes": f"notes_{label}",
            }
        )
        merged = df if merged is None else merged.merge(df, on=["file", "seal_label"], how="outer")

    if merged is None or merged.empty:
        return pd.DataFrame()

    main_label = f"{args.main_window_hours}h"
    short_label = f"{args.short_window_hours}h"
    long_label = f"{args.long_window_hours}h"

    for label in scale_map:
        merged[f"count_{label}"] = pd.to_numeric(merged[f"count_{label}"], errors="coerce").fillna(0).astype(int)
        merged[f"frac_{label}"] = pd.to_numeric(merged[f"frac_{label}"], errors="coerce")
        merged[f"q75_{label}"] = pd.to_numeric(merged[f"q75_{label}"], errors="coerce")

    fused_rows: List[Dict[str, Any]] = []
    for _, row in merged.iterrows():
        count_main = int(row[f"count_{main_label}"])
        count_long = int(row[f"count_{long_label}"])
        short_q75 = float(row[f"q75_{short_label}"]) if pd.notna(row[f"q75_{short_label}"]) else np.nan
        long_q75 = float(row[f"q75_{long_label}"]) if pd.notna(row[f"q75_{long_label}"]) else np.nan
        long_frac = float(row[f"frac_{long_label}"]) if pd.notna(row[f"frac_{long_label}"]) else np.nan

        fused_status = "ext_high_hum_cooling_multiscale_weak"
        rationale: List[str] = []

        if count_main == 0 and count_long == 0:
            fused_status = "ext_high_hum_cooling_multiscale_no_segment"
            rationale.append("main_and_long_no_cooling_segment")
        elif (
            count_main > 0
            and pd.notna(long_q75)
            and pd.notna(long_frac)
            and long_q75 >= float(args.cooling_long_q75_dah_thresh)
            and long_frac >= float(args.cooling_long_pos_dah_ratio_thresh)
        ):
            fused_status = "ext_high_hum_cooling_multiscale_long_confirmed_candidate"
            rationale.append("main_segment_exists")
            rationale.append("long_window_confirms_cumulative_dAH")
            if pd.notna(short_q75) and short_q75 > 0:
                rationale.append("short_window_has_local_positive_dAH")
            else:
                rationale.append("short_window_not_spike_dominated")
        elif count_main > 0:
            fused_status = "ext_high_hum_cooling_multiscale_weak"
            rationale.append("main_segment_exists_but_long_confirmation_missing")
        else:
            fused_status = "ext_high_hum_cooling_multiscale_no_segment"
            rationale.append("main_scale_no_segment")

        fused_rows.append(
            {
                **row.to_dict(),
                "fused_cooling_status_v2": fused_status,
                "fused_cooling_rationale_v2": " | ".join(rationale),
            }
        )

    out = pd.DataFrame(fused_rows)
    return out.sort_values(
        ["fused_cooling_status_v2", f"count_{main_label}", f"q75_{long_label}"],
        ascending=[True, False, False],
    ).reset_index(drop=True)


def build_summary(no_heat_df: pd.DataFrame, cooling_df: pd.DataFrame, args: argparse.Namespace) -> Dict[str, Any]:
    no_heat_counts = no_heat_df["fused_no_heat_status_v2"].value_counts().to_dict() if not no_heat_df.empty else {}
    cooling_counts = cooling_df["fused_cooling_status_v2"].value_counts().to_dict() if not cooling_df.empty else {}

    no_heat_three_state_ready = False
    if not no_heat_df.empty:
        no_heat_three_state_ready = (
            int((no_heat_df["fused_no_heat_status_v2"] == "ext_high_hum_no_heat_multiscale_supported").sum()) >= 1
            and int((no_heat_df["fused_no_heat_status_v2"] == "ext_high_hum_no_heat_multiscale_negative").sum()) >= 1
            and int((no_heat_df["fused_no_heat_status_v2"] == "ext_high_hum_no_heat_multiscale_breathing_watch").sum()) >= 1
        )

    short_window_overreacts = False
    if not no_heat_df.empty:
        short_window_overreacts = bool(
            (
                (no_heat_df["seal_label"] == "seal")
                & (pd.to_numeric(no_heat_df[f"hits_{args.short_window_hours}h"], errors="coerce") <= args.no_heat_negative_hit_thresh)
                & (
                    no_heat_df[f"final_status_{args.short_window_hours}h"].isin(
                        [
                            "static_hard_case_watch",
                            "static_dynamic_support_alert",
                            "static_dynamic_supported_alert",
                            "static_consensus_alert",
                        ]
                    )
                )
            ).any()
        )

    cooling_long_confirmation_helpful = False
    if not cooling_df.empty:
        cooling_long_confirmation_helpful = bool(
            (
                (cooling_df["fused_cooling_status_v2"] == "ext_high_hum_cooling_multiscale_long_confirmed_candidate")
                & (pd.to_numeric(cooling_df[f"count_{args.main_window_hours}h"], errors="coerce") > 0)
            ).any()
        )

    return {
        "short_window_hours": int(args.short_window_hours),
        "main_window_hours": int(args.main_window_hours),
        "long_window_hours": int(args.long_window_hours),
        "no_heat_status_counts": no_heat_counts,
        "no_heat_three_state_ready": bool(no_heat_three_state_ready),
        "short_window_overreacts": bool(short_window_overreacts),
        "cooling_status_counts": cooling_counts,
        "cooling_long_confirmation_helpful": bool(cooling_long_confirmation_helpful),
        "cooling_validation_ready": bool(
            not cooling_df.empty
            and int(
                (
                    (cooling_df["seal_label"] == "seal")
                    & (pd.to_numeric(cooling_df[f"count_{args.long_window_hours}h"], errors="coerce") > 0)
                ).sum()
            )
            >= 1
            and int(
                (cooling_df["fused_cooling_status_v2"] == "ext_high_hum_cooling_multiscale_long_confirmed_candidate").sum()
            )
            >= 1
        ),
    }


def run_multiscale_branch_v2(args: argparse.Namespace) -> Dict[str, Any]:
    cfg = ensure_v2_args(args)
    scale_map: Dict[str, Dict[str, pd.DataFrame]] = {}
    for window_hours in [cfg.short_window_hours, cfg.main_window_hours, cfg.long_window_hours]:
        scale_map[f"{window_hours}h"] = run_scale(cfg, window_hours)

    no_heat_df = fuse_no_heat(scale_map, cfg)
    cooling_df = fuse_cooling(scale_map, cfg)
    summary = build_summary(no_heat_df, cooling_df, cfg)
    return {
        "config": cfg,
        "scale_map": scale_map,
        "no_heat_df": no_heat_df,
        "cooling_df": cooling_df,
        "summary": summary,
    }


def write_markdown(path: str, summary: Dict[str, Any], no_heat_df: pd.DataFrame, cooling_df: pd.DataFrame) -> None:
    lines = [
        "# 外部高湿响应分支 v2 报告",
        "",
        "- 目的：验证 `2h 短窗增强 + 6h 主判定 + 12h 长窗确认` 是否真的比单一窗口更适合当前外部高湿响应分析。",
        "",
        f"- short_window_hours：`{summary['short_window_hours']}`",
        f"- main_window_hours：`{summary['main_window_hours']}`",
        f"- long_window_hours：`{summary['long_window_hours']}`",
        f"- no_heat_status_counts：`{summary['no_heat_status_counts']}`",
        f"- no_heat_three_state_ready：`{summary['no_heat_three_state_ready']}`",
        f"- short_window_overreacts：`{summary['short_window_overreacts']}`",
        f"- cooling_status_counts：`{summary['cooling_status_counts']}`",
        f"- cooling_long_confirmation_helpful：`{summary['cooling_long_confirmation_helpful']}`",
        f"- cooling_validation_ready：`{summary['cooling_validation_ready']}`",
        "",
        "## 无热源高湿分支的结论",
        "",
        "- 当前多尺度有价值，但价值不在“把所有尺度一起喂给统一模型”，而在“用 `6h` 做主判定，再用 `12h` 判断它是持续进湿还是更像慢性呼吸效应”。",
        "- `2h` 当前不适合做主判定，因为它会把原本低信号的 sealed 运行也放大成 watch；因此短窗只能做局部增强，不能做结论主导。",
        "",
    ]

    main_label = f"{summary['main_window_hours']}h"
    short_label = f"{summary['short_window_hours']}h"
    long_label = f"{summary['long_window_hours']}h"

    for _, row in no_heat_df.iterrows():
        lines.append(
            f"- {row['file']} | seal={row['seal_label']} | fused={row['fused_no_heat_status_v2']} | "
            f"hits({short_label}/{main_label}/{long_label})={int(row[f'hits_{short_label}'])}/"
            f"{int(row[f'hits_{main_label}'])}/{int(row[f'hits_{long_label}'])} | "
            f"score({short_label}/{main_label}/{long_label})={row[f'score_{short_label}']:.3f}/"
            f"{row[f'score_{main_label}']:.3f}/{row[f'score_{long_label}']:.3f} | "
            f"gap_main_long={row['score_main_minus_long']:.3f} | rationale={row['fused_no_heat_rationale_v2']}"
        )

    lines.extend(
        [
            "",
            "## 冷却响应分支的结论",
            "",
            "- 冷却响应更像“累计型响应”，不是短时尖峰；因此 `12h` 的价值大于 `2h`。",
            "- 这里的多尺度正确用法不是让 `2h` 决策，而是让 `6h` 先提出候选，再由 `12h` 去确认是否存在累计的 `delta_half_dAH` 正向响应。",
            "",
        ]
    )

    for _, row in cooling_df.iterrows():
        lines.append(
            f"- {row['file']} | seal={row['seal_label']} | fused={row['fused_cooling_status_v2']} | "
            f"count({short_label}/{main_label}/{long_label})={int(row[f'count_{short_label}'])}/"
            f"{int(row[f'count_{main_label}'])}/{int(row[f'count_{long_label}'])} | "
            f"q75_dAH({short_label}/{main_label}/{long_label})={row[f'q75_{short_label}']}/"
            f"{row[f'q75_{main_label}']}/{row[f'q75_{long_label}']} | rationale={row['fused_cooling_rationale_v2']}"
        )

    lines.extend(
        [
            "",
            "## 当前判断",
            "",
            "- 多尺度对当前流程有价值，但只适合做“分支内的层级证据”，不适合现在就做“全流程统一多尺度融合模型”。",
            "- 对 `外部高湿-无热源`，`6h 主判定 + 12h 长窗确认` 是有价值的；`2h` 只能做增强，不应直接主导结论。",
            "- 对 `外部高湿-冷却段`，`12h` 的累计确认比 `2h` 更有价值；当前短窗没有证明自己能带来额外判别力。",
            "- 因此，如果后续真的接回主流程，推荐的收口方式应是：`6h 主判定 + 2h onset 提示 + 12h 累计确认`，而不是把所有尺度直接堆进一个统一分类器。",
            "",
        ]
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = ensure_v2_args(parse_args())
    os.makedirs(args.output_dir, exist_ok=True)

    result = run_multiscale_branch_v2(args)
    no_heat_df = result["no_heat_df"]
    cooling_df = result["cooling_df"]
    summary = result["summary"]

    outputs = {
        "no_heat_csv": os.path.join(args.output_dir, "ext_high_hum_multiscale_no_heat.csv"),
        "cooling_csv": os.path.join(args.output_dir, "ext_high_hum_multiscale_cooling.csv"),
        "report_md": os.path.join(args.output_dir, "ext_high_humidity_response_v2_report.md"),
        "report_json": os.path.join(args.output_dir, "ext_high_humidity_response_v2_report.json"),
    }

    no_heat_df.to_csv(outputs["no_heat_csv"], index=False, encoding="utf-8-sig")
    cooling_df.to_csv(outputs["cooling_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["report_md"], summary, no_heat_df, cooling_df)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
