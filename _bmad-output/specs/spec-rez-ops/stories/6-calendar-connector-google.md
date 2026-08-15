---
title: 'Calendar connector: Google Calendar'
type: 'feature'
created: '2026-08-15'
status: 'done'
review_loop_iteration: 0
baseline_commit: '27ae07a69b75ad5bcdecb72fcce767b75891feff'
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/specs/spec-rez-ops/SPEC.md'
  - '{project-root}/shared/ledger_schema/models.py'
  - '{project-root}/connectors/ticketing/server.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Rez Ops has two Sensors (git, ticketing) but no calendar connector yet (SPEC CAP-2). Google Calendar is the product chosen for this pass — split off from a broader "both Google and Microsoft 365" ask since the two backends have unrelated auth and API shapes and are independently shippable (Microsoft 365 tracked in `deferred-work.md`).

**Approach:** Build `connectors/calendar_google/` exposing one tool, `calendar_get_event_status(calendar_id, event_id, artifact_type, artifact_id)`, that fetches one event from the Google Calendar API v3 (`GET /calendars/{calendarId}/events/{eventId}`) via `httpx` (already a direct dependency since Story 5) and returns it as a `RawFact`. Same no-auto-correlation pattern as the git and ticketing connectors — the caller supplies the exact `calendar_id`/`event_id`. Google's response nests several fields as objects (`start`, `end`, `organizer`) rather than scalars — this story flattens each to a scalar at extraction time, rather than discovering the same class of bug the ticketing connector's review already found. Tested entirely against `httpx.MockTransport`, no live Google account or credentials needed.

## Boundaries & Constraints

**Always:**
- Read-only: only ever issues `GET` requests to the Calendar API — never `POST`/`PUT`/`PATCH`/`DELETE` (CAP-2's "no write/update/delete" success criterion).
- The credential comes only from a `REZOPS_CALENDAR_TOKEN` env var (a pre-provisioned OAuth2 bearer access token; obtaining/refreshing it is out of scope) — never a config file or hardcoded value (AD-7's credential convention).
- The tool name is domain-prefixed: `calendar_get_event_status` (AD-2).
- `start`, `end`, and `organizer` are flattened to scalar strings at extraction time (`start`/`end` → the `dateTime` value, or the `date` value for an all-day event with no `dateTime`; `organizer` → its `email`) before ever reaching `RawFact` — never pass Google's nested objects through as a field value.
- The tool constructs and returns a `RawFact`, serialized to a plain dict — never a `LedgerRecord`-shaped value (AD-9).
- This connector never imports or calls `ledger_core` directly (AD-1).
- `calendar_id` and `event_id` are URL-encoded before being interpolated into the request path (the ticketing connector's review found this exact class of injection risk — apply the fix from the start here).
- Every HTTP request has a timeout.
- Exception messages for non-2xx responses never include raw response body content.
- The exception wrapping `RawFact(...)` construction catches the shared schema module's specific validation error type, not a bare `Exception`.
- Non-string `calendar_id`/`event_id`/`artifact_type`/`artifact_id` input raises the typed validation error rather than an unguarded `AttributeError`.

**Ask First:**
- Any dependency beyond `httpx` (already a direct dependency) plus the existing `mcp` and `shared` packages.

**Never:**
- No write operations against Google Calendar (no event creation or update).
- No auto-correlation of an artifact to a calendar event — the caller supplies the exact `calendar_id` and `event_id`.
- No OAuth flow, token refresh, or credential provisioning — the connector only ever reads a pre-existing token from the environment.
- No Microsoft 365/Outlook connector in this story — tracked separately in `deferred-work.md`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path, timed event | Valid `calendar_id`/`event_id`, mocked 200 with a realistic timed-event body (`start`/`end` as `dateTime` objects, `organizer` as an object) | Returns a `RawFact`-shaped dict with flattened scalar fields: `summary`, `status`, `start`, `end`, `updated`, `organizer_email` | N/A |
| Happy path, all-day event | Same, but `start`/`end` use `date` instead of `dateTime` | Flattening still produces scalar `start`/`end` values | N/A |
| Event with no organizer | `organizer` key absent from the response body entirely | `organizer_email` is omitted/`None` rather than raising | N/A |
| Event not found | Mocked HTTP 404 | No `RawFact` returned | Raises a typed `EventNotFoundError` |
| Auth failure | Mocked HTTP 401 or 403 | No `RawFact` returned | Raises a typed `AuthenticationError` |
| Missing credential | `REZOPS_CALENDAR_TOKEN` unset or blank | No HTTP request attempted | Raises a typed `MissingCredentialsError` |
| Network/timeout failure | Mocked connection error or timeout | No `RawFact` returned | Raises a typed `CalendarConnectorError` |
| Empty/whitespace `calendar_id` or `event_id` | `""` or `"  "` | Rejected before any HTTP call | Raises a typed validation error |
| `calendar_id`/`event_id` containing special characters | A value containing `/`, `?`, or whitespace | URL-encoded; request path/query unaffected | N/A (or typed error if rejected outright — implementer's call, consistent with the ticketing connector) |
| Malformed response body | Mocked 200 with a body missing an expected field, invalid JSON, or a non-object body | No `RawFact` returned | Raises a typed `MalformedResponseError`, not a raw `KeyError` |

</frozen-after-approval>

## Code Map

- `shared/ledger_schema/models.py` -- reuse: `RawFact` construction target; read-only, no changes expected
- `connectors/ticketing/server.py` -- reuse as pattern: typed-error hierarchy, input validation, URL encoding, timeout, and non-leaking error messages all established there
- `pyproject.toml` -- edit: add `connectors/calendar_google` to the wheel packages list if not already covered by the existing `"connectors"` entry (verify by building a wheel, per Story 5's precedent)
- `connectors/calendar_google/__init__.py` -- new: package marker
- `connectors/calendar_google/server.py` -- new: MCP server exposing `calendar_get_event_status`
- `tests/test_calendar_google_connector.py` -- new: covers the I/O matrix above via `httpx.MockTransport`

## Tasks & Acceptance

**Execution:**
- [x] `pyproject.toml` -- verified the existing `"connectors"` wheel-packages entry already covers `connectors/calendar_google` (built a wheel and confirmed); no edit needed
- [x] `connectors/calendar_google/server.py` -- implement `calendar_get_event_status(calendar_id, event_id, artifact_type, artifact_id)`: validate inputs, read credential from env, URL-encode path segments, `GET https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{event_id}` via `httpx` with a timeout and bearer auth, flatten `start`/`end`/`organizer` to scalars, map HTTP/network failures to typed errors, construct and return a `RawFact` -- AD-1, AD-2, AD-9
- [x] `tests/test_calendar_google_connector.py` -- unit tests for every I/O matrix row using `httpx.MockTransport`

**Acceptance Criteria:**
- Given the full test suite, when `uv run pytest` runs, then all tests pass.
- Given an MCP client lists the calendar connector server's tools, then exactly one tool (`calendar_get_event_status`) is present and no write tool exists.
- Given a mocked event body with nested `start`/`end`/`organizer` objects (the real Google API shape), when the tool runs, then the returned `RawFact`'s fields are all scalar values, not nested objects.

## Spec Change Log

## Design Notes

No live Google account exists in this environment, so the test suite is built entirely against `httpx.MockTransport`, mirroring the ticketing connector's approach — the connector code targets the real, documented Google Calendar API v3 contract; only the test harness is simulated. The flattening logic for `start`/`end`/`organizer` exists specifically because Google's API returns these as nested objects, which `RawFact.fields` cannot hold directly (JSON-scalar values only, per AD-9) — this was designed in from the start rather than discovered via review, learning directly from the ticketing connector's `sysparm_display_value` finding.

## Verification

**Commands:**
- `uv sync` -- expected: resolves without error (no new dependency expected)
- `uv run pytest -v` -- expected: all tests pass, including every prior story's
- `uv run python -c "import connectors.calendar_google.server"` -- expected: imports without error

## Suggested Review Order

**Flattening (why this connector needed care Story 5 didn't)**

- Datetime flattening -- now validates the extracted value is a real non-empty string, not just present.
  [`server.py:205`](../../../../connectors/calendar_google/server.py#L205)

- Organizer flattening -- distinguishes "absent" (fine) from "present but null/non-string" (a review-found gap, now typed).
  [`server.py:237`](../../../../connectors/calendar_google/server.py#L237)

- Proof: a null required field, a null datetime, and a non-string organizer email all raise the same typed error.
  [`test_calendar_google_connector.py:595`](../../../../tests/test_calendar_google_connector.py#L595)

**Applying Story 5's lessons from the start**

- Credential validation now also rejects control characters (a new review finding this round) alongside the blank/missing checks carried over from the ticketing connector.
  [`server.py:136`](../../../../connectors/calendar_google/server.py#L136)

- Response parsing: error messages never leak raw body/object content, matching the ticketing connector's discipline -- verified independently this round, not just carried over.
  [`server.py:264`](../../../../connectors/calendar_google/server.py#L264)

**The tool itself**

- Entry point: validates inputs, fetches, flattens, and constructs the `RawFact`.
  [`server.py:339`](../../../../connectors/calendar_google/server.py#L339)

- Error hierarchy -- every failure mode is one of these, nothing propagates raw.
  [`server.py:76`](../../../../connectors/calendar_google/server.py#L76)

**Peripherals**

- Happy-path tests for both timed and all-day events (Google's two different `start`/`end` shapes).
  [`test_calendar_google_connector.py:74`](../../../../tests/test_calendar_google_connector.py#L74)
