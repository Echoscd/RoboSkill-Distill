# Current work

`dev` is the long-lived integration branch for combined fixes. Its PR to `main`
collects those changes; individual fix branches integrate into `dev`.

- [x] Make servo submit full planned trajectories and report computed duration.
- [x] Expose optional `budget: {elapsed_s, max_s}` in seconds on world reads only.
- [x] Migrate callers and documentation; cover execution, interruption, budget
  validation and model-visible results with regression tests.
- [x] Validate the combined changes with typecheck, standalone tests and core tests.

Combined validation passed: typecheck, 53 standalone tests and 99 core tests.
Execution tests used mock devices and temporary Python drivers.

Servo returns immediately; physical arrival still requires measured feedback.
RoboEnv must report budget values already converted to seconds; Kinex does not
convert legacy count/unit budgets or enforce the allowance. Provider changes and
native plugin snapshots remain separate updates.
