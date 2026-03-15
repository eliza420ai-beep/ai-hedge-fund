"""
autoresearch/regime_swarm.py — Multi-signal regime committee (swarm).

Runs 5 cache-derived regime agents in parallel and returns a weighted consensus.
Uses L1 summaries when available (~2KB) and falls back to full cache (L2) when missing.
"""

from __future__ import annotations

import concurrent.futures
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

CACHE_DIR = Path(__file__).resolve().parent / "cache"
THRESHOLD = 0.02


def _price_momentum_regime() -> dict[str, Any] | None:
    """Agent: 20d price momentum from L1 (SPY return_20d) or L2 cache."""
    try:
        from autoresearch.cache_summaries import get_l1
        l1 = get_l1("prices", "benchmark")
        if l1:
            pt = l1.get("per_ticker") or {}
            spy = pt.get("SPY") or pt.get("spy")
            if spy is not None and "return_20d" in spy:
                ret = float(spy["return_20d"])
                if ret > THRESHOLD:
                    return {"regime": "bull", "confidence": 0.8}
                if ret < -THRESHOLD:
                    return {"regime": "bear", "confidence": 0.8}
                return {"regime": "sideways", "confidence": 0.7}
        from autoresearch.regime import get_regime_from_cache
        regime = get_regime_from_cache("SPY", lookback=20)
        return {"regime": regime, "confidence": 0.8}
    except Exception:
        return None


def _realized_vol_regime() -> dict[str, Any] | None:
    """Agent: realized vol from L1 (vol_ratio_20d) or L2 prices cache."""
    try:
        from autoresearch.cache_summaries import get_l1
        l1 = get_l1("prices", "benchmark")
        if l1:
            pt = l1.get("per_ticker") or {}
            spy = pt.get("SPY") or pt.get("spy")
            if spy is not None and "vol_ratio_20d" in spy:
                ratio = float(spy["vol_ratio_20d"])
                if ratio >= 1.5:
                    return {"regime": "bear", "confidence": min(0.9, 0.5 + (ratio - 1.5) / 2)}
                if ratio <= 0.7:
                    return {"regime": "bull", "confidence": 0.7}
                return {"regime": "sideways", "confidence": 0.6}
        import pandas as pd
        path = CACHE_DIR / "prices_benchmark.json"
        if not path.exists():
            path = CACHE_DIR / "prices.json"
        if not path.exists():
            return None
        with open(path) as f:
            raw = json.load(f)
        series = raw.get("SPY") or raw.get("spy")
        if not series:
            return None
        df = pd.DataFrame(series)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        if len(df) < 25:
            return None
        returns = df["close"].pct_change().dropna()
        vol_20d = returns.rolling(20).std() * (252 ** 0.5)
        if vol_20d.empty or vol_20d.iloc[-1] <= 0:
            return None
        current = float(vol_20d.iloc[-1])
        mean_vol = float(vol_20d.mean())
        if mean_vol <= 0:
            return None
        ratio = current / mean_vol
        if ratio >= 1.5:
            return {"regime": "bear", "confidence": min(0.9, 0.5 + (ratio - 1.5) / 2)}
        if ratio <= 0.7:
            return {"regime": "bull", "confidence": 0.7}
        return {"regime": "sideways", "confidence": 0.6}
    except Exception:
        return None


def _macro_rates_regime() -> dict[str, Any] | None:
    """Agent: Fed rate direction from L1 macro_rates or L2."""
    try:
        from autoresearch.cache_summaries import get_l1
        l1 = get_l1("macro_rates", None)
        if l1 and "regime" in l1:
            regime_map = {"tightening": "bear", "easing": "bull", "stable": "sideways"}
            regime = regime_map.get(l1["regime"], "sideways")
            return {"regime": regime, "confidence": 0.75}
        from autoresearch.factors import _load_macro_rates, get_macro_snapshot
        rates = _load_macro_rates(CACHE_DIR)
        if not rates:
            return None
        latest = rates[-1]
        date_str = latest.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        snapshot = get_macro_snapshot(date_str, rates, lookback_months=6)
        if not snapshot:
            return None
        regime_map = {"tightening": "bear", "easing": "bull", "stable": "sideways"}
        regime = regime_map.get(snapshot.get("regime", "stable"), "sideways")
        return {"regime": regime, "confidence": 0.75}
    except Exception:
        return None


def _insider_flow_regime(tickers: list[str] | None) -> dict[str, Any] | None:
    """Agent: net insider flow from L1 aggregate or L2 _load_insider."""
    try:
        from autoresearch.cache_summaries import get_l1
        l1 = get_l1("insider_trades", "fundamentals")
        if l1:
            agg = l1.get("aggregate") or {}
            net_90 = agg.get("net_shares_90d", 0) or 0
            try:
                net_90 = float(net_90)
            except (TypeError, ValueError):
                net_90 = 0.0
            if net_90 < -50_000:
                return {"regime": "bear", "confidence": 0.7}
            if net_90 > 50_000:
                return {"regime": "bull", "confidence": 0.65}
            return {"regime": "sideways", "confidence": 0.6}
        from autoresearch.factors import _load_insider
        data = _load_insider("fundamentals")
        if not data:
            return None
        tickers_to_use = tickers or list(data.keys())[:10]
        as_of = datetime.now(timezone.utc)
        cutoff = as_of - timedelta(days=90)
        net_total = 0.0
        count = 0
        for ticker in tickers_to_use:
            trades = data.get(ticker, [])
            for t in trades:
                filing = t.get("filing_date")
                if not filing:
                    continue
                try:
                    fd = datetime.fromisoformat(filing.replace("Z", ""))
                except Exception:
                    continue
                if fd.date() < cutoff.date() or fd.date() > as_of.date():
                    continue
                shares = t.get("transaction_shares")
                if shares is not None:
                    try:
                        net_total += float(shares)
                        count += 1
                    except (TypeError, ValueError):
                        pass
        if count == 0:
            return None
        if net_total < -50_000:
            return {"regime": "bear", "confidence": 0.7}
        if net_total > 50_000:
            return {"regime": "bull", "confidence": 0.65}
        return {"regime": "sideways", "confidence": 0.6}
    except Exception:
        return None


def _news_sentiment_regime(tickers: list[str] | None) -> dict[str, Any] | None:
    """Agent: average news sentiment from L1 per_ticker or L2 compute_news_sentiment_snapshot."""
    try:
        from autoresearch.cache_summaries import get_l1
        l1 = get_l1("news", "fundamentals")
        if l1:
            pt = l1.get("per_ticker") or {}
            tickers_to_use = tickers or ["SPY", "AAPL", "NVDA", "MSFT", "GOOGL"]
            values = []
            for t in tickers_to_use:
                row = pt.get(t)
                if row and "avg_sentiment_30d" in row:
                    values.append(float(row["avg_sentiment_30d"]))
            if values:
                avg = sum(values) / len(values)
                if avg > 0.15:
                    return {"regime": "bull", "confidence": min(0.85, 0.5 + abs(avg))}
                if avg < -0.15:
                    return {"regime": "bear", "confidence": min(0.85, 0.5 + abs(avg))}
                return {"regime": "sideways", "confidence": 0.6}
        from autoresearch.factors import compute_news_sentiment_snapshot
        tickers_to_use = tickers or ["SPY", "AAPL", "NVDA", "MSFT", "GOOGL"]
        as_of = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        values = []
        for t in tickers_to_use:
            v = compute_news_sentiment_snapshot(t, as_of, "fundamentals", lookback_days=30)
            if v is not None:
                values.append(v)
        if not values:
            return None
        avg = sum(values) / len(values)
        if avg > 0.15:
            return {"regime": "bull", "confidence": min(0.85, 0.5 + abs(avg))}
        if avg < -0.15:
            return {"regime": "bear", "confidence": min(0.85, 0.5 + abs(avg))}
        return {"regime": "sideways", "confidence": 0.6}
    except Exception:
        return None


SWARM_AGENTS = [
    ("price_20d", _price_momentum_regime, 0.30),
    ("realized_vol", _realized_vol_regime, 0.20),
    ("macro_rates", _macro_rates_regime, 0.20),
    ("insider_flow", _insider_flow_regime, 0.15),
    ("news_sent", _news_sentiment_regime, 0.15),
]


def swarm_regime(tickers: list[str] | None = None) -> dict[str, Any]:
    """
    Run all regime agents in parallel; return weighted consensus.
    Returns {"regime": "bull|bear|sideways", "confidence": 0.0-1.0, "votes": {agent: result}}.
    Missing cache => agent abstains (weight redistributed).
    """
    votes: dict[str, dict[str, Any] | None] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures = {}
        for name, fn, _ in SWARM_AGENTS:
            if name in ("insider_flow", "news_sent"):
                futures[pool.submit(fn, tickers)] = name
            else:
                futures[pool.submit(fn)] = name
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            try:
                votes[name] = future.result()
            except Exception:
                votes[name] = None

    weights = {name: w for name, _, w in SWARM_AGENTS}
    total_weight = sum(w for name, w in weights.items() if votes.get(name))
    if total_weight <= 0:
        return {"regime": "sideways", "confidence": 0.0, "votes": votes}

    scores = {"bull": 0.0, "bear": 0.0, "sideways": 0.0}
    for name, w in weights.items():
        v = votes.get(name)
        if not v or "regime" not in v:
            continue
        regime = v.get("regime", "sideways")
        conf = float(v.get("confidence", 0.5))
        if regime in scores:
            scores[regime] += w * conf
    total_score = sum(scores.values())
    if total_score <= 0:
        return {"regime": "sideways", "confidence": 0.0, "votes": votes}
    winner = max(scores, key=scores.get)
    confidence = scores[winner] / total_weight
    return {"regime": winner, "confidence": min(1.0, confidence), "votes": votes}
