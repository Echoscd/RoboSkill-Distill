#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/common.sh"

check_environment
RUN_DIR="${1:-$RUNS_DIR/$(date -u +%Y%m%dT%H%M%SZ)_qwen3-vl-235b_adjust-bottle_seed0}"
mkdir -p "$RUN_DIR/roboenv" "$RUN_DIR/mplconfig" "$RUN_DIR/cache"

export MPLCONFIGDIR="$RUN_DIR/mplconfig"
export XDG_CACHE_HOME="$RUN_DIR/cache"

printf 'Launching RoboTwin into %s\n' "$RUN_DIR"
roboenv_cli launch robotwin/adjust-bottle-aloha-agilex \
  --run-dir "$RUN_DIR/roboenv" \
  --interpreter "$ROBOTWIN_PYTHON" \
  --python-path "$ROBOENV_PYTHON_PATH" \
  --allow-stop \
  --stop-on-success \
  --execution-mode realtime \
  --detach \
  --json \
  > >(tee "$RUN_DIR/launch.stdout.log") \
  2> >(tee "$RUN_DIR/launch.stderr.log" >&2)

RUN_JSON="$(find "$RUN_DIR/roboenv" -type f -name run.json -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)"
require_file "$RUN_JSON"
[[ "$(json_field "$RUN_JSON" state)" == "ready" ]] || {
  printf 'RoboEnv did not reach ready state: %s\n' "$RUN_JSON" >&2
  exit 1
}
printf '%s\n' "$RUN_JSON" >"$RUN_DIR/roboenv-run.path"
printf 'RUN_JSON=%s\n' "$RUN_JSON"
