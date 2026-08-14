---
title: 'Shared schema + ledger-core foundation'
type: 'feature'
created: '2026-08-14'
status: 'done'
review_loop_iteration: 0
baseline_commit: '1dbec4fceb8677c5359bf32263a70dd86a48915a'
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/specs/spec-rez-ops/SPEC.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Rez Ops has no code yet. Before any connector can report data, there must be a shared schema that separates connector-writable facts from ledger-core-computed state, and an append-only log whose replay is the only source of current state (SPEC CAP-1; AD-3, AD-4, AD-9).

**Approach:** Stand up the repo as a `uv`-managed Python project at the repo root, implement the `RawFact`/`LedgerRecord` schema split as a shared module, and implement ledger-core's append-only event log plus a pure projection function, exercised entirely against synthetic facts — no real connector exists yet.

## Boundaries & Constraints

**Always:**
- Ledger state is mutated only by appending an event to the per-artifact-type log; current state is always recomputed by replaying the log, never hand-edited (AD-3).
- `RawFact` (connector-writable: raw data + a `source` reference) and `LedgerRecord` (ledger-core-only, computed: `last_verified`, `verification_method`, `expiry_rule`, `tier_sla`, `escalation_owner`, `confidence`) are two distinct classes in `shared/ledger_schema/`; nothing may construct a `RawFact` carrying a `LedgerRecord`-only field (AD-9).
- Event logs are git-committed, human-readable markdown at `ledger_data/{artifact_type}.log.md`, one line per event (AD-3, Consistency Conventions).
- Python 3.13+, `mcp` SDK pinned to `1.29.x` (`<2`) — per ARCHITECTURE-SPINE.md Stack.

**Ask First:**
- Introducing any third-party dependency beyond `mcp` (e.g. `pydantic`) — default to stdlib `dataclasses` unless there's a concrete reason it doesn't hold up.
- Deviating from the markdown event-log format specified above, if it proves impractical for the projection engine.

**Never:**
- No real connector in this story (calendar/ticketing/git/CMDB are Stories 2 and 5).
- No MCP tool beyond a read/query surface — no write or mutation tool yet.
- No confidence-scoring formula beyond "unknown when unverified" — the actual method is explicitly deferred (ARCHITECTURE-SPINE.md Deferred).
- No network calls.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| New RawFact ingested | `RawFact(artifact_type="test_artifact", artifact_id="x1", source="synthetic:test", fields={...})` appended | Event appended to `ledger_data/test_artifact.log.md`; projection returns a `LedgerRecord` for `x1` with `confidence="unknown"` until a verification event exists | N/A |
| Conflicting RawFacts for the same artifact | Two RawFacts, same `artifact_id`, differing `fields` | Both events appended — nothing overwritten; projection reflects the latest, prior versions remain in log history | N/A |
| RawFact attempts a LedgerRecord-only field | Constructing `RawFact` with a `confidence` or `tier_sla` key | Rejected at construction | Raises a typed validation error; nothing is appended to the log |
| Query for an artifact with no recorded facts | `get_record("test_artifact", "missing")` | Returns a `LedgerRecord` with `confidence="unknown"` and other fields empty | Never raises |
| Fresh replay reproduces state | Log file has multiple prior events, no in-memory cache | Projection reconstructs identical state from a clean read | N/A |

</frozen-after-approval>

## Code Map

- `pyproject.toml` -- new: `uv`-managed project, Python `>=3.13`, dependency `mcp>=1.29,<2`
- `.python-version` -- new: pins `3.13` for `uv`
- `.gitignore` -- new: Python ignores (`.venv/`, `__pycache__/`, `*.pyc`)
- `shared/ledger_schema/__init__.py` -- new: exports `RawFact`, `LedgerRecord`
- `shared/ledger_schema/models.py` -- new: the two schema classes (AD-9 split)
- `ledger_core/__init__.py` -- new: package marker
- `ledger_core/log.py` -- new: `append_event` / `read_events` against `ledger_data/{artifact_type}.log.md`
- `ledger_core/projection.py` -- new: `get_record(artifact_type, artifact_id) -> LedgerRecord`, pure replay over the log
- `ledger_core/server.py` -- new: minimal MCP server (ledger-core is its own server per AD-1/AD-2) exposing one read tool over `projection.py`
- `tests/test_ledger_core.py` -- new: covers the I/O matrix above

## Tasks & Acceptance

**Execution:**
- [x] `pyproject.toml`, `.python-version`, `.gitignore` -- create project scaffold -- establishes the pinned stack before any code
- [x] `shared/ledger_schema/models.py` -- define `RawFact` and `LedgerRecord` as separate dataclasses with field-level validation rejecting cross-contamination -- AD-9
- [x] `ledger_core/log.py` -- append-only writer/reader, one markdown line per event, never rewrites existing lines -- AD-3
- [x] `ledger_core/projection.py` -- pure function replaying a log into current `LedgerRecord` state -- AD-3
- [x] `ledger_core/server.py` -- MCP server scaffold, one `ledger_get_record`-style tool -- AD-1/AD-2
- [x] `tests/test_ledger_core.py` -- unit tests for every I/O matrix row, using synthetic `RawFact`s only

**Acceptance Criteria:**
- Given a fresh clone, when `uv sync` runs, then dependencies install cleanly on Python 3.13+.
- Given the test suite, when `uv run pytest` runs, then all tests pass without any real network access or writes outside `ledger_data/`.
- Given `ledger_core/server.py`, when an MCP client lists its tools, then exactly one read tool is present and no write/mutation tool exists.

## Spec Change Log

## Design Notes

The event log is markdown, not JSON, per ARCHITECTURE-SPINE.md's Consistency Conventions ("memlog-style"): one human-readable line per event, e.g.

```
- (rawfact) 2026-08-14T12:00:00Z source=synthetic:test artifact=test_artifact/x1 fields={"observed": "value"}
```

`projection.get_record` parses these lines back into structured events and folds them into a `LedgerRecord`, so the log stays diffable in git while the projection stays a pure function of it — no separate database, no cached state to go stale.

## Verification

**Commands:**
- `uv sync` -- expected: resolves and installs without error
- `uv run pytest tests/test_ledger_core.py -v` -- expected: all tests pass
- `uv run python -c "import ledger_core.server"` -- expected: imports without error

## Suggested Review Order

**Schema split (AD-9)**

- Entry point: the two classes the whole story hangs on — connector-writable facts vs. ledger-core-only computed state.
  [`models.py:98`](../../../../shared/ledger_schema/models.py#L98)

- The other half of the split — nothing outside ledger-core may construct one of these.
  [`models.py:131`](../../../../shared/ledger_schema/models.py#L131)

- Rejects a `RawFact` field value that isn't JSON-safe, before it ever reaches the log.
  [`models.py:83`](../../../../shared/ledger_schema/models.py#L83)

**Append-only log + projection (AD-3)**

- Writes one immutable markdown line per event; never rewrites an existing line.
  [`log.py:81`](../../../../ledger_core/log.py#L81)

- Reads the log back and parses each line into a structured event, failing loud on corruption.
  [`log.py:112`](../../../../ledger_core/log.py#L112)

- Pure replay: folds the log into current state, skipping any non-`rawfact` event type.
  [`projection.py:16`](../../../../ledger_core/projection.py#L16)

**Input hardening (review findings)**

- Strict charset on `artifact_type`/`artifact_id` — closes both a log-corruption and a path-escape risk.
  [`models.py:67`](../../../../shared/ledger_schema/models.py#L67)

- Same charset guard for `source`, slightly wider to allow `provider:id`-style values.
  [`models.py:75`](../../../../shared/ledger_schema/models.py#L75)

- Rejects a timezone-naive timestamp instead of silently reinterpreting it as UTC.
  [`log.py:69`](../../../../ledger_core/log.py#L69)

- Guards against `ledger_dir` already existing as a non-directory file.
  [`log.py:73`](../../../../ledger_core/log.py#L73)

**MCP surface (AD-1/AD-2)**

- The one read-only tool this story exposes; confirmed FastMCP already converts a raised exception into a structured error result.
  [`server.py:19`](../../../../ledger_core/server.py#L19)

**Peripherals**

- Project scaffold: Python 3.13+, `mcp` pinned `<2`, `pytest` as a dev-only dependency.
  [`pyproject.toml:1`](../../../../pyproject.toml#L1)

- Full I/O-matrix coverage plus the review's hardening tests (charset, JSON-scalar, naive timestamp, non-directory guard, non-rawfact skip, tool invocation, malformed-log detection).
  [`test_ledger_core.py:33`](../../../../tests/test_ledger_core.py#L33)
