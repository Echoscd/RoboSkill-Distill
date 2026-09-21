# Kinex standalone

Read README.md for usage and DESIGN.md for ownership. Update PLAN.md with actual
progress and validation results.

- Core owns robotics and shipped assets, and must not depend on Pi or a UI.
- Standalone composes published Pi SDKs using public APIs. Do not copy/fork the
  upstream provider, agent loop, coding tools, sessions, compaction or TUI.
- Keep user-command execution separate from permission-checked model tools.
- Preserve cancellation, loaded-device restoration, recording opt-in and disposal.
- Keep ordinary shell Python independent of lazy `.kinex/python`.
- Use TypeScript ESM, Node APIs, npm, small modules and typed errors.
- Run `npm run typecheck`, `npm test` and `npm run test:core` for integration changes.
  Builds replace output; never rebuild core concurrently with consumer tests.
- Plugin packaging is a later phase in ../kinex_plugins. Do not publish packages
  as part of routine build/test work.
