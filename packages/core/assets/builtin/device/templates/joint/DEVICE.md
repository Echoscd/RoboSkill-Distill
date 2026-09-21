---
name: joint
type: joint
description: joint control and observation contract.
---

## Use

write {target:[...],speedFraction?} replaces absolute joint-position goals in model order (rad for rotary, m for prismatic joints). Acceptance is not arrival. read reports positions, optional velocities/efforts ([] when unsupported), faults, acquisition time, and declared frame_poses. servo_to settles a joint device; dexterous_hand is excluded. track submits joint policy targets. Optional fk/ik operate without motion; pose goals refer to kinematics.frame in the canonical device frame. Convert reference frames and TCP offsets before solving.

## Setup

Load initializes the connection and any owned control/streaming service, waiting
for readiness; status only observes. Unload stops active work according to the
profile and releases every owned resource, even if a cleanup stage fails. Follow
setup-device for service ownership, partial-startup rollback and exit cleanup.

Use setup-device for registration and driver lifecycle. Fill the starter with known facts; `???` marks unresolved values and `null` has the field’s declared meaning.

intrinsics.model is {format:joints,joints:[...]} for arbitrary joint sets, {format:serial_chain,joints,chain}, or {format:urdf,path,base_link,tip_link}. Each joint declares name, type (revolute/continuous/prismatic), limits (null only for continuous), max_velocity and max_effort (nullable). Geometry is optional.

kinematics:null needs no solver. Otherwise declare frame, fk (numerical/driver/null), ik (numerical DLS/driver/null), feedback (driver/fk), and frame_to_reported. Driver IK supplies frame_to_solver and residual tolerances. Declare the tip under intrinsics.frames. Numerical solvers require a serial model; IK requires FK verification.

control declares mode:position, speed (null or named max_velocity and default_fraction), execution (realtime with command_timeout_s, or stepped with interval_s). home names every joint or is null. feedback declares velocities, efforts and clock (unix/monotonic/simulation). stop declares behavior and affected_devices. intrinsics.frames maps local names to fixed poses or null for read.frame_poses feedback. extrinsics supplies only a mount or measured pose_frame.

### Profile

```yaml
name: joint
type: joint
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
  model: ???
  kinematics: null
  home: ???
  control:
    mode: position
    speed: ???
    execution: ???
  feedback: ???
  stop: ???
extrinsics:
  source: unknown
  mount: ???
```
