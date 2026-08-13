# Rubric Walker Review — Rez Ops Architecture Spine

**Target:** `_bmad-output/planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/ARCHITECTURE-SPINE.md`
**Reviewed:** 2026-08-12
**Applicable checks:** greenfield (no brownfield ratify), no driving spec (no capability map), no parent spine (no inheritance check)

## Verdict

**Pass with findings.** The spine is coherent and its seven ADs cover the dominant divergence risk in this design (the Sensors/Ledger/Voice boundary and the shared schema), but it leaves two real corners of the operational/environmental envelope silent — credential handling across connectors and failure/alerting for the headless scheduled path — and is inconsistent about version pinning for one stack entry.

---

## 1. Real divergence points for the level below — mostly covered, two gaps

The level below this spine is: four independently-built Sensor MCP servers (calendar, ticketing, git, CMDB), one Ledger-Core MCP server, and a Voice runtime that is external/unowned code. Divergence risks I checked for and their disposition:

| Divergence risk | Covered? | Where |
| --- | --- | --- |
| Record shape mismatch across connectors | Yes | AD-4, shared `ledger_schema` module |
| Confidence computed differently per connector | Yes | AD-5, ledger-core sole owner |
| A connector or the runtime growing domain logic | Yes | AD-1 |
| Server scope creep / monolith drift | Yes | AD-2 |
| Unaudited edits to ledger state | Yes | AD-3 |
| An outbound write path bypassing human approval | Yes | AD-6 |
| Assuming hosted infra one runtime can't replicate | Yes | AD-7 |
| **Credential/secrets acquisition per connector** | **No** | Consistency Conventions only says "no secrets committed to git" — never states where/how each of the four connectors is expected to source API keys/tokens (env var? OS keychain? untracked local file?). Each connector is built independently (AD-2), so this is a live divergence point: one could read `os.environ`, another a `.env` file, another a keychain entry, and setup instructions/`rezops.config.yaml` semantics would fragment accordingly. |
| **Failure/alerting contract for the headless scheduled path** | **No** | AD-7 fixes *how* scheduled work is triggered (cron/launchd → headless runtime invoke) but not what happens when that run fails (source API down, expired auth, git push conflict). With no owner or convention for surfacing failure, whether a given connector/skill treats a failed run as silent-degrade vs. hard-fail is left to whoever builds it. |

Everything else that could plausibly diverge two builders is closed off by an AD or a Consistency Convention row. No divergence point is missed *in scope* — the two above are genuine gaps, not nice-to-haves.

## 2. AD Rule enforceability

Six of seven ADs are enforced structurally, not just by convention, because each domain is a separate MCP server process — a connector literally cannot reach into ledger-core's internals, so AD-1 (partially), AD-2, AD-3, AD-4, AD-5, AD-6 have a real mechanism behind them, not just a stated intention.

One partial exception:

- **AD-1's "the runtime holds no domain logic" clause** has no analogous enforcement. The Voice layer is external, unowned code (Claude Code or any MCP client) driven by prompts/skills that Rez Ops authors write. Nothing in the spine says how this is checked (no review gate, lint, or test called out) — it depends entirely on the discipline of whoever writes those prompts/skills later. This is common for this class of architectural boundary and I would not block on it alone, but it is the one Rule in the document whose enforceability is weaker than its siblings, worth naming explicitly since the checklist asks whether each Rule "actually prevents" its divergence.

All other Rules are concrete, testable-in-review, and map 1:1 to the divergence they claim to prevent.

## 3. Deferred — nothing load-bearing found

Walked each Deferred bullet for "could this let two units build incompatibly if skipped":

- Briefing delivery channel — cosmetic, swappable view; no.
- Write-back/auto-actioning, Blast Radius Rewind, micro-drills — not built in v1 at all; no divergence surface exists yet.
- Packaging (personal vs. product) — doesn't affect any interface between the components that do exist in v1.
- Vendor adapters — explicitly reasoned: AD-2 (server-per-domain) + AD-4 (shared schema) already pin the *interface* the adapter must honor, so the adapter choice itself can't cause incompatible builds.
- Confidence-scoring formula — explicitly reasoned and correctly so: AD-5 gives ledger-core sole ownership, so there is only ever one builder touching this; a single owner can't diverge from itself.
- MCP SDK v2 migration — pinned away (`<2`) until it settles; no divergence risk while pinned.
- Multi-user/multi-tenant — not in v1's build surface.

Nothing deferred is secretly load-bearing. This section is clean.

## 4. Named tech verification / pinning

| Entry | Assessment |
| --- | --- |
| Python 3.12+ | Concrete floor, reasonable, not vague. |
| `mcp` (Python MCP SDK) 1.29.x, pinned `<2` | Well pinned, and the Deferred section shows the verification actually happened — it names the exact v2 ship date (2026-07-28) as the reason for holding at 1.x. This is evidence of a real, dated check, not a guess. |
| Claude Code (reference runtime): **"current"** | **Vague** — not a pinned or dated version, inconsistent with the rigor applied to the other two entries. AD-7's cron/launchd flow depends on a specific headless invocation (`claude -p --bare --output-format json`); if that flag surface changes on a future "current" release, the documented invocation breaks with nothing in the spine to catch it. This is a finding, not a blocker, but it's the one stack entry that reads unverified. |
| git | Not version-pinned, but correctly so — it's used at the level of "a git repo + remote," not a feature-specific version dependency. No finding. |

## 5. Operational/environmental envelope (explicit focus item)

AD-7 ("Local-first operational envelope") is a real, substantive answer to deployment strategy and infra/provider strategy: no hosted DB, no orchestration, no persistent process, git-as-persistence, OS scheduler for cron work, runtime-portable. This dimension is **not** silently skipped — it has its own AD, which is the right weight for an initiative-altitude decision.

Two sub-dimensions under "operations" are thinner than the rest of the document, per the gaps in §1:

- **Failure handling / alerting** for the headless scheduled path is undecided and unmentioned, not even flagged as an open question or deferred item.
- **Credential/secrets handling** for connectors is asserted negatively ("no secrets committed to git") but never given a positive convention.
- **Git remote push conflict handling**: AD-7 states durability comes from "a git remote, pushed after each session," but doesn't address what happens if that push fails (offline, or diverges from another session's history). Low risk given v1 is explicitly single-owner/single-session, but it's an operational edge the spine is silent on rather than having explicitly deferred.

These are gaps *within* an otherwise-addressed dimension, not a wholly silent dimension — AD-7 clearly exists and does real work. But per the checklist's specific call-out for the operational/environmental envelope, I'm flagging them rather than letting partial coverage read as complete coverage.

## 6. Checks skipped per instructions

- Brownfield ratification — skipped (greenfield).
- Spec capability coverage / Capability→Architecture Map — skipped (no driving spec; brief + addendum only).
- Parent spine inheritance — skipped (`binds: []`, confirmed no parent).

---

## Findings (ranked)

1. **Operational envelope gap — no failure/alerting contract for the headless scheduled run.** AD-7 fixes the trigger mechanism (cron/launchd → headless runtime) but not what happens when that run fails (source API down, expired auth, git push conflict). Nothing owns "the nightly briefing silently didn't happen" as a state. Recommend either a Rule addition to AD-7 or an explicit Deferred/open-question entry.

2. **Credential/secrets handling convention is undefined across connectors.** "No secrets committed to git" states a constraint but not a mechanism. Since the four Sensor servers are built independently (AD-2), each could invent its own way to source API keys, fragmenting setup and config semantics in a way AD-4 doesn't reach (AD-4 only governs the ledger data schema, not connector credential config). Recommend a Consistency Convention row or a small AD.

3. **Stack table version rigor is inconsistent.** Claude Code is listed as "current" while Python and the MCP SDK are pinned/dated with a stated rationale. Given AD-7's cron/launchd flow depends on a specific headless CLI invocation, an unpinned "current" is the one stack entry that reads as unverified rather than deliberately unbounded.

4. **AD-1's "no domain logic in the runtime" clause lacks an enforcement mechanism**, unlike its sibling ADs which are enforced by MCP-server process boundaries. It relies entirely on discipline when authoring prompts/skills for Voice, with no stated review gate. Minor, but worth a one-line note (e.g., "reviewed at PR time against this Rule") if the authors want the same enforceability as the rest of the document.

5. **Git remote push failure/conflict handling is unaddressed.** AD-7 asserts durability via "git remote, pushed after each session" without saying what happens on push failure or divergence. Low risk given the explicit single-owner/single-session v1 scope, but currently neither decided nor deferred — just silent.

**File written to:** `/Users/olu/Documents/rob/_bmad-output/planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/reviews/review-rubric-walker.md`
