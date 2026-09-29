# Current work

`dev` is the long-lived integration branch for combined fixes. Its PR to `main`
collects those changes; individual fix branches integrate into `dev`.

- [x] Make servo submit full planned trajectories and report computed duration.
- [x] Expose optional `budget: {elapsed_s, max_s}` in seconds on world reads only.
- [x] Migrate callers and documentation; cover execution, interruption, budget
  validation and model-visible results with regression tests.
- [x] Validate the combined changes with typecheck, standalone tests and core tests.
- [x] Move tool arguments, inline source and one-shot driver requests to stdin.
- [x] Cover large payloads, startup ordering, image references and interruption.
- [x] Normalize near-unit pose quaternions and frame estimates within 0.001;
  test boundaries, invalid inputs, IK, frame consumers and strict profile checks.
- [x] Trim agent-facing world usage to clock, budget and geometry essentials.
- [x] Build and pack the combined changes.

Combined validation passed: typecheck, 53 standalone tests and 115 core tests,
including 12 Python motion tests. Standalone/core build and local release
packaging also passed.
Execution tests used mock devices and temporary Python drivers.
Local runtime benchmarks showed no noticeable latency regression for 1 KiB and
32 KiB requests. Transport documentation stays in developer references; no new
model-facing instructions were added.

Servo returns immediately; physical arrival still requires measured feedback.
RoboEnv must report budget values already converted to seconds; Kinex does not
convert legacy count/unit budgets or enforce the allowance. Provider changes and
native plugin snapshots remain separate updates.
Custom Python tools/drivers reading request payloads from argv must migrate to
`kinex.args()` or `kinex.driver_protocol.run`; images remain file references.
