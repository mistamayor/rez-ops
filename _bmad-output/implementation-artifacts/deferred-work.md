- source_spec: `_bmad-output/specs/spec-rez-ops/stories/1-shared-schema-ledger-core-foundation.md`
  summary: The append-only event log has no file locking or other concurrency protection against interleaved writes from multiple writers.
  evidence: Story 1 is exercised only against synthetic, effectively single-writer test scenarios, so no collision is currently possible — but Story 5 introduces multiple real connectors that could plausibly write concurrently, and AD-3's append-only guarantee assumes writes don't interleave and corrupt a line.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/1-shared-schema-ledger-core-foundation.md`
  summary: No lint, formatting, or static type-checking tooling (ruff/black/mypy) is configured for the project despite the codebase being fully type-annotated.
  evidence: Nothing currently enforces that the type annotations stay accurate as the codebase grows across the remaining 8 stories; cheap to add now, more disruptive to retrofit later.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/1-shared-schema-ledger-core-foundation.md`
  summary: The new project scaffold has no README, LICENSE, or CI workflow.
  evidence: Nothing documents how to install/run/test rez-ops for a future contributor, and nothing enforces tests passing on push/PR; not blocking for a single-owner v1 but worth adding before the open packaging question (SPEC.md) resolves toward distribution.
