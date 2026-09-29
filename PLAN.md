# Current work

Make servo submit complete planned trajectories and report their computed duration.

- [x] Update the planner and servo API.
- [x] Migrate callers, documentation and calibration guidance.
- [x] Verify full-plan execution, limits, input rejection and interruption behavior.
- [x] Run typecheck, standalone tests and core tests sequentially.

Validation complete: typecheck passed, 53 standalone tests passed, and 95 core
tests passed (including six Python motion tests). Full-plan execution and
interruption were verified with mock devices; physical arrival still requires
measured feedback. Native plugin snapshots remain a separate update.
