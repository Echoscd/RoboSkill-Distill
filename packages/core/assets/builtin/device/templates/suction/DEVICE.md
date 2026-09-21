---
name: suction
type: suction
description: suction control and observation contract.
---

## Use

Binary vacuum activation: write {target:[value]} accepts exactly the declared on_target/off_target. read reports only declared pressure/contact channels and measured state. Activation does not establish a successful grasp.

## Setup

Load initializes the connection and any owned control/streaming service, waiting
for readiness; status only observes. Unload stops active work according to the
profile and releases every owned resource, even if a cleanup stage fails. Follow
setup-device for service ownership, partial-startup rollback and exit cleanup.

Use setup-device for registration and driver lifecycle. Fill the starter with known facts; `???` marks unresolved values and `null` has the field’s declared meaning.

control declares mode:binary, distinct on_target/off_target. feedback declares positions (possibly empty), velocities, sensors, clock and aperture_model:null. stop declares behavior and affected_devices. Mount locates the suction TCP.

### Profile

```yaml
name: suction
type: suction
loaded: false
access:
  source: unknown
  method: unknown
  calibrated_at: null
  connection: ???
  driver:
    entry: driver.py
    actions:
    - read
    - write
    - stop
    - load
    - unload
    - status
    persistent: true
    timeout_s: 30
intrinsics:
  frames: {}
  source: unknown
  method: unknown
  calibrated_at: null
  control: ???
  feedback: ???
  stop: ???
extrinsics:
  source: unknown
  mount: ???
```
