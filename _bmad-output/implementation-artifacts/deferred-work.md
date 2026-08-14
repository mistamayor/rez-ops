- source_spec: `_bmad-output/specs/spec-rez-ops/stories/1-shared-schema-ledger-core-foundation.md`
  summary: The append-only event log has no file locking or other concurrency protection against interleaved writes from multiple writers.
  evidence: Story 1 is exercised only against synthetic, effectively single-writer test scenarios, so no collision is currently possible — but Story 5 introduces multiple real connectors that could plausibly write concurrently, and AD-3's append-only guarantee assumes writes don't interleave and corrupt a line.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/1-shared-schema-ledger-core-foundation.md`
  summary: No lint, formatting, or static type-checking tooling (ruff/black/mypy) is configured for the project despite the codebase being fully type-annotated.
  evidence: Nothing currently enforces that the type annotations stay accurate as the codebase grows across the remaining 8 stories; cheap to add now, more disruptive to retrofit later.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/1-shared-schema-ledger-core-foundation.md`
  summary: The new project scaffold has no README, LICENSE, or CI workflow.
  evidence: Nothing documents how to install/run/test rez-ops for a future contributor, and nothing enforces tests passing on push/PR; not blocking for a single-owner v1 but worth adding before the open packaging question (SPEC.md) resolves toward distribution.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/2-first-connector-git.md`
  summary: The git connector doesn't distinguish git's "detected dubious ownership" (safe.directory) failure from a plain non-git directory.
  evidence: Both currently surface as NotAGitRepositoryError with the same message, which would be a confusing error if a real repo is ever flagged as dubious ownership by git itself; low likelihood in a single-user local v1 but worth a clearer message later.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/2-first-connector-git.md`
  summary: "Last touched" queries via `git log -1 -- file_path` have undocumented, untested behavior across merge commits (no `-m`/`--first-parent` handling).
  evidence: Merge-commit history simplification can make "last touched" ambiguous for a given path; deferred rather than guessed at since the right semantics depend on how Rez Ops's real target repos actually branch/merge, which isn't known yet.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/2-first-connector-git.md`
  summary: `_build_source`'s sanitization can theoretically map two different (repo_path, commit_sha) pairs to an identical `source` string, since multiple disallowed characters all collapse to the same `_` replacement.
  evidence: Extremely unlikely in practice since the full 40-character commit SHA is already included, and nothing in the codebase parses `source` back into components today -- not worth a fix until `source` is actually consumed as more than a display/audit string.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/3-confidence-and-coverage-computation.md`
  summary: `ledger_get_coverage` returns the full tally for every artifact_type/artifact_id with no pagination or size limit.
  evidence: Fine at current scale (a handful of artifact types from one connector); revisit once real connectors (Story 5+) push the artifact count high enough that the response size or read cost becomes a real concern.
