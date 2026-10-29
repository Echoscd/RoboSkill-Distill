#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/common.sh"

check_environment
RUN_DIR="${1:?usage: launch-simulator.sh RUN_DIR}"
mkdir -p "$RUN_DIR/roboenv" "$RUN_DIR/mplconfig" "$RUN_DIR/cache"

export MPLCONFIGDIR="$RUN_DIR/mplconfig"
export XDG_CACHE_HOME="$RUN_DIR/cache"

recording_args=()
if [[ "${KINEX_RECORD_EXECUTION:-1}" == "1" ]]; then
  recording_args=(--record --record-fps "${KINEX_RECORD_FPS:-25}")
  recording_views="${KINEX_RECORD_VIEWS_FILE:-$REPO_ROOT/experiment/lib/recording-views-robotwin.json}"
  if [[ -f "$recording_views" ]]; then
    recording_args+=(--record-views "$recording_views")
  fi
fi

printf 'Launching %s into %s\n' "$TASK_ID" "$RUN_DIR"
roboenv_cli launch "$TASK_ID" \
  --run-dir "$RUN_DIR/roboenv" \
  --interpreter "$ROBOTWIN_PYTHON" \
  --python-path "$ROBOENV_PYTHON_PATH" \
  --allow-stop \
  --stop-on-success \
  --execution-mode realtime \
  "${recording_args[@]}" \
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

