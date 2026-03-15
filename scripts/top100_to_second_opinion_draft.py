#!/usr/bin/env python3
"""
Build a second-opinion PortfolioDraft from TOP100.md (The Bench annex).

Parses markdown tables in TOP100.md to extract tickers, then writes a draft JSON
suitable for scripts/dexter_second_opinion_client.py (with --flow-id to load graph).

Usage:
  poetry run python scripts/top100_to_second_opinion_draft.py \\
    --top100 TOP100.md \\
    --out second_opinion_runs/top100_bench_draft.json \\
    [--equal-weight] [--max-tickers 50] [--sleeve bench_top100]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def parse_tickers_from_top100(md_path: Path) -> list[str]:
    """Extract ticker symbols from TOP100.md markdown tables (first column after header)."""
    text = md_path.read_text()
    tickers: list[str] = []
    seen: set[str] = set()
    # Table rows: | TICKER | Company | ... or | Rank | Ticker | ...
    # Skip header and separator lines; ticker is typically 2-5 uppercase letters.
    ticker_re = re.compile(r"^[A-Z]{2,5}$")

    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if not parts:
            continue
        # First column might be "Rank" or "Ticker" or "---" or a ticker.
        first = parts[0].upper()
        if first in ("TICKER", "RANK", "---", "-"):
            continue
        if re.match(r"^-+$", first):
            continue
        # If first column is numeric (rank), use second column as ticker.
        if parts[0].isdigit() and len(parts) >= 2:
            candidate = parts[1].strip().upper()
        else:
            candidate = first
        if not ticker_re.match(candidate):
            continue
        if candidate not in seen:
            seen.add(candidate)
            tickers.append(candidate)

    return tickers


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a second-opinion PortfolioDraft from TOP100.md.",
    )
    parser.add_argument(
        "--top100",
        type=Path,
        default=Path("TOP100.md"),
        help="Path to TOP100.md (default TOP100.md).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("second_opinion_runs/top100_bench_draft.json"),
        help="Output draft JSON path.",
    )
    parser.add_argument(
        "--equal-weight",
        action="store_true",
        help="Assign equal weight per ticker (default: 1%% each).",
    )
    parser.add_argument(
        "--max-tickers",
        type=int,
        default=None,
        help="Cap number of tickers (default: no cap). Useful for quicker runs.",
    )
    parser.add_argument(
        "--sleeve",
        type=str,
        default="bench_top100",
        help="Sleeve name in draft (default bench_top100).",
    )
    parser.add_argument(
        "--params-profile",
        type=str,
        default="tastytrade_factors_on",
        help="Params profile hint (default tastytrade_factors_on).",
    )
    args = parser.parse_args()

    if not args.top100.exists():
        print(f"File not found: {args.top100}")
        return 1

    tickers = parse_tickers_from_top100(args.top100)
    if args.max_tickers is not None:
        tickers = tickers[: args.max_tickers]
    if not tickers:
        print("No tickers parsed from TOP100.md")
        return 1

    n = len(tickers)
    weight = 100.0 / n if args.equal_weight else (100.0 / n)
    assets = [{"symbol": t, "target_weight_pct": round(weight, 2)} for t in tickers]

    draft = {
        "sleeve": args.sleeve,
        "params_profile": args.params_profile,
        "assets": assets,
        "graph_nodes": [],
        "graph_edges": [],
        "margin_requirement": 0.0,
        "portfolio_positions": [],
        "model_name": "gpt-4.1",
        "model_provider": "openai",
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(draft, indent=2))
    print(f"Wrote draft with {n} tickers to {args.out}")
    if n > 20:
        print(
            f"  WARNING: {n} tickers = many LLM calls per run. Second-opinion runs can take 30+ min and "
            "burn significant API credits. For smoke tests use: --max-tickers 10"
        )
    print("Run second-opinion with:")
    print(f"  poetry run python scripts/dexter_second_opinion_client.py \\")
    print(f"    --draft {args.out} \\")
    print(f"    --flow-id 1 \\")
    print(f"    --output-dir second_opinion_runs \\")
    print(f"    --run-report")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
