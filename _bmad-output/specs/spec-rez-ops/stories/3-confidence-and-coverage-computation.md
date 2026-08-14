---
title: 'Confidence and coverage computation'
type: 'feature'
created: '2026-08-14'
status: 'done'
review_loop_iteration: 0
baseline_commit: 'ef13ed703d5876d1fc14393cf3544acdd9bbe152'
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/specs/spec-rez-ops/SPEC.md'
  - '{project-root}/ledger_core/log.py'
  - '{project-root}/ledger_core/projection.py'
  - '{project-root}/ledger_core/server.py'
  - '{project-root}/connectors/git_repo/server.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Ledger-core can read state (Story 1) and one Sensor can produce real facts (Story 2), but nothing connects them, and confidence is hardcoded to `"unknown"` for every record regardless of what's actually known (SPEC CAP-3; AD-5).

**Approach:** Add an ingestion tool to ledger-core so a real `RawFact` (e.g. from the git connector) can actually be appended to the log, replace the hardcoded confidence with a first real (intentionally simple) computation — `"agent-verified"` if at least one fact exists for an artifact, `"unknown"` if none — and add a coverage-map tool grouping confidence counts by `artifact_type` only (no tier dimension yet; no tiering data source exists).

## Boundaries & Constraints

**Always:**
- Confidence is computed exclusively by `projection.get_record`, never accepted as input — the new ingestion tool has no `confidence` parameter, and `RawFact` already rejects one (Story 1, AD-9).
- The ingestion tool's only side effect is calling the existing `append_event` (AD-3) — no other file write, no direct log-file manipulation.
- The coverage map groups by `artifact_type` only. No tier/SLA dimension in this story.
- Reserved/internal log filenames (leading underscore, e.g. a future `_ops.log.md`) are excluded from the coverage map and never treated as an artifact type.

**Ask First:**
- Any new third-party dependency (none is expected for this story).

**Never:**
- No `"manual"` confidence value yet — no human-entry path exists, so confidence is effectively binary (`agent-verified` / `unknown`) in this story.
- No tier/SLA computation — that needs a tiering data source that doesn't exist yet (Story 5+).
- No write-back to the connector or any external system — ingestion only ever writes to `ledger_data/`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| End-to-end: connector fact ingested | Call the git connector's `git_get_last_touched` for a real file in this repo, feed its output into `ledger_ingest_raw_fact` | A subsequent `ledger_get_record` for that artifact shows `confidence="agent-verified"` and the ingested fields | N/A |
| Query before any fact exists | `ledger_get_record` for an artifact with zero ingested facts | `confidence="unknown"`, empty fields (unchanged from Story 1) | N/A |
| Ingest payload violates the schema | Ingest call with a `fields` payload containing a `LedgerRecord`-only key (e.g. `confidence`) | No event appended | Returns a structured MCP error (`isError=True`), server does not crash |
| Coverage map, multiple types and confidence states | Facts ingested across 2+ `artifact_type`s, some artifacts with facts and some queried with none | Returns a per-`artifact_type` tally of confidence counts matching what `ledger_get_record` would report for each artifact | N/A |
| Coverage map with no data yet | `ledger_data/` doesn't exist or is empty | Returns an empty coverage map | Never raises |
| Coverage map ignores reserved logs | A `_something.log.md` file exists alongside real artifact-type logs | Excluded from the coverage map entirely | N/A |

</frozen-after-approval>

## Code Map

- `shared/ledger_schema/models.py` -- reuse: `RawFact` construction target; read-only, no changes expected
- `ledger_core/log.py` -- reuse: `append_event` is the ingestion tool's only write path; no changes expected
- `ledger_core/projection.py` -- edit: replace the hardcoded `confidence="unknown"` in `get_record` (currently line 49) with the has-any-fact check; add `get_coverage_map`
- `ledger_core/server.py` -- edit: add `ledger_ingest_raw_fact` and `ledger_get_coverage` tools alongside the existing `ledger_get_record`
- `connectors/git_repo/server.py` -- reuse as a real data source in the end-to-end test (call `git_get_last_touched` directly, feed its return value into the new ingestion tool)
- `tests/test_ledger_core.py` -- edit: add tests for every I/O matrix row

## Tasks & Acceptance

**Execution:**
- [ ] `ledger_core/projection.py` -- replace the hardcoded confidence with `"agent-verified"` when `fields` is non-empty, else `"unknown"`; add `get_coverage_map(ledger_dir=...)` that groups confidence counts by `artifact_type`, skipping any log filename starting with `_` -- AD-5
- [ ] `ledger_core/server.py` -- add `ledger_ingest_raw_fact(artifact_type, artifact_id, source, fields)` (constructs a `RawFact`, calls `append_event`, lets schema-validation failures surface as structured MCP errors) and `ledger_get_coverage()` wrapping `get_coverage_map` -- AD-1, AD-2, AD-5
- [ ] `tests/test_ledger_core.py` -- unit tests for every I/O matrix row, including one end-to-end test that calls the real git connector tool and ingests its actual output

**Acceptance Criteria:**
- Given the full test suite, when `uv run pytest` runs, then all tests pass (Stories 1, 2, and this one).
- Given a `RawFact` is ingested for an artifact with zero prior facts, when `ledger_get_record` is queried afterward, then `confidence` is `"agent-verified"` and `fields` reflects the ingested data.
- Given the ledger-core MCP server, when a client lists its tools, then exactly three tools exist (`ledger_get_record`, `ledger_ingest_raw_fact`, `ledger_get_coverage`) and none of them writes anywhere outside the append-only log.

## Spec Change Log

## Design Notes

The confidence rule is deliberately the simplest thing that could work — `agent-verified` iff at least one fact was ever observed, `unknown` otherwise — not the real scoring method (AD-5 fixes *who* computes confidence, not the formula; the formula itself stays an open item in `ARCHITECTURE-SPINE.md`'s Deferred section). This story exists to make confidence real and demonstrable end-to-end, not to finalize its logic.

## Verification

**Commands:**
- `uv sync` -- expected: resolves and installs without error (no new dependency expected)
- `uv run pytest -v` -- expected: all tests pass, including Stories 1 and 2
- `uv run python -c "import ledger_core.server"` -- expected: imports without error

## Suggested Review Order

**Confidence and coverage (the core of this story)**

- The whole rule: `agent-verified` iff any field was ever observed, else `unknown`.
  [`projection.py:33`](../../../../ledger_core/projection.py#L33)

- Single-pass fold per artifact type -- confidence for every artifact_id computed from one log read, not one per artifact.
  [`projection.py:46`](../../../../ledger_core/projection.py#L46)

- Grouped tally by `artifact_type`; one bad log's `LogFormatError` is isolated to its own type rather than blocking every other type's coverage (AD-8).
  [`projection.py:111`](../../../../ledger_core/projection.py#L111)

**Closing the loop: connector data into the ledger**

- The new write path -- ledger-core's only way to receive a real fact, still gated entirely by `RawFact`'s existing schema validation.
  [`server.py:48`](../../../../ledger_core/server.py#L48)

- Proof this is real, not simulated: ingests the git connector's actual tool output and checks confidence flips to `agent-verified`.
  [`test_ledger_core.py:471`](../../../../tests/test_ledger_core.py#L471)

**Peripherals**

- The read surface added alongside `ledger_get_record`; now three tools total, still none of them writing outside the log.
  [`server.py:80`](../../../../ledger_core/server.py#L80)

- Regression coverage for the two robustness fixes review surfaced: one corrupted type doesn't blind the rest, and reads aren't duplicated per artifact.
  [`test_ledger_core.py:749`](../../../../tests/test_ledger_core.py#L749)
