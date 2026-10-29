# Research harness rules

- This package is an experiment-side observer and policy layer. It must not
  reimplement Kinex tool dispatch, permissions, device lifecycle, scheduling or
  recording.
- All live device actions continue through `@kinex/core`. Harness code may
  validate a request before dispatch and normalize evidence after dispatch.
- Keep agent-visible evidence separate from evaluator-only evidence. RoboTwin
  hidden state and `native_success` must not enter model context unless the
  benchmark explicitly permits it.
- Treat command acceptance, controller completion, measured arrival, physical
  effect and task success as separate facts. Unknown facts stay `None`.
- Bind plans to explicit observation, session and simulator-generation IDs.
  Reject stale or cross-session plans before motion.
- Trace audit code is read-only. It may create derived reports but must never
  rewrite raw JSONL evidence.

