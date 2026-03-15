# Second opinion on TOP100.md (The Bench)

Use the repo’s second-opinion pipeline to run the 18-agent committee (and risk/portfolio logic) on the tickers in **TOP100.md** (The Bench annex). You get agree/disagree buckets and optional Substack-ready output.

## Steps

### 1. Start the backend

From the repo root:

```bash
poetry run uvicorn app.backend.main:app --reload
```

Keep it running (default: `http://localhost:8000`). You need a **saved flow** (e.g. flow_id=1) that defines the graph; the second-opinion client loads graph from the API via `--flow-id`.

### 2. Build a draft from TOP100.md

```bash
poetry run python scripts/top100_to_second_opinion_draft.py \
  --top100 TOP100.md \
  --out second_opinion_runs/top100_bench_draft.json
```

Options:

- **`--max-tickers 10`** (or 20) — **strongly recommended for testing.** Full Bench (100+ tickers) = many LLM calls per run; a single run can take 30+ minutes and burn a lot of API credits. Use a small cap first to verify the pipeline, then increase or run full Bench only when you’re ready for cost/time.
- `--max-tickers 30` — cap for a medium run (default: no cap; script parses all tables and dedupes).
- `--sleeve bench_top100` — sleeve name in the draft (default).
- `--params-profile tastytrade_factors_on` — params hint (default).

Output: a PortfolioDraft JSON with `assets` (symbol + equal weight). The script prints the exact `dexter_second_opinion_client.py` command to run next.

### 3. Run second opinion

```bash
poetry run python scripts/dexter_second_opinion_client.py \
  --draft second_opinion_runs/top100_bench_draft.json \
  --flow-id 1 \
  --base-url http://localhost:8000 \
  --output-dir second_opinion_runs \
  --run-report
```

- Polls until the run is **COMPLETE** (or ERROR).
- Writes `second_opinion_run_result_<run_id>.json`.
- With `--run-report`, prints **Strong agree / Mild disagree / Hard disagree** buckets.
- **Cost & timeout:** Runs scale with ticker count (each analyst × ticker can trigger LLM calls). Default client timeout is 15 min. For 20+ tickers use e.g. `--timeout 3600`; expect higher API cost. Prefer `--max-tickers 10` when building the draft for smoke tests.

**Recover after client timeout:** The backend keeps running after the client times out. To see if a run completed and save the result without re-spending credits:

```bash
poetry run python scripts/second_opinion_fetch_result.py --run-id 16 --base-url http://localhost:8000
```

If status is `COMPLETE`, the script writes `second_opinion_run_result_16.json`; you can then run the report or Substack outline on that file.

### 4. (Optional) Substack outline / draft

From a completed run:

```bash
poetry run python scripts/second_opinion_to_substack_outline.py \
  --run-result second_opinion_runs/second_opinion_run_result_<run_id>.json \
  --out second_opinion_runs/substack_outline_top100.md
```

Use `--final-draft` for a full draft. See script help for other options.

## Summary

| Step | What it does |
|------|----------------|
| 1 | Backend + saved flow (e.g. flow_id=1) |
| 2 | `top100_to_second_opinion_draft.py` → draft JSON from TOP100.md |
| 3 | `dexter_second_opinion_client.py` → run committee, get result + report |
| 4 | `second_opinion_to_substack_outline.py` → narrative / Substack draft |

The Bench in TOP100.md is the **list to be stress-tested**; the second-opinion run is the **committee’s view** on those names (and optional sizing). Use the report and Substack output to compare your thesis to the model’s view.
