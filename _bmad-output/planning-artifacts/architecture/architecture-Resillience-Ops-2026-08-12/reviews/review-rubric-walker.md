# Rubric Walker Review — Rez Ops Architecture Spine (AD-11/AD-12 Amendment)

**Target:** `_bmad-output/planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/ARCHITECTURE-SPINE.md`
**Reviewed:** 2026-09-05, against the spine's `updated: '2026-09-05'` state (10 pre-existing ADs + new AD-11, AD-12; AD-1 and AD-6 amended in place)
**Applicable checks:** this is an UPDATE review, not a fresh-spine review — the inheritance check (§5 below) is the load-bearing one. No brownfield ratify, no driving spec/capability map to trace against.
**Supersedes:** the prior `review-rubric-walker.md` in this directory, which reviewed the 7-AD, 2026-08-12 version of this spine (pre-dating AD-8/9/10 and this AD-11/12 amendment). That review's findings on credential handling, scheduled-run failure handling, and the Claude Code version claim have since been addressed in the current text (see AD-7); this review does not re-litigate them.

## Verdict

**Changes requested.** The external-write boundary this amendment claims to hold (`AD-12`'s "no Executor, nothing calls an external API") is genuinely intact — there is no Executor component anywhere in the structural seed, and the "Never" clause is explicit and structurally enforceable. But a narrower, more important crack exists one layer up: **AD-11 never states who computes `EvidenceBundle.confidence`**, and the most natural reading of its own Rule text ("Voice assembles the claim") is that Voice — the LLM — sets that value itself. That directly contradicts AD-1's own amended language ("Voice computing... a confidence value would be [domain logic]") and, chained through AD-12 (whose `policy_decision` partly resolves against "the cited evidence's confidence"), reopens exactly the loophole AD-12's own Prevents clause says must never exist: the LLM indirectly steering whether its own proposed action is `automatic`, `requires_approval`, or `denied`. This is a single fixable gap, not a structural rethink, but it should be closed before this spine is treated as final.

---

## 1. Real divergence points for the level below — mostly covered, two gaps introduced by the amendment

The level below this amendment is: epics/stories that (a) build the two new ledger-core write tools (propose-evidence, propose-action), (b) build or extend Voice-side skills/prompts that call them, and (c) author `rezops.policy.yaml`. Divergence risks checked:

| Divergence risk | Covered? | Where |
| --- | --- | --- |
| Evidence claim persisted as unattributed prose | Yes | AD-11: `EvidenceRef` must cite an ingested `RawFact`/`LedgerRecord`, never inline-duplicate |
| `Draft` and `ActionProposal` shapes conflated | Yes | AD-6 (amended) + AD-12, explicit cross-reference both ways |
| Freeform action strings fragmenting across stories | **Partially** | AD-12 says "fixed vocabulary... never freeform" but never says *where that vocabulary is canonically declared* or *how Voice discovers valid values before calling the tool*. Two independently-written skills could each invent their own list of action identifiers with no shared source of truth to check against — the exact class of divergence AD-4's shared-schema pattern exists to prevent elsewhere, but not extended here. See Finding 2. |
| `EvidenceBundle.confidence` vs `LedgerRecord.confidence` conflation | Yes, in name | AD-11 explicitly distinguishes the two — but see Finding 1: distinguishing the *concepts* doesn't resolve who *computes* the new one. |
| Multi-evidence policy resolution (an `ActionProposal` cites a *list* of `EvidenceBundle`s, but the Rule says policy resolves against "**the** cited evidence's confidence," singular) | **No** | Not addressed anywhere, not even in Deferred. Two ledger-core implementations (or one implementation revisited later) could reasonably pick min, max, average, or most-recent — each gives a different `policy_decision` for the same proposal. See Finding 3. |
| Evidence/proposal file mutability after creation | Implicit only | Presumably write-once like `Draft`/`LedgerRecord`, consistent with AD-3, but never stated for these two new record types specifically. Minor. |

Everything else new in this amendment (storage location/naming, schema-module placement, policy-config separation from `rezops.config.yaml`) is concretely decided and consistent with the existing AD-2/AD-3/AD-4/AD-6 patterns. The amendment does not miss a divergence point wholesale; the two gaps above are specific and fixable.

## 2. AD-11 / AD-12 Rule enforceability vs. their Prevents claims

- **AD-11.** Prevents: "a reasoning-layer claim existing only as unattributed prose." Rule requires every `EvidenceRef` to point at an already-ingested fact/record and routes persistence through a single ledger-core write tool. This is enforceable the same way AD-6 is (single writer, code-reviewable) and does prevent the stated divergence for the *evidence-linkage* half of the claim. It does **not** enforce anything about the *confidence* half of the claim — see Finding 1. The Rule's own justification ("Voice assembles the claim... that is reasoning over facts ledger-core already computed, not domain-logic computation") is doing a lot of unexamined work: reasoning over facts to write prose is one thing; assigning a numeric plausibility score is a computation over those facts, which is precisely what AD-5/AD-1 reserve to ledger-core elsewhere in this same document.

- **AD-12.** Prevents: "the LLM ever deciding for itself whether an action is permitted." Rule requires Voice to call a tool and ledger-core to compute `policy_decision`. Structurally enforceable in the same review-gated way as AD-5 (single locus of computation) — **but only if the tool's inputs cannot include a policy_decision, or anything equivalent to it, supplied by the caller.** AD-9 sets a precedent for exactly this kind of explicit guard: "a connector reporting `tier_sla` as an observed fact is a schema violation." AD-12 has no equivalent sentence — nothing says "`ActionProposal.policy_decision` supplied by the caller is a schema violation" or constrains the tool's write-input schema to exclude it. Given the tool signature isn't shown, this is likely intended but it isn't said, and it's the exact kind of thing this rubric's "Rule text actually prevents its Prevents claim" test is for. Recommend adding the equivalent explicit sentence AD-9 already models.

## 3. Deferred — nothing new introduces incompatible-build risk, with one caveat

Re-walked the full Deferred list for new entries introduced by this amendment:

- **The Executor** — correctly deferred; explicitly requires its own future AD before any code writes externally. This is the single strongest piece of evidence that the write boundary is being taken seriously, not hand-waved.
- **`rezops.policy.yaml`'s exact schema and the fixed action-identifier vocabulary** — deferred together, reasoned as "AD-12 fixes who owns evaluating policy... not the exact rule shape or which actions exist yet," explicitly modeled on AD-5's confidence-formula deferral. That precedent holds for the *rule shape* (single owner, ledger-core, can't diverge from itself). It does **not** fully hold for the *action vocabulary* half of this same bullet: unlike the confidence formula (consumed only by ledger-core, a single component), the action vocabulary must also be *known to Voice* before Voice can call the tool without guessing — a second, independent consumer. Deferring "which actions exist" without deferring or deciding *how Voice learns which actions exist* leaves a live two-sided divergence point where the confidence-formula analogy leaves none. This is the same gap as row 3 in §1 (Finding 2), just visible again from the Deferred-list angle.
- **The exact criticality signal for `policy_decision`** — deferred coherently alongside its own dependency (`tier_sla`'s formula, already deferred under AD-5). Low risk, single owner either way.
- All other Deferred bullets are either untouched by this amendment or correctly reasoned as single-owner/no-interface-yet. Nothing here lets two independently-built units diverge incompatibly except the vocabulary-discovery gap already named.

## 4. Named tech — nothing new to verify

AD-11/AD-12 introduce no new libraries, runtimes, or versioned dependencies — just two new schema types, two new ledger-core tools, one new config file (`rezops.policy.yaml`, same YAML format already used for `rezops.config.yaml`), and two new one-file-per-record directories following the existing `drafts/` convention. The Stack table is unchanged by this amendment and was not the subject of this review pass. One observation, not a finding against the amendment itself: the table's currency claims ("confirmed current as of 2026-08-12 research pass") are now three weeks stale relative to the spine's own `updated: 2026-09-05` stamp, and this update didn't refresh them — worth a re-check next time the spine is touched, since the claim's own framing implies it should be periodically re-verified, not evidence once and trusted forever.

## 5. Inheritance check — does AD-11/AD-12, or the AD-1/AD-6 amendments, weaken or contradict AD-1–AD-10? (the load-bearing check for this review)

**AD-6's amendment** (the closing sentence distinguishing `Draft` from `ActionProposal`) strengthens rather than weakens the original: it forecloses a scope-creep path (stuffing a system-operation proposal into the human-message `Draft` shape) that didn't exist before AD-12 introduced the second shape. No contradiction.

**AD-1's amendment** (the "read-only by default; action is an explicit, separately-gated capability" paragraph) states the right principle in its own text — "Voice reasoning over facts is not domain logic, Voice computing a policy or confidence value would be" — and by stating it, actually raises the bar AD-11 has to clear. This is where the contradiction surfaces, not in the amendment's own wording:

- **AD-5** (pre-existing, untouched): "confidence/coverage values are computed exclusively by ledger-core... Connectors report only raw timestamps and records — never a confidence score." This AD is scoped to connectors, but AD-1's own amendment generalizes its spirit to Voice in the same breath it introduces AD-11/12. AD-11 then hands Voice a `confidence: float 0-1` field to fill in as part of "assembling the claim," with no ledger-core-side computation or validation step described. Read literally, this is Voice computing a confidence value — the exact clause AD-1's own amendment names as the boundary. The spine tries to pre-empt this reading by declaring the two confidence concepts "distinct" and "never conflated," but distinctness of concept doesn't resolve who computes the new one; the document never actually says.
- **Downstream chain into AD-12**: `policy_decision` — the one thing this whole layer exists to keep out of the LLM's hands per AD-12's own Prevents clause — is computed by resolving the action's config-declared risk "against... the cited evidence's confidence." If that confidence number originates from Voice, then `policy_decision` is partly a function of a value Voice supplied, and Voice has an indirect lever over its own outcome (assert higher confidence in the evidence you cite, get a more favorable policy decision). This is not a hypothetical edge case; it is the direct, one-hop consequence of AD-11's unstated computation source, and it lands squarely on the property AD-12 was written to guarantee never happens.

This is the one place in the amendment where the checklist's inheritance question has a real answer: **AD-11, as literally written, creates a path that undercuts AD-5's original intent and AD-12's own stated guarantee**, even though AD-1's and AD-6's amendments in isolation are both faithful to (or strengthen) the original ten. The fix is narrow: AD-11's Rule needs one more sentence making explicit that ledger-core computes (or at minimum validates/caps) `EvidenceBundle.confidence` from the confidence/freshness of the `LedgerRecord`/`RawFact` entries it cites — mirroring how `tier_sla` is computed from config inputs under AD-9 — rather than leaving it as a value Voice hands over as part of the claim payload.

No other original AD (AD-2, AD-3, AD-4, AD-7, AD-8, AD-9, AD-10) is weakened or contradicted by this amendment. In particular:
- AD-3 (append-only): the two new record types follow the existing one-file-per-record pattern already established for `drafts/`; no hand-editing-in-place is introduced.
- AD-9 (RawFact/LedgerRecord split): untouched; AD-11 adds a third shape alongside rather than modifying either.
- AD-10 (ownership arbitration): not implicated by evidence/proposal records, which aren't ownership-bearing fields.

## 6. Operational/environmental envelope — not silent, and not touched by this amendment in a way that reopens it

AD-7 (untouched by this update) already substantively answers deployment, infra/provider strategy, and operations for the whole spine, including the scheduled/headless path, credential sourcing, and failure logging. This amendment adds two new local write paths (`ledger_data/evidence/`, `ledger_data/action_proposals/`) that fall under the same general mechanisms already specified (git-committed writes, AD-8's fail-open behavior, AD-7's `_ops.log.md` for scheduled-run failures) — nothing about the new capability requires its own operational envelope decision, and the spine doesn't have to (and doesn't) repeat one. This dimension is adequately inherited, not left silent by the amendment.

---

## Findings (ranked)

1. **[High] `EvidenceBundle.confidence`'s computation source is unstated, and the natural reading — Voice sets it while "assembling the claim" — contradicts AD-1's own amended rule and reopens the exact loophole AD-12 exists to close.** Because `policy_decision` resolves partly against "the cited evidence's confidence," an LLM-supplied confidence value gives Voice an indirect lever over its own action's approval outcome. Fix: add an explicit sentence to AD-11 stating that ledger-core computes (or validates/bounds) this value from the confidence/freshness of the cited `LedgerRecord`/`RawFact` entries, the same locus-of-computation pattern already used for `tier_sla` (AD-9) and `LedgerRecord.confidence` (AD-5).

2. **[Medium] AD-12's "fixed vocabulary of action identifiers" has no stated canonical source or discovery mechanism for Voice.** Unlike the confidence-formula deferral (single consumer: ledger-core), the action vocabulary has two consumers — ledger-core (evaluates) and Voice (must call with a valid value) — so deferring "which actions exist" without deciding how Voice learns them is a live divergence point between independently-authored skills/stories. Fix: at minimum, name where the vocabulary canonically lives (e.g., keys of `rezops.policy.yaml`) and how Voice obtains it (e.g., a `policy_list_actions` ledger-core tool), even while leaving the vocabulary's actual contents deferred.

3. **[Medium] No rule for aggregating confidence across a multi-item `ActionProposal.evidence` list.** AD-12's Rule speaks of "the cited evidence's confidence" in the singular against a field typed as a list; min/max/average/latest all give different `policy_decision` outcomes for the same facts, and nothing decides or defers this explicitly.

4. **[Low] AD-12 lacks the explicit "caller-supplied X is a schema violation" guard that AD-9 models for `tier_sla`.** Nothing states that a proposal request arriving with its own `policy_decision` (or an equivalent hint) is rejected — implied by "ledger-core computes it," but not said with AD-9's precision, and this rubric's "Rule text must actually prevent the Prevents claim" test flags the gap.

5. **[Low] Stack-table currency claims (2026-08-12 research pass) are unrefreshed against this update's 2026-09-05 date.** Not introduced by this amendment and not urgent, but worth a re-check next time the spine is touched given the table's own framing implies periodic re-verification.

**File written to:** `/Users/olu/Documents/rob/_bmad-output/planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/reviews/review-rubric-walker.md`
