"""
autoresearch/cache_manifest.py — Unified cache index (OpenViking-style filesystem paradigm).

Maintains cache/manifest.json with metadata for every cache file so subsystems
can resolve paths deterministically and check staleness instead of glob/fallback chains.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CACHE_DIR = Path(__file__).resolve().parent / "cache"
MANIFEST_PATH = CACHE_DIR / "manifest.json"

# Filename patterns -> data type (for indexing)
TYPE_PATTERNS = [
    ("prices", "prices"),
    ("signals", "signals"),
    ("financial_metrics", "financial_metrics"),
    ("insider_trades", "insider_trades"),
    ("news", "news"),
    ("macro_rates", "macro_rates"),
    ("crypto_prices", "crypto_prices"),
    ("worldmonitor", "worldmonitor"),
]


def _infer_type(filename: str) -> str | None:
    for pattern, data_type in TYPE_PATTERNS:
        if pattern in filename and filename.endswith(".json"):
            return data_type
    return None


def _extract_meta(path: Path, data_type: str, size_bytes: int, modified_iso: str) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "type": data_type,
        "size_bytes": size_bytes,
        "modified": modified_iso,
        "stale": False,
    }
    try:
        with open(path) as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        meta["tickers"] = []
        meta["date_range"] = []
        return meta

    if data_type == "prices" and isinstance(raw, dict):
        tickers = list(raw.keys())
        meta["tickers"] = tickers
        meta["rows_per_ticker"] = 0
        dates: list[str] = []
        for t in tickers[:1]:
            rows = raw.get(t) or []
            if isinstance(rows, list) and rows:
                meta["rows_per_ticker"] = len(rows)
                for r in rows:
                    if isinstance(r, dict) and "date" in r:
                        dates.append(str(r["date"]))
                        break
                if rows and isinstance(rows[0], dict) and "date" in rows[0]:
                    dates = [rows[0].get("date"), rows[-1].get("date")] if rows else []
            break
        meta["date_range"] = sorted(dates)[:2] if dates else []

    elif data_type == "signals" and isinstance(raw, dict):
        dates = list(raw.keys())
        meta["tickers"] = []
        meta["date_range"] = sorted(dates)[:2] if dates else []
        meta["cached_dates"] = len(dates)

    elif data_type == "financial_metrics" and isinstance(raw, dict):
        meta["tickers"] = list(raw.keys())
        total = sum(len(v) if isinstance(v, list) else 0 for v in raw.values())
        meta["total_records"] = total
        meta["date_range"] = []

    elif data_type == "insider_trades" and isinstance(raw, dict):
        meta["tickers"] = list(raw.keys())
        total = sum(len(v) if isinstance(v, list) else 0 for v in raw.values())
        meta["total_records"] = total
        meta["date_range"] = []

    elif data_type == "news" and isinstance(raw, dict):
        meta["tickers"] = list(raw.keys())
        total = sum(len(v) if isinstance(v, list) else 0 for v in raw.values())
        meta["total_records"] = total
        meta["date_range"] = []

    elif data_type == "macro_rates":
        if isinstance(raw, list) and raw:
            dates = []
            for r in raw:
                if isinstance(r, dict) and r.get("date"):
                    dates.append(str(r["date"]))
            meta["date_range"] = sorted(dates)[:2] if dates else []
            meta["total_records"] = len(raw)
        elif isinstance(raw, dict) and "data" in raw:
            arr = raw["data"] if isinstance(raw["data"], list) else []
            meta["total_records"] = len(arr)
            meta["date_range"] = []
        else:
            meta["date_range"] = []
            meta["total_records"] = 0
        meta["tickers"] = []

    else:
        meta["tickers"] = []
        meta["date_range"] = []

    return meta


def rebuild_manifest(max_age_days: int = 7) -> dict[str, Any]:
    """
    Scan cache/, index every cache file with metadata, write manifest.json.
    Sets stale=True for files older than max_age_days.
    Returns the manifest dict.
    """
    now = datetime.now(timezone.utc)
    cutoff_ts = now.timestamp() - (max_age_days * 86400)
    files_meta: dict[str, dict[str, Any]] = {}

    if not CACHE_DIR.exists():
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    skip_prefixes = ("manifest", "meta.", "_l1", ".bak")
    skip_exact = {"meta.json"}

    for path in sorted(CACHE_DIR.iterdir()):
        if not path.is_file() or path.suffix != ".json":
            continue
        name = path.name
        if name in skip_exact or any(name.startswith(p) or "_l1" in name for p in skip_prefixes):
            continue
        if name.endswith(".bak"):
            continue
        data_type = _infer_type(name)
        if not data_type:
            continue
        try:
            stat = path.stat()
            size_bytes = stat.st_size
            modified_iso = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
            stale = stat.st_mtime < cutoff_ts
        except OSError:
            continue
        meta = _extract_meta(path, data_type, size_bytes, modified_iso)
        meta["stale"] = stale
        files_meta[name] = meta

    manifest = {
        "generated_at": now.isoformat(),
        "files": files_meta,
    }
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)
    return manifest


def get_manifest(force_rebuild: bool = False) -> dict[str, Any]:
    """
    Load cached manifest. Rebuild if missing or if any cache file is newer than manifest.
    """
    if force_rebuild or not MANIFEST_PATH.exists():
        return rebuild_manifest()
    try:
        manifest_mtime = MANIFEST_PATH.stat().st_mtime
    except OSError:
        return rebuild_manifest()
    for path in CACHE_DIR.iterdir():
        if not path.is_file() or path.suffix != ".json" or path.name == "manifest.json":
            continue
        if "_l1" in path.name or path.name.startswith("meta") or path.name.endswith(".bak"):
            continue
        try:
            if path.stat().st_mtime > manifest_mtime:
                return rebuild_manifest()
        except OSError:
            pass
    with open(MANIFEST_PATH) as f:
        return json.load(f)


def resolve(data_type: str, sector_or_universe: str | None = None) -> Path | None:
    """
    Return path to the best-matching cache file for the given data type and optional hint.
    E.g. resolve("prices", "benchmark") -> prices_benchmark.json if exists else prices.json.
    """
    manifest = get_manifest()
    files = manifest.get("files") or {}
    candidates = [(name, meta) for name, meta in files.items() if meta.get("type") == data_type]
    if not candidates:
        return None
    if sector_or_universe:
        preferred = f"{data_type}_{sector_or_universe}.json"
        for name, _ in candidates:
            if name == preferred:
                return CACHE_DIR / name
        if data_type == "prices" and sector_or_universe == "benchmark":
            for name in [f"prices_benchmark.json", "prices.json"]:
                if name in files:
                    return CACHE_DIR / name
    return CACHE_DIR / candidates[0][0]


def check_staleness(max_age_days: int = 7) -> list[tuple[str, dict[str, Any]]]:
    """
    Rebuild manifest with given max_age_days and return list of (filename, meta) for stale files.
    """
    manifest = rebuild_manifest(max_age_days=max_age_days)
    files = manifest.get("files") or {}
    return [(name, meta) for name, meta in files.items() if meta.get("stale")]
