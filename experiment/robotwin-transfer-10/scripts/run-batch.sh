#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
EXPERIMENT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd -- "$EXPERIMENT_DIR/../.." && pwd)"
TASKS_FILE="$EXPERIMENT_DIR/tasks.tsv"
TOOLSET_FILE="$EXPERIMENT_DIR/toolset.txt"
PROMPT_TEMPLATE="$EXPERIMENT_DIR/prompt-template.txt"
STATUS_FILE="$EXPERIMENT_DIR/status.tsv"
RUNNER="$REPO_ROOT/experiment/stack-blocks-three/scripts/reproduce-qwen.sh"
MAX_SECONDS="${KINEX_EXPERIMENT_TIMEOUT_S:-900}"

for required in "$TASKS_FILE" "$TOOLSET_FILE" "$PROMPT_TEMPLATE" "$RUNNER"; do
  [[ -f "$required" ]] || { printf 'missing required file: %s\n' "$required" >&2; exit 1; }
done

mkdir -p "$EXPERIMENT_DIR/runs" "$EXPERIMENT_DIR/generated-prompts"
if [[ ! -f "$STATUS_FILE" ]]; then
  printf 'slug\ttask_id\tstarted_utc\tended_utc\texit_code\tnative_success\trun_dir\n' >"$STATUS_FILE"
fi

while IFS=$'\t' read -r slug task_id goal; do
  [[ -n "$slug" && -n "$task_id" && -n "$goal" ]] || continue
  if awk -F '\t' -v slug="$slug" 'NR > 1 && $1 == slug {found=1} END {exit !found}' "$STATUS_FILE"; then
    printf 'Skipping already recorded task: %s\n' "$slug"
    continue
  fi

  prompt="$EXPERIMENT_DIR/generated-prompts/$slug.txt"
  sed -e "s|{{TASK_ID}}|$task_id|g" -e "s|{{GOAL}}|$goal|g" "$PROMPT_TEMPLATE" >"$prompt"
  started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  run_dir="$EXPERIMENT_DIR/runs/$slug/${stamp}_qwen3-vl-235b_seed0"
  workspace="$REPO_ROOT/env/workspaces/robotwin-transfer-10/$slug"
  mkdir -p "$run_dir"

  printf '=== START %s (%s) at %s ===\n' "$slug" "$task_id" "$started"
  set +e
  timeout --signal=INT --kill-after=60 1100 \
    env KINEX_TASK_ID="$task_id" \
        KINEX_ITERATION="transfer_eval" \
        KINEX_WORKSPACE="$workspace" \
        KINEX_EXPERIMENT_RUNS="$EXPERIMENT_DIR/runs/$slug" \
        KINEX_EXPERIMENT_PROMPT="$prompt" \
        KINEX_TOOLSET_FILE="$TOOLSET_FILE" \
        KINEX_EXPERIMENT_TIMEOUT_S="$MAX_SECONDS" \
        KINEX_AUTO_FORMULATE="${KINEX_AUTO_FORMULATE:-1}" \
        KINEX_FORMULATOR_EXPERIMENT="robotwin-transfer-10/$slug" \
        bash "$RUNNER" "$run_dir" \
        >"$run_dir/driver.log" 2>&1
  exit_code=$?
  set -e

  ended="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  native_success="missing"
  native_episode="$(find "$run_dir" -type f -name native-episode.json -print -quit 2>/dev/null || true)"
  if [[ -n "$native_episode" ]]; then
    native_success="$(python3 - "$native_episode" <<'PY'
import json
import sys
print(str(bool(json.load(open(sys.argv[1], encoding="utf-8")).get("native_success"))).lower())
PY
)"
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$slug" "$task_id" "$started" "$ended" "$exit_code" "$native_success" "$run_dir" >>"$STATUS_FILE"
  printf '=== END %s exit=%s native_success=%s at %s ===\n' "$slug" "$exit_code" "$native_success" "$ended"
done <"$TASKS_FILE"

printf 'Batch complete: %s\n' "$STATUS_FILE"
