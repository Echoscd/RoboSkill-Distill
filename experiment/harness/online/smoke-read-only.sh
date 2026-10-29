#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../../.." && pwd)"
EXPERIMENT_SCRIPTS="$REPO_ROOT/experiment/stack-blocks-three/scripts"
RUN_ROOT="${KINEX_SMOKE_RUNS:-$REPO_ROOT/experiment/harness/runs/online-smoke}"
RUN_DIR="${1:-$RUN_ROOT/$(date -u +%Y%m%dT%H%M%SZ)_press-stapler_camera-read}"

export KINEX_ITERATION="online_smoke_read_only"
export KINEX_TASK_ID="robotwin/press-stapler-aloha-agilex"
export KINEX_WORKSPACE="${KINEX_WORKSPACE:-$REPO_ROOT/env/workspaces/harness-online-smoke}"
export KINEX_EXPERIMENT_RUNS="$RUN_ROOT"
export KINEX_EXPERIMENT_PROMPT="$SCRIPT_DIR/smoke-read-only-prompt.txt"
export KINEX_TOOLSET_FILE="$SCRIPT_DIR/smoke-read-only-toolset.txt"
export KINEX_EXPERIMENT_TIMEOUT_S="${KINEX_EXPERIMENT_TIMEOUT_S:-180}"
export KINEX_ONLINE_HARNESS=1
export KINEX_HARNESS_MODE=observe
export KINEX_RUN_ID="$(basename "$RUN_DIR")"

mkdir -p "$RUN_DIR"
RUN_JSON=""
cleanup() {
  if [[ -n "$RUN_JSON" && -f "$RUN_JSON" ]]; then
    "$EXPERIMENT_SCRIPTS/stop-roboenv.sh" "$RUN_JSON" >"$RUN_DIR/stop.json" 2>"$RUN_DIR/stop.stderr.log" || true
  fi
}
trap cleanup EXIT INT TERM

"$EXPERIMENT_SCRIPTS/launch-roboenv.sh" "$RUN_DIR"
RUN_JSON="$(<"$RUN_DIR/roboenv-run.path")"

set +e
"$EXPERIMENT_SCRIPTS/run-qwen.sh" "$RUN_JSON" "$RUN_DIR"
AGENT_STATUS=$?
set -e

cleanup
trap - EXIT INT TERM
python3 "$REPO_ROOT/experiment/lib/finalize_run.py" \
  --run-dir "$RUN_DIR" \
  --process-exit-code "$AGENT_STATUS"
python3 "$SCRIPT_DIR/validate-smoke.py" "$RUN_DIR/harness-events.jsonl" \
  | tee "$RUN_DIR/online-smoke-validation.json"

printf 'RUN_DIR=%s\nAGENT_EXIT_CODE=%s\n' "$RUN_DIR" "$AGENT_STATUS"

