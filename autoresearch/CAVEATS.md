# What Every Quant Knows — Caveats for Backtest Metrics

The autoresearch loop optimizes **Sharpe ratio** and reports Sortino, max drawdown, and return. These metrics rest on assumptions that often fail in practice. This doc states the caveats explicitly and how this repo addresses (or does not) address them.

---

## 1. Returns are not normally distributed

**Caveat:** Sharpe ratio assumes returns are roughly normal. In **fat-tail regimes** (crypto crashes, flash crashes, black swans), a strategy can show a great in-sample Sharpe and then blow up out-of-sample.

**In this repo:**

- We **report Sortino** (downside deviation) and **max drawdown** alongside Sharpe so fat tails show up in the downside.
- We do **not** optimize on skew/kurtosis or tail risk (VaR/CVaR) in the main loop.
- For tail-aware metrics we have `autoresearch/crypto_metrics.py`: `compute_skew_kurtosis`, `compute_var_cvar`, `compute_ulcer_metrics`. These can be wired into reporting or a separate audit script; they are not part of the canonical `val_sharpe` objective.
- **Recommendation:** In fat-tail or crypto-heavy universes, run `crypto_metrics` on backtest returns and treat high |skew| or excess kurtosis as a warning. Consider lowering risk or position size when tails are fat.

---

## 2. Volatility is a poor proxy for “risk” under skew/kurtosis

**Caveat:** Volatility (standard deviation) treats upside and downside equally. When returns are **skewed** or have **high kurtosis**, volatility understates tail risk. A strategy can have “low vol” and still have severe drawdowns.

**In this repo:**

- Position sizing uses **volatility bands** (`RISK_VOL_BANDS`, `RISK_EXTREME_VOL_MULT`) and drawdown-based scaling in paper trading (`risk_controls.scale_for_drawdown`, `--max-drawdown-pct`).
- We do **not** replace volatility with a skew/kurtosis-adjusted risk measure in the core backtest. Sortino and max_dd partially compensate by focusing on downside.
- **Recommendation:** Use max_dd and Sortino as primary sanity checks. If Sharpe improves but max_dd worsens or Sortino diverges from Sharpe, treat that as a regime where “risk” is not well captured by vol alone.

---

## 3. Look-ahead bias can inflate Sharpe

**Caveat:** Any use of future information in signal generation or parameters (e.g. tuning on the same window you evaluate on) inflates backtest Sharpe. The result is not tradable.

**In this repo:**

- **Fast backtest** uses only past data: signals are computed from prior closes and indicators; no future peeking.
- **Autoresearch** tunes on a fixed in-sample window and we **require OOS checks**: second-half or dedicated OOS window (`--start 2025-08-01 --end 2026-03-07`). Program docs and runbook say “revert if worse or equal” and “check OOS every ~10 commits.”
- **Walk-forward** (`walk_forward.py`, `backtest_regime.py`) trains on one window and tests on the next to reduce overfitting.
- We do **not** run a formal look-ahead audit (e.g. scanning all indicators for accidental future use). That remains a manual/periodic check.
- **Recommendation:** When adding new indicators or params, ensure they use only data available at decision time. Prefer OOS and walk-forward when judging robustness.

---

## 4. Past Sharpe does not predict future Sharpe (regime shifts)

**Caveat:** Regime shifts (vol expansion, correlation spikes, trend → mean-reversion) can make historical Sharpe irrelevant. Optimizing to the last year’s regime can hurt when the regime changes.

**In this repo:**

- We **split in-sample vs OOS** and report OOS Sharpe in results logs and runbook.
- **Regime overlay** exists (`regime.py`, `get_regime_with_drawdown`); portfolio and paper trading can scale by regime. It is not used inside the fast backtest objective.
- **Sector-specific params** (`params_equipment.py`, `params_energy.py`, etc.) and per-sector OOS Sharpe let us see which universes generalize.
- We do **not** automatically detect regime changes or reweight by regime in the autoresearch objective.
- **Recommendation:** Run OOS and walk-forward regularly. If OOS Sharpe drops while in-sample stays high, treat it as a possible regime shift and avoid over-trading on the in-sample optimum.

---

## Summary

| Caveat | How we mitigate | What we don’t do (yet) |
|--------|------------------|-------------------------|
| Non-normality / fat tails | Sortino, max_dd; crypto_metrics (skew, kurtosis, VaR/CVaR) available | Optimize on tail risk in main loop |
| Vol ≠ risk under skew/kurtosis | Sortino, max_dd, drawdown-based scaling in live/paper | No skew/kurtosis-adjusted risk in backtest |
| Look-ahead bias | OOS window, walk-forward, no future data in signals | No automated look-ahead audit |
| Regime shifts | OOS reporting, sector splits, regime.py for scaling | No regime-aware objective in autoresearch |

When in doubt: **trust OOS and max_dd at least as much as in-sample Sharpe.**

---

## How the repo enforces this

- **evaluate.py**  
  - Prints `val_sharpe`, `val_sortino`, `val_max_dd`, `val_return`.  
  - Optional **`--tail-metrics`**: if the backtest returns `returns_skew` and `returns_kurtosis`, prints `val_skew` and `val_kurtosis` for fat-tail awareness (e.g. `poetry run python -m autoresearch.evaluate --params autoresearch.params_tech --tail-metrics`).

- **run_autoresearch_loop.py**  
  - **`--require-oos-improvement`**: when set, a candidate is kept only if OOS Sharpe improves (in addition to in-sample Sharpe).  
  - **`--require-max-dd-no-worse`** (default: **on**): a candidate is rejected if in-sample max drawdown worsened by more than `--max-dd-tolerance` (default 1.0 percentage point). So we “trust max_dd”: better Sharpe is not kept if drawdown got meaningfully worse.  
  - Use **`--no-require-max-dd-no-worse`** to turn off the max_dd check (e.g. when you explicitly want to allow higher risk).
