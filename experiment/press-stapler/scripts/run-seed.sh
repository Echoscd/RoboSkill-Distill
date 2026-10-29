#!/usr/bin/env bash
set -euo pipefail

SEED="${1:?usage: run-seed.sh SEED}"
[[ "$SEED" =~ ^[0-9]+$ ]] || { printf 'seed must be a non-negative integer: %s\n' "$SEED" >&2; exit 2; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
EXPERIMENT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd -- "$EXPERIMENT_DIR/../.." && pwd)"
RUNNER="$REPO_ROOT/experiment/stack-blocks-three/scripts/reproduce-qwen.sh"
PROMPT_FILE="$EXPERIMENT_DIR/seed-eval/prompt.txt"
TOOLSET_FILE="$EXPERIMENT_DIR/seed-eval/toolset.txt"
TASK_TEMPLATE="$EXPERIMENT_DIR/seed-eval/task-template.yaml"
TASK_DIR="$EXPERIMENT_DIR/seed-eval/generated-tasks"

for required in "$RUNNER" "$PROMPT_FILE" "$TOOLSET_FILE" "$TASK_TEMPLATE"; do
  [[ -f "$required" ]] || { printf 'missing required file: %s\n' "$required" >&2; exit 1; }
done

mkdir -p "$TASK_DIR" "$EXPERIMENT_DIR/runs/seed_${SEED}"
TASK_FILE="$TASK_DIR/press-stapler-seed${SEED}.yaml"
sed "s/{{SEED}}/$SEED/g" "$TASK_TEMPLATE" >"$TASK_FILE"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="$EXPERIMENT_DIR/runs/seed_${SEED}/${STAMP}_qwen3-vl-235b_seed${SEED}"
WORKSPACE="$REPO_ROOT/env/workspaces/press-stapler-seed-${SEED}"
mkdir -p "$RUN_DIR"

set +e
timeout --signal=INT --kill-after=60 900 \
  env KINEX_TASK_ID="$TASK_FILE" \
      KINEX_ITERATION="seed_eval_${SEED}" \
      KINEX_WORKSPACE="$WORKSPACE" \
      KINEX_EXPERIMENT_RUNS="$EXPERIMENT_DIR/runs/seed_${SEED}" \
      KINEX_EXPERIMENT_PROMPT="$PROMPT_FILE" \
      KINEX_TOOLSET_FILE="$TOOLSET_FILE" \
      KINEX_EXPERIMENT_TIMEOUT_S=240 \
      KINEX_AUTO_FORMULATE=0 \
      bash "$RUNNER" "$RUN_DIR" \
      >"$RUN_DIR/outer.log" 2>&1
STATUS=$?
set -e

printf 'seed=%s exit=%s run_dir=%s\n' "$SEED" "$STATUS" "$RUN_DIR"
exit "$STATUS"
