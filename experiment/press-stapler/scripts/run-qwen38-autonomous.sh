#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
EXPERIMENT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd -- "$EXPERIMENT_DIR/../.." && pwd)"
ITERATION=qwen38_autonomous
ITERATION_DIR="$EXPERIMENT_DIR/iterations/$ITERATION"
RUN_DIR="${1:-$EXPERIMENT_DIR/runs/qwen38_autonomous/$(date -u +%Y%m%dT%H%M%SZ)_seed5}"
mkdir -p "$RUN_DIR"
mkdir -p "$RUN_DIR/tmp" "$RUN_DIR/private-data/agent/sessions"
mkdir -p "$RUN_DIR/private-config/agent"
cp "$REPO_ROOT/env/config/agent/models.json" "$RUN_DIR/private-config/agent/models.json"

python3 "$REPO_ROOT/experiment/lib/render_agent_prompt.py" \
    --task "$ITERATION_DIR/task.json" \
    --output "$RUN_DIR/input-prompt.txt" \
    --manifest "$RUN_DIR/prompt-provenance.json"

env KINEX_TASK_ID="$EXPERIMENT_DIR/seed-eval/generated-tasks/press-stapler-seed5.yaml" \
    KINEX_ITERATION="$ITERATION" \
    KINEX_EXPERIMENT_MODEL=openrouter/qwen/qwen3.8-max-0902 \
    KINEX_THINKING_LEVEL=low \
    KINEX_WORKSPACE="$RUN_DIR/workspace" \
    KINEX_DATA_DIR="$RUN_DIR/private-data" \
    KINEX_CONFIG_DIR="$RUN_DIR/private-config" \
    KINEX_SESSION_DATA="$RUN_DIR/private-data/agent/sessions" \
    TMPDIR="$RUN_DIR/tmp" \
    KINEX_EXPERIMENT_RUNS="$EXPERIMENT_DIR/runs/qwen38_autonomous" \
    KINEX_EXPERIMENT_PROMPT="$RUN_DIR/input-prompt.txt" \
    KINEX_TOOLSET_FILE="$ITERATION_DIR/toolset.txt" \
    KINEX_EXPERIMENT_TIMEOUT_S=600 \
    KINEX_FAILURE_ANALYSIS_TIMEOUT_S=360 \
    KINEX_HARNESS_MODE=observe \
    KINEX_PC_PROXY_URL="${KINEX_PC_PROXY_URL:-http://192.168.224.140:18000}" \
    KINEX_RECORD_EXECUTION=1 \
    KINEX_AUTO_FORMULATE=0 \
    bash "$REPO_ROOT/experiment/stack-blocks-three/scripts/reproduce-qwen.sh" "$RUN_DIR"
