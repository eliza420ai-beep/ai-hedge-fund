#!/usr/bin/env bash
#
# Run second-opinion on TOP100.md in batches of 10 tickers.
# Pauses between batches so you can check results / costs before continuing.
#
# Usage:
#   chmod +x scripts/top100_batch_runner.sh
#   ./scripts/top100_batch_runner.sh            # start from batch 1
#   ./scripts/top100_batch_runner.sh 5          # resume from batch 5
#
# Prerequisites:
#   - Server running: poetry run uvicorn app.backend.main:app --host 0.0.0.0 --port 8000
#   - No --reload on the server!

set -euo pipefail

BATCH_SIZE=10
TOTAL_TICKERS=129
START_BATCH="${1:-1}"
TOTAL_BATCHES=$(( (TOTAL_TICKERS + BATCH_SIZE - 1) / BATCH_SIZE ))
DRAFT_DIR="second_opinion_runs"

echo "=== TOP100 batch runner ==="
echo "  Batch size:    $BATCH_SIZE"
echo "  Total tickers: $TOTAL_TICKERS"
echo "  Total batches: $TOTAL_BATCHES"
echo "  Starting from: batch $START_BATCH"
echo ""

for (( batch=START_BATCH; batch<=TOTAL_BATCHES; batch++ )); do
    offset=$(( (batch - 1) * BATCH_SIZE ))
    draft_file="${DRAFT_DIR}/top100_batch_${batch}.json"

    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  BATCH $batch / $TOTAL_BATCHES  (offset=$offset, size=$BATCH_SIZE)"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # Build draft for this batch
    poetry run python scripts/top100_to_second_opinion_draft.py \
        --top100 TOP100.md \
        --out "$draft_file" \
        --offset "$offset" \
        --max-tickers "$BATCH_SIZE" \
        --sleeve "bench_top100_batch_${batch}"

    # Run second opinion
    poetry run python scripts/dexter_second_opinion_client.py \
        --draft "$draft_file" \
        --flow-id 1 \
        --output-dir "$DRAFT_DIR" \
        --run-report

    echo ""
    echo "  Batch $batch complete."

    if (( batch < TOTAL_BATCHES )); then
        echo ""
        echo "  Next: batch $((batch + 1)) / $TOTAL_BATCHES"
        echo "  Press ENTER to continue, or Ctrl-C to stop (you can resume later with: $0 $((batch + 1)))"
        read -r
    fi
done

echo ""
echo "=== All $TOTAL_BATCHES batches complete ==="
echo "Results in $DRAFT_DIR/second_opinion_run_result_*.json"
echo ""
echo "To merge all batch reports:"
echo "  poetry run python scripts/top100_merge_batch_results.py --dir $DRAFT_DIR"
