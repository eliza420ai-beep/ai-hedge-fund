# Autoresearch Program — Photonics (LITE, COHR)

Maximize Sharpe for photonics by tuning `params_photonics.py`.

**Default mode:** Use the safe loop profile below unless explicitly running fast supervised exploration.

**Thesis:** Lumentum, Coherent. Ref: ikigaistudio LITE 4%, photonics support tier.

**Baseline to beat:** 2.26 (RISK_EXT 0.60) val, OOS 2.53

```bash
poetry run python -m autoresearch.evaluate --params autoresearch.params_photonics
```

## Safe Loop Defaults (Recommended)

Use the hardened loop for unattended runs:

```bash
poetry run python -m autoresearch.run_autoresearch_loop \
  --sector photonics \
  --iterations 80 \
  --confirm-runs 3 \
  --min-delta 0.005 \
  --require-oos-improvement
```
