# Rubric Walk — Reviewer Gate — AD-13/14/15 Update

**Target:** `ARCHITECTURE-SPINE.md` (Rez Ops), update session adding AD-13/AD-14/AD-15 to an existing 12-AD spine.
**Scope of this review:** the good-spine checklist, applied specifically to the new ADs and their interaction with the inherited AD-1..AD-12 spine.

## Verdict

**Conditional pass.** The update is structurally sound and correctly honors the letter of AD-12's Never clause (every new AD is explicitly and consistently tagged `[DESIGN ONLY — not yet built]`, and the top-level diagram uses dotted edges with matching labels). But it has one **Major** substantive gap — the entire approval/denial/idempotency safety chain for a future Executor is specified as an Executor-side, honor-system check with no centralized ledger-core-side guard, despite ledger-core being established elsewhere in this exact same update as the sole/centralizing authority — and one **Major** documentation defect that goes directly to the prompt's central question: one line in the Structural Seed (`action_proposals.log.md`'s file comment) lists the AD-14 `approved` event alongside the already-built AD-12 `proposed`/`decided` events with no "not yet built" tag, unlike every other AD-13/14/15 reference in the same section. Recommend both be fixed before treating this update as final.

## Walk of each rubric point

### 1. Fixes the real divergence points for the level below, misses none

AD-13's three `Prevents` claims (per-vendor write code creeping into ledger-core; an Executor bypassing the MCP-tool-boundary discipline; a write credential reusing a read-only connector's) are each answered by a corresponding Rule clause, and are genuine divergence risks for whoever builds the first Executor and whoever builds the second one later. AD-14 and AD-15's `Prevents` claims are likewise each matched by a Rule clause (see #2).

One divergence point is **not fully closed**: with Executors explicitly one-per-vendor/action (AD-13, mirroring AD-2's one-server-per-domain), two independently-built Executors are exactly the "independently-built units" this checklist worries about, and the spine leaves the entire safety-critical check sequence (confirm `policy_decision` favorable → confirm `approved` event if required → hard-block if `denied` → idempotency check against `action_executions.log.md`) as something "an Executor" does, with no shared, ledger-core-side enforcement point. See Finding 1.

### 2. Every AD's Rule is enforceable and prevents its stated divergence (Prevents vs. Rule text)

- **AD-13**: Prevents (per-vendor code in ledger-core / boundary bypass / credential sharing) — Rule text matches all three directly (new `executors/` MCP server, tool-call-only interaction with ledger-core, separate credentials even for the same vendor). Enforceable in the same style as the rest of the spine (code-review discipline, per AD-1's stated model) — but AD-13 never states that enforcement model explicitly the way AD-1 does, and the property being enforced here (never act on an unauthorized proposal) is materially higher-stakes than AD-1's (domain logic lives in the right file). See Finding 1.
- **AD-14**: Prevents (losing the approve-vs-invoke audit distinction; a denied proposal executing anyway) — Rule text matches (new `approved` event; hard block on `denied` "regardless of who invokes it"). Same enforceability caveat as AD-13: the hard block is stated to happen "at the Executor," i.e. per-Executor code, not a shared gate.
- **AD-15**: Prevents (forcing retriable execution into the wrong log; double-successful-execution with no idempotency guard) — first half is fully solved (new log). Second half (idempotency) is stated as "an Executor checks this log... before executing" — again Executor-side, not enforced by the ledger-core tool that actually performs the write (which the AD itself says is the *sole* writer to `ledger_data/`). This is the one place in the update where centralizing the check in ledger-core would have been the natural, cheap fix, given the pattern is already used for the log format itself.

### 3. Nothing under Deferred could let two independently-built units diverge incompatibly

The Deferred items themselves are fine — "exact tool names/log line formats" is safely deferred because the actual write to `action_executions.log.md` goes through a single ledger-core tool call (centralized), so format divergence across Executors is not actually possible. The "rejected event" gap is honestly flagged as an open question rather than silently absent. The one thing that *should* arguably appear in Deferred but does not is the idempotency/authorization-check enforcement point from Finding 1 — it is asserted as settled Rule text ("an Executor checks...") rather than flagged as an open question, which actually undersells the risk: a reader could reasonably believe this is already a closed decision when the mechanism described does not structurally prevent the failure mode it names.

### 4. No new AD weakens or contradicts an inherited one, especially AD-12's Never clause

This is the one point where the update does clearly succeed. AD-12's Never clause is quoted almost verbatim as the frame for the whole update ("AD-13/AD-14/AD-15 design the Executor deliberately, as their own dedicated decision, exactly as this clause required — but design is not code"), and every new AD carries the `[DESIGN ONLY — not yet built]` tag in its own heading, the diagram uses dotted lines with inline "[design only, not built]" labels, and the Deferred section repeats "no code exists yet." AD-13's ban on auto-triggered execution and AD-14's requirement that even `automatic`-decision proposals still need deliberate human invocation both go *further* than AD-12 strictly required, reinforcing rather than eroding the human-control non-negotiable. No new AD relaxes an old Rule (e.g., AD-3's append-only/projection discipline, AD-7's credential-source rule) — AD-13/15 extend both without contradiction.

However, the **surrounding prose that was not updated** does create one real contradiction: the Consistency Conventions table's cross-cutting row states "`policy_decision`... is recorded-only — no executor consumes it (AD-12)." That sentence was true before this session and is technically still true today (no Executor exists), but it now sits directly beside a spine that spends three new ADs describing how an Executor *will* consume `policy_decision` once built. It should have been amended (e.g., "...no executor consumes it yet — once AD-13 is built, Executors are its sole consumers") rather than left as an unqualified, now-superseded-sounding claim. See Finding 3.

### 5. Every dimension the altitude owns is decided, deferred, or an open question

Mostly yes: component boundary, credential separation, log placement, rollback (explicitly never), autonomous execution (explicitly deferred), rejected-event (explicitly open question), exact schemas/formats (explicitly deferred). The one dimension that falls into none of the three buckets is **where the authorization/idempotency check is enforced** (Executor vs. ledger-core) — it is asserted as Rule, not flagged as open, yet the text itself does not actually close the risk it's meant to close. This should move from "quietly decided" to either "decided with a stated enforcement mechanism" or "open question, revisit before the first Executor is built."

## Findings

### Finding 1 (Major) — Safety-critical execution gates are Executor-side/honor-system, not centrally enforced
AD-13 requires an Executor to "confirm `policy_decision` is favorable and (for `requires_approval`) that an `approved` event exists... before performing the real external write." AD-14 requires a `denied` proposal to be "hard-blocked at the Executor." AD-15 requires "an Executor checks this log for the target `proposal_id`" before executing, to guarantee idempotency. All three of the update's core safety properties are phrased as something each individual, independently-built Executor must remember to do correctly — with no shared ledger-core tool that itself refuses to hand back an unfavorable/unapproved/denied proposal, or refuses to accept a second successful execution-attempt write for the same `proposal_id`. This is inconsistent with the rest of the paradigm this same update relies on: ledger-core is explicitly "the sole writer to `ledger_data/`" and the single place the log *format* is defined — the natural (and cheap) extension is to make it the single place the *authorization/idempotency check* is enforced too, e.g. a `ledger_core.confirm_executable(proposal_id)` tool that raises unless favorable+approved+not-yet-successfully-executed, called by every future Executor instead of each one re-implementing the check. As written, a second, independently-built Executor (e.g., a later `disable_credential` executor) could omit or subtly mis-implement any of these three checks, silently defeating the entire proposal/approval/idempotency guarantee that AD-12/13/14/15 exist to provide — precisely the "two independently-built units diverging incompatibly" failure mode this rubric asks about.
**Recommendation:** before the first Executor is built, either (a) add a Rule clause requiring a single shared ledger-core tool that performs all three checks server-side and is the only sanctioned way an Executor obtains permission to write, or (b) explicitly move this to Deferred/open-questions with a note that per-Executor enforcement is a known, accepted risk for v1 (single-owner, low Executor count).

### Finding 2 (Major) — Structural Seed inconsistently tags the AD-14 `approved` event as design-only
Line "`action_executions.log.md  # AD-15 [design only, not yet built]: ...`" and the `executors/` line both carry an explicit "not yet built" tag. The adjacent line "`action_proposals.log.md   # AD-12/AD-14: proposed/decided/approved events (incl. policy_decision); current state is a projection, same pattern as AD-3`" does not — it lists `approved` (AD-14, not built) in the same breath as `proposed`/`decided` (AD-12, already built per the Story 13 reference elsewhere in the spine) with no distinguishing tag. This is exactly the ambiguity the review brief asked to scrutinize: a future reader skimming the Structural Seed file tree could reasonably conclude the `approved` event is already supported by ledger-core today.
**Recommendation:** split the comment, e.g. `# AD-12: proposed/decided events (built); AD-14 approved event [design only, not yet built]`.

### Finding 3 (Moderate) — Consistency Conventions row is stale relative to the new ADs
The State & cross-cutting row's claim "`policy_decision`... is recorded-only — no executor consumes it (AD-12)" was accurate pre-session but now reads as contradicting AD-13's description of an Executor consuming `policy_decision`. It was not revisited during this update pass.
**Recommendation:** qualify it, e.g. "...no executor consumes it yet — AD-13, once built, makes Executors its sole consumer."

### Finding 4 (Minor) — "favorable" is used but never formally defined
AD-13's Rule gates execution on `policy_decision` being "favorable," a term introduced here and nowhere spelled out as (`automatic`) OR (`requires_approval` with a recorded `approved` event), explicitly excluding `denied`. It's inferable from reading AD-12/14 together, but a defined term would remove any doubt for whoever implements the first Executor's check.

### Finding 5 (Minor/Cosmetic) — top diagram doesn't show the Executor's re-fetch step
AD-13's Rule has the Executor *re-fetch* its target `ActionProposal` from ledger-core before confirming/writing, but the invariants diagram collapses this into a single dotted edge labeled "confirm policy_decision + approval, then record outcome" without a separate read step. Not misleading, just incomplete relative to the prose.

### Note (informational, not a finding) — AD-6's "future write-capable connector" language predates the Executor/Connector taxonomy split
AD-6 (pre-existing) binds "ledger-core, any future write-capable connector" and was clearly anticipating what this session formally named "Executor," a category now explicitly distinct from Sensor/Connector. AD-6's wording wasn't updated to reflect the new taxonomy. This doesn't change AD-6's substance (still true, still design-only in practice) but is a small terminology-drift cleanup opportunity.

## Summary table

| # | Finding | Severity |
| --- | --- | --- |
| 1 | Approval/denial/idempotency checks are Executor-side only, no ledger-core-side enforcement | Major |
| 2 | Structural Seed's `action_proposals.log.md` line doesn't tag `approved` (AD-14) as not-yet-built, unlike sibling lines | Major |
| 3 | Consistency Conventions "no executor consumes it (AD-12)" row is stale vs. AD-13 | Moderate |
| 4 | "favorable" (AD-13) used without a formal definition | Minor |
| 5 | Diagram omits the Executor's re-fetch step from ledger-core | Minor/Cosmetic |
| — | AD-6's "future write-capable connector" phrasing predates the Executor/Connector taxonomy | Informational |
