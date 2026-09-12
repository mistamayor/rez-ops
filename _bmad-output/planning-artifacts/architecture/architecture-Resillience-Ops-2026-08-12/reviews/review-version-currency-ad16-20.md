# Version-currency review — Stack table, AD-16, AD-17, AD-20, MCP-SDK/elicitation Deferred items

Reviewed: `ARCHITECTURE-SPINE.md` (Stack table lines 190–196; AD-16, AD-17, AD-20; Deferred items "Verifying MCP's elicitation primitive…" and "MCP SDK v2 migration")
Review date: 2026-09-12. Reviewer: version-currency reviewer (team). No project files modified.

Method: every named technology was checked on the web (vendor docs, GitHub, PyPI/npm registries) and, where the tool is present, locally (`claude --version/--help`, `npm ls -g @openai/codex`, `codex --version`, `which agy`, `uv run python -c "…m.version('mcp')"`, `uv.lock`, `.mcp.json`).

## Verdict

**CONDITIONAL PASS.** Every hard technology claim the spine commits to was confirmed against a live vendor or registry source dated today. The conditions are small and all in the Stack table's descriptive wording, not in any AD invariant: (1) Antigravity CLI is labelled "preview-grade" but Google's docs now show it at v1.2.0 with the platform marked Generally Available — the label should be softened or dated; (2) the `.mcp.json`→`.agents/mcp_config.json` "same `mcpServers` shape" claim is true for stdio servers only (remote servers use `serverUrl`/`headers`, not `url`/`type`) and the Phase 1 derivation note should say so; (3) the elicitation Deferred item says "pinned `mcp` 1.29.x" while the pin range `>=1.29,<2` admits 1.30.0 (the current 1.x, released 2026-09-07) — the lock file is at 1.29.0 and should be bumped since 1.x now receives security fixes only. Nothing in AD-16/17/20 needs to change.

## Per-technology table

| # | Claim in spine | Confirmed? | Source | Note |
|---|---|---|---|---|
| 1 | Python 3.13+; 3.12 is security-only | ✅ | https://devguide.python.org/versions/ | 3.12 = "security" (EOL 2028-10); 3.13 and 3.14 = "bugfix"; 3.15 prerelease (Oct 2026). Local: `uv run python` = 3.13.11. `requires-python = ">=3.13"` holds. |
| 2 | `mcp` 1.30.0 is the latest 1.x | ✅ | https://pypi.org/pypi/mcp/json | 1.30.0 uploaded 2026-09-07. 1.29.0 (2026-07-28), 1.29.1 (2026-08-24) also exist. |
| 3 | `mcp` 2.2.0 (2026-09-07) is the default install | ✅ | https://pypi.org/pypi/mcp/json ; https://github.com/modelcontextprotocol/python-sdk/releases | PyPI `info.version` = 2.2.0. GitHub releases: v2.0.0 Jul 28, v2.1.0 Aug 24, v2.2.0 Sep 7 (released in lock-step with 1.29.0 / 1.29.1 / 1.30.0). |
| 4 | 1.x is security-fixes only | ✅ | https://github.com/modelcontextprotocol/python-sdk/releases (v2.0.0 notes); README | Release notes: "v1.x is in maintenance mode and will only receive security fixes from now on." README: "continues to receive critical bug fixes and security patches"; recommends keeping `<2` until migrated. |
| 5 | Pin `mcp>=1.29,<2` | ✅ (see F3) | `pyproject.toml`, `uv.lock` | Pin is the SDK's own recommended shape. **But** `uv.lock` resolves to 1.29.0 while 1.29.1 and 1.30.0 (security-only line) have shipped since. Local `m.version('mcp')` = 1.29.0. |
| 6 | 1.x elicitation is `ctx.elicit`; 2.x is different | ✅ | https://py.sdk.modelcontextprotocol.io/migration/ ; https://py.sdk.modelcontextprotocol.io/handlers/multi-round-trip/ | v1: `ctx.elicit()` in-handler call. v2: resolver dependency injection (`Elicit(...)` parameter / `InputRequiredResult`), client must declare `elicitation` capability or the call fails with `-32021`; `ElicitationResult` became a `TypeAliasType` (isinstance breaks). Spine's "1.x/2.x elicitation API difference … would first bite" is accurate. |
| 7 | Claude Code 2.1.269 is real and current | ✅ | Local `claude --version` = `2.1.269 (Claude Code)`; https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md | 2.1.269 is the top entry of the public CHANGELOG as of today. |
| 8 | `-p`, `--mcp-config`, `--strict-mcp-config`, `--output-format stream-json`, `--session-id`, `--resume` exist | ✅ | Local `claude --help` | All six present verbatim. `--bare` also present and its help text confirms it skips `--mcp-config`/CLAUDE.md autodiscovery, matching AD-7's "never `--bare`" note. `--dangerously-skip-permissions` present (AD-20 §7 forbids it). |
| 9 | "loads all 7 Rez Ops servers (18 tools)" | ✅ (partial) | Local `.mcp.json` | 7 servers (`ledger-core, git-repo, ticketing, calendar-google, cmdb, google-drive, sharepoint`); the tool list exposed to this session shows 12 ledger-core + 6 connector tools = 18. Live headless round-trip itself was not re-run by this reviewer. |
| 10 | Issue anthropics/claude-code#38987: `--print` MCP loading regressed in 2.1.77 (2026-03) | ✅ | https://github.com/anthropics/claude-code/issues/38987 | Title "MCP servers not loaded in --print mode (stdio servers)", opened 2026-03-25 against 2.1.77, labels `area:cli`, `area:mcp`, `bug`, `has repro`. **Status: Closed.** The fix version / closing reason was not visible in the fetched page (see F5). |
| 11 | `codex exec` headless; `--json` JSONL; `--output-schema`; `codex exec resume` | ✅ | https://learn.chatgpt.com/docs/non-interactive-mode (canonical redirect of developers.openai.com/codex/noninteractive) | `--json` = JSON Lines event stream (`thread.started`, `turn.completed`, `item.completed`…); `--output-schema <path>`; `-o/--output-last-message`; `codex exec resume --last "<task>"` and `codex exec resume <SESSION_ID>`. |
| 12 | Codex read-only sandbox by default in exec | ✅ | same | "By default, `codex exec` runs in read-only mode"; `--sandbox workspace-write` / `danger-full-access` opt-ins. |
| 13 | `codex login` ChatGPT-subscription / device auth; tokens in `~/.codex/auth.json` | ✅ | https://learn.chatgpt.com/docs/auth | `codex login` (browser, ChatGPT plan); `codex login --device-auth` (**beta**) for headless; `codex login --with-api-key` for API mode; credentials cached at `~/.codex/auth.json` (or OS keyring via `cli_auth_credentials_store`). Docs explicitly say treat `auth.json` as sensitive — supports AD-20 §1 "never reads". |
| 14 | MCP via `config.toml`, `required = true` | ✅ | https://learn.chatgpt.com/docs/config-file/config-reference ; non-interactive docs | `[mcp_servers.<id>]` with `command/args/env/url/enabled/required/startup_timeout_sec/tool_timeout_sec/enabled_tools`. `required = true` → "fail startup/resume if this enabled MCP server cannot initialize"; in `codex exec` it exits with an error rather than running without the server. |
| 15 | Current `@openai/codex` npm version | ✅ | https://registry.npmjs.org/@openai/codex/latest | **0.154.0** (dist-tag `latest`). Spine correctly does not name a version ("pin … when the adapter is built"). |
| 16 | "a Codex npm wrapper can be installed with its binary missing" (AD-17) | ✅ **reproduced locally** | Local `npm ls -g` = `@openai/codex@0.72.0`; `codex --version` → `spawn …/vendor/aarch64-apple-darwin/codex/codex ENOENT` | The exact failure mode AD-17 cites exists on this machine today: wrapper 0.72.0 present, native binary absent. Strong evidence for "probe, never declare". |
| 17 | Gemini CLI stopped serving Google AI Pro/Ultra on 2026-06-18 | ✅ | https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/ ; https://docs.cloud.google.com/gemini/docs/codeassist/release-notes | "On June 18, 2026, Gemini CLI and Gemini Code Assist IDE extensions will stop serving requests for Google AI Pro and Ultra" and free individual tiers. Announced 2026-05-19 (I/O). Gemini Code Assist Standard/Enterprise keep Gemini CLI. Local `gemini` 0.36.0 is still installed but is not a subscription route. |
| 18 | Binary is `agy` | ✅ | https://antigravity.google/docs/cli/getting-started | Installer registers `~/.local/bin/agy` (macOS/Linux). Not installed locally (`which agy` → not found), so no local probe. |
| 19 | `-p`, `--output-format text\|json\|stream-json`, `--continue`, `--conversation <id>` | ✅ | https://antigravity.google/docs/cli/headless/ | `-p/--print/--prompt`; `--output-format text (default) \| json \| stream-json`; `-c/--continue`; `--conversation <id>`; `--print-timeout` (5m default). `json` and `stream-json` (init event) both emit `conversation_id`, so the `sessions` capability is achievable (issue google-antigravity/antigravity-cli#7, 2026-05-19, asked for exactly this — it now appears in the docs). |
| 20 | Headless exits non-zero when unauthenticated | ✅ | same | "exit with an `authentication required` error instead of hanging"; non-zero exit = failure with reason on stderr. |
| 21 | MCP via `.agents/mcp_config.json` / `~/.gemini/config/mcp_config.json`, `mcpServers` shape | ✅ (with caveat) | https://antigravity.google/docs/cli/mcp/ | Both paths confirmed; top-level key is `mcpServers`. **Caveat:** remote servers use `serverUrl` + `headers`, whereas Claude Code's `.mcp.json` uses `url`/`type` — stdio (`command/args/env`) is identical. All 7 Rez Ops servers are stdio today, so the claim holds for the current server set. |
| 22 | Headless soft-deny unless `permissions.allow`; never `--dangerously-skip-permissions` | ✅ | https://antigravity.google/docs/cli/headless/ ; https://antigravity.google/docs/cli/permissions/ | Soft-denial confirmed: run continues, exits `0`, stderr notice. `permissions.allow/deny/ask` in `~/.gemini/antigravity-cli/settings.json` (precedence Deny > Ask > Allow); `mcp(server/tool)` rule form exists — the AD-20 §7 scoping is expressible. `--dangerously-skip-permissions` exists and is exactly the flag AD-20 §7 forbids. ⚠ Soft-deny + exit 0 means a denied tool does **not** fail the run — see F4. |
| 23 | "preview-grade" | ❌ not confirmed as stated | https://antigravity.google/docs/cli/getting-started (shows "Antigravity CLI v1.2.0"); https://antigravity.google/pricing ("Generally Available"); https://developers.googleblog.com/…transitioning… ("available to everyone") | No vendor page labels the CLI "preview". Docs header shows v1.2.0 (third-party changelog trackers list 1.1.27 on 2026-09-05, i.e. ~weekly releases). Only "Teamwork" (`/teamwork-preview`) is marked preview. The *churn* concern is legitimate; the *label* is not. |
| 24 | `httpx>=0.28,<1` | ✅ | https://pypi.org/pypi/httpx/json | Latest is 0.28.1 (2024-12-06); no 0.29 or 1.x has shipped. Lock = 0.28.1. Pin is correct; 21 months without a release is worth a note, not a change. |

## Findings

**F1 — MEDIUM — Antigravity CLI "preview-grade" is not what the vendor says.** Stack row 196 calls `agy` "preview-grade, pin when the adapter is built". Google's docs show Antigravity CLI v1.2.0 with no preview label, the pricing page says Generally Available, and the launch post says "available to everyone". Change to something dated and factual, e.g. "v1.2.0 as of 2026-09-12, releasing roughly weekly — pin when the adapter is built". Keep the pin instruction; drop the unverifiable label.

**F2 — LOW — `.agents/mcp_config.json` "same `mcpServers` shape" is stdio-only.** Antigravity remote servers use `serverUrl`/`headers`; Claude Code's `.mcp.json` uses `url`/`type`. Rez Ops's 7 servers are all stdio so nothing breaks today, but AD-16's "derive per adapter" is doing real work here. Add "(stdio entries identical; remote entries differ — `serverUrl` vs `url`)" to row 196 or to the Deferred derivation item at line 267 so the Phase 1 spike doesn't assume a copy.

**F3 — LOW — Elicitation Deferred item names "pinned `mcp` 1.29.x" but the pin admits 1.30.0, and the lock is stale on a security-only line.** Line 283 says "the pinned `mcp` 1.29.x SDK"; the pin is `>=1.29,<2` which now resolves to 1.30.0 (2026-09-07), while `uv.lock` still holds 1.29.0 (two security-only releases behind: 1.29.1, 1.30.0). Reword to "the pinned 1.x SDK (1.30.0 at time of writing)" and — outside this review's remit but worth a story-sized action — `uv lock --upgrade-package mcp` to 1.30.0.

**F4 — LOW (design note, not an error) — Antigravity soft-deny exits 0.** Row 196 correctly says "soft-deny", but the consequence matters for AD-20 §7 and AD-17's "healthy" probe: an `agy -p` run whose MCP tool call was denied still exits 0 and reports `SUCCESS`, with only a stderr notice. The google adapter must therefore treat stderr permission notices / absence of expected tool events as `AGENT_OUTPUT_INVALID` rather than trusting the exit code. Suggest a one-clause note in row 196 ("denials surface only on stderr; exit code stays 0") so the Phase 1 spike inherits it.

**F5 — INFO — Issue #38987 is closed; fix version not captured.** The spine's claim (regression in 2.1.77, 2026-03) is accurate and the issue is real and closed. The closing comment / fix version was not retrievable in this review. The spine only uses the issue as evidence for "re-probe every run", which stands regardless; no change required, but the row could say "(closed)" for completeness.

**F6 — INFO — `codex login --device-auth` is marked beta by OpenAI.** Row 195's "device auth" is real but vendor-labelled beta; the plain browser `codex login` is the GA subscription path. Worth one word in row 195 ("device auth, beta") since AD-17 will probe it.

**F7 — INFO — Local evidence for AD-17 is unusually strong.** The npm wrapper `@openai/codex@0.72.0` on this machine has no native binary (`ENOENT`), which is the literal AD-17 example; the current npm `latest` is 0.154.0. Nothing to change in the spine; recording it here so the Phase 1 spike knows the probe must execute the binary, not just `npm ls`.

Claims that were asserted with a date and confirmed: all Stack rows carry "2026-09-12" or an explicit release date. Claims asserted without a date: "preview-grade" (F1), "same `mcpServers` shape" (F2). Claims that could NOT be confirmed: none outright; F1 is contradicted rather than unconfirmed; the #38987 fix version (F5) and a fresh live 7-server/18-tool headless round-trip (row 9) were not re-verified by this reviewer.

## Sources

- Python release status — https://devguide.python.org/versions/
- MCP Python SDK on PyPI — https://pypi.org/pypi/mcp/json
- MCP Python SDK releases — https://github.com/modelcontextprotocol/python-sdk/releases
- MCP Python SDK README — https://github.com/modelcontextprotocol/python-sdk/blob/main/README.md
- MCP SDK v1→v2 migration guide — https://py.sdk.modelcontextprotocol.io/migration/
- MCP SDK multi-round-trip (elicitation) — https://py.sdk.modelcontextprotocol.io/handlers/multi-round-trip/
- Claude Code CHANGELOG — https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md
- Claude Code issue #38987 — https://github.com/anthropics/claude-code/issues/38987
- Codex non-interactive mode — https://learn.chatgpt.com/docs/non-interactive-mode (308 from https://developers.openai.com/codex/noninteractive)
- Codex authentication — https://learn.chatgpt.com/docs/auth
- Codex config reference — https://learn.chatgpt.com/docs/config-file/config-reference
- `@openai/codex` npm latest — https://registry.npmjs.org/@openai/codex/latest
- Gemini CLI → Antigravity CLI transition — https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/
- Gemini Code Assist release notes — https://docs.cloud.google.com/gemini/docs/codeassist/release-notes
- Antigravity CLI getting started — https://antigravity.google/docs/cli/getting-started
- Antigravity CLI headless mode — https://antigravity.google/docs/cli/headless/
- Antigravity CLI MCP config — https://antigravity.google/docs/cli/mcp/
- Antigravity CLI permissions — https://antigravity.google/docs/cli/permissions/
- Antigravity pricing (GA label) — https://antigravity.google/pricing
- antigravity-cli issue #7 (conversation id in --print) — https://github.com/google-antigravity/antigravity-cli/issues/7
- httpx on PyPI — https://pypi.org/pypi/httpx/json
- Local: `claude --version`/`--help` (2.1.269), `npm ls -g @openai/codex` (0.72.0, binary ENOENT), `which agy` (absent), `gemini --version` (0.36.0), `uv run python` (3.13.11), `mcp` 1.29.0, `uv.lock`, `.mcp.json` (7 servers)
