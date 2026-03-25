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

from src.scripts.old_data_interference_analysis import analyze_old_data


STRICT_SEALED_CANDIDATE_WATCH = 0.55
WEAK_SEAL_CANDIDATE_WATCH = 0.30
UNSEALED_POSITIVE_CANDIDATE = 0.50
UNSEALED_WATCH_CANDIDATE = 0.30
FAST_RH_LAG_H = 2.0
HIGH_GAIN = 0.90


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Demo-style interference regression entry for old_data")
    parser.add_argument("--output-dir", default="reports/lab_interference_regression_entry_v1")
    parser.add_argument("--window-hours", type=int, default=12)
    parser.add_argument("--step-hours", type=int, default=1)
    parser.add_argument("--focus-file", default="", help="Optional file name or partial token to generate a focused card.")
    return parser.parse_args()


def classify_old_run(row: pd.Series) -> Dict[str, Any]:
    subgroup = str(row.get("subgroup", "unknown"))
    candidate_ratio = float(row.get("candidate_high_info_ratio", 0.0) or 0.0)
    lag_rh = row.get("best_lag_rh_h")
    gain = row.get("gain_ratio_dAH_change")

    final_status = "unknown"
    risk_level = "abstain"
    rationale: List[str] = []

    if subgroup == "sealed_strict":
        if candidate_ratio >= STRICT_SEALED_CANDIDATE_WATCH:
            final_status = "strict_sealed_interference_watch"
            risk_level = "watch"
            rationale.append("strict sealed but candidate_high_info_ratio is high")
        else:
            final_status = "strict_sealed_negative_control_safe"
            risk_level = "safe"
            rationale.append("strict sealed and no persistent high-info routing")
        if pd.notna(lag_rh) and float(lag_rh) <= FAST_RH_LAG_H:
            rationale.append("RH response is relatively fast")
        if pd.notna(gain) and float(gain) >= HIGH_GAIN:
            rationale.append("absolute-humidity gain is relatively high")

    elif subgroup == "sealed_no_screw_grease":
        if candidate_ratio >= WEAK_SEAL_CANDIDATE_WATCH or (pd.notna(lag_rh) and float(lag_rh) <= FAST_RH_LAG_H):
            final_status = "weak_seal_watch"
            risk_level = "watch"
            rationale.append("weak sealing subgroup should not be treated as strict negative control")
        else:
            final_status = "weak_seal_low_signal"
            risk_level = "abstain"
            rationale.append("weak sealing subgroup with limited high-info evidence")

    elif subgroup == "unsealed":
        if candidate_ratio >= UNSEALED_POSITIVE_CANDIDATE and (
            (pd.notna(lag_rh) and float(lag_rh) <= FAST_RH_LAG_H)
            or (pd.notna(gain) and float(gain) >= HIGH_GAIN)
        ):
            final_status = "challenge_positive_like"
            risk_level = "high"
            rationale.append("persistent high-info routing with fast response or high gain")
        elif candidate_ratio >= UNSEALED_WATCH_CANDIDATE:
            final_status = "challenge_watch"
            risk_level = "watch"
            rationale.append("some high-info evidence but not strong enough for positive-like")
        else:
            final_status = "challenge_low_signal"
            risk_level = "abstain"
            rationale.append("unsealed in old_data but current challenge signals are weak")

    else:
        final_status = "unknown_group"
        risk_level = "abstain"
        rationale.append("unknown subgroup")

    return {
        "demo_final_status": final_status,
        "demo_risk_level": risk_level,
        "demo_rationale": " | ".join(rationale),
    }


def build_regression_table(df: pd.DataFrame) -> pd.DataFrame:
    ok_df = df[df["status"] == "ok"].copy()
    rows: List[Dict[str, Any]] = []
    for _, row in ok_df.iterrows():
        rows.append({**row.to_dict(), **classify_old_run(row)})
    return pd.DataFrame(rows).sort_values(["subgroup", "file"]).reset_index(drop=True)


def _match_focus_file(df: pd.DataFrame, focus: str) -> str:
    if not focus:
        return ""
    exact = df.loc[df["file"] == focus, "file"]
    if not exact.empty:
        return str(exact.iloc[0])
    partial = df.loc[df["file"].astype(str).str.contains(focus, case=False, regex=False), "file"]
    if not partial.empty:
        return str(partial.iloc[0])
    return ""


def _fmt(value: Any, digits: int = 3) -> str:
    if pd.isna(value):
        return "-"
    return f"{float(value):.{digits}f}"


def summarize_regression(df: pd.DataFrame) -> Dict[str, Any]:
    strict = df[df["subgroup"] == "sealed_strict"].copy()
    weak = df[df["subgroup"] == "sealed_no_screw_grease"].copy()
    unsealed = df[df["subgroup"] == "unsealed"].copy()

    def ratio(mask: pd.Series, total: int) -> float:
        return float(mask.sum() / total) if total else 0.0

    return {
        "total_ok_runs": int(len(df)),
        "subgroup_counts": df["subgroup"].value_counts().to_dict(),
        "final_status_counts": df["demo_final_status"].value_counts().to_dict(),
        "strict_safe_rate": ratio(strict["demo_final_status"] == "strict_sealed_negative_control_safe", len(strict)),
        "strict_watch_rate": ratio(strict["demo_final_status"] == "strict_sealed_interference_watch", len(strict)),
        "strict_positive_like_count": int((strict["demo_final_status"] == "challenge_positive_like").sum()),
        "weak_watch_rate": ratio(weak["demo_final_status"] == "weak_seal_watch", len(weak)),
        "unsealed_positive_like_rate": ratio(unsealed["demo_final_status"] == "challenge_positive_like", len(unsealed)),
        "unsealed_watch_or_high_rate": ratio(
            unsealed["demo_final_status"].isin(["challenge_positive_like", "challenge_watch"]),
            len(unsealed),
        ),
    }


def build_run_card(row: pd.Series) -> List[str]:
    lines = [
        f"## {row['file']}",
        "",
        f"- subgroup: `{row['subgroup']}`",
        f"- demo_final_status: `{row['demo_final_status']}`",
        f"- demo_risk_level: `{row['demo_risk_level']}`",
        f"- rationale: `{row['demo_rationale']}`",
        "",
        "### 关键特征",
        "",
        f"- candidate_high_info_ratio: `{_fmt(row['candidate_high_info_ratio'])}`",
        f"- best_lag_rh_h: `{_fmt(row['best_lag_rh_h'])}`",
        f"- best_lag_h: `{_fmt(row['best_lag_h'])}`",
        f"- gain_ratio_dAH_change: `{_fmt(row['gain_ratio_dAH_change'])}`",
        f"- max_corr_outRH_inRH_change: `{_fmt(row['max_corr_outRH_inRH_change'])}`",
        f"- heat_related_ratio: `{_fmt(row['heat_related_ratio'])}`",
        "",
    ]
    return lines


def write_overview(path: str, summary: Dict[str, Any], df: pd.DataFrame) -> None:
    lines = [
        "# 历史旧数据干扰回归测试总览",
        "",
        "## 这份材料的定位",
        "",
        "- 这是 `old_data` 的挑战集回归分诊，不是主训练集结果，也不是主链路分类精度报告。",
        "- 目标是证明系统在强干扰历史数据面前，能够保持保守，不把严格密封样本直接当成泄漏告警。",
        "",
        "## 核心统计",
        "",
        f"- total_ok_runs: `{summary['total_ok_runs']}`",
        f"- subgroup_counts: `{summary['subgroup_counts']}`",
        f"- final_status_counts: `{summary['final_status_counts']}`",
        f"- strict_safe_rate: `{summary['strict_safe_rate']}`",
        f"- strict_watch_rate: `{summary['strict_watch_rate']}`",
        f"- strict_positive_like_count: `{summary['strict_positive_like_count']}`",
        f"- weak_watch_rate: `{summary['weak_watch_rate']}`",
        f"- unsealed_positive_like_rate: `{summary['unsealed_positive_like_rate']}`",
        f"- unsealed_watch_or_high_rate: `{summary['unsealed_watch_or_high_rate']}`",
        "",
        "## 现场建议讲法",
        "",
        "- `strict sealed` 只能落到 `safe` 或 `watch`，不能被直接讲成泄漏。",
        "- `sealed_no_screw_grease` 单独作为结构弱化挑战子集，默认只做 `watch / abstain`。",
        "- `unsealed` 中若同时出现高 candidate 比例和较快动态响应，才进入 `positive-like`。",
        "",
        "## 建议现场展示的样例",
        "",
    ]

    def append_first(mask: pd.Series, label: str) -> None:
        subset = df[mask].copy()
        if subset.empty:
            return
        row = subset.sort_values(["candidate_high_info_ratio", "gain_ratio_dAH_change"], ascending=[False, False]).iloc[0]
        lines.append(
            f"- {label}: {row['file']} | status={row['demo_final_status']} | "
            f"candidate_high_info_ratio={_fmt(row['candidate_high_info_ratio'])} | "
            f"best_lag_rh_h={_fmt(row['best_lag_rh_h'])}"
        )

    append_first(df["demo_final_status"] == "strict_sealed_interference_watch", "严格密封干扰样例")
    append_first(df["demo_final_status"] == "strict_sealed_negative_control_safe", "严格密封保守样例")
    append_first(df["demo_final_status"] == "weak_seal_watch", "结构弱化 watch 样例")
    append_first(df["demo_final_status"] == "challenge_positive_like", "非密封 challenge-positive 样例")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_cards(path: str, df: pd.DataFrame) -> None:
    lines = ["# 历史旧数据干扰回归测试卡片", ""]
    selections: List[pd.Series] = []

    for status in [
        "strict_sealed_interference_watch",
        "strict_sealed_negative_control_safe",
        "weak_seal_watch",
        "challenge_positive_like",
    ]:
        subset = df[df["demo_final_status"] == status].copy()
        if subset.empty:
            continue
        row = subset.sort_values(["candidate_high_info_ratio", "gain_ratio_dAH_change"], ascending=[False, False]).iloc[0]
        selections.append(row)

    seen = set()
    for row in selections:
        file_name = str(row["file"])
        if file_name in seen:
            continue
        seen.add(file_name)
        lines.extend(build_run_card(row))

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    raw_df = analyze_old_data(window_hours=args.window_hours, step_hours=args.step_hours)
    regression_df = build_regression_table(raw_df)
    summary = summarize_regression(regression_df)

    outputs = {
        "overview_md": os.path.join(args.output_dir, "interference_overview.md"),
        "cards_md": os.path.join(args.output_dir, "interference_run_cards.md"),
        "regression_csv": os.path.join(args.output_dir, "interference_regression_runs.csv"),
        "summary_json": os.path.join(args.output_dir, "interference_summary.json"),
    }

    write_overview(outputs["overview_md"], summary, regression_df)
    write_cards(outputs["cards_md"], regression_df)
    regression_df.to_csv(outputs["regression_csv"], index=False, encoding="utf-8-sig")

    focus_file = _match_focus_file(regression_df, args.focus_file)
    if focus_file:
        focus_path = os.path.join(args.output_dir, "interference_focus_card.md")
        row = regression_df.loc[regression_df["file"] == focus_file].iloc[0]
        with open(focus_path, "w", encoding="utf-8") as f:
            f.write("\n".join(build_run_card(row)))
        outputs["focus_md"] = focus_path
        outputs["focus_file"] = focus_file

    with open(outputs["summary_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
