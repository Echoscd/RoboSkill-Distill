# Kinex research harness

This package adds experiment contracts and policy checks around Kinex. It is not
a second robotics runtime: live tools, permissions, device scheduling and
recording remain owned by `@kinex/core`.

The first vertical slice defines four linked records:

1. `ObservationRef` identifies the exact RGB/depth observation, calibration,
   session and simulator generation used by later reasoning.
2. `Plan` binds motion stages to one or more observations, frames, uncertainty
   and an expiry time.
3. `ExecutionReceipt` keeps command acceptance, blocking completion and measured
   arrival separate.
4. `TaskVerdict` keeps the agent's claim, observable effect and RoboTwin native
   verdict separate.

`policies/gates.py` implements pure pre-dispatch and completion gates. The first
integration is deliberately offline: `tracing/audit_pi_session.py` audits an
existing Pi/Kinex session without moving a robot or exposing evaluator state to
the model.

`online/` provides the live `observe` mode used by new Qwen runs. It subscribes
to Kinex Core runtime/device events and appends `harness-events.jsonl` while the
run is active. It never removes tools, blocks actions or requires a particular
planning route. Unknown tool paths remain available and are preserved as raw
events.

Run the tests from the repository root:

```bash
python3 -m unittest discover -s experiment/harness/tests -v
```

Audit any retained run:

```bash
python3 -m experiment.harness.tracing.audit_pi_session \
  --run-dir experiment/press-stapler/runs/qwen38_autonomous/<run-id> \
  --semantic-target stapler \
  --output harness-audit.json
```

The audit normalizes evidence; it does not replace the simulator verdict or
infer unobserved physical contact. Historical records used by regression tests
are fixtures, not model context.

