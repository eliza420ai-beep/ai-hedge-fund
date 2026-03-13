# Autoresearch Program — Foundry (TSM, GFS, UMC)

Maximize Sharpe for foundry by tuning `params_foundry.py`.

**Default mode:** Use the safe loop profile below unless explicitly running fast supervised exploration.

**Thesis:** Foundry monopoly + pure-plays. Ref: ikigaistudio TSM 14%.

**Baseline to beat:** 0.99 (RISK 0.38 → 1.03, OOS 1.22)

```bash
poetry run python -m autoresearch.evaluate --params autoresearch.params_foundry
```

## Safe Loop Defaults (Recommended)

Use the hardened loop for unattended runs:

```bash
poetry run python -m autoresearch.run_autoresearch_loop \
  --sector foundry \
  --iterations 80 \
  --confirm-runs 3 \
  --min-delta 0.005 \
  --require-oos-improvement
```
