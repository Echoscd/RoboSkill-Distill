#!/usr/bin/env bash
# Keep the established entry point on the shared, autonomous prompt path.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/run-qwen38-autonomous.sh" "$@"
