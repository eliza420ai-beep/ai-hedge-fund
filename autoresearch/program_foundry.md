# Autoresearch Program — Foundry (TSM, GFS, UMC)

Maximize Sharpe for foundry by tuning `params_foundry.py`.

**Default mode:** Use the safe loop profile below unless explicitly running fast supervised exploration.

**Thesis:** Foundry monopoly + pure-plays. Ref: ikigaistudio TSM 14%.

**Baseline (as of last run):** in-sample Sharpe 1.03, OOS Sharpe 1.22, max DD -14.3%. Beat this with the loop.

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
