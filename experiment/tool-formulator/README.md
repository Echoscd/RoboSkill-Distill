# Kinex Tool Formulator

This directory bridges failed Qwen evaluations on the development server to Codex
running on a network-enabled workstation.

```text
failed finalized run
  -> queue.py enqueue (server)
  -> pending request directory
  -> watch-codex.ps1 polls over SSH (workstation)
  -> codex exec reads the project skill and edits the remote toolbox
  -> queue.py complete validates metadata, graph, registry, and tests
```

The formulator first diagnoses whether a reusable capability is missing. It is valid
and expected to return `no_tool` for strategy, prompt, runtime, or verification-use
failures. Tool deployment and evaluation are separate later stages.

## Server commands

```bash
python3 experiment/tool-formulator/scripts/queue.py enqueue \
  --run-dir experiment/robotwin-transfer-10/runs/press-stapler/<run> \
  --experiment robotwin-transfer-10/press-stapler \
  --iteration transfer_eval

python3 experiment/tool-formulator/scripts/queue.py pending --json
```

`reproduce-qwen.sh` enqueues a failed finalized run when
`KINEX_AUTO_FORMULATE=1`. Successful native runs are never enqueued.

## Workstation command

Run the PowerShell watcher on the workstation that has both the `drobotic` SSH alias
and a logged-in `codex` executable:

```powershell
powershell -ExecutionPolicy Bypass -File watch-codex.ps1
```

Use `-Once` to process the current queue and exit. The watcher claims each request
before invoking Codex, so a second watcher does not process the same request.

