# RoboTwin ten-task toolbox transfer evaluation

This experiment tests whether the toolbox distilled on `adjust-bottle` and
`stack-blocks-three` transfers to ten previously unseen RoboTwin tasks. Every
task uses seed 0, the same Qwen3-VL-235B-A22B model, a fresh isolated Kinex
workspace, and the same toolbox snapshot.

The batch is intentionally an evaluation pass. It does not create task-specific
tools while an episode is running. Each failure remains a complete trace for a
subsequent GPT diagnosis and reusable-tool decision.

Generated data is stored under `runs/<task-slug>/<timestamp>/`. `status.tsv`
records start/end time, process status, and RoboTwin native success. The full
agent event stream, session, camera observations, commands, and native episode
evidence remain inside each run directory.

Run from the repository root:

```bash
nohup bash experiment/robotwin-transfer-10/scripts/run-batch.sh \
  >experiment/robotwin-transfer-10/batch.log 2>&1 </dev/null &
```

Monitor with:

```bash
bash experiment/robotwin-transfer-10/scripts/status.sh
```
