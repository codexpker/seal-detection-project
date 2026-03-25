#!/usr/bin/env python3
import argparse
import json
import os
import sys
import tempfile
import zipfile
from typing import Any, Dict, List

import numpy as np
import pandas as pd

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.anomaly_v2 import condition_classifier_v1 as cc
from src.scripts.lab_phase1_acceptance import auc_pairwise, compute_run_features


OLD_DATA_ZIPS = [
    "data/old_data/sealed.zip",
    "data/old_data/unsealed.zip",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze historical old_data as interference challenge set")
    parser.add_argument("--output-dir", default="reports/old_data_interference_analysis")
    parser.add_argument("--window-hours", type=int, default=12)
    parser.add_argument("--step-hours", type=int, default=1)
    return parser.parse_args()


def infer_subgroup(inner_path: str) -> str:
    if "非密封状态数据" in inner_path:
        return "unsealed"
    if "严格密封" in inner_path:
        return "sealed_strict"
    if "没拧螺丝和黄油但没打孔" in inner_path:
        return "sealed_no_screw_grease"
    return "unknown"


def infer_path_label(inner_path: str) -> str:
    subgroup = infer_subgroup(inner_path)
    mapping = {
        "unsealed": "非密封状态数据",
        "sealed_strict": "密封状态数据/严格密封",
        "sealed_no_screw_grease": "密封状态数据/没拧螺丝和黄油但没打孔",
    }
    return mapping.get(subgroup, "unknown")


def safe_corr(a: pd.Series, b: pd.Series) -> float:
    if len(a) < 3:
        return np.nan
    value = np.corrcoef(a.astype(float), b.astype(float))[0, 1]
    return float(value) if not np.isnan(value) else np.nan


def lag_response_features(df: pd.DataFrame) -> Dict[str, Any]:
    hourly = df.set_index("time").resample("1h").mean(numeric_only=True).interpolate(limit_direction="both")
    if len(hourly) < 12:
        return {
            "max_corr_dAH_change": np.nan,
            "best_lag_h": np.nan,
            "gain_ratio_dAH_change": np.nan,
            "max_corr_outRH_inRH_change": np.nan,
            "best_lag_rh_h": np.nan,
        }

    out_ah_delta = hourly["AH_out"].diff()
    in_ah_delta = hourly["AH_in"].diff()
    out_rh_delta = hourly["out_hum"].diff()
    in_rh_delta = hourly["in_hum"].diff()

    best_ah_corr = -2.0
    best_ah_lag = np.nan
    best_ah_gain = np.nan
    best_rh_corr = -2.0
    best_rh_lag = np.nan

    for lag in range(0, 7):
        ah_pair = pd.concat([out_ah_delta, in_ah_delta.shift(-lag)], axis=1).dropna()
        if len(ah_pair) >= 6:
            corr_val = ah_pair.iloc[:, 0].corr(ah_pair.iloc[:, 1])
            if pd.notna(corr_val) and corr_val > best_ah_corr:
                best_ah_corr = float(corr_val)
                best_ah_lag = lag
                best_ah_gain = float(ah_pair.iloc[:, 1].std() / max(ah_pair.iloc[:, 0].std(), 1e-6))

        rh_pair = pd.concat([out_rh_delta, in_rh_delta.shift(-lag)], axis=1).dropna()
        if len(rh_pair) >= 6:
            corr_val = rh_pair.iloc[:, 0].corr(rh_pair.iloc[:, 1])
            if pd.notna(corr_val) and corr_val > best_rh_corr:
                best_rh_corr = float(corr_val)
                best_rh_lag = lag

    return {
        "max_corr_dAH_change": best_ah_corr if best_ah_corr > -1.5 else np.nan,
        "best_lag_h": best_ah_lag,
        "gain_ratio_dAH_change": best_ah_gain,
        "max_corr_outRH_inRH_change": best_rh_corr if best_rh_corr > -1.5 else np.nan,
        "best_lag_rh_h": best_rh_lag,
    }


def analyze_old_data(window_hours: int, step_hours: int) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    cfg = cc.Config(window_hours=window_hours, step_hours=step_hours)

    for zip_path in OLD_DATA_ZIPS:
        with zipfile.ZipFile(zip_path) as zf, tempfile.TemporaryDirectory(prefix="old_data_") as tmp_dir:
            for inner_name in zf.namelist():
                if not inner_name.lower().endswith(".xlsx"):
                    continue
                file_name = os.path.basename(inner_name).rsplit(".", 1)[0]
                target = os.path.join(tmp_dir, os.path.basename(inner_name))
                with zf.open(inner_name) as src, open(target, "wb") as out:
                    out.write(src.read())

                try:
                    sheets = cc.load_excel_sheets(target)
                except Exception as exc:
                    rows.append(
                        {
                            "archive": os.path.basename(zip_path),
                            "inner_path": inner_name,
                            "path_label": infer_path_label(inner_name),
                            "subgroup": infer_subgroup(inner_name),
                            "file": file_name,
                            "status": f"read_fail:{type(exc).__name__}",
                        }
                    )
                    continue

                if not sheets:
                    rows.append(
                        {
                            "archive": os.path.basename(zip_path),
                            "inner_path": inner_name,
                            "path_label": infer_path_label(inner_name),
                            "subgroup": infer_subgroup(inner_name),
                            "file": file_name,
                            "status": "no_nonempty_sheet",
                        }
                    )
                    continue

                for sheet_name, raw_df in sheets:
                    try:
                        df = cc.preprocess_df(raw_df)
                    except Exception as exc:
                        rows.append(
                            {
                                "archive": os.path.basename(zip_path),
                                "inner_path": inner_name,
                                "path_label": infer_path_label(inner_name),
                                "subgroup": infer_subgroup(inner_name),
                                "file": file_name,
                                "sheet": sheet_name,
                                "status": f"preprocess_fail:{type(exc).__name__}",
                            }
                        )
                        continue

                    if df.empty:
                        rows.append(
                            {
                                "archive": os.path.basename(zip_path),
                                "inner_path": inner_name,
                                "path_label": infer_path_label(inner_name),
                                "subgroup": infer_subgroup(inner_name),
                                "file": file_name,
                                "sheet": sheet_name,
                                "status": "empty_after_preprocess",
                            }
                        )
                        continue

                    run_feat = compute_run_features(df)
                    windows = cc.sliding_windows(df, cfg)
                    label_rows: List[str] = []
                    group_rows: List[str] = []
                    for _, _, wdf in windows:
                        feat = cc.extract_features(wdf)
                        label = cc.classify_window(feat, cc.CFG)
                        label_rows.append(label)
                        group_rows.append(cc.predicted_group(label))

                    group_share = pd.Series(group_rows).value_counts(normalize=True) if group_rows else pd.Series(dtype=float)
                    label_share = pd.Series(label_rows).value_counts(normalize=True) if label_rows else pd.Series(dtype=float)

                    std_in_hum = float(df["in_hum"].std())
                    std_ah_in = float(df["AH_in"].std())
                    response_feat = lag_response_features(df)

                    rows.append(
                        {
                            "archive": os.path.basename(zip_path),
                            "inner_path": inner_name,
                            "path_label": infer_path_label(inner_name),
                            "subgroup": infer_subgroup(inner_name),
                            "file": file_name,
                            "sheet": sheet_name,
                            "status": "ok",
                            "n_points": int(len(df)),
                            "duration_h": float(run_feat["duration_h"]),
                            "mean_out_h": float(run_feat["mean_out_h"]),
                            "mean_dT": float(run_feat["mean_dT"]),
                            "mean_dAH": float(run_feat["mean_dAH"]),
                            "delta_half_in_h": float(run_feat["delta_half_in_h"]),
                            "delta_half_dAH": float(run_feat["delta_half_dAH"]),
                            "slope_in_h_per_h": float(run_feat["slope_in_h_per_h"]),
                            "slope_dAH_per_h": float(run_feat["slope_dAH_per_h"]),
                            "end_start_dAH": float(run_feat["end_start_dAH"]),
                            "std_in_hum_run": std_in_hum,
                            "std_AH_in_run": std_ah_in,
                            "rh_ah_ratio": float(std_in_hum / max(std_ah_in, 1e-6)),
                            "corr_in_temp_in_hum": safe_corr(df["in_temp"], df["in_hum"]),
                            "corr_in_temp_AH_in": safe_corr(df["in_temp"], df["AH_in"]),
                            "n_windows_12h": int(len(windows)),
                            "candidate_high_info_ratio": float(group_share.get("candidate_high_info", 0.0)),
                            "heat_related_ratio": float(group_share.get("heat_related", 0.0)),
                            "exclude_low_info_ratio": float(group_share.get("exclude_low_info", 0.0)),
                            "complex_ratio": float(group_share.get("complex_coupled", 0.0)),
                            "label_ext_high_hum_ratio": float(label_share.get("外部高湿驱动工况", 0.0)),
                            "label_transition_ratio": float(label_share.get("内部积湿状态切换窗口", 0.0)),
                            "label_heat_stable_ratio": float(label_share.get("热源稳定工况", 0.0)),
                            "label_cooling_ratio": float(label_share.get("冷却窗口", 0.0)),
                            **response_feat,
                        }
                    )
    return pd.DataFrame(rows)


def pairwise_feature_ranking(df: pd.DataFrame, group_a: str, group_b: str, features: List[str], top_k: int = 6) -> List[Dict[str, Any]]:
    subset = df[df["subgroup"].isin([group_a, group_b])].copy()
    subset = subset.dropna(subset=features, how="all")
    labels = [1 if x == group_a else 0 for x in subset["subgroup"]]
    rows: List[Dict[str, Any]] = []
    for feat in features:
        scores = pd.to_numeric(subset[feat], errors="coerce")
        valid = scores.notna()
        if valid.sum() < 4:
            continue
        valid_scores = scores.loc[valid].astype(float).tolist()
        valid_labels = [labels[i] for i, ok in enumerate(valid.tolist()) if ok]
        auc_pos = auc_pairwise(valid_scores, valid_labels) or 0.0
        auc_neg = auc_pairwise([-x for x in valid_scores], valid_labels) or 0.0
        rows.append(
            {
                "feature": feat,
                "auc": float(max(auc_pos, auc_neg)),
                "direction": "pos" if auc_pos >= auc_neg else "neg",
            }
        )
    rows = sorted(rows, key=lambda x: x["auc"], reverse=True)
    return rows[:top_k]


def build_report(run_df: pd.DataFrame) -> Dict[str, Any]:
    ok_df = run_df[run_df["status"] == "ok"].copy()
    subgroup_summary = (
        ok_df.groupby("subgroup")[
            [
                "duration_h",
                "mean_out_h",
                "mean_dT",
                "candidate_high_info_ratio",
                "heat_related_ratio",
                "complex_ratio",
                "best_lag_h",
                "best_lag_rh_h",
                "gain_ratio_dAH_change",
            ]
        ]
        .median()
        .reset_index()
    )

    confusing_strict = ok_df[
        (ok_df["subgroup"] == "sealed_strict")
        & (ok_df["candidate_high_info_ratio"] >= 0.50)
    ].copy()
    confusing_strict = confusing_strict.sort_values(
        ["candidate_high_info_ratio", "label_ext_high_hum_ratio", "duration_h"],
        ascending=[False, False, False],
    )

    features = [
        "mean_out_h",
        "mean_dT",
        "mean_dAH",
        "delta_half_in_h",
        "delta_half_dAH",
        "slope_in_h_per_h",
        "slope_dAH_per_h",
        "end_start_dAH",
        "candidate_high_info_ratio",
        "heat_related_ratio",
        "best_lag_h",
        "best_lag_rh_h",
        "gain_ratio_dAH_change",
        "max_corr_dAH_change",
        "max_corr_outRH_inRH_change",
    ]
    pair_unsealed_vs_strict = pairwise_feature_ranking(ok_df, "unsealed", "sealed_strict", features)
    pair_unsealed_vs_no_screw = pairwise_feature_ranking(ok_df, "unsealed", "sealed_no_screw_grease", features)

    archive_mismatch = [
        {
            "archive": "sealed.zip",
            "inner_path_label": "非密封状态数据",
        },
        {
            "archive": "unsealed.zip",
            "inner_path_label": "密封状态数据/严格密封 或 密封状态数据/没拧螺丝和黄油但没打孔",
        },
    ]

    return {
        "total_rows": int(len(run_df)),
        "ok_rows": int(len(ok_df)),
        "status_counts": run_df["status"].value_counts().to_dict(),
        "subgroup_counts": ok_df["subgroup"].value_counts().to_dict(),
        "archive_label_mismatch": archive_mismatch,
        "subgroup_summary": subgroup_summary.to_dict(orient="records"),
        "confusing_strict_sealed_count": int(len(confusing_strict)),
        "pair_unsealed_vs_strict_top_features": pair_unsealed_vs_strict,
        "pair_unsealed_vs_no_screw_top_features": pair_unsealed_vs_no_screw,
    }


def write_markdown(path: str, summary: Dict[str, Any], run_df: pd.DataFrame) -> None:
    ok_df = run_df[run_df["status"] == "ok"].copy()
    confusing_strict = ok_df[
        (ok_df["subgroup"] == "sealed_strict")
        & (ok_df["candidate_high_info_ratio"] >= 0.50)
    ].copy()
    confusing_strict = confusing_strict.sort_values("candidate_high_info_ratio", ascending=False)

    lines = [
        "# 历史旧数据干扰分析报告",
        "",
        f"- 可用运行数：`{summary['ok_rows']}`",
        f"- 子集合分布：`{summary['subgroup_counts']}`",
        f"- 状态分布：`{summary['status_counts']}`",
        "",
        "## 首要发现",
        "",
        "- 压缩包文件名与包内目录标签是反的，后续分析必须以包内目录为准，不能直接按 zip 文件名做监督标签。",
        "- 这批历史数据至少不是二分类，而是三类集合：`非密封`、`严格密封`、`没拧螺丝和黄油但没打孔`。",
        "- `严格密封` 里存在一批会被当前规则长时间打成 `candidate_high_info` 的运行，这说明旧数据更适合作为干扰挑战集，而不是直接并入主训练集。",
        "",
        "## 分组中位数",
        "",
    ]

    subgroup_df = pd.DataFrame(summary["subgroup_summary"])
    if not subgroup_df.empty:
        lines.append(subgroup_df.to_markdown(index=False))
        lines.append("")

    lines.extend(
        [
            "## 最容易误导当前路线的严格密封运行",
            "",
            f"- 数量：`{summary['confusing_strict_sealed_count']}`",
        ]
    )
    for _, row in confusing_strict.head(8).iterrows():
        lines.append(
            f"- {row['file']} | candidate_high_info_ratio={row['candidate_high_info_ratio']:.3f} | "
            f"ext_high_hum_ratio={row['label_ext_high_hum_ratio']:.3f} | mean_out_h={row['mean_out_h']:.2f} | "
            f"best_lag_rh_h={row['best_lag_rh_h']}"
        )

    lines.extend(
        [
            "",
            "## 可分性线索",
            "",
            "- `unsealed vs sealed_strict` 的静态简单特征分离度并不高，当前最好的几个单特征 AUC 只在中等水平，说明旧数据确实会把主任务打乱。",
            "- 当前更有前景的不是继续堆静态均值/斜率，而是看动态响应特征：`外部变化 -> 内部变化` 的增益和滞后。",
            "",
            "### unsealed vs sealed_strict Top Features",
            "",
        ]
    )
    for item in summary["pair_unsealed_vs_strict_top_features"]:
        lines.append(f"- {item['feature']} | auc={item['auc']:.3f} | direction={item['direction']}")

    lines.extend(
        [
            "",
            "### unsealed vs sealed_no_screw_grease Top Features",
            "",
        ]
    )
    for item in summary["pair_unsealed_vs_no_screw_top_features"]:
        lines.append(f"- {item['feature']} | auc={item['auc']:.3f} | direction={item['direction']}")

    lines.extend(
        [
            "",
            "## 结论",
            "",
            "- 这批旧数据不适合直接并入当前 `seal/unseal` 主训练集，否则会把大量严格密封运行也推成高风险模式。",
            "- 这批旧数据最合适的角色是：`干扰挑战集 + 负控制集 + 动态响应特征发现集`。",
            "- 如果要继续利用它们，下一步不应先建更复杂分类器，而应先验证动态响应特征，例如 `best_lag_rh_h`、`best_lag_h`、`gain_ratio_dAH_change` 是否能稳定刻画外部激励到内部响应的差异。",
            "",
        ]
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    run_df = analyze_old_data(window_hours=args.window_hours, step_hours=args.step_hours)
    summary = build_report(run_df)

    confusing_df = run_df[
        (run_df["status"] == "ok")
        & (run_df["subgroup"] == "sealed_strict")
        & (run_df["candidate_high_info_ratio"] >= 0.50)
    ].copy()
    confusing_df = confusing_df.sort_values("candidate_high_info_ratio", ascending=False)

    outputs = {
        "run_summary_csv": os.path.join(args.output_dir, "old_data_run_summary.csv"),
        "confusing_cases_csv": os.path.join(args.output_dir, "old_data_confusing_strict_sealed.csv"),
        "report_md": os.path.join(args.output_dir, "old_data_interference_report.md"),
        "report_json": os.path.join(args.output_dir, "old_data_interference_report.json"),
    }

    run_df.to_csv(outputs["run_summary_csv"], index=False, encoding="utf-8-sig")
    confusing_df.to_csv(outputs["confusing_cases_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["report_md"], summary, run_df)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
