---
name: world
type: world
description: World clock and optional spatial reference.
---

## Use

`read()` returns `{time_s}`. `wait({duration_s})` waits in world time and returns
`{time_s, elapsed_s}`. Waits are concurrent and individually cancellable.
The driver abstracts the clock; callers do not select an execution mode.

Reads may include an optional episode budget, for example:
`{time_s: 42, budget: {elapsed_s: 2.5, max_s: 250}}`.
Budget values are seconds: `elapsed_s` is finite and nonnegative, and `max_s` is
finite and positive or `null` for no cap. Omit `budget` when it is unavailable.
Drivers own accounting and conversion from native counts to seconds; Kinex does
not infer budget values from `time_s` or enforce the allowance. Elapsed time may
exceed the allowance. Budget objects accept only `elapsed_s` and `max_s`; legacy
`used`, `max` and `unit` fields are rejected. Wait results carry no budget, and
their top-level `elapsed_s` describes that wait rather than the episode.

World geometry is optional. Bounds and posed surfaces are informational;
they do not constrain motion or imply transforms between disconnected frame trees.
Named frames are fixed; `null` live transforms are not supported on world.

## Setup

The supplied driver uses a real-world monotonic clock. Remote environments supply
their own driver. Configure access and load the device before read/wait.

```yaml
name: world
type: world
loaded: false
access:
  connection: {kind: process}
  driver:
    entry: driver.py
    persistent: true
    actions: [read, wait, load, unload, status]
intrinsics:
  source: unknown
  method: unknown
  calibrated_at: null
  frames: {}
  bounds: null
  surfaces: []
```

Bounds are `{min: [x,y,z], max: [x,y,z]}` in metres; null bounds impose no box,
null sides are open, and `???` means unresolved. Surfaces have a unique name,
world pose and rectangle, polygon or unbounded extent. Use only measured geometry.
