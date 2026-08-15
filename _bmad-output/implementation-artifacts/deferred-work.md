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

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/4-chat-queryable-live-state.md`
  summary: `list_records`/`ledger_list_records` don't validate the `confidence` filter value -- a typo (e.g. "unkown") silently returns zero matches, indistinguishable from "nothing actually matches."
  evidence: Low real-world risk since the Runtime/LLM caller typically already knows valid confidence values from prior get_record/get_coverage responses, but worth a guard if it ever causes real confusion.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/4-chat-queryable-live-state.md`
  summary: No documented or tested ordering guarantee for `list_records` results spanning multiple artifact types.
  evidence: Not needed yet since the Voice/LLM layer can sort or filter conversationally, but a "chat-queryable" feature may eventually want stable ordering across repeated calls; no clear correct default (alphabetical, insertion, by last_verified) has been decided.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/4-chat-queryable-live-state.md`
  summary: `ledger_list_records` has no pagination or size limit, same category as `ledger_get_coverage`'s existing deferral.
  evidence: Fine at current scale; revisit alongside the coverage pagination deferral once real connector volume grows.

- source_spec: none
  summary: Calendar connector, deferred from Story 5's original "calendar, ticketing, CMDB" scope.
  evidence: Story 5 covered three independently shippable connectors bundled as one story; split so each is built, reviewed, and committed on its own (same rhythm as Story 2). Ticketing was picked to go first.

- source_spec: none
  summary: CMDB connector, deferred from Story 5's original "calendar, ticketing, CMDB" scope.
  evidence: Story 5 covered three independently shippable connectors bundled as one story; split so each is built, reviewed, and committed on its own (same rhythm as Story 2). Ticketing was picked to go first.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/5-ticketing-connector-servicenow.md`
  summary: The ticketing connector has no retry/backoff for transient failures, and HTTP 429 (ServiceNow rate limiting) isn't distinguished from other error types.
  evidence: A single connection error, timeout, or throttling response is treated as an immediate hard failure; fine for a low-frequency, on-demand tool, but worth revisiting if it's ever polled frequently enough to hit real rate limits.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/5-ticketing-connector-servicenow.md`
  summary: A new httpx.Client is constructed and torn down on every call, with no connection pooling/reuse across invocations.
  evidence: A full TCP/TLS handshake per call is acceptable for an on-demand status check but would matter if this tool were polled repeatedly during a DR runbook; revisit if usage patterns change.

- source_spec: none
  summary: Microsoft 365 / Outlook calendar connector, deferred from the calendar connector's own further split (user wanted both Google Calendar and Microsoft 365).
  evidence: The two calendar backends have completely different auth and API shapes and are independently shippable, same reasoning as the original Story 5 split; Google Calendar was picked to go first.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/6-calendar-connector-google.md`
  summary: `_build_source`'s character sanitization can theoretically collide two distinct (calendar_id, event_id) pairs into an identical source string.
  evidence: Same class of risk already accepted for the git and ticketing connectors' source construction -- extremely unlikely in practice given both identifiers are included, not worth a fix until source is consumed as more than a display/audit string.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/6-calendar-connector-google.md`
  summary: No HTTP 429/retry-backoff handling for the Google Calendar connector.
  evidence: Same category as the ticketing connector's existing deferral; fine for a low-frequency, on-demand tool.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/6-calendar-connector-google.md`
  summary: No response-body size guard before JSON-parsing the Calendar API response.
  evidence: Low risk against a well-behaved, documented Google API; revisit if this ever proves to be a real problem.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/6-calendar-connector-google.md`
  summary: No test or documented behavior for a 3xx redirect response from the Calendar API.
  evidence: Low likelihood against a fixed, well-known Google API endpoint; falls into the generic error branch today, untested but not obviously wrong.
