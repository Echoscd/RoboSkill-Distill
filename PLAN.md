# Kinex rewrite progress

## Decisions

- Standalone embeds the published Pi 0.86.1 session SDK and TUI; no upstream fork.
- Core is the sole robotics implementation; preserve robotics workspaces and assets.
- New coding configuration and sessions are isolated from Pi and legacy Kinex state.
- Same-workspace session replacement keeps devices connected and finalizes recording.
- First delivery: independent source/npm builds; no actual npm publication or bundled Node release.

## Standalone

- [x] Independent standalone project, migrated core and package-consumption checks.
- [x] Pi SDK application, interactive/headless entrypoints and isolated storage.
- [x] Shared robotics commands, tools, permissions, context and recording integration.
- [x] Kinex TUI, cancellation/lifecycle, fake-provider and PTY verification.
- [x] Installation/relocation verification and documentation.
- [x] Remove the TUI header's slash-command hint row; keep the Kinex title and commands.
  Rebuilt successfully and passed all 4 real PTY tests after the display change.
- [x] Task-local tool/skill/context refresh after each complete tool batch, including
  headless runs without further input. Public Pi next-turn hook synchronizes
  persisted context-only messages before SDK compaction and tool preparation.
- [x] P0 batch semantics: core/question batches execute sequentially through Pi;
  denial/cancellation stops later calls, while pure coding batches stay parallel.
- [x] P0 compaction continuity: scope robotics rules to Pi summary requests and
  immediately persist/synchronize a full snapshot after compaction. Failed state
  recovery blocks model work until a successful refresh. Core API/source unchanged.

Core exports a host-independent command catalog/executor alongside its runtime,
tools, workflows and assets. Standalone adapts those APIs through Pi's public
extension hooks; future adapters can reuse the same operations and workflows.

The original Kinex checkout remains unchanged. The new standalone has no dependency
on that checkout, `kinex-pi`, or an adjacent Pi source tree. `kinex_plugins/` is
reserved for the next phase and currently contains no implementation.

## v0.5.0 repository and delivery

- [x] Initialize the rewritten standalone as an independent Git repository on `main`;
  v0.5.0 is its first commit and local release tag.
- [x] Restore the original light/dark SVG branding and README banner/navigation.
  Include branding assets in the standalone npm package.
- [x] Keep progress, parity and context audits inside the standalone repository so
  a fresh checkout has working documentation links.
- [x] Adapt GitHub CI to the Pi build: Node from `.nvmrc`, Python 3.12, clean npm
  install, typecheck, core tests and standalone tests including PTY/relocation.
- [x] Add tag-triggered GitHub Releases containing both npm tarballs and SHA256SUMS;
  check standalone/core versions before packaging. npm registry publication and
  bundled Node binaries remain outside this workflow.
- [x] Locally verified clean `npm ci`, typecheck, 15 core tests and 46 standalone
  tests; workflow YAML/shell syntax and accepting/rejecting release version guards.
  GitHub-hosted execution has not run; no remote push or publication was performed.

## v0.5.0 repository and delivery

- [x] Initialize the rewritten standalone as an independent Git repository on `main`;
  v0.5.0 is its first commit and local release tag.
- [x] Restore the original light/dark SVG branding and README banner/navigation.
  Include branding assets in the standalone npm package.
- [x] Keep progress, parity and context audits inside the standalone repository so
  a fresh checkout has working documentation links.
- [x] Adapt GitHub CI to the Pi build: Node from `.nvmrc`, Python 3.12, clean npm
  install, typecheck, core tests and standalone tests including PTY/relocation.
- [x] Add tag-triggered GitHub Releases containing both npm tarballs and SHA256SUMS;
  check standalone/core versions before packaging. npm registry publication and
  bundled Node binaries remain outside this workflow.
- [x] Locally verified clean `npm ci`, typecheck, 15 core tests and 46 standalone
  tests; workflow YAML/shell syntax and accepting/rejecting release version guards.
  GitHub-hosted execution has not run; no remote push or publication was performed.

## Later

- [x] Audit original standalone feature parity against the installed Pi 0.86.1 and
  current integration; detailed inventory in [FEATURE_PARITY.md](FEATURE_PARITY.md).
- [x] Refresh the parity audit after P0 fixes: record 46+15 passing tests,
  adapter ownership, native tool/cache protocol coverage and remaining priorities.
- [ ] Resolve the audited host-level gaps before claiming full feature parity:
  stale hot-loading instructions, autonomous-mode instructions, image robustness,
  doom-loop guard, todo, local commands/skill shortcuts, device pickers,
  richer approval/question/status UI, exports/stats/cache audit and domain tests.
  Some command/config changes are intentional; see the inventory for distinctions.
- [ ] Pi and OpenCode adapters and release packaging in kinex_plugins/.
- [ ] MCP transport and broader host compatibility.
- [ ] Self-contained releases with Node, installer and native CI matrix.

## Validation

Verified on Linux with Node 22.19.0:

- Context/cache/hot-loading audit: 13 tests pass, including stdin-closed headless
  CLI, same-task discovery, interface updates/removal/error recovery, complete-batch
  message ordering, and prefix stability across skill/state changes/session reopen.
  Five explicit model-compatibility profiles verify Pi's native additions and
  fallback protocols. Real provider cache hit rates remain unmeasured.
  See [CONTEXT_AUDIT.md](CONTEXT_AUDIT.md).

- `npm run typecheck` passes.
- P0 regression suite: 14 tests pass for mixed-batch ordering, denial/cancellation,
  pure coding parallelism, session continuation/reopen, manual/threshold/overflow
  compaction, user focus, split-summary retries, failure/cancellation, immediate
  snapshots and blocking/recovering from snapshot failures.
- `npm test`: 46/46 standalone tests pass, covering coding/robotics tool calls, permission denial, interactive
  approvals/questions/cancellation, commands and completions, context prefix
  stability, retry/compaction, image replay, dynamic tools, recording traces and
  same/different-workspace session replacement.
- Real subprocess SIGINT/SIGTERM tests verify driver closure and recording
  finalization while a model request is pending.
- `npm run test:core`: 15/15 core integration and independent npm package tests pass.
- Both npm tarballs install together in an unrelated directory and run after
  relocation without source checkouts. The core package includes its assets/types.
- Integration validation reran typecheck, the complete standalone suite (including
  package relocation and real PTY tests), then the independent core suite in order.

Live provider cache-hit rates and physical hardware have not been measured. Tests
use a local HTTP model provider and mock/Python test drivers. No packages have been
published. External Pi resource/package loading, old coding-session migration and
the bundled-Node installer are outside this phase. See `README.md` for setup,
configuration paths, command semantics and permission modes.
