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

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/14-google-drive-connector.md`
  summary: `_build_source`'s character sanitization can theoretically collide two distinct `file_id`s into an identical source string -- same accepted risk class as every other connector's identical deferral (git/ticketing/calendar/CMDB).
  evidence: Extremely unlikely in practice; not worth a fix until `source` is consumed as more than a display/audit string.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/14-google-drive-connector.md`
  summary: HTTP 403 from the Drive API is always treated as `AuthenticationError`, but Google also returns 403 for transient rate/quota errors (e.g. `userRateLimitExceeded`) -- indistinguishable here from a genuine permission failure. No dedicated 429/retry-backoff handling either.
  evidence: Same category as the ticketing/calendar/CMDB connectors' existing 429/retry-backoff deferrals; fine for a low-frequency, on-demand tool.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/14-google-drive-connector.md`
  summary: The connector doesn't surface whether a file is `trashed` (deleted) -- a trashed file's `modifiedTime` can look "not stale" while the document no longer meaningfully exists.
  evidence: Real, useful signal for a "document status" connector, but outside this story's frozen field scope (`modifiedTime`/`lastModifyingUser` only); a reasonable follow-up enhancement, not a defect in what was built.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/14-google-drive-connector.md`
  summary: The Drive API response's `id` field is requested but never verified against the requested `file_id`.
  evidence: Low real-world risk since the request URL already scopes the lookup to one file id; defensive check with no realistic trigger today.

- source_spec: `_bmad-output/specs/spec-rez-ops/stories/14-google-drive-connector.md`
  summary: No length/format upper bound on `file_id`/`artifact_type`/`artifact_id` beyond non-empty-string -- same category as other connectors' accepted no-length-bound gaps.
  evidence: Low risk since the only caller today is Voice itself, not untrusted input.

- source_spec: none
  summary: Credential validation across every connector (calendar, ticketing, CMDB, and now Google Drive) only rejects ASCII control characters, not general non-ASCII input (e.g. an accented character or emoji in a token) -- a non-ASCII credential could raise an untyped `UnicodeEncodeError` from httpx's header encoding, escaping uncaught.
  evidence: Pre-existing gap across the whole connector family, not specific to any one story (found during Story 14's review, which mirrors the same `_CONTROL_CHAR_RE` pattern every other connector already uses) -- worth a dedicated cross-connector hardening pass rather than an ad-hoc fix in just one connector.

- source_spec: none
  summary: `ledger_core.projection.get_record` (a single-artifact lookup, unlike `list_records`/`get_coverage_map`) doesn't catch `LogFormatError` for a corrupted artifact-type log -- it propagates raw rather than degrading gracefully (no sentinel-record pattern at this granularity). Found via a Story 13 hardening pass: `create_action_proposal`'s own `get_record` call for the target was patched to fail open around this (treats a corrupted target log as unknown criticality), but the root cause in `get_record`/`ledger_get_record` itself remains -- a corrupted log still crashes a direct single-artifact lookup.
  evidence: Pre-existing gap predating Story 13, dating back to Story 3/4 (confidence/coverage computation, chat-queryable live state) -- `list_records`/`get_coverage_map` already got the sentinel-record AD-8 treatment (Stories 4/8), but `get_record` (and the `ledger_get_record` MCP tool) never did, since no caller's crash had a visible enough consequence until `create_action_proposal` started depending on it as one step of a larger operation.
- source_spec: `_bmad-output/specs/spec-rez-ops/stories/15-sharepoint-connector.md`
  summary: `_build_source`'s join-then-sanitize-with-"_" pattern is not injective — two distinct multi-identifier inputs (e.g. drive_id="a/b", item_id="c" vs. drive_id="a", item_id="b/c") can collapse to the identical `source` string, silently conflating two different artifacts' provenance in the ledger.
  evidence: Confirmed independently by 2 of 3 Story 15 reviewers (edge-case-hunter, blind-hunter). The pattern is copied verbatim across `ticketing`, `cmdb`, `calendar_google`, and now `sharepoint` — pre-existing in 3 already-shipped connectors, not introduced by Story 15. A fix should be structural (e.g. length-prefixed or otherwise unambiguous encoding inside a shared `_build_source` helper) rather than patched connector-by-connector.
- source_spec: `_bmad-output/specs/spec-rez-ops/stories/15-sharepoint-connector.md`
  summary: `_read_credential` validates a credential is non-blank and control-char-free but returns it unstripped, so incidental leading/trailing whitespace is sent verbatim in the `Authorization` header — inconsistent with every other value in these modules, which is `.strip()`ped before use.
  evidence: Confirmed independently by 2 of 3 Story 15 reviewers (edge-case-hunter, blind-hunter). Present verbatim in `google_drive`, `calendar_google`, `ticketing`, and `cmdb` as well as the new `sharepoint` connector — pre-existing across 4 already-shipped connectors, not introduced by Story 15.
- source_spec: `_bmad-output/specs/spec-rez-ops/stories/16-cross-cutting-connector-and-ledger-core-hardening.md`
  summary: RESOLVED within Story 16 itself (not left deferred). The `ticketing` connector's `_read_credentials` never checked its token for control characters at all -- unlike `calendar_google`, `cmdb`, `google_drive`, and `sharepoint`, which all reject an embedded CR/LF before any HTTP request.
  evidence: Confirmed independently by 2 of 3 Story 16 reviewers (edge-case-hunter, blind-hunter) as pre-existing/out of scope; deferred here first, then closed anyway in the same story's own patch round when fixing an unrelated validation-order bug required touching this exact code path in all 5 credential-bearing connectors uniformly. Left as a record of the finding, not an open item.
- source_spec: `_bmad-output/specs/spec-rez-ops/stories/16-cross-cutting-connector-and-ledger-core-hardening.md`
  summary: `cmdb`/`ticketing`'s `instance_url` env var is validated (non-blank, `https://`-prefixed, trailing-`/`-stripped) but never `.strip()`ped of general leading/trailing whitespace the way the token now is -- a trailing newline on `REZOPS_CMDB_INSTANCE_URL`/`REZOPS_TICKETING_INSTANCE_URL` (a common artifact of some secret-store tooling) still hard-fails with `InvalidInstanceUrlError`.
  evidence: Surfaced by Story 16's blind-hunter review as an inconsistency highlighted by contrast with the token now being stripped. Pre-existing since these connectors were built (Stories 5/7), not introduced by Story 16 -- out of this story's frozen scope (token stripping only).
- source_spec: `_bmad-output/specs/spec-rez-ops/stories/17-tier-assignment-dr-risk-classification.md`
  summary: `LedgerRecord.risk` (Story 17, CAP-11) is computed but never consulted by `action_proposals._compute_policy_decision` -- `policy_decision` still only reads `impact`/`tier_sla_known`/`min_confidence`, not the risk level itself.
  evidence: Confirmed by Story 17's blind-hunter reviewer. `_compute_policy_decision` is Story 13's frozen policy rule (AD-12) -- out of Story 17's own "no other change to action_proposals.py" scope. A real future integration question (should a HIGH-risk target ever downgrade an otherwise-automatic decision?), not a defect in what Story 17 built.
- source_spec: `_bmad-output/specs/spec-rez-ops/stories/17-tier-assignment-dr-risk-classification.md`
  summary: Naming collision between `list_records`' pre-existing `orphan_risk: bool` filter (escalation-ownership gap) and the new `LedgerRecord.risk: str` field (DR expiry classification) -- no docstring disambiguates the two for an MCP-tool-schema reader.
  evidence: Surfaced by Story 17's blind-hunter review. Doc-only; both concepts already work correctly, just share the word "risk" for unrelated things.
- source_spec: `_bmad-output/specs/spec-rez-ops/stories/17-tier-assignment-dr-risk-classification.md`
  summary: `expiry_rule = f"{expiry_days} days"` is unconditionally pluralized -- a tier declared with `expiry_days: 1` renders `"1 days"`.
  evidence: Surfaced by Story 17's blind-hunter review. Cosmetic, untested, no functional impact.
- source_spec: `_bmad-output/specs/spec-rez-ops/stories/17-tier-assignment-dr-risk-classification.md`
  summary: `rezops.tiers.yaml`'s hand-rolled parser has an asymmetric tier-name charset: `_TIER_DECLARATION_RE` restricts to `[A-Za-z0-9_-]+` but `_TIER_ASSIGNMENT_RE` captures the assigned tier name with an unrestricted `\S+`. Currently harmless (the undeclared-tier check catches anything not already declared under the stricter pattern), but an inconsistency that could bite if that check is ever refactored.
  evidence: Surfaced by Story 17's blind-hunter review.
- source_spec: `_bmad-output/specs/spec-rez-ops/stories/18-dr-readiness-summary-query.md`
  summary: `TierReadiness.risk_counts` is a plain mutable `dict[str, int]` field on a `frozen=True` dataclass -- a direct caller of `get_dr_readiness_summary()` can mutate a tier's counts in place, undermining the "immutable snapshot" reasoning `DrReadinessSummary.tiers` (a tuple) explicitly documents for itself.
  evidence: Surfaced by Story 18's blind-hunter review. Confirmed to match `ledger_core/briefing.py`'s `Briefing.data_quality_issues` (also a plain mutable `dict[str, dict[str, int]]` field on a frozen dataclass) -- a pre-existing, cross-cutting pattern in this project, not unique to Story 18. Worth a dedicated pass across both if ever fixed, not a one-off patch.
- source_spec: `_bmad-output/specs/spec-rez-ops/stories/18-dr-readiness-summary-query.md`
  summary: `dr_readiness.py`'s `artifacts_by_tier[tier_name].append(...)` indexes the dict directly rather than defensively, relying implicitly on `load_tiers`'s own validation to guarantee every assignment's tier name is declared. If that upstream invariant is ever relaxed, this fails with a bare, unattributed `KeyError`.
  evidence: Surfaced by Story 18's blind-hunter review. No realistic trigger today -- `load_tiers` already rejects an assignment naming an undeclared tier (`TiersFileError`, Story 17).
- source_spec: `_bmad-output/specs/spec-rez-ops/stories/18-dr-readiness-summary-query.md`
  summary: `get_dr_readiness_summary`'s per-artifact loop calls `projection.get_record`, which internally re-reads/re-parses `rezops.tiers.yaml` via its own `load_tiers` call -- if the config file changes (or becomes malformed) between the function's own initial `load_tiers` call and a later iteration's `get_record` call, that later call could raise `TiersFileError`, contradicting the function's documented never-raises-for-a-missing-file contract (a malformed file was always documented to raise, per Story 17's fail-loudly design -- this is specifically about the file changing *mid-computation*).
  evidence: Surfaced by Story 18's edge-case-hunter review. Requires a genuine race (external file mutation during a single synchronous call) -- narrow, single-process, local-first v1 has no concurrent writers expected, same risk category as other already-accepted race-window items in this project.
- source_spec: `_bmad-output/specs/spec-rez-ops/stories/18-dr-readiness-summary-query.md`
  summary: Tier-naming convention inconsistency in `rezops.tiers.yaml`: `platinum`/`gold`/`silver` are single lowercase words, but the two tiers this story added, `infrastructure`/`data_centre`, mix in snake_case -- inconsistent for values now displayed side-by-side in the same `tiers` list.
  evidence: Surfaced by Story 18's blind-hunter review. Cosmetic, no functional impact.
- source_spec: `_bmad-output/specs/spec-rez-ops/stories/19-dr-test-achievement-signals.md`
  summary: `load_testing_window` (`ledger_core/projection.py`) has no defensive handling for `OSError` (permission-denied, a directory instead of a file, non-UTF-8 content, or the file vanishing after its own `exists()` check) -- an uncaught exception would crash `get_record`/`list_records` instead of raising the typed `TestingWindowFileError`.
  evidence: Surfaced by Story 19's edge-case-hunter review. Confirmed to match `load_tiers`'s identical pre-existing gap (Story 17) -- not new to this story, same unfixed class of issue.
- source_spec: `_bmad-output/specs/spec-rez-ops/stories/19-dr-test-achievement-signals.md`
  summary: `_achieved_pct`'s `target / actual` true-division could in principle raise `OverflowError` for an astronomically large `int` pair.
  evidence: Surfaced by Story 19's edge-case-hunter review. No realistic trigger with real recovery-time data (minutes, not googol-scale integers) -- same category as other already-accepted "no defensive check, no realistic trigger" gaps in this project.
