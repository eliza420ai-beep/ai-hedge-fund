#!/usr/bin/env python3
"""
Merge multiple batch second-opinion results into a single combined report.

After running top100_batch_runner.sh, this script finds all batch draft + result
pairs and prints a unified agree/disagree report.

Usage:
  poetry run python scripts/top100_merge_batch_results.py --dir second_opinion_runs
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from app.backend.models.second_opinion import summarize_second_opinion


def find_batch_pairs(results_dir: Path) -> list[tuple[Path, Path]]:
    """Find matching (draft, result) pairs from batch runs."""
    drafts = sorted(results_dir.glob("top100_batch_*.json"))
    pairs: list[tuple[Path, Path]] = []

    for draft_path in drafts:
        draft = json.loads(draft_path.read_text())
        sleeve = draft.get("sleeve", "")
        # Find result files and match by checking which ones reference this batch's tickers
        batch_tickers = {a["symbol"] for a in draft.get("assets", [])}
        if not batch_tickers:
            continue

        # Look at all result files and find one whose decisions contain our tickers
        for result_path in sorted(results_dir.glob("second_opinion_run_result_*.json")):
            result = json.loads(result_path.read_text())
            if result.get("status") != "COMPLETE":
                continue
            raw_results = result.get("results") or {}
            decisions = raw_results.get("decisions") if isinstance(raw_results, dict) else {}
            if not isinstance(decisions, dict):
                continue
            decision_tickers = set(decisions.keys())
            overlap = batch_tickers & decision_tickers
            if len(overlap) >= min(3, len(batch_tickers)):
                pairs.append((draft_path, result_path))
                break

    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge batch second-opinion results into one report.")
    parser.add_argument(
        "--dir",
        type=Path,
        default=Path("second_opinion_runs"),
        help="Directory containing batch drafts and results.",
    )
    args = parser.parse_args()

    pairs = find_batch_pairs(args.dir)
    if not pairs:
        print("No batch result pairs found. Run top100_batch_runner.sh first.")
        return 1

    print(f"Found {len(pairs)} completed batch(es)\n")

    all_decisions: dict = {}
    all_assets: dict = {}

    for draft_path, result_path in pairs:
        draft = json.loads(draft_path.read_text())
        result = json.loads(result_path.read_text())

        for a in draft.get("assets", []):
            all_assets[a["symbol"]] = a

        raw_results = result.get("results") or {}
        decisions = raw_results.get("decisions") if isinstance(raw_results, dict) else {}
        if isinstance(decisions, dict):
            all_decisions.update(decisions)

    print(f"Combined: {len(all_decisions)} ticker decisions from {len(all_assets)} draft tickers\n")

    summaries = summarize_second_opinion(all_decisions, sleeve="bench_top100")

    strong_agree = []
    mild_disagree = []
    hard_disagree = []

    for s in summaries:
        asset = all_assets.get(s.symbol, {})
        target_w = asset.get("target_weight_pct", 0.0)
        stance = s.committee_stance.upper()

        if target_w >= 0:
            if stance in ("BUY", "HOLD"):
                strong_agree.append((s, target_w))
            elif stance in ("SELL", "SHORT"):
                if target_w >= 3.0:
                    hard_disagree.append((s, target_w))
                else:
                    mild_disagree.append((s, target_w))
        else:
            if stance in ("SELL", "SHORT"):
                strong_agree.append((s, target_w))
            elif stance in ("BUY", "HOLD"):
                if abs(target_w) >= 3.0:
                    hard_disagree.append((s, target_w))
                else:
                    mild_disagree.append((s, target_w))

    def _print_bucket(title: str, bucket):
        print(f"\n{title}")
        print("-" * len(title))
        if not bucket:
            print("  (none)")
            return
        print(f"  {'symbol':6}  {'weight':>6}  {'stance':6}  {'conf':>4}")
        for s, w in sorted(bucket, key=lambda x: -abs(x[1])):
            conf = f"{s.confidence:.1f}" if s.confidence is not None else "-"
            print(f"  {s.symbol:6}  {w:5.1f}%  {s.committee_stance:6}  {conf:>4}")

    print("=" * 50)
    print("  COMBINED SECOND-OPINION REPORT (all batches)")
    print("=" * 50)

    _print_bucket(f"Strong agree ({len(strong_agree)})", strong_agree)
    _print_bucket(f"Mild disagree ({len(mild_disagree)})", mild_disagree)
    _print_bucket(f"Hard disagree ({len(hard_disagree)})", hard_disagree)

    no_result = set(all_assets.keys()) - set(all_decisions.keys())
    if no_result:
        print(f"\nNo result ({len(no_result)})")
        print("-" * 20)
        for t in sorted(no_result):
            print(f"  {t}")

    print(f"\nTotal: {len(strong_agree)} agree, {len(mild_disagree)} mild disagree, "
          f"{len(hard_disagree)} hard disagree, {len(no_result)} missing")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
