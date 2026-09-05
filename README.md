# Rez Ops

An AI agent framework for managing a Disaster Recovery program as a thin, read-only orchestration layer over the tools a program already has — never a new system of record. Positioning: **smoke detector, not fire inspector**.

Full rationale lives in the planning artifacts below; this file covers what's built, how to run it, and how to actually use it day to day.

## Architecture

**Sensors–Ledger–Voice**, three layers, each an MCP-server boundary:

- **Sensors** (`connectors/`) — dumb, read-only, domain-scoped MCP servers. Each fetches raw facts from one external system and normalizes them into `RawFact`. No freshness, confidence, or ownership logic.
- **Ledger** (`ledger_core/`) — one MCP server, sole owner of the Freshness Ledger: append-only event log, confidence/coverage computation, live queries.
- **Voice** (external) — the orchestrating coding-agent runtime (Claude Code, or any MCP-compatible client). Calls Sensors and Ledger, presents output. Holds no domain logic of its own. **You** are the Voice's operator — everything in the User Guide below happens by talking to Claude Code (or another MCP client) in this repo, not by running Python directly.

Full architecture: [`_bmad-output/planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/`](_bmad-output/planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/) (`ARCHITECTURE-SPINE.md` for the build-facing contract, `solution-design.md` for the rationale, `walkthrough-deck.html` for a visual walkthrough). Machine contract: [`_bmad-output/specs/spec-rez-ops/SPEC.md`](_bmad-output/specs/spec-rez-ops/SPEC.md).

## Status

All 11 planned stories shipped, 399 tests passing. See [`_bmad-output/specs/spec-rez-ops/stories.yaml`](_bmad-output/specs/spec-rez-ops/stories.yaml) for the full breakdown.

**Built:**
- Shared `RawFact`/`LedgerRecord` schema and append-only ledger core (confidence, coverage, live queries)
- Four Sensors: git (local, no credentials needed), ServiceNow ticketing, Google Calendar, ServiceNow CMDB
- Ownership inference/arbitration and orphan-risk detection, draft-not-send outbound content, a periodic briefing aggregating what needs a decision today, and `.mcp.json` + `ops/run_scheduled_briefing.py` for OS-scheduled headless operation with explicit failure logging

**Not yet done:** registering an actual cron/launchd job on any machine — `ops/README.md` documents how, but nothing installs one automatically. Known gaps and accepted risks are tracked in [`_bmad-output/implementation-artifacts/deferred-work.md`](_bmad-output/implementation-artifacts/deferred-work.md).

## Requirements

- Python 3.13+
- [`uv`](https://docs.astral.sh/uv/)
- [Claude Code](https://claude.com/claude-code) (or any other MCP-compatible client) to actually *use* Rez Ops — see the User Guide below. Not required just to develop/test the codebase.

## Setup (development)

```bash
uv sync
uv run pytest -v      # 399 tests, all mocked/local — no live credentials needed to run the suite
```

This is enough to develop and test Rez Ops. To actually *use* it against real systems, continue to the User Guide.

---

## User Guide

Rez Ops has no CLI and no UI of its own — every one of the 11 tools below is an MCP tool call, and you drive it by talking to an MCP-compatible client (Claude Code is the reference runtime) in natural language. This section walks through going from a fresh checkout to a running daily briefing.

### 1. Set connector credentials

Each connector reads its own credentials from environment variables — never a config file, never shared between connectors even when they target the same vendor (AD-7). Set whichever connectors you plan to use; you don't need all four.

| Connector | Env vars | Notes |
|---|---|---|
| git | none | Reads local git history directly — no setup needed |
| ticketing (ServiceNow) | `REZOPS_TICKETING_INSTANCE_URL`, `REZOPS_TICKETING_TOKEN` | Instance URL must be `https://` |
| calendar (Google) | `REZOPS_CALENDAR_TOKEN` | An OAuth access token with Calendar read scope |
| cmdb (ServiceNow) | `REZOPS_CMDB_INSTANCE_URL`, `REZOPS_CMDB_TOKEN` | Separate instance/token from ticketing even if it's the same ServiceNow tenant — no credential sharing between connectors, by design |

```bash
export REZOPS_TICKETING_INSTANCE_URL="https://yourinstance.service-now.com"
export REZOPS_TICKETING_TOKEN="..."
export REZOPS_CALENDAR_TOKEN="..."
export REZOPS_CMDB_INSTANCE_URL="https://yourinstance.service-now.com"
export REZOPS_CMDB_TOKEN="..."
```

None of these are required to run the test suite — every HTTP-based connector is tested against `httpx.MockTransport`. They're only needed when you want a connector to talk to a real system.

### 2. Connect Claude Code to Rez Ops

`.mcp.json` at the repo root already registers all five servers (ledger-core + four connectors) as project-scoped MCP servers, each launched as `uv run python -m {module}.server`. Nothing further to configure — just run Claude Code from inside this repo:

```bash
cd /path/to/rez-ops
claude
```

Claude Code detects `.mcp.json` automatically and (on first use) will prompt you to approve the project-scoped servers. Once approved, all 11 tools below are available to it. If you're using a different MCP client, point it at the same `.mcp.json`.

### 3. Core concepts

- **`artifact_type` / `artifact_id`** — you choose these; they're the label for whatever you're tracking. `artifact_type` is a category (e.g. `runbooks`, `bia`, `tiering`, `raci`, `test_records`), `artifact_id` is one specific thing within it (e.g. `payments-service-runbook`). Both must match `^[A-Za-z0-9_-]+$` (letters, digits, `_`, `-`). Pick a convention and stay consistent — the ledger doesn't validate against any external list, so a typo silently creates a new, separate artifact.
- **RawFact vs. LedgerRecord** — a connector tool returns a *RawFact*: one observed fact from one source system, with no confidence or ownership attached (AD-9). Calling `ledger_ingest_raw_fact` records that fact into the ledger's append-only log. A *LedgerRecord* (what you get back from `ledger_get_record`/`ledger_list_records`) is ledger-core's computed view over every fact ever ingested for that artifact — confidence, escalation owner, and orphan-risk status are all derived, never something you set directly.
- **Confidence is never hidden** — every record's `confidence` is one of `agent-verified`, `manual`, or `unknown`. There's no "assume it's fine" state; if nothing has ever ingested a fact for an artifact, it's `unknown`, visibly.
- **Escalation owner & orphan-risk** — ledger-core picks one owner per artifact from whichever of these fields is present, in priority order: CMDB's `support_group` > ticketing's `assigned_to` > calendar's `organizer_email`. An artifact with facts but none of those three fields is *orphan-risk* — known to exist, but nobody's on the hook for it.

### 4. The tools

**Ledger-core** (7 tools — the only thing that ever writes to the ledger):

| Tool | Purpose |
|---|---|
| `ledger_ingest_raw_fact(artifact_type, artifact_id, source, fields)` | Record one observed fact. Usually called with a connector tool's output, not by hand. |
| `ledger_get_record(artifact_type, artifact_id)` | Get the current computed state of one artifact. |
| `ledger_list_records(artifact_type=None, confidence=None, orphan_risk=None)` | List/filter every known artifact — "what's `unknown`", "what's orphan-risk". |
| `ledger_get_coverage()` | Per-artifact-type tally of confidence counts — a bird's-eye view. |
| `ledger_create_draft(artifact_type, artifact_id, draft_type, subject, body, recipient=None)` | Draft outbound content (e.g. a nudge to an owner). Never sends anything. |
| `ledger_list_drafts(artifact_type=None, artifact_id=None, draft_type=None)` | List drafts waiting for a human to actually send. |
| `ledger_get_briefing()` | The daily briefing: orphan-risk artifacts, unknown-confidence artifacts, pending drafts, and any data-quality issues, in one call. |

**Sensors** (4 tools — one per connector, each returns a RawFact-shaped dict, never writes to the ledger itself):

| Tool | Fetches |
|---|---|
| `git_get_last_touched(repo_path, file_path, artifact_type, artifact_id)` | Last commit that touched a file — who, when, which SHA. |
| `ticketing_get_ticket_status(table, sys_id, artifact_type, artifact_id)` | One ServiceNow ticket's current state. |
| `calendar_get_event_status(calendar_id, event_id, artifact_type, artifact_id)` | One Google Calendar event's current state (e.g. a scheduled DR test). |
| `cmdb_get_ci_status(table, sys_id, artifact_type, artifact_id)` | One ServiceNow CMDB configuration item's current state. |

### 5. Walkthrough: tracking your first artifact

Say you want Rez Ops to track whether `payments-service`'s runbook is actually being kept up to date. In Claude Code, in this repo, just ask in plain language:

> "Check when `runbooks/payments-service.md` was last touched in this repo, and record that as a fact for artifact `runbooks`/`payments-service`."

Claude Code will call `git_get_last_touched`, then feed its output straight into `ledger_ingest_raw_fact` (the connector's output — `artifact_type`, `artifact_id`, `source`, `fields` — is already shaped to be passed through as-is). Then:

> "What's the current state of `runbooks`/`payments-service`?"

calls `ledger_get_record` and shows you the computed confidence, last-verified timestamp, and (once a CMDB/ticketing/calendar fact is also ingested for it) escalation owner. Repeat the ingest step for a ticketing, CMDB, or calendar fact about the same artifact and the owner/orphan-risk computation updates automatically — no separate step.

### 6. Getting the daily briefing

> "Give me the Rez Ops briefing."

calls `ledger_get_briefing()` — everything that needs a decision today, in one call: which artifacts are orphan-risk, which are `unknown` confidence, which drafts are still waiting to be sent, and any data-quality issues (a corrupted log surfaces here rather than silently vanishing — AD-8).

### 7. Drafting outbound content

Rez Ops never sends anything on its own (AD-6) — it only prepares a draft for a human to review and send manually:

> "Draft a message to whoever owns `runbooks`/`payments-service` asking them to review it — it hasn't been verified in months."

calls `ledger_create_draft`, which defaults `recipient` to that artifact's computed escalation owner (or leaves it unset if the artifact is orphan-risk — never a guess). The draft is written to `ledger_data/drafts/{draft_id}.md`, a plain git-tracked markdown file you can also open and read directly. List everything pending with `ledger_list_drafts()`.

### 8. Running it unattended

`ops/run_scheduled_briefing.py` invokes `claude -p --mcp-config .mcp.json --output-format json` non-interactively and logs any failure (never fails silently) to `ledger_data/_ops.log.md`. Full setup, including sample crontab/launchd snippets, is in [`ops/README.md`](ops/README.md) — registering an actual scheduled job is a manual step nothing in this repo does for you.

---

## Project layout

```
shared/ledger_schema/   # RawFact (connector-writable) / LedgerRecord (ledger-core-only) — the shared schema
ledger_core/            # Ledger MCP server: append-only log, confidence, coverage, ownership, drafts, briefing
connectors/
  git_repo/              # Sensor: local git "last touched" metadata — no credentials needed
  ticketing/              # Sensor: ServiceNow Table API (incidents/tasks)
  calendar_google/         # Sensor: Google Calendar API v3
  cmdb/                     # Sensor: ServiceNow Table API (configuration items)
ops/                     # Scheduled headless invocation wrapper + failure logging (AD-7)
tests/                   # One test file per module, httpx.MockTransport for every HTTP connector
ledger_data/             # Runtime state: append-only per-artifact-type logs (git-committed, human-readable)
.mcp.json                # Project-scoped registration of ledger-core + all four connector servers
_bmad-output/            # Planning artifacts, spec, architecture, per-story specs, deferred-work log
```

## Non-negotiables (v1)

- **Read-only-first** — no connector writes to any external system of record.
- **Graceful degradation** — any failure fails open to today's manual baseline; Rez Ops is additive, never a dependency of the program it observes.
- **Never hide uncertainty** — every derived value carries an explicit confidence state; a corrupted or missing data source surfaces visibly rather than disappearing.
