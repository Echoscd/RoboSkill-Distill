#!/usr/bin/env bash

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
EXPERIMENT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd -- "$EXPERIMENT_DIR/../.." && pwd)"

ENV_ROOT="${KINEX_ENV_ROOT:-$REPO_ROOT/env}"
WORKSPACE="${KINEX_WORKSPACE:-$ENV_ROOT/workspace}"
RUNS_DIR="${KINEX_EXPERIMENT_RUNS:-$EXPERIMENT_DIR/runs}"
PROMPT_FILE="${KINEX_EXPERIMENT_PROMPT:-$EXPERIMENT_DIR/prompts/full-task.txt}"
KEY_FILE="${OPENROUTER_KEY_FILE:-$ENV_ROOT/secrets/openrouter_api_key}"
SESSION_DATA="${KINEX_SESSION_DATA:-$ENV_ROOT/data/agent/sessions}"
KINEX_BIN="${KINEX_BIN:-$ENV_ROOT/bin/kinex-via-pc}"

ROBOENV_ROOT="${ROBOENV_ROOT:-$ENV_ROOT/RoboEnv}"
ROBOTWIN_PYTHON="${ROBOTWIN_PYTHON:-/LargeModelDev/users/chendong.song/env/robotwin/bin/python}"
ROBOENV_PYTHON_PATH="${ROBOENV_PYTHON_PATH:-$ROBOENV_ROOT/combined-pythonpath}"
ROBOENV_MODULE_PATH="${ROBOENV_MODULE_PATH:-$ROBOENV_ROOT/runtime/src:$ROBOENV_ROOT/src}"

MODEL="${KINEX_EXPERIMENT_MODEL:-openrouter/qwen/qwen3-vl-235b-a22b-instruct}"
PC_PROXY_URL="${KINEX_PC_PROXY_URL:-http://192.168.224.140:18000}"

require_file() {
  [[ -f "$1" ]] || { printf 'Required file is missing: %s\n' "$1" >&2; return 1; }
}

require_executable() {
  [[ -x "$1" ]] || { printf 'Required executable is missing: %s\n' "$1" >&2; return 1; }
}

check_environment() {
  require_executable "$ROBOTWIN_PYTHON"
  require_executable "$KINEX_BIN"
  require_file "$KEY_FILE"
  require_file "$PROMPT_FILE"
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
