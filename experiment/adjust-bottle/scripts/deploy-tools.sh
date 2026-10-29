#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/common.sh"

TOOLBOX_CLI="$REPO_ROOT/toolbox/scripts/toolbox.py"
TOOLSET="$EXPERIMENT_DIR/toolset.txt"
TARGET="$WORKSPACE/.kinex/tools"

require_file "$TOOLBOX_CLI"
require_file "$TOOLSET"
mkdir -p "$TARGET"

mapfile -t tools < <(sed -e 's/#.*$//' -e '/^[[:space:]]*$/d' "$TOOLSET")
(( ${#tools[@]} > 0 )) || { printf 'Toolset is empty: %s\n' "$TOOLSET" >&2; exit 1; }

python3 "$TOOLBOX_CLI" validate --write-registry
python3 "$TOOLBOX_CLI" install --destination "$TARGET" --tools "${tools[@]}"
