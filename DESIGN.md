# Design

Kinex composes the published Pi session SDK with a host-independent robotics core.
Pi owns providers/auth, the coding tools, model loops, transcript persistence,
retry, compaction and terminal rendering. Kinex owns robot semantics and product
composition. Neither dependency is forked.

## Packages and contracts

`packages/core` is the authoritative robotics source and assets package. Its root
runtime API exposes tools, skills, devices, profiles, calibration, recording and
events. Core imports no Pi, provider, session or UI implementation. The new command
catalog and executor encode trusted user operations independently of slash syntax.
Workflows return prompts; direct operations return structured output. Model calls
must continue through `runtime.tools.call` with host authorization.

`src/application.ts` creates Pi's `AgentSessionRuntime`, `ModelRuntime`, settings
storage and one `RoboticsOwner`. Its factory rebuilds SDK services when the cwd or
session changes. `src/integration` maps core JSON schemas/results into Pi tools,
registers commands and connects permission, state and recording events. Public
SDK hooks and interfaces are the only integration points.

The core and standalone are independently packable. Subsequent plugin packaging
belongs in the sibling `kinex_plugins` project, consuming the published core API.
No plugin or MCP server is required for this standalone application.

## Ownership and cancellation

The owner retains a core runtime across session replacement within a cwd. Outgoing
sessions settle SDK calls, cancel core invocations and dialogs, finalize recordings
against the outgoing transcript, and clear session permission grants. The next
session rebinds callbacks without restarting drivers. A different cwd first disposes
the previous owner. Quit and failed initialization also dispose it.

Core construction is inert. `warmLoaded()` reserves startup lanes, so tool calls
cannot overtake initialization. Failures stay per device. Call signals combine the
SDK invocation, session lifetime and core lifetime; driver disposal retains core's
process-group termination. Ordinary coding processes use Pi's own process handling.

Core tools (including discovered custom tools) and question declare sequential
execution. Pi serializes any batch containing one of them, including mixed coding
and robotics calls; pure coding batches retain Pi's parallel execution. Permission
denial or question cancellation aborts the run before later calls start. Earlier
completed calls are not rolled back. This scheduling contract belongs to the Pi
adapter, not core's device-local queues.

## State and recording

The fixed instructions form one Pi system section. Runtime snapshots are hidden
custom messages with their comparison data persisted in the active branch. A new
snapshot emits only changed sections. A compaction boundary invalidates the previous
snapshot for comparison. Tool definitions are sorted and only re-registered when
their description/schema changes. Removed tools are deactivated.

Discovery runs before a task and at `turn_end`, after every tool in the batch has
finished. Changed snapshots are persisted with `triggerTurn: false`, so refresh
never starts another response by itself. Pi 0.86.1's running loop keeps a separate
message array from agent state; the application wraps its public
`prepareNextTurnWithContext` hook to synchronize persisted messages before calling
Pi's original compaction/loadout preparation. Provider tool deltas and cache
protocols remain entirely SDK-owned. There is no idle file watcher.

Compaction still uses Pi's summary generator, preparation, retries and persistence.
`session_before_compact` scopes a robotics summary rule to that operation's abort
signal. A wrapper around the public agent stream function adds the rule only to
matching summary requests, including split-turn summaries and retries. It preserves
the normal Pi template and any user focus. Success, failure and shutdown clear the
scope; normal model requests and their prefixes are not rewritten.

At `session_compact`, the adapter reads a fresh full core snapshot, persists it with
the public SessionManager API and adds its converted message to agent state before
the SDK resumes. This committed boundary has no pending tool batch; ordinary queued
sendMessage would be too late. Manual, threshold and overflow compaction all share
the path. Snapshot failure aborts work and blocks subsequent model requests until a
successful refresh. The next normal snapshot comparison deduplicates unchanged
state, including on session reopen. These hooks and summary prose are standalone
integration code; other harness adapters must implement their own lifecycle wiring.

Tool images are read into bytes before entering the SDK transcript. Recording
messages are observed at turn/end boundaries, after Pi persists their message IDs;
the earlier extension `message_end` hook is deliberately not used for this mapping.
Trace export includes normalized text/tool calls, not provider reasoning state or
image payloads. Core recording remains opt-in for model access.

## Storage and resources

SDK settings use Kinex-specific storage through `SettingsManager.fromStorage`,
atomic writes and an interprocess file lock. Reads do not create a project `.kinex`
directory, preserving ancestor workspace discovery. Core's existing config/content
precedence stays authoritative. Pi system-prompt discovery and external resource
loading are disabled; project instructions still use the SDK loader.

Coding credentials and transcripts use the new `agent` subdirectories. There are
no migration wrappers for old harness formats. Python stays lazy and workspace-local;
the general bash tool is unmodified.
