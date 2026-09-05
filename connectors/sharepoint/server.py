"""SharePoint connector MCP server (AD-1, AD-2): the sixth Sensor.

Exposes exactly one read-only tool, `sharepoint_get_document_status`, which
fetches a single item's metadata from Microsoft Graph
(`GET https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}`)
via `httpx` and returns it as a `RawFact`-shaped dict (AD-9) -- last-modified
metadata only, never document content.

Mirrors `google_drive.server`'s structure exactly: same validation order,
same typed-error hierarchy shape, same complete redaction discipline on
every non-2xx and malformed-body branch (not just the non-2xx branch,
unlike CMDB's Story 7 regression). `drive_id` is required in addition to
`item_id` because Graph has no vendor-agnostic "just the item" address the
way Drive's `file_id` is self-sufficient -- an item only resolves within its
containing drive.

Graph's `lastModifiedBy` is an `IdentitySet` (`{"application": {...},
"device": {...}, "user": {...}}`) -- one level deeper than Drive's flat
`lastModifyingUser` object. Flattening reaches into `lastModifiedBy.user`,
then prefers `email`, falling back to `displayName` when `email` is absent
(Graph does not reliably populate `email` for every tenant/account type) --
extending the same absent/malformed-shape handling
`calendar_google.server._flatten_organizer_field` established for a
single-level nested object.

Like the other connectors, this module never imports or calls `ledger_core`
(AD-1), never computes a confidence/staleness value (AD-5), and never
attempts to auto-correlate an artifact to a Graph item -- the caller
supplies the exact `drive_id`/`item_id`. It only ever issues `GET` requests
-- never `POST`/`PUT`/`PATCH`/`DELETE` -- against Graph (CAP-2). The
credential comes only from the `REZOPS_SHAREPOINT_TOKEN` env var (AD-7) --
a distinct credential from every other connector's, including
`REZOPS_CALENDAR_TOKEN`/`REZOPS_DRIVE_TOKEN` despite all three ultimately
being OAuth-based (AD-7's no-credential-sharing-even-same-vendor rule
applied for the third time).
"""

from __future__ import annotations

import os
import re
import urllib.parse
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from shared.ledger_schema import RawFact, SchemaValidationError

mcp = FastMCP("sharepoint")

#: `shared.ledger_schema.RawFact.source` is validated against a strict
#: charset (`^[A-Za-z0-9_:-]+$` -- see shared/ledger_schema/models.py,
#: read-only for this story) that excludes "/" and other characters a
#: `drive_id`/`item_id` could in principle contain. Mirroring the other
#: connectors' `_build_source`, the whole constructed
#: "sharepoint:<drive_id>/<item_id>" string is swept for any character
#: outside this charset and each is replaced with "_" -- producing an
#: opaque, human-readable provenance string, not a structured, parseable
#: one.
_SOURCE_UNSAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9_:-]")

#: Wall-clock budget for each HTTP request to Microsoft Graph. A hung
#: connection must not block this tool indefinitely -- same lesson every
#: prior connector's review already surfaced.
_HTTP_TIMEOUT_SECONDS = 10.0

_TOKEN_ENV_VAR = "REZOPS_SHAREPOINT_TOKEN"

#: A credential containing a control character (e.g. an embedded CR/LF) must
#: never reach `httpx`'s header-encoding machinery -- that could either
#: inject an extra header/line into the request or raise an untyped,
#: connector-specific exception that escapes this module uncaught. Rejected
#: up front, before any HTTP request is attempted, as a typed
#: `MissingCredentialsError`.
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")

_GRAPH_API_BASE_URL = "https://graph.microsoft.com/v1.0"

#: The `$select` query parameter sent with every request. Graph returns a
#: broad default field set otherwise -- requesting only what's needed
#: avoids incidentally fetching file content or unrelated metadata.
_SELECT_QUERY_PARAM = "id,lastModifiedDateTime,lastModifiedBy"

#: Top-level fields expected in a Graph drive-item metadata body, beyond
#: `lastModifiedBy` (which is optional -- an item may have no recorded
#: last-modifying identity at all). Missing any of these is treated as a
#: malformed response (typed error), never a raw `KeyError`.
_REQUIRED_ITEM_FIELDS = ("lastModifiedDateTime",)


class SharePointConnectorError(Exception):
    """Base class for every error this connector raises."""


class InvalidItemIdentifierError(SharePointConnectorError, ValueError):
    """Raised when `drive_id`/`item_id` fail input validation
    (empty/whitespace-only/non-string).

    Always raised before any HTTP request is attempted.
    """


class InvalidArtifactIdentifierError(SharePointConnectorError, ValueError):
    """Raised when `artifact_type`/`artifact_id` fail input validation
    (empty/whitespace-only/non-string).

    Always raised before any HTTP request is attempted.
    """


class MissingCredentialsError(SharePointConnectorError):
    """Raised when `REZOPS_SHAREPOINT_TOKEN` is unset, empty/whitespace-only,
    or contains a control character (e.g. an embedded CR/LF) that would be
    unsafe to place in an HTTP header.

    Always raised before any HTTP request is attempted.
    """


class DocumentNotFoundError(SharePointConnectorError):
    """Raised when Graph returns HTTP 404 for the given `drive_id`/`item_id`."""


class AuthenticationError(SharePointConnectorError):
    """Raised when Graph returns HTTP 401 or 403."""


class MalformedResponseError(SharePointConnectorError):
    """Raised when a 200 response body is not valid JSON, is not an object,
    or is missing an expected field -- never a raw `KeyError` or
    `json.JSONDecodeError`.
    """


def _require_nonempty_item_field(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InvalidItemIdentifierError(
            f"{name} must be a non-empty string; got {value!r}"
        )


def _require_nonempty_identifier(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InvalidArtifactIdentifierError(
            f"{name} must be a non-empty string; got {value!r}"
        )


def _read_credential() -> str:
    """Read and validate the bearer token from the env.

    Raises `MissingCredentialsError` -- before any HTTP request is attempted
    -- if the var is unset or empty/whitespace-only.
    """
    token = os.environ.get(_TOKEN_ENV_VAR)
    if not token or not token.strip():
        raise MissingCredentialsError(f"missing required env var: {_TOKEN_ENV_VAR}")
    if _CONTROL_CHAR_RE.search(token):
        raise MissingCredentialsError(
            f"{_TOKEN_ENV_VAR} contains a control character and cannot be "
            "used in an HTTP header"
        )
    return token


def _build_source(drive_id: str, item_id: str) -> str:
    raw_source = f"sharepoint:{drive_id}/{item_id}"
    return _SOURCE_UNSAFE_CHARS_RE.sub("_", raw_source)


def _build_client() -> httpx.Client:
    """Construct the `httpx.Client` used for every Graph request.

    Isolated behind a factory so tests can monkeypatch this to inject an
    `httpx.MockTransport`-backed client instead of a live one -- the same
    seam every other connector's factory provides.
    """
    return httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS)


def _fetch_document(token: str, drive_id: str, item_id: str) -> httpx.Response:
    """Issue the single `GET` request against Microsoft Graph.

    Translates every network-level failure (timeout, connection error, etc.)
    into a typed `SharePointConnectorError` -- never lets a raw `httpx`
    exception escape this module.

    `drive_id`/`item_id` are percent-encoded (`safe=""`) before being
    interpolated into the request path -- both have already been validated
    as non-empty strings, but neither is validated against a restrictive
    charset, so a value containing "/", "?", "#", or whitespace must not be
    allowed to alter the request path or inject extra query parameters.
    """
    encoded_drive_id = urllib.parse.quote(drive_id, safe="")
    encoded_item_id = urllib.parse.quote(item_id, safe="")
    url = f"{_GRAPH_API_BASE_URL}/drives/{encoded_drive_id}/items/{encoded_item_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    params = {"$select": _SELECT_QUERY_PARAM}

    with _build_client() as client:
        try:
            return client.get(url, headers=headers, params=params)
        except httpx.TimeoutException as exc:
            raise SharePointConnectorError(
                f"request to Microsoft Graph timed out: {drive_id}/{item_id}: {exc}"
            ) from exc
        except httpx.RequestError as exc:
            raise SharePointConnectorError(
                f"request to Microsoft Graph failed: {drive_id}/{item_id}: {exc}"
            ) from exc


def _flatten_last_modified_by_field(value: Any) -> str | None:
    """Flatten Graph's `lastModifiedBy` `IdentitySet` to a single scalar.

    Returns `None` if `lastModifiedBy` is absent from the response entirely,
    if present but has no `user` member (or that member is `null`), or if
    `user` is present but has neither `email` nor `displayName`. Prefers
    `email`, falling back to `displayName` when `email` is absent -- Graph
    does not reliably populate `email` for every tenant/account type.

    Raises `MalformedResponseError` -- never a raw `KeyError` -- if
    `lastModifiedBy` is present but is not an object, if its `user` member is
    present (non-`null`) but is not an object, or if a present `email`/
    `displayName` value is not a non-empty string (e.g. `null`) -- a `None`/
    non-string value must not silently flow through to `RawFact.fields`.

    The raised messages deliberately omit the raw object/value content --
    consistent with the non-2xx branch of `_parse_document_response`.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise MalformedResponseError("item 'lastModifiedBy' is not an object")
    if "user" not in value or value["user"] is None:
        return None
    user = value["user"]
    if not isinstance(user, dict):
        raise MalformedResponseError("item 'lastModifiedBy.user' is not an object")

    if "email" in user:
        email = user["email"]
        if not isinstance(email, str) or not email.strip():
            raise MalformedResponseError(
                "item 'lastModifiedBy.user' has a non-string or empty "
                "'email' value"
            )
        return email.strip()

    if "displayName" in user:
        display_name = user["displayName"]
        if not isinstance(display_name, str) or not display_name.strip():
            raise MalformedResponseError(
                "item 'lastModifiedBy.user' has a non-string or empty "
                "'displayName' value"
            )
        return display_name.strip()

    return None


def _parse_document_response(
    response: httpx.Response, drive_id: str, item_id: str
) -> dict[str, Any]:
    """Map a Graph HTTP response to the raw `fields` mapping for a `RawFact`.

    Raises `DocumentNotFoundError` (404), `AuthenticationError` (401/403),
    `SharePointConnectorError` (any other non-2xx), or
    `MalformedResponseError` (invalid JSON, non-object body, or missing an
    expected field) -- never a raw `KeyError`/`json.JSONDecodeError`.
    """
    if response.status_code == 404:
        raise DocumentNotFoundError(f"no item found for {drive_id}/{item_id}")
    if response.status_code in (401, 403):
        raise AuthenticationError(
            f"authentication failed for Microsoft Graph (HTTP {response.status_code})"
        )
    if not response.is_success:
        # The response body is deliberately omitted -- it may contain real
        # item metadata that must not leak into logs, error channels, or an
        # agent transcript via this exception's message.
        raise SharePointConnectorError(
            f"Microsoft Graph returned HTTP {response.status_code} for "
            f"{drive_id}/{item_id} (response body omitted)"
        )

    try:
        body = response.json()
    except ValueError as exc:  # httpx surfaces json.JSONDecodeError, a ValueError
        raise MalformedResponseError(
            f"Microsoft Graph response body for {drive_id}/{item_id} is not "
            f"valid JSON: {exc}"
        ) from exc

    if not isinstance(body, dict):
        # The raw body is deliberately omitted from the message -- same
        # reasoning as the non-2xx branch above: it may contain real item
        # metadata that must not leak into an exception message.
        raise MalformedResponseError(
            f"Microsoft Graph response for {drive_id}/{item_id} is not an "
            "object (response body omitted)"
        )

    # A required field whose value is `None` is treated the same as an
    # absent key -- a `null` `lastModifiedDateTime`, for example, is just as
    # unusable as a missing `lastModifiedDateTime` and must not silently
    # produce a `RawFact` with a `None` field value.
    missing_fields = [
        key
        for key in _REQUIRED_ITEM_FIELDS
        if key not in body or body[key] is None
    ]
    if missing_fields:
        # The raw body is deliberately omitted -- same reasoning as the
        # non-2xx branch above.
        raise MalformedResponseError(
            f"Microsoft Graph item {drive_id}/{item_id} is missing expected "
            f"field(s) {missing_fields!r} (response body omitted)"
        )

    modified_time = body["lastModifiedDateTime"]
    if not isinstance(modified_time, str) or not modified_time.strip():
        raise MalformedResponseError(
            f"Microsoft Graph item {drive_id}/{item_id} has a non-string or "
            "empty 'lastModifiedDateTime' value (response body omitted)"
        )

    fields: dict[str, Any] = {
        "modified_time": modified_time.strip(),
        "last_modified_by": _flatten_last_modified_by_field(
            body.get("lastModifiedBy")
        ),
    }
    return fields


@mcp.tool(name="sharepoint_get_document_status")
def sharepoint_get_document_status(
    drive_id: str, item_id: str, artifact_type: str, artifact_id: str
) -> dict[str, Any]:
    """Return a RawFact-shaped dict for one Microsoft Graph drive item's
    metadata.

    Read-only: issues exactly one `GET https://graph.microsoft.com/v1.0/
    drives/{drive_id}/items/{item_id}?$select=id,lastModifiedDateTime,
    lastModifiedBy` request via `httpx`, never a `POST`/`PUT`/`PATCH`/
    `DELETE` (CAP-2). `drive_id`/`item_id` are percent-encoded before being
    placed in the request path. `drive_id`/`item_id`/`artifact_type`/
    `artifact_id` are validated as non-empty strings (rejecting non-string
    input, e.g. an int, with the same typed error as an empty one) before
    anything else runs, and the credential is read from
    `REZOPS_SHAREPOINT_TOKEN` and checked before any HTTP request is
    attempted.

    Only item *metadata* is ever fetched or returned -- never document
    content. Graph's nested `lastModifiedBy` `IdentitySet` is flattened to a
    scalar before ever reaching `RawFact`: to `lastModifiedBy.user.email`,
    falling back to `lastModifiedBy.user.displayName` when `email` is absent
    (or `None` if neither is present, or `lastModifiedBy` is absent entirely)
    -- `RawFact.fields` cannot hold a nested object (AD-9).

    Raises a typed error -- never lets a raw `httpx`/`KeyError`/
    `json.JSONDecodeError` exception escape -- for every failure case in the
    I/O matrix: `InvalidItemIdentifierError` for empty/whitespace-only/
    non-string `drive_id`/`item_id`, `InvalidArtifactIdentifierError` for
    empty/whitespace-only/non-string `artifact_type`/`artifact_id`,
    `MissingCredentialsError` when `REZOPS_SHAREPOINT_TOKEN` is unset, blank,
    or contains a control character, `DocumentNotFoundError` on HTTP 404,
    `AuthenticationError` on HTTP 401/403, `MalformedResponseError` for a 200
    body missing `lastModifiedDateTime` (a `null` value counts as missing),
    that isn't valid JSON, that isn't an object, or whose
    `lastModifiedBy`/`lastModifiedBy.user` is malformed, and
    `SharePointConnectorError` for any other HTTP failure or network/timeout
    error.

    Computes no confidence or staleness value -- that is ledger-core's job
    (AD-5), not a connector's. Performs no auto-correlation of `artifact_id`
    to a Graph item -- the caller supplies the exact `drive_id`/`item_id`.
    """
    _require_nonempty_item_field("drive_id", drive_id)
    _require_nonempty_item_field("item_id", item_id)
    _require_nonempty_identifier("artifact_type", artifact_type)
    _require_nonempty_identifier("artifact_id", artifact_id)

    token = _read_credential()

    response = _fetch_document(token, drive_id, item_id)
    fields = _parse_document_response(response, drive_id, item_id)

    try:
        fact = RawFact(
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            source=_build_source(drive_id, item_id),
            fields=fields,
        )
    except SchemaValidationError as exc:
        raise MalformedResponseError(
            f"Microsoft Graph item {drive_id}/{item_id} could not be "
            f"represented as a RawFact (likely a non-scalar field value): {exc}"
        ) from exc

    return {
        "artifact_type": fact.artifact_type,
        "artifact_id": fact.artifact_id,
        "source": fact.source,
        "fields": dict(fact.fields),
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
