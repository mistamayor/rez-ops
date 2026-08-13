---
review: version-currency
target: ARCHITECTURE-SPINE.md (Rez Ops)
target_path: '_bmad-output/planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/ARCHITECTURE-SPINE.md'
lens: "Verify every committed decision was web-researched or reality-checked rather than asserted from training data: current library/framework versions, that each named technology still exists and fits, and — greenfield — the live defaults of any starter it leans on. Flag anything that could be out of date and wasn't confirmed against the web, the existing project, or the current starter."
date: '2026-08-12'
verdict: CHANGES-REQUESTED
---

# Version-Currency Review — Rez Ops Architecture Spine

## Verdict

**Changes required.** One claim in the Stack table is not just unverified but demonstrably wrong once checked against Claude Code's own documentation: the documented headless invocation (`claude -p --bare --output-format json`) will not load the MCP servers the entire architecture is built around. Everything else in the Stack table checks out or is a defensible, if unstated, judgment call. This looks like a partial research pass — the `mcp` SDK pin was clearly checked against the web (it's accurate to the day), but the Claude Code headless flags were not reality-checked against Claude Code's own `--bare` semantics.

## Method

Independently web-searched each named technology/version rather than trusting the spine's "researched earlier the same day" claim, per this gate's mandate. Checked: PyPI/GitHub release history for the `mcp` Python SDK, the MCP spec/SDK v2 announcement, Claude Code's official headless-mode docs and CLI reference, Python's release/EOL schedule, and whether any starter/scaffold is implicated by the design (none is).

## Findings

### 1. CRITICAL — `--bare` will not load the MCP servers the headless path depends on

**Claim (Stack table, AD-7):** `claude -p --bare --output-format json` is the mechanism by which the OS scheduler (cron/launchd) invokes the runtime headlessly to do things like a daily briefing.

**Reality (Claude Code official headless docs, code.claude.com/docs/en/headless):**
> "Add `--bare` to reduce startup time by **skipping auto-discovery of hooks, skills, plugins, MCP servers, auto memory, and CLAUDE.md**... A hook in a teammate's `~/.claude` or **an MCP server in the project's `.mcp.json` won't run, because bare mode never reads them.**"

This is a direct contradiction of the architecture's own design. The Voice layer's entire job in a scheduled run is to call the Sensors (calendar/ticketing/git/CMDB) and Ledger-Core MCP servers registered in `.mcp.json` (per the Consistency Conventions row: "Connector/config lives in `.mcp.json` + `rezops.config.yaml`"). As literally specified, the cron-triggered command in AD-7 would start a bare Claude Code session with **no MCP servers attached at all** — no Sensors, no Ledger-Core — because `--bare` never reads `.mcp.json`. A scheduled daily briefing built this way would produce no ledger-backed output; it would silently degrade to a plain LLM call with only Bash/Read/Edit tools.

The docs also give the fix, which the spine should incorporate: MCP servers must be passed explicitly even in bare mode via `--mcp-config <file-or-json>`. The corrected headless invocation is something like `claude -p --bare --mcp-config .mcp.json --output-format json`, not the flag combination currently in the spine.

This was checkable in one docs read and was not caught — a strong signal the "researched earlier the same day" pass did not reality-check the specific flag combination against Claude Code's own semantics, only that the flags individually exist.

**Recommendation:** Add `--mcp-config` (or equivalent) to the documented headless command in the Stack table and AD-7, or explicitly note that the scheduled path must not use `--bare` if minimal-config MCP loading isn't wired up another way.

### 2. MEDIUM — `--bare` mode forces API-key auth, disabling OAuth/subscription login

**Reality (same doc):** "In bare mode, Claude Code never reads OAuth credentials or the system keychain. For the Anthropic API, set `ANTHROPIC_API_KEY` in the environment... or supply an `apiKeyHelper`."

AD-7 frames Rez Ops as local-first and low-friction ("no hosted database... just a laptop and a git remote"), and the interactive path presumably uses the program owner's normal Claude Code login. But the scheduled/headless path via `--bare` cannot use that same OAuth session — it needs a separately provisioned `ANTHROPIC_API_KEY` (i.e., pay-as-you-go API billing, not the subscription the interactive session may be using). This operational fork (two auth paths, two billing models) is a real consequence of the chosen flag and isn't surfaced anywhere in the spine. Worth a line in AD-7 or the Stack table so it isn't discovered at implementation time.

### 3. MEDIUM — Python floor ("3.12+") is not the current line and isn't justified

Verified via web search:
- Python 3.12's full bugfix support ended **April 2025**; it has been in **security-only maintenance** since, through EOL **October 2028**.
- Python 3.13 is the actively bugfixed stable line (3.13.15 shipped Aug 5, 2026); **Python 3.14** is the current newest release (3.14.7, Aug 5, 2026); 3.15 is already in release-candidate.
- The `mcp` Python SDK only requires `>=3.10`, so nothing forces the 3.12 floor.

"3.12+" isn't wrong (it still exists, is supported until 2028, and satisfies the SDK's floor), but for a greenfield project starting today it reads like a remembered "safe modern default" rather than a checked one — there's no note on why 3.12 was picked over the actively-maintained 3.13/3.14 baseline. Recommend either bumping the floor to 3.13+ or adding a one-line rationale (e.g., "3.12 chosen for X library compatibility") so this isn't an unexamined carry-over from training data.

### 4. LOW — Claude Code reference runtime has no version floor despite version-gated behavior

The Stack table pins Python and `mcp` to specific ranges but gives Claude Code only as "current." Confirmed via Claude Code's own docs/changelog that several behaviors this architecture will lean on are version-gated (e.g., `--bare` itself landed at v2.1.81; the `mcp_server_errors`/`mcp_servers` fields in `system/init` used to verify a connector actually loaded require v2.1.219+; the `--mcp-config` startup-wait behavior needs v2.1.221+). None of this breaks the architecture, but "current" isn't independently reproducible the way the other two pins are — worth stating the minimum Claude Code version the design assumes, especially since it's needed to make Finding #1's fix observable/verifiable (checking `mcp_server_errors` in the JSON output to confirm the ledger/connector servers actually loaded on each cron run).

## Confirmed as correctly researched (no action needed)

- **`mcp` Python SDK, `1.29.x` pinned `<2`.** Verified against GitHub releases/PyPI: `1.29.0` and the stable `2.0.0` GA both shipped **2026-07-28** — the same date the spine's own Deferred section cites for the v2 MCP spec/SDK release. `pip install mcp` now defaults to 2.x, which makes the explicit `<2` pin not just accurate but load-bearing (an unpinned install today would silently pull v2 and break every SDK call the low-level `Server`/`ServerSession` code in this architecture would use). This is exactly the kind of decision the gate is looking for: current, dated, and defensible.
- **`mcp` technology still exists and fits** — actively maintained, official SDK, is the correct choice for the Sensors/Ledger MCP-server design.
- **git as sole persistence layer** — not a version-currency risk; no version is pinned or needs to be, and git's continued existence/fitness for an append-only, git-committed ledger isn't in question.

## Not applicable

- **Greenfield starter defaults:** the lens asks to check the live defaults of any starter the design leans on. No scaffold/starter (e.g. `create-mcp-server`, cookiecutter, `uv init` template) is referenced anywhere in the spine — the design is a hand-rolled layout on top of the raw `mcp` SDK, not bootstrapped from a template. There is nothing to reality-check here, so this is a clean N/A rather than a silent gap — but if implementation later reaches for the official quickstart scaffold, its defaults (stdio transport, `FastMCP`-style decorators) should be checked against AD-2/AD-4 at that point since they weren't checked now.

## Sources consulted

- https://github.com/modelcontextprotocol/python-sdk/releases (release dates for 1.28.x/1.29.0/2.0.0)
- https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.0.0
- https://blog.modelcontextprotocol.io/posts/sdk-betas-2026-07-28/
- https://pypi.org/project/mcp/
- https://libraries.io/pypi/mcp
- https://code.claude.com/docs/en/headless.md (official `--bare`, `-p`, `--output-format json`, `--mcp-config` semantics)
- https://github.com/anthropics/claude-code/issues/36852 (`--bare` documentation-gap issue, corroborates skip list)
- https://www.npmjs.com/package/@anthropic-ai/claude-code and Claude Code changelog sources (current CLI version line, v2.1.x)
- https://www.python.org/downloads/ and blog.python.org release posts (3.12/3.13/3.14/3.15 status as of Aug 2026)
- endoflife/HeroDevs Python EOL schedule summaries (3.12 support phase)
