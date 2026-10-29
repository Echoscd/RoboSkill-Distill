#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../../.." && pwd)"
KINEX_ENV_ROOT="${KINEX_ENV_ROOT:-$REPO_ROOT/env}"
PC_PROXY_URL="${KINEX_PC_PROXY_URL:-http://127.0.0.1:18080}"

export PATH="$KINEX_ENV_ROOT/node/current/bin:$PATH"
export npm_config_cache="$KINEX_ENV_ROOT/cache/npm"
export npm_config_prefix="$KINEX_ENV_ROOT/npm-prefix"
export KINEX_CONFIG_DIR="${KINEX_CONFIG_DIR:-$KINEX_ENV_ROOT/config}"
export KINEX_DATA_DIR="${KINEX_DATA_DIR:-$KINEX_ENV_ROOT/data}"
export XDG_CACHE_HOME="$KINEX_ENV_ROOT/cache"
export UV_CACHE_DIR="$KINEX_ENV_ROOT/cache/uv"
export http_proxy="$PC_PROXY_URL"
export https_proxy="$PC_PROXY_URL"
export HTTP_PROXY="$PC_PROXY_URL"
export HTTPS_PROXY="$PC_PROXY_URL"
export no_proxy="localhost,127.0.0.1,::1,.local,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,ivolces.com,volces.com"
export NO_PROXY="$no_proxy"
export NODE_OPTIONS="${NODE_OPTIONS:+$NODE_OPTIONS }--require=$KINEX_ENV_ROOT/config/kinex-env-proxy.cjs"

exec node "$SCRIPT_DIR/run-agent.mjs" --source-root "$KINEX_ENV_ROOT/source" "$@"

