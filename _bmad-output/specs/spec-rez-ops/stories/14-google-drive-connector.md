---
title: 'Google Drive connector'
type: 'feature'
created: '2026-09-05'
status: 'done'
review_loop_iteration: 1
baseline_commit: '5e3bec70377fa46a4f56ed5dcb816016277def23'
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/specs/spec-rez-ops/SPEC.md'
  - '{project-root}/connectors/calendar_google/server.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Rez Ops's four connectors (git, ticketing, calendar, CMDB) can't observe a DR artifact that lives as a document — a BIA, a RACI matrix, a tiering sheet — stored in Google Drive rather than in any of those four systems. SPEC CAP-2 has no document-store connector.

**Approach:** Add a fifth Sensor, `google_drive_get_document_status`, fetching one file's metadata from the Google Drive API v3 (`GET /drive/v3/files/{fileId}`) and returning it as a `RawFact`-shaped dict — last-modified metadata only (`modifiedTime`, `lastModifyingUser` flattened to a scalar email), never content. Mirrors `calendar_get_event_status`'s shape exactly: same validation order, same typed-error hierarchy, same flatten-nested-objects-to-scalars discipline for `lastModifyingUser` (an object, like Calendar's `organizer`). Credential is `REZOPS_DRIVE_TOKEN` — separate from `REZOPS_CALENDAR_TOKEN` despite both being Google OAuth tokens (AD-7: no credential sharing between connectors, even the same vendor).

## Boundaries & Constraints

**Always:**
- Read-only: issues exactly one `GET` request; never `POST`/`PUT`/`PATCH`/`DELETE` against the Drive API (CAP-2).
- `file_id`/`artifact_type`/`artifact_id` validated as non-empty strings before any HTTP request; credential validated (present, non-blank, no control character) before any HTTP request.
- The request's `fields` query parameter explicitly lists only the fields this connector needs (`id, modifiedTime, lastModifyingUser`) — Drive's API returns a minimal default field set otherwise, and requesting only what's needed avoids incidentally fetching document content or unrelated metadata.
- `lastModifyingUser` (an object) is flattened to its `emailAddress` scalar before ever reaching `RawFact`, mirroring `calendar_get_event_status`'s `_flatten_organizer_field` exactly — absent-organizer and non-string/null-email cases both already have a proven, correct precedent to copy.
- Every non-2xx response and every malformed-200-body error path omits the raw response body from its exception message — mirroring `calendar_get_event_status`'s complete redaction discipline (every branch, not just one) rather than CMDB's Story 7 regression, which initially carried forward redaction for only the non-2xx branch and missed the malformed-body branches.
- Credential comes only from `REZOPS_DRIVE_TOKEN` (AD-7) — never a config file, never shared with `REZOPS_CALENDAR_TOKEN` even though both are Google OAuth.

**Ask First:**
- Any dependency beyond what's already direct.

**Never:**
- No auto-correlation of `artifact_id` to a Drive file — the caller supplies the exact `file_id`.
- No fetching or exposing document content, only metadata.
- Computes no confidence/staleness value — that's ledger-core's job (AD-5).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path | Valid `file_id`, credentials set | `RawFact`-shaped dict with `modified_time`, `last_modified_by` | N/A |
| File has no `lastModifyingUser` | Field absent from response | `last_modified_by: None` | N/A |
| Empty/whitespace/non-string `file_id` | `""`, `"  "`, or e.g. an int | Rejected before any HTTP request | Raises a typed validation error |
| Empty/whitespace/non-string `artifact_type`/`artifact_id` | Same | Rejected before any HTTP request | Raises a typed validation error |
| Missing/blank/control-char credential | `REZOPS_DRIVE_TOKEN` unset, blank, or contains a control character | Rejected before any HTTP request | Raises a typed validation error |
| File not found | HTTP 404 | — | Raises a typed not-found error |
| Auth failure | HTTP 401/403 | — | Raises a typed authentication error |
| Other non-2xx | Any other non-success status | — | Raises a typed connector error; response body never appears in the message |
| Malformed 200 body | Not valid JSON, not an object, missing `modifiedTime`, or `modifiedTime` is `null`/non-string | — | Raises a typed malformed-response error; response body never appears in the message |
| `lastModifyingUser` present but malformed | Not an object, or `emailAddress` is `null`/non-string | — | Raises a typed malformed-response error; response body never appears in the message |

</frozen-after-approval>

## Code Map

- `connectors/calendar_google/server.py` -- reuse as the exact template: `_require_nonempty_*`, `_read_credential`/`_CONTROL_CHAR_RE`, `_build_source`/`_SOURCE_UNSAFE_CHARS_RE`, `_build_client`, the typed-error hierarchy shape, `_flatten_organizer_field`'s pattern (for `lastModifyingUser`), and — critically — every redaction point in `_parse_event_response` (both the non-2xx branch and every malformed-body branch)
- `connectors/cmdb/server.py` -- reuse as a cautionary reference only: Story 7's review found redaction had been carried forward for the non-2xx branch but not the malformed-200-body branches; don't repeat that split
- `connectors/git_repo/server.py` -- reuse as pattern: `_build_source`'s sanitization approach (shared precedent across every connector)
- `connectors/google_drive/server.py` -- new: `google_drive_get_document_status` MCP server
- `tests/test_google_drive_connector.py` -- new: unit tests for every I/O matrix row, `httpx.MockTransport`-backed

## Tasks & Acceptance

**Execution:**
- [x] `connectors/google_drive/server.py` -- implemented `google_drive_get_document_status(file_id, artifact_type, artifact_id)`, mirroring `calendar_get_event_status`'s structure exactly (validation order, credential check, typed errors, redaction discipline on every branch) -- CAP-2
- [x] `tests/test_google_drive_connector.py` -- unit tests for every I/O matrix row, plus a redaction-specific test proving a planted sensitive value in a malformed 200 body never appears in any raised exception's message (matching the exact test shape that caught CMDB's Story 7 regression)

**Acceptance Criteria:**
- Given the full test suite, when `uv run pytest` runs, then all tests pass.
- Given a 200 response missing `modifiedTime`, when the tool is called, then a typed `MalformedResponseError`-equivalent is raised and the raw response body never appears in its message.
- Given the ledger-core-independent connector server, when a client lists its tools, then exactly one tool, `google_drive_get_document_status`, is exposed, and it never calls any write API.

## Spec Change Log

## Design Notes

`REZOPS_DRIVE_TOKEN` is a distinct env var from `REZOPS_CALENDAR_TOKEN` even though both connectors authenticate against Google OAuth — this mirrors CMDB's own precedent of a separate credential from ticketing despite sharing a ServiceNow tenant (AD-7's no-credential-sharing-even-same-vendor rule applies uniformly, not just across different vendors).

## Verification

**Commands:**
- `uv sync` -- expected: resolves without error -- ran, resolved with no changes
- `uv run pytest -v` -- expected: all tests pass, including every prior story's -- ran, 569 passed
- `uv run python -c "import connectors.google_drive.server"` -- expected: imports without error -- ran, imported cleanly
- `.mcp.json` -- expected: 6 servers registered including `google-drive` -- confirmed independently

Adversarial review ran (3 lenses). Findings triaged: 4 patched, remainder deferred to `deferred-work.md`. Patches applied and independently re-verified (not just self-reported by the fixing agent):
1. `google-drive` was missing from `.mcp.json` entirely -- a connector shipping unregistered from the real product. Registered; `tests/test_mcp_config.py` updated to expect six servers.
2. Missing `supportsAllDrives=true` -- a `file_id` living in a Shared Drive would 404. Added to the request params, asserted in a test.
3. `modified_time`/`last_modified_by` were stored unstripped -- inconsistent with every other connector's normalization. Now `.strip()`-ed before reaching `RawFact`.
4. README left at "four sensors" / stale tool and test counts. Updated throughout.

## Suggested Review Order

1. `connectors/google_drive/server.py` -- the connector itself; compare against `connectors/calendar_google/server.py` to confirm the mirrored structure and redaction discipline actually hold
2. `tests/test_google_drive_connector.py` -- every I/O matrix row, plus the redaction-specific and `supportsAllDrives`/stripped-value regression tests
3. `.mcp.json` + `tests/test_mcp_config.py` -- registration and the six-server contract test
4. `README.md` -- credentials table, tool table, project layout, counts
