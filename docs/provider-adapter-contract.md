# Provider Adapter Contract — an adapter author's checklist

**Status:** Phase 0 deliverable. Binds every package under `agents/providers/`.
**Canonical source:** AD-16, AD-17, AD-18, AD-19, AD-20 in `ARCHITECTURE-SPINE.md`. This page restates them as the questions a reviewer asks of an adapter pull request. The spine wins on any disagreement.
**Not in scope here:** the `AgentProvider` method signatures. Those are designed in the Phase 1 spike *after* the fake, claude, codex, and google runtimes have been inspected. Do not write them from this page.

---

## 0. What an adapter is

One Python package, `agents/providers/<name>/`, that launches, drives, observes, and stops **one** vendor's official local agent runtime in Driven mode, and reports honestly what that runtime can do right now.

An adapter is not an MCP server. It is an MCP *client launcher*. AD-2's one-server-per-domain rule governs Sensors and the Ledger, not adapters.

The four adapters Phase 1 ships, in build order:

| Order | Adapter | Runtime | Why this order |
| --- | --- | --- | --- |
| 1 | `fake` | none — in-process | Defines the interface and the contract suite. Everything else is measured against it. |
| 2 | `claude` | Claude Code CLI | The only runtime with a live-verified headless MCP path today. |
| 3 | `codex` | OpenAI Codex CLI | Different MCP config surface (TOML). Proves derivation. |
| 3 | `google` | Antigravity CLI `agy` | Different permission model (soft-deny, exit 0). Proves probe-by-result. |

## 1. Authentication and vendor terms — AD-20 §1, §2

- [ ] Launches the vendor's **official** CLI. No SDK-with-API-key path unless `API` mode is explicitly opted in for this provider.
- [ ] Never reads, copies, proxies, converts, stores, or logs the vendor's credentials or token files (`~/.codex/auth.json`, Claude's keychain entry, `~/.gemini`). Rez Ops knows only "authenticated: yes/no" from the probe.
- [ ] Never scrapes a private web session. Never retries around, spoofs, or otherwise games a rate or usage limit.
- [ ] Records `auth_mode` on every session as `SUBSCRIPTION` or `API`.
- [ ] Probes which mode the runtime *will* use. If the probe says `API` and this provider has no opt-in, refuses to launch with `AUTH_MODE_MISMATCH`. An API key sitting in the shell must never silently turn a subscription run into a billed one.

## 2. Isolation — AD-20 §3

- [ ] The vendor's binary name, flags, config format, and output schema appear **only** inside this package.
- [ ] `grep` for the vendor's name in `ledger_core/`, `connectors/`, `shared/`, `agents/core/` returns nothing.
- [ ] Exception, named and temporary: `ops/run_scheduled_briefing.py` hard-codes `claude -p`. It is grandfathered until Phase 1 turns it into a shim over `rezops agent run --provider claude`. Do not copy the pattern.

## 3. Probing — AD-17

- [ ] `installed`, `authenticated`, `healthy`, and the capability set (`mcp`, `headless`, `sessions`, `structured_output`, `auth_mode`) come from checking the real runtime at call time. Nothing is read from a config file.
- [ ] Health is judged from the runtime's **structured result**, never its exit code alone. Antigravity CLI exits 0 with `status: SUCCESS` even when a tool call was denied.
- [ ] The probe distinguishes "wrapper present, binary missing" from "installed". This machine's Codex install is exactly that case.
- [ ] A failed probe reports a specific code from the shared enum, and any task bound for this provider goes to `task.pending`, visibly.
- [ ] `rezops doctor` calls this same probe. There is no second implementation.

## 4. Launching — AD-16

- [ ] Working directory is the **project root**. Never a temp directory. Ledger-core and the connectors resolve `ledger_data/`, `.mcp.json`, and `rezops.*.yaml` relative to it.
- [ ] Never relocates the provider's home (`CODEX_HOME`, `~/.gemini`). That would relocate its auth too.
- [ ] Derives the provider's native MCP config from `.mcp.json` at launch. Writes it to `.rezops/run/{session_id}/`, which is git-ignored. Never hand-maintains a second server list. Never commits a copy.
- [ ] Launches in the provider's **strict / isolated MCP-config mode** so user- or global-scope MCP configs cannot merge extra servers in. Claude Code: `--strict-mcp-config`. Codex and Antigravity: the equivalent the spike confirms. If the provider has no such mode, the adapter fails the launch rather than proceeding.
- [ ] The provider process lives only for this one `rezops agent run`, under a wall-clock budget. Resume re-launches through the provider's native resume plus the Rez Ops `session_id`. No adapter keeps a process alive between invocations.

## 5. Tool scope — AD-20 §7

- [ ] Scope is the set of `(server, tool)` pairs exposed by exactly the servers in `.mcp.json`. It is defined in those terms, not in the provider's own tool-naming scheme.
- [ ] The provider's built-in shell, file-write, and web tools are denied through the provider's own permission mechanism.
- [ ] Never passes a skip-all-permissions flag (`--dangerously-skip-permissions` or equivalent).
- [ ] **Before the first task**, reads the provider's reported loaded-server set and compares it to `.mcp.json`. Any difference fails the session with `TOOL_SCOPE_VIOLATION`.
- [ ] If not every server attaches, fails the session with `MCP_ATTACH_FAILED`. Never runs degraded with fewer Sensors than a human would have.

## 6. Provenance — AD-19

- [ ] Before launch, `agents/core` has minted a UUID `session_id` and the adapter sets exactly four variables in the provider's environment: `REZOPS_AGENT_SESSION_ID`, `REZOPS_AGENT_PROVIDER`, `REZOPS_AGENT_MODE=driven`, `REZOPS_AGENT_AUTH_MODE`.
- [ ] Guarantees the ledger-core process the CLI spawns **inherits** them. Some runtimes whitelist the environment passed to MCP children. The spike confirms the mechanism per provider.
- [ ] Forwards environment **by name, never by value**. No `REZOPS_*` value, credential or provenance, is ever written into a generated config file to get it through.
- [ ] If forwarding by name is impossible for this provider, fails the launch with `PROVENANCE_UNAVAILABLE`. Never falls back to values-in-a-file or passing provenance as a tool argument.
- [ ] The contract suite's end-to-end check passes: a record written from a driven session carries exactly that session's stamp (Phase 3, once ledger-core stamps).

## 7. Events — AD-18

- [ ] Emits every event type `agents/core` defines: `session.started`, `task.pending`, `task.started`, `tool.called`, `tool.completed`, `agent.message`, `claim.submitted`, `task.completed`, `task.failed`, `session.cancelled`, `session.failed`, `session.completed`.
- [ ] Every event carries `timestamp`, `session_id`, `provider`, `model` (when the runtime reports it), `mode`, `auth_mode`, `event_type`, `payload`. Payload shapes are the versioned ones in `agents/core`, never ad hoc.
- [ ] Records the provider's native session/thread id as `provider_session_id` on `session.started`. Never conflates it with `session_id`.
- [ ] Writes only to `agent_data/`. Never to `ledger_data/`.
- [ ] Payloads carry tool names and argument digests. Never a credential value. Never a raw transcript unless the human opted in, and then only to git-ignored `agent_data/transcripts/`.

## 8. Failure — AD-20 §4

- [ ] Every failure is a code from the one enum in `shared/`. Never "unknown error". Never a bare exception message as the only signal.
- [ ] Agent codes available today: `PROVIDER_NOT_INSTALLED`, `AUTHENTICATION_FAILED`, `AUTH_MODE_MISMATCH`, `AGENT_UNAVAILABLE`, `AGENT_TIMEOUT`, `AGENT_QUOTA_EXHAUSTED`, `RATE_LIMITED`, `AGENT_OUTPUT_INVALID`, `MCP_ATTACH_FAILED`, `TOOL_SCOPE_VIOLATION`, `PROVENANCE_UNAVAILABLE`, `PROVENANCE_INVALID`.
- [ ] Needs a code that does not exist? Add it to `shared/` with a test. The enum is a closed set in code; where the spine writes an ellipsis it is abbreviating, not licensing new codes.
- [ ] A driven failure is a `session.failed` event plus a non-zero exit from `rezops agent run`. It never writes `ledger_data/_ops.log.md`.

## 9. The fake — AD-20 §6

- [ ] Runs in-process. Launches no binary. Simulates a full session end to end.
- [ ] Passes the same `tests/providers/` suite as every real adapter. If the fake needs a special case in the suite, the suite is wrong.
- [ ] Can be configured to inject every failure code in the enum.
- [ ] When a Phase 3 test needs it to reach Rez Ops MCP tools, it does so through a real MCP client with the `REZOPS_AGENT_*` environment set, against an isolated test project root. Never the repository's own `ledger_data/`.
- [ ] Anything it writes carries `provider: fake`; the stamp is how a fake session is told apart from a real one.

## 10. Selection — AD-20 §5

- [ ] The adapter never chooses itself. Selection happens in `agents/core` from config preferences plus probe results, deterministically. Phase 1 has no router; the caller names the provider.
- [ ] When the executed provider differs from the requested one (a later routing phase), both are recorded on the session.

## 11. Definition of done for an adapter PR

- All 820 existing tests pass. Nothing changed under `ledger_core/`, `connectors/`, `shared/` (a Phase 1 constraint).
- `tests/providers/` passes for this adapter with no adapter-specific skips.
- `rezops doctor` shows this provider by probe, honestly, on a machine where it is installed, one where it is not, and one where it is installed but unauthenticated.
- The four negative launches fail with the right code: wrong `.mcp.json` → `MCP_ATTACH_FAILED`; extra global server → `TOOL_SCOPE_VIOLATION`; ambient API key without opt-in → `AUTH_MODE_MISMATCH`; environment forwarding unavailable → `PROVENANCE_UNAVAILABLE`.
- `git status` shows nothing new under `.rezops/run/` or `agent_data/transcripts/`.
- `grep -r <vendor> ledger_core connectors shared agents/core` is empty.

## 12. Runtime facts you will build against (verified 2026-09-12; re-probe anyway)

| | Claude Code 2.1.269 | Codex CLI | Antigravity CLI `agy` 1.2.0 |
| --- | --- | --- | --- |
| Headless | `claude -p` | `codex exec` | `agy -p` |
| Structured output | `--output-format json\|stream-json` | `--json` (JSONL), `--output-schema` | `--output-format json\|stream-json` |
| MCP config | `--mcp-config .mcp.json` | `config.toml` (`[mcp_servers.*]`) | `.agents/mcp_config.json` (`mcpServers`, stdio shape matches) |
| Strict MCP | `--strict-mcp-config` | spike confirms | spike confirms |
| Sessions | `--session-id <uuid>`, `--resume` | `codex exec resume <id>` | `--conversation <id>`, `--continue` |
| Subscription auth | Claude login | `codex login` (device auth), `~/.codex/auth.json` | one interactive `agy` login, cached |
| Headless denial behaviour | permission mode / allowed tools | read-only sandbox default | soft-deny, **exits 0, `status: SUCCESS`** |
| Known gotcha | `--print` MCP loading regressed in 2.1.77 | npm wrapper can exist with binary missing | Gemini CLI is *not* the subscription route since 2026-06-18 |
