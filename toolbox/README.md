# Kinex Toolbox

This directory is the source of truth for reusable tools formulated during
agent experiments. A tool is either:

- **atomic**: one narrowly scoped observation, transform, predicate, or action;
- **composite**: a higher-level capability assembled from lower-level tools.

Every tool must carry `metadata.json`. The metadata records two independent
scores:

- `generality.score` (1-10): how readily the tool transfers to other tasks;
- `level.score` (1-10): how much behavior the tool composes. Higher-level
  tools may depend only on tools with lower level scores.

The scores describe the current implementation, not the ambition implied by
the tool name. They must be backed by explicit assumptions and evaluation
evidence.

## Layout

```text
toolbox/
├── tools/<tool-name>/
│   ├── tool.py             # Kinex executable entry point
│   ├── tool.yaml           # concise Kinex runtime contract exposed to the model
│   ├── toolbook.yaml       # on-demand usage, examples, failures, recovery, source map
│   ├── changes.jsonl       # append-only modification history
│   └── metadata.json       # Toolbox provenance and scores
├── failurebox/
│   ├── events/*.json       # failed calls, trace links, diagnosis, and resolution
│   └── index.json          # generated failure summary
├── combos/                 # Declarative compositions (added as they mature)
├── schemas/                # Machine-readable metadata contracts
├── scripts/toolbox.py      # Validate, list, graph, scaffold, and install
├── tests/                  # Registry invariants
├── registry.json           # Generated summary; do not hand edit
└── SCORING.md              # Scoring rubric
```

## Required workflow for a GPT-formulated tool

1. Prefer the smallest reusable capability that closes the observed gap.
2. Run `python toolbox/scripts/toolbox.py new ...` to create the tool skeleton.
3. Implement the concise `tool.yaml` interface, then the detailed
   `toolbook.yaml` and source. Do not put long recovery prose in the runtime
   description.
4. Fill in concrete generality assumptions, limitations, and provenance.
5. For a composite, declare every toolbox dependency. Dependencies must have a
   lower `level.score`.
6. Add deterministic tests or replay evidence.
7. Append a `changes.jsonl` entry explaining what changed and why. Reference
   every failurebox event that motivated the change.
8. Run `python toolbox/scripts/toolbox.py validate --write-registry`.
9. Only then expose the tool to an agent or install it into a workspace.

## Commands

From the repository root:

```bash
python toolbox/scripts/toolbox.py validate --write-registry
python toolbox/scripts/toolbox.py list
python toolbox/scripts/toolbox.py graph --format mermaid
python toolbox/scripts/toolbox.py install --destination env/workspace/.kinex/tools
python toolbox/scripts/toolbox.py record-failure --help
python toolbox/scripts/toolbox.py log-change --help
```

Create a new atomic tool:

```bash
python toolbox/scripts/toolbox.py new measure_support_gap \
  --type atomic --generality 8 --level 3 \
  --summary "Measure the metric gap between an object and a support surface"
```

Create a composite tool:

```bash
python toolbox/scripts/toolbox.py new verify_grasp \
  --type composite --generality 8 --level 6 \
  --depends-on measure_support_gap measure_object_ee_distance \
  --summary "Combine independent evidence into a grasp verdict"
```

The installer validates the complete toolbox before copying runtime files. It
installs `tool.yaml`, `toolbook.yaml`, the entrypoint, and implementation source
so a model can inspect them after failure. It does not install `metadata.json`,
`changes.jsonl`, tests, or experiment records into the runtime directory.

## Runtime and diagnostic layers

`tool.yaml` is the single executable source of truth. Its `parameters` field is
JSON Schema and is adapted to each model provider at runtime. Keep its name,
description, parameter definitions, output schema, annotations, device gates,
entrypoint, and timeout concise.

`toolbook.yaml` is not injected into every model turn. The runtime points the
agent to it after a failed call. It contains a deep reference for every parameter
(meaning, format, unit, frame, source, constraints, and forbidden uses), return
semantics, examples with symbolic placeholders, prerequisites, known failures,
recovery steps, and the source/test map.

`failurebox` records failed invocations; `changes.jsonl` records modifications.
Together they provide the causal chain `failed call -> diagnosis -> tool change
-> new version -> evaluation evidence`. Runtime recording redacts credential-like
fields and stores large media only by reference.

