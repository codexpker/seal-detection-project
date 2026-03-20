#!/usr/bin/env python3
import argparse
import csv
import json
import urllib.request
from typing import Dict, Any, Tuple


def post_json(url: str, payload: Dict[str, Any], timeout: float = 10.0) -> Tuple[int, Dict[str, Any]]:
    req = urllib.request.Request(
        url,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = resp.getcode()
        body = resp.read().decode("utf-8")
    return status, json.loads(body)


def normalize_label(label: str) -> str:
    v = (label or "").strip().lower()
    if v in {"true", "false", "uncertain"}:
        return v
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Import anomaly v2 review labels from CSV")
    parser.add_argument("--csv", required=True, help="CSV file path with event_id,label,reviewer,note")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Backend base URL")
    parser.add_argument("--dry-run", action="store_true", help="Validate rows without sending requests")
    args = parser.parse_args()

    endpoint = f"{args.base_url.rstrip('/')}/api/anomaly/v2/review/label"

    total = 0
    valid = 0
    skipped = 0
    success = 0
    failed = 0
    fail_items = []

    with open(args.csv, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"event_id", "label"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"CSV missing required columns: {sorted(missing)}")

        for row in reader:
            total += 1
            event_id = (row.get("event_id") or "").strip()
            label = normalize_label(row.get("label") or "")
            reviewer = (row.get("reviewer") or "").strip()
            note = (row.get("note") or "").strip()

            if not event_id or not label:
                skipped += 1
                continue

            valid += 1
            payload = {
                "event_id": event_id,
                "label": label,
                "reviewer": reviewer,
                "note": note,
            }

            if args.dry_run:
                continue

            try:
                status, resp = post_json(endpoint, payload)
                if status == 200 and int(resp.get("code", -1)) == 0:
                    success += 1
                else:
                    failed += 1
                    fail_items.append({"event_id": event_id, "response": resp})
            except Exception as err:
                failed += 1
                fail_items.append({"event_id": event_id, "error": str(err)})

    summary = {
        "csv": args.csv,
        "endpoint": endpoint,
        "dry_run": args.dry_run,
        "total_rows": total,
        "valid_rows": valid,
        "skipped_rows": skipped,
        "success": success,
        "failed": failed,
        "fail_items": fail_items[:20],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
