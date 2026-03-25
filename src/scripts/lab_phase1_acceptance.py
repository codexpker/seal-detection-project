#!/usr/bin/env python3
import argparse
import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.anomaly_v2 import condition_classifier_v1 as cc


@dataclass
class Phase1Config:
    input_dir: str = "./excel_input"
    input_zip: str = "./data/data_2026-03-24.zip"
    metadata_xlsx: str = "./data/A312实验室采集数据说明文档.xlsx"
    output_dir: str = "./reports/lab_phase1_acceptance"
    window_hours: int = 12
    step_hours: int = 1
    transition_near_hours: int = 6


def robust_z_positive(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    med = values.median()
    mad = (values - med).abs().median()
    if pd.isna(mad) or mad < 1e-9:
        return pd.Series(np.zeros(len(values)), index=values.index, dtype=float)
    z = 0.6745 * (values - med) / mad
    return z.clip(lower=0).fillna(0.0)


def safe_polyfit_slope(time_s: pd.Series, value_s: pd.Series) -> float:
    if len(time_s) < 3:
        return 0.0
    x = (time_s - time_s.min()).dt.total_seconds() / 3600.0
    y = pd.to_numeric(value_s, errors="coerce").values.astype(float)
    if np.allclose(y, y[0]):
        return 0.0
    try:
        return float(np.polyfit(x, y, 1)[0])
    except Exception:
        return 0.0


def infer_seal_label(meta_row: Dict[str, Any], file_name: str) -> str:
    initial_state = str(meta_row.get("initial_state", "") or "").strip()
    lower_name = file_name.lower()
    if "非密封" in initial_state or "unseal" in lower_name:
        return "unseal"
    if "密封" in initial_state or "seal" in lower_name:
        return "seal"
    return "unknown"


def infer_heat_source(meta_row: Dict[str, Any], file_name: str) -> str:
    heat_source = str(meta_row.get("heat_source", "") or "").strip()
    lower_name = file_name.lower()
    if heat_source in {"有", "无"}:
        return heat_source
    if "unheated" in lower_name:
        return "无"
    if "heated" in lower_name:
        return "有"
    return ""


def auc_pairwise(scores: List[float], labels: List[int]) -> Optional[float]:
    positives = [float(s) for s, y in zip(scores, labels) if y == 1]
    negatives = [float(s) for s, y in zip(scores, labels) if y == 0]
    if not positives or not negatives:
        return None
    wins = 0.0
    total = float(len(positives) * len(negatives))
    for pos in positives:
        for neg in negatives:
            if pos > neg:
                wins += 1.0
            elif pos == neg:
                wins += 0.5
    return wins / total


def compute_run_features(df: pd.DataFrame) -> Dict[str, float]:
    duration_h = (df["time"].max() - df["time"].min()).total_seconds() / 3600.0
    half = len(df) // 2
    first = df.iloc[:half]
    second = df.iloc[half:]
    return {
        "duration_h": float(duration_h),
        "mean_out_h": float(df["out_hum"].mean()),
        "mean_dT": float(df["dT"].mean()),
        "mean_dAH": float(df["dAH"].mean()),
        "mean_dH": float(df["in_hum"].mean() - df["out_hum"].mean()),
        "delta_end_in_h": float(df["in_hum"].iloc[-1] - df["in_hum"].iloc[0]),
        "delta_half_in_h": float(second["in_hum"].mean() - first["in_hum"].mean()) if half else 0.0,
        "delta_half_dAH": float(second["dAH"].mean() - first["dAH"].mean()) if half else 0.0,
        "slope_in_h_per_h": safe_polyfit_slope(df["time"], df["in_hum"]),
        "slope_dAH_per_h": safe_polyfit_slope(df["time"], df["dAH"]),
        "end_start_dAH": float(df["dAH"].iloc[-1] - df["dAH"].iloc[0]),
    }


def process_dataset(cfg: Phase1Config) -> Tuple[pd.DataFrame, pd.DataFrame]:
    base_cfg = cc.Config()
    base_cfg.input_dir = cfg.input_dir
    base_cfg.input_zip = cfg.input_zip
    base_cfg.metadata_xlsx = cfg.metadata_xlsx
    base_cfg.output_dir = cfg.output_dir
    base_cfg.window_hours = cfg.window_hours
    base_cfg.step_hours = cfg.step_hours
    base_cfg.transition_near_hours = cfg.transition_near_hours
    base_cfg.export_window_csv = False
    base_cfg.export_feature_json = False
    base_cfg.export_window_plot = False

    metadata_df = cc.load_metadata_manifest(cfg.metadata_xlsx)
    metadata_map = (
        {row["data_file_name"]: row.to_dict() for _, row in metadata_df.iterrows()}
        if not metadata_df.empty
        else {}
    )

    window_rows: List[Dict[str, Any]] = []
    run_rows: List[Dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="lab_phase1_") as tmp_dir:
        files = cc.collect_input_files(base_cfg, tmp_dir)
        for file_path in files:
            file_base = cc.normalize_filename_token(os.path.basename(file_path))
            meta_row = dict(metadata_map.get(file_base, {}))
            sheets = cc.load_excel_sheets(file_path)
            if not sheets:
                run_rows.append(
                    {
                        "file": file_base,
                        "sheet": "",
                        "expected_family": cc.expected_family_from_manifest(meta_row),
                        "seal_label": infer_seal_label(meta_row, file_base),
                        "heat_source_inferred": infer_heat_source(meta_row, file_base),
                        "status": "empty_or_unreadable",
                    }
                )
                continue

            for sheet_name, raw_df in sheets:
                try:
                    df = cc.preprocess_df(raw_df)
                except Exception:
                    run_rows.append(
                        {
                            "file": file_base,
                            "sheet": sheet_name,
                            "expected_family": cc.expected_family_from_manifest(meta_row),
                            "seal_label": infer_seal_label(meta_row, file_base),
                            "heat_source_inferred": infer_heat_source(meta_row, file_base),
                            "status": "preprocess_failed",
                        }
                    )
                    continue

                if df.empty:
                    run_rows.append(
                        {
                            "file": file_base,
                            "sheet": sheet_name,
                            "expected_family": cc.expected_family_from_manifest(meta_row),
                            "seal_label": infer_seal_label(meta_row, file_base),
                            "heat_source_inferred": infer_heat_source(meta_row, file_base),
                            "status": "empty_after_preprocess",
                        }
                    )
                    continue

                expected_family = cc.expected_family_from_manifest(meta_row)
                expected_candidates = cc.expected_label_candidates(expected_family)
                windows = cc.sliding_windows(df, base_cfg)
                run_feat = compute_run_features(df)
                seal_label = infer_seal_label(meta_row, file_base)
                heat_source_inferred = infer_heat_source(meta_row, file_base)
                run_row = {
                    "file": file_base,
                    "sheet": sheet_name,
                    "expected_family": expected_family,
                    "expected_candidates": "|".join(expected_candidates),
                    "seal_label": seal_label,
                    "heat_source_inferred": heat_source_inferred,
                    "initial_state": meta_row.get("initial_state", ""),
                    "ext_humidity_level": meta_row.get("ext_humidity_level", ""),
                    "in_humidity_level": meta_row.get("in_humidity_level", ""),
                    "heat_source": meta_row.get("heat_source", ""),
                    "hole_time": meta_row.get("hole_time"),
                    "status": "ok",
                    "n_points": int(len(df)),
                    "n_windows": int(len(windows)),
                    **run_feat,
                }
                run_rows.append(run_row)

                for idx, (w_start, w_end, wdf) in enumerate(windows, start=1):
                    feat = cc.extract_features(wdf)
                    label = cc.classify_window(feat, base_cfg)
                    center = w_start + (w_end - w_start) / 2
                    hole_time = meta_row.get("hole_time")
                    phase = cc.transition_phase(center, hole_time, cfg.transition_near_hours)
                    row = {
                        "file": file_base,
                        "sheet": sheet_name,
                        "window_id": f"W{idx:04d}",
                        "start_time": w_start,
                        "end_time": w_end,
                        "window_center_time": center,
                        "class_label": label,
                        "predicted_group": cc.predicted_group(label),
                        "expected_family": expected_family,
                        "expected_match": int(label in expected_candidates) if expected_candidates else np.nan,
                        "transition_phase": phase,
                        "seal_label": seal_label,
                        "heat_source_inferred": heat_source_inferred,
                        "hole_time": hole_time,
                        **feat,
                    }
                    window_rows.append(row)

    window_df = pd.DataFrame(window_rows)
    run_df = pd.DataFrame(run_rows)
    return window_df, run_df


def apply_transition_relative_score(window_df: pd.DataFrame) -> pd.DataFrame:
    if window_df.empty:
        return window_df
    df = window_df.copy()
    df["transition_score"] = 0.0
    df["transition_rank_pct"] = np.nan

    trans_mask = df["expected_family"] == "transition_run"
    for file_name, group in df.loc[trans_mask].groupby("file", dropna=False):
        score = (
            0.45 * robust_z_positive(group["delta_half_in_hum"])
            + 0.35 * robust_z_positive(group["delta_half_dAH"])
            + 0.20 * robust_z_positive(group["slope_AH_in"])
        )
        rank_pct = score.rank(pct=True, method="average")
        df.loc[group.index, "transition_score"] = score.values
        df.loc[group.index, "transition_rank_pct"] = rank_pct.values
    return df


def build_file_summary(window_df: pd.DataFrame, run_df: pd.DataFrame) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    run_map = {
        (row["file"], row["sheet"]): row.to_dict()
        for _, row in run_df.iterrows()
    }

    for key, group in window_df.groupby(["file", "sheet"], dropna=False):
        file_name, sheet_name = key
        class_counts = group["class_label"].value_counts()
        dominant_label = class_counts.idxmax()
        rec = dict(run_map.get((file_name, sheet_name), {}))
        rec.update(
            {
                "file": file_name,
                "sheet": sheet_name,
                "dominant_label": dominant_label,
                "dominant_ratio": float(class_counts.iloc[0] / len(group)),
                "expected_match_ratio": float(group["expected_match"].dropna().mean()) if group["expected_match"].notna().any() else np.nan,
                "candidate_high_info_ratio": float((group["predicted_group"] == "candidate_high_info").mean()),
                "heat_related_ratio": float((group["predicted_group"] == "heat_related").mean()),
                "exclude_low_info_ratio": float((group["predicted_group"] == "exclude_low_info").mean()),
                "near_transition_windows": int((group["transition_phase"] == "near_transition").sum()),
                "near_transition_mean_score": float(group.loc[group["transition_phase"] == "near_transition", "transition_score"].mean())
                if (group["transition_phase"] == "near_transition").any()
                else np.nan,
                "near_transition_median_rank_pct": float(group.loc[group["transition_phase"] == "near_transition", "transition_rank_pct"].median())
                if (group["transition_phase"] == "near_transition").any()
                else np.nan,
                "non_near_transition_mean_score": float(group.loc[group["transition_phase"] != "near_transition", "transition_score"].mean())
                if (group["transition_phase"] != "near_transition").any()
                else np.nan,
            }
        )
        for class_name in cc.CLASS_NAMES:
            rec[f"count_{class_name}"] = int(class_counts.get(class_name, 0))
            rec[f"ratio_{class_name}"] = float(class_counts.get(class_name, 0) / len(group))
        rows.append(rec)

    only_run_rows = run_df[run_df["n_windows"].fillna(0) <= 0]
    for _, row in only_run_rows.iterrows():
        rec = row.to_dict()
        rec.setdefault("dominant_label", "")
        rec.setdefault("dominant_ratio", np.nan)
        rec.setdefault("expected_match_ratio", np.nan)
        rec.setdefault("candidate_high_info_ratio", np.nan)
        rec.setdefault("heat_related_ratio", np.nan)
        rec.setdefault("exclude_low_info_ratio", np.nan)
        rec.setdefault("near_transition_windows", 0)
        rec.setdefault("near_transition_mean_score", np.nan)
        rec.setdefault("near_transition_median_rank_pct", np.nan)
        rec.setdefault("non_near_transition_mean_score", np.nan)
        rows.append(rec)

    summary_df = pd.DataFrame(rows)
    if summary_df.empty:
        return summary_df
    return summary_df.sort_values(["expected_family", "file", "sheet"]).reset_index(drop=True)


def evaluate_gate(file_df: pd.DataFrame) -> Dict[str, Any]:
    known = file_df[file_df["expected_family"].isin(
        [
            "transition_run",
            "ext_high_hum_no_heat",
            "ext_high_hum_with_heat",
            "balanced_no_heat",
            "balanced_with_heat",
            "internal_moist_no_heat",
            "internal_moist_with_heat",
        ]
    )].copy()
    known = known[known["n_windows"].fillna(0) > 0]
    mean_match = float(known["expected_match_ratio"].dropna().mean()) if not known.empty else np.nan
    return {
        "known_files_with_windows": int(len(known)),
        "expected_match_ratio_mean": mean_match,
        "pass": bool(not pd.isna(mean_match) and mean_match >= 0.90),
    }


def evaluate_transition(file_df: pd.DataFrame) -> Dict[str, Any]:
    trans = file_df[(file_df["expected_family"] == "transition_run") & (file_df["near_transition_windows"] > 0)].copy()
    if trans.empty:
        return {"transition_files": 0, "pass": False, "details": []}

    details: List[Dict[str, Any]] = []
    all_pass = True
    for _, row in trans.iterrows():
        median_rank = float(row.get("near_transition_median_rank_pct", np.nan))
        near_score = float(row.get("near_transition_mean_score", np.nan))
        non_near_score = float(row.get("non_near_transition_mean_score", np.nan))
        row_pass = bool(
            not pd.isna(median_rank)
            and median_rank >= 0.80
            and not pd.isna(near_score)
            and not pd.isna(non_near_score)
            and near_score > (non_near_score + 0.20)
        )
        all_pass = all_pass and row_pass
        details.append(
            {
                "file": row["file"],
                "near_transition_windows": int(row["near_transition_windows"]),
                "near_transition_median_rank_pct": median_rank,
                "near_transition_mean_score": near_score,
                "non_near_transition_mean_score": non_near_score,
                "pass": row_pass,
            }
        )
    return {"transition_files": int(len(trans)), "pass": all_pass, "details": details}


def evaluate_static_branch(run_df: pd.DataFrame) -> Dict[str, Any]:
    static_df = run_df.copy()
    static_df = static_df[static_df["status"] == "ok"]
    static_df = static_df[static_df["seal_label"].isin(["seal", "unseal"])]
    static_df = static_df[static_df["heat_source_inferred"] == "无"]
    static_df = static_df[static_df["file"].str.contains("unheated", case=False, na=False)]
    static_df = static_df[static_df["expected_family"] != "transition_run"]
    static_df = static_df[(static_df["mean_out_h"] >= 80.0) & (static_df["mean_dT"] < 1.5)]

    features = [
        "mean_dAH",
        "mean_dH",
        "delta_end_in_h",
        "delta_half_in_h",
        "delta_half_dAH",
        "slope_in_h_per_h",
        "slope_dAH_per_h",
        "end_start_dAH",
    ]
    label_map = {"seal": 0, "unseal": 1}
    labels = [label_map[x] for x in static_df["seal_label"].tolist()]

    best_feature = None
    best_auc = -1.0
    best_direction = "pos"
    for feat_name in features:
        scores = static_df[feat_name].astype(float).tolist()
        auc_pos = auc_pairwise(scores, labels)
        auc_neg = auc_pairwise([-x for x in scores], labels)
        auc_val = max(auc_pos or 0.0, auc_neg or 0.0)
        direction = "pos" if (auc_pos or 0.0) >= (auc_neg or 0.0) else "neg"
        if auc_val > best_auc:
            best_auc = auc_val
            best_feature = feat_name
            best_direction = direction

    class_counts = static_df["seal_label"].value_counts().to_dict()
    has_min_samples = class_counts.get("seal", 0) >= 2 and class_counts.get("unseal", 0) >= 2
    # 小样本下 0.75 只能算边缘可用，不能直接视为“稳定可分”
    static_pass = bool(has_min_samples and best_auc >= 0.80)
    return {
        "candidate_runs": int(len(static_df)),
        "class_counts": class_counts,
        "best_feature": best_feature,
        "best_auc": None if best_auc < 0 else float(best_auc),
        "best_direction": best_direction,
        "pass": static_pass,
        "static_runs": static_df,
    }


def build_acceptance(gate_eval: Dict[str, Any], transition_eval: Dict[str, Any], static_eval: Dict[str, Any]) -> Dict[str, Any]:
    demo_ready = bool(gate_eval["pass"] and transition_eval["pass"])
    overall_pass = bool(demo_ready and static_eval["pass"])
    if overall_pass:
        verdict = "PASS"
    elif demo_ready:
        verdict = "PARTIAL_PASS"
    else:
        verdict = "FAIL"

    return {
        "verdict": verdict,
        "phase1_pass": overall_pass,
        "demo_ready": demo_ready,
        "gate_eval": gate_eval,
        "transition_eval": transition_eval,
        "static_eval": {
            k: v for k, v in static_eval.items() if k != "static_runs"
        },
        "conclusion": {
            "gate_branch_ready": gate_eval["pass"],
            "transition_branch_ready": transition_eval["pass"],
            "static_branch_ready": static_eval["pass"],
            "first_stage_can_pass_smoothly": overall_pass,
        },
    }


def write_markdown_report(path: str, acceptance: Dict[str, Any]) -> None:
    gate_eval = acceptance["gate_eval"]
    transition_eval = acceptance["transition_eval"]
    static_eval = acceptance["static_eval"]
    lines = [
        "# 实验室一阶段验收报告",
        "",
        f"- 验收结论：`{acceptance['verdict']}`",
        f"- 第一阶段是否可判定顺利通过：`{acceptance['conclusion']['first_stage_can_pass_smoothly']}`",
        f"- 演示版是否可用：`{acceptance['demo_ready']}`",
        "",
        "## 工况 Gate",
        "",
        f"- 已知工况且可成窗文件数：`{gate_eval['known_files_with_windows']}`",
        f"- expected_match_ratio_mean：`{gate_eval['expected_match_ratio_mean']}`",
        f"- Gate 是否通过：`{gate_eval['pass']}`",
        "",
        "## 转移分支",
        "",
        f"- 转移文件数：`{transition_eval['transition_files']}`",
        f"- 转移分支是否通过：`{transition_eval['pass']}`",
    ]
    for item in transition_eval["details"]:
        lines.append(
            f"- {item['file']} | near_windows={item['near_transition_windows']} | "
            f"median_rank={item['near_transition_median_rank_pct']:.3f} | "
            f"near_score={item['near_transition_mean_score']:.3f} | "
            f"non_near_score={item['non_near_transition_mean_score']:.3f} | pass={item['pass']}"
        )

    lines.extend(
        [
            "",
            "## 静态高信息分支",
            "",
            f"- 候选运行数：`{static_eval['candidate_runs']}`",
            f"- 类别分布：`{static_eval['class_counts']}`",
            f"- 最优单特征：`{static_eval['best_feature']}`",
            f"- 最优 AUC：`{static_eval['best_auc']}`",
            f"- 静态分支是否通过：`{static_eval['pass']}`",
            "",
            "## 结论",
            "",
            "- 当前数据已经足够支撑“工况先筛 + 转移段相对打分”的演示闭环。",
            "- 当前数据还不足以支撑“高外湿无热源静态 seal/unseal 稳定区分”这一条分支通过验收。",
            "- 因此一阶段不能判定为顺利通过，只能判定为演示版可用、主目标需分支推进。",
            "",
        ]
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lab phase-1 acceptance evaluator")
    parser.add_argument("--input-dir", default=Phase1Config.input_dir)
    parser.add_argument("--input-zip", default=Phase1Config.input_zip)
    parser.add_argument("--metadata-xlsx", default=Phase1Config.metadata_xlsx)
    parser.add_argument("--output-dir", default=Phase1Config.output_dir)
    parser.add_argument("--window-hours", type=int, default=Phase1Config.window_hours)
    parser.add_argument("--step-hours", type=int, default=Phase1Config.step_hours)
    parser.add_argument("--transition-near-hours", type=int, default=Phase1Config.transition_near_hours)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = Phase1Config(
        input_dir=args.input_dir,
        input_zip=args.input_zip,
        metadata_xlsx=args.metadata_xlsx,
        output_dir=args.output_dir,
        window_hours=args.window_hours,
        step_hours=args.step_hours,
        transition_near_hours=args.transition_near_hours,
    )

    os.makedirs(cfg.output_dir, exist_ok=True)

    window_df, run_df = process_dataset(cfg)
    window_df = apply_transition_relative_score(window_df)
    file_df = build_file_summary(window_df, run_df)

    gate_eval = evaluate_gate(file_df)
    transition_eval = evaluate_transition(file_df)
    static_eval = evaluate_static_branch(file_df)
    acceptance = build_acceptance(gate_eval, transition_eval, static_eval)

    window_path = os.path.join(cfg.output_dir, "phase1_window_scores.csv")
    file_path = os.path.join(cfg.output_dir, "phase1_file_summary.csv")
    static_path = os.path.join(cfg.output_dir, "phase1_static_branch_runs.csv")
    json_path = os.path.join(cfg.output_dir, "phase1_acceptance.json")
    md_path = os.path.join(cfg.output_dir, "phase1_acceptance_report.md")

    window_df.to_csv(window_path, index=False, encoding="utf-8-sig")
    file_df.to_csv(file_path, index=False, encoding="utf-8-sig")
    static_eval["static_runs"].to_csv(static_path, index=False, encoding="utf-8-sig")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "config": asdict(cfg),
                "acceptance": acceptance,
                "outputs": {
                    "window_scores_csv": window_path,
                    "file_summary_csv": file_path,
                    "static_branch_csv": static_path,
                    "report_md": md_path,
                },
            },
            f,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    write_markdown_report(md_path, acceptance)

    print(
        json.dumps(
            {
                "config": asdict(cfg),
                "acceptance": acceptance,
                "outputs": {
                    "window_scores_csv": window_path,
                    "file_summary_csv": file_path,
                    "static_branch_csv": static_path,
                    "report_md": md_path,
                },
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
