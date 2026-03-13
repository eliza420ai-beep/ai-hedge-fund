"""
autoresearch/factors.py — Fundamental & event-based helper signals.

This module reads cached fundamentals/events from autoresearch/cache/ and
exposes small, interpretable factor snapshots that the fast backtester can use
as filters or sizing multipliers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd


CACHE_DIR = Path(__file__).resolve().parent / "cache"

# String sentiment labels -> numeric for averaging (bounded -1 to 1)
_SENTIMENT_MAP = {
    "positive": 1.0,
    "negative": -1.0,
    "neutral": 0.0,
    "bearish": -0.7,
    "bullish": 0.7,
}


@dataclass
class FactorSnapshot:
    ticker: str
    as_of: str
    value_score: float | None
    quality_score: float | None
    leverage_score: float | None
    insider_net_shares: float | None


_METRICS_DF: Dict[str, pd.DataFrame] | None = None
_INSIDER_MAP: Dict[str, List[dict]] | None = None
_NEWS_CACHE: Dict[str, Dict[str, List[dict]]] = {}


def _load_macro_rates(cache_dir: Path | None = None) -> List[dict]:
    """Load interest_rates from macro_rates.json; filter to FED, sort by date."""
    directory = cache_dir or CACHE_DIR
    path = directory / "macro_rates.json"
    if not path.exists():
        return []
    try:
        with open(path) as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    rates = raw.get("interest_rates", [])
    bank = "FED"
    filtered = [r for r in rates if r.get("bank") == bank and r.get("date") and r.get("rate") is not None]
    try:
        filtered.sort(key=lambda x: x["date"])
    except (KeyError, TypeError):
        return []
    return filtered


def get_macro_snapshot(
    as_of_date: str,
    rates: List[dict],
    lookback_months: int = 6,
) -> Optional[Dict[str, Any]]:
    """
    Return {rate, regime, prior_rate} for as_of_date.
    Regime: tightening (rate > prior), easing (rate < prior), else stable.
    """
    if not rates:
        return None
    try:
        as_dt = datetime.strptime(as_of_date, "%Y-%m-%d")
    except ValueError:
        return None
    # Latest rate on or before as_of_date
    current_rate = None
    current_idx = None
    for i, r in enumerate(rates):
        try:
            rd = datetime.strptime(r["date"], "%Y-%m-%d")
            if rd.date() <= as_dt.date():
                current_rate = float(r["rate"])
                current_idx = i
        except (KeyError, ValueError, TypeError):
            continue
    if current_rate is None or current_idx is None:
        return None
    # Prior rate ~lookback_months ago (by index, not calendar)
    prior_idx = max(0, current_idx - lookback_months)
    prior_rate = float(rates[prior_idx].get("rate", current_rate))
    if current_rate > prior_rate:
        regime = "tightening"
    elif current_rate < prior_rate:
        regime = "easing"
    else:
        regime = "stable"
    return {"rate": current_rate, "regime": regime, "prior_rate": prior_rate}


def apply_macro_overlay(snapshot: Optional[Dict[str, Any]], params: Any) -> tuple[bool, float]:
    """Apply macro regime sizing overlay. Returns (allowed, size_multiplier)."""
    if not getattr(params, "USE_MACRO_OVERLAY", False) or snapshot is None:
        return True, 1.0
    regime = snapshot.get("regime", "stable")
    mult = 1.0
    if regime == "tightening":
        mult = float(getattr(params, "MACRO_TIGHTENING_SCALE", 0.85))
    elif regime == "easing":
        mult = float(getattr(params, "MACRO_EASING_SCALE", 1.05))
    else:
        mult = float(getattr(params, "MACRO_STABLE_SCALE", 1.0))
    return True, mult


def _load_metrics(prefix: str) -> Dict[str, pd.DataFrame]:
    global _METRICS_DF
    if _METRICS_DF is not None:
        return _METRICS_DF

    path = CACHE_DIR / f"financial_metrics_{prefix}.json"
    if not path.exists():
        _METRICS_DF = {}
        return _METRICS_DF

    with open(path) as f:
        raw: Dict[str, List[dict]] = json.load(f)

    frames: Dict[str, pd.DataFrame] = {}
    for ticker, rows in raw.items():
        if not rows:
            continue
        df = pd.DataFrame(rows)
        if "report_period" in df.columns:
            df["report_period"] = pd.to_datetime(df["report_period"])
            df = df.sort_values("report_period")
        frames[ticker] = df

    _METRICS_DF = frames
    return frames


def _load_insider(prefix: str) -> Dict[str, List[dict]]:
    global _INSIDER_MAP
    if _INSIDER_MAP is not None:
        return _INSIDER_MAP

    path = CACHE_DIR / f"insider_trades_{prefix}.json"
    if not path.exists():
        _INSIDER_MAP = {}
        return _INSIDER_MAP

    with open(path) as f:
        raw: Dict[str, List[dict]] = json.load(f)

    _INSIDER_MAP = raw
    return raw


def _load_news(prefix: str) -> Dict[str, List[dict]]:
    """Load news_<prefix>.json; return {ticker: [items]}."""
    if prefix in _NEWS_CACHE:
        return _NEWS_CACHE[prefix]
    path = CACHE_DIR / f"news_{prefix}.json"
    if not path.exists():
        _NEWS_CACHE[prefix] = {}
        return _NEWS_CACHE[prefix]
    try:
        with open(path) as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        _NEWS_CACHE[prefix] = {}
        return _NEWS_CACHE[prefix]
    if not isinstance(raw, dict):
        _NEWS_CACHE[prefix] = {}
        return _NEWS_CACHE[prefix]
    _NEWS_CACHE[prefix] = raw
    return raw


def _parse_news_date(date_val: Any) -> Optional[datetime]:
    """Parse date from news item (YYYY-MM-DD or ISO string)."""
    if date_val is None:
        return None
    s = str(date_val).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(s.replace("Z", "").split(".")[0], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _sentiment_to_number(sentiment: Any) -> Optional[float]:
    """Map sentiment field to numeric in [-1, 1]. Returns None if unusable."""
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


def compute_news_sentiment_snapshot(
    ticker: str,
    date_str: str,
    prefix: str,
    lookback_days: int = 30,
) -> Optional[float]:
    """
    Average sentiment for ticker's news in (date_str - lookback_days, date_str].
    Return value in [-1, 1], or None if no usable data.
    """
    data = _load_news(prefix)
    items = data.get(ticker, [])
    if not items:
        return None
    try:
        as_of = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None
    cutoff = as_of - timedelta(days=lookback_days)
    values: List[float] = []
    for item in items:
        d = _parse_news_date(item.get("date"))
        if d is None or d.date() <= cutoff.date() or d.date() > as_of.date():
            continue
        v = _sentiment_to_number(item.get("sentiment"))
        if v is not None:
            values.append(v)
    if not values:
        return None
    return sum(values) / len(values)


def apply_news_rules(sentiment_score: Optional[float], params: Any) -> tuple[bool, float]:
    """Apply news sentiment filter/sizing. Returns (allowed, size_multiplier)."""
    if not getattr(params, "USE_NEWS_FILTER", False) or sentiment_score is None:
        return True, 1.0
    min_sentiment = getattr(params, "NEWS_SENTIMENT_MIN", 0.0)
    mult = getattr(params, "NEWS_SIZE_MULTIPLIER", 0.5)
    if sentiment_score < min_sentiment:
        return True, mult
    return True, 1.0


def _latest_metrics_before(
    ticker: str,
    as_of: datetime,
    prefix: str,
) -> Optional[pd.Series]:
    frames = _load_metrics(prefix)
    df = frames.get(ticker)
    if df is None or df.empty:
        return None
    if "report_period" not in df.columns:
        return df.iloc[-1]

    mask = df["report_period"] <= as_of
    if not mask.any():
        return None
    return df.loc[mask].iloc[-1]


def _insider_net_shares(
    ticker: str,
    as_of: datetime,
    prefix: str,
    lookback_days: int,
) -> Optional[float]:
    data = _load_insider(prefix)
    trades = data.get(ticker, [])
    if not trades:
        return None

    cutoff = as_of - timedelta(days=lookback_days)
    net = 0.0
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
        if shares is None:
            continue
        try:
            net += float(shares)
        except (TypeError, ValueError):
            continue
    return net


def compute_factor_snapshot(
    ticker: str,
    date_str: str,
    prefix: str,
    insider_lookback_days: int = 365,
) -> Optional[FactorSnapshot]:
    """Return a compact factor snapshot for one ticker as of date_str."""
    try:
        as_of = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None

    row = _latest_metrics_before(ticker, as_of, prefix)
    if row is None:
        return None

    # Simple, bounded scores based on a handful of intuitive fields.
    pe = float(row.get("price_to_earnings_ratio") or 0.0)
    ev_ebitda = float(row.get("enterprise_value_to_ebitda_ratio") or 0.0)
    ps = float(row.get("price_to_sales_ratio") or 0.0)

    # Value: lower multiples are better. Treat <=0 as neutral.
    comps = [x for x in (pe, ev_ebitda, ps) if x > 0]
    value_score = None
    if comps:
        avg_mult = sum(comps) / len(comps)
        # Map multiples into a 0–1 band (cheap→1, expensive→0) with soft clipping.
        value_score = max(0.0, min(1.0, (30.0 - min(avg_mult, 60.0)) / 30.0))

    roe = float(row.get("return_on_equity") or 0.0)
    roic = float(row.get("return_on_invested_capital") or 0.0)
    gross = float(row.get("gross_margin") or 0.0)
    op_margin = float(row.get("operating_margin") or 0.0)
    net_margin = float(row.get("net_margin") or 0.0)

    quality_components = [roe, roic, gross, op_margin, net_margin]
    qs = [c for c in quality_components if c is not None]
    quality_score = None
    if qs:
        avg_q = sum(qs) / len(qs)
        # Map margins/returns into 0–1 (0%→0, 40%+→1).
        quality_score = max(0.0, min(1.0, avg_q / 40.0))

    debt_to_equity = row.get("debt_to_equity")
    interest_cov = row.get("interest_coverage")
    leverage_score = None
    try:
        d2e = float(debt_to_equity) if debt_to_equity is not None else None
        cov = float(interest_cov) if interest_cov is not None else None
    except (TypeError, ValueError):
        d2e = cov = None

    if d2e is not None or cov is not None:
        # Very rough: penalize very levered names or those with weak coverage.
        score = 0.5
        if d2e is not None:
            if d2e > 3.0:
                score -= 0.25
            elif d2e < 1.0:
                score += 0.1
        if cov is not None:
            if cov < 2.0:
                score -= 0.25
            elif cov > 6.0:
                score += 0.1
        leverage_score = max(0.0, min(1.0, score))

    insider_net = _insider_net_shares(
        ticker=ticker,
        as_of=as_of,
        prefix=prefix,
        lookback_days=insider_lookback_days,
    )

    return FactorSnapshot(
        ticker=ticker,
        as_of=date_str,
        value_score=value_score,
        quality_score=quality_score,
        leverage_score=leverage_score,
        insider_net_shares=insider_net,
    )


def apply_fundamental_rules(
    snapshot: FactorSnapshot | None,
    params,
) -> tuple[bool, float]:
    """
    Apply simple filter/sizing rules based on params.

    Returns:
        (allowed, size_multiplier)
    """
    if snapshot is None:
        # No data → allow but do not scale.
        return True, 1.0

    mult = 1.0
    allowed = True

    # Value filter: penalize expensive names via sizing, but don't hard-ban.
    use_value = getattr(params, "USE_VALUE_FILTER", False)
    min_value = getattr(params, "MIN_VALUE_SCORE", 0.0)
    if use_value and snapshot.value_score is not None:
        if snapshot.value_score < min_value:
            # Down-weight instead of outright blocking the name.
            mult *= getattr(params, "INSIDER_SIZE_MULTIPLIER", 0.5)

    # Quality filter: penalize low-quality names via sizing, but don't hard-ban.
    use_quality = getattr(params, "USE_QUALITY_FILTER", False)
    min_quality = getattr(params, "MIN_QUALITY_SCORE", 0.0)
    if use_quality and snapshot.quality_score is not None:
        if snapshot.quality_score < min_quality:
            mult *= getattr(params, "INSIDER_SIZE_MULTIPLIER", 0.5)

    # Insider filter: down-weight persistent net sellers
    use_insider = getattr(params, "USE_INSIDER_FILTER", False)
    sell_threshold = getattr(params, "INSIDER_NET_SELL_THRESHOLD", 0.0)
    insider_mult = getattr(params, "INSIDER_SIZE_MULTIPLIER", 0.5)
    if use_insider and snapshot.insider_net_shares is not None:
        if snapshot.insider_net_shares < sell_threshold:
            mult *= insider_mult

    return allowed, mult


def apply_worldmonitor_overlay(
    wm_snapshot: dict[str, Any] | None,
    params,
) -> tuple[bool, float]:
    """
    Optional macro/geopolitical sizing overlay from a normalized WM snapshot.

    This helper is a scaffold and is not wired into execution paths yet.
    Returns:
        (allowed, size_multiplier)
    """
    use_wm = getattr(params, "USE_WM_FILTER", False)
    if not use_wm or not wm_snapshot:
        return True, 1.0

    mult = 1.0
    allowed = True

    regime = wm_snapshot.get("wm_macro_regime")
    if regime == "risk_off":
        mult *= float(getattr(params, "WM_RISK_OFF_SCALE", 0.8))

    country_risk = wm_snapshot.get("wm_country_risk") or {}
    cap = float(getattr(params, "WM_COUNTRY_RISK_CAP", 85.0))
    if isinstance(country_risk, dict) and country_risk:
        max_risk = max(
            (float(v) for v in country_risk.values() if isinstance(v, (int, float))),
            default=0.0,
        )
        if max_risk >= cap:
            # Keep this soft in scaffold phase: no hard ban, only scale down.
            mult *= 0.9

    return allowed, mult

