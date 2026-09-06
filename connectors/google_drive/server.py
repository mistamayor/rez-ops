"""Google Drive connector MCP server (AD-1, AD-2): the fifth Sensor.

Exposes exactly one read-only tool, `google_drive_get_document_status`, which
fetches a single file's metadata from the Google Drive API v3
(`GET https://www.googleapis.com/drive/v3/files/{fileId}`, with
`supportsAllDrives=true` so a file living in a Shared Drive resolves
correctly) via `httpx` and returns it as a `RawFact`-shaped dict (AD-9) --
last-modified metadata only, never document content.

Mirrors `calendar_google.server`'s structure exactly: same validation order,
same typed-error hierarchy shape, same flatten-nested-objects-to-scalars
discipline (here for `lastModifyingUser`, an object -- like Calendar's
`organizer`), and the same complete redaction discipline on every non-2xx and
malformed-body branch (not just the non-2xx branch, unlike CMDB's Story 7
regression). Like the other connectors, this module never imports or calls
`ledger_core` (AD-1), never computes a confidence/staleness value (AD-5), and
never attempts to auto-correlate an artifact to a Drive file -- the caller
supplies the exact `file_id`. It only ever issues `GET` requests -- never
`POST`/`PUT`/`PATCH`/`DELETE` -- against the Drive API (CAP-2). The
credential comes only from the `REZOPS_DRIVE_TOKEN` env var (AD-7) -- a
distinct credential from `REZOPS_CALENDAR_TOKEN` even though both connectors
authenticate against Google OAuth (AD-7's no-credential-sharing-even-same-
vendor rule).
"""

from __future__ import annotations

import os
import re
import urllib.parse
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from shared.ledger_schema import RawFact, SchemaValidationError

mcp = FastMCP("google-drive")

#: `shared.ledger_schema.RawFact.source` is validated against a strict
#: charset (`^[A-Za-z0-9_:-]+$` -- see shared/ledger_schema/models.py,
#: read-only for this story) that excludes "/" and other characters a Drive
#: `file_id` could in principle contain. Mirroring the other connectors'
#: `_build_source`, the whole constructed "google-drive:<file_id>" string is
#: swept for any character outside this charset and each is replaced with
#: "_" -- producing an opaque, human-readable provenance string, not a
#: structured, parseable one.
_SOURCE_UNSAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9_:-]")

#: Wall-clock budget for each HTTP request to the Drive API. A hung
#: connection must not block this tool indefinitely -- same lesson every
#: prior connector's review already surfaced.
_HTTP_TIMEOUT_SECONDS = 10.0

_TOKEN_ENV_VAR = "REZOPS_DRIVE_TOKEN"

#: A credential containing a control character (e.g. an embedded CR/LF) must
#: never reach `httpx`'s header-encoding machinery -- that could either
#: inject an extra header/line into the request or raise an untyped,
#: connector-specific exception that escapes this module uncaught. Rejected
#: up front, before any HTTP request is attempted, as a typed
#: `MissingCredentialsError`.
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")

_DRIVE_API_BASE_URL = "https://www.googleapis.com/drive/v3"

#: The `fields` query parameter sent with every request. Drive's API returns
#: only a minimal default field set otherwise -- explicitly listing exactly
#: the fields this connector needs avoids incidentally fetching document
#: content or unrelated metadata.
_FIELDS_QUERY_PARAM = "id,modifiedTime,lastModifyingUser"

#: Without `supportsAllDrives=true`, a `file_id` that lives in a Google
#: Shared Drive (the realistic common case for a team-owned DR document, not
#: an edge case) 404s even though the credential legitimately has access to
#: it -- the Drive API v3 defaults every request to "My Drive" only unless a
#: request opts in to Shared Drive support.
_SUPPORTS_ALL_DRIVES = "true"

#: Top-level fields expected in a Google Drive API v3 file metadata body,
#: beyond `lastModifyingUser` (which is optional -- a file may have no
#: recorded last-modifying user at all). Missing any of these is treated as
#: a malformed response (typed error), never a raw `KeyError`.
_REQUIRED_FILE_FIELDS = ("modifiedTime",)


class GoogleDriveConnectorError(Exception):
    """Base class for every error this connector raises."""


class InvalidFileIdentifierError(GoogleDriveConnectorError, ValueError):
    """Raised when `file_id` fails input validation (empty/whitespace-only/
    non-string).

    Always raised before any HTTP request is attempted.
    """


class InvalidArtifactIdentifierError(GoogleDriveConnectorError, ValueError):
    """Raised when `artifact_type`/`artifact_id` fail input validation
    (empty/whitespace-only/non-string).

    Always raised before any HTTP request is attempted.
    """


class MissingCredentialsError(GoogleDriveConnectorError):
    """Raised when `REZOPS_DRIVE_TOKEN` is unset, empty/whitespace-only,
    contains a control character (e.g. an embedded CR/LF), or contains a
    non-ASCII character -- any of which would be unsafe to place in an HTTP
    header.

    Always raised before any HTTP request is attempted.
    """


class DocumentNotFoundError(GoogleDriveConnectorError):
    """Raised when the Drive API returns HTTP 404 for the given `file_id`."""


class AuthenticationError(GoogleDriveConnectorError):
    """Raised when the Drive API returns HTTP 401 or 403."""


class MalformedResponseError(GoogleDriveConnectorError):
    """Raised when a 200 response body is not valid JSON, is not an object,
    or is missing an expected field -- never a raw `KeyError` or
    `json.JSONDecodeError`.
    """


def _require_nonempty_file_field(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InvalidFileIdentifierError(
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
    -- if the var is unset or empty/whitespace-only, contains a control
    character, or contains a non-ASCII character. The returned token is
    stripped of incidental leading/trailing whitespace -- never sent to
    Google Drive padded.
    """
    token = os.environ.get(_TOKEN_ENV_VAR)
    if not token or not token.strip():
        raise MissingCredentialsError(f"missing required env var: {_TOKEN_ENV_VAR}")
    if _CONTROL_CHAR_RE.search(token):
        raise MissingCredentialsError(
            f"{_TOKEN_ENV_VAR} contains a control character and cannot be "
            "used in an HTTP header"
        )
    if not token.isascii():
        raise MissingCredentialsError(
            f"{_TOKEN_ENV_VAR} must contain only ASCII characters"
        )
    return token.strip()


def _build_source(file_id: str) -> str:
    safe_file_id = _SOURCE_UNSAFE_CHARS_RE.sub("_", file_id)
    return f"google-drive:{safe_file_id}"


def _build_client() -> httpx.Client:
    """Construct the `httpx.Client` used for every Drive API request.

    Isolated behind a factory so tests can monkeypatch this to inject an
    `httpx.MockTransport`-backed client instead of a live one -- the same
    seam every other connector's factory provides.
    """
    return httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS)


def _fetch_document(token: str, file_id: str) -> httpx.Response:
    """Issue the single `GET` request against the Drive API.

    Translates every network-level failure (timeout, connection error, etc.)
    into a typed `GoogleDriveConnectorError` -- never lets a raw `httpx`
    exception escape this module.

    `file_id` is percent-encoded (`safe=""`) before being interpolated into
    the request path -- it has already been validated as a non-empty string,
    but not against a restrictive charset, so a value containing "/", "?",
    "#", or whitespace must not be allowed to alter the request path or
    inject extra query parameters.
    """
    encoded_file_id = urllib.parse.quote(file_id, safe="")
    url = f"{_DRIVE_API_BASE_URL}/files/{encoded_file_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    params = {
        "fields": _FIELDS_QUERY_PARAM,
        "supportsAllDrives": _SUPPORTS_ALL_DRIVES,
    }

    with _build_client() as client:
        try:
            return client.get(url, headers=headers, params=params)
        except httpx.TimeoutException as exc:
            raise GoogleDriveConnectorError(
                f"request to Google Drive timed out: {file_id}: {exc}"
            ) from exc
        except httpx.RequestError as exc:
            raise GoogleDriveConnectorError(
                f"request to Google Drive failed: {file_id}: {exc}"
            ) from exc


def _flatten_last_modifying_user_field(value: Any) -> str | None:
    """Flatten a Google Drive `lastModifyingUser` object to its
    `emailAddress` scalar.

    Returns `None` if `lastModifyingUser` is absent from the response
    entirely, or if present but with no `emailAddress` key. Raises
    `MalformedResponseError` if `lastModifyingUser` is present but is not an
    object, or if its `emailAddress` key is present but its value is not a
    non-empty string (e.g. `null`) -- a `None`/non-string `emailAddress` must
    not silently flow through to `RawFact.fields`.

    The raised messages deliberately omit the raw object/value content --
    consistent with the non-2xx branch of `_parse_document_response`.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise MalformedResponseError("file 'lastModifyingUser' is not an object")
    if "emailAddress" not in value:
        return None
    email = value["emailAddress"]
    if not isinstance(email, str) or not email.strip():
        raise MalformedResponseError(
            "file 'lastModifyingUser' has a non-string or empty 'emailAddress' value"
        )
    return email.strip()


def _parse_document_response(response: httpx.Response, file_id: str) -> dict[str, Any]:
    """Map a Drive API HTTP response to the raw `fields` mapping for a
    `RawFact`.

    Raises `DocumentNotFoundError` (404), `AuthenticationError` (401/403),
    `GoogleDriveConnectorError` (any other non-2xx), or
    `MalformedResponseError` (invalid JSON, non-object body, or missing an
    expected field) -- never a raw `KeyError`/`json.JSONDecodeError`.
    """
    if response.status_code == 404:
        raise DocumentNotFoundError(f"no file found for {file_id}")
    if response.status_code in (401, 403):
        raise AuthenticationError(
            f"authentication failed for Google Drive (HTTP {response.status_code})"
        )
    if not response.is_success:
        # The response body is deliberately omitted -- it may contain real
        # file metadata that must not leak into logs, error channels, or an
        # agent transcript via this exception's message.
        raise GoogleDriveConnectorError(
            f"Google Drive returned HTTP {response.status_code} for "
            f"{file_id} (response body omitted)"
        )

    try:
        body = response.json()
    except ValueError as exc:  # httpx surfaces json.JSONDecodeError, a ValueError
        raise MalformedResponseError(
            f"Google Drive response body for {file_id} is not valid JSON: {exc}"
        ) from exc

    if not isinstance(body, dict):
        # The raw body is deliberately omitted from the message -- same
        # reasoning as the non-2xx branch above: it may contain real file
        # metadata that must not leak into an exception message.
        raise MalformedResponseError(
            f"Google Drive response for {file_id} is not an object "
            "(response body omitted)"
        )

    # A required field whose value is `None` is treated the same as an
    # absent key -- a `null` `modifiedTime`, for example, is just as unusable
    # as a missing `modifiedTime` and must not silently produce a `RawFact`
    # with a `None` field value.
    missing_fields = [
        key
        for key in _REQUIRED_FILE_FIELDS
        if key not in body or body[key] is None
    ]
    if missing_fields:
        # The raw body is deliberately omitted -- same reasoning as the
        # non-2xx branch above.
        raise MalformedResponseError(
            f"Google Drive file {file_id} is missing expected field(s) "
            f"{missing_fields!r} (response body omitted)"
        )

    modified_time = body["modifiedTime"]
    if not isinstance(modified_time, str) or not modified_time.strip():
        raise MalformedResponseError(
            f"Google Drive file {file_id} has a non-string or empty "
            "'modifiedTime' value (response body omitted)"
        )

    fields: dict[str, Any] = {
        "modified_time": modified_time.strip(),
        "last_modified_by": _flatten_last_modifying_user_field(
            body.get("lastModifyingUser")
        ),
    }
    return fields


@mcp.tool(name="google_drive_get_document_status")
def google_drive_get_document_status(
    file_id: str, artifact_type: str, artifact_id: str
) -> dict[str, Any]:
    """Return a RawFact-shaped dict for one Google Drive API v3 file's
    metadata.

    Read-only: issues exactly one `GET https://www.googleapis.com/drive/v3/
    files/{file_id}?fields=id,modifiedTime,lastModifyingUser&supportsAllDrives=true`
    request via `httpx`, never a `POST`/`PUT`/`PATCH`/`DELETE` (CAP-2).
    `supportsAllDrives=true` is always sent so a `file_id` living in a
    Google Shared Drive resolves correctly instead of 404ing. `file_id` is
    percent-encoded before being placed in the request path. `file_id`/
    `artifact_type`/`artifact_id` are validated as non-empty strings
    (rejecting non-string input, e.g. an int, with the same typed error as
    an empty one) before anything else runs, and the credential is read from
    `REZOPS_DRIVE_TOKEN` and checked before any HTTP request is attempted.

    Only file *metadata* is ever fetched or returned -- never document
    content. Google's nested `lastModifyingUser` object is flattened to a
    scalar before ever reaching `RawFact`: to its `emailAddress` (or `None`
    if absent) -- `RawFact.fields` cannot hold a nested object (AD-9).

    Raises a typed error -- never lets a raw `httpx`/`KeyError`/
    `json.JSONDecodeError` exception escape -- for every failure case in the
    I/O matrix: `InvalidFileIdentifierError` for empty/whitespace-only/
    non-string `file_id`, `InvalidArtifactIdentifierError` for empty/
    whitespace-only/non-string `artifact_type`/`artifact_id`,
    `MissingCredentialsError` when `REZOPS_DRIVE_TOKEN` is unset, blank, or
    contains a control character or a non-ASCII character,
    `DocumentNotFoundError` on HTTP 404,
    `AuthenticationError` on HTTP 401/403, `MalformedResponseError` for a 200
    body missing `modifiedTime` (a `null` value counts as missing), that
    isn't valid JSON, that isn't an object, or whose
    `lastModifyingUser.emailAddress` value is `null` or non-string, and
    `GoogleDriveConnectorError` for any other HTTP failure or network/
    timeout error.

    Computes no confidence or staleness value -- that is ledger-core's job
    (AD-5), not a connector's. Performs no auto-correlation of `artifact_id`
    to a Drive file -- the caller supplies the exact `file_id`.
    """
    _require_nonempty_file_field("file_id", file_id)
    _require_nonempty_identifier("artifact_type", artifact_type)
    _require_nonempty_identifier("artifact_id", artifact_id)

    token = _read_credential()

    response = _fetch_document(token, file_id)
    fields = _parse_document_response(response, file_id)

    try:
        fact = RawFact(
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            source=_build_source(file_id),
            fields=fields,
        )
    except SchemaValidationError as exc:
        raise MalformedResponseError(
            f"Google Drive file {file_id} could not be represented as a "
            f"RawFact (likely a non-scalar field value): {exc}"
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
