#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/common.sh"

check_environment
RUN_DIR="${1:-$RUNS_DIR/$(date -u +%Y%m%dT%H%M%SZ)_qwen3-vl-235b_adjust-bottle_seed0}"
mkdir -p "$RUN_DIR"

RUN_JSON=""
cleanup() {
  final_exit=$?
  set +e
  if [[ -n "$RUN_JSON" ]]; then
    if [[ "${KEEP_SIMULATOR:-0}" == "1" ]]; then
      printf 'KEEP_SIMULATOR=1; simulator remains available at %s\n' "$RUN_JSON"
    else
      "$SCRIPT_DIR/stop-roboenv.sh" "$RUN_JSON" >"$RUN_DIR/stop.json" 2>"$RUN_DIR/stop.stderr.log" || true
    fi
  fi
  python3 "$REPO_ROOT/experiment/lib/evaluate_simulator.py" \
    --run-dir "$RUN_DIR" \
    >"$RUN_DIR/simulator-evaluation.log" 2>&1 || true
  python3 "$REPO_ROOT/experiment/lib/finalize_run.py" \
    --run-dir "$RUN_DIR" \
    --process-exit-code "$final_exit" \
    >>"$RUN_DIR/finalize.log" 2>&1 || true
}
trap cleanup EXIT

"$SCRIPT_DIR/deploy-tools.sh"
"$SCRIPT_DIR/launch-roboenv.sh" "$RUN_DIR"
RUN_JSON="$(<"$RUN_DIR/roboenv-run.path")"

set +e
"$SCRIPT_DIR/run-qwen.sh" "$RUN_JSON" "$RUN_DIR"
agent_status=$?
set -e

printf 'Experiment directory: %s\n' "$RUN_DIR"
exit "$agent_status"
