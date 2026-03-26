#!/usr/bin/env python3
import argparse
import json
import os
from typing import Any, Dict

import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate review label CSV template from review_output")
    parser.add_argument(
        "--review-output-csv",
        default="reports/lab_unified_data_interface_v1_run4/review_output.csv",
        help="Input review_output CSV",
    )
    parser.add_argument(
        "--output-dir",
        default="reports/lab_review_label_template_v1_run1",
        help="Output directory",
    )
    parser.add_argument(
        "--include-reviewed",
        action="store_true",
        help="Include reviewed rows as well; default only exports pending rows",
    )
    return parser.parse_args()


def build_template(review_df: pd.DataFrame, include_reviewed: bool) -> pd.DataFrame:
    out = review_df.copy()
    if not include_reviewed and "review_status" in out.columns:
        out = out[out["review_status"].eq("pending")].copy()

    out["review_label"] = ""
    out["reviewer"] = ""
    out["review_note"] = ""
    out["label_options"] = "healthy|anomaly|uncertain"
    out["recommended_focus"] = out["review_priority"].map(
        {
            "P0_transition": "先确认是否为真实转移/异常",
            "P1_static_alert": "先确认是否可判为异常/不密封",
            "P2_hard_case_watch": "先确认是否属于密封难例/呼吸效应",
            "P2_static_support": "先确认是否存在辅助异常证据",
        }
    ).fillna("按运行级证据人工复核")

    cols = [
        "run_id",
        "review_label",
        "reviewer",
        "review_note",
        "file",
        "condition_family_manual",
        "heat_state_manual",
        "ext_humidity_regime_manual",
        "final_status",
        "risk_level",
        "primary_evidence",
        "review_priority",
        "label_options",
        "recommended_focus",
        "probe_status_v3",
        "probe_rationale_v3",
        "no_heat_probe_v3_context",
        "fused_no_heat_status_v2",
        "fused_no_heat_rationale_v2",
        "fused_cooling_status_v2",
        "fused_cooling_rationale_v2",
        "notes",
    ]
    keep = [c for c in cols if c in out.columns]
    return out[keep].sort_values(["review_priority", "run_id"]).reset_index(drop=True)


def build_summary(template_df: pd.DataFrame, include_reviewed: bool) -> Dict[str, Any]:
    return {
        "row_count": int(len(template_df)),
        "include_reviewed": bool(include_reviewed),
        "review_priority_counts": template_df["review_priority"].value_counts(dropna=False).to_dict()
        if "review_priority" in template_df.columns and not template_df.empty
        else {},
    }


def write_markdown(path: str, summary: Dict[str, Any], outputs: Dict[str, str]) -> None:
    lines = [
        "# Review Label Template v1",
        "",
        "- 目的：把当前 `review_output` 直接压成可填写的真实复核标签模板，字段与 `lab_health_bank_feedback_loop_v1.py` 完全兼容。",
        "",
        f"- row_count：`{summary['row_count']}`",
        f"- include_reviewed：`{summary['include_reviewed']}`",
        f"- review_priority_counts：`{summary['review_priority_counts']}`",
        "",
        "## 输出文件",
        "",
        f"- template_csv: `{outputs['template_csv']}`",
        "",
        "## 填写要求",
        "",
        "- 真正会被回灌脚本读取的只有四列：`run_id, review_label, reviewer, review_note`。",
        "- 其他列都是辅助上下文，保留即可，不影响脚本读取。",
        "- 推荐直接使用标准标签：`healthy`、`anomaly`、`uncertain`。",
        "",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    review_df = pd.read_csv(args.review_output_csv)
    template_df = build_template(review_df, include_reviewed=args.include_reviewed)
    summary = build_summary(template_df, include_reviewed=args.include_reviewed)

    outputs = {
        "template_csv": os.path.join(args.output_dir, "review_labels_template.csv"),
        "report_md": os.path.join(args.output_dir, "review_label_template_report.md"),
        "report_json": os.path.join(args.output_dir, "review_label_template_report.json"),
    }
    template_df.to_csv(outputs["template_csv"], index=False, encoding="utf-8-sig")
    write_markdown(outputs["report_md"], summary, outputs)
    with open(outputs["report_json"], "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "outputs": outputs}, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({"summary": summary, "outputs": outputs}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
