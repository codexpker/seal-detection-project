#!/usr/bin/env python3
import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter
from typing import Any, Dict, List

import pandas as pd


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.anomaly_v2 import local_model as current_local_model
from src.anomaly_v2 import upload_parser


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare current seal_v4 with HEAD baseline on new_data.zip")
    parser.add_argument("--input-zip", default="data/new_data.zip")
    parser.add_argument("--baseline-ref", default="HEAD")
    parser.add_argument("--output-dir", default="reports/seal_v4_upgrade_compare_v1_run1")
    return parser.parse_args()


def load_baseline_module(git_ref: str):
    content = subprocess.check_output(
        ["git", "show", f"{git_ref}:src/anomaly_v2/local_model.py"],
        cwd=ROOT_DIR,
        text=True,
    )
    with tempfile.NamedTemporaryFile("w", suffix="_baseline_local_model.py", delete=False, encoding="utf-8") as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    spec = importlib.util.spec_from_file_location("baseline_local_model", tmp_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to create baseline module spec")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, tmp_path


def load_points_from_member(zf: zipfile.ZipFile, member: str, temp_dir: str) -> List[Dict[str, Any]]:
    target = os.path.join(temp_dir, os.path.basename(member))
    with zf.open(member) as src, open(target, "wb") as out:
        out.write(src.read())
    xls = pd.ExcelFile(target)
    df = None
    for sheet in xls.sheet_names:
        try:
            raw = pd.read_excel(target, sheet_name=sheet)
            cand = upload_parser.preprocess_excel_df(raw)
            if not cand.empty:
                df = cand
                break
        except Exception:
            continue
    if df is None or df.empty:
        return []
    return [
        {
            "ts": int(pd.Timestamp(row.time).value // 1_000_000),
            "in_temp": float(row.in_temp),
            "out_temp": float(row.out_temp),
            "in_hum": float(row.in_hum),
            "out_hum": float(row.out_hum),
        }
        for row in df.itertuples()
    ]


def compare_runs(args: argparse.Namespace) -> pd.DataFrame:
    baseline_module, baseline_tmp = load_baseline_module(args.baseline_ref)
    rows: List[Dict[str, Any]] = []
    try:
        with zipfile.ZipFile(args.input_zip) as zf, tempfile.TemporaryDirectory(prefix="seal_v4_cmp_") as temp_dir:
            for member in zf.namelist():
                if not member.lower().endswith(".xlsx"):
                    continue
                file_name = os.path.basename(member)
                points = load_points_from_member(zf, member, temp_dir)
                if not points:
                    continue
                latest_ts = int(points[-1]["ts"])
                before = baseline_module.run_local_detection(
                    dev_num=file_name,
                    device_timestamp=latest_ts,
                    points=points,
                    requested_model_name="seal_v4",
                )
                after = current_local_model.run_local_detection(
                    dev_num=file_name,
                    device_timestamp=latest_ts,
                    points=points,
                    requested_model_name="seal_v4",
                )
                before_ctx = before.get("local_context") or {}
                after_ctx = after.get("local_context") or {}
                before_no_heat = before_ctx.get("no_heat") or {}
                after_no_heat = after_ctx.get("no_heat") or {}
                after_mv = after_no_heat.get("multiview_v2") or {}
                rows.append(
                    {
                        "file": file_name,
                        "before_status": before.get("status"),
                        "after_status": after.get("status"),
                        "status_changed": bool(before.get("status") != after.get("status")),
                        "before_is_anomaly": bool(before.get("is_anomaly")),
                        "after_is_anomaly": bool(after.get("is_anomaly")),
                        "anomaly_changed": bool(bool(before.get("is_anomaly")) != bool(after.get("is_anomaly"))),
                        "before_score": float(before.get("anomaly_score", 0.0) or 0.0),
                        "after_score": float(after.get("anomaly_score", 0.0) or 0.0),
                        "score_delta": float((after.get("anomaly_score", 0.0) or 0.0) - (before.get("anomaly_score", 0.0) or 0.0)),
                        "branch": after_ctx.get("context_branch") or before_ctx.get("context_branch"),
                        "before_transition_status": (before_ctx.get("transition") or {}).get("status"),
                        "after_transition_status": (after_ctx.get("transition") or {}).get("status"),
                        "before_no_heat_status": before_no_heat.get("status"),
                        "after_no_heat_status": after_no_heat.get("status"),
                        "support_score_v2": after_mv.get("support_score_v2"),
                        "breathing_guard_score_v2": after_mv.get("breathing_guard_score_v2"),
                        "confound_guard_score_v2": after_mv.get("confound_guard_score_v2"),
                    }
                )
    finally:
        try:
            os.remove(baseline_tmp)
        except OSError:
            pass
    return pd.DataFrame(rows).sort_values("file").reset_index(drop=True)


def build_summary(compare_df: pd.DataFrame) -> Dict[str, Any]:
    changed_df = compare_df[compare_df["status_changed"]].copy()
    anomaly_changed_df = compare_df[compare_df["anomaly_changed"]].copy()
    ext_high_df = compare_df[compare_df["branch"].eq("ext_high_hum_no_heat")].copy()
    return {
        "run_count": int(len(compare_df)),
        "status_changed_count": int(len(changed_df)),
        "anomaly_changed_count": int(len(anomaly_changed_df)),
        "before_status_counts": Counter(compare_df["before_status"]).copy(),
        "after_status_counts": Counter(compare_df["after_status"]).copy(),
        "ext_high_hum_no_heat_count": int(len(ext_high_df)),
        "ext_high_status_changed_count": int(ext_high_df["status_changed"].sum()) if not ext_high_df.empty else 0,
        "changed_files": changed_df["file"].tolist(),
    }


def write_markdown(path: str, summary: Dict[str, Any], compare_df: pd.DataFrame) -> None:
    changed_df = compare_df[compare_df["status_changed"]].copy()
    lines = [
        "# seal_v4 在线模型改前改后对照报告",
        "",
        f"- run_count: `{summary['run_count']}`",
        f"- status_changed_count: `{summary['status_changed_count']}`",
        f"- anomaly_changed_count: `{summary['anomaly_changed_count']}`",
        f"- ext_high_hum_no_heat_count: `{summary['ext_high_hum_no_heat_count']}`",
        f"- ext_high_status_changed_count: `{summary['ext_high_status_changed_count']}`",
        f"- before_status_counts: `{dict(summary['before_status_counts'])}`",
        f"- after_status_counts: `{dict(summary['after_status_counts'])}`",
        "",
        "## 当前结论",
        "",
        "- 这次改动不是重训 whole-run 模型，而是把已验证有效的 `dew / lag / coupling / persistence` 结构特征接进当前在线 `seal_v4`。",
        "- 主要目标是：减少 `ext_high_hum_no_heat` 主战场里 guarded positive 的误抬，并把 `breathing / confound` 更稳定地压回 `watch`。",
        "",
        "## 状态发生变化的文件",
        "",
    ]
    if changed_df.empty:
        lines.append("- 本轮对照没有出现状态变化。")
    else:
        for _, row in changed_df.iterrows():
            lines.append(
                f"- {row['file']} | {row['before_status']} -> {row['after_status']} | "
                f"before_score={row['before_score']:.4f} | after_score={row['after_score']:.4f} | "
                f"support={row['support_score_v2'] if pd.notna(row['support_score_v2']) else 'nan'} | "
                f"breathing_guard={row['breathing_guard_score_v2'] if pd.notna(row['breathing_guard_score_v2']) else 'nan'} | "
                f"confound_guard={row['confound_guard_score_v2'] if pd.notna(row['confound_guard_score_v2']) else 'nan'}"
            )
    lines.extend(
        [
            "",
            "## 全量结果",
            "",
        ]
    )
    for _, row in compare_df.iterrows():
        lines.append(
            f"- {row['file']} | branch={row['branch']} | {row['before_status']} -> {row['after_status']} | "
            f"anomaly={row['before_is_anomaly']}->{row['after_is_anomaly']} | score={row['before_score']:.4f}->{row['after_score']:.4f}"
        )
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)
    compare_df = compare_runs(args)
    summary = build_summary(compare_df)
    outputs = {
        "compare_csv": os.path.join(args.output_dir, "seal_v4_upgrade_compare_v1.csv"),
        "report_md": os.path.join(args.output_dir, "seal_v4_upgrade_compare_v1.md"),
        "report_json": os.path.join(args.output_dir, "seal_v4_upgrade_compare_v1.json"),
    }
    compare_df.to_csv(outputs["compare_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["report_md"], summary, compare_df)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)
    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
