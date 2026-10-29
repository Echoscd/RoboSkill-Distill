# Online shadow recorder

The online recorder attaches to the existing Kinex runtime and appends one JSON
object per line while a run is active. It is deliberately observational:

- it does not remove or replace tools;
- it does not reject motion;
- it does not require a plan before an action;
- unknown tools and new control strategies remain usable and are retained as
  `model_tool` events with no derived classification.

Device events come from `KinexRuntime.subscribe()`, so actions issued inside
Python or composite tools are visible without matching hard-coded tool names.
Device profile types distinguish camera/model observations from actuator writes.
Toolbox metadata supplies optional planning/verification annotations. Missing
metadata never blocks a call.

`harness-events.jsonl` is the live append-only stream. The ordinary Kinex session
remains the source of full model messages and tool payloads, and the finalizer
adds evaluator-only evidence separately after the simulator stops.

Run `smoke-read-only.sh` to launch the RoboTwin press-stapler scene, ask the
agent for exactly one `head_camera` read, finalize all artifacts, and validate
that observation events were recorded without any actuator writes. This is an
integration test for the recorder, not a task-success evaluation.

