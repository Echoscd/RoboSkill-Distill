# Experiments

One shared pipeline runs every task. Task folders contain only a goal and simulator
configuration; the model chooses its own tools and actions.

## Run

```bash
bash experiment/runtime/start-task.sh experiment/press-stapler
bash experiment/runtime/start-task.sh experiment/click-bell
bash experiment/runtime/start-task.sh experiment/turn-switch
```

The default model is OpenRouter `qwen/qwen3.8-max-0902`. Set
`KINEX_EXPERIMENT_MODEL` to override it. Use `KINEX_DRY_RUN=1` to render and check
the task prompt without credentials, simulator launch, or model calls.

## Source map

- `runtime/`: shared environment setup, tool deployment, simulator lifecycle and model execution.
- `prompts/robot_agent.txt`: identical cross-task instruction.
- `toolset.txt`: shared active catalog; dependencies are resolved by the installer.
- `<task>/task.json`: task ID and goal only.
- `<task>/task.yaml`: evaluator-side scene, seed and budget.
- `harness/`: evidence contracts, observe-only ledger, stream safeguards and offline audit.
- `lib/`: native evaluator submission, video-first diagnosis, complete HTML export.
- `monitor/`: read-only live scene and trace dashboard.
- `tool-formulator/`: failure-to-tool request queue and workstation watcher.
- `device-check/`: deterministic simulator compatibility checks.
- `dependency-patches/`: pinned RoboEnv/RoboTwin revisions and required patches.
- `protocols/`: supervisor-only research rules and known limitations.
- `archive-index.json`: cleanup scope, backup verification and historical path mapping.

## Local prerequisites

Keep installations, model weights and credentials under `env/`, outside Git:
`env/source`, `env/RoboEnv`, `env/node/current`, `env/workspace`,
`env/config/agent/models.json`, and `env/secrets/openrouter_api_key`.
The shared runtime retains deployment defaults in `runtime/common.sh`; override
`KINEX_ENV_ROOT`, `ROBOTWIN_PYTHON`, `ROBOENV_ROOT`,
`ROBOENV_PYTHON_PATH` and `KINEX_PC_PROXY_URL` for another machine.
Apply the pinned dependency patches before using the custom recording/evaluation behavior.

## Evidence and evaluation

Every attempt retains raw model input/output, tool calls/results, simulator
recordings, native verdict, audit, manifest and HTML under `<task>/runs/`.
Run artifacts are ignored by Git. Success, failure and timeout all require
finalization; see [lib/README.md](lib/README.md).

The model requests evaluation; the supervisor records the native simulator label.
A failed evaluation triggers read-only video diagnosis. The ledger never requires
a chosen tool or motion recipe. It provides no filesystem isolation boundary.
The active toolbox is inherited experimental knowledge, not a no-tool baseline.

The stapler benchmark's current native criterion checks contact with a static
actor; it does not prove full compression. TCP-origin contact planning still lacks
calibrated physical finger/pad geometry. Keep those limitations explicit.

## Checks

```bash
python3 toolbox/scripts/toolbox.py validate --write-registry
python3 -m unittest discover -s toolbox/tests
python3 -m unittest discover -s experiment/runtime/tests
python3 -m unittest discover -s experiment/lib/tests
python3 -m unittest discover -s experiment/harness/tests
node --test experiment/harness/online/test/*.test.mjs
```

Old prescribed prompts, abandoned task launchers and inactive tools are removed
from the active tree. Complete historical evidence is recoverable from the
external backup and pre-cleanup Git commit recorded in `archive-index.json`.
