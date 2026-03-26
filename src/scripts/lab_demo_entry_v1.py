#!/usr/bin/env python3
import argparse
import json
import os
import sys
from typing import Any, Dict, List

import pandas as pd

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.scripts.lab_ext_high_humidity_response_v2 import run_multiscale_branch_v2
from src.scripts.lab_ext_high_humidity_no_heat_probe_v3 import run_no_heat_probe_v3
from src.scripts.lab_phase1_acceptance import Phase1Config
from src.scripts.lab_phase3_evidence_fuser_v4 import run_pipeline_v4
from src.scripts.lab_transition_event_summary_v1 import build_event_table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Demo-oriented entry for lab evidence fuser v4")
    parser.add_argument("--input-dir", default=Phase1Config.input_dir)
    parser.add_argument("--input-zip", default=Phase1Config.input_zip)
    parser.add_argument("--metadata-xlsx", default=Phase1Config.metadata_xlsx)
    parser.add_argument("--output-dir", default="reports/lab_demo_entry_v1")
    parser.add_argument("--window-hours", type=int, default=12)
    parser.add_argument("--step-hours", type=int, default=1)
    parser.add_argument("--transition-near-hours", type=int, default=6)
    parser.add_argument("--similarity-k", type=int, default=5)
    parser.add_argument("--focus-file", default="", help="Optional file name or partial token to generate a focused demo card.")
    return parser.parse_args()


def collect_demo_outputs(args: argparse.Namespace) -> Dict[str, pd.DataFrame]:
    outputs = run_pipeline_v4(args)
    event_df, _ = build_event_table(outputs["routed_df"], outputs["decision_df"], args)
    ext_high_hum_v2 = run_multiscale_branch_v2(args)
    no_heat_probe_v3 = run_no_heat_probe_v3(args)
    outputs["event_df"] = event_df
    outputs["summary_df"] = pd.DataFrame([outputs["summary"]])
    outputs["ext_high_hum_v2_summary_df"] = pd.DataFrame([ext_high_hum_v2["summary"]])
    outputs["ext_high_hum_no_heat_v2_df"] = ext_high_hum_v2["no_heat_df"]
    outputs["ext_high_hum_cooling_v2_df"] = ext_high_hum_v2["cooling_df"]
    outputs["no_heat_probe_v3_summary_df"] = pd.DataFrame([no_heat_probe_v3["summary"]])
    outputs["no_heat_probe_v3_df"] = no_heat_probe_v3["probe_df"]
    return outputs


def _match_focus_file(decision_df: pd.DataFrame, focus: str) -> str:
    if not focus:
        return ""
    exact = decision_df.loc[decision_df["file"] == focus, "file"]
    if not exact.empty:
        return str(exact.iloc[0])
    partial = decision_df.loc[decision_df["file"].astype(str).str.contains(focus, case=False, regex=False), "file"]
    if not partial.empty:
        return str(partial.iloc[0])
    return ""


def _to_float(value: Any) -> str:
    if pd.isna(value):
        return "-"
    return f"{float(value):.3f}"


def build_run_card(
    file_name: str,
    decision_df: pd.DataFrame,
    segments_df: pd.DataFrame,
    transition_boost_df: pd.DataFrame,
    multiview_df: pd.DataFrame,
    event_df: pd.DataFrame,
    no_heat_v2_df: pd.DataFrame,
    cooling_v2_df: pd.DataFrame,
    no_heat_probe_v3_df: pd.DataFrame,
) -> List[str]:
    row = decision_df.loc[decision_df["file"] == file_name].iloc[0]
    lines = [
        f"## {file_name}",
        "",
        f"- final_status: `{row['final_status']}`",
        f"- risk_level: `{row['risk_level']}`",
        f"- primary_evidence: `{row['primary_evidence']}`",
        f"- dominant_route_role: `{row['dominant_route_role']}`",
        f"- primary_segment_id: `{row['primary_segment_id']}`",
        f"- needs_review: `{bool(row['needs_review'])}`",
        f"- notes: `{row['notes']}`",
        "",
    ]

    seg = segments_df[
        (segments_df["file"] == file_name)
        & (segments_df["segment_id"] == row["primary_segment_id"])
    ].copy()
    if not seg.empty:
        s = seg.iloc[0]
        lines.extend(
            [
                "### 主证据段",
                "",
                f"- branch: `{s['route_branch']}`",
                f"- role: `{s['route_role']}`",
                f"- start_time: `{s['start_time']}`",
                f"- end_time: `{s['end_time']}`",
                f"- n_windows: `{int(s['n_windows'])}`",
                f"- mean_info_score_v2: `{_to_float(s['mean_info_score_v2'])}`",
                f"- max_info_score_v2: `{_to_float(s['max_info_score_v2'])}`",
                f"- mean_transition_score: `{_to_float(s['mean_transition_score'])}`",
                f"- mean_delta_half_dAH: `{_to_float(s['mean_delta_half_dAH'])}`",
                "",
            ]
        )

    trans = transition_boost_df.loc[transition_boost_df["file"] == file_name]
    if not trans.empty:
        t = trans.iloc[0]
        lines.extend(
            [
                "### Transition Boost",
                "",
                f"- transition_boost: `{bool(t['transition_boost'])}`",
                f"- transition_boost_count: `{int(t['transition_boost_count'])}`",
                f"- transition_boost_features: `{t['transition_boost_features']}`",
                "",
            ]
        )

    event = event_df.loc[event_df["file"] == file_name]
    if not event.empty:
        e = event.iloc[0]
        lines.extend(
            [
                "### Transition Event",
                "",
                f"- event_start: `{e['event_start']}`",
                f"- event_end: `{e['event_end']}`",
                f"- event_duration_h: `{_to_float(e['event_duration_h'])}`",
                f"- peak_time: `{e['peak_time']}`",
                f"- peak_phase: `{e['peak_transition_phase']}`",
                f"- peak_smooth_score_v3: `{_to_float(e['peak_smooth_score_v3'])}`",
                f"- upper_threshold: `{_to_float(e['upper_threshold'])}`",
                f"- lower_threshold: `{_to_float(e['lower_threshold'])}`",
                "",
            ]
        )

    mv = multiview_df.loc[multiview_df["file"] == file_name]
    if not mv.empty:
        m = mv.iloc[0]
        lines.extend(
            [
                "### Static Multiview",
                "",
                f"- dynamic_vote_count: `{int(m['dynamic_vote_count'])}/{int(m['dynamic_vote_total'])}`",
                f"- dynamic_support: `{bool(m['dynamic_support'])}`",
                f"- dynamic_hit_features: `{m['dynamic_hit_features']}`",
                f"- hard_case_watch: `{bool(m['hard_case_watch'])}`",
                f"- hard_case_ratio: `{_to_float(m['hard_case_ratio'])}`",
                f"- nearest_other_file: `{m['nearest_other_file']}`",
                f"- nearest_other_distance: `{_to_float(m['nearest_other_distance'])}`",
                "",
            ]
        )

    no_heat_v2 = no_heat_v2_df.loc[no_heat_v2_df["file"] == file_name]
    cooling_v2 = cooling_v2_df.loc[cooling_v2_df["file"] == file_name]
    if not no_heat_v2.empty or not cooling_v2.empty:
        lines.extend(["### 外部高湿响应 v2", ""])
        if not no_heat_v2.empty:
            n = no_heat_v2.iloc[0]
            lines.extend(
                [
                    f"- no_heat_status_v2: `{n['fused_no_heat_status_v2']}`",
                    f"- no_heat_rationale_v2: `{n['fused_no_heat_rationale_v2']}`",
                    f"- no_heat_hits_2h_6h_12h: `{int(n['hits_2h'])}/{int(n['hits_6h'])}/{int(n['hits_12h'])}`",
                    f"- no_heat_scores_2h_6h_12h: `{_to_float(n['score_2h'])}/{_to_float(n['score_6h'])}/{_to_float(n['score_12h'])}`",
                ]
            )
        if not cooling_v2.empty:
            c = cooling_v2.iloc[0]
            lines.extend(
                [
                    f"- cooling_status_v2: `{c['fused_cooling_status_v2']}`",
                    f"- cooling_rationale_v2: `{c['fused_cooling_rationale_v2']}`",
                    f"- cooling_counts_2h_6h_12h: `{int(c['count_2h'])}/{int(c['count_6h'])}/{int(c['count_12h'])}`",
                    f"- cooling_q75_dAH_12h: `{_to_float(c['q75_12h'])}`",
                ]
            )
        lines.append("")

    probe_v3 = no_heat_probe_v3_df.loc[no_heat_probe_v3_df["file"] == file_name]
    if not probe_v3.empty:
        p = probe_v3.iloc[0]
        lines.extend(
            [
                "### 无热源高湿 Probe v3",
                "",
                f"- probe_status_v3: `{p['probe_status_v3']}`",
                f"- probe_rationale_v3: `{p['probe_rationale_v3']}`",
                f"- onset_positive_v3: `{bool(p['onset_positive_v3'])}`",
                f"- late_persistence_v3: `{bool(p['late_persistence_v3'])}`",
                f"- breathing_bias_v3: `{bool(p['breathing_bias_v3'])}`",
                f"- early_resp_ratio / early_rh_gain: `{_to_float(p['early_respond_in_h_pos_ratio'])} / {_to_float(p['early_rh_gain_per_out'])}`",
                f"- late_resp_ratio / late_rh_gain: `{_to_float(p['late_respond_in_h_pos_ratio'])} / {_to_float(p['late_rh_gain_per_out'])}`",
                f"- late_ah_decay_per_headroom: `{_to_float(p['late_ah_decay_per_headroom'])}`",
                "",
            ]
        )
    return lines


def write_overview(
    path: str,
    summary: Dict[str, Any],
    decision_df: pd.DataFrame,
    transition_boost_df: pd.DataFrame,
    event_df: pd.DataFrame,
    ext_high_hum_v2_summary: Dict[str, Any],
    no_heat_v2_df: pd.DataFrame,
    cooling_v2_df: pd.DataFrame,
    no_heat_probe_v3_summary: Dict[str, Any],
    no_heat_probe_v3_df: pd.DataFrame,
) -> None:
    lines = [
        "# 现场演示总览",
        "",
        "## 当前主线",
        "",
        "`分支感知路由 -> 转移段相对打分 -> evidence_fuser v4`",
        "",
        "## 核心结论",
        "",
        f"- verdict: `{summary['verdict']}`",
        f"- transition_capture_rate: `{summary['transition_capture_rate']}`",
        f"- transition_boost_capture_rate: `{summary['transition_boost_capture_rate']}`",
        f"- static_eval_balanced_accuracy: `{summary['static_eval_balanced_accuracy']}`",
        f"- static_prediction_coverage: `{summary['static_prediction_coverage']}`",
        "",
        "## 外部高湿响应补充证据",
        "",
        f"- no_heat_status_counts_v2: `{ext_high_hum_v2_summary.get('no_heat_status_counts', {})}`",
        f"- no_heat_three_state_ready_v2: `{ext_high_hum_v2_summary.get('no_heat_three_state_ready', False)}`",
        f"- short_window_overreacts_v2: `{ext_high_hum_v2_summary.get('short_window_overreacts', False)}`",
        f"- cooling_status_counts_v2: `{ext_high_hum_v2_summary.get('cooling_status_counts', {})}`",
        f"- cooling_validation_ready_v2: `{ext_high_hum_v2_summary.get('cooling_validation_ready', False)}`",
        f"- no_heat_probe_v3_status_counts: `{no_heat_probe_v3_summary.get('status_counts', {})}`",
        f"- no_heat_probe_v3_onset_positive_count: `{no_heat_probe_v3_summary.get('onset_positive_count', 0)}`",
        f"- no_heat_probe_v3_late_persistence_count: `{no_heat_probe_v3_summary.get('late_persistence_count', 0)}`",
        "",
        "### v2 重点样例",
        "",
    ]

    for _, row in no_heat_v2_df.iterrows():
        lines.append(
            f"- {row['file']} | no_heat={row['fused_no_heat_status_v2']} | "
            f"score_2h/6h/12h={_to_float(row['score_2h'])}/{_to_float(row['score_6h'])}/{_to_float(row['score_12h'])} | "
            f"rationale={row['fused_no_heat_rationale_v2']}"
        )

    for _, row in cooling_v2_df.loc[
        cooling_v2_df["fused_cooling_status_v2"].eq("ext_high_hum_cooling_multiscale_long_confirmed_candidate")
    ].iterrows():
        lines.append(
            f"- {row['file']} | cooling={row['fused_cooling_status_v2']} | "
            f"count_2h/6h/12h={int(row['count_2h'])}/{int(row['count_6h'])}/{int(row['count_12h'])} | "
            f"q75_12h={_to_float(row['q75_12h'])} | rationale={row['fused_cooling_rationale_v2']}"
        )

    lines.extend(["", "### no-heat probe v3 样例", ""])
    for _, row in no_heat_probe_v3_df.iterrows():
        lines.append(
            f"- {row['file']} | probe={row['probe_status_v3']} | "
            f"early_resp={_to_float(row['early_respond_in_h_pos_ratio'])} | late_resp={_to_float(row['late_respond_in_h_pos_ratio'])} | "
            f"late_ah_decay_per_headroom={_to_float(row['late_ah_decay_per_headroom'])} | rationale={row['probe_rationale_v3']}"
        )

    lines.extend(
        [
            "",
        "## 建议现场优先展示的样例",
        "",
        ]
    )

    transition_demo = decision_df[decision_df["final_status"] == "transition_boost_alert"].copy()
    for _, row in transition_demo.iterrows():
        boost = transition_boost_df.loc[transition_boost_df["file"] == row["file"]]
        event = event_df.loc[event_df["file"] == row["file"]]
        feature_text = ""
        event_text = ""
        if not boost.empty:
            feature_text = str(boost.iloc[0]["transition_boost_features"])
        if not event.empty:
            e = event.iloc[0]
            event_text = f" | event={e['event_start']} -> {e['event_end']} | peak={e['peak_time']}"
        lines.append(f"- {row['file']} | `transition_boost_alert` | features={feature_text}{event_text}")

    lines.extend(
        [
            "",
            "## 建议现场展示的保守案例",
            "",
        ]
    )
    watch_df = decision_df[decision_df["final_status"].isin(["static_hard_case_watch", "static_abstain_low_signal"])].copy()
    for _, row in watch_df.iterrows():
        lines.append(f"- {row['file']} | `{row['final_status']}` | notes={row['notes']}")

    lines.extend(
        [
            "",
            "## 讲解口径",
            "",
            "- 强证据场景：直接进入 review，不拖成全局分类问题。",
            "- 静态场景：只做辅助证据，不承诺全覆盖。",
            "- 难例和干扰：主动进入 `watch / abstain`，不乱报。",
            "",
        ]
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_cards(
    path: str,
    decision_df: pd.DataFrame,
    segments_df: pd.DataFrame,
    transition_boost_df: pd.DataFrame,
    multiview_df: pd.DataFrame,
    event_df: pd.DataFrame,
    no_heat_v2_df: pd.DataFrame,
    cooling_v2_df: pd.DataFrame,
    no_heat_probe_v3_df: pd.DataFrame,
) -> None:
    lines = ["# 现场演示运行卡片", ""]
    card_df = decision_df[
        decision_df["final_status"].isin(
            [
                "transition_boost_alert",
                "static_dynamic_support_alert",
                "static_dynamic_supported_alert",
                "static_hard_case_watch",
                "static_abstain_low_signal",
            ]
        )
    ].copy()
    for _, row in card_df.iterrows():
        lines.extend(
            build_run_card(
                str(row["file"]),
                decision_df,
                segments_df,
                transition_boost_df,
                multiview_df,
                event_df,
                no_heat_v2_df,
                cooling_v2_df,
                no_heat_probe_v3_df,
            )
        )
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    outputs_df = collect_demo_outputs(args)
    summary = outputs_df["summary_df"].iloc[0].to_dict()
    decision_df = outputs_df["decision_df"]
    segments_df = outputs_df["segments_df"]
    transition_boost_df = outputs_df["transition_boost_df"]
    multiview_df = outputs_df["multiview_df"]
    event_df = outputs_df["event_df"]
    ext_high_hum_v2_summary = outputs_df["ext_high_hum_v2_summary_df"].iloc[0].to_dict()
    no_heat_v2_df = outputs_df["ext_high_hum_no_heat_v2_df"]
    cooling_v2_df = outputs_df["ext_high_hum_cooling_v2_df"]
    no_heat_probe_v3_summary = outputs_df["no_heat_probe_v3_summary_df"].iloc[0].to_dict()
    no_heat_probe_v3_df = outputs_df["no_heat_probe_v3_df"]

    output_paths = {
        "overview_md": os.path.join(args.output_dir, "demo_overview.md"),
        "cards_md": os.path.join(args.output_dir, "demo_run_cards.md"),
        "decision_csv": os.path.join(args.output_dir, "demo_run_decisions.csv"),
        "summary_json": os.path.join(args.output_dir, "demo_summary.json"),
    }

    write_overview(
        output_paths["overview_md"],
        summary,
        decision_df,
        transition_boost_df,
        event_df,
        ext_high_hum_v2_summary,
        no_heat_v2_df,
        cooling_v2_df,
        no_heat_probe_v3_summary,
        no_heat_probe_v3_df,
    )
    write_cards(
        output_paths["cards_md"],
        decision_df,
        segments_df,
        transition_boost_df,
        multiview_df,
        event_df,
        no_heat_v2_df,
        cooling_v2_df,
        no_heat_probe_v3_df,
    )
    decision_df.to_csv(output_paths["decision_csv"], index=False, encoding="utf-8-sig")

    focus_file = _match_focus_file(decision_df, args.focus_file)
    if focus_file:
        focus_path = os.path.join(args.output_dir, "demo_focus_card.md")
        with open(focus_path, "w", encoding="utf-8") as f:
            f.write(
                "\n".join(
                    build_run_card(
                        focus_file,
                        decision_df,
                        segments_df,
                        transition_boost_df,
                        multiview_df,
                        event_df,
                        no_heat_v2_df,
                        cooling_v2_df,
                        no_heat_probe_v3_df,
                    )
                )
            )
        output_paths["focus_md"] = focus_path
        output_paths["focus_file"] = focus_file

    with open(output_paths["summary_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": output_paths}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": output_paths}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
