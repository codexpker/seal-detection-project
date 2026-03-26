#!/usr/bin/env python3
import argparse
import json
import os
import sys
import zipfile
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.anomaly_v2 import condition_classifier_v1 as cc
from src.scripts.lab_ext_high_humidity_response_v2 import run_multiscale_branch_v2
from src.scripts.lab_ext_high_humidity_no_heat_probe_v3 import run_no_heat_probe_v3
from src.scripts.lab_phase1_acceptance import Phase1Config
from src.scripts.lab_phase3_evidence_fuser_v4 import run_pipeline_v4
from src.scripts.lab_transition_event_summary_v1 import build_event_table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Unified run/window/review export for the lab v4 pipeline")
    parser.add_argument("--input-dir", default=Phase1Config.input_dir)
    parser.add_argument("--input-zip", default=Phase1Config.input_zip)
    parser.add_argument("--metadata-xlsx", default=Phase1Config.metadata_xlsx)
    parser.add_argument("--output-dir", default="reports/lab_unified_data_interface_v1")
    parser.add_argument("--window-hours", type=int, default=12)
    parser.add_argument("--step-hours", type=int, default=1)
    parser.add_argument("--transition-near-hours", type=int, default=6)
    parser.add_argument("--similarity-k", type=int, default=5)
    return parser.parse_args()


def collect_source_path_map(args: argparse.Namespace) -> Dict[str, str]:
    path_map: Dict[str, str] = {}
    if os.path.isdir(args.input_dir):
        for name in sorted(os.listdir(args.input_dir)):
            full_path = os.path.join(args.input_dir, name)
            if not os.path.isfile(full_path):
                continue
            lower = name.lower()
            if not (lower.endswith(".xlsx") or lower.endswith(".xls")):
                continue
            token = cc.normalize_filename_token(name)
            path_map[token] = os.path.abspath(full_path)
        if path_map:
            return path_map

    if args.input_zip and os.path.exists(args.input_zip):
        with zipfile.ZipFile(args.input_zip) as zf:
            for member in zf.namelist():
                lower = member.lower()
                if member.startswith("old_data/"):
                    continue
                if not (lower.endswith(".xlsx") or lower.endswith(".xls")):
                    continue
                token = cc.normalize_filename_token(os.path.basename(member))
                path_map[token] = f"zip://{os.path.abspath(args.input_zip)}#{member}"
    return path_map


def add_segment_ids(routed_df: pd.DataFrame) -> pd.DataFrame:
    if routed_df.empty:
        return routed_df.copy()
    out = routed_df.sort_values(["file", "sheet", "start_time", "end_time", "window_id"]).copy()
    out["segment_seq"] = (
        out.groupby(["file", "sheet"], dropna=False)["route_role"]
        .transform(lambda s: s.ne(s.shift()).cumsum())
        .astype(int)
    )
    out["segment_id"] = out["segment_seq"].map(lambda x: f"S{x:03d}")
    return out


def map_seal_state(seal_label: Any, expected_family: Any) -> str:
    label = str(seal_label or "").strip()
    family = str(expected_family or "").strip()
    if family == "transition_run":
        return "mixed"
    if label == "seal":
        return "sealed"
    if label == "unseal":
        return "unsealed"
    return "unknown"


def map_heat_state(raw: Any, inferred: Any) -> str:
    value = str(raw or inferred or "").strip()
    if value == "有":
        return "on"
    if value == "无":
        return "off"
    return "mixed"


def map_ext_regime(level: Any, expected_family: Any) -> str:
    text = str(level or "").strip()
    family = str(expected_family or "").strip()
    if text == "高":
        return "high"
    if text == "中":
        return "stable"
    if text == "低":
        return "low"
    if "high_hum" in family:
        return "high"
    return "unknown"


def map_label_coarse(row: pd.Series) -> str:
    transition_phase = str(row.get("transition_phase", "") or "")
    route_role = str(row.get("route_role", "") or "")
    predicted_group = str(row.get("predicted_group", "") or "")

    if transition_phase == "near_transition":
        return "transition_neighbor"
    if route_role in {"reject_low_info", "reject_heat_related"}:
        return "exclude_low_info"
    if route_role in {"reject_complex_or_unknown"} or predicted_group == "complex_coupled":
        return "holdout_complex"
    if route_role in {"transition_core", "transition_context", "static_threshold_favored", "static_memory_candidate", "background_high_hum"}:
        return "candidate_high_info"
    if predicted_group == "exclude_low_info":
        return "exclude_low_info"
    return "holdout_complex"


def map_label_confidence(row: pd.Series) -> str:
    if str(row.get("expected_family", "") or "") != "unknown":
        return "manual_high"
    return "auto_rule"


def to_epoch_ms(series: pd.Series) -> pd.Series:
    ts = pd.to_datetime(series, errors="coerce")
    return ((ts.astype("int64", copy=False) // 10**6).where(ts.notna(), np.nan)).astype("Float64")


def build_run_manifest(
    file_df: pd.DataFrame,
    decision_df: pd.DataFrame,
    event_df: pd.DataFrame,
    source_map: Dict[str, str],
) -> pd.DataFrame:
    decision_cols = [
        "file",
        "final_status",
        "risk_level",
        "primary_evidence",
        "primary_segment_id",
        "needs_review",
        "notes",
    ]
    event_cols = [
        "file",
        "event_start",
        "event_end",
        "peak_time",
        "event_duration_h",
        "peak_transition_phase",
    ]
    merged = file_df.copy()
    merged = merged.merge(decision_df[decision_cols], on="file", how="left")
    merged = merged.merge(event_df[event_cols], on="file", how="left")

    rows: List[Dict[str, Any]] = []
    for _, row in merged.iterrows():
        file_name = str(row["file"])
        notes = str(row.get("notes", "") or "")
        meta_notes = str(row.get("initial_state", "") or "")
        combined_notes = " | ".join([x for x in [meta_notes, notes] if x])
        rows.append(
            {
                "run_id": file_name,
                "file_path": source_map.get(file_name, ""),
                "sheet": row.get("sheet", ""),
                "seal_state_global": map_seal_state(row.get("seal_label"), row.get("expected_family")),
                "has_transition": bool(row.get("expected_family") == "transition_run"),
                "transition_ts": pd.to_datetime(row.get("hole_time"), errors="coerce"),
                "condition_family_manual": row.get("expected_family", ""),
                "heat_state_manual": map_heat_state(row.get("heat_source"), row.get("heat_source_inferred")),
                "ext_humidity_regime_manual": map_ext_regime(row.get("ext_humidity_level"), row.get("expected_family")),
                "device_id_manifest": row.get("device_id_manifest", ""),
                "initial_state": row.get("initial_state", ""),
                "in_humidity_level_manifest": row.get("in_humidity_level", ""),
                "status": row.get("status", ""),
                "n_points": row.get("n_points", np.nan),
                "n_windows": row.get("n_windows", np.nan),
                "candidate_high_info_ratio": row.get("candidate_high_info_ratio", np.nan),
                "heat_related_ratio": row.get("heat_related_ratio", np.nan),
                "exclude_low_info_ratio": row.get("exclude_low_info_ratio", np.nan),
                "final_status": row.get("final_status", ""),
                "risk_level": row.get("risk_level", ""),
                "primary_evidence": row.get("primary_evidence", ""),
                "primary_segment_id": row.get("primary_segment_id", ""),
                "needs_review": row.get("needs_review", False),
                "event_start": pd.to_datetime(row.get("event_start"), errors="coerce"),
                "event_end": pd.to_datetime(row.get("event_end"), errors="coerce"),
                "peak_time": pd.to_datetime(row.get("peak_time"), errors="coerce"),
                "event_duration_h": row.get("event_duration_h", np.nan),
                "peak_transition_phase": row.get("peak_transition_phase", ""),
                "notes": combined_notes,
            }
        )
    return pd.DataFrame(rows).sort_values(["condition_family_manual", "run_id"]).reset_index(drop=True)


def build_window_table(routed_df: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    window_df = add_segment_ids(routed_df)
    out = window_df.copy()
    out["run_id"] = out["file"]
    out["start_ts"] = to_epoch_ms(out["start_time"])
    out["end_ts"] = to_epoch_ms(out["end_time"])
    out["W"] = int(args.window_hours)
    out["S"] = int(args.step_hours)
    out["candidate_condition"] = out["route_branch"].replace({"none": ""})
    out["info_score"] = pd.to_numeric(out.get("info_score_v3"), errors="coerce")
    out["label_coarse"] = out.apply(map_label_coarse, axis=1)
    out["label_confidence"] = out.apply(map_label_confidence, axis=1)

    cols = [
        "run_id",
        "window_id",
        "start_ts",
        "end_ts",
        "W",
        "S",
        "segment_id",
        "candidate_condition",
        "info_score",
        "label_coarse",
        "label_confidence",
        "file",
        "sheet",
        "start_time",
        "end_time",
        "window_center_time",
        "expected_family",
        "transition_phase",
        "seal_label",
        "class_label",
        "predicted_group",
        "route_role",
        "route_branch",
        "route_reason_v3",
        "transition_score_v3",
        "transition_rank_pct_v3",
        "static_context_score_v3",
        "legacy_info_score",
        "delta_half_in_hum",
        "delta_half_dAH",
        "max_hourly_hum_rise",
        "corr_AH",
    ]
    existing_cols = [c for c in cols if c in out.columns]
    return out[existing_cols].sort_values(["run_id", "start_time", "window_id"]).reset_index(drop=True)


def build_review_output(
    decision_df: pd.DataFrame,
    event_df: pd.DataFrame,
    run_manifest_df: pd.DataFrame,
    no_heat_v2_df: pd.DataFrame | None = None,
    cooling_v2_df: pd.DataFrame | None = None,
    no_heat_probe_v3_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    event_cols = [
        "file",
        "event_start",
        "event_end",
        "peak_time",
        "event_duration_h",
        "peak_transition_phase",
        "peak_smooth_score_v3",
        "peak_rank_pct_v3",
        "upper_threshold",
        "lower_threshold",
        "event_window_count",
    ]
    run_cols = [
        "run_id",
        "file_path",
        "condition_family_manual",
        "heat_state_manual",
        "ext_humidity_regime_manual",
    ]
    out = decision_df.copy()
    out = out.merge(event_df[event_cols], left_on="file", right_on="file", how="left")
    out = out.merge(run_manifest_df[run_cols], on="run_id", how="left") if "run_id" in out.columns else out
    if "run_id" not in out.columns:
        out["run_id"] = out["file"]
        out = out.merge(run_manifest_df[run_cols], on="run_id", how="left")

    if no_heat_v2_df is not None and not no_heat_v2_df.empty:
        no_heat_cols = [
            "file",
            "fused_no_heat_status_v2",
            "fused_no_heat_rationale_v2",
            "score_2h",
            "score_6h",
            "score_12h",
            "hits_2h",
            "hits_6h",
            "hits_12h",
        ]
        keep = [c for c in no_heat_cols if c in no_heat_v2_df.columns]
        out = out.merge(no_heat_v2_df[keep], on="file", how="left")

    if cooling_v2_df is not None and not cooling_v2_df.empty:
        cooling_cols = [
            "file",
            "fused_cooling_status_v2",
            "fused_cooling_rationale_v2",
            "count_2h",
            "count_6h",
            "count_12h",
            "q75_12h",
        ]
        keep = [c for c in cooling_cols if c in cooling_v2_df.columns]
        out = out.merge(cooling_v2_df[keep], on="file", how="left")

    if no_heat_probe_v3_df is not None and not no_heat_probe_v3_df.empty:
        probe_cols = [
            "file",
            "probe_status_v3",
            "probe_rationale_v3",
            "onset_positive_v3",
            "late_persistence_v3",
            "breathing_bias_v3",
            "early_respond_in_h_pos_ratio",
            "early_rh_gain_per_out",
            "late_respond_in_h_pos_ratio",
            "late_rh_gain_per_out",
            "late_ah_decay_per_headroom",
        ]
        keep = [c for c in probe_cols if c in no_heat_probe_v3_df.columns]
        merge_cols = ["file"] + [c for c in keep if c != "file" and c not in out.columns]
        if len(merge_cols) > 1:
            out = out.merge(no_heat_probe_v3_df[merge_cols], on="file", how="left")

    out["ext_high_hum_v2_context"] = ""
    if "fused_no_heat_status_v2" in out.columns:
        no_heat_status = out["fused_no_heat_status_v2"].fillna("")
        no_heat_reason = out.get("fused_no_heat_rationale_v2", pd.Series("", index=out.index)).fillna("")
        out.loc[no_heat_status.ne(""), "ext_high_hum_v2_context"] = (
            "no_heat="
            + no_heat_status.astype(str)
            + " | "
            + no_heat_reason.astype(str)
        )
    if "fused_cooling_status_v2" in out.columns:
        cooling_status = out["fused_cooling_status_v2"].fillna("")
        cooling_reason = out.get("fused_cooling_rationale_v2", pd.Series("", index=out.index)).fillna("")
        prefix = np.where(out["ext_high_hum_v2_context"].ne(""), " || ", "")
        out.loc[cooling_status.ne(""), "ext_high_hum_v2_context"] = (
            out.loc[cooling_status.ne(""), "ext_high_hum_v2_context"].astype(str)
            + prefix[cooling_status.ne("")]
            + "cooling="
            + cooling_status[cooling_status.ne("")].astype(str)
            + " | "
            + cooling_reason[cooling_status.ne("")].astype(str)
        )

    out["no_heat_probe_v3_context"] = ""
    if "probe_status_v3" in out.columns:
        probe_status = out["probe_status_v3"].fillna("")
        probe_reason = out.get("probe_rationale_v3", pd.Series("", index=out.index)).fillna("")
        out.loc[probe_status.ne(""), "no_heat_probe_v3_context"] = (
            probe_status.astype(str) + " | " + probe_reason.astype(str)
        )

    out["review_status"] = np.where(out["needs_review"].fillna(False), "pending", "not_required")
    out["review_priority"] = np.select(
        [
            out["final_status"].eq("transition_boost_alert"),
            out["final_status"].eq("static_dynamic_supported_alert"),
            out["final_status"].eq("static_dynamic_support_alert"),
            out["final_status"].eq("static_hard_case_watch"),
        ],
        ["P0_transition", "P1_static_alert", "P2_static_support", "P2_hard_case_watch"],
        default="P3_other",
    )
    out["reviewer"] = ""
    out["review_label"] = ""
    out["review_note"] = ""
    out["event_start"] = pd.to_datetime(out["event_start"], errors="coerce")
    out["event_end"] = pd.to_datetime(out["event_end"], errors="coerce")
    out["peak_time"] = pd.to_datetime(out["peak_time"], errors="coerce")

    cols = [
        "run_id",
        "file",
        "file_path",
        "condition_family_manual",
        "heat_state_manual",
        "ext_humidity_regime_manual",
        "final_status",
        "risk_level",
        "primary_evidence",
        "primary_segment_id",
        "needs_review",
        "review_status",
        "review_priority",
        "event_start",
        "event_end",
        "peak_time",
        "event_duration_h",
        "peak_transition_phase",
        "peak_smooth_score_v3",
        "peak_rank_pct_v3",
        "event_window_count",
        "fused_no_heat_status_v2",
        "fused_no_heat_rationale_v2",
        "score_2h",
        "score_6h",
        "score_12h",
        "hits_2h",
        "hits_6h",
        "hits_12h",
        "fused_cooling_status_v2",
        "fused_cooling_rationale_v2",
        "count_2h",
        "count_6h",
        "count_12h",
        "q75_12h",
        "ext_high_hum_v2_context",
        "probe_status_v3",
        "probe_rationale_v3",
        "onset_positive_v3",
        "late_persistence_v3",
        "breathing_bias_v3",
        "early_respond_in_h_pos_ratio",
        "early_rh_gain_per_out",
        "late_respond_in_h_pos_ratio",
        "late_rh_gain_per_out",
        "late_ah_decay_per_headroom",
        "no_heat_probe_v3_context",
        "notes",
        "reviewer",
        "review_label",
        "review_note",
    ]
    existing_cols = [c for c in cols if c in out.columns]
    sort_rank = out["review_status"].map({"pending": 0, "not_required": 1}).fillna(9)
    out = out.assign(_sort_rank=sort_rank)
    result = out[existing_cols + ["_sort_rank"]].sort_values(["_sort_rank", "review_priority", "run_id"]).reset_index(drop=True)
    return result.drop(columns="_sort_rank")


def build_summary(run_manifest_df: pd.DataFrame, window_table_df: pd.DataFrame, review_df: pd.DataFrame) -> Dict[str, Any]:
    return {
        "run_count": int(len(run_manifest_df)),
        "window_count": int(len(window_table_df)),
        "review_rows": int(len(review_df)),
        "review_pending_rows": int(review_df["review_status"].eq("pending").sum()) if not review_df.empty else 0,
        "condition_family_counts": run_manifest_df["condition_family_manual"].value_counts(dropna=False).to_dict() if not run_manifest_df.empty else {},
        "label_coarse_counts": window_table_df["label_coarse"].value_counts(dropna=False).to_dict() if not window_table_df.empty else {},
        "final_status_counts": run_manifest_df["final_status"].value_counts(dropna=False).to_dict() if not run_manifest_df.empty else {},
    }


def write_markdown(path: str, summary: Dict[str, Any], outputs: Dict[str, str]) -> None:
    lines = [
        "# Unified Data Interface v1",
        "",
        "- 目的：把当前 `evidence_fuser v4` 主路线统一收口为三张正式表，供后续现场迁移、人工复核和历史库建设复用。",
        "- 当前默认主路线：`gate/info selector v3 -> evidence_fuser v4 -> transition event summary`。",
        "- 本次补充：保守接入 `no_heat probe v3` 到无热源高湿静态支线，同时继续在 `review_output` 中保留 `外部高湿响应分支 v2` 的多尺度解释字段。",
        "",
        f"- run_count：`{summary['run_count']}`",
        f"- window_count：`{summary['window_count']}`",
        f"- review_pending_rows：`{summary['review_pending_rows']}`",
        f"- condition_family_counts：`{summary['condition_family_counts']}`",
        f"- label_coarse_counts：`{summary['label_coarse_counts']}`",
        f"- final_status_counts：`{summary['final_status_counts']}`",
        "",
        "## 输出文件",
        "",
        f"- run_manifest: `{outputs['run_manifest_csv']}`",
        f"- window_table: `{outputs['window_table_csv']}`",
        f"- review_output: `{outputs['review_output_csv']}`",
        "",
        "## 当前判断",
        "",
        "- 这一步没有引入新模型，只把当前已验证主路线整理成统一数据接口。",
        "- 后续现场数据、健康窗口库、人工复核结果都应优先复用这三张表，而不是继续从零拼接不同报告。",
        "",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    result = run_pipeline_v4(args)
    ext_high_hum_v2 = run_multiscale_branch_v2(args)
    no_heat_probe_v3_df = run_no_heat_probe_v3(args)["probe_df"]
    event_df, _ = build_event_table(result["routed_df"], result["decision_df"], args)
    source_map = collect_source_path_map(args)

    run_manifest_df = build_run_manifest(result["file_df"], result["decision_df"], event_df, source_map)
    window_table_df = build_window_table(result["routed_df"], args)
    review_df = build_review_output(
        result["decision_df"],
        event_df,
        run_manifest_df,
        no_heat_v2_df=ext_high_hum_v2["no_heat_df"],
        cooling_v2_df=ext_high_hum_v2["cooling_df"],
        no_heat_probe_v3_df=no_heat_probe_v3_df,
    )
    summary = build_summary(run_manifest_df, window_table_df, review_df)

    outputs = {
        "run_manifest_csv": os.path.join(args.output_dir, "run_manifest.csv"),
        "window_table_csv": os.path.join(args.output_dir, "window_table.csv"),
        "review_output_csv": os.path.join(args.output_dir, "review_output.csv"),
        "summary_md": os.path.join(args.output_dir, "unified_data_interface_report.md"),
        "summary_json": os.path.join(args.output_dir, "unified_data_interface_report.json"),
    }

    run_manifest_df.to_csv(outputs["run_manifest_csv"], index=False, encoding="utf-8-sig")
    window_table_df.to_csv(outputs["window_table_csv"], index=False, encoding="utf-8-sig")
    review_df.to_csv(outputs["review_output_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["summary_md"], summary, outputs)
    with open(outputs["summary_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
