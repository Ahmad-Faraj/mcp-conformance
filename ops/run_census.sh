#!/usr/bin/env bash
# Run the census on a host with Docker.
#
#   bash ops/run_census.sh smoke    # 20 servers, checks the setup works
#   bash ops/run_census.sh full     # the whole eligible frame
#   bash ops/run_census.sh retest   # a seeded random subsample, for test-retest
#
# Results land in data/probe_results.jsonl and data/transcripts/. Nothing is
# overwritten: each mode writes to its own directory under data/runs/.
set -euo pipefail

MODE="${1:-smoke}"
WORKERS="${WORKERS:-8}"
TIMEOUT="${TIMEOUT:-90}"
SEED="${SEED:-20260719}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUTDIR="data/runs/${MODE}-${STAMP}"

mkdir -p "$OUTDIR"

case "$MODE" in
  smoke)  ARGS="--n 20 --seed $SEED" ;;
  full)   ARGS="--all" ;;
  retest) ARGS="--n ${RETEST_N:-400} --seed ${RETEST_SEED:-20260926}" ;;
  *) echo "unknown mode: $MODE" >&2; exit 2 ;;
esac

echo "mode=$MODE workers=$WORKERS timeout=${TIMEOUT}s out=$OUTDIR"
df -h . | tail -1

# shellcheck disable=SC2086
python3 driver/run_batch.py $ARGS --workers "$WORKERS" --timeout "$TIMEOUT" \
  2>&1 | tee "$OUTDIR/run.log"

mv -f data/probe_results.jsonl "$OUTDIR/" 2>/dev/null || true
if [ -d data/transcripts ]; then
  tar -czf "$OUTDIR/transcripts.tar.gz" data/transcripts
  rm -rf data/transcripts
fi

echo
echo "rows written: $(wc -l < "$OUTDIR/probe_results.jsonl" 2>/dev/null || echo 0)"
echo "results in $OUTDIR"
echo "check before trusting the run:"
echo "  every row carries harness_commit, image_digests and request_timeout_s"
echo "  no row carries batch_error"
echo "  transcripts parse as JSON end to end"
