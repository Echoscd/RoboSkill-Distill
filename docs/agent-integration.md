# Agent integration and context

## Tools and device guidance

Tools declare input schemas; Python manifests also declare capability kind and
timeout. Composition preserves permissions and recording attribution. Device
guides own Setup, Profile and Use sections; only
Use enters loaded-device context. Custom instance `DEVICE.md` guides are allowed
only for `legged_base`, require nonempty Use text and override shared guides with
normal discovery precedence. Other types use shared guides and profile parameters.
Workspace safety limits and keep-out zones remain manifest data, outside robot
context; `safety.notes` is not a schema field.

`exec` is a core tool alongside direct device calls and reusable Python tools.
It runs source or script files in a fresh process, returning captured stdout/stderr,
an exit code and an optional structured result. Its optional `description` is a
display label; standalone falls back to the script path or `python script`.
The host's shell and file tools retain their own execution paths and permissions.

Tool results can carry image attachments as `{mime, data}` (base64) or
`{mime, path}`. Hosts must forward both as image content in attachment order.
Direct camera reads attach RGB images automatically; Python results attach
selected image files returned through `finish`. A partially successful `devices`
batch retains successful images and per-call errors, with the top-level error
flag set only when every call failed. Hosts must inspect individual results
without discarding the successful observations.

## Sessions and permissions

Hosts own approval UI, session identity and cancellation, keeping trusted commands
separate from model calls. Missing permission callbacks deny except stop. Standalone
retains connections across same-workspace sessions while cancelling old calls,
resetting grants and ending recordings; workspace replacement/quit disposes them.
Robotics/question batches execute sequentially; denial/cancellation stops later
calls without rolling back completed work. Pure coding batches remain parallel.

`exec` requests `python_tool_controller` approval once for the script and its
composed runtime calls. Device reads and actions share that approval; composed
perception tools retain their capability restrictions. Python's runtime API cannot
change device lifecycle or call the recording tool. Existing manifest tools keep
their permission behavior when invoked outside `exec`.

Scripts and composed tools share cancellation and motion ownership. On controller
failure, timeout or cancellation, the runner attempts to stop motion they still
own and terminates owned subprocesses. Cleanup failures are logged while the
original failure is returned. Normal script completion does not imply a stop:
scripts use `stop_owned()` when their stopping condition requires one. Ownership
checks preserve replacements, subject to the driver's physical stop scope.
These behaviors use the shared Python runner; hosts should route `exec` through
core's tool API. Per-entry errors
in a Python `devices()` result do not by themselves fail the script; scripts must
inspect them and decide whether to stop or raise an error.

## Recording

Manual recording is available; model recording is opt-in. Native capture or dispatch
sampling produces manifests, timelines, profile snapshots and per-device products;
incidental traffic is separate. Acquisition timestamps, cadence and playback FPS
are distinct. Losses are counted, failures are per-device, finalization is bounded
and quotas permit limited overshoot. Hosts supply transcript references; outcome
labels are annotations, not verification.

## Context and compaction

Tools/skills refresh within tasks. Stable prompt prefixes exclude dynamic state;
changes append to the active branch. Compaction preserves robotics facts and
restores a full current snapshot before the next request, stopping if recovery
fails. Images enter history as bytes; recording traces omit image bytes and opaque
reasoning. Active time uses a monotonic clock, excludes idle/input dialogs and
persists outside model context; shutdown clears footer timers/subscriptions.

## Pi resources and credentials

Standalone uses Kinex storage and a managed auth link so SDK child sessions share
credentials and OAuth locks; conflicts are never overwritten. Pi owns `/reload`;
programmatic core `devices.reload()` remains available. Setup bundles upstream
web-search/BTW extensions, loaded through Pi with explicit packages taking
precedence. BTW children use upstream coding tools and credentials without Kinex
runtime or permission hooks. Package management uses Pi APIs without starting
sessions, loading extensions or initializing robotics. Project declarations live
under `.kinex/agent`, resources under `.pi`; version/ref pins survive updates.

See [project overview](overview.md) for contribution ownership and
[device contracts](devices.md) for driver lifecycle and capture interfaces.

[Design index](README.md)
