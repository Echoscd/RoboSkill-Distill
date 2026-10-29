# Kinex experiments

This directory contains reproducible experiment source. Runtime environments and
credentials stay outside it.

## Layout

```text
experiment/
├── harness/          contracts, policy gates and read-only trace audits
├── lib/              mandatory trace finalization and offline HTML renderer
├── adjust-bottle/
│   ├── prompts/       versioned model prompts
│   ├── scripts/       launch, run, stop and reproduction entry points
│   ├── toolset.txt    toolbox tools selected for this experiment
│   └── runs/          generated traces and RoboEnv evidence (gitignored)
└── monitor/           read-only live run dashboard
```

The separation is intentional:

- `env/` owns installed interpreters, RoboEnv sources, the active Kinex workspace,
  secrets, caches and other machine-local runtime state.
- `toolbox/` owns scored, reusable tool source and dependency metadata.
- `experiment/harness/` supervises experiments without reimplementing Kinex Core;
  it owns observation, plan, execution-receipt and task-verdict contracts.
- `experiment/` owns prompts, selected toolsets and reproducible launch scripts.
- `experiment/*/runs/` owns generated results. These files are retained locally
  but are not committed by default.

Historical runs under `env/iterations/` are kept as immutable legacy evidence.
New experiments must write to `experiment/<name>/runs/`.

Every attempted run, including failures and timeouts, must be finalized by
`experiment/lib/finalize_run.py`. A run is not considered archived until it has
the raw JSONL trace, `trace-manifest.json`, `trace.html` and
`trace-render.log`. See [`lib/README.md`](lib/README.md) for the contract and
backfill command.

See [`adjust-bottle/README.md`](adjust-bottle/README.md) for the Qwen baseline and
[`monitor/README.md`](monitor/README.md) for live supervision. The current
tool-distillation study is documented in
[`stack-blocks-three/README.md`](stack-blocks-three/README.md).
