# Failurebox

`failurebox` is the append-only history of failed tool calls. It records what
was called, the runtime error, the trace that contains the surrounding scene,
the later diagnosis, and the tool revision that resolved it.

Runtime failures are written automatically. Set `KINEX_FAILUREBOX_DIR` to this
directory when Kinex runs outside the repository root. Without that variable,
Kinex writes to `toolbox/failurebox` when present, otherwise to
`.kinex/failurebox` in the active workspace.

## Layout

```text
failurebox/
├── events/<failure-id>.json  # one immutable event per failed call
├── index.json                # generated summary; do not hand edit
└── README.md
```

Large images, videos, and traces are referenced by path; they are not copied
into the event. Credentials are redacted by the runtime recorder. Diagnosis and
resolution fields may be updated after analysis, but the original call and
error fields remain unchanged.

Record an externally observed failure:

```bash
python toolbox/scripts/toolbox.py record-failure \
  --tool plan_linear_contact --stage runtime --code IK_UNREACHABLE \
  --message "No IK solution for the contact stage" \
  --arguments '{"arm":"right_arm"}' --run-id seed5 \
  --trace-ref outputs/qwen_press_stapler_seed5_trace.html
```

When a failure drives a change, include its ID in the tool change log:

```bash
python toolbox/scripts/toolbox.py log-change \
  --tool plan_linear_contact --version 0.3.0 --author joint \
  --change-type fix --summary "Validate contact frame before IK" \
  --reason "Camera-frame points were accepted as world coordinates" \
  --failure-id failure_20261029_0001 --file tool.py --file tool.yaml
```
