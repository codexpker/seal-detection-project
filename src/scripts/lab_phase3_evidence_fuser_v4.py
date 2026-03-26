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

from src.scripts.lab_ext_high_humidity_no_heat_probe_v3 import run_no_heat_probe_v3
from src.scripts.lab_phase1_acceptance import Phase1Config
from src.scripts.lab_phase3_evidence_fuser_v2 import build_summary as build_summary_core
from src.scripts.lab_phase3_evidence_fuser_v3 import run_pipeline_v3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lab phase-3 segment-level evidence fuser v4")
    parser.add_argument("--input-dir", default=Phase1Config.input_dir)
    parser.add_argument("--input-zip", default=Phase1Config.input_zip)
    parser.add_argument("--metadata-xlsx", default=Phase1Config.metadata_xlsx)
    parser.add_argument("--output-dir", default="reports/lab_phase3_evidence_fuser_v4")
    parser.add_argument("--window-hours", type=int, default=12)
    parser.add_argument("--step-hours", type=int, default=1)
    parser.add_argument("--transition-near-hours", type=int, default=6)
    parser.add_argument("--similarity-k", type=int, default=5)
    return parser.parse_args()


def _append_note(notes_text: Any, note: str) -> str:
    parts = [p for p in str(notes_text or "").split(" | ") if p]
    if note not in parts:
        parts.append(note)
    return " | ".join(parts)


def overlay_no_heat_probe_v4(decision_df: pd.DataFrame, probe_df: pd.DataFrame) -> pd.DataFrame:
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
    keep = [c for c in probe_cols if c in probe_df.columns]
    out = decision_df.merge(probe_df[keep], on="file", how="left")
    out["probe_overlay_action_v4"] = ""

    alert_like_statuses = {
        "static_dynamic_supported_alert",
        "static_dynamic_support_alert",
        "static_consensus_alert",
        "static_threshold_only_alert",
        "static_memory_only_alert",
        "static_disagreement_watch",
    }

    for idx, row in out.iterrows():
        if str(row.get("expected_family", "") or "") != "ext_high_hum_no_heat":
            continue

        probe_status = str(row.get("probe_status_v3", "") or "")
        if not probe_status:
            continue

        out.at[idx, "notes"] = _append_note(out.at[idx, "notes"], f"no_heat_probe_v3={probe_status}")

        if probe_status == "ext_high_hum_no_heat_probe_supported":
            if str(row.get("final_status", "") or "") == "static_dynamic_support_alert":
                out.at[idx, "final_status"] = "static_dynamic_supported_alert"
                out.at[idx, "risk_level"] = "high"
                out.at[idx, "primary_evidence"] = "multiview_support+no_heat_probe"
                out.at[idx, "needs_review"] = True
                out.at[idx, "predicted_label"] = 1
                out.at[idx, "probe_overlay_action_v4"] = "supported_upgrades_dynamic_support"
                out.at[idx, "notes"] = _append_note(
                    out.at[idx, "notes"],
                    "no_heat probe corroborates multiview-supported static alert",
                )
            else:
                out.at[idx, "probe_overlay_action_v4"] = "supported_context_only"
        elif probe_status == "ext_high_hum_no_heat_probe_breathing_watch":
            if str(row.get("final_status", "") or "") in alert_like_statuses:
                out.at[idx, "final_status"] = "static_hard_case_watch"
                out.at[idx, "risk_level"] = "watch"
                out.at[idx, "primary_evidence"] = "hard_case_multiview+no_heat_probe"
                out.at[idx, "needs_review"] = True
                out.at[idx, "predicted_label"] = np.nan
                out.at[idx, "probe_overlay_action_v4"] = "breathing_watch_suppresses_static_alert"
                out.at[idx, "notes"] = _append_note(
                    out.at[idx, "notes"],
                    "no_heat probe breathing watch suppresses static alerting",
                )
            else:
                out.at[idx, "probe_overlay_action_v4"] = "breathing_watch_context_only"
        elif probe_status == "ext_high_hum_no_heat_probe_negative":
            out.at[idx, "probe_overlay_action_v4"] = "negative_context_only"

    return out


def run_pipeline_v4(args: argparse.Namespace) -> Dict[str, Any]:
    base = run_pipeline_v3(args)
    probe = run_no_heat_probe_v3(args)
    decision_df = overlay_no_heat_probe_v4(base["decision_df"], probe["probe_df"])
    summary = build_summary_v4(
        decision_df,
        base["transition_df"],
        base["threshold_df"],
        base["multiview_df"],
    )
    return {
        **base,
        "decision_df": decision_df,
        "summary": summary,
        "probe_df": probe["probe_df"],
        "probe_summary": probe["summary"],
    }


def build_summary_v4(
    decision_df: pd.DataFrame,
    transition_df: pd.DataFrame,
    threshold_df: pd.DataFrame,
    multiview_df: pd.DataFrame,
) -> Dict[str, Any]:
    summary = build_summary_core(decision_df, transition_df, threshold_df, multiview_df)
    promoted_supported_count = int(
        decision_df.get("probe_overlay_action_v4", pd.Series("", index=decision_df.index))
        .eq("supported_upgrades_dynamic_support")
        .sum()
    )
    if promoted_supported_count <= 0:
        return summary

    dynamic_recovered_count = int(summary["dynamic_support_recovered_runs"]) + promoted_supported_count
    acceptance = dict(summary["acceptance"])
    acceptance["dynamic_support_recovers_miss"] = bool(dynamic_recovered_count > 0)

    if all(acceptance.values()):
        verdict = "PASS"
    elif acceptance["transition_evidence_captured"] and acceptance["all_runs_resolved_to_status"]:
        verdict = "PARTIAL_PASS"
    else:
        verdict = "FAIL"

    summary["dynamic_support_recovered_runs"] = dynamic_recovered_count
    summary["acceptance"] = acceptance
    summary["verdict"] = verdict
    return summary


def compare_v3_v4(v3_result: Dict[str, Any], v4_result: Dict[str, Any]) -> Dict[str, Any]:
    v3_df = v3_result["decision_df"][
        ["file", "final_status", "primary_evidence", "risk_level"]
    ].copy()
    v3_df = v3_df.rename(
        columns={
            "final_status": "final_status_v3",
            "primary_evidence": "primary_evidence_v3",
            "risk_level": "risk_level_v3",
        }
    )
    v4_df = v4_result["decision_df"][
        ["file", "final_status", "primary_evidence", "risk_level", "probe_overlay_action_v4"]
    ].copy()
    v4_df = v4_df.rename(
        columns={
            "final_status": "final_status_v4",
            "primary_evidence": "primary_evidence_v4",
            "risk_level": "risk_level_v4",
        }
    )
    merged = v3_df.merge(v4_df, on="file", how="outer")
    merged["status_changed"] = merged["final_status_v3"] != merged["final_status_v4"]
    merged["evidence_changed"] = merged["primary_evidence_v3"] != merged["primary_evidence_v4"]
    merged["risk_changed"] = merged["risk_level_v3"] != merged["risk_level_v4"]

    changed_status_files = merged.loc[merged["status_changed"], "file"].dropna().tolist()
    changed_evidence_files = merged.loc[merged["evidence_changed"], "file"].dropna().tolist()
    changed_risk_files = merged.loc[merged["risk_changed"], "file"].dropna().tolist()

    probe_files = set(v4_result["probe_df"]["file"].dropna().tolist()) if not v4_result["probe_df"].empty else set()
    non_no_heat_changed = [name for name in changed_status_files if name not in probe_files]
    promoted_supported = int(
        v4_result["decision_df"]["probe_overlay_action_v4"]
        .eq("supported_upgrades_dynamic_support")
        .sum()
    )
    suppressed_breathing = int(
        v4_result["decision_df"]["probe_overlay_action_v4"]
        .eq("breathing_watch_suppresses_static_alert")
        .sum()
    )

    adoption_checks = {
        "verdict_not_worse": v4_result["summary"]["verdict"] in {"PASS", v3_result["summary"]["verdict"]},
        "transition_capture_not_worse": float(v4_result["summary"]["transition_capture_rate"])
        >= float(v3_result["summary"]["transition_capture_rate"]),
        "transition_boost_not_worse": float(v4_result["summary"]["transition_boost_capture_rate"])
        >= float(v3_result["summary"]["transition_boost_capture_rate"]),
        "static_balanced_accuracy_not_worse": float(v4_result["summary"]["static_eval_balanced_accuracy"])
        >= float(v3_result["summary"]["static_eval_balanced_accuracy"]),
        "static_coverage_not_worse": float(v4_result["summary"]["static_prediction_coverage"])
        >= float(v3_result["summary"]["static_prediction_coverage"]),
        "changes_restricted_to_no_heat_branch": len(non_no_heat_changed) == 0,
        "probe_effective": bool(promoted_supported + suppressed_breathing > 0),
    }

    return {
        "status_changed_count": int(merged["status_changed"].sum()),
        "evidence_changed_count": int(merged["evidence_changed"].sum()),
        "risk_changed_count": int(merged["risk_changed"].sum()),
        "changed_status_files": changed_status_files,
        "changed_evidence_files": changed_evidence_files,
        "changed_risk_files": changed_risk_files,
        "promoted_supported_count": promoted_supported,
        "suppressed_breathing_count": suppressed_breathing,
        "non_no_heat_status_changes": non_no_heat_changed,
        "adoption_checks": adoption_checks,
        "adopt_v4_default": bool(all(adoption_checks.values())),
        "merged": merged,
    }


def write_markdown(
    path: str,
    v3_result: Dict[str, Any],
    v4_result: Dict[str, Any],
    comparison: Dict[str, Any],
) -> None:
    summary = v4_result["summary"]
    review_df = v4_result["decision_df"][v4_result["decision_df"]["needs_review"]].copy()
    probe_df = v4_result["probe_df"]

    lines = [
        "# 实验室第三阶段 状态段级证据融合 v4 报告",
        "",
        f"- 结论：`{summary['verdict']}`",
        f"- review_queue_runs：`{summary['review_queue_runs']}`",
        f"- transition_capture_rate：`{summary['transition_capture_rate']}`",
        f"- transition_boost_capture_rate：`{summary['transition_boost_capture_rate']}`",
        f"- static_eval_balanced_accuracy：`{summary['static_eval_balanced_accuracy']}`",
        f"- static_prediction_coverage：`{summary['static_prediction_coverage']}`",
        f"- adopt_v4_default：`{comparison['adopt_v4_default']}`",
        "",
        "## v4 的核心变化",
        "",
        "- 只在 `外部高湿-无热源` 静态支线上接入 `no_heat probe v3`，不改 transition 主线，也不重启 cooling 分支。",
        "- `probe_supported` 只增强 `static_dynamic_support_alert` 这一类“已有静态支持但还不够强”的运行。",
        "- `probe_breathing_watch` 只作为误报抑制层，对 alert-like 静态运行主动压回 watch。",
        "",
        "## v3 / v4 对照",
        "",
        f"- v3_verdict = `{v3_result['summary']['verdict']}`",
        f"- v4_verdict = `{v4_result['summary']['verdict']}`",
        f"- status_changed_count = `{comparison['status_changed_count']}`",
        f"- evidence_changed_count = `{comparison['evidence_changed_count']}`",
        f"- risk_changed_count = `{comparison['risk_changed_count']}`",
        f"- changed_status_files = `{comparison['changed_status_files']}`",
        f"- promoted_supported_count = `{comparison['promoted_supported_count']}`",
        f"- suppressed_breathing_count = `{comparison['suppressed_breathing_count']}`",
        "",
        "## 验收判断",
        "",
    ]
    for key, value in summary["acceptance"].items():
        lines.append(f"- {key} = `{value}`")
    for key, value in comparison["adoption_checks"].items():
        lines.append(f"- {key} = `{value}`")

    lines.extend(["", "## no-heat probe v3 叠加结果", ""])
    for _, row in probe_df.iterrows():
        decision_row = v4_result["decision_df"].loc[v4_result["decision_df"]["file"] == row["file"]]
        if decision_row.empty:
            continue
        d = decision_row.iloc[0]
        lines.append(
            f"- {row['file']} | probe={row['probe_status_v3']} | overlay={d['probe_overlay_action_v4']} | "
            f"final_status={d['final_status']} | evidence={d['primary_evidence']} | rationale={row['probe_rationale_v3']}"
        )

    lines.extend(["", "## 需要复核的运行", ""])
    for _, row in review_df.iterrows():
        overlay = str(row.get("probe_overlay_action_v4", "") or "")
        extra = f" | overlay={overlay}" if overlay else ""
        lines.append(
            f"- {row['file']} | status={row['final_status']} | evidence={row['primary_evidence']} | "
            f"segment={row['primary_segment_id']} | notes={row['notes']}{extra}"
        )

    lines.extend(
        [
            "",
            "## 当前判断",
            "",
            "- `v4` 不是新模型，而是把已经验证通过的 `no_heat probe v3` 以极小范围接回静态决策层。",
            "- 如果 `adopt_v4_default = True`，后续默认主线可以升级成：`gate/info selector v3 -> evidence_fuser v4 -> transition event summary`。",
            "- cooling 仍保持 review / 物理解释探针角色，不进入默认主判定。",
            "",
        ]
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    v3_result = run_pipeline_v3(args)
    v4_result = run_pipeline_v4(args)
    comparison = compare_v3_v4(v3_result, v4_result)

    outputs = {
        "decision_csv": os.path.join(args.output_dir, "phase3_run_decisions.csv"),
        "decision_compare_csv": os.path.join(args.output_dir, "phase3_v3_v4_decision_compare.csv"),
        "report_md": os.path.join(args.output_dir, "phase3_evidence_fuser_report.md"),
        "report_json": os.path.join(args.output_dir, "phase3_evidence_fuser_report.json"),
    }

    v4_result["decision_df"].to_csv(outputs["decision_csv"], index=False, encoding="utf-8-sig")
    comparison["merged"].to_csv(outputs["decision_compare_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["report_md"], v3_result, v4_result, comparison)

    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump(
            {
                "v4_summary": v4_result["summary"],
                "v3_summary": v3_result["summary"],
                "comparison": {k: v for k, v in comparison.items() if k != "merged"},
                "probe_summary": v4_result["probe_summary"],
                "outputs": outputs,
            },
            f,
            ensure_ascii=False,
            indent=2,
            default=str,
        )

    print(
        json.dumps(
            {
                "v4_summary": v4_result["summary"],
                "v3_summary": v3_result["summary"],
                "comparison": {k: v for k, v in comparison.items() if k != "merged"},
                "probe_summary": v4_result["probe_summary"],
                "outputs": outputs,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
