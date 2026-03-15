#!/usr/bin/env python3
"""
Fetch a second-opinion run result by run_id (e.g. after client timed out).

The backend keeps running after the client times out. If the run completed,
you can recover the result without re-spending credits.

Usage:
  # One-shot: fetch only if already complete
  poetry run python scripts/second_opinion_fetch_result.py --run-id 16

  # Wait for completion then fetch (run still IN_PROGRESS)
  poetry run python scripts/second_opinion_fetch_result.py --run-id 16 --wait --timeout 3600
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests


def get_status(base: str, run_id: int) -> dict | None:
    try:
        r = requests.get(f"{base}/api/v1/second-opinion/runs/{run_id}", timeout=15)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        print(f"Failed to get status for run {run_id}: {e}", file=sys.stderr)
        if hasattr(e, "response") and e.response is not None and e.response.status_code == 404:
            print("Run not found. Backend may have been restarted (run state is in DB).", file=sys.stderr)
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch second-opinion result by run_id (recover after timeout).")
    parser.add_argument("--run-id", type=int, required=True, help="Run ID (e.g. 16).")
    parser.add_argument("--base-url", type=str, default="http://localhost:8000", help="Backend base URL.")
    parser.add_argument("--output-dir", type=str, default="second_opinion_runs", help="Where to write result JSON.")
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Poll until run is COMPLETE/ERROR then fetch. Use when status is still IN_PROGRESS.",
    )
    parser.add_argument("--poll-interval", type=float, default=60.0, help="Seconds between polls when using --wait (default 60).")
    parser.add_argument("--timeout", type=float, default=3600.0, help="Max seconds to wait when using --wait (default 3600).")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    run_id = args.run_id

    # 1. Status (optionally wait)
    status_data = get_status(base, run_id)
    if status_data is None:
        return 1

    status = status_data.get("status")
    if status in ("COMPLETE", "ERROR"):
        pass
    elif args.wait:
        print(f"Run {run_id} status: {status}. Polling every {args.poll_interval}s (max {args.timeout}s)...")
        t0 = time.monotonic()
        while True:
            time.sleep(args.poll_interval)
            if time.monotonic() - t0 > args.timeout:
                print("Timeout waiting for run to finish.", file=sys.stderr)
                return 1
            status_data = get_status(base, run_id)
            if status_data is None:
                return 1
            status = status_data.get("status")
            print(f"  status={status}")
            if status in ("COMPLETE", "ERROR"):
                break
    else:
        print(f"Run {run_id} status: {status}")
        print(f"Run has not finished. Re-run with --wait to poll until complete, e.g.:", file=sys.stderr)
        print(f"  poetry run python scripts/second_opinion_fetch_result.py --run-id {run_id} --wait", file=sys.stderr)
        return 1

    print(f"Run {run_id} status: {status}")
    if status_data.get("error_message"):
        print(f"Error message: {status_data['error_message']}")

    # 2. Result
    try:
        r = requests.get(f"{base}/api/v1/second-opinion/runs/{run_id}/result", timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"Failed to fetch result: {e}", file=sys.stderr)
        return 1

    result = r.json()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result_path = out_dir / f"second_opinion_run_result_{run_id}.json"
    result_path.write_text(json.dumps(result, indent=2))
    print(f"Result written to {result_path}")
    if result.get("results", {}).get("decisions"):
        print("Result contains decisions — you can run --run-report with the original draft or use second_opinion_to_substack_outline.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
