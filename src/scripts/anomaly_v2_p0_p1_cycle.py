#!/usr/bin/env python3
import argparse
import csv
import json
import os
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional


def http_get_json(url: str, timeout: float = 15.0) -> Dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def now_ms() -> int:
    return int(time.time() * 1000)


def read_csv_rows(path: str) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_json(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def write_kv_csv(path: str, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def run_import_labels(base_url: str, csv_path: str) -> Dict[str, Any]:
    endpoint = f"{base_url.rstrip('/')}/api/anomaly/v2/review/label"
    rows = read_csv_rows(csv_path)

    total = len(rows)
    valid = 0
    skipped = 0
    success = 0
    failed = 0
    failures: List[Dict[str, Any]] = []

    for row in rows:
        event_id = (row.get("event_id") or "").strip()
        label = (row.get("label") or "").strip().lower()
        reviewer = (row.get("reviewer") or "").strip()
        note = (row.get("note") or "").strip()

        if not event_id or label not in {"true", "false", "uncertain"}:
            skipped += 1
            continue

        valid += 1
        payload = {
            "event_id": event_id,
            "label": label,
            "reviewer": reviewer,
            "note": note,
        }
        req = urllib.request.Request(
            endpoint,
            method="POST",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            if resp.status == 200 and int(body.get("code", -1)) == 0:
                success += 1
            else:
                failed += 1
                failures.append({"event_id": event_id, "response": body})
        except Exception as err:
            failed += 1
            failures.append({"event_id": event_id, "error": str(err)})

    return {
        "csv": csv_path,
        "endpoint": endpoint,
        "total_rows": total,
        "valid_rows": valid,
        "skipped_rows": skipped,
        "success": success,
        "failed": failed,
        "failures": failures[:50],
    }


def fetch_eval_and_reports(base_url: str, hours: int) -> Dict[str, Any]:
    end_ts = now_ms()
    start_ts = end_ts - hours * 3600 * 1000

    eval_summary = http_get_json(f"{base_url.rstrip('/')}/api/anomaly/v2/eval/summary")
    labels = http_get_json(f"{base_url.rstrip('/')}/api/anomaly/v2/review/labels?label=all&limit=1000")
    shadow = http_get_json(
        f"{base_url.rstrip('/')}/api/anomaly/v2/shadow/summary?start_ts={start_ts}&end_ts={end_ts}&top_n=10"
    )
    weekly = http_get_json(
        f"{base_url.rstrip('/')}/api/anomaly/v2/report/weekly?start_ts={start_ts}&end_ts={end_ts}&top_n=10"
    )
    runtime = http_get_json(f"{base_url.rstrip('/')}/api/runtime/metrics")

    return {
        "scope": {"start_ts": start_ts, "end_ts": end_ts, "hours": hours},
        "eval_summary": eval_summary.get("data"),
        "labels": labels.get("data"),
        "shadow_summary": shadow.get("data"),
        "weekly_report": weekly.get("data"),
        "runtime_metrics": runtime.get("data"),
    }


def build_kpi_row(snapshot: Dict[str, Any], import_summary: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    eval_data = snapshot.get("eval_summary") or {}
    metrics = eval_data.get("metrics") or {}
    review_stats = eval_data.get("review_stats") or {}
    runtime_metrics = ((snapshot.get("runtime_metrics") or {}).get("metrics") or {})

    row = {
        "generated_at": now_ms(),
        "label_total": review_stats.get("total", 0),
        "label_true": review_stats.get("true", 0),
        "label_false": review_stats.get("false", 0),
        "label_uncertain": review_stats.get("uncertain", 0),
        "precision": metrics.get("precision"),
        "recall": metrics.get("recall"),
        "f1": metrics.get("f1"),
        "tp": (eval_data.get("confusion_like") or {}).get("tp"),
        "fp": (eval_data.get("confusion_like") or {}).get("fp"),
        "fn": (eval_data.get("confusion_like") or {}).get("fn"),
        "anomaly_v2_runs": runtime_metrics.get("anomaly_v2_runs"),
        "anomaly_v2_events": runtime_metrics.get("anomaly_v2_events"),
        "anomaly_v2_shadow_events": runtime_metrics.get("anomaly_v2_shadow_events"),
        "process_total": runtime_metrics.get("process_total"),
        "process_model_error": runtime_metrics.get("process_model_error"),
    }

    if import_summary:
        row.update(
            {
                "import_total_rows": import_summary.get("total_rows"),
                "import_valid_rows": import_summary.get("valid_rows"),
                "import_skipped_rows": import_summary.get("skipped_rows"),
                "import_success": import_summary.get("success"),
                "import_failed": import_summary.get("failed"),
            }
        )
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description="Run P0/P1 cycle: import labels + eval/report snapshot")
    parser.add_argument("--base-url", default="http://127.0.0.1:8001", help="Backend base URL")
    parser.add_argument("--labels-csv", default="", help="Optional labeled CSV path to import")
    parser.add_argument("--hours", type=int, default=24 * 7, help="Report time window in hours")
    parser.add_argument("--out-dir", default="reports/anomaly_v2", help="Output directory")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    import_summary: Optional[Dict[str, Any]] = None
    if args.labels_csv:
        import_summary = run_import_labels(args.base_url, args.labels_csv)
        write_json(os.path.join(args.out_dir, "p1_import_summary_v1.json"), import_summary)

    snapshot = fetch_eval_and_reports(args.base_url, args.hours)
    write_json(os.path.join(args.out_dir, "p1_eval_snapshot_v1.json"), snapshot)

    kpi_row = build_kpi_row(snapshot, import_summary)
    write_kv_csv(
        os.path.join(args.out_dir, "p1_eval_kpi_v1.csv"),
        [kpi_row],
        list(kpi_row.keys()),
    )

    summary = {
        "base_url": args.base_url,
        "labels_csv": args.labels_csv,
        "hours": args.hours,
        "outputs": {
            "import_summary": os.path.join(args.out_dir, "p1_import_summary_v1.json") if args.labels_csv else None,
            "eval_snapshot": os.path.join(args.out_dir, "p1_eval_snapshot_v1.json"),
            "eval_kpi_csv": os.path.join(args.out_dir, "p1_eval_kpi_v1.csv"),
        },
        "kpi": kpi_row,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
