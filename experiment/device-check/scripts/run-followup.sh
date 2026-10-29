#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)"
RUN_DIR="${1:?usage: run-followup.sh RUN_DIR}"
bash "$ROOT/experiment/device-check/scripts/launch.sh" "$RUN_DIR"
export KINEX_CONFIG_DIR="$ROOT/env/config"
export KINEX_DATA_DIR="$ROOT/env/data"
export UV_CACHE_DIR="$ROOT/env/cache/uv"
export XDG_CACHE_HOME="$RUN_DIR/cache"
export PATH="$ROOT/env/node/current/bin:$PATH"
node "$ROOT/experiment/device-check/scripts/check-native.mjs" "$RUN_DIR" followup
