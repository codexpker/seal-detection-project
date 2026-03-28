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

from src.scripts.new_data_deep_analysis_v1 import load_readme


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a model-tuning action plan from guarded review outputs")
    parser.add_argument("--readme-xlsx", default="/Users/xpker/Downloads/data_readme.xlsx")
    parser.add_argument(
        "--segment-manifest-csv",
        default="reports/new_data_segment_pipeline_v1_run1/segment_pipeline_manifest.csv",
    )
    parser.add_argument(
        "--segment-support-csv",
        default="reports/new_data_segment_static_support_v3_run1/segment_support_output_v3.csv",
    )
    parser.add_argument(
        "--review-template-csv",
        default="reports/new_data_segment_review_label_template_v2_run1/segment_review_labels_template_v2.csv",
    )
    parser.add_argument(
        "--auto-seed-csv",
        default="reports/new_data_segment_auto_seed_labels_v2_run1/segment_review_labels_auto_seed_v2.csv",
    )
    parser.add_argument(
        "--pending-csv",
        default="reports/new_data_segment_feedback_loop_v2_run1/pending_segment_review_reranked_v2.csv",
    )
    parser.add_argument(
        "--output-dir",
        default="reports/new_data_model_tuning_plan_v1_run1",
    )
    return parser.parse_args()


def safe_read_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path) if os.path.exists(path) else pd.DataFrame()


def build_summary(
    readme_df: pd.DataFrame,
    manifest_df: pd.DataFrame,
    support_df: pd.DataFrame,
    review_template_df: pd.DataFrame,
    auto_seed_df: pd.DataFrame,
    pending_df: pd.DataFrame,
) -> Dict[str, Any]:
    mainfield_mask = manifest_df["segment_role"].eq("mainfield_extHigh_intLow_noHeat") if not manifest_df.empty else pd.Series(dtype=bool)
    queue_source = review_template_df if not review_template_df.empty else support_df
    transition_primary_count = int(
        queue_source["support_status_v3"].eq("transition_primary_support").sum()
    ) if not queue_source.empty else 0
    guarded_positive_count = int(
        queue_source["support_status_v3"].eq("static_review_weak_positive_guarded").sum()
    ) if not queue_source.empty else 0
    breathing_count = int(
        queue_source["support_status_v3"].eq("static_watch_breathing_hardguard").sum()
    ) if not queue_source.empty else 0
    confound_count = int(
        queue_source["support_status_v3"].eq("static_watch_confound_hardguard").sum()
    ) if not queue_source.empty else 0
    secondary_transition_count = int(
        queue_source["support_status_v3"].eq("transition_secondary_control").sum()
    ) if not queue_source.empty else 0
    seeded_labels = (
        auto_seed_df.loc[auto_seed_df["review_label"].fillna("").astype(str) != "", "review_label"].value_counts(dropna=False).to_dict()
        if not auto_seed_df.empty else {}
    )
    top_pending = pending_df.head(5).to_dict(orient="records") if not pending_df.empty else []
    return {
        "run_count": int(len(readme_df)),
        "changed_run_count": int(readme_df["change_type"].ne("no_change").sum()) if not readme_df.empty else 0,
        "mainfield_segment_count": int(mainfield_mask.sum()) if not manifest_df.empty else 0,
        "transition_primary_segment_count": transition_primary_count,
        "guarded_positive_segment_count": guarded_positive_count,
        "breathing_watch_segment_count": breathing_count,
        "confound_segment_count": confound_count,
        "transition_secondary_segment_count": secondary_transition_count,
        "auto_seed_label_counts": seeded_labels,
        "top_pending": top_pending,
    }


def section_lines(summary: Dict[str, Any], pending_df: pd.DataFrame) -> List[str]:
    pending_rows: List[str] = []
    for _, row in pending_df.head(5).iterrows():
        pending_rows.append(
            f"- {row['segment_id']} | status={row['support_status_v3']} | "
            f"memory={row.get('memory_role_v2', 'nan')} | anomaly_adv={row.get('anomaly_advantage_v2', 'nan')} | "
            f"guard={row.get('guard_feature_score_v3', 'nan')}"
        )

    return [
        "# New Data Model Tuning Plan v1",
        "",
        "## 当前数据状态",
        "",
        f"- run_count: `{summary['run_count']}`",
        f"- changed_run_count: `{summary['changed_run_count']}`",
        f"- mainfield_segment_count: `{summary['mainfield_segment_count']}`",
        f"- transition_primary_segment_count: `{summary['transition_primary_segment_count']}`",
        f"- guarded_positive_segment_count: `{summary['guarded_positive_segment_count']}`",
        f"- breathing_watch_segment_count: `{summary['breathing_watch_segment_count']}`",
        f"- confound_segment_count: `{summary['confound_segment_count']}`",
        f"- transition_secondary_segment_count: `{summary['transition_secondary_segment_count']}`",
        f"- auto_seed_label_counts: `{summary['auto_seed_label_counts']}`",
        "",
        "## 调优主线",
        "",
        "1. `transition` 继续做主分支，不重启 whole-run 统一分类。",
        "2. `static support` 继续保持 `support / watch / uncertain` 四态，不压回二分类。",
        "3. `tri-memory + guard` 保留为硬约束，先减少误抬，再谈覆盖率。",
        "4. `breathing_watch / confound / transition_secondary_control` 只做 challenge 池，不进主训练正池。",
        "",
        "## 当前最该优化的模型点",
        "",
        "- **Transition 主分支**：只围绕 3 条 `transition_positive` 做事件级提分、提前量、持续性验证。",
        "- **Static 支持层**：只允许在人工确认后把 guarded 段升级到 `supported positive`，尤其是 `181049` 这一类。",
        "- **误报抑制层**：继续用 `160246` 和 `20260321 heat-off` 约束 `breathing/confound`，防止静态支线误抬。",
        "- **控制迁移层**：4 条 `transition_secondary_control` 继续作为边界条件验证，不参与主战场训练。",
        "",
        "## 待复核优先队列",
        "",
        *(pending_rows if pending_rows else ["- 当前没有剩余 pending。"]),
        "",
        "## 具体执行建议",
        "",
        "1. 先用 `review_agenda_v1.csv` 完成 3 条主战场 transition 的人工确认。",
        "2. 单独复核 `181049`，只在确认其跨数据集仍稳定时，才考虑从 `guarded` 升到 `supported`。",
        "3. 保持 `160246 -> breathing_watch`、`20260321 -> confound` 的 hard-negative 角色，不抬进正池。",
        "4. 复核完成后只重跑 `feedback_loop_v2`，再看 `pending` 是否还有 guarded 正段残留。",
        "5. 只有当 guarded 段被连续人工确认后，才考虑调 `guard_score_thresh / weak_support_thresh`。",
        "",
        "## 当前不要做",
        "",
        "- 不要重启 whole-run `GRU/XGBoost`。",
        "- 不要把 `181049` 自动并入 `positive_reference`。",
        "- 不要把 `transition_secondary_control` 并入主战场 transition 正池。",
        "- 不要把 `dew/vpd` 派生特征重新全量堆回统一模型。",
        "",
    ]


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    readme_df = load_readme(args.readme_xlsx)
    manifest_df = safe_read_csv(args.segment_manifest_csv)
    support_df = safe_read_csv(args.segment_support_csv)
    review_template_df = safe_read_csv(args.review_template_csv)
    auto_seed_df = safe_read_csv(args.auto_seed_csv)
    pending_df = safe_read_csv(args.pending_csv)

    summary = build_summary(readme_df, manifest_df, support_df, review_template_df, auto_seed_df, pending_df)
    outputs = {
        "report_md": os.path.join(args.output_dir, "new_data_model_tuning_plan_v1.md"),
        "report_json": os.path.join(args.output_dir, "new_data_model_tuning_plan_v1.json"),
    }

    lines = section_lines(summary, pending_df)
    with open(outputs["report_md"], "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
