# Autoresearch Program — Tokenization Sector (COIN, HOOD, CRCL)

Maximize Sharpe for tokenization by tuning `params_tokenization.py`.

**Default mode:** Use the safe loop profile below unless explicitly running fast supervised exploration.

**Thesis:** Crypto infrastructure, institutional + retail. Ref: ikigaistudio "The Fund, Rebalanced" — Tokenization 7%.

**Baseline to beat:** `val_sharpe=0.580, val_return=+15.6%, OOS=0.54`

```bash
poetry run python -m autoresearch.evaluate --params autoresearch.params_tokenization
poetry run python -m autoresearch.evaluate --params autoresearch.params_tokenization --start 2025-08-01 --end 2026-03-07
```

## Safe Loop Defaults (Recommended)

Use the hardened loop for unattended runs:

```bash
poetry run python -m autoresearch.run_autoresearch_loop \
  --sector tokenization \
  --iterations 80 \
  --confirm-runs 3 \
  --min-delta 0.005 \
  --require-oos-improvement
```
