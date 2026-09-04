#!/usr/bin/env bash
set -u

# Run an improv show config as a detached background process, aborting on a stall.
# Usage: run_improv_sample.sh <config.yaml> <output_dir> [--no-stall-abort]
# Progress is written to <output_dir>/watch.log; the run's own logs go to stdout.log.

YAML="$1"
OUT="$2"
STALL_ABORT=1
if [[ "${3:-}" == "--no-stall-abort" ]]; then
  STALL_ABORT=0
fi

mkdir -p "$OUT"
if [[ -n "$(ls -A "$OUT" 2>/dev/null)" ]]; then
  echo "Output dir not empty: $OUT" >&2
  exit 2
fi

LOG="$OUT/watch.log"
: > "$LOG"
: > "$OUT/stdout.log"

( uv run python -m llm_from_here.showRunner "$YAML" --clear-cache --output-dir "$OUT" > "$OUT/stdout.log" 2>&1 ) &
PID=$!
echo "$(date +%T) [run_improv_sample] pid=$PID yaml=$YAML out=$OUT" >> "$LOG"
echo "started pid=$PID" >&2

if [[ "$STALL_ABORT" -eq 0 ]]; then
  wait "$PID"
  exit $?
fi

last_mt=0
while true; do
  if ! kill -0 "$PID" 2>/dev/null; then
    wait "$PID"; rc=$?
    echo "$(date +%T) [run_improv_sample] EXIT rc=$rc" >> "$LOG"
    exit $rc
  fi
  newest_mt=$(find "$OUT" -type f -exec stat -f %m {} \; 2>/dev/null | sort -n | tail -1)
  newest_mt=${newest_mt:-0}
  now=$(date +%s)
  if (( newest_mt > last_mt )); then
    last_mt=$newest_mt
    echo "$(date +%T) [run_improv_sample] activity ts=$newest_mt" >> "$LOG"
  fi
  if (( now - newest_mt > 900 )); then
    echo "$(date +%T) [run_improv_sample] STALL: no new files for $(( now - newest_mt ))s killing $PID" >> "$LOG"
    kill -9 "$PID" 2>/dev/null
    sleep 2
    exit 124
  fi
  sleep 20
done
