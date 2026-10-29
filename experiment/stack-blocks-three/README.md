# RoboTwin stack-blocks-three tool-distillation experiment

This experiment evaluates a Qwen learner on a three-stage ordered block stack,
then uses failed traces to formulate reusable GPT tools in the repository-level
`toolbox/`.

## Why this task

The task repeats the same perception-grasp-place-verification cycle for three
different objects, while placement accuracy and stack state become progressively
harder. It therefore rewards reusable primitives rather than one bottle-specific
macro.

## Layout

```text
stack-blocks-three/
├── iterations/<iter>/
│   ├── manifest.json   model, task, intent, and predecessor
│   ├── prompt.txt      immutable learner prompt
│   └── toolset.txt     toolbox tools visible in this iteration
├── scripts/            reproducible launch and run entry points
└── runs/<iter>/        generated traces and native evidence (gitignored)
```

`iter_000` is the Qwen0 control: its toolset is empty, so it receives only the
Kinex built-ins. Later iterations may select GPT-formulated tools, but those
tools remain owned and scored under `toolbox/tools/`.

## Current result

- `iter_000`: no custom tools; capability-search loop, no robot motion.
- `iter_001`: color localization succeeded; guessed joint targets failed.
- `iter_002`: generic grasp composition produced a real red-green stack; blue remained separate.
- `iter_003`: exact-orientation placement exposed an IK reachability gap.
- `iter_004`: yaw-search placement built the red-green stack precisely; cross-arm blue placement failed.
- `iter_005`: existing generic tools plus a support-buffer policy completed the three-block stack with RoboTwin `native_success=true`.

## Run

From the repository root:

```bash
KINEX_ITERATION=iter_000 \
  ./experiment/stack-blocks-three/scripts/reproduce-qwen.sh
```

The scripts use an isolated machine-local workspace at
`env/workspaces/stack-blocks-three`. Device profiles and the Python runtime are
shared by symlink with `env/workspace`, while active tools and recordings remain
isolated. This prevents tools from earlier tasks leaking into Qwen0.

