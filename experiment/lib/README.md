# Experiment trace finalization

Every Kinex experiment attempt is finalized into a durable raw trace and an
offline HTML report, regardless of native success, model failure or timeout.

Required run artifacts:

- `agent/events.jsonl`: raw Kinex JSON event stream;
- `agent/session.jsonl`: copied Kinex session when one was created;
- `harness-events.jsonl`: append-only online shadow events when the online
  recorder is enabled;
- `trace-manifest.json`: hashes, sizes, exit state and RoboTwin verdict;
- `trace.html`: self-contained offline visualization;
- `trace-render.log`: renderer output or a visible fallback reason.
- `harness-audit.json`: normalized execution receipts and separated outcome
  evidence when a Pi session was created;
- `harness-audit.log`: audit stdout/stderr for reproducibility.

Experiment launchers call `finalize_run.py` from an `EXIT` trap after stopping
RoboEnv so that terminal evidence is available. The finalizer never deletes or
rewrites raw trace files. If rendering fails or no model session starts, it
still emits a fallback HTML and manifest.

To backfill an existing run:

```bash
python3 experiment/lib/finalize_run.py --run-dir experiment/<name>/runs/<run>
```
