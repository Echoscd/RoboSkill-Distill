# Toolbox agent rules

- Every GPT-formulated tool must live under `toolbox/tools/<name>` and include
  `tool.yaml`, `toolbook.yaml`, `tool.py`, `changes.jsonl`, and a valid
  `metadata.json`.
- Keep `tool.yaml` concise because it is exposed to the model. Put extended
  examples, frame conventions, failure diagnosis, recovery, and source links in
  `toolbook.yaml`, which is loaded only when needed.
- Document every runtime parameter again in `toolbook.yaml` at greater semantic
  depth: exact meaning, shape, unit, coordinate frame, authoritative data source,
  constraints, parameter relationships, and forbidden substitutions.
- Use symbolic placeholders in examples. Never publish plausible observation
  IDs, image paths, coordinates, depths, or device IDs that a model could copy
  into a live call.
- Record `generality.score` and `level.score` as integers from 1 through 10.
  Score the implementation that exists today, not the intended future tool.
- State concrete assumptions, limitations, provenance, and tested tasks. Never
  raise a generality score without new cross-task evidence.
- Prefer atomic, deterministic tools. Build complex behavior as a declared
  composition of lower-level tools.
- Every declared dependency must have a strictly lower level score. Do not
  introduce dependency cycles.
- Keep objective measurements separate from boolean predicates, and keep
  predicates separate from task success policies.
- Preserve raw measurements, units, coordinate frames, confidence, timestamp,
  and thresholds in outputs; do not return only a boolean verdict.
- Record every failed tool call in `failurebox`. Preserve the original call and
  error; add diagnosis and resolution later without rewriting the evidence.
- Append every modification to `changes.jsonl` with version, reason, files, and
  motivating failure IDs. A changed tool without a change-log entry is invalid.
- Run `python toolbox/scripts/toolbox.py validate --write-registry` and the
  toolbox tests after every tool or metadata change.

