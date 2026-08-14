---
title: 'Chat-queryable live state'
type: 'feature'
created: '2026-08-14'
status: 'done'
review_loop_iteration: 0
baseline_commit: 'c5c6042655682f59752c1dc83d132f7269d4906a'
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/specs/spec-rez-ops/SPEC.md'
  - '{project-root}/ledger_core/log.py'
  - '{project-root}/ledger_core/projection.py'
  - '{project-root}/ledger_core/server.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Nothing computes `LedgerRecord.last_verified` yet, and there's no way to ask "what's stale" or "what needs attention" without already knowing every artifact's exact ID — `ledger_get_record` needs an exact lookup, `ledger_get_coverage` only gives counts (SPEC CAP-4).

**Approach:** Populate `last_verified` from the timestamp of the most recent fact recorded for an artifact (already captured in every log event, just never surfaced), and add `ledger_list_records` (optionally filtered by `artifact_type` and/or `confidence`) so the runtime can answer a natural-language query like "what's unknown" or "what hasn't been touched in a while" without pre-knowing artifact IDs. `expiry_rule`, `tier_sla`, and `escalation_owner` stay unset — no tiering or ownership data source exists yet, so a formal SLA-based "what's due" isn't honestly answerable this story.

## Boundaries & Constraints

**Always:**
- `last_verified` is computed exclusively by ledger-core from the latest fact's own timestamp — never accepted as input, never hand-set (same principle as AD-5's confidence rule).
- `ledger_list_records` reuses the existing single-pass fold (`_fold_events_by_artifact`) — no per-artifact re-reads (the same N+1 pattern Story 3 already fixed for coverage).
- A corrupted artifact-type log encountered while listing is isolated to that type, the same way `get_coverage_map` already isolates a `LogFormatError` — never aborts listing for other types.

**Ask First:**
- Any new third-party dependency (none expected).

**Never:**
- No `expiry_rule`, `tier_sla`, or `escalation_owner` computation — no tiering/ownership data source exists yet.
- No `verification_method` value — a folded record can merge fields from more than one fact/source over time, and there's no single honest value to report yet without fabricating one.
- No write-back or mutation — this story only reads and lists.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| First fact populates `last_verified` | One `RawFact` ingested for a fresh artifact | `ledger_get_record` shows `last_verified` matching that event's timestamp | N/A |
| No facts yet | Artifact with zero ingested facts | `last_verified` stays `None`, `confidence="unknown"` (unchanged from Story 1/3) | N/A |
| Multiple facts, `last_verified` tracks the latest | Two facts ingested at different times for the same artifact | `last_verified` matches the second (later) event's timestamp, not the first | N/A |
| List with no filters | 2+ artifact types, several artifacts each | Returns every known artifact across all types | N/A |
| List filtered by `artifact_type` | Filter to one type | Returns only that type's artifacts | N/A |
| List filtered by `confidence` | Filter to `"unknown"` | Returns only matching records (e.g. one ingested with `fields={}`, per Story 3's edge case) | N/A |
| List with a corrupted type present | One artifact-type log fails to parse, others are healthy | Returns results for the healthy types; the corrupted type is isolated, not silently dropped and not fatal to the rest | N/A |
| List filtered to a nonexistent `artifact_type` | No log file for that type | Returns an empty list | Never raises |

</frozen-after-approval>

## Code Map

- `ledger_core/log.py` -- reuse: `LogEvent.timestamp` is the source for `last_verified`; no changes expected
- `ledger_core/projection.py` -- edit: extend the fold to track each artifact's latest event timestamp; set `last_verified` in `get_record`; add `list_records(artifact_type=None, confidence=None, ...)`
- `ledger_core/server.py` -- edit: add `ledger_list_records` tool
- `tests/test_ledger_core.py` -- edit: add tests for every I/O matrix row

## Tasks & Acceptance

**Execution:**
- [x] `ledger_core/projection.py` -- extend `_fold_events_by_artifact` (or an equivalent single-pass helper) to also track each artifact_id's latest event timestamp; set `LedgerRecord.last_verified` in `get_record` from it -- AD-5-style computed-only field
- [x] `ledger_core/projection.py` -- add `list_records(artifact_type=None, confidence=None, *, ledger_dir=...) -> list[LedgerRecord]`, reusing the existing single-pass fold and the same per-type `LogFormatError` isolation `get_coverage_map` already has
- [x] `ledger_core/server.py` -- add `ledger_list_records(artifact_type=None, confidence=None)` tool wrapping `list_records`
- [x] `tests/test_ledger_core.py` -- unit tests for every I/O matrix row

**Acceptance Criteria:**
- Given the full test suite, when `uv run pytest` runs, then all tests pass (Stories 1 through this one).
- Given two facts ingested for the same artifact at different times, when `ledger_get_record` is queried, then `last_verified` matches the later event's timestamp, not the earlier one.
- Given one artifact-type log is corrupted, when `ledger_list_records` runs with no filter, then it still returns every artifact from the healthy types rather than raising.

## Spec Change Log

## Design Notes

`last_verified` is deliberately the only new computed field this story adds — `expiry_rule`/`tier_sla`/`escalation_owner` all require a data source (tiering, ownership) that doesn't exist yet, and fabricating a value for them would violate the never-hide-uncertainty non-negotiable more than leaving them `None` does. The Voice layer (whatever calls these tools) can still answer "what hasn't been touched in a while" by comparing `last_verified` timestamps itself — that's a relative judgment, not a formal SLA rule, and this story doesn't need to encode one.

## Verification

**Commands:**
- `uv sync` -- expected: resolves and installs without error (no new dependency expected)
- `uv run pytest -v` -- expected: all tests pass, including Stories 1, 2, and 3
- `uv run python -c "import ledger_core.server"` -- expected: imports without error

## Suggested Review Order

**`last_verified` (the new computed field)**

- `get_record` now sets `last_verified` from the latest folded event -- entry point for this story's first change.
  [`projection.py:97`](../../../../ledger_core/projection.py#L97)

**`list_records` (the new query surface, and where review found the real gap)**

- Filters by type and/or confidence, reusing the single-pass fold -- no per-artifact re-reads.
  [`projection.py:230`](../../../../ledger_core/projection.py#L230)

- A corrupted type now surfaces as a visible sentinel record, matching `get_coverage_map`'s guarantee -- this was silent exclusion before review caught it.
  [`projection.py:260`](../../../../ledger_core/projection.py#L260)

- Shared exclusion rule for reserved/empty type names, now applied consistently whether discovering types or filtering to one explicitly.
  [`projection.py:189`](../../../../ledger_core/projection.py#L189)

**MCP surface**

- `ledger_list_records` tool, the fourth and last tool this ledger-core exposes so far.
  [`server.py:100`](../../../../ledger_core/server.py#L100)

**Peripherals**

- Regression test proving the corrupted-type sentinel actually surfaces through the real MCP tool call, not just the function.
  [`test_ledger_core.py:1398`](../../../../tests/test_ledger_core.py#L1398)

- The `artifact_type` + `confidence` AND-filter interaction, previously untested.
  [`test_ledger_core.py:1244`](../../../../tests/test_ledger_core.py#L1244)
