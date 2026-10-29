#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
EXPERIMENT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
STATUS_FILE="$EXPERIMENT_DIR/status.tsv"
PID_FILE="$EXPERIMENT_DIR/batch.pid"

if [[ -f "$PID_FILE" ]]; then
  pid="$(<"$PID_FILE")"
  if kill -0 "$pid" 2>/dev/null; then
    printf 'batch: running (pid=%s)\n' "$pid"
  else
    printf 'batch: stopped (last pid=%s)\n' "$pid"
  fi
else
  printf 'batch: not started\n'
fi

if [[ -f "$STATUS_FILE" ]]; then
  printf '\ncompleted records:\n'
  column -t -s $'\t' "$STATUS_FILE" 2>/dev/null || cat "$STATUS_FILE"
else
  printf '\ncompleted records: 0/10\n'
fi

printf '\nlatest batch log:\n'
tail -n 30 "$EXPERIMENT_DIR/batch.log" 2>/dev/null || true
