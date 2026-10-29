#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)"
RUN_DIR="${1:?usage: launch.sh RUN_DIR}"
export KINEX_TASK_ID="$ROOT/experiment/press-stapler/task.yaml"
export KINEX_WORKSPACE="$RUN_DIR/launch-workspace"
export KINEX_EXPERIMENT_PROMPT="$ROOT/experiment/harness/online/smoke-read-only-prompt.txt"
export KINEX_TOOLSET_FILE="$ROOT/experiment/harness/online/smoke-read-only-toolset.txt"
export KINEX_RECORD_EXECUTION=1
bash "$ROOT/experiment/runtime/launch-simulator.sh" "$RUN_DIR"
