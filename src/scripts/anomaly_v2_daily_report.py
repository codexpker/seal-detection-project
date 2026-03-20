#!/usr/bin/env python3
import argparse
import csv
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Dict, Optional


def http_get_json(url: str, timeout: float = 10.0) -> Dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def build_url(base: str, path: str, params: Dict[str, Any]) -> str:
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    return f"{base.rstrip('/')}{path}?{qs}" if qs else f"{base.rstrip('/')}{path}"


def safe_get(d: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate anomaly v2 daily report (JSON + CSV)")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Backend base URL")
    parser.add_argument("--hours", type=int, default=24, help="Lookback hours")
    parser.add_argument("--dev-num", default="", help="Optional device number")
    parser.add_argument("--top-n", type=int, default=10, help="Top devices count")
    parser.add_argument("--out-dir", default="reports/anomaly_v2", help="Output directory")
    args = parser.parse_args()

    end_ts = int(time.time() * 1000)
    start_ts = end_ts - args.hours * 3600 * 1000
    ts_label = datetime.now().strftime("%Y%m%d_%H%M%S")

    os.makedirs(args.out_dir, exist_ok=True)

    metrics_url = build_url(args.base_url, "/api/runtime/metrics", {})
    compare_url = build_url(
        args.base_url,
        "/api/diagnosis/replay/compare",
        {"start_ts": start_ts, "end_ts": end_ts, "dev_num": args.dev_num or None},
    )
    summary_url = build_url(
        args.base_url,
        "/api/anomaly/v2/shadow/summary",
        {"start_ts": start_ts, "end_ts": end_ts, "top_n": args.top_n},
    )
    weekly_url = build_url(
        args.base_url,
        "/api/anomaly/v2/report/weekly",
        {"start_ts": start_ts, "end_ts": end_ts, "dev_num": args.dev_num or None, "top_n": args.top_n},
    )
    drift_url = build_url(
        args.base_url,
        "/api/anomaly/v2/drift/summary",
        {"start_ts": start_ts, "end_ts": end_ts, "dev_num": args.dev_num or None},
    )

    metrics = http_get_json(metrics_url)
    compare = http_get_json(compare_url)
    summary = http_get_json(summary_url)
    weekly = http_get_json(weekly_url)
    drift = http_get_json(drift_url)

    combined = {
        "meta": {
            "generated_at": end_ts,
            "generated_at_text": datetime.now().isoformat(timespec="seconds"),
            "base_url": args.base_url,
            "hours": args.hours,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "dev_num": args.dev_num or None,
            "top_n": args.top_n,
        },
        "runtime_metrics": metrics,
        "compare": compare,
        "shadow_summary": summary,
        "weekly_report": weekly,
        "drift_summary": drift,
    }

    json_path = os.path.join(args.out_dir, f"daily_report_{ts_label}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(combined, f, ensure_ascii=False, indent=2)

    # Flat KPI CSV (one row)
    csv_path = os.path.join(args.out_dir, f"daily_report_{ts_label}.csv")
    row = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "hours": args.hours,
        "dev_num": args.dev_num,
        "v1_point_anomaly_count": safe_get(compare, "data", "v1", "point_anomaly_count", default=0),
        "v1_event_count": safe_get(compare, "data", "v1", "event_count", default=0),
        "v2_event_count": safe_get(compare, "data", "v2", "event_count", default=0),
        "v2_shadow_event_count": safe_get(compare, "data", "v2", "shadow_event_count", default=0),
        "event_count_diff_v2_minus_v1": safe_get(compare, "data", "delta", "event_count_diff_v2_minus_v1", default=0),
        "score_count": safe_get(summary, "data", "score_stats", "count", default=0),
        "score_avg_raw": safe_get(summary, "data", "score_stats", "avg_raw", default=""),
        "score_avg_smooth": safe_get(summary, "data", "score_stats", "avg_smooth", default=""),
        "score_max_smooth": safe_get(summary, "data", "score_stats", "max_smooth", default=""),
        "anomaly_v2_runs": safe_get(metrics, "data", "metrics", "anomaly_v2_runs", default=0),
        "anomaly_v2_events": safe_get(metrics, "data", "metrics", "anomaly_v2_events", default=0),
        "anomaly_v2_errors": safe_get(metrics, "data", "metrics", "anomaly_v2_errors", default=0),
        "process_model_error": safe_get(metrics, "data", "metrics", "process_model_error", default=0),
        "drift_flag": safe_get(drift, "data", "drift", "flag", default=False),
        "drift_score": safe_get(drift, "data", "drift", "score", default=0.0),
        "drift_method": safe_get(drift, "data", "drift", "method", default=""),
    }

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)

    print(json.dumps({
        "ok": True,
        "json": json_path,
        "csv": csv_path,
        "kpi": row,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
