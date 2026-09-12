# Reconciliation Review — `docs/product-direction.md` vs. ARCHITECTURE-SPINE.md (AD-16..AD-20 amendment)

- **Reviewer role:** reconcile-plan (what did NOT land, contradictions, over-reach)
- **Date:** 2026-09-12
- **Inputs:** `docs/product-direction.md` (plan; load-bearing §5, 6, 18–29, 34–42, 48–50, 61–65, 78, 87, 88 — plus §4, 52–55, 79 read for quiet rules) and `ARCHITECTURE-SPINE.md` as of `updated: 2026-09-12` (AD-16–20, AD-1/AD-7 in-place amendments, Agent-runtime Conventions row, Stack, Structural Seed, Deferred). `.memlog.md` lines 86–104 read for the amendment's declared overrides.
- **Currency note:** the spine was edited on disk mid-review (AD-16 stdio-shape clause, AD-17 "structured result, never exit code alone", Antigravity Stack row, elicitation Deferred item). Re-diffed 2026-09-12; none of those edits touch any finding below. AD-16's new "stdio entries … the only kind Rez Ops ships" clause narrows, but does not close, O-1 — it still makes env inheritance a per-adapter fact to verify in the spike.
- **Declared scope honoured:** Phase 0 baseline for the Phase 1 spike. Missions/routing/multi-agent/domain model are correctly Deferred with owning phases and are not counted as gaps.

## Verdict

**CONDITIONAL PASS.** The amendment lands the plan's big invariants faithfully (subscription-first, no provider as system of record, probed capabilities, separate agent store, environment-attested provenance, deterministic routing invariant, deferred signatures). Two findings need a fix before this is a safe Phase 1 baseline: (1) AD-20 §7 grants a driven session **every** `mcp__ledger-core__*` tool, including `ledger_ingest_raw_fact` and `ledger_create_draft`, neither of which AD-19 stamps with provenance — so the spine's own AD-18 claim ("agent output enters the Ledger only as a structured claim through AD-11/AD-12") is not true of the tool set it grants, and the plan's §28 forbidden path ("Claude said X" → "Rez Ops knows X") is open via a fabricated `RawFact.source`; (2) AD-19 requires a `ledger_core/` change (env-read + schema stamp on `EvidenceBundle`/`ActionProposal`), but the plan's Phase 1 says "Do not modify Ledger" and the spine never says which phase carries AD-19's ledger-core half. Everything else is medium or lower: the plan's system-wide failure enum landed as adapter-only, "no secret values in logs" is not bound for `agent_data/` (which is git-committed *with* raw transcripts), and "what policy version was used?" (§41) is still unanswered anywhere in the spine.

## Did not land

Ordered by severity. "Landed as" says where the nearest spine text is; "Gap" says what is missing.

### DNL-1 · **high** · §28, §38 rule 4 & 9, §19 — driven sessions can write un-provenanced `RawFact`s and `Draft`s

- **Plan:** §28 "The agent must submit a structured claim. The Ledger validates it … `Claude said X` must never automatically become `Rez Ops knows X`." §38 rule 4 "Agent output is untrusted until validated", rule 9 "Provenance is mandatory."
- **Landed as:** AD-18 ("Agent output enters the Ledger only as a structured claim through the existing AD-11/AD-12 tools … no new write tool, no side channel"); AD-19 stamps provenance on `EvidenceBundle` and `ActionProposal` only; AD-20 §7 grants a driven session "exactly the Rez Ops MCP tools (`mcp__<server>__*` for the servers in `.mcp.json`)".
- **Gap:** `ledger_core/server.py` today exposes `ledger_ingest_raw_fact(artifact_type, artifact_id, source: str, fields)` and `ledger_create_draft`. Both are inside the §7 grant, both are pre-existing (not "new") write tools, and neither is covered by AD-19. A driven LLM can therefore append a `RawFact` whose `source` string it invented — it becomes a first-class observed fact, feeds `get_record`'s confidence/`tier_sla`/`risk` projection (Story 17), and is indistinguishable from a connector-relayed fact. That is exactly the §28 path, one layer *below* the claim boundary AD-11 guards. The Design Paradigm's "the Runtime mediates all data flow between [Connectors and Ledger-Core]" makes the runtime the relay for every RawFact, so this isn't an edge case — it is the main ingest path, now driven by an LLM that may have read prompt-injected content (§38 rule 3). The spine needs one of: (a) extend AD-19's stamp to `RawFact` events and `Draft` records (provenance on *every* ledger-core write, matching the Conventions row's "every write records actor"); (b) exclude `ledger_ingest_raw_fact` from the driven tool scope in AD-20 §7 and state how driven sessions get facts into the Ledger; or (c) state explicitly that a driven-session RawFact carries `provenance.mode: driven` and how AD-10/AD-5 treat it. Also amend AD-18's sentence so it stops claiming a property the granted tool set does not have.

### DNL-2 · **high** · §63 ("Do not modify Ledger") vs AD-19's ledger-core change — phase not stated

- **Plan:** Phase 1 exit criteria are `rezops doctor` + `rezops agent run --provider {fake,claude,codex,google}` doing a simple non-destructive task; explicit constraint "Do not modify Ledger." Phase 3 (§65) is the first phase where agents touch Rez Ops MCP.
- **Landed as:** AD-19 binds `ledger-core` and requires it to read `REZOPS_AGENT_*` from its environment and stamp a `provenance` block on every `EvidenceBundle`/`ActionProposal` — a `ledger_core/` code change and a record-schema change.
- **Gap:** The spine's scope line says "AD-16–20 are the Phase 0 architecture baseline"; nothing says AD-19's ledger-core half is a Phase 3 deliverable rather than Phase 1. An implementer reading AD-19 as "part of the Phase 1 baseline" would violate §63. Fix: one sentence in AD-19 (or Deferred) — "the ledger-core stamp lands with Phase 3 (first agent ↔ MCP integration); Phase 1 only *sets* the env vars." Note also that stamping provenance on existing records is a `LedgerRecord`/`EvidenceBundle` schema addition and should be called out as additive under §79 Rule 2.

### DNL-3 · **medium** · §37 — failure semantics landed adapter-only; plan's enum is system-wide

- **Plan:** §37 lists `CONNECTOR_UNAVAILABLE, AUTHENTICATION_FAILED, RATE_LIMITED, SOURCE_DATA_INVALID, LEDGER_UNAVAILABLE, AGENT_UNAVAILABLE, AGENT_TIMEOUT, AGENT_QUOTA_EXHAUSTED, POLICY_REJECTED, APPROVAL_REQUIRED, EVIDENCE_INVALID` and "Do not collapse every failure into unknown error" — a cross-cutting rule.
- **Landed as:** AD-20 §4 / Conventions "Agent runtime" row: one shared enum for *adapters* (`PROVIDER_NOT_INSTALLED, AUTHENTICATION_FAILED, AGENT_UNAVAILABLE, AGENT_TIMEOUT, AGENT_QUOTA_EXHAUSTED, RATE_LIMITED, AGENT_OUTPUT_INVALID, …`).
- **Gap:** `CONNECTOR_UNAVAILABLE`, `LEDGER_UNAVAILABLE`, `SOURCE_DATA_INVALID`, `POLICY_REJECTED`, `APPROVAL_REQUIRED`, `EVIDENCE_INVALID` have no home: the "Data & formats" Conventions cell names "error shapes" in its header but defines none, and AD-8 speaks of an explicit `unknown` *state*, not an explicit failure *code*. Specifically Phase-1-relevant: a driven launch where one or more `.mcp.json` servers fail to attach. AD-7 warns about `--bare` running "with no Sensors or Ledger attached", the Codex Stack row notes `required = true`, and Claude's init event reports server count — but no invariant says "a driven session whose required Rez Ops servers did not all attach reports `LEDGER_UNAVAILABLE`/`CONNECTOR_UNAVAILABLE` and does not proceed silently degraded." Add that clause to AD-16 or AD-20 §4, and either widen the enum to the plan's full list or record the ledger/connector-side codes in Conventions.

### DNL-4 · **medium** · §38 rule 8 ("No secret values in logs") and rule 3 — not bound for `agent_data/`, which is git-committed with raw transcripts

- **Plan:** §38 rule 8; §28 "A provider transcript may be retained separately for debugging/audit **if appropriate**"; §42 "Store observable execution metadata and structured outputs, not hidden chain-of-thought."
- **Landed as:** AD-7 (provider *credentials* never appear in any log); AD-18 (`agent_data/transcripts/` optional, "consumed by nothing"; "`agent_data/` is git-committed like `ledger_data/`").
- **Gap:** Nothing binds redaction or content limits on `tool.called`/`tool.completed` payloads or transcripts. A transcript of a driven session contains every connector result the agent saw (ticket bodies, document titles — the untrusted external content of rule 3) and any secret a connector or CLI happened to echo. Committing that to git by default is a decision the plan does not make and rule 8 argues against. Needs either: payloads carry tool name + argument/result *summaries or hashes*, not bodies; transcripts are opt-in, git-ignored by default, and retention-bounded; or an explicit "no secrets / no raw external content in `agent_data/`" convention with a stated enforcement point.

### DNL-5 · **medium** · §41 — "What policy version was used?" is answered nowhere

- **Plan:** §41's reconstruction list includes "What policy version was used?"
- **Landed as:** AD-12 records `policy_decision`; AD-19 records `{session_id, provider, mode, auth_mode, operator}`.
- **Gap:** No AD or convention records the `rezops.policy.yaml` (or `rezops.tiers.yaml`) version/hash on the `decided` event or on a `LedgerRecord`'s computed `tier_sla`/`risk`. Pre-existing before this amendment, but §41 is in the load-bearing set and AD-19 was the natural place to add it (provenance block or `decided` payload). One field (`policy_ref: {file, git_sha | content_hash}`) closes it.

### DNL-6 · **medium** · §38 rule 3 / §79 Rule 9 — "external content is untrusted" lands only as Driven-mode rationale

- **Plan:** "External documents are untrusted" / "Documents, tickets, repository content and external text must never be treated as trusted instructions" — mode-independent.
- **Landed as:** AD-20 §7's *Prevents* clause (prompt-injected content having no path to act) — driven mode only; "Hosted mode … is not constrained by clause 7."
- **Gap:** No convention states the rule itself, so nothing binds connectors (e.g. returning content as data, never as instruction), the hosted path, or the future Phase 7 document-content ingestion. A one-line Conventions entry ("all connector-returned content is data; no component interprets it as instruction; driven mode enforces via AD-20 §7, hosted mode relies on the human") makes the quiet rule visible.

### DNL-7 · **medium** · §19 — "must not scrape private web sessions" and "must not bypass vendor limits"

- **Landed as:** AD-20 §1 (never extract/proxy/convert/store/log credentials; official runtime only) and §38 rule 12 (never bypass vendor *authentication*).
- **Gap:** "Bypass vendor limits" (quota/rate limits — e.g. retry-hammering on `RATE_LIMITED`, multi-account rotation, parallel session fan-out to dodge a cap) is not covered by any clause; "scrape private web sessions" is only implied by "official local runtime". Both are cheap to add to AD-20 §1.

### DNL-8 · **low** · §42 — `model/runtime` version not on the session/event record

- **Plan:** agent-run record includes `model/runtime`.
- **Landed as:** AD-17 probes "binary present, version"; AD-18 event fields are `timestamp, session_id, provider, mode, auth_mode, event_type, payload`.
- **Gap:** The probed runtime version (and model, where the CLI reports it) is not required on `session.started` or in the AD-19 provenance block. Without it, "which provider was used?" (§41) can't distinguish Claude Code 2.1.77 (MCP regression) from 2.1.269. Add `runtime_version`/`model` to `session.started` payload at minimum.

### DNL-9 · **low** · §52 — fake adapter as a *fault injector*

- **Plan:** the fake should simulate success, timeout, failure, approval, structured result, malformed result, quota exhaustion, session continuation.
- **Landed as:** AD-20 §6 (fake passes the same contract suite; "the contract's executable definition").
- **Gap:** "Passes the suite" does not require the fake to be able to *emit* every enum code and lifecycle path on demand, which is what lets the session layer (Phase 2) be built without burning quota. One clause: "the fake can be driven to produce every AD-20 §4 failure code and every AD-18 event type."

### DNL-10 · **low** · §62 — Phase 0 deliverables listed in the Seed but absent

- `docs/architecture-next.md` and `docs/provider-adapter-contract.md` appear in the Structural Seed tagged "Phase 0 deliverable"; `docs/` currently contains only `product-direction.md`. Not a spine-content defect, but the amendment claims Phase 0 scope and the plan's Phase 0 exit criterion is "Architecture baseline documented" naming those files. Either create them (they can be short projections of AD-16–20) or tag them in the Seed as "to be written".

### DNL-11 · **low** · §78 — `docs/security-model.md`

- Plan §78's target tree includes `docs/security-model.md`; the Seed omits it and Deferred doesn't name it. §38's 12 rules currently live scattered across AD-1/7/12/13/14/19/20. Either add the file to the Seed or note in Deferred that the security model is expressed in-line in the ADs.

### DNL-12 · **low** · §27 — dropped event types

- Plan events `approval.requested`, `agent.message`, `finding.created`, `evidence.created` are absent from AD-18's list (which has `claim.submitted` and a trailing "…"). `evidence.created`→`claim.submitted` is a sensible rename; `approval.requested` is the one that matters for Phase 3 (a driven session whose proposal resolves `requires_approval` should surface it in the event stream so §55's "pending approvals" is answerable from `agent_data/`). The "…" makes this non-blocking; a note that the list is open and maps to the plan's would suffice.

## Contradictions

### C-1 · **high** · AD-18 vs AD-20 §7 (internal) — and both vs plan §28

AD-18: "Agent output enters the Ledger only as a structured claim through the existing AD-11/AD-12 tools … no new write tool, no side channel." AD-20 §7: driven session gets every `mcp__ledger-core__*` tool. `ledger_ingest_raw_fact` and `ledger_create_draft` are existing write tools not covered by AD-11/12 or AD-19. The spine contradicts itself and, through the gap, the plan (§28). See DNL-1 for fix options. This is silent — no clause acknowledges the pre-existing write tools.

### C-2 · **high** · AD-19 vs plan §63 "Do not modify Ledger"

Silent. See DNL-2. Resolved by a phase-assignment sentence, not by changing the rule.

### C-3 · **low** · Terminology: "execution modes" and `LOCAL_SUBSCRIPTION`

- Plan §20: the "two execution modes" are `LOCAL_SUBSCRIPTION | API`. Spine AD-16 title: "Two execution modes" = `hosted | driven`; the plan's pair became `auth_mode: SUBSCRIPTION | API`. Both renames are silent (memlog line 91 still says `LOCAL_SUBSCRIPTION`; the spine says `SUBSCRIPTION`). Harmless, but a reader holding both documents will collide on "execution mode". One line in AD-16 or AD-20 §2 ("the plan's `LOCAL_SUBSCRIPTION`/`API` execution modes are this spine's `auth_mode`; `hosted`/`driven` is a different axis") ends it.

### C-4 · **low** · §28 "debugging/audit" vs AD-18 "debugging … consumed by nothing"

The plan allows transcripts to serve *audit*; the spine says nothing consumes them. If they are truly consumed by nothing they cannot serve audit, and if they may be read by an auditor then DNL-4's redaction question is live. Pick one wording.

### C-5 · **low** · §62 vs §78 file naming (plan-internal), resolved silently by the spine

Plan §62 says `docs/provider-adapter-contract.md`; plan §78 says `docs/provider-adapters.md`. The Seed chose the §62 name without noting the plan's own inconsistency. Fine choice; say so.

### Explicit overrides (acknowledged, no action)

- Keeping the name "Voice" (plan §18 rename) — declared in AD-1 and the Design Paradigm. ✓
- `agents/` is "a Python package plus the `rezops` CLI, not an MCP server" — declared in Conventions, reconciled with AD-2. ✓
- Gemini CLI replaced by Antigravity CLI `agy` for the Google adapter — declared in AD-17/Stack/Seed, matching plan §63's own instruction. ✓
- `rezops` CLI introduced now (plan §53 says "only when it has clear value") — memlog 94 declares it "ADOPTED from plan sec 53/54/63"; §63's exit criteria are the clear value. ✓

## Over-reach

### O-1 · **medium** · AD-19's process-topology assumption is a rule, not a spike question

AD-19 states as rule: "the CLI spawns ledger-core as a child process, so ledger-core inherits [the env vars]." That is true for stdio-transport MCP servers launched by the CLI (today's `.mcp.json`), but it is a property of *each provider's* MCP launch behaviour — precisely what §18 says to inspect before designing. If any adapter derives a config that runs servers over HTTP/SSE, via a daemonised MCP manager, or with a scrubbed environment, the attestation silently degrades to `mode: hosted` (AD-19's absent-vars default) — i.e. a driven claim gets stamped as a human's. Keep the invariant ("provenance is environment-attested, never caller-supplied"), demote the mechanism to "verified per adapter in the Phase 1 spike; the contract suite must assert that a driven session's ledger-core process sees the vars", and add the failure mode: if the vars are *expected* (launcher set them) but a claim arrives without them, that is a launch error, not hosted mode. Related low-severity hardening: the launcher must *clear* stale `REZOPS_AGENT_*` from its own inherited environment before a hosted session could inherit them.

### O-2 · **low** · AD-18 fixes event names, field set, and log path before the spike has seen what providers emit

The plan's own §27 gives an event list, so fixing one is reasonable — but the Conventions row also fixes `agent_data/sessions/{session_id}.log.md` memlog-style and the exact field tuple. Claude emits `stream-json`, Codex emits `thread/turn/item` JSONL, Antigravity emits its own `stream-json`; the mapping to a single normalised stream is exactly the spike's job. Consider marking event names as "candidate, normalised after the spike" the same way AD-20 marks method names.

### O-3 · **low** · Stack rows declare Codex/Antigravity capabilities from vendor docs

AD-17 says capabilities are probed, never declared; the Stack table then declares Codex's `--output-schema`, `resume`, sandbox default, and Antigravity's `--continue`/`--conversation`, soft-deny behaviour "verified from vendor docs" only (Codex is in fact locally broken: wrapper present, binary missing — memlog 99). The rows are clearly version-currency notes, and "pin when the adapter is built" is stated, but a reader may take them as the capability matrix §21 warned against hard-coding. A one-word tag ("docs-verified, not probed") on those two rows keeps AD-17 honest.

### O-4 · none · Interface signatures

AD-20 correctly leaves `AgentProvider` signatures, `AgentSession/Task/Result/Event/ProviderHealth/ProviderCapabilities` shapes, per-provider MCP-config derivation, and permission flags to the spike, and Deferred says why. This is exactly what §18 asked for. ✓

## Landed cleanly (brief)

- **§5 / §6 / §87** — Sensors contract untouched; Ledger never depends on an LLM (AD-1, AD-16 "Ledger never orchestrates agents"); no provider as system of record (AD-1 new clause). ✓
- **§18** — "must not assume Claude Code is the agent" (AD-20 §3 vendor names only inside adapters); signatures deferred; "no premature fake abstractions" quoted verbatim. ✓
- **§19 / §20 / §38 rule 2, 12 / §79 Rule 6, 7** — official runtime only; never extract/proxy/convert/store/log credentials; subscription primary, API explicit opt-in (AD-20 §1/§2, AD-7 amendment, Deferred "API execution mode"). ✓
- **§21** — capability matrix replaced by run-time probe, with real evidence for why (AD-17). Capability keys dropped (`reasoning`, `tools`, `local filesystem`) are consistent with AD-20 §7. ✓
- **§22 / §48 / §49 / §50** — routing invariant fixed (deterministic, inspectable, never LLM-chosen, requested-vs-executed recorded, task stays `pending`), router itself Deferred to Phase 6; `auth_mode` never hidden; `rezops doctor` is the probe's rendering. ✓
- **§23–26** — missions/tasks/scheduling/multi-agent Deferred with owning phases and revisit conditions; the mission `approvals` conflict with AD-12/14 surfaced now rather than later; scheduler must not become a daemon (AD-7). ✓
- **§29** — one MCP surface for both modes; `.mcp.json` single source of truth with per-adapter derivation (AD-16); no business logic in wrappers (AD-1/2). ✓
- **§34 / §35** — policy config-driven, never in prompts; `rezops.providers.yaml` scoped to preferences only (AD-17). ✓
- **§36 / §49** — fail-open to explicit unknown (AD-8); provider failure → visible `pending` (AD-17/20). ✓
- **§38 rules 1, 5, 6, 7 (driven), 10, 11** — AD-1/2, AD-12, AD-13/14, AD-20 §7, AD-12, AD-5/9/11. ✓
- **§39 / §40** — local-first kept; agent runtime per-run, never resident; persistence migration Deferred for both stores. ✓
- **§41 / §42 (mostly)** — session/provider/mode/auth_mode/operator provenance environment-attested (AD-19); observable metadata not chain-of-thought (AD-18). Gaps are DNL-5/DNL-8 only. ✓
- **§61** — Deferred/AD-20 §7 keep the driven agent inside Rez Ops's own tools; no generic assistant. ✓
- **§63** — `agents/providers/{fake,claude,codex,google}`, fake as the contract's executable definition, `tests/providers/` suite, Google → Antigravity, no routing/multi-agent in Phase 1. ✓ (Ledger constraint: see DNL-2.)
- **§65** — Phase 3 exit criterion is the revisit trigger for Missions; MCP SDK v2 revisit pinned "before Phase 3". ✓
- **§78 / §88** — no wholesale reorganisation; `ops/` stays; `domain/ skills/ ui/ missions/ routing/` explicitly not created; first engineering objective restated in the Design Paradigm. ✓
- **§79 Rule 5** — "no fake implementations" honoured by making the fake loud (`provider: fake` by construction) — a genuinely good reconciliation. ✓
