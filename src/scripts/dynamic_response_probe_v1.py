#!/usr/bin/env python3
import argparse
import json
import os
import sys
import tempfile
from typing import Any, Dict, List

import pandas as pd

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.anomaly_v2 import condition_classifier_v1 as cc
from src.scripts.lab_gate_info_selector_v2 import build_views, assign_routes
from src.scripts.lab_phase1_acceptance import Phase1Config, auc_pairwise, compute_run_features, infer_heat_source, infer_seal_label
from src.scripts.old_data_interference_analysis import analyze_old_data, lag_response_features


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dynamic response probe v1")
    parser.add_argument("--current-input-dir", default=Phase1Config.input_dir)
    parser.add_argument("--current-input-zip", default=Phase1Config.input_zip)
    parser.add_argument("--current-metadata-xlsx", default=Phase1Config.metadata_xlsx)
    parser.add_argument("--output-dir", default="reports/dynamic_response_probe_v1")
    parser.add_argument("--window-hours", type=int, default=12)
    parser.add_argument("--step-hours", type=int, default=1)
    parser.add_argument("--transition-near-hours", type=int, default=6)
    return parser.parse_args()


def current_dynamic_runs(args: argparse.Namespace) -> pd.DataFrame:
    class GateArgs:
        input_dir = args.current_input_dir
        input_zip = args.current_input_zip
        metadata_xlsx = args.current_metadata_xlsx
        output_dir = args.output_dir
        window_hours = args.window_hours
        step_hours = args.step_hours
        transition_near_hours = args.transition_near_hours

    window_df, file_df = build_views(GateArgs)
    _, static_route_df = assign_routes(window_df, file_df)
    static_files = set(static_route_df["file"].dropna().tolist())

    metadata_df = cc.load_metadata_manifest(args.current_metadata_xlsx)
    metadata_map = {row["data_file_name"]: row.to_dict() for _, row in metadata_df.iterrows()}

    rows: List[Dict[str, Any]] = []
    cfg = cc.Config(
        input_dir=args.current_input_dir,
        input_zip=args.current_input_zip,
        metadata_xlsx=args.current_metadata_xlsx,
        output_dir=args.output_dir,
        window_hours=args.window_hours,
        step_hours=args.step_hours,
    )

    with tempfile.TemporaryDirectory(prefix="dynamic_probe_current_") as tmp_dir:
        files = cc.collect_input_files(cfg, tmp_dir)
        for file_path in files:
            file_base = cc.normalize_filename_token(os.path.basename(file_path))
            meta_row = dict(metadata_map.get(file_base, {}))
            expected_family = cc.expected_family_from_manifest(meta_row)
            seal_label = infer_seal_label(meta_row, file_base)
            heat_source = infer_heat_source(meta_row, file_base)
            sheets = cc.load_excel_sheets(file_path)
            for sheet_name, raw_df in sheets:
                try:
                    df = cc.preprocess_df(raw_df)
                except Exception:
                    continue
                if df.empty:
                    continue

                run_feat = compute_run_features(df)
                response_feat = lag_response_features(df)
                windows = cc.sliding_windows(df, cc.Config(window_hours=args.window_hours, step_hours=args.step_hours))
                group_rows: List[str] = []
                for _, _, wdf in windows:
                    feat = cc.extract_features(wdf)
                    label = cc.classify_window(feat, cc.CFG)
                    group_rows.append(cc.predicted_group(label))
                group_share = pd.Series(group_rows).value_counts(normalize=True) if group_rows else pd.Series(dtype=float)

                analysis_group = "current_other"
                if file_base in static_files:
                    analysis_group = f"current_static_{seal_label}"
                elif expected_family == "transition_run":
                    analysis_group = "current_transition"
                elif heat_source == "有":
                    analysis_group = "current_heat_related"

                rows.append(
                    {
                        "file": file_base,
                        "sheet": sheet_name,
                        "analysis_group": analysis_group,
                        "expected_family": expected_family,
                        "seal_label": seal_label,
                        "heat_source_inferred": heat_source,
                        "static_candidate": file_base in static_files,
                        "duration_h": float(run_feat["duration_h"]),
                        "mean_out_h": float(run_feat["mean_out_h"]),
                        "mean_dT": float(run_feat["mean_dT"]),
                        "mean_dAH": float(run_feat["mean_dAH"]),
                        "delta_half_in_h": float(run_feat["delta_half_in_h"]),
                        "delta_half_dAH": float(run_feat["delta_half_dAH"]),
                        "slope_in_h_per_h": float(run_feat["slope_in_h_per_h"]),
                        "candidate_high_info_ratio": float(group_share.get("candidate_high_info", 0.0)),
                        "heat_related_ratio": float(group_share.get("heat_related", 0.0)),
                        **response_feat,
                    }
                )
    return pd.DataFrame(rows)


def rank_features(df: pd.DataFrame, positive_group: str, negative_group: str, features: List[str]) -> List[Dict[str, Any]]:
    subset = df[df["analysis_group"].isin([positive_group, negative_group])].copy()
    rows: List[Dict[str, Any]] = []
    for feature in features:
        scores = pd.to_numeric(subset[feature], errors="coerce")
        valid = scores.notna()
        if valid.sum() < 4:
            continue
        labels = [1 if g == positive_group else 0 for g in subset.loc[valid, "analysis_group"]]
        values = scores.loc[valid].astype(float).tolist()
        auc_pos = auc_pairwise(values, labels) or 0.0
        auc_neg = auc_pairwise([-x for x in values], labels) or 0.0
        rows.append(
            {
                "feature": feature,
                "auc": float(max(auc_pos, auc_neg)),
                "direction": "pos" if auc_pos >= auc_neg else "neg",
            }
        )
    return sorted(rows, key=lambda x: x["auc"], reverse=True)


def summarize_probe(old_df: pd.DataFrame, current_df: pd.DataFrame) -> Dict[str, Any]:
    old_ok = old_df[old_df["status"] == "ok"].copy()
    old_ok = old_ok[old_ok["subgroup"].isin(["unsealed", "sealed_strict", "sealed_no_screw_grease"])]
    current_static = current_df[current_df["analysis_group"].isin(["current_static_seal", "current_static_unseal"])].copy()

    old_medians = old_ok.groupby("subgroup")[["best_lag_h", "best_lag_rh_h", "gain_ratio_dAH_change", "max_corr_dAH_change"]].median()
    current_medians = current_static.groupby("analysis_group")[["best_lag_h", "best_lag_rh_h", "gain_ratio_dAH_change", "max_corr_dAH_change"]].median()

    features = [
        "best_lag_h",
        "best_lag_rh_h",
        "gain_ratio_dAH_change",
        "max_corr_dAH_change",
        "max_corr_outRH_inRH_change",
        "candidate_high_info_ratio",
        "heat_related_ratio",
    ]
    old_rank = rank_features(
        old_ok.rename(columns={"subgroup": "analysis_group"}),
        positive_group="unsealed",
        negative_group="sealed_strict",
        features=features,
    )
    current_rank = rank_features(
        current_static,
        positive_group="current_static_unseal",
        negative_group="current_static_seal",
        features=features,
    )

    direction_consistency: Dict[str, Any] = {}
    if not old_medians.empty and not current_medians.empty:
        try:
            old_unsealed = old_medians.loc["unsealed"]
            old_strict = old_medians.loc["sealed_strict"]
            cur_unsealed = current_medians.loc["current_static_unseal"]
            cur_sealed = current_medians.loc["current_static_seal"]
            direction_consistency = {
                "lag_rh_unsealed_faster_in_old": bool(old_unsealed["best_lag_rh_h"] < old_strict["best_lag_rh_h"]),
                "lag_rh_unsealed_faster_in_current": bool(cur_unsealed["best_lag_rh_h"] < cur_sealed["best_lag_rh_h"]),
                "gain_unsealed_higher_in_old": bool(old_unsealed["gain_ratio_dAH_change"] > old_strict["gain_ratio_dAH_change"]),
                "gain_unsealed_higher_in_current": bool(cur_unsealed["gain_ratio_dAH_change"] > cur_sealed["gain_ratio_dAH_change"]),
            }
        except KeyError:
            direction_consistency = {}

    return {
        "old_ok_runs": int(len(old_ok)),
        "current_runs": int(len(current_df)),
        "current_static_runs": int(len(current_static)),
        "old_medians": old_medians.reset_index().to_dict(orient="records"),
        "current_medians": current_medians.reset_index().to_dict(orient="records"),
        "old_top_features": old_rank[:6],
        "current_top_features": current_rank[:6],
        "direction_consistency": direction_consistency,
    }


def write_markdown(path: str, summary: Dict[str, Any], current_df: pd.DataFrame) -> None:
    current_static = current_df[current_df["analysis_group"].isin(["current_static_seal", "current_static_unseal"])].copy()
    lines = [
        "# Dynamic Response Probe v1",
        "",
        f"- old_ok_runs = `{summary['old_ok_runs']}`",
        f"- current_runs = `{summary['current_runs']}`",
        f"- current_static_runs = `{summary['current_static_runs']}`",
        "",
        "## 旧数据结论",
        "",
        "- 旧数据里的 `strict sealed` 与 `unsealed`，静态特征分离度有限，但动态响应特征开始出现工程价值。",
        "- 当前旧数据里最强的动态线索仍然是 `best_lag_rh_h`，说明外部 RH 变化到内部 RH 变化的响应滞后值得继续跟。",
        "",
        "### old unsealed vs sealed_strict Top Features",
        "",
    ]
    for item in summary["old_top_features"]:
        lines.append(f"- {item['feature']} | auc={item['auc']:.3f} | direction={item['direction']}")

    lines.extend(
        [
            "",
            "## 当前分工况数据检查",
            "",
            "- 只抽取当前 `static routed` 运行做对照，不把转移和热相关运行混进来。",
            "- 当前样本量很小，这一步只看方向，不做通过验收。",
            "",
            "### current static runs",
            "",
        ]
    )
    for _, row in current_static.sort_values(["analysis_group", "file"]).iterrows():
        lines.append(
            f"- {row['file']} | group={row['analysis_group']} | best_lag_h={row['best_lag_h']} | "
            f"best_lag_rh_h={row['best_lag_rh_h']} | gain_ratio_dAH_change={row['gain_ratio_dAH_change']}"
        )

    lines.extend(
        [
            "",
            "### current static unseal vs seal Top Features",
            "",
        ]
    )
    for item in summary["current_top_features"]:
        lines.append(f"- {item['feature']} | auc={item['auc']:.3f} | direction={item['direction']}")

    dc = summary["direction_consistency"]
    lines.extend(
        [
            "",
            "## 方向一致性",
            "",
            f"- lag_rh_unsealed_faster_in_old = `{dc.get('lag_rh_unsealed_faster_in_old')}`",
            f"- lag_rh_unsealed_faster_in_current = `{dc.get('lag_rh_unsealed_faster_in_current')}`",
            f"- gain_unsealed_higher_in_old = `{dc.get('gain_unsealed_higher_in_old')}`",
            f"- gain_unsealed_higher_in_current = `{dc.get('gain_unsealed_higher_in_current')}`",
            "",
            "## 当前判断",
            "",
            "- `dynamic response` 这条线在旧数据上更像“干扰识别线索”，而不是成熟主分类器。",
            "- 在当前分工况小样本里，这些特征方向只有部分一致，还不足以替代现有主路线。",
            "- 因此下一步最合理的定位是：把它做成 `interference/watch` 辅助探针，而不是立即升级为主判别分支。",
            "",
        ]
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    old_df = analyze_old_data(window_hours=args.window_hours, step_hours=args.step_hours)
    current_df = current_dynamic_runs(args)
    summary = summarize_probe(old_df, current_df)

    outputs = {
        "old_csv": os.path.join(args.output_dir, "dynamic_probe_old_runs.csv"),
        "current_csv": os.path.join(args.output_dir, "dynamic_probe_current_runs.csv"),
        "report_md": os.path.join(args.output_dir, "dynamic_response_probe_report.md"),
        "report_json": os.path.join(args.output_dir, "dynamic_response_probe_report.json"),
    }
    old_df.to_csv(outputs["old_csv"], index=False, encoding="utf-8-sig")
    current_df.to_csv(outputs["current_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["report_md"], summary, current_df)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
