---
id: SPEC-rez-ops
companions:
  - '../../planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/ARCHITECTURE-SPINE.md'
  - '../../planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/solution-design.md'
sources:
  - '../../planning-artifacts/briefs/brief-Resillience-Ops-2026-08-12/brief.md'
  - '../../planning-artifacts/briefs/brief-Resillience-Ops-2026-08-12/addendum.md'
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Rez Ops

## Why

A pain to solve, for DR/resilience program owners at large, always-on organizations: DR program artifacts (BIAs, tiering, runbooks, RACI, test schedules) are scattered across disconnected systems with no shared concept of freshness, so reconstructing the program's true state is manual and slow — done only under pressure, right before an audit or right after an incident proves a gap was real. Rez Ops closes that gap as a thin, read-only orchestration layer over the tools a program already has, rather than a new system of record, so the program becomes proactive instead of reactive.

## Capabilities

- **CAP-1 — Freshness Ledger**
  - **intent:** Maintain a structured, per-artifact-type record of verification state (last verified, method, expiry rule, tier SLA, escalation owner) that expires rather than staying valid indefinitely.
  - **success:** Every tracked artifact type has a queryable ledger record whose fields are populated or explicitly marked unknown, with an expiry rule that can trigger a staleness flag.

- **CAP-2 — Read-only connectors**
  - **intent:** Ingest calendar, ticketing, git, CMDB, and document-store (Google Drive, SharePoint) data as raw observed facts without writing back to any of those systems.
  - **success:** Each connector returns normalized raw facts to the runtime; no connector call in v1 issues a write, update, or delete against its external system.

- **CAP-3 — Confidence/coverage computation**
  - **intent:** Compute an explicit confidence state (agent-verified, manual, or unknown) for every derived ledger value rather than presenting derived state as uniformly certain.
  - **success:** A coverage query returns confidence broken down by domain and tier; any record lacking a verifying source shows as unknown, never omitted or defaulted.

- **CAP-4 — Chat-queryable live state**
  - **intent:** Let a user ask, in natural language, what is stale, what is due, or what needs their attention, and get an answer from current ledger state on demand.
  - **success:** A live query returns an answer reflecting current state without requiring a scheduled briefing to have run first.

- **CAP-5 — Ownership inference and arbitration**
  - **intent:** Infer who is accountable for an entity from live activity signals rather than a static ownership record, and arbitrate disagreement between sources.
  - **success:** For any ownership-bearing field with conflicting inputs, exactly one source is authoritative and the conflict is recorded, never silently overwritten; total absence of signal marks the entity orphan-risk.

- **CAP-6 — Draft-not-send outbound content**
  - **intent:** Draft outbound content (e.g. an owner-reconfirmation message) for human review without sending it.
  - **success:** Every drafted item is retrievable from a pending queue and requires explicit human action before anything sends externally; v1 has no auto-send code path.

- **CAP-7 — Daily/periodic briefing**
  - **intent:** Produce a periodic briefing ranking what needs a decision today, using the same underlying state a live query would return.
  - **success:** A generated briefing's content matches what a live query returns at the same point in time; the delivery channel swaps without changing the underlying content.

- **CAP-8 — Scheduled headless operation**
  - **intent:** Generate a briefing on a schedule without a human present.
  - **success:** An OS-scheduled invocation completes end-to-end and updates ledger state or logs a failure explicitly; no scheduled run fails silently.

- **CAP-9 — Evidence-backed claims**
  - **intent:** Let Voice make a reasoning-layer claim about ledger state as a structured `EvidenceBundle` (claim, confidence, cited facts, reasoning) rather than unattributed prose, with confidence computed exclusively by ledger-core from the cited evidence — never supplied by the caller.
  - **success:** Every `EvidenceBundle`'s confidence is ledger-core-computed, not accepted as input; a caller-supplied confidence value is rejected as a schema violation; every citation resolves back to a real ingested fact or ledger record, never an inline duplicate.

- **CAP-10 — Policy-gated action proposals**
  - **intent:** Let Voice propose a system-state-changing action — naming it from a config-declared vocabulary, citing at least one `EvidenceBundle` — and have ledger-core alone compute whether it's automatic, requires human approval, or is denied, without any component executing it.
  - **success:** Every `ActionProposal`'s `policy_decision` is computed by ledger-core from config-declared action risk, target criticality, and the minimum confidence across cited evidence — never asserted by the caller; naming an undeclared action or citing no evidence is rejected before anything is recorded; no code path in v1 consumes an approved/automatic decision to perform the action against any external system.

## Constraints

- No connector may write to any external system of record in v1 (read-only-first).
- Any Rez Ops failure (a connector or ledger-core outage) must fail open to today's manual baseline — never blocking or worsening the DR program (graceful degradation).
- Every derived/computed value must carry an explicit confidence state; no derived value may be presented without one (never hide uncertainty).
- v1 runs local-first: no hosted database, container orchestration, or persistent server process; git is the sole persistence layer.
- Ledger state is mutated only through an append-only log; no in-place edits — single writer, auditable history.
- v1 favors fewer, high-trust, provenance-ranked sources over broad source coverage.
- Voice may propose a claim or an action; it never computes the derived value that evaluates it — `EvidenceBundle.confidence` and `ActionProposal.policy_decision` are ledger-core-exclusive, the same discipline as CAP-3's confidence computation extended to the proposal layer.

*Full mechanism for each of these lives in `ARCHITECTURE-SPINE.md` (AD-1 through AD-12).*

## Non-goals

- Auto-actioning against any system of record: a computed `policy_decision` (CAP-10) is a recorded judgment, not a permission that anything acts on.
- An Executor that consumes an `ActionProposal`'s `policy_decision` to actually perform the action against any external system — explicitly deferred; a separate, later, deliberate decision, not a default extrapolation from CAP-10 existing.
- A retroactive "would-have-caught-it" scoreboard against past incidents (Blast Radius Rewind).
- Proactive or surprise micro-drills, or agent-triggered synthetic failovers.
- Auto-sending owner-reconfirmation messages or any outbound content without human approval.
- A passive-observation, watch-only baselining period.
- Multi-user or multi-tenant support.
- Packaging as an installable product for other practitioners — left open, not decided for v1.
- Migrating to MCP SDK v2 in v1.

## Success signal

Zero "we didn't know that was stale" surprises at the next audit or review; "who owns X" answered in seconds via a live query instead of days of chasing; a generated briefing consistently surfaces genuinely new information rather than repeating already-handled items; and every proposed action shows its evidence trail and policy decision before any human is asked to approve it — never a bare recommendation with no attributable reasoning.

## Assumptions

- Primary user and scale modeled on a Booking.com/Expedia-scale global travel or e-commerce business; the real target scale is otherwise unconfirmed.
- The refuse-to-be-a-system-of-record differentiator is a product-philosophy choice, not a defensible technical moat, and could be replicated by a competitor.

## Open Questions

- Is Rez Ops a personal configuration for a single program owner, or does it need to support installation by other DR practitioners? Affects how generic connector configuration and onboarding need to be.
- Which specific calendar/ticketing/CMDB vendor products will the first connectors target?
- Should v1 capabilities design directly for secondary users (compliance stakeholders, application/service owners), or stay scoped to the primary program-owner user until the capability set stabilizes?
