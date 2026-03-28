#!/usr/bin/env python3
import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from typing import Any, Dict, List

import pandas as pd


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.anomaly_v2 import local_model as current_local_model
from src.anomaly_v2 import upload_parser


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare seal_v4 transition event hit quality before/after upgrade")
    parser.add_argument("--input-zip", default="data/new_data.zip")
    parser.add_argument(
        "--segment-manifest-csv",
        default="reports/new_data_segment_pipeline_v1_run1/segment_pipeline_manifest.csv",
    )
    parser.add_argument("--baseline-ref", default="HEAD")
    parser.add_argument("--output-dir", default="reports/seal_v4_transition_event_compare_v1_run1")
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
    spec = importlib.util.spec_from_file_location("baseline_local_model_transition", tmp_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to create baseline module spec")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, tmp_path


def reduce_scan_timestamps(scan_timestamps: List[int], max_points: int = 180) -> List[int]:
    if len(scan_timestamps) <= max_points:
        return scan_timestamps
    if max_points <= 1:
        return [scan_timestamps[-1]]
    step = (len(scan_timestamps) - 1) / float(max_points - 1)
    picked: List[int] = []
    for idx in range(max_points):
        pos = int(round(idx * step))
        pos = min(max(pos, 0), len(scan_timestamps) - 1)
        ts = int(scan_timestamps[pos])
        if not picked or picked[-1] != ts:
            picked.append(ts)
    if picked[-1] != int(scan_timestamps[-1]):
        picked.append(int(scan_timestamps[-1]))
    return picked


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


def build_target_files(manifest_csv: str) -> pd.DataFrame:
    manifest_df = pd.read_csv(manifest_csv)
    target_df = manifest_df[
        manifest_df["transition_bucket"].isin(["transition_primary_mainfield", "transition_secondary_control"])
    ][["file", "transition_bucket", "segment_role"]].drop_duplicates().copy()
    target_df["xlsx_name"] = target_df["file"].astype(str) + ".xlsx"
    return target_df.sort_values(["transition_bucket", "file"]).reset_index(drop=True)


def scan_with_module(module: Any, file_name: str, points: List[Dict[str, Any]]) -> Dict[str, Any]:
    prepared = module.prepare_points_df(points)
    resampled = module.resample_points_df(prepared)
    raw_scan_timestamps = [int(ts) for ts in resampled["ts"].dropna().astype("int64").tolist()]
    if not raw_scan_timestamps:
        raw_scan_timestamps = [int(points[-1]["ts"])]
    scan_timestamps = reduce_scan_timestamps(raw_scan_timestamps, 180)
    detections: List[Dict[str, Any]] = []
    point_idx = 0
    prefix_points: List[Dict[str, Any]] = []
    builtin_window_span_ms = 720 * 60_000
    window_start_idx = 0
    for ts in scan_timestamps:
        while point_idx < len(points) and int(points[point_idx]["ts"]) <= ts:
            prefix_points.append(points[point_idx])
            point_idx += 1
        if not prefix_points:
            continue
        min_ts = ts - builtin_window_span_ms
        while window_start_idx < len(prefix_points) and int(prefix_points[window_start_idx]["ts"]) < min_ts:
            window_start_idx += 1
        points_for_scan = prefix_points[window_start_idx:]
        result = module.run_local_detection(
            dev_num=file_name,
            device_timestamp=ts,
            points=points_for_scan,
            requested_model_name="seal_v4",
        )
        detections.append(result)

    transition_hits = [x for x in detections if x.get("status") == "transition_boost_alert"]
    anomaly_hits = [x for x in detections if x.get("is_anomaly")]
    transition_scores = [
        float(((x.get("local_context") or {}).get("transition") or {}).get("score", 0.0) or 0.0)
        for x in detections
    ]
    latest = detections[-1] if detections else {}
    return {
        "scan_count": int(len(detections)),
        "transition_hit_count": int(len(transition_hits)),
        "anomaly_hit_count": int(len(anomaly_hits)),
        "any_transition_hit": bool(transition_hits),
        "latest_status": latest.get("status"),
        "latest_score": float(latest.get("anomaly_score", 0.0) or 0.0) if latest else 0.0,
        "max_transition_score": max(transition_scores) if transition_scores else 0.0,
        "first_transition_ts": int(transition_hits[0]["local_context"]["device_timestamp"]) if transition_hits else None,
    }


def compare_transition_files(args: argparse.Namespace) -> pd.DataFrame:
    baseline_module, baseline_tmp = load_baseline_module(args.baseline_ref)
    target_df = build_target_files(args.segment_manifest_csv)
    rows: List[Dict[str, Any]] = []
    try:
        with zipfile.ZipFile(args.input_zip) as zf, tempfile.TemporaryDirectory(prefix="seal_v4_transition_cmp_") as temp_dir:
            for _, target in target_df.iterrows():
                member = next((m for m in zf.namelist() if os.path.basename(m) == target["xlsx_name"]), None)
                if not member:
                    continue
                points = load_points_from_member(zf, member, temp_dir)
                if not points:
                    continue
                before = scan_with_module(baseline_module, target["xlsx_name"], points)
                after = scan_with_module(current_local_model, target["xlsx_name"], points)
                rows.append(
                    {
                        "file": target["file"],
                        "xlsx_name": target["xlsx_name"],
                        "transition_bucket": target["transition_bucket"],
                        "segment_role": target["segment_role"],
                        "before_transition_hit_count": before["transition_hit_count"],
                        "after_transition_hit_count": after["transition_hit_count"],
                        "transition_hit_delta": int(after["transition_hit_count"] - before["transition_hit_count"]),
                        "before_any_transition_hit": before["any_transition_hit"],
                        "after_any_transition_hit": after["any_transition_hit"],
                        "before_anomaly_hit_count": before["anomaly_hit_count"],
                        "after_anomaly_hit_count": after["anomaly_hit_count"],
                        "before_latest_status": before["latest_status"],
                        "after_latest_status": after["latest_status"],
                        "before_latest_score": before["latest_score"],
                        "after_latest_score": after["latest_score"],
                        "before_max_transition_score": before["max_transition_score"],
                        "after_max_transition_score": after["max_transition_score"],
                        "before_first_transition_ts": before["first_transition_ts"],
                        "after_first_transition_ts": after["first_transition_ts"],
                    }
                )
    finally:
        try:
            os.remove(baseline_tmp)
        except OSError:
            pass
    return pd.DataFrame(rows).sort_values(["transition_bucket", "file"]).reset_index(drop=True)


def build_summary(compare_df: pd.DataFrame) -> Dict[str, Any]:
    primary_df = compare_df[compare_df["transition_bucket"].eq("transition_primary_mainfield")].copy()
    secondary_df = compare_df[compare_df["transition_bucket"].eq("transition_secondary_control")].copy()
    return {
        "file_count": int(len(compare_df)),
        "primary_count": int(len(primary_df)),
        "secondary_count": int(len(secondary_df)),
        "primary_before_any_hit": int(primary_df["before_any_transition_hit"].fillna(False).sum()) if not primary_df.empty else 0,
        "primary_after_any_hit": int(primary_df["after_any_transition_hit"].fillna(False).sum()) if not primary_df.empty else 0,
        "secondary_before_any_hit": int(secondary_df["before_any_transition_hit"].fillna(False).sum()) if not secondary_df.empty else 0,
        "secondary_after_any_hit": int(secondary_df["after_any_transition_hit"].fillna(False).sum()) if not secondary_df.empty else 0,
        "primary_hit_deltas": primary_df[["file", "transition_hit_delta"]].to_dict(orient="records") if not primary_df.empty else [],
    }


def write_markdown(path: str, summary: Dict[str, Any], compare_df: pd.DataFrame) -> None:
    lines = [
        "# seal_v4 Transition 事件级改前改后对照",
        "",
        f"- file_count: `{summary['file_count']}`",
        f"- primary_count: `{summary['primary_count']}`",
        f"- secondary_count: `{summary['secondary_count']}`",
        f"- primary_before_any_hit: `{summary['primary_before_any_hit']}`",
        f"- primary_after_any_hit: `{summary['primary_after_any_hit']}`",
        f"- secondary_before_any_hit: `{summary['secondary_before_any_hit']}`",
        f"- secondary_after_any_hit: `{summary['secondary_after_any_hit']}`",
        "",
        "## 当前结论",
        "",
        "- 这份对照只看 transition 运行的全扫描事件命中，不看最终尾窗一帧。",
        "- 如果 `after_any_transition_hit` 仍然保留，就说明这次 `dew / lag / coupling` 接入主要影响的是尾窗保守性，而不是把整段 transition 事件完全打没。",
        "",
        "## 主战场 transition",
        "",
    ]
    primary_df = compare_df[compare_df["transition_bucket"].eq("transition_primary_mainfield")].copy()
    if primary_df.empty:
        lines.append("- 当前没有主战场 transition 文件。")
    else:
        for _, row in primary_df.iterrows():
            lines.append(
                f"- {row['file']} | hit={row['before_transition_hit_count']}->{row['after_transition_hit_count']} | "
                f"any_hit={bool(row['before_any_transition_hit'])}->{bool(row['after_any_transition_hit'])} | "
                f"latest={row['before_latest_status']}->{row['after_latest_status']} | "
                f"peak_score={row['before_max_transition_score']:.4f}->{row['after_max_transition_score']:.4f}"
            )
    lines.extend(["", "## Secondary control", ""])
    secondary_df = compare_df[compare_df["transition_bucket"].eq("transition_secondary_control")].copy()
    if secondary_df.empty:
        lines.append("- 当前没有 secondary control 文件。")
    else:
        for _, row in secondary_df.iterrows():
            lines.append(
                f"- {row['file']} | hit={row['before_transition_hit_count']}->{row['after_transition_hit_count']} | "
                f"any_hit={bool(row['before_any_transition_hit'])}->{bool(row['after_any_transition_hit'])} | "
                f"latest={row['before_latest_status']}->{row['after_latest_status']} | "
                f"peak_score={row['before_max_transition_score']:.4f}->{row['after_max_transition_score']:.4f}"
            )
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)
    compare_df = compare_transition_files(args)
    summary = build_summary(compare_df)
    outputs = {
        "compare_csv": os.path.join(args.output_dir, "seal_v4_transition_event_compare_v1.csv"),
        "report_md": os.path.join(args.output_dir, "seal_v4_transition_event_compare_v1.md"),
        "report_json": os.path.join(args.output_dir, "seal_v4_transition_event_compare_v1.json"),
    }
    compare_df.to_csv(outputs["compare_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["report_md"], summary, compare_df)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)
    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
