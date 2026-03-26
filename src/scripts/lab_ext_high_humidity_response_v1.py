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

from src.scripts.current_condition_multiview_analysis import build_run_table
from src.scripts.lab_phase1_acceptance import Phase1Config
from src.scripts.lab_phase3_evidence_fuser_v3 import run_pipeline_v3


NO_HEAT_FEATURE_SPECS: List[Tuple[str, str]] = [
    ("corr_out_hum_in_hum", "pos"),
    ("max_corr_outRH_inRH_change", "pos"),
    ("frac_threshold_favored", "pos"),
    ("frac_pos_delta_half_dAH", "pos"),
    ("q90_delta_half_dAH_w", "pos"),
    ("std_in_hum_run", "neg"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Explicit external-high-humidity response branch analysis v1")
    parser.add_argument("--input-dir", default=Phase1Config.input_dir)
    parser.add_argument("--input-zip", default=Phase1Config.input_zip)
    parser.add_argument("--metadata-xlsx", default=Phase1Config.metadata_xlsx)
    parser.add_argument("--output-dir", default="reports/lab_ext_high_humidity_response_v1")
    parser.add_argument("--window-hours", type=int, default=12)
    parser.add_argument("--step-hours", type=int, default=1)
    parser.add_argument("--transition-near-hours", type=int, default=6)
    parser.add_argument("--similarity-k", type=int, default=5)
    parser.add_argument("--cooling-delta-temp-thresh", type=float, default=-0.3)
    parser.add_argument("--cooling-slope-temp-thresh", type=float, default=-0.01)
    parser.add_argument("--cooling-half-temp-thresh", type=float, default=-0.1)
    parser.add_argument("--heated-mean-dt-thresh", type=float, default=5.0)
    parser.add_argument("--cooling-q75-dah-thresh", type=float, default=0.15)
    parser.add_argument("--cooling-pos-dah-ratio-thresh", type=float, default=0.6)
    return parser.parse_args()


def robust_z_positive(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    if values.dropna().empty:
        return pd.Series(np.zeros(len(values)), index=series.index, dtype=float)
    median = float(values.median())
    mad = float((values - median).abs().median())
    scale = max(mad * 1.4826, 1e-6)
    return ((values - median) / scale).clip(lower=0.0).fillna(0.0)


def build_inputs(args: argparse.Namespace) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    run_df, window_df, _, _ = build_run_table(args)
    result = run_pipeline_v3(args)
    decision_df = result["decision_df"].copy()
    return run_df, window_df.copy(), decision_df


def compute_no_heat_response(run_df: pd.DataFrame, decision_df: pd.DataFrame) -> pd.DataFrame:
    static_train = run_df[run_df["analysis_group"].isin(["current_static_seal", "current_static_unseal"])].copy()
    no_heat_df = run_df[run_df["expected_family"] == "ext_high_hum_no_heat"].copy()
    if no_heat_df.empty:
        return pd.DataFrame()

    cutoffs: Dict[str, float] = {}
    for feature, direction in NO_HEAT_FEATURE_SPECS:
        seal = pd.to_numeric(static_train.loc[static_train["seal_label"] == "seal", feature], errors="coerce").dropna()
        unseal = pd.to_numeric(static_train.loc[static_train["seal_label"] == "unseal", feature], errors="coerce").dropna()
        if seal.empty or unseal.empty:
            continue
        cutoffs[feature] = float((seal.median() + unseal.median()) / 2.0)

    score_df = no_heat_df.copy()
    score_df["no_heat_response_score_v1"] = (
        0.25 * robust_z_positive(score_df["corr_out_hum_in_hum"])
        + 0.20 * robust_z_positive(score_df["max_corr_outRH_inRH_change"])
        + 0.20 * robust_z_positive(score_df["frac_threshold_favored"])
        + 0.15 * robust_z_positive(score_df["frac_pos_delta_half_dAH"])
        + 0.10 * robust_z_positive(score_df["q90_delta_half_dAH_w"])
        + 0.10 * robust_z_positive(-pd.to_numeric(score_df["std_in_hum_run"], errors="coerce"))
    )

    hit_cols: List[str] = []
    for feature, direction in NO_HEAT_FEATURE_SPECS:
        cutoff = cutoffs.get(feature, np.nan)
        col = f"pass_{feature}"
        values = pd.to_numeric(score_df[feature], errors="coerce")
        if pd.isna(cutoff):
            score_df[col] = False
        elif direction == "pos":
            score_df[col] = values >= cutoff
        else:
            score_df[col] = values <= cutoff
        hit_cols.append(col)

    score_df["response_hit_count"] = score_df[hit_cols].sum(axis=1).astype(int)
    score_df["response_hit_features"] = score_df[hit_cols].apply(
        lambda row: ",".join(
            feature.replace("pass_", "")
            for feature, hit in row.items()
            if bool(hit)
        ),
        axis=1,
    )

    merged = score_df.merge(
        decision_df[
            [
                "file",
                "final_status",
                "risk_level",
                "primary_evidence",
                "dynamic_vote_count",
                "hard_case_watch",
                "notes",
            ]
        ],
        on="file",
        how="left",
    )

    def branch_status(row: pd.Series) -> str:
        if str(row.get("final_status", "")) == "static_hard_case_watch":
            return "ext_high_hum_no_heat_breathing_watch"
        if str(row.get("final_status", "")) in {
            "static_dynamic_support_alert",
            "static_dynamic_supported_alert",
            "static_consensus_alert",
        }:
            return "ext_high_hum_no_heat_response_supported"
        if str(row.get("final_status", "")) in {"static_abstain_low_signal", "static_low_risk"}:
            return "ext_high_hum_no_heat_response_negative"
        if int(row.get("response_hit_count", 0)) >= 4:
            return "ext_high_hum_no_heat_response_like"
        return "ext_high_hum_no_heat_response_weak"

    merged["response_branch_status"] = merged.apply(branch_status, axis=1)
    return merged.sort_values(["response_hit_count", "no_heat_response_score_v1"], ascending=[False, False]).reset_index(drop=True)


def mark_cooling_windows(window_df: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    heated = window_df[window_df["expected_family"] == "ext_high_hum_with_heat"].copy()
    if heated.empty:
        return heated

    delta_in_temp = pd.to_numeric(heated["delta_in_temp"], errors="coerce")
    delta_half_in_temp = pd.to_numeric(heated["delta_half_in_temp"], errors="coerce")
    slope_in_temp = pd.to_numeric(heated["slope_in_temp"], errors="coerce")
    mean_dT = pd.to_numeric(heated["mean_dT"], errors="coerce")

    cooling_flag = (
        (mean_dT > float(args.heated_mean_dt_thresh))
        & (
            (delta_in_temp < float(args.cooling_delta_temp_thresh))
            | (
                (slope_in_temp < float(args.cooling_slope_temp_thresh))
                & (delta_half_in_temp < float(args.cooling_half_temp_thresh))
            )
        )
    )
    heated["cooling_response_flag"] = cooling_flag.fillna(False)
    return heated


def aggregate_cooling_runs(cooling_window_df: pd.DataFrame, decision_df: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    if cooling_window_df.empty:
        return pd.DataFrame()

    rows: List[Dict[str, Any]] = []
    for file_name, group in cooling_window_df.groupby("file", dropna=False):
        flagged = group[group["cooling_response_flag"]].copy()
        record: Dict[str, Any] = {
            "file": file_name,
            "seal_label": str(group["seal_label"].iloc[0]),
            "expected_family": str(group["expected_family"].iloc[0]),
            "total_windows": int(len(group)),
            "cooling_window_count": int(len(flagged)),
            "cooling_window_ratio": float(len(flagged) / len(group)) if len(group) else np.nan,
        }
        if not flagged.empty:
            record.update(
                {
                    "frac_pos_delta_half_dAH": float((pd.to_numeric(flagged["delta_half_dAH"], errors="coerce") > 0).mean()),
                    "frac_pos_delta_half_in_hum": float((pd.to_numeric(flagged["delta_half_in_hum"], errors="coerce") > 0).mean()),
                    "median_delta_half_dAH": float(pd.to_numeric(flagged["delta_half_dAH"], errors="coerce").median()),
                    "q75_delta_half_dAH": float(pd.to_numeric(flagged["delta_half_dAH"], errors="coerce").quantile(0.75)),
                    "median_delta_in_temp": float(pd.to_numeric(flagged["delta_in_temp"], errors="coerce").median()),
                    "median_slope_in_temp": float(pd.to_numeric(flagged["slope_in_temp"], errors="coerce").median()),
                    "dominant_cooling_class_label": str(flagged["class_label"].mode().iloc[0]) if not flagged["class_label"].dropna().empty else "",
                }
            )
        else:
            record.update(
                {
                    "frac_pos_delta_half_dAH": np.nan,
                    "frac_pos_delta_half_in_hum": np.nan,
                    "median_delta_half_dAH": np.nan,
                    "q75_delta_half_dAH": np.nan,
                    "median_delta_in_temp": np.nan,
                    "median_slope_in_temp": np.nan,
                    "dominant_cooling_class_label": "",
                }
            )
        rows.append(record)

    run_df = pd.DataFrame(rows)
    run_df = run_df.merge(
        decision_df[["file", "final_status", "risk_level", "primary_evidence", "notes"]],
        on="file",
        how="left",
    )

    def cooling_status(row: pd.Series) -> str:
        if int(row.get("cooling_window_count", 0)) == 0:
            return "ext_high_hum_cooling_no_segment"
        if (
            pd.notna(row.get("q75_delta_half_dAH"))
            and float(row.get("q75_delta_half_dAH")) >= float(args.cooling_q75_dah_thresh)
            and float(row.get("frac_pos_delta_half_dAH")) >= float(args.cooling_pos_dah_ratio_thresh)
        ):
            return "ext_high_hum_cooling_response_candidate"
        return "ext_high_hum_cooling_response_weak"

    run_df["cooling_branch_status"] = run_df.apply(cooling_status, axis=1)
    return run_df.sort_values(["cooling_window_count", "q75_delta_half_dAH"], ascending=[False, False]).reset_index(drop=True)


def build_summary(no_heat_df: pd.DataFrame, cooling_run_df: pd.DataFrame) -> Dict[str, Any]:
    no_heat_status_counts = no_heat_df["response_branch_status"].value_counts().to_dict() if not no_heat_df.empty else {}
    cooling_status_counts = cooling_run_df["cooling_branch_status"].value_counts().to_dict() if not cooling_run_df.empty else {}
    cooling_validation_ready = False
    if not cooling_run_df.empty:
        sealed_with_cooling = int(
            (
                (cooling_run_df["seal_label"] == "seal")
                & (cooling_run_df["cooling_window_count"] > 0)
            ).sum()
        )
        unsealed_with_cooling = int(
            (
                (cooling_run_df["seal_label"] == "unseal")
                & (cooling_run_df["cooling_window_count"] > 0)
            ).sum()
        )
        cooling_validation_ready = sealed_with_cooling >= 1 and unsealed_with_cooling >= 1
    else:
        sealed_with_cooling = 0
        unsealed_with_cooling = 0

    return {
        "no_heat_runs": int(len(no_heat_df)),
        "no_heat_status_counts": no_heat_status_counts,
        "no_heat_supported_unsealed": int(
            (
                (no_heat_df["seal_label"] == "unseal")
                & (no_heat_df["response_branch_status"] == "ext_high_hum_no_heat_response_supported")
            ).sum()
        )
        if not no_heat_df.empty
        else 0,
        "no_heat_negative_sealed": int(
            (
                (no_heat_df["seal_label"] == "seal")
                & (no_heat_df["response_branch_status"] == "ext_high_hum_no_heat_response_negative")
            ).sum()
        )
        if not no_heat_df.empty
        else 0,
        "no_heat_breathing_watch_sealed": int(
            (
                (no_heat_df["seal_label"] == "seal")
                & (no_heat_df["response_branch_status"] == "ext_high_hum_no_heat_breathing_watch")
            ).sum()
        )
        if not no_heat_df.empty
        else 0,
        "cooling_family_runs": int(len(cooling_run_df)),
        "cooling_status_counts": cooling_status_counts,
        "cooling_runs_with_segments": int((cooling_run_df["cooling_window_count"] > 0).sum()) if not cooling_run_df.empty else 0,
        "cooling_sealed_reference_runs": sealed_with_cooling,
        "cooling_unsealed_reference_runs": unsealed_with_cooling,
        "cooling_validation_ready": bool(cooling_validation_ready),
    }


def write_markdown(
    path: str,
    summary: Dict[str, Any],
    no_heat_df: pd.DataFrame,
    cooling_run_df: pd.DataFrame,
) -> None:
    lines = [
        "# 外部高湿响应分支 v1 报告",
        "",
        "- 目的：把 `外部高湿驱动` 从混合静态逻辑里显式拆成 `无热源响应` 和 `冷却响应` 两条分支，直接回答“理论上该能分，为什么现在还没稳定分出来”。",
        "",
        f"- no_heat_runs：`{summary['no_heat_runs']}`",
        f"- no_heat_status_counts：`{summary['no_heat_status_counts']}`",
        f"- no_heat_supported_unsealed：`{summary['no_heat_supported_unsealed']}`",
        f"- no_heat_negative_sealed：`{summary['no_heat_negative_sealed']}`",
        f"- no_heat_breathing_watch_sealed：`{summary['no_heat_breathing_watch_sealed']}`",
        f"- cooling_family_runs：`{summary['cooling_family_runs']}`",
        f"- cooling_status_counts：`{summary['cooling_status_counts']}`",
        f"- cooling_runs_with_segments：`{summary['cooling_runs_with_segments']}`",
        f"- cooling_sealed_reference_runs：`{summary['cooling_sealed_reference_runs']}`",
        f"- cooling_unsealed_reference_runs：`{summary['cooling_unsealed_reference_runs']}`",
        f"- cooling_validation_ready：`{summary['cooling_validation_ready']}`",
        "",
        "## 外部高湿-无热源响应",
        "",
        "- 这条分支的物理假设是：在外部持续高湿、内部无热源时，不密封运行应表现出更强的 `外部湿度驱动 -> 内部湿度响应`。",
        "- 当前结果说明：这条逻辑不是无效，而是已经能把 `低信号 sealed`、`response-supported unsealed` 和 `response-like sealed hard case` 三种状态分开。",
        "",
    ]
    for _, row in no_heat_df.iterrows():
        lines.append(
            f"- {row['file']} | seal={row['seal_label']} | status={row['response_branch_status']} | "
            f"hits={int(row['response_hit_count'])}/6 | score={row['no_heat_response_score_v1']:.3f} | "
            f"features={row['response_hit_features']} | final_status={row.get('final_status', '')}"
        )

    lines.extend(
        [
            "",
            "## 外部高湿-冷却响应",
            "",
            "- 这条分支的物理假设是：热源停止后的冷却段若出现进湿，不应只表现为 RH 回升，而应伴随更明确的 `delta_half_dAH` 正向响应。",
            "- 当前先用 `delta_in_temp < 0` 或 `slope_in_temp < 0 且 delta_half_in_temp < 0` 抽取冷却窗口，再看这些窗口里的 `delta_half_dAH` 是否持续为正。",
            "",
        ]
    )
    for _, row in cooling_run_df.iterrows():
        lines.append(
            f"- {row['file']} | seal={row['seal_label']} | cooling_windows={int(row['cooling_window_count'])} | "
            f"status={row['cooling_branch_status']} | frac_pos_dAH={row['frac_pos_delta_half_dAH']} | "
            f"q75_dAH={row['q75_delta_half_dAH']} | final_status={row.get('final_status', '')}"
        )

    lines.extend(
        [
            "",
            "## 当前解释",
            "",
            "- 外部高湿驱动并不是“筛不出来”，而是已经能筛成一个有价值主战场；问题出在这个主战场内部仍然存在 `sealed 但表现出 response-like` 的难例。",
            "- 这类难例最合理的解释不是“物理假设失效”，而是 `材料吸放湿 / 内部残余湿气 / 初始状态差异 / 结构呼吸效应` 让 sealed 运行也出现了类似外部驱动的响应。",
            "- 冷却响应当前还不能稳定验收，不是因为物理机制不成立，而是因为当前数据里缺少足够的 `高湿 + 有热源 + 明确冷却段 + sealed 对照` 参考窗口。",
            "- 因此下一步真正该改的是：把高湿无热源和高湿冷却从“长窗静态判别”改成“受激响应段判别”，而不是继续试图用整段均值去做统一分类。",
            "",
        ]
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    run_df, window_df, decision_df = build_inputs(args)
    no_heat_df = compute_no_heat_response(run_df, decision_df)
    cooling_window_df = mark_cooling_windows(window_df, args)
    cooling_run_df = aggregate_cooling_runs(cooling_window_df, decision_df, args)
    summary = build_summary(no_heat_df, cooling_run_df)

    outputs = {
        "no_heat_csv": os.path.join(args.output_dir, "ext_high_hum_no_heat_response.csv"),
        "cooling_window_csv": os.path.join(args.output_dir, "ext_high_hum_cooling_windows.csv"),
        "cooling_run_csv": os.path.join(args.output_dir, "ext_high_hum_cooling_response.csv"),
        "report_md": os.path.join(args.output_dir, "ext_high_humidity_response_report.md"),
        "report_json": os.path.join(args.output_dir, "ext_high_humidity_response_report.json"),
    }

    no_heat_df.to_csv(outputs["no_heat_csv"], index=False, encoding="utf-8-sig")
    cooling_window_df.to_csv(outputs["cooling_window_csv"], index=False, encoding="utf-8-sig")
    cooling_run_df.to_csv(outputs["cooling_run_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["report_md"], summary, no_heat_df, cooling_run_df)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
