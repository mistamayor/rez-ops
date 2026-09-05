---
title: 'Evidence boundary'
type: 'feature'
created: '2026-09-05'
status: 'done'
review_loop_iteration: 0
baseline_commit: 'edc316da979238b65af2ce52b8381327b8a5d55d'
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/specs/spec-rez-ops/SPEC.md'
  - '{project-root}/ledger_core/drafts.py'
  - '{project-root}/ledger_core/projection.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Voice has no way to make a reasoning-layer claim ("this runbook looks stale") as anything other than unattributed chat prose — no structured link back to the facts that justified it, and no honest measure of how well those facts actually support the claim. SPEC CAP-9 has no implementation.

**Approach:** Add `EvidenceBundle` (claim, confidence, evidence citations, reasoning, generated_at) plus a ledger-core write tool that creates one. Each citation (`EvidenceRef`) names one artifact (`artifact_type`/`artifact_id`) and either the `source` of a specific ingested `RawFact` or the name of a computed `LedgerRecord` field — never both, never neither. `confidence` is never accepted from the caller: ledger-core computes it itself, as the fraction of citations that actually resolve against current ledger state (a source-citation resolves if that artifact's log contains an event with that exact source; a field-citation resolves if that artifact's current record has a non-empty value for that field). A bundle citing nothing that resolves gets `confidence: 0.0` — computed and shown, never blocked, matching this project's standing refusal to hide bad states rather than surface them.

## Boundaries & Constraints

**Always:**
- `EvidenceBundle`'s `confidence` is computed exclusively by ledger-core at creation time, from the cited evidence — never accepted as a caller-supplied value (AD-11, extending AD-5's ledger-core-exclusive-computation principle). A caller-supplied `confidence` field is a schema violation, exactly like a connector-supplied `tier_sla` (AD-9).
- Every `EvidenceRef` is a structured object — `artifact_type`, `artifact_id`, and exactly one of `source`/`field` — never a bare string.
- A bundle must cite at least one `EvidenceRef`; citing zero is invalid (an "evidence-backed claim" with no evidence is a contradiction).
- Persistence goes only through this story's new ledger-core write tool, one file per bundle, created-only (no update/delete) — mirrors `Draft`'s lifecycle (AD-6), not `ActionProposal`'s (AD-12, a later story), since a bundle is never itself approved or denied.

**Ask First:**
- Any dependency beyond what's already direct.

**Never:**
- No validation that a citation's underlying fact/field still exists at *read* time — resolution is checked once, at creation, and the result (resolved or not) is baked into the confidence score computed then; a bundle is a point-in-time snapshot, like a `LedgerRecord`.
- No interpretation of `claim`/`reasoning` content — opaque caller-supplied text, never inspected or templated.
- No `ActionProposal` in this story — that's Story 13, which depends on this one.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| All citations resolve | Every `EvidenceRef` matches a real ingested source or a populated record field | `confidence: 1.0` | N/A |
| Some citations resolve | 2 of 3 citations resolve | `confidence: 0.667` (fraction resolved, not rounded to a coarse bucket) | N/A |
| No citations resolve | Every citation is stale/wrong | `confidence: 0.0` — bundle is still created, not rejected | N/A |
| Source-citation | `EvidenceRef{artifact_type, artifact_id, source}` | Resolves if that artifact's log has an event with that exact `source` | N/A |
| Field-citation | `EvidenceRef{artifact_type, artifact_id, field}` | Resolves if `get_record(artifact_type, artifact_id)` has a non-empty value for `field` | N/A |
| Corrupted artifact-type log for a cited artifact | The citation's artifact_type log is malformed | That citation counts as unresolved (fails open, doesn't crash bundle creation — AD-8) | N/A |
| Empty evidence list | `evidence=[]` | Rejected, nothing written | Raises a typed validation error |
| Caller supplies `confidence` | Any value | Rejected as a schema violation, nothing written | Raises a typed validation error |
| Empty/whitespace `claim`/`reasoning` | `""` or whitespace-only | Rejected, nothing written | Raises a typed validation error |
| List with no bundles yet | `ledger_data/evidence/` doesn't exist | Returns an empty list | Never raises |

</frozen-after-approval>

## Code Map

- `ledger_core/drafts.py` -- reuse as pattern: file-per-record persistence (frontmatter + body), `_generate_draft_id`-style id generation, `_escape_frontmatter_value`/parse round-trip, per-file error isolation in list (AD-8) — mirror this shape for evidence, don't import from it
- `ledger_core/log.py` -- reuse: `read_events(artifact_type)` to check source-citation resolution
- `ledger_core/projection.py` -- reuse: `get_record(artifact_type, artifact_id)` to check field-citation resolution; catch `LogFormatError` the same way `drafts.py`'s `recipient` lookup already does (treat as unresolved, don't abort)
- `shared/ledger_schema/models.py` -- reuse as pattern (read-only): `_IDENTIFIER_RE` for `artifact_type`/`artifact_id` validation. `EvidenceBundle`/`EvidenceRef` do NOT live here despite the architecture spine's literal wording -- see Design Notes
- `ledger_core/evidence.py` -- new: `EvidenceBundle`, `EvidenceRef`, `create_evidence_bundle(...)`, `list_evidence(...)`
- `ledger_core/server.py` -- edit: add `ledger_create_evidence` and `ledger_list_evidence` MCP tools
- `tests/test_evidence.py` -- new: unit tests for every I/O matrix row

## Tasks & Acceptance

**Execution:**
- [x] `ledger_core/evidence.py` -- implement `EvidenceRef` (`artifact_type`, `artifact_id`, `source: str | None`, `field: str | None`, exactly one of `source`/`field` set), `EvidenceBundle` (`evidence_id`, `claim`, `confidence`, `evidence: tuple[EvidenceRef, ...]`, `reasoning`, `generated_at`), `create_evidence_bundle(claim, reasoning, evidence, *, ledger_dir=...)` (validates, resolves each citation, computes confidence as resolved/total, generates `evidence_id`, writes `{ledger_dir}/evidence/{evidence_id}.md`), and `list_evidence(*, ledger_dir=...)` -- AD-11
- [x] `ledger_core/server.py` -- add `ledger_create_evidence` and `ledger_list_evidence` MCP tools wrapping the above; neither accepts a `confidence` parameter
- [x] `tests/test_evidence.py` -- unit tests for every I/O matrix row, including one round-trip test proving a caller-supplied `confidence` argument is impossible to pass through the MCP tool signature, not just rejected at runtime

**Acceptance Criteria:**
- Given the full test suite, when `uv run pytest` runs, then all tests pass.
- Given a bundle with 2 resolving and 1 non-resolving citation, when read back via `ledger_list_evidence`, then `confidence` is exactly `0.6666666666666666` (or a value that round-trips without silent rounding) and all three citations are still present in `evidence`.
- Given the ledger-core MCP server, when a client lists its tools, then `ledger_create_evidence` and `ledger_list_evidence` both exist alongside the seven existing tools.

## Spec Change Log

## Design Notes

**Module placement deviates from the architecture spine's literal wording, deliberately.** AD-11 says "the shared schema module adds `EvidenceBundle`," but `shared/ledger_schema/` exists specifically for AD-4/AD-9's RawFact/LedgerRecord connector contract — every connector imports it, ledger-core imports it, and nothing in `EvidenceBundle` is connector-writable or connector-relevant (only Voice ever creates one, via ledger-core). `Draft` (AD-6), the closest precedent — also Voice-only, also not connector-facing — already lives in `ledger_core/drafts.py`, not `shared/`. `EvidenceBundle` follows that established precedent instead of the spine's literal module name, preserving the actual invariant (one well-defined, single-owner schema type) rather than the incidental wording.

**`EvidenceRef` carries `artifact_type`/`artifact_id`**, which the spine's terse "cites a RawFact's source or a LedgerRecord field" didn't fully pin down (deliberately left as implementation detail — Spec Law: intents describe WHAT, not HOW). Without an artifact reference, "a LedgerRecord field" is ambiguous (whose record?) and unverifiable. Scoping every citation to one artifact makes resolution checkable and `confidence` computation meaningful rather than decorative.

## Verification

**Commands:**
- `uv sync` -- expected: resolves without error (no new dependency expected) -- ran, resolved with no changes
- `uv run pytest -v` -- expected: all tests pass, including every prior story's -- ran, 447 passed after review fixes
- `uv run python -c "import ledger_core.server"` -- expected: imports without error -- ran, imported cleanly

## Suggested Review Order

**Closing the resolution bug review found (the real catch this round, confirmed by two reviewers with a concrete repro)**

- `_resolve_ref`'s source-citation check now requires `artifact_id` to match too, not just `source` -- without this, a citation for one artifact could resolve using a completely different artifact's real fact, defeating the entire point of scoping `EvidenceRef` to one artifact.
  [`ledger_core/evidence.py:271`](../../../../ledger_core/evidence.py#L271)

- Proof: two artifacts of the same type, distinct sources, cross-cited -- confidence correctly stays 0.0.
  [`tests/test_evidence.py:234`](../../../../tests/test_evidence.py#L234)

**Closing the field-citation gameability gap**

- `_CITABLE_FIELDS` whitelist -- a field-citation can no longer resolve against a dunder/method attribute, and `confidence` is deliberately excluded (citing the ledger's own verification-status enum as evidence for a separate claim is circular, and "unknown" trivially counting as "resolved" was backwards).
  [`ledger_core/evidence.py:92`](../../../../ledger_core/evidence.py#L92)

**Closing the confidence-gaming gap**

- Citations are de-duplicated by `(artifact_type, artifact_id, source, field)` before computing the resolved/total fraction -- repeating the same citation three times no longer inflates confidence past what the distinct set would produce.
  [`ledger_core/evidence.py:420`](../../../../ledger_core/evidence.py#L420)

- Proof: 3x resolving + 1 non-resolving citation (one of the three a duplicate) gives 0.5, not 0.75.
  [`tests/test_evidence.py:289`](../../../../tests/test_evidence.py#L289)

**Smaller hardening**

- A non-dict citation item now raises a proper `EvidenceValidationError` instead of an unguarded `AttributeError`.
  [`tests/test_evidence.py:501`](../../../../tests/test_evidence.py#L501)

- `list_evidence` now isolates a genuinely unreadable file (not just a malformed one), and `_parse_bundle_file` rejects an out-of-range or NaN confidence value read back from disk.
