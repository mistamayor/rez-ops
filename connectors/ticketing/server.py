"""Ticketing connector MCP server (AD-1, AD-2): the second Sensor.

Exposes exactly one read-only tool, `ticketing_get_ticket_status`, which
fetches a single record from ServiceNow's Table API
(`GET {instance_url}/api/now/table/{table}/{sys_id}
?sysparm_display_value=true&sysparm_fields=...`) via `httpx` and returns it
as a `RawFact`-shaped dict (AD-9).

Like the git connector, this module never imports or calls `ledger_core`
(AD-1), never computes a confidence/staleness value (AD-5), and never
attempts to auto-correlate an artifact to a ServiceNow record -- the caller
supplies the exact `table`/`sys_id`. It only ever issues `GET` requests --
never `POST`/`PUT`/`PATCH`/`DELETE` -- against ServiceNow (CAP-2). Credentials
come only from the `REZOPS_TICKETING_INSTANCE_URL` and `REZOPS_TICKETING_TOKEN`
env vars (AD-7) -- never a config file or hardcoded value. The instance URL
must be `https://` -- never plaintext `http://` -- since the token travels
as a bearer `Authorization` header.
"""

from __future__ import annotations

import os
import re
import urllib.parse
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from shared.ledger_schema import RawFact, SchemaValidationError

mcp = FastMCP("ticketing")

#: `shared.ledger_schema.RawFact.source` is validated against a strict
#: charset (`^[A-Za-z0-9_:-]+$` -- see shared/ledger_schema/models.py,
#: read-only for this story) that excludes "/", ".", and other characters a
#: ServiceNow instance URL legitimately contains (e.g. "https://dev123.
#: service-now.com"). Mirroring the git connector's `_build_source`, the
#: whole constructed "servicenow:<instance>/<table>/<sys_id>" string is swept
#: for any character outside this charset and each is replaced with "_" --
#: producing an opaque, human-readable provenance string, not a structured,
#: parseable one. Nothing in this codebase parses `source` back into its
#: parts today; only its charset-validity and human-readability are load
#: bearing.
_SOURCE_UNSAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9_:-]")

#: Wall-clock budget for each HTTP request to ServiceNow. A hung connection
#: (e.g. a stalled network path or an unresponsive instance) must not block
#: this tool indefinitely -- same lesson Story 2's review surfaced for
#: `subprocess.run`.
_HTTP_TIMEOUT_SECONDS = 10.0

#: Fields expected in a ServiceNow Table API record's `result` object.
#: Missing any of these is treated as a malformed response (typed error),
#: never a raw `KeyError`.
_EXPECTED_RESULT_FIELDS = (
    "number",
    "state",
    "assigned_to",
    "sys_updated_on",
    "short_description",
)

_INSTANCE_URL_ENV_VAR = "REZOPS_TICKETING_INSTANCE_URL"
_TOKEN_ENV_VAR = "REZOPS_TICKETING_TOKEN"

#: Query parameters sent with every Table API request. `sysparm_display_value`
#: is the single most important line in this module: without it, ServiceNow
#: reference fields (e.g. `assigned_to`) come back as a nested
#: `{"link": ..., "value": ...}` object rather than a flat display string, and
#: every one of those objects would fail RawFact's JSON-scalar validation --
#: silently turning almost every real ServiceNow response into a
#: `MalformedResponseError`. `sysparm_fields` restricts the response to only
#: the fields this connector reads, both as a minor payload-size optimization
#: and to keep the response shape predictable.
_TABLE_API_QUERY_PARAMS = {
    "sysparm_display_value": "true",
    "sysparm_fields": ",".join(_EXPECTED_RESULT_FIELDS),
}

#: `instance_url` must be `https://` -- never plain `http://` or a
#: schemeless value -- so the bearer token in the Authorization header is
#: never transmitted in the clear, and so a malformed scheme never reaches
#: `httpx` and risks an `httpx.InvalidURL`/`UnsupportedProtocol` escaping past
#: the `except httpx.RequestError` catch in `_fetch_ticket` (neither of those
#: exception types is an `httpx.RequestError` subclass).
_REQUIRED_INSTANCE_URL_SCHEME = "https://"


class TicketingConnectorError(Exception):
    """Base class for every error this connector raises."""


class InvalidTicketIdentifierError(TicketingConnectorError, ValueError):
    """Raised when `table`/`sys_id` fail input validation (empty/whitespace-only).

    Always raised before any HTTP request is attempted.
    """


class InvalidArtifactIdentifierError(TicketingConnectorError, ValueError):
    """Raised when `artifact_type`/`artifact_id` fail input validation.

    Always raised before any HTTP request is attempted.
    """


class MissingCredentialsError(TicketingConnectorError):
    """Raised when `REZOPS_TICKETING_INSTANCE_URL` or `REZOPS_TICKETING_TOKEN`
    is unset (or empty/whitespace-only). Always raised before any HTTP
    request is attempted.
    """


class InvalidInstanceUrlError(TicketingConnectorError, ValueError):
    """Raised when `REZOPS_TICKETING_INSTANCE_URL` is blank (including after
    stripping trailing "/" characters) or does not start with "https://".

    Always raised before any HTTP request is attempted -- protects the
    bearer token from ever being sent in the clear.
    """


class TicketNotFoundError(TicketingConnectorError):
    """Raised when ServiceNow returns HTTP 404 for the given `table`/`sys_id`."""


class AuthenticationError(TicketingConnectorError):
    """Raised when ServiceNow returns HTTP 401 or 403."""


class MalformedResponseError(TicketingConnectorError):
    """Raised when a 200 response body is not valid JSON, has no `result`
    object, or is missing an expected field -- never a raw `KeyError` or
    `json.JSONDecodeError`.
    """


def _require_nonempty_ticket_field(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InvalidTicketIdentifierError(
            f"{name} must be a non-empty string; got {value!r}"
        )


def _require_nonempty_identifier(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InvalidArtifactIdentifierError(
            f"{name} must be a non-empty string; got {value!r}"
        )


def _validate_instance_url(instance_url: str) -> str:
    """Strip trailing "/" and validate the result is non-blank and `https://`.

    Raises `InvalidInstanceUrlError` -- before any HTTP request is attempted
    -- if the value is blank once trailing slashes are removed (e.g. a value
    consisting only of "/" characters), or if it does not start with
    "https://" (rejects `http://` and schemeless values alike).
    """
    stripped = instance_url.rstrip("/")
    if not stripped.strip():
        raise InvalidInstanceUrlError(
            f"{_INSTANCE_URL_ENV_VAR} must be a non-empty https:// URL; "
            f"got {instance_url!r}"
        )
    if not stripped.startswith(_REQUIRED_INSTANCE_URL_SCHEME):
        raise InvalidInstanceUrlError(
            f"{_INSTANCE_URL_ENV_VAR} must start with {_REQUIRED_INSTANCE_URL_SCHEME!r} "
            f"to avoid transmitting the bearer token in the clear; got {instance_url!r}"
        )
    return stripped


def _read_credentials() -> tuple[str, str]:
    """Read and validate credentials from env vars.

    Raises `MissingCredentialsError` -- before any HTTP request is attempted
    -- if either var is unset or empty/whitespace-only.
    """
    instance_url = os.environ.get(_INSTANCE_URL_ENV_VAR)
    token = os.environ.get(_TOKEN_ENV_VAR)

    missing = [
        name
        for name, value in (
            (_INSTANCE_URL_ENV_VAR, instance_url),
            (_TOKEN_ENV_VAR, token),
        )
        if not value or not value.strip()
    ]
    if missing:
        raise MissingCredentialsError(
            f"missing required env var(s): {', '.join(missing)}"
        )

    assert instance_url is not None and token is not None  # narrowed by the check above
    return instance_url, token


def _build_source(instance_url: str, table: str, sys_id: str) -> str:
    raw_source = f"servicenow:{instance_url}/{table}/{sys_id}"
    return _SOURCE_UNSAFE_CHARS_RE.sub("_", raw_source)


def _build_client() -> httpx.Client:
    """Construct the `httpx.Client` used for every ServiceNow request.

    Isolated behind a factory so tests can monkeypatch this to inject an
    `httpx.MockTransport`-backed client instead of a live one -- the same
    seam the git connector's `_run_git` provides for `subprocess.run`.
    """
    return httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS)


def _fetch_ticket(instance_url: str, token: str, table: str, sys_id: str) -> httpx.Response:
    """Issue the single `GET` request against ServiceNow's Table API.

    Translates every network-level failure (timeout, connection error, etc.)
    into a typed `TicketingConnectorError` -- never lets a raw `httpx`
    exception escape this module.

    `table`/`sys_id` are percent-encoded (`safe=""`) before being interpolated
    into the request path -- both have already been validated as non-empty
    strings, but neither is validated against a restrictive charset, so a
    value containing "/", "?", "#", or whitespace must not be allowed to
    alter the request path or inject extra query parameters.
    """
    encoded_table = urllib.parse.quote(table, safe="")
    encoded_sys_id = urllib.parse.quote(sys_id, safe="")
    url = f"{instance_url}/api/now/table/{encoded_table}/{encoded_sys_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    with _build_client() as client:
        try:
            return client.get(url, headers=headers, params=_TABLE_API_QUERY_PARAMS)
        except httpx.TimeoutException as exc:
            raise TicketingConnectorError(
                f"request to ServiceNow timed out: {table}/{sys_id} on "
                f"{instance_url}: {exc}"
            ) from exc
        except httpx.RequestError as exc:
            raise TicketingConnectorError(
                f"request to ServiceNow failed: {table}/{sys_id} on "
                f"{instance_url}: {exc}"
            ) from exc


def _parse_ticket_response(
    response: httpx.Response, table: str, sys_id: str, instance_url: str
) -> dict[str, Any]:
    """Map a ServiceNow HTTP response to the raw `fields` mapping for a `RawFact`.

    Raises `TicketNotFoundError` (404), `AuthenticationError` (401/403),
    `TicketingConnectorError` (any other non-2xx), or `MalformedResponseError`
    (invalid JSON, missing `result`, or missing an expected field) -- never a
    raw `KeyError`/`json.JSONDecodeError`.
    """
    if response.status_code == 404:
        raise TicketNotFoundError(
            f"no record found for {table}/{sys_id} on {instance_url}"
        )
    if response.status_code in (401, 403):
        raise AuthenticationError(
            f"authentication failed for {instance_url} (HTTP {response.status_code})"
        )
    if not response.is_success:
        # The response body is deliberately omitted -- it may contain real
        # ticket content (e.g. short_description text) that must not leak
        # into logs, error channels, or an agent transcript via this
        # exception's message.
        raise TicketingConnectorError(
            f"ServiceNow returned HTTP {response.status_code} for "
            f"{table}/{sys_id} on {instance_url} (response body omitted)"
        )

    try:
        body = response.json()
    except ValueError as exc:  # httpx surfaces json.JSONDecodeError, a ValueError
        raise MalformedResponseError(
            f"ServiceNow response body for {table}/{sys_id} is not valid JSON: {exc}"
        ) from exc

    if not isinstance(body, dict) or "result" not in body:
        raise MalformedResponseError(
            f"ServiceNow response for {table}/{sys_id} is missing the expected "
            f"'result' envelope: {body!r}"
        )

    result = body["result"]
    if not isinstance(result, dict):
        raise MalformedResponseError(
            f"ServiceNow 'result' for {table}/{sys_id} is not an object: {result!r}"
        )

    missing_fields = [key for key in _EXPECTED_RESULT_FIELDS if key not in result]
    if missing_fields:
        raise MalformedResponseError(
            f"ServiceNow record for {table}/{sys_id} is missing expected "
            f"field(s) {missing_fields!r}: {result!r}"
        )

    return {key: result[key] for key in _EXPECTED_RESULT_FIELDS}


@mcp.tool(name="ticketing_get_ticket_status")
def ticketing_get_ticket_status(
    table: str, sys_id: str, artifact_type: str, artifact_id: str
) -> dict[str, Any]:
    """Return a RawFact-shaped dict for one ServiceNow Table API record.

    Read-only: issues exactly one `GET {instance_url}/api/now/table/{table}/
    {sys_id}?sysparm_display_value=true&sysparm_fields=...` request via
    `httpx`, never a `POST`/`PUT`/`PATCH`/`DELETE` (CAP-2). `table`/`sys_id`
    are percent-encoded before being placed in the request path. `table`/
    `sys_id`/`artifact_type`/`artifact_id` are validated as non-empty strings
    (rejecting non-string input, e.g. an int, with the same typed error as an
    empty one) before anything else runs, and credentials are read from
    `REZOPS_TICKETING_INSTANCE_URL`/`REZOPS_TICKETING_TOKEN` and checked --
    including that the instance URL is non-blank after stripping trailing
    "/" characters and starts with "https://" -- before any HTTP request is
    attempted. All of these validation failures are raised with zero HTTP
    calls made.

    Raises a typed error -- never lets a raw `httpx`/`KeyError`/
    `json.JSONDecodeError` exception escape -- for every failure case in the
    I/O matrix: `InvalidTicketIdentifierError` for empty/whitespace-only/
    non-string `table`/`sys_id`, `InvalidArtifactIdentifierError` for empty/
    whitespace-only/non-string `artifact_type`/`artifact_id`,
    `MissingCredentialsError` when either env var is unset,
    `InvalidInstanceUrlError` when the instance URL is blank or not
    `https://`, `TicketNotFoundError` on HTTP 404, `AuthenticationError` on
    HTTP 401/403, `MalformedResponseError` for a 200 body missing expected
    fields, that isn't valid JSON, or that contains a non-scalar field value,
    and `TicketingConnectorError` for any other HTTP failure or
    network/timeout error.

    Computes no confidence or staleness value -- that is ledger-core's job
    (AD-5), not a connector's. Performs no auto-correlation of `artifact_id`
    to a ServiceNow record -- the caller supplies the exact `table`/`sys_id`.
    """
    _require_nonempty_ticket_field("table", table)
    _require_nonempty_ticket_field("sys_id", sys_id)
    _require_nonempty_identifier("artifact_type", artifact_type)
    _require_nonempty_identifier("artifact_id", artifact_id)

    instance_url, token = _read_credentials()
    instance_url = _validate_instance_url(instance_url)

    response = _fetch_ticket(instance_url, token, table, sys_id)
    fields = _parse_ticket_response(response, table, sys_id, instance_url)

    try:
        fact = RawFact(
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            source=_build_source(instance_url, table, sys_id),
            fields=fields,
        )
    except SchemaValidationError as exc:
        raise MalformedResponseError(
            f"ServiceNow record for {table}/{sys_id} could not be represented "
            f"as a RawFact (likely a non-scalar field value): {exc}"
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
