# RoboTwin adjust-bottle experiment

This is the reproducible source for the successful Qwen3-VL-235B-A22B iter8
experiment. It intentionally does not contain interpreters, credentials or the
active Kinex workspace.

## Boundaries

| Content | Location |
| --- | --- |
| Experiment prompt, scripts and selected toolset | `experiment/adjust-bottle/` |
| Reusable tool source and metadata | `toolbox/tools/` |
| Generated run evidence | `experiment/adjust-bottle/runs/` |
| Kinex/RoboEnv installations and caches | `env/` |
| Active deployed tools and device profiles | `env/workspace/.kinex/` |
| OpenRouter key | `env/secrets/openrouter_api_key` |

`toolset.txt` selects four tools from the repository-level toolbox.
`scripts/deploy-tools.sh` validates the complete toolbox and installs this
experiment's selection, including declared lower-level dependencies, into the
active workspace before a run.

## One-command reproduction

From the repository root:

```bash
./experiment/adjust-bottle/scripts/reproduce-qwen.sh
```

The runner performs the following steps:

1. validates the machine-local environment;
2. deploys the four experiment tools to the Kinex workspace;
3. launches a fresh RoboTwin `adjust-bottle` environment;
4. reads `endpoint`, `session` and `generation` from the new `run.json`;
5. runs Qwen through Kinex with the saved prompt;
6. saves events, the complete session, logs and native RoboEnv evidence;
7. stops/finalizes the simulator.

Every run receives a new timestamped directory under `runs/`. Existing evidence
is never overwritten.

To select a custom output directory:

```bash
./experiment/adjust-bottle/scripts/reproduce-qwen.sh \
  /absolute/path/to/run-directory
```

To keep the simulator alive after the model exits for inspection:

```bash
KEEP_SIMULATOR=1 ./experiment/adjust-bottle/scripts/reproduce-qwen.sh
```

Then finalize it explicitly:

```bash
./experiment/adjust-bottle/scripts/stop-roboenv.sh \
  /path/to/run/roboenv/<session>/run.json
```

## Environment overrides

The scripts support these variables without committing machine-specific secrets:

- `KINEX_ENV_ROOT`
- `KINEX_WORKSPACE`
- `ROBOTWIN_PYTHON`
- `ROBOENV_ROOT`
- `OPENROUTER_KEY_FILE`
- `KINEX_EXPERIMENT_MODEL`
- `KINEX_PC_PROXY_URL`
- `KEEP_SIMULATOR`

The default model is `openrouter/qwen/qwen3-vl-235b-a22b-instruct`.

## Historical evidence

The original development iterations remain under `env/iterations/adjust-bottle/`
for provenance. They are not used by the new runner and should not be treated as
the experiment source tree.
