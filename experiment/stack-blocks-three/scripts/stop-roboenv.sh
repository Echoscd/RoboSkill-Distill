#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/common.sh"

RUN_JSON="${1:?usage: stop-roboenv.sh RUN_JSON}"
require_file "$RUN_JSON"
roboenv_cli stop "$RUN_JSON" --json
