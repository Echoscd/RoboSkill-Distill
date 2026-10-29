# Press stapler

`task.json` contains the model-visible goal. `task.yaml` selects RoboTwin seed 5.
The task uses the shared prompt and toolbox; no arm, tool sequence or motion
parameters are prescribed.

```bash
bash experiment/press-stapler/run.sh
```

This wrapper delegates to `experiment/runtime/start-task.sh`. Evidence is written
under `runs/`; older evidence is preserved in the external cleanup backup.
See [../README.md](../README.md) for setup, overrides and evaluation semantics.

