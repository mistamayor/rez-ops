---
name: 'Rez Ops — Adversarial Review: AD-11/AD-12'
type: architecture-review
lens: adversarial-two-units
target: architecture-Resillience-Ops-2026-08-12/ARCHITECTURE-SPINE.md
scope: 'AD-11 (Evidence boundary), AD-12 (ActionProposal/Policy Engine), and their amendments to AD-1/AD-6'
supersedes-scope-of: review-adversarial.md (2026-08-12 pass covered AD-1–AD-10; not re-litigated here except where AD-11/AD-12 introduce a new conflict with them)
created: '2026-09-05'
---

# Adversarial Review — AD-11/AD-12 (new ADs, 2026-09-05 pass)

**Method:** for each pair below, two engineers each read only the spine — AD-11, AD-12, and the AD-1/AD-6 amendment language they carry — and each implements a unit one level down (a future story building an EvidenceBundle producer or an ActionProposal type) that satisfies every AD it is bound by *to the letter*. The two units still build incompatibly: a clashing shared-data shape, two owners of one entity, conflicting mutation paths, or a Rule read two valid ways. Each pair closes with the AD (new or tightened) that would have prevented it. Per the brief, AD-1–AD-10 are not re-opened except where AD-11/AD-12's own text creates a fresh contradiction with them (Pairs 1 and 7 both do).

**Verdict:** AD-11 and AD-12 correctly keep Voice out of the *decision* seat (evaluation stays ledger-core's), but they under-specify the *seams* one level down even more than the original ten did — one field (`EvidenceBundle.confidence`) has textually contradictory ownership, the "fixed vocabulary" and the policy-resolution algorithm are both asserted but neither is anchored to a single artifact a second implementer could read and match, `EvidenceRef` has no defined shape at all, and `requires_approval` names a state with no mechanism to ever leave it. Seven holes found, none requiring a paradigm change — all closable by naming a single owner, a single file, or a single algorithm where the current text names none.

---

## Pair 1 — `EvidenceBundle.confidence`: two textually-licensed owners (CRITICAL)

**Unit A — Story 12, "Runbook Staleness Evidence":** engineer reads AD-11's rule literally: "*persistence goes through a new ledger-core write tool only, **mirroring AD-6's mechanism exactly***." AD-6's write tool is pure pass-through persistence — a `Draft`'s content is authored verbatim by Voice and stored as-is; ledger-core computes nothing about it. Mirroring that "exactly," Story 12's `ledger_write_evidence_bundle` tool accepts `claim`, `confidence`, `evidence`, `reasoning` as given by Voice and writes them verbatim. Voice's prompt computes the 0–1 plausibility score itself (e.g. "runbook untouched for 400 days against a 90-day SLA → confidence 0.85") and passes it in.

**Unit B — Story 13, "RACI Gap Evidence":** engineer reads AD-1's amendment instead: "*Voice reasoning over facts is not domain logic, **Voice computing a policy or confidence value would be***." Confidence is named explicitly as the forbidden output. So Story 13's `ledger_write_evidence_bundle` tool accepts only `claim`, `reasoning`, `evidence` from Voice, and computes `confidence` itself server-side — e.g. as a function of the cited `EvidenceRef`s' underlying `LedgerRecord.confidence`/freshness. The tool signature has no `confidence` parameter at all.

**The clash:** both engineers read a real sentence in the spine and built the opposite tool contract. Story 12's tool takes a `confidence` argument; Story 13's doesn't. A caller (Voice, or any future skill) written against one will fail or silently misbehave against the other, and — more importantly — one of the two implementations must be violating an AD: if Voice supplies confidence (Story 12), that is Voice computing a confidence value, which AD-1's own amendment names as domain logic Voice may never perform; if ledger-core derives it unaided (Story 13), then AD-11's explicit statement that "Voice assembles the claim and reasoning text" (silent on confidence, implying it's part of that same assembly) is being read as excluding the one field the object requires. AD-11 enumerates `EvidenceBundle`'s fields but never assigns an author to `confidence` — the one field this whole pass is supposed to make Voice's uncertainty explicit *about*.

**Root gap:** AD-11 says who assembles `claim`/`reasoning` and who persists the bundle, but never says who computes `confidence` — the field the "never-hide-uncertainty" Prevents clause is built around. "Mirrors AD-6's mechanism exactly" is only true of the *persistence path* (ledger-core is sole writer); it cannot also be true of the *computation* without contradicting AD-1's amendment, and AD-11 doesn't say which half of "mirrors AD-6" is meant.

**Close with:** tighten AD-11 — name the author of `confidence` explicitly, and give it a resolution method the way AD-5 does ("computed exclusively by ledger-core... using one documented method"). If the intent is Voice proposes a plausibility score as part of its reasoning (defensible, since it's subjective judgment over already-ledger-verified facts, not a derived ledger value), say so and drop the "mirrors AD-6 exactly" phrasing that implies pure pass-through is fine while AD-1 forbids Voice-computed confidence. If the intent is ledger-core derives it, say what it derives it *from* (e.g., min/mean of cited `LedgerRecord.confidence` values) with the same "one documented method" discipline AD-5 requires.

---

## Pair 2 — The "fixed vocabulary of action identifiers" is fixed nowhere (HIGH)

**Unit A — Story 14, "Restart Service Action":** engineer reads AD-12 literally ("naming the action from a fixed vocabulary... never freeform") and the Deferred note ("not the exact rule shape or which actions exist yet; that's implementation detail owned by the code once written"). Concluding the vocabulary lives wherever the config that "config-declares risk/impact" lives, Story 14 treats **`rezops.policy.yaml`'s top-level keys as the vocabulary** — no enum anywhere in code; validity = "is this action a key in the policy file." Adds `restart_service` as a policy.yaml key with its own risk/impact block. No schema change.

**Unit B — Story 15, "Escalate Incident Action":** engineer reads AD-4/AD-9's discipline the other way — "one shared schema module defines every record shape... none declares ad hoc fields" — and concludes an action *identifier* is exactly the kind of thing that must be schema-enforced, not config-enforced (config can drift out of git review; the schema module is the one place both connectors and ledger-core import). Story 15 adds an `ActionIdentifier` enum to `shared/ledger_schema` with its own five values (not including `restart_service`), and the ledger-core tool validates against *that* enum, independently of whatever `rezops.policy.yaml` contains.

**The clash:** Story 14's `restart_service` is a valid action per Story 14's own build (it's a policy.yaml key) but does not exist as far as Story 15's validator (the schema enum) is concerned — and Story 15's five enum values have no corresponding policy.yaml entries in Story 14's world. Two "fixed, never-freeform" vocabularies that don't overlap, each fully AD-12-compliant, because AD-12 says the vocabulary must be fixed without ever saying *where* — the Deferred section explicitly punts "which actions exist yet" without naming the single artifact (schema enum vs. config keys vs. something else) that is the source of truth for membership.

**Root gap:** "fixed vocabulary" names a property (closed, non-freeform) but not a location. Unlike every other schema object in this spine (each of which is enumerated by field), the action-identifier set has no designated home.

**Close with:** tighten AD-12 to name the single source of truth — most naturally: *the action vocabulary is exactly the set of top-level keys in `rezops.policy.yaml`; the shared schema module's `ActionProposal.action` field is validated against that file at proposal-creation time by ledger-core, never against a separate code-level enum*. One artifact, one owner, machine-checkable (`action in policy_config.keys()`). Leave the exact keys deferred (fine, per the existing Deferred note) but stop leaving the *location* of the fixed set deferred too.

---

## Pair 3 — `policy_decision` resolution: no "one documented method," so no two implementers compute the same answer (HIGH)

**Unit A — Story 14 (cont'd):** implements resolution as a decision table: `if risk == high and target_criticality == high: denied; elif impact == high or evidence.confidence < 0.5: requires_approval; else: automatic`.

**Unit B — Story 15 (cont'd):** implements resolution as a weighted score: `score = risk_weight * impact_weight * (1 - evidence.confidence) * criticality_weight`, thresholded into the same three buckets at 0.2/0.6.

**The clash:** feed both implementations the identical abstract inputs — action risk = medium, impact = medium, target criticality = high, evidence confidence = 0.9 — and they can (and, worked through, do) land on different buckets: Story 14's table denies on `risk==high` only, so medium risk with high criticality falls through to the `impact/confidence` branch → `automatic` (confidence 0.9 ≥ 0.5, impact not high); Story 15's weighted formula multiplies in `criticality_weight` unconditionally, so a high-criticality target can push the same inputs into `requires_approval` or `denied` depending on chosen weights. Both are "resolving the named action's config-declared risk/impact... against the target's criticality and the cited evidence's confidence" per AD-12's letter. Neither is wrong by that text, because that text describes *what the three inputs are*, never *how they combine*.

**Root gap:** AD-5 explicitly requires "**one documented method**" for confidence/coverage computation. AD-12 claims to "extend AD-5's existing principle... rather than invent a new exception to it" for `policy_decision` — but only extends the *who* (ledger-core, not Voice), silently dropping the *one documented method* half of AD-5's own principle. The Deferred section defers "the exact rule shape" the same way it defers AD-5's "exact confidence-scoring formula" — but AD-5's formula, whatever it is, is at least singular by AD-5's own rule text; `policy_decision`'s formula has no such singularity requirement anywhere, so nothing stops two action-type implementations (built as separate stories against the same ledger-core server, as AD-12's own "config-declared risk/impact *per action*" implies will happen) from hand-rolling incompatible per-action-type resolution logic inline.

**Close with:** tighten AD-12's Rule to add AD-5's missing clause: "*resolved by one documented resolution function, common to every action, never a per-action-type bespoke calculation*" — and require that function to live in one place in ledger-core (not duplicated per action handler). The exact function can stay deferred implementation detail; its singularity cannot.

---

## Pair 4 — `EvidenceRef` has no defined shape (HIGH)

**Unit A — Story 12 (cont'd):** engineer needs to cite the `last_verified` field of a runbook's `LedgerRecord` as evidence for a staleness claim. Nothing in AD-11 gives `EvidenceRef` fields (contrast: `EvidenceBundle` itself is fully enumerated — `claim, confidence, evidence, reasoning, generated_at` — but `evidence: list[EvidenceRef]`'s element type is never opened up). Story 12 implements it as a single URI-style string: `"ledger://runbooks/rb-042#last_verified"`.

**Unit B — Story 13 (cont'd):** implements it as a structured object: `{ref_type: "ledger_record", artifact_type: "raci", artifact_id: "raci-gap-07", field: "escalation_owner"}`. For its `RawFact`-citing case it adds a second variant: `{ref_type: "raw_fact", source: "<connector source ref>"}`.

**The clash:** one shape is a string, the other a dict with a discriminated union of two sub-shapes — both satisfy "cites an already-ingested RawFact's source or a LedgerRecord field" to the letter, because that sentence describes a citation *target*, not a serialization *format*. Both land in the same shared schema module (AD-11 binds it) as the element type of the same `evidence` list field on the same `EvidenceBundle` type — they cannot both be right, and any code that reads one bundle written by Story 12 and one by Story 13 (e.g. a future audit tool, or `ledger_get_briefing` composing multiple bundles) has no single parse path. There is a second, sharper version of the same gap even *within* one shape: for the `RawFact` case, does the ref store the RawFact's `source` value (the origin-system pointer, per AD-9) or the identity of the specific ingested-RawFact record that source appeared on (distinct if the same origin is re-ingested over time, producing multiple RawFacts sharing one `source`)? AD-11's sentence — "cites an already-ingested RawFact's source" — is compatible with either, and picks between them differently depending on whether "cites a RawFact's source" is read as "stores that source value" or "points at the RawFact, using its source as the citable handle."

**Root gap:** every other object this spine's schema touches (`RawFact`, `LedgerRecord`, `EvidenceBundle`, `ActionProposal`, `Draft`) is given as an enumerated field list. `EvidenceRef` — the one new type that exists *purely to make citation machine-checkable*, per AD-11's own Prevents clause — is the only one described entirely in prose.

**Close with:** tighten AD-11 (or AD-4) to give `EvidenceRef` an explicit, enumerated shape in the shared schema module, e.g. `{ref_type: "raw_fact" | "ledger_record_field", artifact_type, artifact_id, field?, source?, ingested_at}` — and resolve the source-vs-ingestion-event question explicitly (cite the specific ingested-RawFact record, not the bare source string, so a re-ingested source doesn't collapse two distinct facts into one ambiguous citation). Until this exists, "never inline-duplicates fact content, only points at it" is unenforceable — there's no fixed pointer format to enforce it against.

---

## Pair 5 — `requires_approval` names a state with no exit (HIGH)

**Unit A — Story 14 (cont'd):** treats `ledger_data/action_proposals/{proposal_id}.md` the way AD-6 treats a draft file — mutable-by-outcome. When the program owner later approves a `requires_approval` proposal, Story 14's tool rewrites the same file in place, adding `approved_by`/`approved_at` fields, on the theory that AD-12's own text says this storage "mirror[s] `drafts/`'s convention (AD-6)" and a `Draft`'s lifecycle (pending → sent) is likewise a state carried on one record.

**Unit B — Story 15 (cont'd):** treats `ActionProposal` as bound by AD-3 instead ("every state change is appended as an immutable, timestamped event... current state is always a pure, recomputed projection... never hand-edited in place") since AD-12 binds `ledger-core` and never carves ActionProposal out of AD-3's scope. Story 15 leaves `action_proposals/{id}.md` untouched forever and instead appends approval/denial events to a new `ledger_data/approvals.log.md`, keyed by `proposal_id`, projecting current approval state from that log.

**The clash:** Story 14's mechanism is a direct, in-place hand-edit of a committed record — the exact thing AD-3 forbids — yet it is what AD-12's own "mirrors `drafts/`'s convention" line most naturally suggests to an implementer who doesn't independently notice the AD-3 conflict. Story 15's mechanism is AD-3-compliant but invents an entire new artifact type and log file that no AD, naming convention, or Structural Seed entry mentions. Neither reads as forced by the text; both consume the same three-valued field (`policy_decision: requires_approval`) and produce structurally incompatible follow-on storage. And underneath both: **AD-12 defines a value (`requires_approval`) whose entire reason to exist is that something happens next, but never says what that something is, who triggers it (a person acting through the runtime? a manual `ledger_core` tool call?), or where its outcome is recorded.** Absent that, `requires_approval` is behaviorally indistinguishable from `denied` — a proposal sits in the file forever either way.

**Root gap:** AD-12's Rule fully specifies how `policy_decision` is computed and fully specifies (Never clause) that it triggers no execution — but says nothing about the human-approval half of its own three-valued output, and doesn't state whether `ActionProposal` is an AD-3 append-only-log-and-projection artifact (like `bia`/`tiering`/etc.) or an AD-6-style one-file-per-record artifact (like `drafts`) with a different mutation discipline. The Consistency Conventions table calls both `evidence/` and `action_proposals/` "one-file-per-record... mirroring `drafts/`'s convention," but never says whether `drafts/` files themselves are ever mutated post-write either — so the ambiguity may already exist in AD-6, and AD-12 imports it unchanged into a context (recording an approval decision) where it actually matters.

**Close with:** add to AD-12: name the mechanism for recording a human decision on a `requires_approval` proposal — most consistent with the rest of the spine is a new append-only `ledger_data/approvals.log.md` (AD-3-compliant, keeping `action_proposals/{id}.md` immutable once written), with `ledger_core`'s projection tool reading both files to answer "is this proposal currently approved." State explicitly that `action_proposals/{id}.md`, once written, is never edited in place — closing the AD-3 conflict Story 14's reading opens.

---

## Pair 6 — `ActionProposal.target`: which artifact types, and criticality from where (MEDIUM)

**Unit A — Story 14 (cont'd):** restricts `target: artifact_type/artifact_id` to the five artifact types the Naming convention already lists (`bia, tiering, runbooks, raci, test_records`), since only those have a `LedgerRecord` and hence a `tier_sla` to read criticality from (per the Deferred note: "likely `LedgerRecord.tier_sla`... not yet wired"). An action like `restart_service` targets `tiering/payment-service` (the tiering record for the service), not the service itself.

**Unit B — Story 15 (cont'd):** targets the DR-relevant entity directly — a CMDB CI (`cmdb_ci/server-042`) — since that's what a DR action like "restart" or "escalate" naturally acts on, and CMDB is already a Sensor in the Structural Seed. CMDB CIs have no `LedgerRecord` (CMDB is a raw-fact-only connector; nothing computes a `tier_sla` from CMDB source data per AD-9). Story 15 invents its own criticality lookup — reading a CI attribute directly from the (unowned, un-derived) `RawFact` — to unblock `policy_decision` resolution, since the spine gives it no other path.

**The clash:** Story 14's `target` values only ever resolve against the five artifact types the Naming convention enumerates; Story 15's don't appear in that enumeration at all, and its "criticality" is read from a raw, connector-asserted fact rather than a ledger-core-derived `LedgerRecord` field — quietly reintroducing the exact thing AD-5/AD-9/AD-10 exist to prevent (a non-ledger-core-computed value standing in for a derived one) inside the one new object (`ActionProposal`) whose entire job is to gate on derived state.

**Root gap:** AD-12 never states which `artifact_type`s are valid `target` values, and the Deferred note only says the criticality *signal* (`tier_sla`) isn't wired yet — it doesn't foreclose a target that could never have one.

**Close with:** tighten AD-12 (or fold into the AD-9 criticality wiring, when done) to restrict `target.artifact_type` to types that have a `LedgerRecord` (the five enumerated ones) — an action against a raw-connector-only entity (a CMDB CI, a calendar event) must target the ledger artifact that observes it, never the raw entity directly, so criticality always resolves through ledger-core's own derived state.

---

## Pair 7 — Does `policy_decision: automatic` license Voice to trigger the one write path that already exists? (MEDIUM-HIGH — Never-clause gray zone / AD-6 amendment conflict)

**Unit A — Story 14 (cont'd), strict reading:** implements the Never clause maximally: whatever `policy_decision` resolves to, ledger-core's tool only ever writes the `ActionProposal` record. `automatic` changes nothing observable — it's a label in a stored file, full stop.

**Unit B — Story 16, "Auto-Notify on Automatic Decisions":** reads AD-12's Prevents clause the other way. It doesn't say "no write of any kind follows an automatic decision" — it forecloses only "the LLM ever deciding for itself whether an action is *permitted*" and "conflating drafted human content (AD-6) with a structured, policy-evaluated system operation." Story 16's action is `notify_escalation_owner`; its "config-declared risk/impact" is deliberately set low (a notification isn't an external-system mutation), so it commonly resolves `automatic`. Story 16's implementer reasons: an `automatic` decision on a *notify*-type action means Voice needn't wait for a second round-trip before drafting the notification — so on `policy_decision == automatic`, the ledger-core tool that creates the `ActionProposal` *also* calls the already-licensed AD-6 write path, queueing a `Draft` addressed to the escalation owner, in the same call. No external send/write API is touched (a human still must send the Draft) — the Never clause's literal words ("nothing here calls an external write/send API") are honored exactly.

**The clash:** Story 16 has built exactly what AD-12's own Prevents clause names as the thing to prevent — an `ActionProposal`'s resolution automatically producing a `Draft` — while never violating a single word of the Never clause, because the Never clause is written against *external execution* ("no executor... calls no external write/send API"), not against *automatically triggering Rez Ops's own, already-authorized, internal write path*. `automatic` as a policy_decision label reads, to a reasonable second implementer, as "proceed automatically" for at least the sub-class of actions whose only consequence is queuing something a human must still approve — and nothing in AD-6 or AD-12 states that an `ActionProposal`'s `policy_decision` may never itself be the trigger condition for a `Draft` write, even though that is precisely the AD-6/AD-12 shape-conflation AD-12's Prevents clause exists to rule out.

**Root gap:** the Never clause scopes "no executor exists **in this phase**" — temporal language, not a structural bar — and never explicitly forecloses `policy_decision` (of any value, including `automatic`) being wired as an automated trigger into the one write mechanism (`drafts/`) the architecture has already built and licensed. AD-1's amendment ("Voice reasoning over facts is not domain logic, Voice computing a policy... value would be") governs who computes the decision, not what may consume it once computed.

**Close with:** tighten AD-12's Never clause from "no executor exists in this phase" to something structural: **no `policy_decision` value, including `automatic`, may itself be the trigger for any write — to `drafts/` or anywhere else — except a human-initiated one; `ActionProposal` creation is always a terminal, human-read-only event until a future Executor AD says otherwise.** This closes the one path by which "recorded, never acted on" could be read as "recorded, and its `automatic` value acted on internally" while every other word of the Never clause stays satisfied.

---

## Summary table

| # | Hole | Severity | Fields/ADs implicated |
|---|---|---|---|
| 1 | `EvidenceBundle.confidence` has two textually-licensed owners (Voice vs. ledger-core) | CRITICAL | AD-11, AD-1 amendment |
| 2 | "Fixed vocabulary" of action identifiers has no designated home | HIGH | AD-12, AD-4 |
| 3 | `policy_decision` resolution has no "one documented method" requirement | HIGH | AD-12, AD-5 |
| 4 | `EvidenceRef` has no enumerated shape — string vs. structured object | HIGH | AD-11, AD-4 |
| 5 | `requires_approval` has no recording mechanism; storage discipline (AD-3 vs. AD-6-style) unresolved | HIGH | AD-12, AD-3, AD-6 |
| 6 | `ActionProposal.target` artifact-type scope and criticality source unbounded | MEDIUM | AD-12, AD-9, AD-5 |
| 7 | Never clause is temporal ("in this phase"), not structural — `automatic` could trigger an internal `Draft` write | MEDIUM-HIGH | AD-12 Never clause, AD-6 |

---

## Direct answers to the four flagged questions

- **Is the "fixed vocabulary of action identifiers" actually fixed anywhere?** No — see Pair 2. AD-12 asserts closure ("never freeform") without naming the single artifact whose membership defines it, and the Deferred section's punt ("implementation detail owned by the code once written") doesn't specify *which* code, leaving schema-enum and config-key readings equally licensed and mutually exclusive.

- **Is `policy_decision`'s computation precise enough that two implementers converge?** No — see Pair 3. The three inputs (action risk/impact, target criticality, evidence confidence) are named, but nothing constrains how they combine, and AD-12 conspicuously drops AD-5's "one documented method" language when it claims to extend AD-5's principle.

- **Is the `EvidenceRef` citation format precise enough to be machine-checkable?** No — see Pair 4. It has no enumerated field shape at all (unique among this spine's schema objects), and even the underlying citation semantics (source-string vs. specific-ingestion-event) are ambiguous.

- **Could AD-11/AD-12 license actual execution in some edge case the Never clause doesn't foreclose?** Not external execution — that's well-guarded. But see Pair 7: the Never clause's "no executor exists in this phase" is temporal scoping, not a structural bar on `policy_decision` triggering Rez Ops's *own* already-licensed internal write (`drafts/`), which is exactly the AD-6/AD-12 conflation the Prevents clause names as the thing to avoid.
