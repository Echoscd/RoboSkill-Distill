#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
EXPERIMENT_DIR="$(cd -- "${1:?usage: start-task.sh TASK_DIR [RUN_DIR]}" && pwd)"
ENV_ROOT="${KINEX_ENV_ROOT:-$REPO_ROOT/env}"
ITERATION=autonomous
RUN_DIR="${2:-$EXPERIMENT_DIR/runs/autonomous/$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$RUN_DIR"
RUN_DIR="$(cd -- "$RUN_DIR" && pwd)"

python3 "$REPO_ROOT/experiment/lib/render_agent_prompt.py" \
    --task "$EXPERIMENT_DIR/task.json" \
    --output "$RUN_DIR/input-prompt.txt" \
    --manifest "$RUN_DIR/prompt-provenance.json"

if [[ "${KINEX_DRY_RUN:-0}" == "1" ]]; then
    printf 'TASK_DIR=%s\nPROMPT=%s\nTOOLSET=%s\n' \
        "$EXPERIMENT_DIR" "$RUN_DIR/input-prompt.txt" "$REPO_ROOT/experiment/toolset.txt"
    exit 0
fi

mkdir -p "$RUN_DIR/tmp" "$RUN_DIR/private-data/agent/sessions"
mkdir -p "$RUN_DIR/private-config/agent"
cp "$ENV_ROOT/config/agent/models.json" "$RUN_DIR/private-config/agent/models.json"

env KINEX_TASK_DIR="$EXPERIMENT_DIR" \
    KINEX_TASK_ID="$EXPERIMENT_DIR/task.yaml" \
    KINEX_ITERATION="$ITERATION" \
    KINEX_EXPERIMENT_MODEL="${KINEX_EXPERIMENT_MODEL:-openrouter/qwen/qwen3.8-max-0902}" \
    KINEX_THINKING_LEVEL="${KINEX_THINKING_LEVEL:-low}" \
    KINEX_WORKSPACE="$RUN_DIR/workspace" \
    KINEX_DATA_DIR="$RUN_DIR/private-data" \
    KINEX_CONFIG_DIR="$RUN_DIR/private-config" \
    KINEX_SESSION_DATA="$RUN_DIR/private-data/agent/sessions" \
    TMPDIR="$RUN_DIR/tmp" \
    KINEX_EXPERIMENT_RUNS="$EXPERIMENT_DIR/runs/autonomous" \
    KINEX_EXPERIMENT_PROMPT="$RUN_DIR/input-prompt.txt" \
    KINEX_TOOLSET_FILE="$REPO_ROOT/experiment/toolset.txt" \
    KINEX_EXPERIMENT_TIMEOUT_S="${KINEX_EXPERIMENT_TIMEOUT_S:-600}" \
    KINEX_FAILURE_ANALYSIS_TIMEOUT_S="${KINEX_FAILURE_ANALYSIS_TIMEOUT_S:-360}" \
    KINEX_HARNESS_MODE=observe \
    KINEX_PC_PROXY_URL="${KINEX_PC_PROXY_URL:-http://192.168.224.140:18000}" \
    KINEX_RECORD_EXECUTION=1 \
    KINEX_AUTO_FORMULATE="${KINEX_AUTO_FORMULATE:-0}" \
    bash "$REPO_ROOT/experiment/runtime/run.sh" "$RUN_DIR"
