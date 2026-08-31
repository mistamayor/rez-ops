---
title: 'Ownership inference and arbitration'
type: 'feature'
created: '2026-08-26'
status: 'done'
review_loop_iteration: 0
baseline_commit: '384d33f6b20f0694cf172332bd3695db677471c2'
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/specs/spec-rez-ops/SPEC.md'
  - '{project-root}/shared/ledger_schema/models.py'
  - '{project-root}/ledger_core/projection.py'
  - '{project-root}/ledger_core/server.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `LedgerRecord.escalation_owner` has never been computed (SPEC CAP-5) — three of the four connectors already carry an ownership-adjacent signal under different field names (CMDB's `support_group`, ticketing's `assigned_to`, calendar's `organizer_email`), but nothing picks an authoritative one, and nothing flags an artifact that has no ownership signal at all.

**Approach:** Ledger-core computes `escalation_owner` from a fixed priority order — `support_group` (CMDB, most authoritative: the canonical "who supports this system" record) → `assigned_to` (ticketing: who's handling an active issue, may be transient) → `organizer_email` (calendar: weakest signal, just who scheduled a meeting). Git's `author` is excluded — it means "who last touched this," not "who owns this." Orphan-risk is computed, not stored: an artifact with observed facts but no resolved owner. Extends `list_records`/`ledger_list_records` with an `orphan_risk` filter rather than adding a new tool, reusing Story 4's existing query infrastructure.

## Boundaries & Constraints

**Always:**
- `escalation_owner` is computed exclusively by ledger-core from the fixed field-priority order, never accepted as input, never set by a connector (AD-5/AD-9 principle applied to ownership).
- Lower-priority ownership-adjacent fields remain visible in `fields` even when a higher-priority one wins — nothing is deleted or hidden, only not selected as `escalation_owner`.
- Orphan-risk is computed at query time (`fields` non-empty AND `escalation_owner` is `None`) — never a stored or cached flag, consistent with how confidence and coverage are already pure functions of the log.
- An artifact with entirely empty `fields` (never observed at all) is not orphan-risk — orphan-risk means "known but unowned," not "unknown."

**Ask First:**
- Any dependency beyond what's already direct.

**Never:**
- No literal HRIS/org-chart connector in this story — the priority order is fixed for the four real connectors' actual field names, not a configurable/pluggable priority system.
- No mutation of historical log entries — both `escalation_owner` and orphan-risk are purely derived from the existing log, nothing is rewritten.
- No auto-notification or auto-escalation action for an orphan-risk artifact — that's future work (draft-not-send), not this story.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Single ownership signal | Only `support_group` present in folded fields | `escalation_owner` = that value | N/A |
| Single lower-priority signal | Only `assigned_to` present | `escalation_owner` = that value | N/A |
| Multiple signals, priority wins | Both `support_group` and `assigned_to` present (e.g. a CMDB fact and a ticketing fact ingested for the same artifact) | `escalation_owner` = the `support_group` value; `assigned_to` remains visible in `fields`, not discarded | N/A |
| All three signals present | `support_group`, `assigned_to`, `organizer_email` all present | `escalation_owner` = `support_group`'s value (highest priority) | N/A |
| No ownership signal, but other facts exist | `fields` non-empty (e.g. only git's `author`/`commit_sha`) but none of the three priority fields present | `escalation_owner` is `None`; artifact appears in the orphan-risk filter | N/A |
| Never observed | `fields` entirely empty | `escalation_owner` is `None`; artifact does NOT appear in the orphan-risk filter | N/A |
| Resolved artifact excluded from orphan-risk | An artifact with a resolved `escalation_owner` | Does not appear when `list_records(orphan_risk=True)` | N/A |
| No orphans at all | Every known artifact has a resolved owner | `orphan_risk=True` filter returns an empty list | Never raises |
| End-to-end, real connectors | Ingest a real CMDB fact and a real ticketing fact (via the actual connector tools) for the same artifact | `escalation_owner` resolves to the CMDB value | N/A |

</frozen-after-approval>

## Code Map

- `shared/ledger_schema/models.py` -- reuse: `LedgerRecord.escalation_owner` is the target field; read-only, no changes expected
- `ledger_core/projection.py` -- edit: add `_OWNERSHIP_FIELD_PRIORITY` and `_compute_escalation_owner`; set `escalation_owner` in `get_record`; extend `list_records` with an `orphan_risk: bool | None` filter
- `ledger_core/server.py` -- edit: extend `ledger_list_records` with the `orphan_risk` parameter
- `connectors/ticketing/server.py`, `connectors/calendar_google/server.py`, `connectors/cmdb/server.py` -- reuse as real data sources for the end-to-end test; no changes expected
- `tests/test_ledger_core.py` -- edit: add tests for every I/O matrix row

## Tasks & Acceptance

**Execution:**
- [x] `ledger_core/projection.py` -- add `_OWNERSHIP_FIELD_PRIORITY = ("support_group", "assigned_to", "organizer_email")` and `_compute_escalation_owner(fields)`; set `escalation_owner` in `get_record` from it -- AD-10
- [x] `ledger_core/projection.py` -- extend `list_records` with `orphan_risk: bool | None = None`, filtering to records where `fields` is non-empty and `escalation_owner` is `None` (when `True`), or the inverse (when `False`)
- [x] `ledger_core/server.py` -- extend `ledger_list_records`'s signature and docstring with the new `orphan_risk` parameter
- [x] `tests/test_ledger_core.py` -- unit tests for every I/O matrix row, including one end-to-end test using the real CMDB and ticketing connector tools' output

**Acceptance Criteria:**
- Given the full test suite, when `uv run pytest` runs, then all tests pass.
- Given an artifact with both `support_group` and `assigned_to` present, when `ledger_get_record` is queried, then `escalation_owner` matches `support_group` and `assigned_to` is still present in `fields`.
- Given `ledger_list_records(orphan_risk=True)`, when no artifact qualifies, then it returns an empty list without raising.

## Spec Change Log

## Design Notes

The priority order (CMDB > ticketing > calendar) is a judgment call, not derived from anything in the architecture spine — CMDB's support-group assignment is treated as the closest real-world proxy to "who is accountable for this system," ticketing's assignee as "who's currently on it" (useful but transient), and calendar organizer as the weakest signal (just who happened to schedule something). This ordering is a fixed constant in code, not user-configurable in this story — revisit if a real DR program's actual ownership semantics turn out to disagree.

## Verification

**Commands:**
- `uv sync` -- expected: resolves without error (no new dependency expected) -- ran, resolved with no changes
- `uv run pytest -v` -- expected: all tests pass, including every prior story's -- ran, 328 passed after review fixes
- `uv run python -c "import ledger_core.server"` -- expected: imports without error -- ran, imported cleanly

## Suggested Review Order

**The arbitration logic (where review found the real bug)**

- The whole rule, fixed to treat blank/whitespace-only values as absent, not just `None` -- this is what makes orphan-risk detection actually work against real ServiceNow data.
  [`projection.py:56`](../../../../ledger_core/projection.py#L56)

- Root cause fix in a different file entirely: CMDB could never ingest a legitimately unassigned CI before this.
  [`connectors/cmdb/server.py:336`](../../../../connectors/cmdb/server.py#L336)

- Proof: a blank `assigned_to` now falls through to the next-priority field instead of resolving as a blank owner.
  [`test_ledger_core.py:1666`](../../../../tests/test_ledger_core.py#L1666)

- Proof of the root-cause fix: CMDB successfully ingests a CI with `support_group: null`.
  [`test_cmdb_connector.py:784`](../../../../tests/test_cmdb_connector.py#L784)

**The query surface**

- `list_records` extended with `orphan_risk`, computed at query time from `fields` + `escalation_owner`, never stored.
  [`projection.py:286`](../../../../ledger_core/projection.py#L286)

- Three-way filter combination (`artifact_type` + `confidence` + `orphan_risk`), previously untested despite the docstring's AND claim.
  [`test_ledger_core.py:1300`](../../../../tests/test_ledger_core.py#L1300)

**Peripherals**

- `ledger_list_records` tool, now with the fourth filter parameter.
  [`server.py:104`](../../../../ledger_core/server.py#L104)
