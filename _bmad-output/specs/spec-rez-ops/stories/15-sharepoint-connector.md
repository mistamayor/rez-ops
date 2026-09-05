---
title: 'SharePoint connector'
type: 'feature'
created: '2026-09-05'
status: 'done'
review_loop_iteration: 0
baseline_commit: '2846d40d2544667b1312993288873809ff7db930'
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/specs/spec-rez-ops/SPEC.md'
  - '{project-root}/connectors/google_drive/server.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** SPEC CAP-2's document-store coverage (widened for Story 14) still lacks Microsoft's document store: BIAs/RACI/tiering docs held in SharePoint/OneDrive are invisible to Rez Ops, just as Drive files were before Story 14.

**Approach:** Add a sixth Sensor, `sharepoint_get_document_status(drive_id, item_id, artifact_type, artifact_id)`, fetching one item's metadata from Microsoft Graph (`GET /v1.0/drives/{drive_id}/items/{item_id}?$select=id,lastModifiedDateTime,lastModifiedBy`) and returning it as a `RawFact`-shaped dict -- last-modified metadata only, never content. Mirrors `google_drive_get_document_status`'s shape exactly (itself mirroring Calendar): same validation order, same typed-error hierarchy, same complete redaction discipline on every branch. `drive_id` is required because Graph has no vendor-agnostic "just the item" address the way Drive's `file_id` is self-sufficient -- an item only resolves within its containing drive. Credential is `REZOPS_SHAREPOINT_TOKEN`, a Microsoft Graph bearer token -- the first non-Google, non-ServiceNow credential in this project.

## Boundaries & Constraints

**Always:**
- Read-only: issues exactly one `GET`; never `POST`/`PUT`/`PATCH`/`DELETE` against Graph (CAP-2).
- `drive_id`/`item_id`/`artifact_type`/`artifact_id` validated as non-empty strings before any HTTP request; credential validated (present, non-blank, no control character) before any HTTP request.
- `$select=id,lastModifiedDateTime,lastModifiedBy` sent on every request -- Graph returns a broad default field set otherwise, and requesting only what's needed avoids incidentally fetching file content or unrelated metadata.
- Graph's `lastModifiedBy` is an `IdentitySet` one level deeper than Drive's `lastModifyingUser` (`lastModifiedBy.user.email`, falling back to `lastModifiedBy.user.displayName` when `email` is absent -- Graph does not always populate `email`). Flattened to a single scalar before ever reaching `RawFact`, mirroring `_flatten_last_modifying_user_field`'s absent/malformed-shape handling.
- Every non-2xx response and every malformed-200-body error path omits the raw response body from its exception message -- complete redaction on every branch, not just non-2xx (the CMDB Story 7 regression, guarded against again here).
- Both `.mcp.json` (register `sharepoint` -> `connectors.sharepoint.server`) and `tests/test_mcp_config.py` (`_EXPECTED_SERVERS`, seven-server test name) are updated in this same implementation pass -- Story 14 deferred this to a fix round; it must not happen again.
- Credential comes only from `REZOPS_SHAREPOINT_TOKEN` (AD-7) -- independent from every other connector's credential, including `REZOPS_CALENDAR_TOKEN`/`REZOPS_DRIVE_TOKEN` despite all three ultimately being OAuth-based.

**Ask First:**
- Any dependency beyond what's already direct (httpx, mcp).

**Never:**
- No auto-correlation of `artifact_id` to a Graph item -- the caller supplies the exact `drive_id`/`item_id`.
- No fetching or exposing file content, only metadata.
- Computes no confidence/staleness value -- that's ledger-core's job (AD-5).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path | Valid `drive_id`/`item_id`, credentials set | `RawFact`-shaped dict with `modified_time`, `last_modified_by` | N/A |
| Item has no `lastModifiedBy` | Field absent from response | `last_modified_by: None` | N/A |
| `lastModifiedBy.user` present with no `email` or `displayName` | Both keys absent | `last_modified_by: None` | N/A |
| Empty/whitespace/non-string `drive_id` or `item_id` | `""`, `"  "`, or e.g. an int | Rejected before any HTTP request | Raises a typed validation error |
| Empty/whitespace/non-string `artifact_type`/`artifact_id` | Same | Rejected before any HTTP request | Raises a typed validation error |
| Missing/blank/control-char credential | `REZOPS_SHAREPOINT_TOKEN` unset, blank, or contains a control character | Rejected before any HTTP request | Raises a typed validation error |
| Item not found | HTTP 404 | -- | Raises a typed not-found error |
| Auth failure | HTTP 401/403 | -- | Raises a typed authentication error |
| Other non-2xx | Any other non-success status | -- | Raises a typed connector error; response body never appears in the message |
| Malformed 200 body | Not valid JSON, not an object, missing `lastModifiedDateTime`, or it is `null`/non-string | -- | Raises a typed malformed-response error; response body never appears in the message |
| `lastModifiedBy`/`user` present but malformed | Not an object, or `email`/`displayName` non-string when present | -- | Raises a typed malformed-response error; response body never appears in the message |

</frozen-after-approval>

## Code Map

- `connectors/google_drive/server.py` -- reuse as the near-exact template: `_require_nonempty_*`, `_read_credential`/`_CONTROL_CHAR_RE`, `_build_source`/`_SOURCE_UNSAFE_CHARS_RE`, `_build_client` factory seam, the typed-error hierarchy shape, and -- critically -- every redaction point across both the non-2xx branch and every malformed-body branch
- `connectors/calendar_google/server.py` -- secondary reference: `_flatten_organizer_field`'s absent/malformed-shape handling, the precedent this story's one-level-deeper `lastModifiedBy.user` flattening extends
- `connectors/cmdb/server.py` -- cautionary reference only: Story 7's regression carried redaction forward for only the non-2xx branch, not malformed-body -- don't repeat
- `connectors/git_repo/server.py` -- reuse: `_build_source`'s sanitization approach (shared precedent across every connector)
- `connectors/sharepoint/server.py` -- new: `sharepoint_get_document_status` MCP server
- `tests/test_sharepoint_connector.py` -- new: unit tests for every I/O matrix row, `httpx.MockTransport`-backed, mirroring `tests/test_google_drive_connector.py`'s shape
- `.mcp.json` -- register the `sharepoint` server entry (same shape as the other five: `{"command": "uv", "args": ["run", "python", "-m", "connectors.sharepoint.server"]}`) in this pass, not a later fix round
- `tests/test_mcp_config.py` -- add `sharepoint` to `_EXPECTED_SERVERS`, rename the six-server test to expect seven
- `README.md` -- add `REZOPS_SHAREPOINT_TOKEN` row, the new tool row, bump sensor/tool/server/test counts, add `sharepoint/` to the project layout tree

## Tasks & Acceptance

**Execution:**
- [x] `connectors/sharepoint/server.py` -- implement `sharepoint_get_document_status(drive_id, item_id, artifact_type, artifact_id)`, mirroring `google_drive_get_document_status`'s structure exactly (validation order, credential check, typed errors, redaction discipline on every branch) -- CAP-2
- [x] `tests/test_sharepoint_connector.py` -- unit tests for every I/O matrix row, plus a redaction-specific test proving a planted sensitive value in a malformed 200 body never appears in any raised exception's message
- [x] `.mcp.json` + `tests/test_mcp_config.py` -- register `sharepoint` and update the expected-server-count test in this same pass
- [x] `README.md` -- update credentials table, tool table, project layout tree, and every sensor/tool/server/test count

**Acceptance Criteria:**
- Given the full test suite, when `uv run pytest` runs, then all tests pass.
- Given a 200 response missing `lastModifiedDateTime`, when the tool is called, then a typed `MalformedResponseError`-equivalent is raised and the raw response body never appears in its message.
- Given the ledger-core-independent connector server, when a client lists its tools, then exactly one tool, `sharepoint_get_document_status`, is exposed, and it never calls any write API.
- Given `.mcp.json`, when `tests/test_mcp_config.py` runs, then it lists exactly seven servers including `sharepoint`.

## Spec Change Log

## Design Notes

Graph's `lastModifiedBy` is an `IdentitySet` (`{"application": {...}, "device": {...}, "user": {...}}`), not a flat object like Drive's `lastModifyingUser` -- flattening must reach one level deeper, into `lastModifiedBy.user`, then prefer `email` and fall back to `displayName` (Graph does not reliably populate `email` for every tenant/account type). `REZOPS_SHAREPOINT_TOKEN` is a distinct env var from every other connector's credential even though it is, like Calendar/Drive, ultimately an OAuth bearer token -- AD-7's no-credential-sharing-even-same-vendor rule applied for the third time.

## Verification

**Commands:**
- `uv sync` -- expected: resolves without error -- ran, resolved with no changes
- `uv run pytest -v` -- expected: all tests pass, including every prior story's -- ran, 658 passed (89 for this story, including the fix-round test)
- `uv run python -c "import connectors.sharepoint.server"` -- expected: imports without error -- ran, imported cleanly
- `.mcp.json` -- expected: 7 servers registered including `sharepoint` -- confirmed independently

Adversarial review ran (3 lenses: blind-hunter, edge-case-hunter, verification-gap) against the diff since baseline. One finding patched, independently re-verified (not just self-reported):
1. No test proved `_flatten_last_modified_by_field` actually prefers `email` over `displayName` when both are present -- confirmed via mutation (inverting the precedence still passed all 88 pre-fix tests). Added `test_last_modified_by_prefers_email_over_display_name_when_both_present`.

Two cross-cutting, pre-existing issues surfaced incidentally (present verbatim in 3-4 already-shipped connectors, not introduced by this story) were logged to `deferred-work.md` rather than patched locally: `_build_source`'s join-then-sanitize is non-injective across multi-identifier connectors (ticketing, cmdb, calendar_google, sharepoint); `_read_credential` never strips the token before use (google_drive, calendar_google, ticketing, cmdb, sharepoint).

## Suggested Review Order

**Connector implementation**

- Entry point: validation order, credential check, single `GET`, error mapping into a `RawFact`-shaped dict.
  [`server.py:342`](../../../../connectors/sharepoint/server.py#L342)

- The interesting design decision: flattening Graph's two-level `IdentitySet`, preferring `email` and falling back to `displayName`.
  [`server.py:217`](../../../../connectors/sharepoint/server.py#L217)

- Response parsing and the complete redaction discipline across every non-2xx and malformed-body branch.
  [`server.py:266`](../../../../connectors/sharepoint/server.py#L266)

**Tests**

- The fix-round test: proves `email` wins over `displayName` when both are present -- the one real gap review found.
  [`test_sharepoint_connector.py:164`](../../../../tests/test_sharepoint_connector.py#L164)

- Redaction-specific test: a planted sensitive value in a malformed `lastModifiedBy.user` body never leaks into the exception message.
  [`test_sharepoint_connector.py:816`](../../../../tests/test_sharepoint_connector.py#L816)

- Path-injection guard: `drive_id`/`item_id` containing `/`, `?`, or whitespace can't alter the request path or inject query params.
  [`test_sharepoint_connector.py:556`](../../../../tests/test_sharepoint_connector.py#L556)

**Config and docs**

- Registration landed in the same pass as the connector, not a later fix round (Story 14's own review finding, guarded against here).
  [`.mcp.json:26`](../../../../.mcp.json#L26)

- The expected-server-count test now expects seven, including `sharepoint`.
  [`test_mcp_config.py:29`](../../../../tests/test_mcp_config.py#L29)

- Credentials table, tool table, and every sensor/tool/server/test count updated for the sixth connector.
  [`README.md:63`](../../../../README.md#L63)
