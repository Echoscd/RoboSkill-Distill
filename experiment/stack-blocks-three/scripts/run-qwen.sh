#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/common.sh"

RUN_JSON="${1:?usage: run-qwen.sh RUN_JSON [RUN_DIR]}"
RUN_DIR="${2:-$(cd -- "$(dirname -- "$RUN_JSON")/../.." && pwd)}"
OUT="$RUN_DIR/agent"
mkdir -p "$OUT"

check_environment
require_file "$RUN_JSON"
cp "$PROMPT_FILE" "$OUT/prompt.txt"

before="$(latest_session || true)"
export OPENROUTER_API_KEY="$(tr -d '\r\n' <"$KEY_FILE")"
export KINEX_PC_PROXY_URL="$PC_PROXY_URL"
export ROBOENV_ENDPOINT="$(json_field "$RUN_JSON" endpoint)"
export ROBOENV_SESSION="$(json_field "$RUN_JSON" session)"
export ROBOENV_GENERATION="$(json_field "$RUN_JSON" generation)"

cd "$WORKSPACE"
started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf 'Starting %s against %s\n' "$MODEL" "$ROBOENV_SESSION"
set +e
ONLINE_RUNNER="$REPO_ROOT/experiment/harness/online/run-agent.sh"
if [[ "${KINEX_ONLINE_HARNESS:-1}" == "1" && -x "$ONLINE_RUNNER" ]]; then
  timeout --signal=INT --kill-after=30 "$MAX_SECONDS" "$ONLINE_RUNNER" \
    --model "$MODEL" \
    --prompt-file "$OUT/prompt.txt" \
    --events-file "$RUN_DIR/harness-events.jsonl" \
    </dev/null \
    >"$OUT/events.jsonl" \
    2>"$OUT/stderr.log"
else
  timeout --signal=INT --kill-after=30 "$MAX_SECONDS" "$KINEX_BIN" \
    --yolo \
    --mode json \
    --model "$MODEL" \
    -p "$(cat "$OUT/prompt.txt")" \
    </dev/null \
    >"$OUT/events.jsonl" \
    2>"$OUT/stderr.log"
fi
status=$?
set -e
ended="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
after="$(latest_session || true)"

if [[ -n "$after" && "$after" != "$before" ]]; then
  cp "$after" "$OUT/session.jsonl"
  cp "$after" "$OUT/primary-session.jsonl"
  printf '%s\n' "$after" >"$OUT/session-source.txt"
fi

evaluation_status="not_submitted"
analysis_status="not_requested"
set +e
PYTHONPATH="$ROBOENV_MODULE_PATH" "$ROBOTWIN_PYTHON" \
  "$REPO_ROOT/experiment/lib/submit_simulator.py" \
  --run "$RUN_JSON" \
  --output "$RUN_DIR/simulator-verdict.json" \
  >"$RUN_DIR/simulator-submit.log" 2>"$RUN_DIR/simulator-submit.stderr.log"
submit_status=$?
set -e
evaluation_status="exit_${submit_status}"

if [[ "$submit_status" == "0" && "${KINEX_FAILURE_ANALYSIS:-1}" == "1" ]]; then
  decision="$RUN_DIR/failure-analysis-decision.json"
  analysis_prompt="$OUT/failure-analysis-prompt.txt"
  if python3 "$REPO_ROOT/experiment/lib/prepare_failure_analysis.py" \
    --verdict "$RUN_DIR/simulator-verdict.json" \
    --run-dir "$RUN_DIR" \
    --decision "$decision" \
    --prompt "$analysis_prompt"; then
    before_analysis="$(latest_session || true)"
    set +e
    KINEX_HARNESS_MODE=observe KINEX_DIAGNOSTIC_RUN_DIR="$RUN_DIR" timeout --signal=INT --kill-after=20 \
      "${KINEX_FAILURE_ANALYSIS_TIMEOUT_S:-180}" "$ONLINE_RUNNER" \
      --model "$MODEL" \
      --prompt-file "$analysis_prompt" \
      --events-file "$RUN_DIR/failure-analysis-harness-events.jsonl" \
      </dev/null \
      >"$OUT/failure-analysis-events.jsonl" \
      2>"$OUT/failure-analysis-stderr.log"
    analysis_status=$?
    set -e
    after_analysis="$(latest_session || true)"
    if [[ -n "$after_analysis" && "$after_analysis" != "$before_analysis" ]]; then
      cp "$after_analysis" "$OUT/failure-analysis-session.jsonl"
      printf '%s\n' "$after_analysis" >"$OUT/failure-analysis-session-source.txt"
      if [[ -f "$OUT/primary-session.jsonl" ]]; then
        cat "$OUT/primary-session.jsonl" "$OUT/failure-analysis-session.jsonl" >"$OUT/session.jsonl"
      else
        cp "$OUT/failure-analysis-session.jsonl" "$OUT/session.jsonl"
      fi
    fi
  else
    decision_status=$?
    [[ "$decision_status" == "10" ]] || analysis_status="decision_error_${decision_status}"
  fi
fi

printf 'started=%s\nended=%s\nexit_code=%s\nsession=%s\nmodel=%s\niteration=%s\ntask=%s\nsimulator_evaluation=%s\nfailure_analysis=%s\n' \
  "$started" "$ended" "$status" "$after" "$MODEL" "$ITERATION" "$TASK_ID" "$evaluation_status" "$analysis_status" >"$OUT/run-state.txt"
printf 'Agent exit code: %s\nArtifacts: %s\n' "$status" "$OUT"
exit "$status"
