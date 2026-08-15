---
title: 'Ticketing connector: ServiceNow'
type: 'feature'
created: '2026-08-15'
status: 'done'
review_loop_iteration: 0
baseline_commit: '204dec3ef6cbe954b18ab0a5ee47fd14d2135366'
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/specs/spec-rez-ops/SPEC.md'
  - '{project-root}/shared/ledger_schema/models.py'
  - '{project-root}/connectors/git_repo/server.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Rez Ops has one Sensor (git). SPEC CAP-2's second connector needs to prove the same read-only pattern against a real external system with real HTTP auth, not just a local subprocess — ServiceNow, the ticketing system chosen for this pass (split off from the original "calendar, ticketing, CMDB" story since each is independently shippable; calendar and CMDB are tracked in `deferred-work.md`).

**Approach:** Build `connectors/ticketing/` exposing one tool, `ticketing_get_ticket_status(table, sys_id, artifact_type, artifact_id)`, that fetches one record from ServiceNow's Table API (`GET /api/now/table/{table}/{sys_id}`) via `httpx` (already present transitively through the `mcp` SDK; add it as an explicit direct dependency) and returns it as a `RawFact`. Like the git connector, this does not attempt to auto-correlate an artifact to a ServiceNow record — the caller supplies the exact `table`/`sys_id`, mirroring how the git connector took an explicit `repo_path`/`file_path` rather than inventing a search feature. Tested entirely against `httpx.MockTransport` — no live ServiceNow instance or credentials needed for the test suite, since none exists in this environment.

## Boundaries & Constraints

**Always:**
- Read-only: only ever issues `GET` requests to ServiceNow's Table API — never `POST`/`PUT`/`PATCH`/`DELETE` (CAP-2's "no write/update/delete" success criterion).
- Credentials come only from `REZOPS_TICKETING_INSTANCE_URL` and `REZOPS_TICKETING_TOKEN` env vars — never a config file or hardcoded value (AD-7's credential convention).
- The tool name is domain-prefixed: `ticketing_get_ticket_status` (AD-2).
- The tool constructs and returns a `RawFact`, serialized to a plain dict — never a `LedgerRecord`-shaped value (AD-9).
- This connector never imports or calls `ledger_core` directly (AD-1).
- Every HTTP request has a timeout (same lesson Story 2's review surfaced for `subprocess.run`).

**Ask First:**
- Any dependency beyond `httpx` (already transitively present) plus the existing `mcp` and `shared` packages.

**Never:**
- No write operations against ServiceNow (no incident/ticket creation or update).
- No auto-correlation of an artifact to a ServiceNow record — the caller supplies the exact `table` and `sys_id`.
- No caching of ServiceNow responses across calls.
- No calendar or CMDB connector in this story — tracked separately in `deferred-work.md`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path | Valid `table`/`sys_id`, mocked HTTP 200 with a realistic ServiceNow record body | Returns a `RawFact`-shaped dict: `source="servicenow:<instance>/<table>/<sys_id>"`, `fields` containing `number`, `state`, `assigned_to`, `sys_updated_on`, `short_description` | N/A |
| Record not found | Mocked HTTP 404 | No `RawFact` returned | Raises a typed `TicketNotFoundError` |
| Auth failure | Mocked HTTP 401 or 403 | No `RawFact` returned | Raises a typed `AuthenticationError` |
| Missing credentials | `REZOPS_TICKETING_INSTANCE_URL` or `REZOPS_TICKETING_TOKEN` unset | No HTTP request attempted | Raises a typed `MissingCredentialsError` |
| Network/timeout failure | Mocked connection error or timeout | No `RawFact` returned | Raises a typed `TicketingConnectorError` |
| Empty/whitespace `table` or `sys_id` | `""` or `"  "` | Rejected before any HTTP call | Raises a typed validation error |
| Malformed response body | Mocked 200 with a body missing expected fields | No `RawFact` returned | Raises a typed error, not a raw `KeyError` |

</frozen-after-approval>

## Code Map

- `shared/ledger_schema/models.py` -- reuse: `RawFact` construction target; read-only, no changes expected
- `connectors/git_repo/server.py` -- reuse as pattern: typed-error hierarchy, input validation, timeout handling established there
- `pyproject.toml` -- edit: add `httpx` as an explicit direct dependency, add `connectors/ticketing` to the wheel packages list
- `connectors/ticketing/__init__.py` -- new: package marker
- `connectors/ticketing/server.py` -- new: MCP server exposing `ticketing_get_ticket_status`
- `tests/test_ticketing_connector.py` -- new: covers the I/O matrix above via `httpx.MockTransport`

## Tasks & Acceptance

**Execution:**
- [x] `pyproject.toml` -- add `httpx` as an explicit direct dependency and `connectors/ticketing` to the wheel packages list (the pre-existing `"connectors"` entry in `[tool.hatch.build.targets.wheel] packages` already covers the `connectors/ticketing` subpackage -- confirmed by building a wheel and inspecting its contents, so no separate entry was needed)
- [x] `connectors/ticketing/server.py` -- implement `ticketing_get_ticket_status(table, sys_id, artifact_type, artifact_id)`: validate inputs, read credentials from env, `GET {instance_url}/api/now/table/{table}/{sys_id}` via `httpx` with a timeout and bearer auth, map HTTP/network failures to typed errors, construct and return a `RawFact` -- AD-1, AD-2, AD-9
- [x] `tests/test_ticketing_connector.py` -- unit tests for every I/O matrix row using `httpx.MockTransport`

**Acceptance Criteria:**
- Given the full test suite, when `uv run pytest` runs, then all tests pass.
- Given an MCP client lists the ticketing connector server's tools, then exactly one tool (`ticketing_get_ticket_status`) is present and no write tool exists.
- Given `REZOPS_TICKETING_INSTANCE_URL`/`REZOPS_TICKETING_TOKEN` are unset, when the tool runs, then it raises before any HTTP request is attempted (verifiable by asserting the mock transport receives zero calls for that case).

## Spec Change Log

## Design Notes

No live ServiceNow instance exists in this environment, so the test suite is built entirely against `httpx.MockTransport` (a real `httpx` feature for exactly this purpose) rather than live credentials — the connector code targets ServiceNow's real, documented Table API contract; only the test harness is simulated. `sys_updated_on` and other ServiceNow field values are stored as opaque raw strings in `fields` (no timezone parsing) since `RawFact.fields` only requires JSON-scalar values, not a specific format.

## Verification

**Commands:**
- `uv sync` -- expected: resolves and installs `httpx` as a direct dependency without error
- `uv run pytest -v` -- expected: all tests pass, including every prior story's
- `uv run python -c "import connectors.ticketing.server"` -- expected: imports without error

## Suggested Review Order

**Making this work against a real instance (review's key catch)**

- `sysparm_display_value`/`sysparm_fields` query params -- without these, real ServiceNow reference fields come back as nested objects, not scalars, and every mocked test would have missed it.
  [`server.py:76`](../../../../connectors/ticketing/server.py#L76)

- Proof the fix works: a realistic happy-path response with the actual query params asserted.
  [`test_ticketing_connector.py:75`](../../../../tests/test_ticketing_connector.py#L75)

- Defense-in-depth: if a non-scalar value somehow still arrives, it's a typed error, not a raw schema exception.
  [`test_ticketing_connector.py:569`](../../../../tests/test_ticketing_connector.py#L569)

**Request safety**

- URL-encodes `table`/`sys_id` before building the request path -- closes a path/query-injection risk review found.
  [`test_ticketing_connector.py:151`](../../../../tests/test_ticketing_connector.py#L151)

- Validates `instance_url` is `https://` and non-blank before any request is built.
  [`server.py:153`](../../../../connectors/ticketing/server.py#L153)

**The tool itself**

- Entry point: validates inputs, fetches, and constructs the `RawFact`.
  [`server.py:310`](../../../../connectors/ticketing/server.py#L310)

- Error hierarchy -- every failure mode is one of these, nothing propagates raw.
  [`server.py:90`](../../../../connectors/ticketing/server.py#L90)
