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

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/7-cmdb-connector-servicenow.md`
  summary: No response-body size guard before JSON-parsing the CMDB connector's ServiceNow response.
  evidence: Same category as the calendar connector's existing deferral; low risk against a well-behaved, documented API.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/7-cmdb-connector-servicenow.md`
  summary: No HTTP 429/retry-backoff handling for the CMDB connector.
  evidence: Same category as the ticketing connector's existing deferral; fine for a low-frequency, on-demand tool.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/7-cmdb-connector-servicenow.md`
  summary: A new httpx.Client is constructed and torn down on every call, with no connection pooling/reuse -- same category as the ticketing connector's existing deferral.
  evidence: Acceptable for an on-demand status check; revisit if usage patterns change.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/7-cmdb-connector-servicenow.md`
  summary: `_build_source`'s character sanitization can theoretically collide distinct (instance_url, table, sys_id) triples into an identical source string -- same accepted risk class as git/ticketing/calendar.
  evidence: Extremely unlikely in practice; not worth a fix until source is consumed as more than a display/audit string.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/7-cmdb-connector-servicenow.md`
  summary: No test or documented behavior for a 3xx redirect response from ServiceNow's Table API.
  evidence: Same category as the calendar connector's existing deferral; falls into the generic error branch today, untested but not obviously wrong.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/8-ownership-inference-and-arbitration.md`
  summary: `ledger_get_coverage` has no orphan-risk-aware counterpart -- a caller wanting a count of orphan-risk artifacts (not a full listing) must call `list_records(orphan_risk=True)` and count client-side.
  evidence: `list_records`/`ledger_list_records` already expose the detail view; a counts-only view mirroring the confidence coverage map is a reasonable future addition, not required for orphan-risk to be usable now.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/8-ownership-inference-and-arbitration.md`
  summary: No documented note that `escalation_owner`'s three possible source fields (CMDB `support_group`, ticketing `assigned_to`, calendar `organizer_email`) carry different identifier formats (a group name, a username, an email address) depending on which source resolved it.
  evidence: Low risk today since nothing downstream parses `escalation_owner`'s format, only displays/compares it; worth documenting if a future story starts relying on the value's shape.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/9-draft-not-send-outbound-content.md`
  summary: No charset/enum restriction on `draft_type` beyond corruption-safety escaping -- a typo silently creates a new, never-matching category rather than surfacing the mistake.
  evidence: Low real-world impact since draft_type is caller-chosen categorical text with only one caller (this system itself) so far; revisit if draft_type values proliferate or come from less-trusted input.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/9-draft-not-send-outbound-content.md`
  summary: `create_draft` doesn't check that `artifact_type`/`artifact_id` correspond to any artifact the ledger actually knows about -- only the identifier charset is validated.
  evidence: Consistent with the rest of the system's philosophy (RawFact ingestion doesn't validate artifact existence either, by design); a typo'd reference is indistinguishable from a legitimate orphan-risk artifact today.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/9-draft-not-send-outbound-content.md`
  summary: No tool to fetch a single draft by its `draft_id` -- callers wanting to re-check a specific draft must filter `list_drafts` client-side with no uniqueness guarantee.
  evidence: `list_drafts`'s existing filters (artifact_type/artifact_id/draft_type) cover retrieval reasonably for v1; a get-by-id tool is a reasonable future addition, not required now.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/9-draft-not-send-outbound-content.md`
  summary: No pagination or size limit on `list_drafts`/`ledger_list_drafts` -- same category as the existing coverage/list_records pagination deferrals.
  evidence: Fine at current scale; revisit alongside the other pagination deferrals once real draft volume grows.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/10-periodic-briefing.md`
  summary: `get_briefing`'s four underlying reads (two `list_records` calls, `list_drafts`, `get_coverage_map`) are sequential and unsynchronized -- a write landing between them could produce a briefing that mixes ledger state from different moments, rather than one consistent point-in-time snapshot.
  evidence: Same root category as Story 1's existing no-file-locking deferral, just surfacing as a new symptom (cross-section inconsistency within one briefing) rather than a corrupted single write; low real-world risk for a single-process, on-demand, local-first v1 tool with no concurrent writers today.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/11-scheduled-headless-operation.md`
  summary: No concurrency guard against two overlapping invocations of `ops/run_scheduled_briefing.py` (e.g. a slow scheduled run still in flight when the next one fires).
  evidence: Same root category as the project's existing no-file-locking deferral, now applying to `_ops.log.md`; low real-world risk at v1's expected once-daily cadence, but a real gap for a script explicitly meant to run unattended and repeatedly.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/11-scheduled-headless-operation.md`
  summary: On a `claude -p` timeout, only the immediate child process is killed -- any MCP server grandchild processes it spawned aren't guaranteed to be cleaned up, risking orphaned processes after a timed-out scheduled run.
  evidence: `subprocess.run`'s default timeout handling only reaches the direct child; process-group management (`start_new_session` + killing the group) would need its own design and testing, and no existing pattern in this codebase (including `connectors/git_repo/server.py`'s `_run_git`) currently does this.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/11-scheduled-headless-operation.md`
  summary: No non-interactive/permission-mode flag is passed to `claude -p` -- if the CLI would otherwise prompt for tool-use approval, an unattended scheduled run has no human to answer it, and the resulting stall would surface as a misleading `timeout` log entry rather than the real cause.
  evidence: Needs research into `claude -p`'s actual non-interactive/auto-approve flag semantics before a correct fix can be written; guessing at a flag risks silently no-op-ing or breaking the invocation.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/11-scheduled-headless-operation.md`
  summary: No MCP tool allowlist restricts the headless scheduled run to read-only tools -- nothing currently prevents the fixed prompt from being permitted to call a state-changing tool (e.g. `ledger_create_draft`) rather than being scoped to the read-only briefing path.
  evidence: This story's frozen intent is invocation plumbing only, not access-control policy; a tool allowlist is a real hardening step but a separate scoped decision (which tools, enforced how) not resolved by this story's spec.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/11-scheduled-headless-operation.md`
  summary: No redaction/scrubbing of subprocess `stderr` before it's persisted into `ledger_data/_ops.log.md` -- if `claude -p` or a connector ever emits a credential/token in its error output, truncation alone doesn't prevent it from landing in a file `ops/README.md` tells operators to read directly.
  evidence: A real defense-in-depth gap, but building a correct redaction step (what patterns, what false-positive/negative tradeoffs) is its own scoped decision, not a safe one-line patch.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/11-scheduled-headless-operation.md`
  summary: No log rotation or size cap on `ledger_data/_ops.log.md`, same category as the project's existing pagination/size-limit deferrals.
  evidence: Fine at current scale for a once-daily scheduled job; revisit alongside the other size-limit deferrals once real run history accumulates.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/11-scheduled-headless-operation.md`
  summary: `ledger_data/` is not committed and has no `.gitignore` entry, despite the top-level `README.md` describing it as git-committed -- this story adds `_ops.log.md` (and its README documents `_cron_stdout.log`/`_launchd_stdout.log`/`_launchd_stderr.log`) as more files that could land there ungoverned.
  evidence: Pre-existing gap predating this story (no prior story has committed `ledger_data/` either); the policy decision -- commit runtime state or gitignore it -- is broader than this story's scope.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/12-evidence-boundary.md`
  summary: No `ledger_get_evidence(evidence_id)` single-item lookup or filter-by-artifact/claim surface -- only `ledger_list_evidence`, which returns every bundle unfiltered and unpaginated.
  evidence: Same category as the existing no-get-by-id deferral for `Draft` (Story 9); fine at current scale, Story 13's `ActionProposal` only needs to reference a bundle by id it already holds, not look one up generically.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/12-evidence-boundary.md`
  summary: No retention/pruning/size cap on `ledger_data/evidence/` -- created-only, grows forever.
  evidence: Same category as the project's existing pagination/size-limit deferrals; revisit once real bundle volume grows.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/12-evidence-boundary.md`
  summary: No upper bound on `claim`/`reasoning`/`artifact_type`/`artifact_id` string length -- only non-blank is checked.
  evidence: Low real-world risk since the only caller today is Voice itself, not untrusted input; revisit if this ever proves a real problem (matches the project's existing pattern of deferring unbounded-input guards until they're demonstrated to matter).

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/12-evidence-boundary.md`
  summary: `_parse_bundle_file` doesn't validate `generated_at`'s format as a real timestamp, and doesn't reject an unrecognized extra frontmatter key or a blank reasoning body on read (only at create time).
  evidence: These only matter against a hand-edited or tampered file, not real data this module itself ever writes; low priority defensive parsing, same category as other accepted-but-imperfect parse-time gaps already deferred elsewhere (e.g. Story 8's format-documentation gap).

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/12-evidence-boundary.md`
  summary: `EVIDENCE_FORMAT_ERROR_MARKER`'s sentinel convention isn't exported/documented at the MCP tool-response level for a client to reliably distinguish a corrupted-file placeholder from a legitimate bundle.
  evidence: Same category as Story 10's accepted sentinel-dedup non-behavior; a real gap but low priority for a single-caller (Voice) system today.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/13-action-proposal-and-the-policy-engine.md`
  summary: The two-line `proposed`+`decided` append to `action_proposals.log.md` has no locking against a concurrent writer -- two processes' lines could theoretically interleave.
  evidence: Same root category as the project's existing no-file-locking deferral (Story 1); low real-world risk for a single-process, on-demand tool with no concurrent writers today.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/13-action-proposal-and-the-policy-engine.md`
  summary: No pagination or filter-by-`policy_decision`/`action`/`target` on `list_action_proposals`/`ledger_list_action_proposals` -- same category as the existing pagination deferrals for records/coverage/drafts/evidence.
  evidence: Fine at current scale; revisit alongside the other pagination deferrals once real proposal volume grows.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/13-action-proposal-and-the-policy-engine.md`
  summary: `_compute_policy_decision`'s `min()` over cited bundles' confidence has no defensive type/range check before calling `min()` -- would raise an unhandled `TypeError` rather than a clean validation error if a bundle's `confidence` were ever non-numeric.
  evidence: Story 12's `EvidenceBundle.confidence` is already guaranteed to be a valid float by construction, so this has no realistic trigger today; worth hardening only if that guarantee is ever relaxed.
