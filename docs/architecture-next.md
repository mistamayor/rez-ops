# Architecture Next — the agent-runtime amendment, for implementers

**Status:** Phase 0 deliverable (architecture baseline). No runtime behaviour changed.
**Branch:** `feat/rez-ops-next-generation`
**Canonical source:** `_bmad-output/planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/ARCHITECTURE-SPINE.md` — AD-16 through AD-20, plus in-place amendments to AD-1, AD-7, AD-12, AD-14. Where this page and the spine disagree, the spine wins.
**Input distilled:** `docs/product-direction.md`.

This page is the *delta*: what changed in the architecture, why each change exists, and what it means for the next stories. It is written for whoever builds Phase 1, human or coding agent.

---

## 1. What did not change

Everything the first fifteen ADs bind still holds, unmodified in substance:

- Sensors are dumb, read-only, one MCP server per domain (AD-1, AD-2).
- Ledger-core is the sole owner of every derived value — confidence, tier, policy decision — and the sole writer to `ledger_data/` (AD-3, AD-5, AD-9, AD-11, AD-12).
- Nothing acts on a `policy_decision`; the Executor stays design-only (AD-12 Never clause, AD-13/14/15).
- Local-first, no persistent server process, credentials never in git (AD-7).
- Fail open to an explicit `unknown`, never silently (AD-8).

The earlier amendment's phrase still applies: a new door was added, not a wall removed.

## 2. What changed, in one picture

```text
Before                                 After
──────                                 ─────
Human's MCP client (Claude Code)       HOSTED   — same as before, untouched
   └─ loads .mcp.json                  DRIVEN   — agents/ launches a provider CLI
   └─ calls Sensors + Ledger                      headless, against the SAME .mcp.json
                                                  └─ provider calls Sensors + Ledger
                                                  └─ agents/ writes agent_data/ only
                                                  └─ ledger-core stamps provenance
                                                     from its own environment
```

Both modes use the same MCP tools. Neither carries domain logic. The Ledger does not care which mode is talking to it; from Phase 3 it stamps every record it writes with who wrote it.

## 3. The five new decisions

### AD-16 — Two execution modes, one MCP surface

**Hosted** is today. **Driven** is Rez Ops launching a provider's official CLI (Claude Code, Codex, Antigravity CLI, or the in-process fake) from a new top-level `agents/` package. `agents/` is a peer of `ops/`, never inside `ledger_core/`, and the Ledger never imports or spawns it.

`.mcp.json` is the single source of truth for the server set. Each adapter *derives* its provider's native MCP config from it at launch into a git-ignored `.rezops/run/{session_id}/`. Nobody hand-maintains a second server list. Providers launch with the project root as working directory and their own home directory untouched.

**Why:** the plan requires provider independence, but the three real CLIs read three different config surfaces. Deriving from one file is the only way two adapters cannot drift.

### AD-17 — Capabilities are probed, never declared

An adapter reports `installed`, `authenticated`, `healthy`, and its capability set by checking the real runtime at call time. No config file claims what a provider can do; a future `rezops.providers.yaml` holds *preferences* only. `rezops doctor` renders the same probe. Health is judged from the runtime's structured result, never its exit code alone.

**Why:** this year alone, Gemini CLI stopped serving individual subscriptions (2026-06-18), this machine's Codex install turned out to be an npm wrapper with no binary behind it, and Claude Code's headless MCP loading regressed once (2.1.77). A declaration would have been wrong three times.

### AD-18 — Agent state lives in `agent_data/`

Sessions, tasks, and the structured event stream are appended by `agents/` — and only `agents/` — to `agent_data/`, same append-only discipline and line grammar as `ledger_data/`, different owner. Ledger-core never reads it. Transcripts are off by default, git-ignored when opted in, consumed by nothing. No secret ever lands there.

Rez Ops mints `session_id` (UUID) before launch; the provider's own id is recorded separately as `provider_session_id`.

**Why:** the plan says a provider transcript is not the Ledger. Keeping the stores apart is what makes that true structurally rather than by good intentions.

### AD-19 — Provenance is environment-attested

Ledger-core stamps `provenance {session_id, provider, model, mode, auth_mode, operator}` on **every record its four write tools create** — `RawFact` ingest, `Draft`, `EvidenceBundle`, `ActionProposal`. The values come from ledger-core's own process environment, set by the launcher as `REZOPS_AGENT_*`, never from a tool argument. Hosted mode has no launcher, so records stamp `mode: hosted` and `operator` from `REZOPS_OPERATOR`. Partial variables refuse the write (`PROVENANCE_INVALID`); they never fall open to hosted.

`provenance` is required on write, optional on read. Records written before Phase 3 read back as `provenance: null` and are never rejected.

**Why:** the reviewers found that a driven LLM could call `ledger_ingest_raw_fact` with an invented `source`, which is exactly the "Claude said X, Rez Ops knows X" path the plan forbids. Stamping every write makes a relayed fact attributable. A caller-supplied stamp would be the LLM describing itself, the same hole AD-14 closed for `approver`.

### AD-20 — The adapter contract

Method signatures are deliberately *not* fixed. The spike inspects the real runtimes first. Seven invariants are fixed now:

1. Launch the official runtime. Never touch its credentials, never scrape a session, never bypass vendor limits.
2. Record `auth_mode: SUBSCRIPTION | API` on every session. `API` needs explicit per-provider opt-in; an ambient API key never flips a session silently.
3. Vendor names, flags, and config formats live only inside that adapter's package.
4. One system-wide failure enum in `shared/`. Never "unknown error". A launch whose MCP servers do not all attach fails with `MCP_ATTACH_FAILED`.
5. Provider selection is deterministic, never an LLM's choice. Requested and executed providers are both recorded.
6. The `fake` adapter is a shipped, in-process adapter that passes the same contract suite and can inject every failure code.
7. Tool scope is the `(server, tool)` set from `.mcp.json`, enforced by strict MCP-config mode, denial of built-in tools, and a loaded-server-set check before the first task.

## 4. Amendments to existing ADs

| AD | Change |
| --- | --- |
| AD-1 | "Voice" now means Voice / Agent Runtime in either mode. New clause: the runtime is never a system of record. |
| AD-7 | The literal `claude -p …` invocation is demoted to the claude adapter. A driven failure is a `session.failed` event plus non-zero exit, not an `_ops.log.md` line. A provider process lives only for one `rezops agent run`. `ops/run_scheduled_briefing.py` is a named, grandfathered exception to AD-20 §3 until Phase 1 makes it a shim. |
| AD-12 | From Phase 3, `decided` records the SHA-256 of the policy and tiers files it evaluated against. |
| AD-14 | `approver` resolves from the now-named `REZOPS_OPERATOR`, shared with AD-19. |

## 5. Phase ownership

| Phase | Builds | Must not touch |
| --- | --- | --- |
| **1 — Provider runtime spike** | `agents/core`, `fake` + contract suite (first), `claude` (second), `codex` and `google` (after), `agent_data/`, `rezops doctor`, `rezops agent run` | `ledger_core/`, `connectors/`, `shared/` |
| **2 — Session layer** | durable start/resume/cancel/timeout over `agent_data/` | `ledger_core/` |
| **3 — Agent ↔ MCP** | AD-19 stamp on all four write tools, AD-12 policy hash, `shared/failures` enum | nothing new in `agents/providers` beyond what the suite demands |

Phase 1 sets the `REZOPS_AGENT_*` variables. Phase 3 reads them. Between those phases the variables are set and ignored, which is safe by construction.

## 6. What a Phase 1 story must check before it is done

- 820 existing tests still pass. Nothing in `ledger_core/`, `connectors/`, `shared/` changed.
- The adapter passes `tests/providers/` — the same suite the fake passes.
- `rezops doctor` reports the adapter's provider by probe, and reports this machine's broken Codex install as `PROVIDER_NOT_INSTALLED` (or the code the probe honestly yields), not as available.
- A driven launch with a deliberately wrong `.mcp.json` fails with `MCP_ATTACH_FAILED`; one with an extra server in the provider's global config fails with `TOOL_SCOPE_VIOLATION`.
- No file under `.rezops/run/` or `agent_data/transcripts/` is tracked by git.
- No `REZOPS_*` value appears in any generated file.

The adapter-level checklist, including the four negative launches, is `docs/provider-adapter-contract.md` §11.

## 7. Conflicts carried forward, on purpose

- The plan's mission shape carries its own `approvals` field. The spine has exactly one approval mechanism (AD-12 + AD-14). A future mission AD must cite `ActionProposal` ids, never own a parallel approval state.
- Today every `RawFact` reaches the Ledger through an LLM relay. AD-19 makes that attributable. An LLM-free Sensor → Ledger path would amend AD-1 and is its own later decision.
- `ledger_data/` has no tracked files today. AD-7's "pushed after each session" was never automated. `agent_data/` inherits the same gap; fixing both is a natural Phase 1 or 2 story.

## 8. Vendor facts this amendment rests on (verified 2026-09-12)

| Runtime | Verified |
| --- | --- |
| Claude Code 2.1.269 | `-p --mcp-config .mcp.json --strict-mcp-config --output-format stream-json` loaded all 7 Rez Ops servers, 18 tools, on this machine. |
| OpenAI Codex CLI | `codex exec`, `--json`, `--output-schema`, `codex exec resume`; ChatGPT login via `codex login`; MCP in `config.toml`. Local install is a wrapper with a missing binary. |
| Google Antigravity CLI `agy` 1.2.0 | Gemini CLI stopped serving Google AI Pro/Ultra on 2026-06-18. `-p`, `--output-format json|stream-json`, `--continue`; MCP in `.agents/mcp_config.json`; headless tool denial exits 0 with `status: SUCCESS`. |
| `mcp` Python SDK | 1.30.0 latest 1.x (security only), 2.2.0 default install. Adapters never import it; pin `<2` holds through Phase 1. |

The per-runtime matrix of flags, config paths, and session commands is `docs/provider-adapter-contract.md` §12. Re-probe at every run; that is what AD-17 is for.
