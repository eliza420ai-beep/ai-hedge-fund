# Second opinion on TOP100.md (The Bench)

Use the repo's second-opinion pipeline to run the 18-agent committee (and risk/portfolio logic) on the tickers in **TOP100.md** (The Bench annex). You get agree/disagree buckets and optional Substack-ready output.

---

## Safe run (avoid burning credits)

**Two commands.** Run from repo root. Use a **small draft** (10 tickers) so the run finishes in a few minutes and costs little.

**1) Start the server (Terminal 1)** — **Do not use `--reload`.** Reload kills long-running jobs when you save files.

```bash
poetry run uvicorn app.backend.main:app --host 0.0.0.0 --port 8000
```

Leave this running. If port 8000 is in use, stop the other process first: `lsof -i :8000` then `kill <PID>`.

**2) Build a small draft and run second opinion (Terminal 2)**

```bash
poetry run python scripts/top100_to_second_opinion_draft.py --top100 TOP100.md --out second_opinion_runs/top100_bench_draft.json --max-tickers 10
poetry run python scripts/dexter_second_opinion_client.py --draft second_opinion_runs/top100_bench_draft.json --flow-id 1 --output-dir second_opinion_runs --run-report
```

- First line: draft with **10 tickers only** (low cost).
- Second line: submit run, wait for COMPLETE, save result, print agree/disagree report.
- Do **not** edit app/ or scripts while the run is in progress (if you ever use `--reload` again, edits would restart the server and kill the run).

### Full run (all tickers)

When you're ready to run the entire Bench (~100+ tickers):

```bash
# Build full draft (no --max-tickers)
poetry run python scripts/top100_to_second_opinion_draft.py \
  --top100 TOP100.md \
  --out second_opinion_runs/top100_bench_draft.json

# Run with 2-hour timeout
poetry run python scripts/dexter_second_opinion_client.py \
  --draft second_opinion_runs/top100_bench_draft.json \
  --flow-id 1 \
  --output-dir second_opinion_runs \
  --run-report \
  --timeout 7200
```

- Expect 30–60 min depending on API rate limits. `--timeout 7200` (2 hours) gives plenty of buffer.
- If the client times out, the server keeps running. Recover with:

```bash
poetry run python scripts/second_opinion_fetch_result.py --run-id <N> --wait
```

### Batch run (10 at a time — recommended for cost control)

Runs all 129 tickers in batches of 10. Pauses between batches so you can check costs.

```bash
# Start from batch 1
./scripts/top100_batch_runner.sh

# Or resume from batch 5 (if you stopped earlier)
./scripts/top100_batch_runner.sh 5
```

Each batch takes ~3–5 min. Press Enter between batches to continue, Ctrl-C to stop.
After all batches, merge into one report:

```bash
poetry run python scripts/top100_merge_batch_results.py --dir second_opinion_runs
```

You can also build a single batch manually with `--offset`:

```bash
poetry run python scripts/top100_to_second_opinion_draft.py \
  --top100 TOP100.md --out second_opinion_runs/top100_batch_3.json \
  --offset 20 --max-tickers 10
```

---

## Steps (detailed)

### 2. Build a draft from TOP100.md

```bash
poetry run python scripts/top100_to_second_opinion_draft.py \
  --top100 TOP100.md \
  --out second_opinion_runs/top100_bench_draft.json
```

Options:

- **`--max-tickers 10`** (or 20) — **strongly recommended for testing.** Full Bench (100+ tickers) = many LLM calls per run; a single run can take 30+ minutes and burn a lot of API credits. Use a small cap first to verify the pipeline, then increase or run full Bench only when you're ready for cost/time.
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
- **Cost & timeout:** Runs scale with ticker count (each analyst × ticker can trigger LLM calls). Default client timeout is 15 min. For 20+ tickers use `--timeout 3600`; for 100+ use `--timeout 7200`. Prefer `--max-tickers 10` when building the draft for smoke tests.

**Recover after client timeout:** The backend keeps running after the client times out. To see if a run completed and save the result without re-spending credits:

```bash
poetry run python scripts/second_opinion_fetch_result.py --run-id <N> --base-url http://localhost:8000
# Or poll until done:
poetry run python scripts/second_opinion_fetch_result.py --run-id <N> --wait
```

If status is `COMPLETE`, the script writes `second_opinion_run_result_<N>.json`; you can then run the report or Substack outline on that file.

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

The Bench in TOP100.md is the **list to be stress-tested**; the second-opinion run is the **committee's view** on those names (and optional sizing). Use the report and Substack output to compare your thesis to the model's view.
