#!/usr/bin/env python3
import argparse
import json
import os
import sys
import tempfile
import zipfile
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.anomaly_v2 import condition_classifier_v1 as cc
from src.scripts.lab_phase1_acceptance import compute_run_features
from src.scripts.old_data_interference_analysis import lag_response_features


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deep analysis for new_data.zip with change-type aware segmentation")
    parser.add_argument("--input-zip", default="data/new_data.zip")
    parser.add_argument("--readme-xlsx", default="/Users/xpker/Downloads/data_readme.xlsx")
    parser.add_argument("--output-dir", default="reports/new_data_deep_analysis_v1")
    parser.add_argument("--window-hours", type=int, default=12)
    parser.add_argument("--step-hours", type=int, default=1)
    parser.add_argument("--segment-min-hours", type=float, default=12.0)
    return parser.parse_args()


def normalize_file_token(value: Any) -> str:
    token = str(value or "").strip()
    token = token.replace("\\", "/").split("/")[-1]
    if token.lower().endswith(".xlsx") or token.lower().endswith(".xls"):
        token = token.rsplit(".", 1)[0]
    return token


def map_level(value: Any) -> str:
    text = str(value or "").strip()
    return {
        "高": "high",
        "低": "low",
        "均衡": "eq",
        "中": "eq",
    }.get(text, "unknown")


def map_heat(value: Any) -> str:
    text = str(value or "").strip()
    return {
        "加": "heat_on",
        "不加": "heat_off",
    }.get(text, "unknown")


def map_seal(value: Any) -> str:
    text = str(value or "").strip()
    return {
        "密封": "sealed",
        "非密封": "unsealed",
    }.get(text, "unknown")


def infer_change_type(has_change: Any, changed_state: Any) -> str:
    changed = str(has_change or "").strip()
    state = str(changed_state or "").strip()
    if changed != "改变":
        return "no_change"
    if state == "不密封":
        return "seal_change_to_unsealed"
    if state == "加热":
        return "heat_on"
    if state == "不加热":
        return "heat_off"
    if state == "外部湿度高":
        return "ext_humidity_up"
    return "other_change"


def parse_change_time(value: Any) -> Optional[pd.Timestamp]:
    if value in (None, "", "无"):
        return None
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    return pd.Timestamp(ts)


def initial_role(ext_level: str, in_level: str, heat_state: str) -> str:
    if ext_level == "high" and in_level == "low" and heat_state == "heat_off":
        return "mainfield_extHigh_intLow_noHeat"
    if ext_level == "high" and in_level == "low" and heat_state == "heat_on":
        return "highhum_heated"
    if ext_level == "eq" and in_level == "eq":
        return "balanced_control"
    if ext_level == "low" and in_level == "high":
        return "internal_moisture_control"
    return "other"


def role_after_change(row: pd.Series) -> str:
    ext_level = row["ext_level"]
    in_level = row["in_level"]
    heat_state = row["heat_state"]
    seal_state = row["seal_state"]
    change_type = row["change_type"]

    if change_type == "seal_change_to_unsealed":
        seal_state = "unsealed"
    elif change_type == "heat_on":
        heat_state = "heat_on"
    elif change_type == "heat_off":
        heat_state = "heat_off"
    elif change_type == "ext_humidity_up":
        ext_level = "high"

    return initial_role(ext_level, in_level, heat_state)


def load_readme(readme_xlsx: str) -> pd.DataFrame:
    df = pd.read_excel(readme_xlsx)
    df = df.rename(
        columns={
            "id": "device_id",
            "开始时间": "start_date",
            "密封状态": "seal_state_cn",
            "外部湿度": "ext_level_cn",
            "内部湿度": "in_level_cn",
            "是否加热": "heat_state_cn",
            "是否中途改变状态": "change_flag_cn",
            "改变时间": "change_time",
            "改变状态": "changed_state_cn",
            "文件名": "file_name",
        }
    )
    df["file"] = df["file_name"].map(normalize_file_token)
    df["seal_state"] = df["seal_state_cn"].map(map_seal)
    df["ext_level"] = df["ext_level_cn"].map(map_level)
    df["in_level"] = df["in_level_cn"].map(map_level)
    df["heat_state"] = df["heat_state_cn"].map(map_heat)
    df["change_type"] = df.apply(lambda r: infer_change_type(r["change_flag_cn"], r["changed_state_cn"]), axis=1)
    df["change_ts"] = df["change_time"].map(parse_change_time)
    df["initial_role"] = df.apply(lambda r: initial_role(r["ext_level"], r["in_level"], r["heat_state"]), axis=1)
    df["post_role"] = df.apply(role_after_change, axis=1)
    return df.sort_values(["initial_role", "file"]).reset_index(drop=True)


def summarize_window_groups(df: pd.DataFrame, window_hours: int, step_hours: int) -> Dict[str, Any]:
    cfg = cc.Config(window_hours=window_hours, step_hours=step_hours)
    windows = cc.sliding_windows(df, cfg)
    counts: Dict[str, int] = {}
    for _, _, wdf in windows:
        feat = cc.extract_features(wdf)
        label = cc.classify_window(feat, cfg)
        counts[label] = counts.get(label, 0) + 1

    total = sum(counts.values())
    dominant_label = max(counts.items(), key=lambda x: x[1])[0] if counts else ""
    return {
        "n_windows": int(total),
        "dominant_label": dominant_label,
        "candidate_high_info_ratio": float(
            sum(counts.get(k, 0) for k in ["外部高湿驱动工况", "内部积湿状态切换窗口"]) / total
        ) if total else np.nan,
        "heat_related_ratio": float(
            sum(counts.get(k, 0) for k in ["热源稳定工况", "热源启动窗口", "冷却窗口"]) / total
        ) if total else np.nan,
        "exclude_low_info_ratio": float(counts.get("低信息工况", 0) / total) if total else np.nan,
        "internal_moisture_ratio": float(counts.get("内部积湿工况", 0) / total) if total else np.nan,
        "complex_ratio": float(counts.get("复杂耦合工况", 0) / total) if total else np.nan,
        "label_counts": counts,
    }


def first_valid_sheet(file_path: str) -> Tuple[str, pd.DataFrame]:
    sheets = cc.load_excel_sheets(file_path)
    for sheet_name, raw_df in sheets:
        try:
            df = cc.preprocess_df(raw_df)
        except Exception:
            continue
        if not df.empty:
            return sheet_name, df
    return "", pd.DataFrame()


def build_run_and_segment_tables(args: argparse.Namespace, readme_df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    meta_map = {row["file"]: row for _, row in readme_df.iterrows()}
    run_rows: List[Dict[str, Any]] = []
    seg_rows: List[Dict[str, Any]] = []

    with zipfile.ZipFile(args.input_zip) as zf, tempfile.TemporaryDirectory(prefix="new_data_deep_") as tmp_dir:
        for member in sorted(zf.namelist()):
            if not member.lower().endswith(".xlsx"):
                continue
            file_name = normalize_file_token(os.path.basename(member))
            target = os.path.join(tmp_dir, os.path.basename(member))
            with zf.open(member) as src, open(target, "wb") as out:
                out.write(src.read())

            sheet_name, df = first_valid_sheet(target)
            meta = meta_map.get(file_name)
            if meta is None:
                run_rows.append({"file": file_name, "status": "missing_readme"})
                continue
            if df.empty:
                run_rows.append({"file": file_name, "status": "no_valid_sheet", **meta.to_dict()})
                continue

            run_feat = compute_run_features(df)
            dynamic_feat = lag_response_features(df)
            route_stats = summarize_window_groups(df, args.window_hours, args.step_hours)
            start_ts = pd.to_datetime(df["time"].min())
            end_ts = pd.to_datetime(df["time"].max())
            duration_h = float((end_ts - start_ts).total_seconds() / 3600.0)
            change_ts = meta["change_ts"]
            pre_hours = np.nan
            post_hours = np.nan
            change_in_range = False
            if change_ts is not None and start_ts <= change_ts <= end_ts:
                change_in_range = True
                pre_hours = float((change_ts - start_ts).total_seconds() / 3600.0)
                post_hours = float((end_ts - change_ts).total_seconds() / 3600.0)

            run_rows.append(
                {
                    "file": file_name,
                    "sheet": sheet_name,
                    "status": "ok",
                    "device_id": meta["device_id"],
                    "seal_state": meta["seal_state"],
                    "ext_level": meta["ext_level"],
                    "in_level": meta["in_level"],
                    "heat_state": meta["heat_state"],
                    "change_type": meta["change_type"],
                    "change_ts": change_ts,
                    "initial_role": meta["initial_role"],
                    "post_role": meta["post_role"],
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                    "duration_h": duration_h,
                    "change_in_range": change_in_range,
                    "pre_hours": pre_hours,
                    "post_hours": post_hours,
                    "n_points": int(len(df)),
                    "n_windows": route_stats["n_windows"],
                    "dominant_label": route_stats["dominant_label"],
                    "candidate_high_info_ratio": route_stats["candidate_high_info_ratio"],
                    "heat_related_ratio": route_stats["heat_related_ratio"],
                    "exclude_low_info_ratio": route_stats["exclude_low_info_ratio"],
                    "internal_moisture_ratio": route_stats["internal_moisture_ratio"],
                    "complex_ratio": route_stats["complex_ratio"],
                    "window_label_counts": json.dumps(route_stats["label_counts"], ensure_ascii=False),
                    **run_feat,
                    **dynamic_feat,
                }
            )

            def add_segment(segment_name: str, seg_df: pd.DataFrame, seg_role: str, seg_seal: str, seg_heat: str, seg_ext: str, source: str) -> None:
                if seg_df.empty:
                    return
                seg_start = pd.to_datetime(seg_df["time"].min())
                seg_end = pd.to_datetime(seg_df["time"].max())
                seg_hours = float((seg_end - seg_start).total_seconds() / 3600.0)
                analyzable = bool(seg_hours >= float(args.segment_min_hours))
                seg_feat = compute_run_features(seg_df)
                seg_rows.append(
                    {
                        "file": file_name,
                        "segment_name": segment_name,
                        "segment_source": source,
                        "segment_start": seg_start,
                        "segment_end": seg_end,
                        "segment_hours": seg_hours,
                        "segment_analyzable": analyzable,
                        "segment_role": seg_role,
                        "segment_seal_state": seg_seal,
                        "segment_heat_state": seg_heat,
                        "segment_ext_level": seg_ext,
                        **seg_feat,
                    }
                )

            if meta["change_type"] == "no_change" or not change_in_range:
                add_segment(
                    "full",
                    df,
                    meta["initial_role"],
                    meta["seal_state"],
                    meta["heat_state"],
                    meta["ext_level"],
                    "full_run",
                )
            else:
                pre_df = df[df["time"] < change_ts].copy()
                post_df = df[df["time"] >= change_ts].copy()
                add_segment(
                    "pre_change",
                    pre_df,
                    meta["initial_role"],
                    meta["seal_state"],
                    meta["heat_state"],
                    meta["ext_level"],
                    meta["change_type"],
                )

                post_seal = meta["seal_state"]
                post_heat = meta["heat_state"]
                post_ext = meta["ext_level"]
                if meta["change_type"] == "seal_change_to_unsealed":
                    post_seal = "unsealed"
                elif meta["change_type"] == "heat_on":
                    post_heat = "heat_on"
                elif meta["change_type"] == "heat_off":
                    post_heat = "heat_off"
                elif meta["change_type"] == "ext_humidity_up":
                    post_ext = "high"

                add_segment(
                    "post_change",
                    post_df,
                    meta["post_role"],
                    post_seal,
                    post_heat,
                    post_ext,
                    meta["change_type"],
                )

    return (
        pd.DataFrame(run_rows).sort_values(["initial_role", "file"]).reset_index(drop=True),
        pd.DataFrame(seg_rows).sort_values(["segment_role", "file", "segment_name"]).reset_index(drop=True),
    )


def build_summary(run_df: pd.DataFrame, seg_df: pd.DataFrame) -> Dict[str, Any]:
    ok_runs = run_df[run_df["status"] == "ok"].copy()
    analyzable_seg = seg_df[seg_df["segment_analyzable"]].copy()

    mainfield_runs = ok_runs[ok_runs["initial_role"] == "mainfield_extHigh_intLow_noHeat"].copy()
    mainfield_static_full = analyzable_seg[
        analyzable_seg["segment_role"].eq("mainfield_extHigh_intLow_noHeat")
        & analyzable_seg["segment_source"].eq("full_run")
    ].copy()
    mainfield_static_split = analyzable_seg[
        analyzable_seg["segment_role"].eq("mainfield_extHigh_intLow_noHeat")
        & analyzable_seg["segment_source"].isin(["seal_change_to_unsealed", "heat_off"])
    ].copy()
    mainfield_post_unseal = analyzable_seg[
        analyzable_seg["segment_role"].eq("mainfield_extHigh_intLow_noHeat")
        & analyzable_seg["segment_seal_state"].eq("unsealed")
    ].copy()
    mainfield_seal_counts = (
        analyzable_seg[analyzable_seg["segment_role"].eq("mainfield_extHigh_intLow_noHeat")]["segment_seal_state"]
        .value_counts(dropna=False)
        .to_dict()
    )

    controls = analyzable_seg[
        analyzable_seg["segment_role"].isin(["balanced_control", "internal_moisture_control", "highhum_heated"])
    ].copy()

    high_candidate = ok_runs.sort_values(
        ["candidate_high_info_ratio", "heat_related_ratio", "internal_moisture_ratio"],
        ascending=[False, False, False],
    ).head(8)

    return {
        "total_runs": int(len(run_df)),
        "ok_runs": int(len(ok_runs)),
        "change_type_counts": ok_runs["change_type"].value_counts(dropna=False).to_dict(),
        "initial_role_counts": ok_runs["initial_role"].value_counts(dropna=False).to_dict(),
        "dominant_label_counts": ok_runs["dominant_label"].value_counts(dropna=False).to_dict(),
        "segment_role_counts": analyzable_seg["segment_role"].value_counts(dropna=False).to_dict() if not analyzable_seg.empty else {},
        "mainfield_whole_runs": int(len(mainfield_runs)),
        "mainfield_full_analyzable_segments": int(len(mainfield_static_full)),
        "mainfield_split_analyzable_segments": int(len(mainfield_static_split)),
        "mainfield_unsealed_segments": int(len(mainfield_post_unseal)),
        "mainfield_seal_counts": mainfield_seal_counts,
        "control_analyzable_segments": int(len(controls)),
        "top_candidate_runs": high_candidate[
            ["file", "initial_role", "change_type", "candidate_high_info_ratio", "heat_related_ratio", "internal_moisture_ratio", "dominant_label"]
        ].to_dict(orient="records"),
    }


def write_markdown(path: str, summary: Dict[str, Any], run_df: pd.DataFrame, seg_df: pd.DataFrame) -> None:
    ok_runs = run_df[run_df["status"] == "ok"].copy()
    analyzable_seg = seg_df[seg_df["segment_analyzable"]].copy()
    mainfield = analyzable_seg[analyzable_seg["segment_role"].eq("mainfield_extHigh_intLow_noHeat")].copy()

    lines = [
        "# 新补充数据深度分析报告",
        "",
        "## 核心结论",
        "",
        f"- 总运行数：`{summary['total_runs']}`",
        f"- 可用运行数：`{summary['ok_runs']}`",
        f"- change_type_counts：`{summary['change_type_counts']}`",
        f"- initial_role_counts：`{summary['initial_role_counts']}`",
        f"- dominant_label_counts：`{summary['dominant_label_counts']}`",
        "",
        "## 先说最关键的判断",
        "",
        "- 这批 `new_data` 不是简单地“在旧数据上多加了几条同分布样本”，而是明显扩展成了 `seal 变化 + heat 变化 + 外部湿度变化 + no-change` 混合数据集。",
        "- 所以如果继续按“整文件 seal/unseal 直接建模”的口径使用它，很多运行会天然变成混合样本，反而会污染当前主任务。",
        "- 这批数据真正的新价值，不主要是增加了多少 whole-run 静态样本，而是提供了更多 **已知改变时刻** 的段级样本和更多 **非密封以外的对照变化**。",
        "",
        "## 这批新数据实际补强了什么",
        "",
        f"- `mainfield_extHigh_intLow_noHeat` whole-run 数量：`{summary['mainfield_whole_runs']}`",
        f"- 主战场 full-run 可分析段数量：`{summary['mainfield_full_analyzable_segments']}`",
        f"- 主战场 split-run 可分析段数量：`{summary['mainfield_split_analyzable_segments']}`",
        f"- 主战场可分析的 `unsealed` 段数量：`{summary['mainfield_unsealed_segments']}`",
        f"- 主战场可分析段 seal/unseal 分布：`{summary['mainfield_seal_counts']}`",
        f"- 对照/干扰可分析段数量：`{summary['control_analyzable_segments']}`",
        "",
        "### 对主战场的意义",
        "",
        "- 如果只看 whole-run，这批数据对 `外部高湿-无热源` 静态 seal/unseal 的直接补充并不算多。",
        "- 但如果按说明表里的 `改变时间` 做段级切分，就能把一部分 `seal->unseal` 运行拆成 `pre sealed` 和 `post unsealed` 两段，从而真正增加可用静态样本和 transition 样本。",
        "",
        "### 对干扰建模的意义",
        "",
        "- `heat_on / heat_off / ext_humidity_up` 这些变化，不应当被当成新的异常正样本，而应被当成 **反事实对照** 或 **干扰控制组**。",
        "- 这批运行最适合用来验证：当前路由是否会把“热源变化”或“外界湿度变化”误当成泄漏证据。",
        "",
        "## 当前高价值运行",
        "",
    ]

    for item in summary["top_candidate_runs"]:
        lines.append(
            f"- {item['file']} | role={item['initial_role']} | change={item['change_type']} | "
            f"candidate_high_info_ratio={item['candidate_high_info_ratio']:.3f} | "
            f"heat_related_ratio={item['heat_related_ratio']:.3f} | "
            f"internal_moisture_ratio={item['internal_moisture_ratio']:.3f} | "
            f"dominant_label={item['dominant_label']}"
        )

    lines.extend(
        [
            "",
            "## 对后续建模最重要的建议",
            "",
            "1. 不要把这批新数据直接并到当前 whole-run 监督训练集里。",
            "2. 先做 `segment_manifest`：把 `pre_change / post_change` 从整文件里拆出来，再决定哪些段能进入主任务。",
            "3. `seal_change_to_unsealed` 的 `pre/post` 段应优先进入两类任务：",
            "   - `transition event detection`",
            "   - `extHigh_intLow_noHeat` 静态段对照",
            "4. `heat_on / heat_off / ext_humidity_up` 应优先进入 `watch / abstain` 和路由鲁棒性验证，不应直接当成 anomaly 正样本。",
            "5. 如果后面继续建模，应优先从“段级建模”而不是“整文件建模”开始。",
            "",
            "## 当前最合理的下一步",
            "",
            "- 第一步：把这批数据先标准化成 `segment_manifest`，而不是直接重训模型。",
            "- 第二步：只在 `extHigh_intLow_noHeat` 的稳定段和 `seal->unseal` 转移段上更新现有主线。",
            "- 第三步：把 `heat_on / heat_off / ext_humidity_up` 作为新的挑战集，专门验证误报控制。",
            "",
        ]
    )

    if not mainfield.empty:
        lines.append("## 主战场可分析段")
        lines.append("")
        for _, row in mainfield.sort_values(["segment_seal_state", "file", "segment_name"]).iterrows():
            lines.append(
                f"- {row['file']} | segment={row['segment_name']} | seal={row['segment_seal_state']} | "
                f"hours={row['segment_hours']:.1f} | source={row['segment_source']} | "
                f"delta_half_in_h={row['delta_half_in_h']:.3f} | delta_half_dAH={row['delta_half_dAH']:.3f}"
            )

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    readme_df = load_readme(args.readme_xlsx)
    run_df, seg_df = build_run_and_segment_tables(args, readme_df)
    summary = build_summary(run_df, seg_df)

    outputs = {
        "readme_csv": os.path.join(args.output_dir, "new_data_readme_normalized.csv"),
        "run_inventory_csv": os.path.join(args.output_dir, "new_data_run_inventory.csv"),
        "segment_manifest_csv": os.path.join(args.output_dir, "new_data_segment_manifest.csv"),
        "report_md": os.path.join(args.output_dir, "new_data_deep_analysis_report.md"),
        "report_json": os.path.join(args.output_dir, "new_data_deep_analysis_report.json"),
    }

    readme_df.to_csv(outputs["readme_csv"], index=False, encoding="utf-8-sig")
    run_df.to_csv(outputs["run_inventory_csv"], index=False, encoding="utf-8-sig")
    seg_df.to_csv(outputs["segment_manifest_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["report_md"], summary, run_df, seg_df)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
