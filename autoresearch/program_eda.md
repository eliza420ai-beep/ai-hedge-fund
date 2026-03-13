# Autoresearch Program — EDA Sector (SNPS, CDNS)

Maximize Sharpe for EDA by tuning `params_eda.py`.

**Default mode:** Use the safe loop profile below unless explicitly running fast supervised exploration.

**Thesis:** Duopoly, infinite switching costs, design-starts growth. Most durable category per ikigaistudio.

**Baseline to beat:** val_sharpe=-0.14 (3-ticker: SNPS, CDNS, ARM). Strategy still negative; design-tool regime may differ from momentum/equipment.

```bash
poetry run python -m autoresearch.evaluate --params autoresearch.params_eda
poetry run python -m autoresearch.evaluate --params autoresearch.params_eda --start 2025-08-01 --end 2026-03-07
```

## Safe Loop Defaults (Recommended)

Use the hardened loop for unattended runs:

```bash
poetry run python -m autoresearch.run_autoresearch_loop \
  --sector eda \
  --iterations 80 \
  --confirm-runs 3 \
  --min-delta 0.005 \
  --require-oos-improvement
```
