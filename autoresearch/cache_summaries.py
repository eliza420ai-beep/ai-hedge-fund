"""
autoresearch/cache_summaries.py — L1 summaries for tiered context loading (OpenViking-style).

Pre-computes lightweight _l1.json companion files for prices, insider_trades, news, macro_rates
so regime_swarm and other consumers can read ~2KB instead of loading full cache files (~25MB).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

CACHE_DIR = Path(__file__).resolve().parent / "cache"

_SENTIMENT_MAP = {
    "positive": 1.0,
    "negative": -1.0,
    "neutral": 0.0,
    "bearish": -0.7,
    "bullish": 0.7,
}


def _sentiment_to_number(sentiment: Any) -> float | None:
    if sentiment is None:
        return None
    if isinstance(sentiment, (int, float)):
        return max(-1.0, min(1.0, float(sentiment)))
    s = str(sentiment).strip().lower()
    if s in _SENTIMENT_MAP:
        return _SENTIMENT_MAP[s]
    for key, val in _SENTIMENT_MAP.items():
        if key in s:
            return val
    return None


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    s = str(s).replace("Z", "").split(".")[0]
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def build_l1_prices(path: Path) -> dict[str, Any]:
    """Build L1 summary from a prices_*.json file: per-ticker latest_close, return_20d, vol_20d_ann, return_60d."""
    with open(path) as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        return {"as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "per_ticker": {}}

    as_of = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    per_ticker: dict[str, dict[str, float]] = {}

    for ticker, rows in raw.items():
        if not isinstance(rows, list) or not rows:
            continue
        try:
            import pandas as pd
            df = pd.DataFrame(rows)
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").sort_index()
            if len(df) < 20:
                continue
            close = df["close"]
            ret_20 = (close.iloc[-1] / close.iloc[-20] - 1.0) if len(close) >= 20 else 0.0
            ret_60 = (close.iloc[-1] / close.iloc[-60] - 1.0) if len(close) >= 60 else 0.0
            returns = close.pct_change().dropna()
            vol_20d = returns.rolling(20).std() * (252 ** 0.5)
            vol_20 = float(vol_20d.iloc[-1]) if len(vol_20d) and vol_20d.iloc[-1] > 0 else 0.0
            mean_vol_20 = float(vol_20d.mean()) if len(vol_20d) and vol_20d.mean() > 0 else 0.0
            vol_ratio_20d = (vol_20 / mean_vol_20) if mean_vol_20 else 0.0
            per_ticker[ticker] = {
                "latest_close": float(close.iloc[-1]),
                "return_20d": round(ret_20, 6),
                "return_60d": round(ret_60, 6),
                "vol_20d_ann": round(vol_20, 6),
                "vol_ratio_20d": round(vol_ratio_20d, 4),
            }
        except Exception:
            continue

    return {"as_of": as_of, "per_ticker": per_ticker}


def build_l1_insider(path: Path) -> dict[str, Any]:
    """Build L1 summary from insider_trades_*.json: per-ticker net_shares_90d/30d, trade_count_90d, aggregate."""
    with open(path) as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        return {"as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "per_ticker": {}, "aggregate": {"net_shares_90d": 0, "net_shares_30d": 0}}

    as_of_dt = datetime.now(timezone.utc)
    as_of = as_of_dt.strftime("%Y-%m-%d")
    cutoff_90 = as_of_dt - timedelta(days=90)
    cutoff_30 = as_of_dt - timedelta(days=30)
    per_ticker: dict[str, dict[str, float | int]] = {}
    agg_90 = 0.0
    agg_30 = 0.0

    for ticker, trades in raw.items():
        if not isinstance(trades, list):
            continue
        net_90 = 0.0
        net_30 = 0.0
        count_90 = 0
        for t in trades:
            fd = _parse_date(t.get("filing_date"))
            if fd is None:
                continue
            if fd.date() < cutoff_90.date() or fd.date() > as_of_dt.date():
                continue
            count_90 += 1
            shares = t.get("transaction_shares")
            if shares is not None:
                try:
                    s = float(shares)
                    net_90 += s
                    if fd.date() >= cutoff_30.date():
                        net_30 += s
                except (TypeError, ValueError):
                    pass
        per_ticker[ticker] = {"net_shares_90d": round(net_90, 0), "net_shares_30d": round(net_30, 0), "trade_count_90d": count_90}
        agg_90 += net_90
        agg_30 += net_30

    return {
        "as_of": as_of,
        "per_ticker": per_ticker,
        "aggregate": {"net_shares_90d": round(agg_90, 0), "net_shares_30d": round(agg_30, 0)},
    }


def build_l1_news(path: Path) -> dict[str, Any]:
    """Build L1 summary from news_*.json: per-ticker avg_sentiment_30d, article_count_30d."""
    with open(path) as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        return {"as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "per_ticker": {}}

    as_of_dt = datetime.now(timezone.utc)
    as_of = as_of_dt.strftime("%Y-%m-%d")
    cutoff = as_of_dt - timedelta(days=30)
    per_ticker: dict[str, dict[str, float | int]] = {}

    for ticker, items in raw.items():
        if not isinstance(items, list):
            continue
        values: list[float] = []
        for item in items:
            d = _parse_date(item.get("date"))
            if d is None or d.date() <= cutoff.date() or d.date() > as_of_dt.date():
                continue
            v = _sentiment_to_number(item.get("sentiment"))
            if v is not None:
                values.append(v)
        if values:
            per_ticker[ticker] = {
                "avg_sentiment_30d": round(sum(values) / len(values), 4),
                "article_count_30d": len(values),
            }

    return {"as_of": as_of, "per_ticker": per_ticker}


def build_l1_macro(path: Path) -> dict[str, Any]:
    """Build L1 summary from macro_rates.json: latest_rate, delta_6mo, regime (easing/tightening/stable)."""
    with open(path) as f:
        raw = json.load(f)
    rates = raw.get("interest_rates", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
    if not rates:
        return {"as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "latest_rate": 0.0, "delta_6mo": 0.0, "regime": "stable"}

    bank = "FED"
    filtered = [r for r in rates if isinstance(r, dict) and r.get("bank") == bank and r.get("date") and r.get("rate") is not None]
    filtered.sort(key=lambda x: x["date"])
    if not filtered:
        return {"as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "latest_rate": 0.0, "delta_6mo": 0.0, "regime": "stable"}

    latest = float(filtered[-1]["rate"])
    idx_6mo = max(0, len(filtered) - 6)
    prior = float(filtered[idx_6mo].get("rate", latest))
    delta_6mo = latest - prior
    if delta_6mo > 0:
        regime = "tightening"
    elif delta_6mo < 0:
        regime = "easing"
    else:
        regime = "stable"
    as_of = filtered[-1].get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    return {
        "as_of": as_of,
        "latest_rate": round(latest, 4),
        "delta_6mo": round(delta_6mo, 4),
        "regime": regime,
    }


def _l1_path(source_path: Path) -> Path:
    return source_path.parent / (source_path.stem + "_l1.json")


def _build_l1_for_path(path: Path) -> bool:
    """Build L1 for a single source file; return True if written."""
    name = path.name
    if "prices" in name and name.endswith(".json") and "_l1" not in name:
        out = build_l1_prices(path)
    elif "insider_trades" in name:
        out = build_l1_insider(path)
    elif "news" in name and "meta" not in name:
        out = build_l1_news(path)
    elif "macro_rates" in name:
        out = build_l1_macro(path)
    else:
        return False
    l1_path = _l1_path(path)
    with open(l1_path, "w") as f:
        json.dump(out, f, indent=2)
    return True


def rebuild_summaries(data_type: str | None = None) -> list[Path]:
    """
    Recompute L1 summaries for cache files. If data_type is None, do all four types.
    Returns list of written L1 paths.
    """
    written: list[Path] = []
    if not CACHE_DIR.exists():
        return written

    builders: list[tuple[str, Any]] = [
        ("prices", build_l1_prices),
        ("insider_trades", build_l1_insider),
        ("news", build_l1_news),
        ("macro_rates", build_l1_macro),
    ]
    if data_type:
        builders = [(t, fn) for t, fn in builders if t == data_type]

    for pattern, build_fn in builders:
        if pattern == "macro_rates":
            path = CACHE_DIR / "macro_rates.json"
            if path.exists():
                try:
                    out = build_fn(path)
                    l1_path = _l1_path(path)
                    with open(l1_path, "w") as f:
                        json.dump(out, f, indent=2)
                    written.append(l1_path)
                except Exception:
                    pass
            continue
        for path in sorted(CACHE_DIR.glob(f"{pattern}*.json")):
            if "_l1" in path.name or path.name == "macro_rates.json":
                continue
            try:
                out = build_fn(path)
                l1_path = _l1_path(path)
                with open(l1_path, "w") as f:
                    json.dump(out, f, indent=2)
                written.append(l1_path)
            except Exception:
                continue

    return written


def get_l1(data_type: str, prefix: str | None = None) -> dict[str, Any] | None:
    """
    Load L1 summary for the given data type and optional prefix (e.g. "benchmark", "fundamentals").
    If L1 is missing or older than source, rebuilds it first. Returns None if no source file exists.
    """
    try:
        from autoresearch.cache_manifest import resolve
    except ImportError:
        resolve = None

    if data_type == "macro_rates":
        path = CACHE_DIR / "macro_rates.json"
    elif resolve:
        path = resolve(data_type, prefix or "")
    else:
        if data_type == "prices":
            path = CACHE_DIR / "prices_benchmark.json" if prefix == "benchmark" else CACHE_DIR / "prices.json"
        elif data_type == "insider_trades":
            path = CACHE_DIR / f"insider_trades_{prefix or 'fundamentals'}.json"
        elif data_type == "news":
            path = CACHE_DIR / f"news_{prefix or 'fundamentals'}.json"
        else:
            return None
    if path is None or not path.exists():
        return None
    l1_path = _l1_path(path)
    try:
        if not l1_path.exists() or path.stat().st_mtime > l1_path.stat().st_mtime:
            _build_l1_for_path(path)
    except Exception:
        pass
    if not l1_path.exists():
        return None
    try:
        with open(l1_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
