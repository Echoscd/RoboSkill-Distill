# Kinex progress

## Architecture and delivery

- One npm workspace owns `kinex`, `@kinex/core`, `@kinex/pi`,
  `@kinex/opencode` and `@kinex/codex`. All five use version **0.6.0**, exact internal dependencies,
  and a shared CI/release workflow. No separate `kinex_plugins` repository.
- Standalone embeds published Pi SDKs; providers, coding tools, agent loop,
  sessions, compaction and TUI remain upstream-owned.
- Core owns robotics and assets, with no host dependency. Its additive
  `KinexContribution` interface exposes tools, skills, commands and context.
  Products explicitly compose features; adapters convert them to host APIs.
- Future `@kinex/real-world` can contribute beside core using the same adapters.
  Extraction and automatic package discovery are deferred.

## Completed: standalone and host adapters

- [x] Independent standalone with isolated coding storage, preserved robotics
  workspaces, native commands, ask/auto/yolo and recording opt-in.
- [x] Preserve batch-boundary hot loading, prefix-stable context updates,
  sequential robotics batches, denial/cancellation and post-compaction recovery.
- [x] Move reusable Pi ownership, tools, commands, permissions and context code
  into `packages/pi`; standalone imports it without copying an upstream harness.
- [x] Add explicit multi-feature composition with duplicate-name validation,
  refreshed routing, skill loading and namespaced context.
- [x] Native Pi extension: direct commands, conflict aliases, dynamic tools/skills,
  host permissions/UI integration and persistent context projection. Keep native
  Pi's summarizer; refresh a full snapshot before continuation.
- [x] Native Pi lifecycle: same-workspace SDK factory handoff keeps devices and
  ends outgoing recording; workspace changes, reload and quit dispose resources.
- [x] OpenCode server plugin: fixed discovery/call tools, native permissions,
  serial Kinex execution, recording ownership and compaction/context hooks.
- [x] OpenCode TUI plugin: native dialogs and direct commands over private local
  IPC; no model needed. Disconnect cancels work; server owns runtime disposal.
- [x] Preserve ancestor robotics workspace discovery when storing OpenCode context.
- [x] Codex stdio MCP adapter with live contribution discovery, Core permission
  forms/questionnaires, byte images, immediate stop and cancellation of queued work.
- [x] Codex direct user controls share the server runtime over private local IPC;
  manual recording remains available while model recording is opt-in.
- [x] Codex startup/EOF/signals preserve initialization ordering, cancel owned
  processes and finalize recording. Stable instructions and result context keep
  host-independent Core assets authoritative.
- [x] Model context exposes Python paths/readiness without inherited process
  environment variables; execution APIs retain the environment for child processes.
- [x] Five independently packable npm artifacts, release version/dependency guard,
  checksums, CI adapter tests and documentation. Actual publication is not part
  of this stage.

## Validation

Validated on Linux, Node 22.19.0, Pi 0.86.1, OpenCode 1.18.31 and Codex 0.155.1:

- Typechecking and builds pass.
- Standalone: **46 tests**, including all four real PTY cases, context/cache
  request capture, P0 batch/compaction behavior, recording and signal cleanup.
- Core: **16 tests**, including independent package consumption and contribution
  composition/authorization/cancellation contracts.
- Native adapters: **14 tests** (7 Pi, 7 OpenCode), including real SDK/plugin
  loading, actual OpenCode model requests and TUI interaction, zero-model device
  commands, hot loading, prefix preservation, compaction, runtime handoff,
  multi-feature routing, IPC cancellation and recording ownership.
- Codex: **14 tests**, including actual host tool-search/model requests and forms,
  hot loading, direct-control PTY confirmation without model requests, shared
  recording, permissions, cancellation, initialization/exit cleanup, bounded
  images and Core+Codex-only package relocation. Core/standalone checks rerun;
  Pi/OpenCode packages and their tests were unchanged in this addition.
- Tarballs install outside the checkout and still run after relocation.
  Standalone installs without OpenCode; adapters install without standalone.
- Local release validation checks workflow syntax, matching/mismatched tags and
  package checksums. GitHub-hosted execution has not run.

Tests use a local HTTP model provider and mock/Python drivers. No physical hardware
or live provider cache-hit rate was measured. No npm publish, remote push or
release tag was performed for this stage.

## Deliberate first-release limits

- OpenCode direct commands use selection/input dialogs and same-machine Unix IPC;
  remote attach commands and Windows IPC are deferred. Linux is the tested platform.
- Native Pi keeps its own coding permissions and default summarizer. Standalone's
  extra robotics summary rules are application-specific.
- OpenCode serializes Kinex calls; already-running host coding calls cannot be
  rolled back. In-tool questionnaires are declined; use host questions beforehand.
- OpenCode's context ledger is local workspace state and does not accompany host
  session export/fork. An active recording excludes other sessions' non-emergency
  Kinex operations until it ends.
- Codex uses explicit full-context discovery and changed tool-result sections,
  without per-turn/compaction hooks or conversation transcript export. Recording
  belongs to the MCP instance. Direct controls require a running local server;
  multiple instances must be selected explicitly. The queue cannot enforce a
  host-wide turn halt or cancel Codex coding tools. No marketplace wrapper is needed.
- Upstream upgrades require dependency updates and real-host regression checks.
  Standalone third-party Pi package loading remains disabled.

Documentation: DESIGN.md summarizes the current products and core contracts;
AGENTS.md records ownership, invariants and required checks. Detailed behavior and
known gaps remain in package READMEs and FEATURE_PARITY.md.

## Remaining work

- [ ] Extract real-world onboarding into a separate feature package when its
  ownership is concrete; use the existing explicit contribution composition.
- [ ] Broader host/platform compatibility beyond the current local adapters.
- [ ] Remaining standalone parity priorities: autonomous-mode instructions,
  bounded image attachment handling, loop/task budgets and robotics domain/RoboEnv
  regressions. See [FEATURE_PARITY.md](FEATURE_PARITY.md).
- [ ] Lower-priority command/UI/export/statistics gaps and self-contained Node
  releases. See [CONTEXT_AUDIT.md](CONTEXT_AUDIT.md) for cache validation limits.
