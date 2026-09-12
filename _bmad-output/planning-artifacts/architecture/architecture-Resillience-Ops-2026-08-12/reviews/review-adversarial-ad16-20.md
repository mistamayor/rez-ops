---
name: 'Rez Ops — Adversarial Review: AD-16..AD-20'
type: architecture-review
lens: adversarial-two-units
target: architecture-Resillience-Ops-2026-08-12/ARCHITECTURE-SPINE.md
scope: 'AD-16 (two modes), AD-17 (probed capabilities), AD-18 (agent_data/), AD-19 (environment-attested provenance), AD-20 (adapter contract §1–7); the amended AD-1 and AD-7; the "Agent runtime" Consistency Conventions row; the Structural Seed''s agents/ + agent_data/ + rezops CLI'
supersedes-scope-of: review-adversarial-ad13-15.md (AD-13–15 not re-litigated; AD-1–12 reopened only where AD-16–20 create a fresh contradiction with them)
code-read: ledger_core/server.py, ledger_core/evidence.py, ledger_core/action_proposals.py, ledger_core/log.py, ops/run_scheduled_briefing.py, ops/README.md, .mcp.json, tests/test_mcp_config.py, pyproject.toml, docs/product-direction.md (§18–28, §52, §63–66, §79), ~/.codex/config.toml (this machine, as evidence for Finding 2)
created: '2026-09-12'
---

# Adversarial Review — AD-16..AD-20 (agent-runtime amendment, 2026-09-12 pass)

**Method:** for each pair below, two engineers each read only the spine and build one Phase-1 unit — `agents/core` (session + events), `agents/providers/{fake,claude,codex,google}`, `rezops` CLI + `doctor`, ledger-core provenance stamping, or the `agent_data/` log + projection — obeying every AD it is bound by *to the letter*. The two units still build incompatibly, or the pair leaves a hole an attacker (the LLM, prompt-injected content, or a stale environment) can walk through. Each closes with the AD text that would have prevented it. Existing code was read so that "the adapter derives X" or "ledger-core inherits Y" is checked against what `ledger_core/server.py`, `.mcp.json` and `ops/run_scheduled_briefing.py` actually do today.

## Verdict

**Not yet buildable as a consistent Phase 1.** The amendment gets the big shape right — agents/ is a peer, never inside the Ledger; provenance is never a tool argument; the fake is a real adapter; tool scope is a contract clause, not a hope — but it fixes *what* must be true without pinning *where the truth is checked*, and in two places it contradicts itself or the code it sits on. Two findings are critical: (1) AD-7's scheduled-failure log at `ledger_data/_ops.log.md` now has to be written by the agent runtime, which AD-18 forbids in the same sentence that makes it the sole writer of `agent_data/`; and `ops/run_scheduled_briefing.py` remains a second, non-runtime launcher whose headless sessions ledger-core will stamp `mode: hosted`. (2) AD-20 §7's "exactly the Rez Ops MCP tools and nothing else" is escapable through every verified provider's user-scope MCP configuration — on the very machine this review ran on, `~/.codex/config.toml` already registers a `node_repl` MCP server, i.e. arbitrary code execution that a driven Codex session would inherit while the adapter obeys AD-16 to the letter. Four more are high: AD-19's inheritance assumption is provider-specific and fails open; AD-19 leaves `ledger_ingest_raw_fact`/`ledger_create_draft` unstamped on the same driven surface; `session_id`, derived-config location and ledger-core's cwd-relative `ledger_data/` collide; and AD-18 fixes event *names* but not payload shape, line grammar, the `pending` task's home, or cancellation. Twelve findings, none needing a paradigm change — all closable by naming a single owner, a single check, or a single format where the current text names none.

---

## Findings

### F1 — AD-7 tells the agent runtime to write `ledger_data/_ops.log.md`; AD-18 forbids it — and the old launcher stays alive (CRITICAL — AD-7, AD-18, AD-19, AD-16)

**Unit A — `rezops` CLI + `rezops agent run` (scheduled path):** the engineer reads AD-7 verbatim: "Scheduled work … is triggered by the OS scheduler … invoking the agent runtime in Driven mode … A failed scheduled run appends an error entry to `ledger_data/_ops.log.md` rather than failing silently." The Consistency Conventions repeat it: "Scheduled-run failures log to `ledger_data/_ops.log.md` (AD-7)." So `rezops agent run` catches the launch failure and appends to `ledger_data/_ops.log.md`, exactly as `ops/run_scheduled_briefing.py::_safe_append_ops_log_entry` does today.

**Unit B — `agent_data/` log + projection:** the engineer reads AD-18 verbatim: "**Ledger-core never reads or writes `agent_data/`**, and `agents/` never writes `ledger_data/`." A failed scheduled run is a `session.failed`/`task.failed` event in `agent_data/sessions/{session_id}.log.md` with an AD-20 §4 failure code, and nothing else. Any write into `ledger_data/` from `agents/` is a boundary violation, and this unit adds a test asserting `agents/` contains no reference to `ledger_data`.

**The clash:** both are AD-compliant and mutually exclusive; the spine's own text says both. It is a literal contradiction between AD-7's Rule, the Conventions row, and AD-18's Rule. Worse, the *existing* code sits on a third path: `ops/run_scheduled_briefing.py` still shells out to `claude -p` directly, sets no `REZOPS_AGENT_*` vars, emits no `agent_data/` events, applies no AD-20 §7 scoping (no `--allowedTools`, no `--strict-mcp-config`), and the spine keeps it ("The `ops/` scripts stay where they are until a concrete architectural reason moves them"). Under AD-19 ("In Hosted mode no launcher exists, so the vars are absent and ledger-core stamps `mode: hosted`") every evidence bundle that headless cron session creates is stamped **`mode: hosted`, operator = the cron user** — a fully unattended LLM run recorded as a human's session. AD-19's inverse ("absent vars ⇒ hosted") is only true if the agent runtime is the *only* headless launcher, and today it isn't.

**Fix:**
- AD-7 Rule: replace "appends an error entry to `ledger_data/_ops.log.md`" with "is recorded as a `session.failed` event (with an AD-20 §4 code) in `agent_data/` by the agent runtime; `ledger_data/_ops.log.md` is retired with `ops/run_scheduled_briefing.py`". Update the Conventions row and Structural Seed (`_ops.log.md` → historical/removed).
- AD-16 Rule, add: "**The agent runtime is the only component that launches a provider CLI headless.** `ops/run_scheduled_briefing.py` is replaced in Phase 1 by `rezops agent run --provider claude --task briefing` (or becomes a two-line wrapper over it); no other script may invoke `claude -p`, `codex exec`, or `agy -p`." This is the "concrete architectural reason" the seed says it is waiting for — it arrived with AD-19.
- AD-19 Rule, replace "absent vars mean hosted" with: "absent vars mean hosted **because the runtime is the only headless launcher (AD-16)**; a headless invocation outside the runtime is a spine violation, not a hosted session."

---

### F2 — AD-20 §7's tool scope is escapable via provider user-scope MCP config; and it is written in Claude Code's naming (CRITICAL — AD-20 §3/§7, AD-16, AD-17)

**Unit A — `agents/providers/codex`:** the engineer follows AD-16: derive Codex's native TOML from `.mcp.json` "into a per-run location", pass it, and per §7 rely on "read-only sandbox + MCP allow" (memlog wording). Codex *merges* configuration layers — `~/.codex/config.toml` (user), project `.codex/config.toml`, and `-c` overrides. The derived config adds the seven Rez Ops servers; it does not remove anything the user scope already declares. On this machine `~/.codex/config.toml` contains `[mcp_servers.node_repl]` pointing at a Node REPL binary — a driven Codex session gets a JavaScript execution environment as an MCP tool, obeying every word of AD-16 and §7 ("the provider's built-in shell, file-write, and web tools are denied" — a *third-party MCP server's* REPL is none of those).

**Unit B — `agents/providers/claude`:** the engineer follows AD-16's literal sentence — "Claude Code reads `.mcp.json` directly via `--mcp-config`" — and passes `--mcp-config .mcp.json`. Without `--strict-mcp-config`, Claude Code also loads user-scope servers from `~/.claude.json` (this operator's user scope registers `namecheap` with `dns_records_save`/`domain_register`, `claude-in-chrome` with a browser, `stitch`, Gmail send, etc. — visible in this very session's tool list). The Stack row happens to mention `--strict-mcp-config` as what was *verified*, but no AD *requires* it, so an adapter written from the ADs alone omits it and AD-19's Prevents clause — "a driven agent that read prompt-injected external content having any path to act outside the Ledger's gated tools" — is void: a poisoned SharePoint title can send email or buy a domain through the operator's user-scope servers.

**Unit C — `agents/providers/google`:** `.agents/mcp_config.json` is read from the cwd (no path flag); the user-scope equivalent, if present, merges too, and `~/.agents/` already exists on this machine.

**Second clash, same clause:** §7 and the Conventions row define scope as "`mcp__<server>__*`" — that is Claude Code's tool-naming convention, which §3 says must "appear *only* inside that provider's adapter package". Codex and Antigravity name MCP tools differently. A Codex adapter that literally allow-lists `mcp__ledger-core__*` allows nothing; a contract test written against the §7 string passes on Claude and cannot even be expressed on the other two.

**Fix (AD-20 §7, rewrite):** "A driven session is granted exactly the tools served by the servers registered in `.mcp.json` — identified provider-neutrally as `(server key, tool name)` — and **no other MCP server from any scope**, including the provider's user/global configuration: the adapter must launch in the provider's strict/isolated-config mode (Claude Code: `--strict-mcp-config`; Codex/Antigravity: the mechanism the Phase 1 spike finds, which must not be 'copy the user's home') and the provider's built-in shell, file-write, web, and sub-agent tools are denied through the provider's own permission mechanism. **Scope is verified, not assumed (AD-17):** before the first task is sent, the adapter reads the provider's actual loaded server/tool list (a real headless probe) and compares it to `.mcp.json`; any extra server or missing Rez Ops server is `TOOL_SCOPE_VIOLATION` — the task stays `pending`, the session records the diff. `tests/providers/` includes this check for every adapter, with a deliberately planted extra user-scope server." Strike `mcp__<server>__*` from the Conventions row.

---

### F3 — AD-19's "the CLI spawns ledger-core, so it inherits the vars" is a per-provider property, fails open to `hosted`, and is never verified end-to-end (HIGH — AD-19, AD-7, AD-8, AD-17)

**Unit A — `agents/providers/claude`:** sets `REZOPS_AGENT_*` in the child env and launches. Claude Code spawns `.mcp.json` stdio servers with its own environment, so `uv run python -m ledger_core.server` sees the vars. Works.

**Unit B — `agents/providers/codex`:** does the same. Codex launches stdio MCP servers with a *whitelisted* environment (a fixed default list — `HOME`, `PATH`, `USER`, `TMPDIR`, … — plus that server's explicit `env`/`env_vars` entries), not the full parent env (verify at spike; this is the documented shape of Codex's MCP transport config). So ledger-core under Codex sees no `REZOPS_AGENT_*` and — per AD-19's letter — stamps every bundle **`mode: hosted`**. Nor does it see `REZOPS_{DOMAIN}_TOKEN`, so every connector fails auth. The engineer's obvious remedy is to write the values into the derived TOML's `[mcp_servers.ledger-core.env]` block — which puts **connector credentials by value into a generated file**, the exact leak `tests/test_mcp_config.py::test_mcp_config_servers_have_no_credential_shaped_fields` exists to prevent in `.mcp.json` (AD-7).

**Unit C — ledger-core provenance stamping:** reads the four vars. The engineer applies AD-8 ("every runtime-facing operation fails open"): `REZOPS_AGENT_MODE=driven` with `REZOPS_AGENT_SESSION_ID` unset (a half-configured launcher, a typo, a Codex whitelist) → treat as hosted and carry on. The write succeeds with a permanently wrong stamp; nothing surfaces it. A different engineer treats partial env as an error. Both are AD-compliant.

**Also unverified:** nothing in the ADs makes the launcher check that the stamp ledger-core *will* apply equals the session it launched. The launcher sets env and hopes.

**Fix:**
- AD-19 Rule, add: "Provenance and credential env vars reach ledger-core and connectors **by name, never by value in any generated file** — an adapter forwards the `REZOPS_*` names through the provider's env-passthrough mechanism (or the spike proves the provider inherits the parent env). A generated provider config carrying a `REZOPS_*` *value* is a schema violation, tested per adapter exactly as `test_mcp_config.py` tests `.mcp.json`."
- AD-19 Rule, add: "ledger-core treats a **partial or malformed** `REZOPS_AGENT_*` set (any var present but not all four; `MODE` not exactly `driven`; `AUTH_MODE` not in the enum) as `PROVENANCE_INVALID` and **refuses the write** with a typed error — AD-8's fail-open applies to reads and to unavailable sources, never to mislabelling a record. Only *all four absent* means hosted."
- AD-17/AD-20 §4, add an end-to-end contract test: "a driven session (fake and every real adapter) that creates one `EvidenceBundle` must yield a bundle whose `provenance.session_id`/`provider`/`mode`/`auth_mode` equal the session record in `agent_data/`; the adapter emits `session.started` only after this round-trip succeeds, else `PROVENANCE_UNVERIFIED` and the task stays `pending`." Add `PROVENANCE_INVALID`/`PROVENANCE_UNVERIFIED` to the shared enum.

---

### F4 — AD-19 stamps only `EvidenceBundle`/`ActionProposal`; `ledger_ingest_raw_fact` and `ledger_create_draft` are on the same driven surface, unstamped (HIGH — AD-19, AD-18, AD-9)

**Unit A — ledger-core provenance stamping:** implements exactly AD-19's Binds: provenance on `create_evidence_bundle` and `create_action_proposal`. `ledger_ingest_raw_fact` and `ledger_create_draft` are untouched — AD-19 doesn't name them.

**Unit B — `agents/providers/*` under §7:** grants "exactly the Rez Ops MCP tools" — which includes `ledger_ingest_raw_fact(artifact_type, artifact_id, source, fields)`. In Hosted mode Voice already mediates Sensor → Ledger by calling ingest with connector output (AD-1: "the Runtime mediates all data flow between them"), so the tool *must* stay in scope. A driven agent that read a prompt-injected ticket description can call `ledger_ingest_raw_fact(artifact_type="runbooks", artifact_id="payments-dr", source="cmdb", fields={"last_verified": "2026-09-12"})`. `RawFact` rejects LedgerRecord-only keys, but `last_verified`-shaped observed fields are exactly what connectors emit, and `source` is a free string. The event line in `ledger_data/runbooks.log.md` is byte-identical to a real CMDB observation; the projection turns it into `confidence: agent-verified`. AD-18's Prevents — "'Claude said X' silently becoming 'Rez Ops knows X'" — is defeated through the front door, not through transcripts. Drafts likewise: an unattended, un-provenanced `Draft` addressed to the escalation owner, which AD-6 says a human "sends manually" — with no record of which provider wrote it.

**Fix (AD-19 Rule):** "ledger-core stamps `provenance` on **every write path** — `RawFact` events (a `provenance` key on the log line, alongside `source`; `log.py`'s writer and reader change together), `Draft`, `EvidenceBundle`, `ActionProposal`. `provenance` is reserved: a `RawFact.fields` key named `provenance` is rejected like `confidence` is. Projection may later weight `mode: driven` ingests differently (Deferred); recording them is not deferred." Note the format consequence for `log.py::_LINE_RE` and `_format_event`, and that Finding F10's legacy-record rule applies.

---

### F5 — Three things named "session": `session_id` format vs. provider session ids; per-run config location vs. ledger-core's cwd-relative `ledger_data/`; Codex's `CODEX_HOME` binds config to auth (HIGH — AD-18, AD-16, AD-20 §1, AD-3)

**Unit A — `agents/core` session + events:** mints `session_id` as a "stable slug" per the Conventions row, mirroring `evidence.py::_generate_evidence_id` (`20260912T140000Z-a1b2c3`), names the log `agent_data/sessions/{session_id}.log.md`, and exports it as `REZOPS_AGENT_SESSION_ID`.

**Unit B — `agents/providers/claude`:** needs `--session-id <uuid>` (Claude Code requires a UUID) to make the provider session resumable and to correlate transcripts. It can't pass Unit A's slug, so it mints its own UUID, and the `agent_data/` session and the provider session have different ids; `resume_session` then needs a mapping nobody owns. `agents/providers/codex` has a thread id; `google` has `--conversation <id>`. Three adapters, three notions of "the session id", and AD-18 says one `session_id` is "on every event".

**Unit C — derived config "into a per-run location":** Codex reads project config from `<cwd>/.codex/config.toml`; Antigravity reads `<cwd>/.agents/mcp_config.json`. Neither is a *per-run* location unless the adapter runs the CLI from a per-run temp cwd. But `.mcp.json` launches `uv run python -m ledger_core.server` with no `cwd`, and **`ledger_core` resolves `ledger_data/` relative to the process cwd** (`DEFAULT_LEDGER_DATA_DIR = Path("ledger_data")` in `log.py`, `evidence.py`, `action_proposals.py`; `rezops.policy.yaml`/`rezops.tiers.yaml` likewise). Launch the provider from `/tmp/rezops-run-123/` and ledger-core silently writes a brand-new `ledger_data/` there — every bundle the session creates is lost, and `uv run` may not even find the project. Writing into the repo's `.codex/`/`.agents/` instead is not per-run: two concurrent runs (cron overlapping a manual `rezops agent run`) clobber each other's file, and it must be git-ignored — "never committed as a second copy" is currently a hope, not a rule. Codex's alternative, `CODEX_HOME=<per-run dir>`, moves config *and* `auth.json` — the run has no credentials, and copying `auth.json` in is the "extracts/stores credentials" §1 forbids.

**Fix:**
- AD-18 Rule: "`session_id` is minted by `agents/core` **before any probe or launch**, as a UUIDv4 (the one format every verified provider accepts as an external session id); the provider's own session/thread/conversation reference is recorded as `provider_session_ref` on the session record and is never the primary key. Adapters receive `session_id`; they never mint one."
- AD-16 Rule: "Derived provider config is delivered without changing the provider's cwd from the repo root and without touching the provider's user home (CLI-level overrides such as Codex `-c`, or a per-run file referenced by path where the provider supports one). Any derived file written inside the repo tree is under a git-ignored, session-id-named path (`.rezops/runs/{session_id}/`) — tested."
- Ledger-core (a Phase 1 story, cited from AD-16): "ledger-core and connectors resolve `ledger_data/`, `rezops.*.yaml` from the repo root (an explicit `REZOPS_ROOT` set by the launcher, else the package's parent), never from cwd." The `.mcp.json` entries may also gain a `cwd` — Claude Code supports it; check the others at spike.

---

### F6 — AD-18 fixes event *names*; `payload` is untyped, the line grammar is unspecified, the `pending` task has no home, and cancellation has no event (HIGH — AD-18, AD-17, AD-20 §4)

**Unit A — `agents/providers/claude`:** parses `stream-json`, and on a `tool_use` named `mcp__ledger-core__ledger_create_evidence` emits `tool.called {tool: "mcp__ledger-core__ledger_create_evidence", input: {...}}`, then on the result emits `claim.submitted {evidence_id: "...", tool: ...}` by parsing ledger-core's returned dict.

**Unit B — `agents/providers/codex`:** parses `--json` JSONL `item.*` events and emits `tool.called {server: "ledger-core", name: "ledger_create_evidence"}` and `claim.submitted {kind: "evidence"}` with no id (its stream doesn't surface the result body the same way). **Unit C — `agents/sessions/` projection:** reads `claim.submitted.payload.evidence_id` to answer "which bundles did this session author?" — works for Claude, blank for Codex. All three obey AD-18: the seven required fields are present and `payload` is a dict.

**Same AD, second gap:** AD-17 says "a task bound for [a failed provider] stays `pending`, visibly." Where? AD-18 keys everything by `session_id` in `agent_data/sessions/{session_id}.log.md`, and says `task_id` arrives "once missions exist". A provider that is `PROVIDER_NOT_INSTALLED` never started a session; Unit A writes `agent_data/tasks/{task_id}.log.md` (a new directory not in the seed); Unit B emits `task.pending` into a session log for a session that never started (possible only if `session_id` is minted before the probe — F5); Unit C treats a `pending` task as "no record at all" (which is exactly the silent failure AD-17 forbids).

**Third gap:** `cancel_session` is an AD-20 candidate and the plan's mission statuses include `cancelled`, but AD-18's event list has no `session.cancelled`/`task.cancelled`. Unit A emits `session.failed` with a made-up code `CANCELLED` (not in the §4 enum); Unit B adds a new event type. Both compliant.

**Fourth gap:** "memlog-style" already means three different line grammars in this repo (`log.py`'s `- (rawfact) ts source= artifact= fields=`, `action_proposals.py`'s `- (proposed) ts proposal_id= fields=`, `_ops.log.md`'s `- (reason) ts detail=`), each with its own regex. AD-18 does not say which — or a fourth.

**Fix (AD-18 Rule, add):**
- "`agents/core/events.py` owns **both** the writer and the parser of `agent_data/sessions/*.log.md` (the `log.py` pattern); adapters emit through `core`'s typed emitter and never write a line themselves. Each `event_type` has a **typed payload** defined in `core` (e.g. `tool.called{server, tool, call_id}`, `tool.completed{call_id, ok, error_code?}`, `claim.submitted{kind: evidence|proposal|draft|rawfact, ledger_id}`) — the adapter's only job is to map its provider's stream onto those types; `tests/providers/` asserts a fixed sequence of typed events for the fake and every real adapter."
- "Line grammar: `- ({event_type}) {timestamp} session={session_id} provider={provider} mode={mode} auth={auth_mode} payload={json}` — one grammar, stated here."
- "`task_id` and `task.pending` exist from Phase 1 (a run has exactly one task until missions arrive); because `session_id` is minted before the probe (F5), a task whose provider fails its probe still has a session log carrying `task.pending{code}`."
- Add `session.cancelled`/`task.cancelled` to the event list and `CANCELLED` to the §4 enum, with the rule "cancel = SIGTERM the provider process, wait for its MCP children to exit, then `session.cancelled`; a cancelled session is resumable only via the provider's own resume mechanism (F9)."

---

### F7 — The fake adapter: in-process simulator or real MCP client? And it writes the real `ledger_data/` (MEDIUM — AD-20 §6, AD-19, AD-3)

**Unit A — `agents/providers/fake` (simulator):** an in-process generator that emits the AD-18 event sequence and the plan's §52 failure modes (`timeout`, `quota exhaustion`, `malformed result`, …) on demand. Never spawns anything, never speaks MCP. Passes the `tests/providers/` suite Unit A also wrote — which therefore can't test §7 tool scope, AD-19 stamping, or config derivation for *any* adapter, because the "executable definition of the contract" has no MCP path to define them on. AD-19's "anything [the fake] authors carries `provider: fake` by construction" is vacuously true: it authors nothing that reaches the Ledger.

**Unit B — `agents/providers/fake` (scripted MCP client):** spawns the seven servers from a derived config and makes real tool calls on a script (call `ledger_get_briefing`, then `ledger_create_evidence`), so the suite *can* test derivation, scope and provenance. But `ledger_core/server.py` takes no `ledger_dir` from the environment — only the module functions do — so the fake's bundles land in the repo's real, git-committed `ledger_data/evidence/` with `provider: fake`, every `uv run pytest`. "Loud, not banned" becomes "committed forever".

**Fix:** AD-20 §6, add: "the fake is a real MCP client: it launches the same server set from the same derived config path as a real adapter and makes real tool calls from a script — the contract suite exercises AD-16 derivation, §7 scope and AD-19 stamping *through* it. Ledger-core honours a launcher-set `REZOPS_LEDGER_DIR` (same never-LLM-suppliable discipline as AD-19), and `rezops agent run --provider fake` defaults it to a scratch directory unless `--ledger real` is passed explicitly; the contract suite always uses a temp dir." Add a test that the committed `ledger_data/` contains no `provider: fake` record.

---

### F8 — `auth_mode`: probed (AD-17), recorded (AD-20 §2), or opted-in (AD-20 §2 again)? And an ambient API key silently flips it (MEDIUM — AD-17, AD-20 §1/§2, AD-19)

**Unit A — `agents/providers/claude`:** AD-17 says `auth_mode` is a probed capability. Claude Code exposes no headless "are you on a subscription or an API key" query; the only observable is whether `ANTHROPIC_API_KEY` is present in the environment the CLI will see. The adapter reports `auth_mode = API if ANTHROPIC_API_KEY in env else SUBSCRIPTION` — a *declaration from environment*, not a probe, and if cron's environment happens to carry an `ANTHROPIC_API_KEY` (this repo's README already tells operators to put credentials in the job environment), the "primary development mode" silently becomes API billing. §2 says API is "an explicit per-provider opt-in" — nothing opted in.

**Unit B — `agents/providers/codex`:** `codex login status` genuinely distinguishes ChatGPT login from API key; the adapter probes it. Two adapters, two methods — exactly what AD-17's Prevents names — and neither reads §2's "opt-in" as a launch-time control.

**Third unit — `agents/core` event emission:** AD-18 puts `auth_mode` on *every* event, including `task.pending{PROVIDER_NOT_INSTALLED}` where no auth mode can exist. The enum is `SUBSCRIPTION | API`. One engineer writes `null`, another `"UNKNOWN"`, a third omits the field.

**Fix (AD-20 §2, rewrite):** "`auth_mode` is a **launch-time decision** owned by `agents/core`: `SUBSCRIPTION` unless the operator has opted that provider into `API` (a per-provider flag, Phase 1: CLI `--auth-mode api`; later `rezops.providers.yaml`). The adapter launches with the vendor's API-key env var(s) **removed** from the child environment unless `API` was opted in (removal is not extraction — §1 is intact), then probes (AD-17); if the probe's observed mode disagrees with the decided one, `AUTH_MODE_MISMATCH` and the task stays `pending`. `REZOPS_AGENT_AUTH_MODE` carries the decided value. The event-level enum is `SUBSCRIPTION | API | UNKNOWN`; `UNKNOWN` is legal on events before a successful probe and never on an AD-19 stamp (a driven launch with `UNKNOWN` is refused)."

---

### F9 — AD-7's "never a resident daemon" vs. an `AgentProvider` whose session is a live process (MEDIUM — AD-7, AD-20, AD-18)

**Unit A — `agents/providers/claude` (process-per-task):** `start_session` records a session; `send_task` spawns `claude -p --session-id … --output-format stream-json`, streams, reaps at exit; a second task on the same session spawns `claude -p --resume …`. Between tasks no process exists. Obeys AD-7.

**Unit B — `agents/providers/claude` (live session):** reads the candidate signatures — `start_session` / `send_task` / `stream_events` / `get_result` — as a *connection* model and implements it the way the CLI most naturally supports: one long-lived `claude -p --input-format stream-json --output-format stream-json` process with stdin held open, fed a new user turn per `send_task`. `rezops agent run` now holds a provider process (and its seven MCP server children, including ledger-core) open for as long as the runtime wants — a per-run process that is, functionally, the resident daemon AD-7 forbids and its Deferred item warns "must not become one by accident". Both satisfy AD-7's "invoked per run and exits" — Unit B just defines a run as the whole day. Codex `exec` and `agy -p` push toward Unit A; only the reference adapter tempts Unit B, so two adapters diverge on what a session physically is.

**Fix (AD-7 Rule, add; AD-20 add clause 8):** "A provider process's lifetime is bounded by **one task**: `send_task` spawns it, `get_result` reaps it, and process exit is part of task completion. Session continuity across tasks uses only the provider's own resume mechanism (`--resume`, `codex exec resume`, `--continue`) — never a process kept alive between tasks, never an open stdin stream fed later turns. Every launch carries a mandatory wall-clock timeout (`AGENT_TIMEOUT`; `ops/run_scheduled_briefing.py`'s 600 s is the precedent). `rezops agent run` exits when its one task does."

---

### F10 — `operator` is stamped from an identity that only a design-only AD names (and doesn't actually name); pre-provenance records have no reading (MEDIUM — AD-19, AD-14, AD-11, AD-12)

**Unit A — ledger-core provenance stamping:** AD-19 says `operator` comes "from AD-14's operator identity". AD-14 is `[DESIGN ONLY — not yet built]` and its text says only "e.g. an env var set once by the human"; the var name (`REZOPS_OPERATOR_NAME`) exists in the memlog, not the spine. The engineer names it `REZOPS_OPERATOR`; absent → `operator: None`. **Unit B — a later AD-14 story:** names it `REZOPS_OPERATOR_NAME`; absent → refuse. Two vars, two absent-behaviours, one field.

**Same unit, second gap:** `evidence.py::_parse_bundle_file` raises `EvidenceFileFormatError` on any missing `_FRONTMATTER_KEYS` entry, and `action_proposals.py` checks `_PROPOSED_FIELD_KEYS` the same way. Adding `provenance` as a required key turns **every pre-amendment bundle and proposal into a format-error sentinel** (AD-8's "loud" path — but for healthy data). Making it optional means a missing block reads as… what? One engineer defaults it to `{mode: hosted}` (a fabricated attestation); another to `None`.

**Fix (AD-19 Rule, add):** "The operator identity var is named here, now, for both modes: `REZOPS_OPERATOR` (AD-14 inherits the name). Absent → `operator: unknown` — recorded, never a guess, never a refusal (a scheduled driven run may legitimately have no interactive operator). Records written before provenance existed are read as `provenance: {mode: legacy}` — an explicit ninth value, never a format error and never assumed hosted; `evidence.py`/`action_proposals.py` parsers treat the key as optional with that default." Add `legacy` to the mode enum in the Conventions row.

---

### F11 — The §4 failure enum is an open set ("…"), and the existing ops script already ships the "unknown error" it bans (LOW — AD-20 §4, AD-17, AD-7)

**Unit A — `agents/providers/codex`:** maps a non-zero exit with unparseable stderr to a new member `AGENT_CRASHED`. **Unit B — `agents/providers/google`:** maps the same situation to `PROCESS_EXITED`. Both are "a code from one shared enum" as long as each adds its own member — the trailing "…" in §4 and the Conventions row licenses it. Meanwhile `ops/run_scheduled_briefing.py` reports `REASON_UNEXPECTED_ERROR = "unexpected_error"` — "unknown error" under another name — and per F1 it is still a launcher.

**Fix (AD-20 §4):** "The enum is **closed** and lives in `agents/core`; adapters may not extend it. Every provider exit path maps to a member, and `AGENT_UNAVAILABLE` is the catch-all *with the raw cause in the payload* — never a bare 'unknown'. Adding a member is a `core` change with a contract-suite update." Drop the "…" from both places in the spine.

---

### F12 — A `rezops doctor` "real headless round-trip" is a provider session with no rules (LOW — AD-17, AD-18, AD-20 §7)

**Unit A — `rezops doctor`:** implements AD-17's "a real headless round-trip when the caller needs certainty" as a throw-away `claude -p "reply OK"` with no session record — it is a probe, not a session. **Unit B — `agents/core`:** every provider launch is a session (AD-18: `session.started` on every launch), so the probe writes `agent_data/sessions/…` and — because it is launched like any session — gets the full derived MCP config and can call ledger tools. A doctor run that reaches the Ledger is a doctor run that can write it; a doctor run in a shell loop burns subscription quota (`AGENT_QUOTA_EXHAUSTED` is on the enum for a reason).

**Fix (AD-17 Rule, add):** "A probe round-trip is a session of kind `probe`, recorded in `agent_data/` like any other, launched with an **empty** server set (no MCP config derived) so it can never reach the Ledger, and rate-limited by `doctor` (one round-trip per provider per invocation)."

---

## Attacks that failed

- **Voice passing `provenance` as a tool argument.** `FastMCP` derives the schema from the function signature; an unknown argument is rejected by validation before the tool body runs, the same way a caller-supplied `confidence` is today. Holds — with the F4 caveat that `RawFact.fields` must also reserve the key.
- **Ledger orchestrating agents.** `ledger_core/` has no import, subprocess, or await path into `agents/`; AD-16's sentence is enforceable by a one-line import-boundary test. Holds.
- **Provenance feeding policy.** `_compute_policy_decision(impact, tier_sla_known, min_confidence)` has no provenance input, and AD-19 doesn't add one; a driven `provider: fake` proposal is decided exactly like a human's. Holds — recommend a regression test pinning that signature so a future "weight driven claims lower" story goes through an AD, not a kwarg.
- **A driven LLM launching a nested driven run** (`rezops agent run --provider codex` from inside a driven Claude session, to pick its own provider — AD-20 §5). §7 denies the shell tool, so no path exists in Driven mode once F2 holds. A *hosted* session can do it — but hosted is the operator's own session by AD-16/§7's last sentence, and the nested run's provenance is honest (`driven`, `codex`). Out of AD-19's stated threat model; noted, not a finding.
- **Hosted shell with `REZOPS_AGENT_*` exported** (leftover `.envrc`, a debugging session) forging `mode: driven` on a human's session. Possible, but only the operator can do it — not the LLM — which is the same trust AD-14 already places in the operator's env. F3's partial-set refusal plus a `rezops doctor` warning ("`REZOPS_AGENT_*` present in an interactive shell") makes it loud enough; not a separate finding.
- **Two hand-maintained server lists.** AD-16's single-source rule holds *provided* derivation is tested per adapter the way `test_mcp_config.py` tests `.mcp.json` (F2/F3 fixes add that). The rule itself is sound.
- **`agent_data/` acquiring a second writer.** Nothing in `ops/` or `ledger_core/` has a reason to touch it; F1 is the crossing in the *other* direction. Holds.
- **Concurrent driven runs corrupting each other's session logs.** Per-session files keyed by a launcher-minted id don't collide (once F5 fixes who mints it). Both runs' ledger-core children appending to the same `action_proposals.log.md` is the already-deferred no-file-locking item — inherited, not new.
- **Transcripts becoming domain truth.** `agent_data/transcripts/` is "consumed by nothing" and no AD-18 projection reads it; the adapters parse the live stream, not the retained transcript. Holds — F4 shows the real "Claude said X → Rez Ops knows X" path is `ledger_ingest_raw_fact`, not transcripts.
