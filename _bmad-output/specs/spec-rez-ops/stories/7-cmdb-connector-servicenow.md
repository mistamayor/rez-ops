---
title: 'CMDB connector: ServiceNow'
type: 'feature'
created: '2026-08-16'
status: 'done'
review_loop_iteration: 0
baseline_commit: '814b147795da56697a30c5a24faaddc417fda944'
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/specs/spec-rez-ops/SPEC.md'
  - '{project-root}/shared/ledger_schema/models.py'
  - '{project-root}/connectors/ticketing/server.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Rez Ops has three Sensors (git, ticketing, calendar) but no CMDB connector yet (SPEC CAP-2's fourth and last connector from the original brief) — the last item deferred from Story 5's split.

**Approach:** Build `connectors/cmdb/` exposing one tool, `cmdb_get_ci_status(table, sys_id, artifact_type, artifact_id)`, that fetches one configuration-item record from ServiceNow's Table API (`GET /api/now/table/{table}/{sys_id}`) and returns it as a `RawFact`. Same vendor and API mechanism as the ticketing connector, but a genuinely different domain (CIs, not tickets) — per AD-2, this is its own independent connector server, not an extension of `connectors/ticketing/`, and duplicates rather than shares the ServiceNow-fetch pattern (connectors don't import each other). Every lesson from the ticketing and calendar connectors' reviews is applied from the start: `sysparm_display_value`/`sysparm_fields`, URL-encoding, HTTPS-only instance URL validation, no response-body leakage in errors, narrow exception types, non-string input guards, control-character-free credentials.

## Boundaries & Constraints

**Always:**
- Read-only: only ever issues `GET` requests to ServiceNow's Table API — never `POST`/`PUT`/`PATCH`/`DELETE` (CAP-2's "no write/update/delete" success criterion).
- Credentials come only from `REZOPS_CMDB_INSTANCE_URL` and `REZOPS_CMDB_TOKEN` env vars — a separate pair from the ticketing connector's, even though both may point at the same ServiceNow instance in practice (AD-2 independence: no connector depends on another connector's configuration).
- `instance_url` must start with `https://` and be non-blank after stripping trailing slashes; the credential token must not contain control characters.
- The request includes `sysparm_display_value=true` and a `sysparm_fields` restriction to the fields actually used, since ServiceNow reference fields (e.g. `support_group`) come back as nested objects otherwise (the exact bug the ticketing connector's review found).
- The tool name is domain-prefixed: `cmdb_get_ci_status` (AD-2).
- `table` and `sys_id` are URL-encoded before being interpolated into the request path.
- The tool constructs and returns a `RawFact`, serialized to a plain dict — never a `LedgerRecord`-shaped value (AD-9).
- This connector never imports or calls `ledger_core`, nor `connectors/ticketing/`, directly (AD-1, AD-2).
- Every HTTP request has a timeout. Exception messages never include raw response body content. The exception wrapping `RawFact(...)` construction catches the shared schema module's specific validation error type, not a bare `Exception`. Non-string inputs raise the typed validation error rather than an unguarded `AttributeError`. Required response fields present but `None` are treated as malformed, same as absent.

**Ask First:**
- Any dependency beyond `httpx` (already a direct dependency) plus the existing `mcp` and `shared` packages.

**Never:**
- No write operations against ServiceNow (no CI creation or update).
- No auto-correlation of an artifact to a CI record — the caller supplies the exact `table` and `sys_id`.
- No computation of `tier_sla`/`escalation_owner` from CI data in this story — that's a future ledger-core capability (mirroring how Story 3 added confidence computation after Story 2 shipped the git connector), not this connector's job.
- No sharing of code or credentials with the ticketing connector, even though both target ServiceNow.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path | Valid `table`/`sys_id`, mocked HTTP 200 with a realistic CI record (`support_group` as a reference-field object) | Returns a `RawFact`-shaped dict: `source="servicenow:<instance>/<table>/<sys_id>"`, `fields` containing `name`, `sys_class_name`, `operational_status`, `install_status`, `support_group`, `sys_updated_on`, all scalar | N/A |
| CI not found | Mocked HTTP 404 | No `RawFact` returned | Raises a typed `CINotFoundError` |
| Auth failure | Mocked HTTP 401 or 403 | No `RawFact` returned | Raises a typed `AuthenticationError` |
| Missing/blank credential | Either env var unset or blank | No HTTP request attempted | Raises a typed `MissingCredentialsError` |
| Malformed `instance_url` | Missing `https://` scheme, or only slashes | No HTTP request attempted | Raises a typed `InvalidInstanceUrlError` |
| Network/timeout failure | Mocked connection error or timeout | No `RawFact` returned | Raises a typed `CMDBConnectorError` |
| Empty/whitespace or non-string `table`/`sys_id`/`artifact_type`/`artifact_id` | `""`, `"  "`, or a non-string value | Rejected before any HTTP call | Raises a typed validation error |
| Malformed response body | Mocked 200 with a missing/`null` required field, invalid JSON, or a non-object body | No `RawFact` returned | Raises a typed `MalformedResponseError`, not a raw `KeyError` |

</frozen-after-approval>

## Code Map

- `shared/ledger_schema/models.py` -- reuse: `RawFact` construction target; read-only, no changes expected
- `connectors/ticketing/server.py` -- reuse as pattern (read, not imported): typed-error hierarchy, `sysparm_display_value`, instance URL validation, URL encoding, credential control-char check, non-leaking errors — all carried over directly
- `pyproject.toml` -- verify (per Story 6's precedent) whether the existing `"connectors"` wheel-packages entry already covers `connectors/cmdb`
- `connectors/cmdb/__init__.py` -- new: package marker
- `connectors/cmdb/server.py` -- new: MCP server exposing `cmdb_get_ci_status`
- `tests/test_cmdb_connector.py` -- new: covers the I/O matrix above via `httpx.MockTransport`

## Tasks & Acceptance

**Execution:**
- [x] `pyproject.toml` -- verified the existing `"connectors"` wheel-packages entry already covers `connectors/cmdb` (confirmed via `uv sync` + `import connectors.cmdb.server`); no edit needed
- [x] `connectors/cmdb/server.py` -- implemented `cmdb_get_ci_status(table, sys_id, artifact_type, artifact_id)`, applying every hardening pattern from `connectors/ticketing/server.py` from the start -- AD-1, AD-2, AD-9
- [x] `tests/test_cmdb_connector.py` -- unit tests for every I/O matrix row using `httpx.MockTransport`

**Acceptance Criteria:**
- Given the full test suite, when `uv run pytest` runs, then all tests pass.
- Given an MCP client lists the CMDB connector server's tools, then exactly one tool (`cmdb_get_ci_status`) is present and no write tool exists.
- Given a mocked CI record with `support_group` as a nested reference-field object, when the tool runs, then the returned `RawFact`'s `support_group` field is a scalar (proving `sysparm_display_value` was applied correctly, not rediscovered via review).

## Spec Change Log

## Design Notes

This is the fourth connector and the third against ServiceNow's Table API (after ticketing). Every hardening lesson from ticketing's and calendar's reviews is specified as an "Always" boundary here rather than left to be found again — the goal is a review round that finds CMDB-specific gaps only, the same way calendar's review found new issues but confirmed all of ticketing's known bugs were already avoided.

## Verification

**Commands:**
- `uv sync` -- expected: resolves without error (no new dependency expected) -- ran, resolved with no changes
- `uv run pytest -v` -- expected: all tests pass, including every prior story's -- ran, 306 passed after review fixes (79 for this story)
- `uv run python -c "import connectors.cmdb.server"` -- expected: imports without error -- ran, imported cleanly

## Suggested Review Order

**Closing the leak review found (the real catch this round)**

- Malformed-response branches no longer echo raw CI field content -- this had regressed from the calendar connector's already-fixed pattern.
  [`server.py:331`](../../../../connectors/cmdb/server.py#L331)

- Proof: a planted sensitive field never appears in any malformed-response error message.
  [`test_cmdb_connector.py:700`](../../../../tests/test_cmdb_connector.py#L700)

**Validation that now actually prevents a wasted live call**

- Identifier charset now matches `RawFact`'s own rule -- a malformed `artifact_type`/`artifact_id` is rejected before any HTTP request, not after.
  [`server.py:188`](../../../../connectors/cmdb/server.py#L188)

- `instance_url` now rejects control characters, whitespace, and `?`/`#`, not just missing `https://`.
  [`server.py:205`](../../../../connectors/cmdb/server.py#L205)

**The tool itself**

- Entry point: validates inputs, fetches (with `sysparm_display_value`/`sysparm_fields` applied from the start), constructs the `RawFact`.
  [`server.py:407`](../../../../connectors/cmdb/server.py#L407)

- Error hierarchy -- every failure mode is one of these, including client construction itself now wrapped.
  [`server.py:128`](../../../../connectors/cmdb/server.py#L128), [`:284`](../../../../connectors/cmdb/server.py#L284)

**Peripherals**

- Happy path, proving the reference-field flattening (`support_group`) works via the query params, not code-side transformation.
  [`test_cmdb_connector.py:79`](../../../../tests/test_cmdb_connector.py#L79)
