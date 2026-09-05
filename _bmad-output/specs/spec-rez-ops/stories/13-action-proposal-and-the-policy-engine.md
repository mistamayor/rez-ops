---
title: 'ActionProposal and the Policy Engine'
type: 'feature'
created: '2026-09-05'
status: 'done'
review_loop_iteration: 0
baseline_commit: '8f73527b99bc979b11b9b03cb26e8a93fca65332'
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/specs/spec-rez-ops/SPEC.md'
  - '{project-root}/ledger_core/evidence.py'
  - '{project-root}/ledger_core/log.py'
  - '{project-root}/ledger_core/drafts.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Voice can observe state and draft human-readable content, but has no way to propose a system-state-changing *action* with a computed judgment on whether it needs approval — and critically, nothing guarantees that judgment is computed by ledger-core rather than asserted by the LLM itself. SPEC CAP-10 has no implementation.

**Approach:** Add `ActionProposal` (action, target, reason, evidence citations, impact, `policy_decision`) plus a ledger-core write tool. `action` must be a key declared in a new `rezops.policy.yaml` (each entry declaring that action's `impact`: `low`/`medium`/`high`) — never freeform. Ledger-core — never Voice — computes both `impact` (copied from the action's config-declared value) and `policy_decision` (`automatic`/`requires_approval`/`denied`) from: the minimum `confidence` across every cited `EvidenceBundle` (Story 12), and whether the target's `tier_sla` is currently known (it never is yet — AD-9 — so criticality always resolves to its most conservative reading in today's real data, honestly, not a bug). Unlike `Draft`/`EvidenceBundle` (one file, created-only), a proposal has a lifecycle — proposed, then decided — implemented as two events appended to one flat log, extending AD-3's discipline; both events are written by the same tool call, since there is no separate later approval step in this phase. No executor: `policy_decision` is recorded, never acted on.

## Boundaries & Constraints

**Always:**
- `action` must be a key in `rezops.policy.yaml`; naming anything else is rejected before anything is appended.
- A proposal must cite at least one `EvidenceBundle` by its `evidence_id`; every cited id must resolve to a bundle that actually exists (checked via Story 12's `list_evidence`) — citing zero, or an id that doesn't exist, is rejected.
- `impact` and `policy_decision` are computed exclusively by ledger-core — never accepted as caller-supplied values. Either being present in the caller's input is a schema violation, exactly like a connector-supplied `tier_sla` (AD-9) or a caller-supplied `EvidenceBundle.confidence` (AD-11, Story 12).
- `policy_decision` is `denied` if the minimum confidence across cited bundles is below `0.5`; `automatic` only if the action's impact is `low` AND the target's `tier_sla` is currently known AND minimum confidence is exactly `1.0`; `requires_approval` otherwise. Deterministic, same inputs always produce the same decision.
- Both a `proposed` and a `decided` event are appended to `ledger_data/action_proposals.log.md` by the same tool call — current state is a projection over that log, never a hand-edited field.

**Ask First:**
- Any dependency beyond what's already direct.

**Never:**
- No executor of any kind. `policy_decision` is recorded and returned to the caller — nothing in this story consumes it to perform the action, not an external call, not an internally-triggered `Draft` write, not any other component's write path.
- No retry/resubmission or update to an existing proposal — create (which always immediately decides) is the only operation this story adds.
- No validation that `target`'s artifact actually exists beyond resolving its (possibly empty/unknown) `LedgerRecord` — same non-validation precedent `create_draft` already established for its own `artifact_type`/`artifact_id`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Low-confidence evidence | Minimum cited confidence `< 0.5` | `policy_decision: "denied"` | N/A |
| Perfect confidence, low impact, known criticality | Min confidence `1.0`, action's impact `low`, target's `tier_sla` is set | `policy_decision: "automatic"` | N/A |
| Perfect confidence, but criticality unknown | Min confidence `1.0`, action's impact `low`, target's `tier_sla` is `None` (today's universal case) | `policy_decision: "requires_approval"` — never guessed as automatic | N/A |
| High-impact action | Action's impact is `high`, any confidence `>= 0.5` | `policy_decision: "requires_approval"` (never `automatic` for a non-`low`-impact action) | N/A |
| Undeclared action | `action` isn't a key in `rezops.policy.yaml` | Rejected, nothing appended | Raises a typed validation error |
| No evidence cited | `evidence=[]` | Rejected, nothing appended | Raises a typed validation error |
| Nonexistent evidence_id cited | Citing an id with no matching bundle | Rejected, nothing appended | Raises a typed validation error |
| Caller supplies `impact`/`policy_decision` | Any value | Ignored/rejected — computed values only, nothing appended if the tool signature can't express them | Raises a typed validation error where the signature allows the argument at all |
| Multiple cited bundles, mixed confidence | Bundles with confidence `1.0`, `0.5`, `0.9` cited together | Uses `0.5` (the minimum), not an average | N/A |
| List with no proposals yet | `ledger_data/action_proposals.log.md` doesn't exist | Returns an empty list | Never raises |

</frozen-after-approval>

## Code Map

- `ledger_core/evidence.py` -- reuse: `list_evidence(ledger_dir=...)` to resolve cited `evidence_id`s to real bundles and read their `confidence`
- `ledger_core/log.py` -- reuse as pattern (read, not imported): append-only-write discipline (open in a mode that never truncates); this story's own event-line format differs from `RawFact`'s, so its reader/writer are new, not reused
- `ledger_core/projection.py` -- reuse: `get_record(artifact_type, artifact_id)` to read the target's `tier_sla`
- `rezops.policy.yaml` -- new: per-action `impact` declarations (repo-root, git-tracked, inputs only -- ledger-core evaluates); seed with two example actions (`create_ticket`: `impact: low`, `disable_credential`: `impact: high`) so the story is concretely testable
- `ledger_core/action_proposals.py` -- new: `ActionProposal`, `create_action_proposal(...)`, `list_action_proposals(...)`, the policy-decision rule, and the new append-only log's own line format/parser
- `ledger_core/server.py` -- edit: add `ledger_create_action_proposal` and `ledger_list_action_proposals` MCP tools
- `tests/test_action_proposals.py` -- new: unit tests for every I/O matrix row

## Tasks & Acceptance

**Execution:**
- [x] `rezops.policy.yaml` -- create with `create_ticket` (`impact: low`) and `disable_credential` (`impact: high`)
- [x] `ledger_core/action_proposals.py` -- implement `ActionProposal` (`proposal_id`, `action`, `target_artifact_type`, `target_artifact_id`, `reason`, `evidence: tuple[str, ...]` of evidence_ids, `impact`, `policy_decision`, `proposed_at`, `decided_at`); `create_action_proposal(action, target_artifact_type, target_artifact_id, reason, evidence, *, ledger_dir=...)` (validates action against `rezops.policy.yaml`, validates evidence ids resolve via `list_evidence`, computes minimum confidence, reads target's `tier_sla` via `get_record`, computes `impact`/`policy_decision` per the frozen rule, appends `proposed` then `decided` events to `ledger_data/action_proposals.log.md`); `list_action_proposals(*, ledger_dir=...)` (folds the log into current per-proposal state, one record per `proposal_id`) -- AD-12
- [x] `ledger_core/server.py` -- add `ledger_create_action_proposal` and `ledger_list_action_proposals` MCP tools; neither accepts `impact` or `policy_decision` parameters
- [x] `tests/test_action_proposals.py` -- unit tests for every I/O matrix row, including one proving the returned `policy_decision` is deterministic across repeated identical inputs

**Acceptance Criteria:**
- Given the full test suite, when `uv run pytest` runs, then all tests pass.
- Given three cited `EvidenceBundle`s with confidence `1.0`, `0.5`, and `0.9`, when a proposal citing all three is created, then the decision logic uses `0.5`, not an average or any other aggregation.
- Given the ledger-core MCP server, when a client lists its tools, then `ledger_create_action_proposal` and `ledger_list_action_proposals` both exist alongside the nine existing tools, and no tool in this story ever calls an external write/send API or triggers any other component's write path.

## Spec Change Log

## Design Notes

**`automatic` is expected to never actually occur against today's real data**, since it requires the target's `tier_sla` to be known, and `tier_sla` is never computed by any story so far (AD-9 defers its formula). This is an honest, accepted characteristic of v1, not a bug: the three-way decision exists for when `tier_sla` is eventually computed, and nothing in this story or the next depends on `automatic` actually firing yet, since there's no Executor to consume it regardless.

**Why `0.5` and `1.0` as the two thresholds, specifically:** picked as the simplest, most defensible round numbers that satisfy the frozen invariants (deterministic, minimum-aggregation, unknown-criticality-never-automatic) without pretending to a more precise formula the project doesn't have evidence to justify yet — same spirit as AD-5's confidence formula being deferred rather than over-specified. Revisit once real usage shows these are miscalibrated.

**Two log events per creation, not one combined write:** matches AD-12's literal text ("a `proposed` event... immediately followed by a `decided` event") and keeps the log genuinely event-sourced (not a single-shot record), so a future story that adds a real, separate human-approval step only needs to append a `decided` event later — no format change required.

## Verification

**Commands:**
- `uv sync` -- expected: resolves without error (no new dependency expected) -- ran, resolved with no changes
- `uv run pytest -v` -- expected: all tests pass, including every prior story's -- ran, 494 passed after review fixes
- `uv run python -c "import ledger_core.server"` -- expected: imports without error -- ran, imported cleanly

## Suggested Review Order

**Closing the availability gap review found (the real catch this round)**

- A corrupted `action_proposals.log.md` no longer permanently blocks every future proposal creation -- the id-collision pre-check (defense-in-depth only, never the primary uniqueness mechanism) now tolerates a format error rather than propagating it.
  [`ledger_core/action_proposals.py:553`](../../../../ledger_core/action_proposals.py#L553)

- Proof: creation still succeeds against a log with a corrupted historical line.
  [`tests/test_action_proposals.py:618`](../../../../tests/test_action_proposals.py#L618)

**Closing the `evidence` type foot-gun two reviewers converged on**

- `evidence` must be a list/tuple -- a bare string (which would otherwise silently iterate per-character) or `None` is now rejected explicitly.
  [`ledger_core/action_proposals.py:489`](../../../../ledger_core/action_proposals.py#L489)

- Proof, with a fault-injection check confirming the test actually fails without the fix (not just incidentally, via an unrelated error path).
  [`tests/test_action_proposals.py:323`](../../../../tests/test_action_proposals.py#L323), [`:351`](../../../../tests/test_action_proposals.py#L351)

**Policy-file parser hardening**

- Duplicate field key within one action block, and an inline `#` comment on a field-value line, both now fail loudly instead of silently misparsing.
  [`ledger_core/action_proposals.py:276`](../../../../ledger_core/action_proposals.py#L276), [`:281`](../../../../ledger_core/action_proposals.py#L281)

**Corrupted-log-read hardening**

- A `proposed` event missing a required field, or a duplicate `decided` event for one `proposal_id`, now raise the typed format error instead of a raw `KeyError` or silently overwriting.
  [`ledger_core/action_proposals.py:105`](../../../../ledger_core/action_proposals.py#L105), [`:644`](../../../../ledger_core/action_proposals.py#L644)

- `README.md`'s tool count was stale since Story 12 (still said 7); now lists all 11.
