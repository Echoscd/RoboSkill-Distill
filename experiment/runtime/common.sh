#!/usr/bin/env bash

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
EXPERIMENT_DIR="${KINEX_TASK_DIR:-$REPO_ROOT/experiment/press-stapler}"

ITERATION="${KINEX_ITERATION:-autonomous}"
ENV_ROOT="${KINEX_ENV_ROOT:-$REPO_ROOT/env}"
BASE_WORKSPACE="${KINEX_BASE_WORKSPACE:-$ENV_ROOT/workspace}"
WORKSPACE="${KINEX_WORKSPACE:-$ENV_ROOT/workspaces/$(basename "$EXPERIMENT_DIR")}"
RUNS_DIR="${KINEX_EXPERIMENT_RUNS:-$EXPERIMENT_DIR/runs/$ITERATION}"
PROMPT_FILE="${KINEX_EXPERIMENT_PROMPT:?Set KINEX_EXPERIMENT_PROMPT to a rendered task prompt}"
TOOLSET_FILE="${KINEX_TOOLSET_FILE:-$REPO_ROOT/experiment/toolset.txt}"
KEY_FILE="${OPENROUTER_KEY_FILE:-$ENV_ROOT/secrets/openrouter_api_key}"
SESSION_DATA="${KINEX_SESSION_DATA:-$ENV_ROOT/data/agent/sessions}"
KINEX_BIN="${KINEX_BIN:-$ENV_ROOT/bin/kinex-via-pc}"

ROBOENV_ROOT="${ROBOENV_ROOT:-$ENV_ROOT/RoboEnv}"
ROBOTWIN_PYTHON="${ROBOTWIN_PYTHON:-/LargeModelDev/users/chendong.song/env/robotwin/bin/python}"
ROBOENV_PYTHON_PATH="${ROBOENV_PYTHON_PATH:-$ROBOENV_ROOT/combined-pythonpath}"
ROBOENV_MODULE_PATH="${ROBOENV_MODULE_PATH:-$ROBOENV_ROOT/runtime/src:$ROBOENV_ROOT/src}"

MODEL="${KINEX_EXPERIMENT_MODEL:-openrouter/qwen/qwen3.8-max-0902}"
PC_PROXY_URL="${KINEX_PC_PROXY_URL:-http://192.168.224.140:18000}"
MAX_SECONDS="${KINEX_EXPERIMENT_TIMEOUT_S:-900}"
TASK_ID="${KINEX_TASK_ID:-$EXPERIMENT_DIR/task.yaml}"

require_file() {
  [[ -f "$1" ]] || { printf 'Required file is missing: %s\n' "$1" >&2; return 1; }
}

require_executable() {
  [[ -x "$1" ]] || { printf 'Required executable is missing: %s\n' "$1" >&2; return 1; }
}

prepare_workspace() {
  mkdir -p "$WORKSPACE/.kinex" "$WORKSPACE/.kinex/tools" "$WORKSPACE/.kinex/recordings"
  require_file "$BASE_WORKSPACE/.kinex/workspace.yaml"
  cp "$BASE_WORKSPACE/.kinex/workspace.yaml" "$WORKSPACE/.kinex/workspace.yaml"
  for shared in devices python; do
    if [[ ! -e "$WORKSPACE/.kinex/$shared" ]]; then
      ln -s "$BASE_WORKSPACE/.kinex/$shared" "$WORKSPACE/.kinex/$shared"
    fi
  done
}

check_environment() {
  require_executable "$ROBOTWIN_PYTHON"
  require_executable "$KINEX_BIN"
  require_file "$KEY_FILE"
  require_file "$PROMPT_FILE"
  require_file "$TOOLSET_FILE"
  prepare_workspace
  [[ -d "$WORKSPACE/.kinex/devices" ]] || {
    printf 'Kinex devices are missing from workspace: %s\n' "$WORKSPACE" >&2
    return 1
  }
  mkdir -p "$RUNS_DIR" "$SESSION_DATA"
}

roboenv_cli() {
  PYTHONPATH="$ROBOENV_MODULE_PATH" "$ROBOTWIN_PYTHON" \
    -c 'from roboenv.cli.main import main; main()' "$@"
}

json_field() {
  local file="$1"
  local field="$2"
  python3 - "$file" "$field" <<'PY'
import json
import sys

value = json.load(open(sys.argv[1], encoding="utf-8"))
for part in sys.argv[2].split("."):
    value = value[part]
print(value)
PY
}

latest_session() {
  find "$SESSION_DATA" -type f -name '*.jsonl' -printf '%T@ %p\n' 2>/dev/null \
    | sort -nr | head -1 | cut -d' ' -f2-
}

