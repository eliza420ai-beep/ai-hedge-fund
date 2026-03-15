"""
autoresearch/param_memory.py — Machine-readable experiment memory for the autoresearch loop.

Tracks (param, value, regime, sector, sharpe, accepted) so the loop can skip dead ends
and optionally prefer known-good values per regime. One .jsonl file per sector.
Supports session briefings (synthesize_briefing) and exploitation hints (suggest_start_value).
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class ExperimentRecord:
    param: str
    old_value: float
    new_value: float
    regime: str  # "bull" | "bear" | "sideways"
    sector: str
    in_sample_sharpe: float
    oos_sharpe: float | None
    max_dd: float | None
    accepted: bool
    ts: str


def _default_serializer(obj):
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    raise TypeError(type(obj).__name__)


class ParamMemory:
    """Queryable memory of parameter experiments. One .jsonl file per sector."""

    def __init__(self, path: Path):
        self.path = path
        self._records: list[ExperimentRecord] = self._load()

    def _load(self) -> list[ExperimentRecord]:
        records = []
        if not self.path.exists():
            return records
        with open(self.path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    records.append(
                        ExperimentRecord(
                            param=d["param"],
                            old_value=float(d["old_value"]),
                            new_value=float(d["new_value"]),
                            regime=d["regime"],
                            sector=d["sector"],
                            in_sample_sharpe=float(d["in_sample_sharpe"]),
                            oos_sharpe=float(d["oos_sharpe"]) if d.get("oos_sharpe") is not None else None,
                            max_dd=float(d["max_dd"]) if d.get("max_dd") is not None else None,
                            accepted=bool(d["accepted"]),
                            ts=d["ts"],
                        )
                    )
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    continue
        return records

    def record(self, r: ExperimentRecord) -> None:
        self._records.append(r)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a") as f:
            f.write(json.dumps(asdict(r), default=_default_serializer) + "\n")

    def skip_if_tested(
        self,
        param: str,
        value: float,
        regime: str,
        tolerance: float = 0.5,
    ) -> bool:
        """True if this (param, value, regime) combo was already tested (accepted or rejected)."""
        for rec in self._records:
            if rec.param != param or rec.regime != regime:
                continue
            if abs(rec.new_value - value) <= tolerance:
                return True
        return False

    def best_value_in_regime(self, param: str, regime: str) -> float | None:
        """Return the best accepted new_value for this param in this regime, or None."""
        best_sharpe = None
        best_value = None
        for rec in self._records:
            if rec.param != param or rec.regime != regime or not rec.accepted:
                continue
            if best_sharpe is None or rec.in_sample_sharpe > best_sharpe:
                best_sharpe = rec.in_sample_sharpe
                best_value = rec.new_value
        return best_value

    def summary(self) -> dict:
        """Acceptance rate and count per (param, regime)."""
        accepted_count: dict[tuple[str, str], int] = defaultdict(int)
        total_count: dict[tuple[str, str], int] = defaultdict(int)
        for rec in self._records:
            key = (rec.param, rec.regime)
            total_count[key] += 1
            if rec.accepted:
                accepted_count[key] += 1
        result: dict[str, dict[str, float | int]] = {}
        for (param, regime), total in total_count.items():
            key = f"{param}_{regime}"
            result[key] = {
                "param": param,
                "regime": regime,
                "accepted": accepted_count[(param, regime)],
                "total": total,
                "acceptance_rate": accepted_count[(param, regime)] / total if total else 0.0,
            }
        return result

    def suggest_start_value(self, param: str, regime: str) -> float | None:
        """
        Return the best accepted new_value for this param in this regime (for exploitation).
        Caller can use this ~30% of the time and random walk the rest.
        """
        return self.best_value_in_regime(param, regime)

    def synthesize_briefing(self) -> dict[str, Any]:
        """
        Produce a session briefing: per-param per-regime stats, dead zones, strategic notes.
        Written to session_briefing_{sector}.json by the loop.
        """
        sector = ""
        for rec in self._records:
            sector = rec.sector
            break
        total = len(self._records)
        accepted_total = sum(1 for r in self._records if r.accepted)
        overall_rate = (accepted_total / total) if total else 0.0

        per_param: dict[str, dict[str, Any]] = defaultdict(dict)
        param_regime_rejected: dict[tuple[str, str], list[float]] = defaultdict(list)
        param_regime_accepted_values: dict[tuple[str, str], list[float]] = defaultdict(list)
        best_sharpe_per_key: dict[tuple[str, str], float] = {}
        best_value_per_key: dict[tuple[str, str], float] = {}

        for rec in self._records:
            key = (rec.param, rec.regime)
            if rec.accepted:
                param_regime_accepted_values[key].append(rec.new_value)
                if key not in best_sharpe_per_key or rec.in_sample_sharpe > best_sharpe_per_key[key]:
                    best_sharpe_per_key[key] = rec.in_sample_sharpe
                    best_value_per_key[key] = rec.new_value
            else:
                param_regime_rejected[key].append(rec.new_value)

        seen: set[tuple[str, str]] = set()
        for rec in self._records:
            key = (rec.param, rec.regime)
            if key in seen:
                continue
            seen.add(key)
            total_pr = sum(1 for r in self._records if r.param == rec.param and r.regime == rec.regime)
            accepted_pr = sum(1 for r in self._records if r.param == rec.param and r.regime == rec.regime and r.accepted)
            accepted_vals = param_regime_accepted_values[key]
            rejected_vals = param_regime_rejected[key]
            best_value = best_value_per_key.get(key)
            worst_rejected = min(rejected_vals) if rejected_vals else None
            dead_zone: list[float] | None = None
            if rejected_vals:
                dead_zone = [min(rejected_vals), max(rejected_vals)]
            rec_rate = (accepted_pr / total_pr) if total_pr else 0.0
            recommendation = ""
            if best_value is not None:
                recommendation = f"try values near {best_value}"
            elif dead_zone:
                recommendation = f"avoid range [{dead_zone[0]:.4f}, {dead_zone[1]:.4f}] (all rejected)"
            per_param[rec.param][rec.regime] = {
                "experiments": total_pr,
                "acceptance_rate": round(rec_rate, 4),
                "best_value": best_value,
                "worst_rejected": worst_rejected,
                "dead_zone": dead_zone,
                "recommendation": recommendation or "no data yet",
            }

        strategic_notes: list[str] = []
        param_totals: dict[str, int] = defaultdict(int)
        for rec in self._records:
            param_totals[rec.param] += 1
        if param_totals:
            most_tested = max(param_totals, key=param_totals.get)
            pct = 100.0 * param_totals[most_tested] / total if total else 0
            strategic_notes.append(f"{most_tested} is the most tested param ({pct:.0f}% of experiments)")
        regime_rates: dict[str, list[float]] = defaultdict(list)
        for _param, regime_dict in per_param.items():
            for reg, stats in regime_dict.items():
                regime_rates[reg].append(stats.get("acceptance_rate", 0.0))
        for reg, rates in regime_rates.items():
            if rates:
                avg = sum(rates) / len(rates)
                strategic_notes.append(f"{reg} regime has average acceptance rate {avg:.2%}")
        if total and overall_rate < 0.1:
            strategic_notes.append("overall acceptance rate is low; consider smaller steps or different param set")

        return {
            "sector": sector or "unknown",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_experiments": total,
            "overall_acceptance_rate": round(overall_rate, 4),
            "per_param": {p: dict(r) for p, r in per_param.items()},
            "strategic_notes": strategic_notes,
        }
