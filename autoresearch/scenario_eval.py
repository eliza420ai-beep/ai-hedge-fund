"""
autoresearch/scenario_eval.py — Parallel scenario backtesting for robustness.

Runs the same params against 5 macro/stress scenarios concurrently and returns
a weighted composite Sharpe. Used with evaluate.py --composite and the autoresearch loop.
"""

from __future__ import annotations

import concurrent.futures
import importlib
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

SCENARIO_CONFIGS = {
    "base": {},
    "rate_shock": {
        "price_shock": {
            "pct": -0.08,
            "start": "2025-09-01",
            "end": "2025-09-21",
        },
    },
    "crash_q4": {
        "price_shock": {
            "pct": -0.20,
            "start": "2025-10-01",
            "end": "2025-11-15",
        },
    },
    "bear_grind": {
        "price_shock": {
            "pct": -0.30,
            "start": "2025-01-01",
            "end": "2025-12-31",
            "gradual": True,
        },
    },
    "rotation": {
        "price_shock": {
            "tickers": ["NVDA", "TSLA"],
            "pct": -0.30,
            "start": "2025-06-01",
            "end": "2025-09-30",
        },
    },
}

SCENARIO_WEIGHTS = {
    "base": 0.40,
    "rate_shock": 0.20,
    "crash_q4": 0.20,
    "bear_grind": 0.10,
    "rotation": 0.10,
}


def _run_one_scenario(
    params_module: str,
    start: str | None,
    end: str | None,
    prices_path: str | Path | None,
    perturbation: dict,
) -> float:
    """Run a single scenario backtest. Top-level for ProcessPoolExecutor pickling."""
    from autoresearch.evaluate import load_params, make_params_override
    from autoresearch.fast_backtest import FastBacktestEngine

    params = load_params(params_module)
    overrides = {}
    if start or end:
        overrides["BACKTEST_START"] = start or params.BACKTEST_START
        overrides["BACKTEST_END"] = end or params.BACKTEST_END
    if overrides:
        params = make_params_override(params, **overrides)
    effective_prices_path = prices_path or getattr(params, "PRICES_PATH", None)
    engine = FastBacktestEngine(
        params,
        tickers_override=None,
        prices_path_override=effective_prices_path,
        price_perturbation=perturbation if perturbation else None,
    )
    metrics = engine.run()
    return float(metrics.get("sharpe_ratio", 0.0))


def run_scenario_suite(
    params_module: str,
    start: str | None = None,
    end: str | None = None,
    prices_path: str | Path | None = None,
    max_workers: int = 5,
) -> dict[str, float]:
    """Run all scenarios concurrently. Returns {scenario_name: sharpe_ratio}."""
    results = {}
    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _run_one_scenario,
                params_module,
                start,
                end,
                str(prices_path) if prices_path else None,
                SCENARIO_CONFIGS[name],
            ): name
            for name in SCENARIO_CONFIGS
        }
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception:
                results[name] = 0.0
    return results


def composite_sharpe(scenario_results: dict[str, float]) -> float:
    """Weighted average of scenario Sharpes."""
    return sum(
        SCENARIO_WEIGHTS.get(k, 0.0) * scenario_results.get(k, 0.0)
        for k in SCENARIO_WEIGHTS
    )
