---
title: 'Periodic briefing'
type: 'feature'
created: '2026-08-26'
status: 'done'
review_loop_iteration: 0
baseline_commit: '521a5cdbf9c5144481367554945797443a162761'
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/specs/spec-rez-ops/SPEC.md'
  - '{project-root}/ledger_core/projection.py'
  - '{project-root}/ledger_core/drafts.py'
  - '{project-root}/ledger_core/server.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** SPEC CAP-7 has no implementation — there's no single view surfacing "what needs a decision today," even though every piece it needs (orphan-risk artifacts, unverified artifacts, pending drafts) already exists as separate queries.

**Approach:** Add `ledger_get_briefing()`, a pure aggregation over three existing read functions — `list_records(orphan_risk=True)`, `list_records(confidence="unknown")`, and `list_drafts()` — plus a `data_quality_issues` section pulled from `get_coverage_map()`'s existing per-type corruption markers. No new computation logic: this satisfies CAP-7's "must match what a live query returns" requirement by construction, since it *is* the same read path, just composed. Sections are in a **fixed category order** (orphan-risk first, then unknown-confidence, then pending drafts) rather than a computed priority score — there's no tier/SLA data yet to rank by, so this doesn't pretend to. The delivery channel stays entirely out of scope: the tool returns structured data, and whatever calls it decides how to present it.

## Boundaries & Constraints

**Always:**
- `ledger_get_briefing()` calls only existing read functions (`list_records`, `list_drafts`, `get_coverage_map`) — it computes nothing new about artifact state itself.
- Section order is fixed: orphan-risk, unknown-confidence, pending drafts, data-quality issues. Not a computed ranking.
- The briefing is read-only — no state is created, modified, or sent anywhere.
- `generated_at` is included so a caller can tell how fresh the briefing is.

**Ask First:**
- Any dependency beyond what's already direct.

**Never:**
- No delivery-channel implementation (no Slack, email, or any outbound call) — the tool returns data only.
- No new severity/priority scoring — sections are grouped, not ranked by computed risk.
- No pagination or filtering in this story — returns everything, same as `list_records`/`list_drafts`/`get_coverage_map` today.
- No mutation of any kind.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path | A mix of orphan-risk artifacts, unknown-confidence artifacts, and pending drafts exist | All three sections populated correctly | N/A |
| Empty ledger | Nothing has ever been ingested or drafted | All sections empty, `generated_at` still present | Never raises |
| Matches live query: orphan-risk | Same ledger state queried both ways | Briefing's `orphan_risk` section is identical to a direct `list_records(orphan_risk=True)` call at the same point in time | N/A |
| Matches live query: unknown-confidence | Same ledger state queried both ways | Briefing's `unknown_confidence` section is identical to a direct `list_records(confidence="unknown")` call | N/A |
| Matches live query: drafts | Same ledger state queried both ways | Briefing's `pending_drafts` section is identical to a direct `list_drafts()` call | N/A |
| Corrupted artifact-type log present | One artifact type's log is malformed | Surfaces in `data_quality_issues` (via the existing coverage-map marker); the rest of the briefing still generates | N/A |
| Corrupted draft file present | One draft file is malformed | `pending_drafts` still includes it as the existing sentinel record `list_drafts` already produces; briefing doesn't crash | N/A |

</frozen-after-approval>

## Code Map

- `ledger_core/projection.py` -- reuse: `list_records`, `get_coverage_map`; no changes expected
- `ledger_core/drafts.py` -- reuse: `list_drafts`; no changes expected
- `ledger_core/briefing.py` -- new: `get_briefing(*, ledger_dir=...) -> Briefing` composing the above
- `ledger_core/server.py` -- edit: add `ledger_get_briefing` tool
- `tests/test_ledger_core.py` -- edit: add tests for every I/O matrix row

## Tasks & Acceptance

**Execution:**
- [x] `ledger_core/briefing.py` -- implement `Briefing` (a simple dataclass or typed dict: `orphan_risk`, `unknown_confidence`, `pending_drafts`, `data_quality_issues`, `generated_at`) and `get_briefing(*, ledger_dir=...)`, composing `list_records`, `list_drafts`, and `get_coverage_map` with no new computation -- CAP-7
- [x] `ledger_core/server.py` -- add `ledger_get_briefing()` MCP tool wrapping `get_briefing`
- [x] `tests/test_ledger_core.py` -- unit tests for every I/O matrix row, including the three explicit content-matches-live-query assertions

**Acceptance Criteria:**
- Given the full test suite, when `uv run pytest` runs, then all tests pass.
- Given the same ledger state, when `ledger_get_briefing()`'s `orphan_risk`/`unknown_confidence`/`pending_drafts` sections are compared against direct calls to `list_records`/`list_drafts` at the same point in time, then they match exactly.
- Given the ledger-core MCP server, when a client lists its tools, then `ledger_get_briefing` exists alongside the six existing tools and performs no write of any kind.

## Spec Change Log

## Design Notes

A corrupted-log sentinel from `list_records` can, in principle, appear in both the `orphan_risk` and `unknown_confidence` sections if queried under both filters (the sentinel bypasses filters entirely, per Story 8's design) — this story doesn't attempt to deduplicate that across sections; visibility of a real data-quality problem matters more than a tidy briefing, and it's a rare, non-normal-operation case. `data_quality_issues` pulls from `get_coverage_map()` specifically because that already isolates a corrupted type exactly once per type, rather than re-deriving the same signal a second way.

## Verification

**Commands:**
- `uv sync` -- expected: resolves without error (no new dependency expected) -- ran, resolved with no changes
- `uv run pytest -v` -- expected: all tests pass, including every prior story's -- ran, 381 passed after review fixes
- `uv run python -c "import ledger_core.server"` -- expected: imports without error -- ran, imported cleanly

## Suggested Review Order

**Closing the mutable-snapshot gap review found (the real catch this round)**

- `Briefing`'s three sequence fields are now tuples, not lists, and `data_quality_issues`'s per-type tallies are copied, not shared references into `get_coverage_map()`'s internals -- a frozen dataclass alone doesn't stop a caller mutating (or aliasing into) what's meant to be an immutable snapshot.
  [`briefing.py:110`](../../../../ledger_core/briefing.py#L110)

- Same gap closed a second time at the MCP boundary: the tool's `dict()` conversion was only a shallow copy, leaving nested tally dicts as shared references at the response layer too.
  [`server.py:280`](../../../../ledger_core/server.py#L280)

**Consolidating the dict-building logic three review layers converged on**

- `_record_to_dict`/`_draft_to_dict` now defined once and reused by all five tools that need them, replacing three independent copies (two inline, one added just for this story).
  [`server.py:35`](../../../../ledger_core/server.py#L35), [`:56`](../../../../ledger_core/server.py#L56)

- Tests now import and call the real helpers instead of maintaining an independent copy that could silently drift out of sync.
  [`test_ledger_core.py:3459`](../../../../tests/test_ledger_core.py#L3459)

**The aggregation itself**

- `get_briefing` -- pure composition of four existing read functions, no new computation.
  [`briefing.py:94`](../../../../ledger_core/briefing.py#L94)

- Proof: two simultaneously-corrupted artifact types both surface in `data_quality_issues`, not just the first.
  [`test_ledger_core.py:3337`](../../../../tests/test_ledger_core.py#L3337)

- The new MCP tool, bringing ledger-core to seven total.
  [`server.py:256`](../../../../ledger_core/server.py#L256)
