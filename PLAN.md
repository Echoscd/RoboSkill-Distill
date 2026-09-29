# Current work

Expose an optional episode budget in seconds on world reads on `dev`.

- [x] Validate optional `budget: {elapsed_s, max_s}` on reads only.
- [x] Verify model-visible results, validation and unchanged wait behavior.
- [x] Document the informational contract and driver-owned conversion to seconds.
- [x] Run typecheck, standalone tests and core tests sequentially.

Validation complete: typecheck passed, 53 standalone tests passed, and 97 core
tests passed. Runtime verification used temporary Python world drivers.

RoboEnv must report this seconds-based shape; its legacy count/unit budget is not
converted by Kinex. Provider changes and native plugin snapshots are separate.
