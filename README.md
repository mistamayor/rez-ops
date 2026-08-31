# Rez Ops

An AI agent framework for managing a Disaster Recovery program as a thin, read-only orchestration layer over the tools a program already has — never a new system of record. Positioning: **smoke detector, not fire inspector**.

Full rationale lives in the planning artifacts below; this file covers what's built and how to run it.

## Architecture

**Sensors–Ledger–Voice**, three layers, each an MCP-server boundary:

- **Sensors** (`connectors/`) — dumb, read-only, domain-scoped MCP servers. Each fetches raw facts from one external system and normalizes them into `RawFact`. No freshness, confidence, or ownership logic.
- **Ledger** (`ledger_core/`) — one MCP server, sole owner of the Freshness Ledger: append-only event log, confidence/coverage computation, live queries.
- **Voice** (external) — the orchestrating coding-agent runtime (Claude Code, or any MCP-compatible client). Calls Sensors and Ledger, presents output. Holds no domain logic of its own.

Full architecture: [`_bmad-output/planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/`](_bmad-output/planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/) (`ARCHITECTURE-SPINE.md` for the build-facing contract, `solution-design.md` for the rationale, `walkthrough-deck.html` for a visual walkthrough). Machine contract: [`_bmad-output/specs/spec-rez-ops/SPEC.md`](_bmad-output/specs/spec-rez-ops/SPEC.md).

## Status

7 of 11 planned stories shipped, 306 tests passing. See [`_bmad-output/specs/spec-rez-ops/stories.yaml`](_bmad-output/specs/spec-rez-ops/stories.yaml) for the full breakdown and what's next (currently: ownership inference and arbitration).

**Built:**
- Shared `RawFact`/`LedgerRecord` schema and append-only ledger core (confidence, coverage, live queries)
- Four Sensors: git (local, no credentials needed), ServiceNow ticketing, Google Calendar, ServiceNow CMDB

**Not yet built:** ownership arbitration, draft-not-send outbound content, periodic briefing, scheduled headless operation — see `stories.yaml`. Known gaps and accepted risks are tracked in [`_bmad-output/implementation-artifacts/deferred-work.md`](_bmad-output/implementation-artifacts/deferred-work.md).

## Requirements

- Python 3.13+
- [`uv`](https://docs.astral.sh/uv/)

## Setup

```bash
uv sync
uv run pytest -v      # 306 tests, all mocked/local — no live credentials needed to run the suite
```

## Project layout

```
shared/ledger_schema/   # RawFact (connector-writable) / LedgerRecord (ledger-core-only) — the shared schema
ledger_core/            # Ledger MCP server: append-only log, confidence, coverage, live queries
connectors/
  git_repo/              # Sensor: local git "last touched" metadata — no credentials needed
  ticketing/              # Sensor: ServiceNow Table API (incidents/tasks)
  calendar_google/         # Sensor: Google Calendar API v3
  cmdb/                     # Sensor: ServiceNow Table API (configuration items)
tests/                   # One test file per module, httpx.MockTransport for every HTTP connector
ledger_data/             # Runtime state: append-only per-artifact-type logs (git-committed, human-readable)
_bmad-output/            # Planning artifacts, spec, architecture, per-story specs, deferred-work log
```

## Connector credentials

Each connector reads its own credentials from environment variables — never a config file, never shared between connectors even when they target the same vendor (see `ARCHITECTURE-SPINE.md` AD-7).

| Connector | Env vars |
|---|---|
| git | none — reads local git history directly |
| ticketing (ServiceNow) | `REZOPS_TICKETING_INSTANCE_URL`, `REZOPS_TICKETING_TOKEN` |
| calendar (Google) | `REZOPS_CALENDAR_TOKEN` |
| cmdb (ServiceNow) | `REZOPS_CMDB_INSTANCE_URL`, `REZOPS_CMDB_TOKEN` |

None of the above are required to run the test suite — every HTTP-based connector is tested against `httpx.MockTransport`.

## Non-negotiables (v1)

- **Read-only-first** — no connector writes to any external system of record.
- **Graceful degradation** — any failure fails open to today's manual baseline; Rez Ops is additive, never a dependency of the program it observes.
- **Never hide uncertainty** — every derived value carries an explicit confidence state; a corrupted or missing data source surfaces visibly rather than disappearing.
