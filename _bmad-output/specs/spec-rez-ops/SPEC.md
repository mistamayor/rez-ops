---
id: SPEC-rez-ops
companions:
  - '../../planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/ARCHITECTURE-SPINE.md'
  - '../../planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/solution-design.md'
  - '../../../docs/architecture-next.md'
  - '../../../docs/provider-adapter-contract.md'
sources:
  - '../../planning-artifacts/briefs/brief-Resillience-Ops-2026-08-12/brief.md'
  - '../../planning-artifacts/briefs/brief-Resillience-Ops-2026-08-12/addendum.md'
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Rez Ops

## Why

A pain to solve, for DR/resilience program owners at large, always-on organizations: DR program artifacts (BIAs, tiering, runbooks, RACI, test schedules) are scattered across disconnected systems with no shared concept of freshness, so reconstructing the program's true state is manual and slow — done only under pressure, right before an audit or right after an incident proves a gap was real. Rez Ops closes that gap as a thin, read-only orchestration layer over the tools a program already has, rather than a new system of record, so the program becomes proactive instead of reactive. A September 2026 evolution adds an opportunity to capture: the same read-only, ledger-owned discipline should run on whichever subscription-backed local agent runtime the operator already has — Claude Code, Codex, or Google's Antigravity CLI — launched by Rez Ops itself for unattended work, so no single vendor's runtime is ever load-bearing for the program's state.

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
  - **success:** An OS-scheduled invocation completes end-to-end and updates ledger state or logs a failure explicitly; no scheduled run fails silently. Once Driven mode exists (CAP-14), the scheduled path runs through the agent runtime: the existing scheduled-briefing script's hard-coded vendor invocation is a named, grandfathered exception until Phase 1 makes it a thin shim over the claude adapter, and a driven-mode failure surfaces as a `session.failed` event plus a non-zero exit rather than an `_ops.log.md` line.

- **CAP-9 — Evidence-backed claims**
  - **intent:** Let Voice make a reasoning-layer claim about ledger state as a structured `EvidenceBundle` (claim, confidence, cited facts, reasoning) rather than unattributed prose, with confidence computed exclusively by ledger-core from the cited evidence — never supplied by the caller.
  - **success:** Every `EvidenceBundle`'s confidence is ledger-core-computed, not accepted as input; a caller-supplied confidence value is rejected as a schema violation; every citation resolves back to a real ingested fact or ledger record, never an inline duplicate.

- **CAP-10 — Policy-gated action proposals**
  - **intent:** Let Voice propose a system-state-changing action — naming it from a config-declared vocabulary, citing at least one `EvidenceBundle` — and have ledger-core alone compute whether it's automatic, requires human approval, or is denied, without any component executing it.
  - **success:** Every `ActionProposal`'s `policy_decision` is computed by ledger-core from config-declared action risk, target criticality, and the minimum confidence across cited evidence — never asserted by the caller; naming an undeclared action or citing no evidence is rejected before anything is recorded; no code path in v1 consumes an approved/automatic decision to perform the action against any external system. From Phase 3 the `decided` event also records the SHA-256 of the policy and tiers files it was evaluated against, so which policy version was used is answerable from the log alone.

- **CAP-11 — Tiered DR risk classification**
  - **intent:** Compute each artifact's DR risk level from its config-declared tier, current freshness against that tier's expiry rule, and its confidence — closing the gap where `tier_sla`/`expiry_rule`/`verification_method` have existed in the schema since CAP-1 but no story has ever populated them.
  - **success:** An artifact whose type has a declared tier gets a computed `tier_sla`, `expiry_rule`, and risk level (high/medium/low); an artifact with no declared tier resolves to the most conservative reading (risk unknown), never a guess; every value is ledger-core-computed, never accepted as connector/caller input.

- **CAP-12 — DR test achievement signals**
  - **intent:** For a DR test result, compute how well the test actually performed against its declared target — RTO/RPO achieved as a percentage of target, not bare pass/fail — and whether it ran inside the program's mandated annual testing window, an independent compliance signal regardless of pass/fail.
  - **success:** A DR test result artifact carrying target and actual recovery-time fields gets computed RTO-achieved and RPO-achieved percentages; a test scheduled outside the config-declared testing window is flagged even if it later passes; both values are ledger-core-computed, never accepted as connector/caller input.

- **CAP-13 — Executive dashboard generation**
  - **intent:** Generate a self-contained, static HTML snapshot of current DR readiness (KPI tiles + RAG status per tier) from real ledger state via a regenerate-on-demand script — no hosted server, no new computation, a human-facing view of what CAP-4/CAP-11's existing query surface already returns.
  - **success:** Running the generation script produces a valid HTML file whose displayed KPI/RAG values exactly match what the underlying query functions return at the same point in time — the same "must match a live query" criterion CAP-7 already established; any view without a real backing data source is visibly labeled as not-yet-wired, never populated with fabricated numbers presented as real.

- **CAP-14 — Driven-mode agent runtime**
  - **intent:** Let Rez Ops itself launch a provider's official local agent CLI headless (Driven mode) against exactly the MCP server set a human's own client loads (Hosted mode), so unattended work reaches Sensors and Ledger through the same tools a human would, from a runtime package (`agents/`) that is a peer of `ops/` and never part of the Ledger.
  - **success:** `rezops agent run --provider <name>` completes a simple non-destructive task through Rez Ops's MCP tools for the fake adapter and for each subscription-authenticated real provider; a driven session's loaded server set equals `.mcp.json`'s exactly, derived per run and never hand-maintained; a launch where not every server attaches fails as `MCP_ATTACH_FAILED` rather than running degraded; `ledger_core/` imports, spawns, or awaits nothing in `agents/`.

- **CAP-15 — Probed provider health and capabilities**
  - **intent:** Report what each provider runtime can actually do right now — installed, authenticated, healthy, its capability set and auth mode — by probing the real runtime at call time, rendered for a human by `rezops doctor` and consumed by the same code path for any run.
  - **success:** `rezops doctor` reports every adapter by probe, correctly distinguishing installed, installed-but-unauthenticated, and wrapper-present-binary-missing; health is judged from the runtime's structured result, never its exit code alone; a failed probe names a specific failure code and leaves the task bound for that provider pending and visible; no config file supplies a capability claim.

- **CAP-16 — Agent session record**
  - **intent:** Record every driven session, task, tool call, claim, and outcome as an append-only event stream in the agent runtime's own store (`agent_data/`), with current state a pure projection, so what an agent did — and whether a run failed — is answerable from the store alone without any provider transcript, and a session can be resumed or cancelled by its Rez Ops session id.
  - **success:** Every driven run leaves a `session.started`-to-terminal event trail in `agent_data/sessions/`; a failure is a `session.failed` event plus a non-zero exit, never silent; the provider's native session id is recorded separately from the Rez Ops session id, and resume/cancel address the Rez Ops id; no event payload contains a credential value; no transcript exists unless opted in, and then git-ignored and consumed by nothing; ledger-core never reads or writes `agent_data/`, and `agents/` never writes `ledger_data/`.

- **CAP-17 — Environment-attested provenance on every Ledger write**
  - **intent:** Stamp every record a ledger-core write tool creates — `RawFact` ingest, `Draft`, `EvidenceBundle`, `ActionProposal` — with who wrote it (session, provider, model, mode, auth mode, operator), sourced from ledger-core's own process environment and never a tool argument, so a fact or claim relayed by a driven LLM is attributable and never indistinguishable from an observed fact.
  - **success:** A record written from a driven session carries exactly that session's stamp (the contract suite's end-to-end check); a caller-supplied provenance value is rejected as a schema violation; a partial or malformed `REZOPS_AGENT_*` set refuses the write as `PROVENANCE_INVALID`, never falling open to hosted; a hosted-mode record stamps mode hosted with the operator from `REZOPS_OPERATOR`, or unknown when unset, never a guess; every record written before the stamp existed reads back as provenance null and is never rejected or downgraded; anything the fake adapter authors carries provider fake.

- **CAP-18 — Provider adapter contract**
  - **intent:** Ship four adapters — fake (in-process, no binary), claude, codex, google — each driving one vendor's official local runtime under one contract, proven by one shared contract suite that the fake adapter both passes and fault-injects against, so the fake is the contract's executable definition rather than a stub.
  - **success:** Every adapter passes `tests/providers/` with no adapter-specific skips; the fake can inject every code in the shared failure enum; the four negative launches fail with the right code — wrong `.mcp.json` gives `MCP_ATTACH_FAILED`, an extra server in the provider's global config gives `TOOL_SCOPE_VIOLATION`, an ambient API key without per-provider opt-in gives `AUTH_MODE_MISMATCH`, environment forwarding unavailable gives `PROVENANCE_UNAVAILABLE`; a search for a vendor's name outside its adapter package returns nothing; no `REZOPS_*` value appears in any generated file; nothing under `.rezops/run/` or `agent_data/transcripts/` is tracked by git.

## Constraints

- No connector may write to any external system of record in v1 (read-only-first).
- Any Rez Ops failure (a connector or ledger-core outage) must fail open to today's manual baseline — never blocking or worsening the DR program (graceful degradation).
- Every derived/computed value must carry an explicit confidence state; no derived value may be presented without one (never hide uncertainty).
- v1 runs local-first: no hosted database, container orchestration, or persistent server process; the agent runtime is invoked per run under a wall-clock budget and exits, never a resident daemon; git is the sole persistence layer for `ledger_data/` and `agent_data/` alike.
- Ledger state is mutated only through an append-only log; no in-place edits — single writer, auditable history.
- v1 favors fewer, high-trust, provenance-ranked sources over broad source coverage.
- Voice may propose a claim or an action; it never computes the derived value that evaluates it — `EvidenceBundle.confidence`, `ActionProposal.policy_decision`, and CAP-11/CAP-12's `tier_sla`/`expiry_rule`/risk level/RTO-RPO-achieved values are all ledger-core-exclusive, the same discipline as CAP-3's confidence computation extended to the proposal and risk-classification layers.
- A generated dashboard view without a real backing data source must be visibly labeled as such, never populated with fabricated numbers presented as real — extends the same never-hide-uncertainty discipline to the presentation layer (CAP-13).
- No provider runtime is ever a system of record: every fact, claim, decision, and action lives in `ledger_data/` and is fully reconstructable with every provider gone; `ledger_core/` never imports, spawns, or awaits the agent runtime, and the runtime holds no domain logic in either mode.
- `.mcp.json` is the single source of truth for the server set in both modes: a driven adapter derives its provider's native MCP config from it per run into a git-ignored per-session location, launches the provider with the project root as working directory and its home directory untouched, and a provider's global MCP config never merges extra servers into a driven session.
- Provider capabilities are probed at call time, never declared: no config file asserts what a provider can do; a future preferences file holds routing preferences only, never capability claims; health is read from the runtime's structured result, never its exit code alone.
- Two stores, two writers: `agents/` writes only `agent_data/`, ledger-core writes only `ledger_data/`, and the only thing crossing between them is a provider session calling the same MCP tools a human would — no new write tool, no side channel; no secret ever lands in `agent_data/`.
- Provenance is never caller-supplied: ledger-core reads it from its own environment; the launcher sets the four `REZOPS_AGENT_*` variables and forwards them by name, never by value (an adapter that cannot fails the launch as `PROVENANCE_UNAVAILABLE` rather than writing values into a file); the stamp is required on write, optional on read.
- Every provider adapter obeys the seven-clause contract in `provider-adapter-contract.md` (AD-20): it launches the vendor's official runtime and never extracts, proxies, stores, or logs its credentials; `auth_mode` is recorded on every session, SUBSCRIPTION by default and API only by explicit per-provider opt-in; vendor CLI names, flags, and config formats appear only inside that adapter's package; failures come only from the one closed enum (housed in `agents/core` during Phase 1, in `shared/` from Phase 3), never "unknown error"; provider selection is deterministic and inspectable, never an LLM's choice, with requested and executed providers both recorded; a driven session's tool scope is exactly the (server, tool) set from `.mcp.json`, enforced by strict MCP-config mode, denial of the provider's built-in shell/file-write/web tools, and a loaded-server-set check before the first task — never a skip-all-permissions flag.
- Phase ownership is fixed: Phase 1 builds `agents/` (core, the four adapters, `agent_data/`, the `rezops` CLI) and changes nothing in `ledger_core/`, `connectors/`, or `shared/` — it only sets the `REZOPS_AGENT_*` environment; Phase 3 owns the provenance stamp on all four write tools, the policy-file hash on `decided`, and the one system-wide failure enum in `shared/` — during Phase 1 the agent failure codes are defined in `agents/core`, and Phase 3 relocates them into `shared/` beside the connector, ledger, and policy codes. Adapter build order is fixed by dependency: core + fake + contract suite first, claude second, codex and google after, each against the same suite.
- Everything a Sensor returns and everything a provider emits is untrusted data, never instructions.

*Full mechanism for each of these lives in `ARCHITECTURE-SPINE.md` (AD-1 through AD-20); the adapter clauses are restated as a reviewer's checklist in `provider-adapter-contract.md`.*

## Non-goals

- Auto-actioning against any system of record: a computed `policy_decision` (CAP-10) is a recorded judgment, not a permission that anything acts on.
- An Executor that consumes an `ActionProposal`'s `policy_decision` to actually perform the action against any external system — explicitly deferred; a separate, later, deliberate decision, not a default extrapolation from CAP-10 existing.
- A retroactive "would-have-caught-it" scoreboard against past incidents (Blast Radius Rewind).
- Proactive or surprise micro-drills, or agent-triggered synthetic failovers.
- Auto-sending owner-reconfirmation messages or any outbound content without human approval.
- A passive-observation, watch-only baselining period.
- Multi-user or multi-tenant support.
- Packaging as an installable product for other practitioners — left open, not decided for v1.
- Migrating to MCP SDK v2 before Phase 3: the `<2` pin holds through Phases 0–1 because adapters launch CLIs and never import the SDK; revisit before Phase 3, where the 1.x/2.x elicitation API difference would first bite.
- Automatic tier discovery: an artifact's tier is declared in a git-tracked config file, never inferred from a CMDB field, a connector, or any live system.
- A live, auto-refreshing, or hosted dashboard: CAP-13 generates a static snapshot only, regenerated on demand by rerunning the script; a persistent server process is a separate, later, deliberate decision, not a default extrapolation from this capability existing.
- Inverting the usage model: Hosted mode — the human's own MCP client loading `.mcp.json` — is unchanged by this evolution; interactive Claude Code does not become "the claude provider in interactive mode", and a driven session is not privileged over a hosted one.
- Missions and tasks, provider routing and a providers preferences file, multi-agent review, agent skills, a typed domain model, and a mission scheduler — each is Deferred in the spine to a named later phase; Phase 1 builds no routing and the caller names the provider.
- A resident agent daemon or polling scheduler: the OS scheduler invoking `rezops agent run` is the whole scheduler until a concrete requirement forces more.
- Fixing `AgentProvider` method signatures before the Phase 1 spike has inspected the real runtimes: the contract's invariants are fixed now; the interface is designed after inspection, never prematurely.
- Rez Ops handling any provider's credentials — extracting, proxying, converting, storing, or logging them, scraping a private web session, or bypassing a vendor's rate or usage limit; API auth mode stays unbuilt until a user opts in for a specific provider.
- An LLM-free Sensor-to-Ledger relay: today every `RawFact` reaches the Ledger through the runtime; CAP-17 makes that relay attributable, and removing the LLM from the path would amend the mediation rule and is its own later decision.
- Treating a provider transcript as domain truth: transcripts are opt-in, git-ignored debugging aids consumed by nothing.

## Success signal

Zero "we didn't know that was stale" surprises at the next audit or review; "who owns X" answered in seconds via a live query instead of days of chasing; a generated briefing consistently surfaces genuinely new information rather than repeating already-handled items; every proposed action shows its evidence trail and policy decision before any human is asked to approve it — never a bare recommendation with no attributable reasoning; every computed risk level or RTO/RPO-achieved percentage traces to a declared tier and an observed freshness/confidence/test-result value — never a bare label with no derivation; and each of the three real provider runtimes answers "what is the current DR readiness?" through the same Rez Ops MCP tools with no provider-specific domain logic, `rezops doctor` reports every provider honestly by probe, and every Ledger record written from a driven session names the session, provider, and mode that wrote it — never an unattributed relayed fact.

## Assumptions

- Primary user and scale modeled on a Booking.com/Expedia-scale global travel or e-commerce business; the real target scale is otherwise unconfirmed.
- The refuse-to-be-a-system-of-record differentiator is a product-philosophy choice, not a defensible technical moat, and could be replicated by a competitor.
- The plan's Phase 1 exit criterion — `rezops doctor` reports each provider, `rezops agent run --provider fake` works, each authenticated real provider performs a simple non-destructive task — is adopted as CAP-14/CAP-15's demonstrable bar, and the Phase 3 exit (each provider answers the DR-readiness question via the same tools) as CAP-17/CAP-18's.
- The vendor facts this spec rests on (Claude Code 2.1.269 loads all seven servers headless in strict MCP-config mode; Codex CLI runs headless with a TOML MCP config; Google Antigravity CLI 1.2.0 is the individual-subscription route since Gemini CLI stopped serving it on 2026-06-18) were verified 2026-09-12 and are re-probed at every run, never pinned by this spec.

## Open Questions

- Is Rez Ops a personal configuration for a single program owner, or does it need to support installation by other DR practitioners? Affects how generic connector configuration and onboarding need to be.
- Which specific calendar/ticketing/CMDB vendor products will the first connectors target?
- Should v1 capabilities design directly for secondary users (compliance stakeholders, application/service owners), or stay scoped to the primary program-owner user until the capability set stabilizes?
