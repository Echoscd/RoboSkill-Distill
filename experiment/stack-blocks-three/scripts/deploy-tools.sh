#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/common.sh"

check_environment
TOOLBOX_CLI="$REPO_ROOT/toolbox/scripts/toolbox.py"
TARGET="$WORKSPACE/.kinex/tools"
MANIFEST="$TARGET/.toolbox-managed-tools"

require_file "$TOOLBOX_CLI"
mapfile -t requested_tools < <(sed -e 's/#.*$//' -e '/^[[:space:]]*$/d' "$TOOLSET_FILE")
PYTHONDONTWRITEBYTECODE=1 python3 "$TOOLBOX_CLI" validate --write-registry
if (( ${#requested_tools[@]} > 0 )); then
  mapfile -t tools < <(PYTHONDONTWRITEBYTECODE=1 python3 "$TOOLBOX_CLI" resolve --tools "${requested_tools[@]}")
else
  tools=()
fi

declare -A selected=()
for name in "${tools[@]}"; do
  selected["$name"]=1
done

if [[ -f "$MANIFEST" ]]; then
  while IFS= read -r previous; do
    [[ -n "$previous" ]] || continue
    [[ -z "${selected[$previous]+x}" ]] || continue
    stale="$(realpath -m "$TARGET/$previous")"
    target_root="$(realpath "$TARGET")"
    case "$stale" in
      "$target_root"/*)
        rm -rf -- "$stale"
        printf 'removed stale managed tool %s\n' "$previous"
        ;;
      *)
        printf 'Refusing to remove unexpected path: %s\n' "$stale" >&2
        exit 2
        ;;
    esac
  done <"$MANIFEST"
fi

if (( ${#requested_tools[@]} > 0 )); then
  PYTHONDONTWRITEBYTECODE=1 python3 "$TOOLBOX_CLI" install \
    --destination "$TARGET" --tools "${requested_tools[@]}"
else
  printf 'No custom toolbox tools selected for %s\n' "$ITERATION"
fi
printf '%s\n' "${tools[@]}" >"$MANIFEST"

