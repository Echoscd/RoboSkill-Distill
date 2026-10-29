#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO="${KINEX_REPO:-$(cd -- "$HERE/../.." && pwd)}"
WORKSPACE="${KINEX_WORKSPACE:-$REPO/env/workspace}"
ITERATIONS_ROOT="${KINEX_ITERATIONS_ROOT:-$REPO/experiment}"

exec python3 "$HERE/monitor.py" \
  --repo "$REPO" \
  --workspace "$WORKSPACE" \
  --iterations-root "$ITERATIONS_ROOT" \
  "$@"
