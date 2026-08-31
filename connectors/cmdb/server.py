"""CMDB connector MCP server (AD-1, AD-2): the fourth and last Sensor.

Exposes exactly one read-only tool, `cmdb_get_ci_status`, which fetches a
single configuration-item (CI) record from ServiceNow's Table API
(`GET {instance_url}/api/now/table/{table}/{sys_id}
?sysparm_display_value=true&sysparm_fields=...`) via `httpx` and returns it
as a `RawFact`-shaped dict (AD-9).

This is a genuinely different domain from the ticketing connector (CIs, not
tickets) even though both target ServiceNow's Table API and vendor
mechanism -- per AD-2 this is its own independent connector server, never an
extension of `connectors/ticketing/`. Connectors never import each other
(AD-1, AD-2), so the ServiceNow-fetch pattern is duplicated here rather than
shared, and credentials come only from `REZOPS_CMDB_INSTANCE_URL`/
`REZOPS_CMDB_TOKEN` -- a separate env-var pair from the ticketing
connector's, even when both happen to point at the same ServiceNow instance
in practice.

Every lesson from the ticketing and calendar connectors' reviews is applied
here from the start rather than rediscovered: `sysparm_display_value`/
`sysparm_fields` (so reference fields like `support_group` come back as flat
display strings, not nested objects), URL-encoding of `table`/`sys_id`,
HTTPS-only instance URL validation, no response-body leakage in error
messages, narrow exception types (never a bare `Exception`/`KeyError`/
`json.JSONDecodeError` escaping this module), non-string input guards, and a
control-character check on the credential token.

Like the other connectors, this module never imports or calls `ledger_core`
(AD-1), never computes a confidence/staleness/tier_sla/escalation_owner value
(AD-5, AD-9 -- that is a future ledger-core capability), and never attempts
to auto-correlate an artifact to a CI record -- the caller supplies the exact
`table`/`sys_id`. It only ever issues `GET` requests -- never `POST`/`PUT`/
`PATCH`/`DELETE` -- against ServiceNow (CAP-2).
"""

from __future__ import annotations

import os
import re
import urllib.parse
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from shared.ledger_schema import RawFact, SchemaValidationError

mcp = FastMCP("cmdb")

#: `shared.ledger_schema.RawFact.source` is validated against a strict
#: charset (`^[A-Za-z0-9_:-]+$` -- see shared/ledger_schema/models.py,
#: read-only for this story) that excludes "/", ".", and other characters a
#: ServiceNow instance URL legitimately contains (e.g. "https://dev123.
#: service-now.com"). Mirroring the ticketing connector's `_build_source`,
#: the whole constructed "servicenow:<instance>/<table>/<sys_id>" string is
#: swept for any character outside this charset and each is replaced with
#: "_" -- producing an opaque, human-readable provenance string, not a
#: structured, parseable one.
_SOURCE_UNSAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9_:-]")

#: Wall-clock budget for each HTTP request to ServiceNow. A hung connection
#: must not block this tool indefinitely -- same lesson every prior
#: connector's review already surfaced.
_HTTP_TIMEOUT_SECONDS = 10.0

#: Fields expected in a ServiceNow Table API CI record's `result` object.
#: Missing any of these (or present but `None`) is treated as a malformed
#: response (typed error), never a raw `KeyError` -- *except* `support_group`,
#: whose value may legitimately be `None` (an unassigned support group is a
#: normal CMDB state, not malformed data; the connector must still be able to
#: report such a CI so Story 8's orphan-risk detection can see it). It must
#: still be a present key -- only its *value* being `None` is tolerated.
#: `support_group` is also a reference field -- without
#: `sysparm_display_value=true` it would come back as a nested
#: `{"link": ..., "value": ...}` object rather than a flat display string
#: (the exact bug the ticketing connector's review found).
_EXPECTED_RESULT_FIELDS = (
    "name",
    "sys_class_name",
    "operational_status",
    "install_status",
    "support_group",
    "sys_updated_on",
)

_INSTANCE_URL_ENV_VAR = "REZOPS_CMDB_INSTANCE_URL"
_TOKEN_ENV_VAR = "REZOPS_CMDB_TOKEN"

#: Query parameters sent with every Table API request. `sysparm_display_value`
#: guarantees reference fields (e.g. `support_group`) come back as a flat
#: display string rather than a nested object -- every one of those objects
#: would otherwise fail RawFact's JSON-scalar validation. `sysparm_fields`
#: restricts the response to only the fields this connector reads.
_TABLE_API_QUERY_PARAMS = {
    "sysparm_display_value": "true",
    "sysparm_fields": ",".join(_EXPECTED_RESULT_FIELDS),
}

#: `instance_url` must be `https://` -- never plain `http://` or a
#: schemeless value -- so the bearer token in the Authorization header is
#: never transmitted in the clear.
_REQUIRED_INSTANCE_URL_SCHEME = "https://"

#: A credential containing a control character (e.g. an embedded CR/LF) must
#: never reach `httpx`'s header-encoding machinery -- that could either
#: inject an extra header/line into the request or raise an untyped
#: exception that escapes this module uncaught. Rejected up front, before
#: any HTTP request is attempted, as a typed `MissingCredentialsError`.
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")

#: Control characters, internal whitespace, and URL-structure-altering
#: characters ("?", "#") must never be allowed to reach `httpx`'s URL
#: construction as part of `instance_url`. Unlike the token (guarded by
#: `_CONTROL_CHAR_RE` above), `instance_url` was previously checked only for
#: the "https://" prefix and non-blankness -- so a value containing e.g. an
#: embedded CR/LF or "?" could reach `client.get()` unguarded and raise
#: `httpx.InvalidURL`, which is not a subclass of `httpx.RequestError`/
#: `httpx.TimeoutException` and would otherwise escape this module raw.
#: Rejected up front, before any HTTP request is attempted, as a typed
#: `InvalidInstanceUrlError`.
_INSTANCE_URL_UNSAFE_CHARS_RE = re.compile(r"[\x00-\x1f\x7f\s?#]")

#: Mirrors `shared.ledger_schema.models._IDENTIFIER_RE` -- the exact charset
#: `RawFact.artifact_type`/`RawFact.artifact_id` enforce
#: (`^[A-Za-z0-9_-]+$`). Validating `artifact_type`/`artifact_id` against
#: this upfront -- rather than only checking non-emptiness -- means a
#: malformed identifier (e.g. "team/dr") is rejected before any HTTP call is
#: made, instead of wasting a live ServiceNow request and credential use
#: only to fail later at `RawFact` construction.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class CMDBConnectorError(Exception):
    """Base class for every error this connector raises."""


class InvalidCIIdentifierError(CMDBConnectorError, ValueError):
    """Raised when `table`/`sys_id` fail input validation (empty/
    whitespace-only/non-string).

    Always raised before any HTTP request is attempted.
    """


class InvalidArtifactIdentifierError(CMDBConnectorError, ValueError):
    """Raised when `artifact_type`/`artifact_id` fail input validation
    (empty/whitespace-only/non-string).

    Always raised before any HTTP request is attempted.
    """


class MissingCredentialsError(CMDBConnectorError):
    """Raised when `REZOPS_CMDB_INSTANCE_URL` or `REZOPS_CMDB_TOKEN` is unset,
    empty/whitespace-only, or (for the token) contains a control character
    that would be unsafe to place in an HTTP header.

    Always raised before any HTTP request is attempted.
    """


class InvalidInstanceUrlError(CMDBConnectorError, ValueError):
    """Raised when `REZOPS_CMDB_INSTANCE_URL` is blank (including after
    stripping trailing "/" characters) or does not start with "https://".

    Always raised before any HTTP request is attempted -- protects the
    bearer token from ever being sent in the clear.
    """


class CINotFoundError(CMDBConnectorError):
    """Raised when ServiceNow returns HTTP 404 for the given `table`/`sys_id`."""


class AuthenticationError(CMDBConnectorError):
    """Raised when ServiceNow returns HTTP 401 or 403."""


class MalformedResponseError(CMDBConnectorError):
    """Raised when a 200 response body is not valid JSON, has no `result`
    object, or is missing (or has a `None` value for) an expected field --
    never a raw `KeyError` or `json.JSONDecodeError`.
    """


def _require_nonempty_ci_field(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InvalidCIIdentifierError(
            f"{name} must be a non-empty string; got {value!r}"
        )


def _require_nonempty_identifier(name: str, value: Any) -> None:
    """Validate `artifact_type`/`artifact_id` against `RawFact`'s own charset.

    Raises `InvalidArtifactIdentifierError` -- before any HTTP request is
    attempted -- for non-string, empty/whitespace-only, or charset-invalid
    (e.g. containing "/") values. Checking the exact charset upfront (not
    just non-emptiness) guarantees a value that would fail `RawFact`
    construction is rejected before wasting a live HTTP call and credential
    use on a request whose result could never be returned anyway.
    """
    if not isinstance(value, str) or not _IDENTIFIER_RE.match(value):
        raise InvalidArtifactIdentifierError(
            f"{name} must be a non-empty string matching {_IDENTIFIER_RE.pattern!r} "
            f"(the same charset RawFact.{name} enforces); got {value!r}"
        )


def _validate_instance_url(instance_url: str) -> str:
    """Strip trailing "/" and validate the result is non-blank and `https://`.

    Raises `InvalidInstanceUrlError` -- before any HTTP request is attempted
    -- if the value is blank once trailing slashes are removed (e.g. a value
    consisting only of "/" characters), if it does not start with
    "https://" (rejects `http://` and schemeless values alike), or if it
    contains a control character, internal whitespace, or a "?"/"#"
    character that could otherwise reach `httpx`'s URL construction unguarded
    and raise an uncaught `httpx.InvalidURL`.
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
    if _INSTANCE_URL_UNSAFE_CHARS_RE.search(stripped):
        raise InvalidInstanceUrlError(
            f"{_INSTANCE_URL_ENV_VAR} must not contain control characters, "
            f"whitespace, '?', or '#'; got {instance_url!r}"
        )
    return stripped


def _read_credentials() -> tuple[str, str]:
    """Read and validate credentials from env vars.

    Raises `MissingCredentialsError` -- before any HTTP request is attempted
    -- if either var is unset or empty/whitespace-only, or if the token
    contains a control character.
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

    if _CONTROL_CHAR_RE.search(token):
        raise MissingCredentialsError(
            f"{_TOKEN_ENV_VAR} contains a control character and cannot be "
            "used in an HTTP header"
        )

    return instance_url, token


def _build_source(instance_url: str, table: str, sys_id: str) -> str:
    raw_source = f"servicenow:{instance_url}/{table}/{sys_id}"
    return _SOURCE_UNSAFE_CHARS_RE.sub("_", raw_source)


def _build_client() -> httpx.Client:
    """Construct the `httpx.Client` used for every ServiceNow request.

    Isolated behind a factory so tests can monkeypatch this to inject an
    `httpx.MockTransport`-backed client instead of a live one -- the same
    seam the other connectors' factories provide.
    """
    return httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS)


def _fetch_ci(instance_url: str, token: str, table: str, sys_id: str) -> httpx.Response:
    """Issue the single `GET` request against ServiceNow's Table API.

    Translates every network-level failure (timeout, connection error,
    malformed URL, etc.) into a typed `CMDBConnectorError` -- never lets a
    raw `httpx` exception escape this module. The whole fetch flow --
    constructing the client (`_build_client()`), entering its `with` block,
    and issuing the request -- is wrapped by the same `try`, since a failure
    in client construction/entry must not escape raw any more than a failure
    in the request itself.

    `table`/`sys_id` are percent-encoded (`safe=""`) before being
    interpolated into the request path -- both have already been validated
    as non-empty strings, but neither is validated against a restrictive
    charset, so a value containing "/", "?", "#", or whitespace must not be
    allowed to alter the request path or inject extra query parameters.
    """
    encoded_table = urllib.parse.quote(table, safe="")
    encoded_sys_id = urllib.parse.quote(sys_id, safe="")
    url = f"{instance_url}/api/now/table/{encoded_table}/{encoded_sys_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    try:
        with _build_client() as client:
            return client.get(url, headers=headers, params=_TABLE_API_QUERY_PARAMS)
    except httpx.TimeoutException as exc:
        raise CMDBConnectorError(
            f"request to ServiceNow timed out: {table}/{sys_id} on "
            f"{instance_url}: {exc}"
        ) from exc
    except httpx.InvalidURL as exc:
        # Not a subclass of httpx.RequestError -- must be caught explicitly,
        # same defense-in-depth as the upfront instance_url validation.
        raise CMDBConnectorError(
            f"invalid ServiceNow request URL for {table}/{sys_id} on "
            f"{instance_url}: {exc}"
        ) from exc
    except httpx.RequestError as exc:
        raise CMDBConnectorError(
            f"request to ServiceNow failed: {table}/{sys_id} on "
            f"{instance_url}: {exc}"
        ) from exc


def _parse_ci_response(
    response: httpx.Response, table: str, sys_id: str, instance_url: str
) -> dict[str, Any]:
    """Map a ServiceNow HTTP response to the raw `fields` mapping for a `RawFact`.

    Raises `CINotFoundError` (404), `AuthenticationError` (401/403),
    `CMDBConnectorError` (any other non-2xx), or `MalformedResponseError`
    (invalid JSON, missing `result`, non-object body, or a missing/`None`
    expected field -- except `support_group`, which may legitimately be
    `None`; see `_EXPECTED_RESULT_FIELDS`) -- never a raw
    `KeyError`/`json.JSONDecodeError`.
    """
    if response.status_code == 404:
        raise CINotFoundError(
            f"no CI record found for {table}/{sys_id} on {instance_url}"
        )
    if response.status_code in (401, 403):
        raise AuthenticationError(
            f"authentication failed for {instance_url} (HTTP {response.status_code})"
        )
    if not response.is_success:
        # The response body is deliberately omitted -- it may contain real
        # CI content that must not leak into logs, error channels, or an
        # agent transcript via this exception's message.
        raise CMDBConnectorError(
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
        # The raw body is deliberately omitted -- it may contain real CI
        # content that must not leak into logs, error channels, or an agent
        # transcript via this exception's message. Same reasoning as the
        # non-2xx branch above.
        raise MalformedResponseError(
            f"ServiceNow response for {table}/{sys_id} is missing the expected "
            "'result' envelope (response body omitted)"
        )

    result = body["result"]
    if not isinstance(result, dict):
        # The raw result is deliberately omitted -- same reasoning as above.
        raise MalformedResponseError(
            f"ServiceNow 'result' for {table}/{sys_id} is not an object "
            "(response body omitted)"
        )

    # A required field whose value is `None` is treated the same as an
    # absent key -- a `null` `name`, for example, is just as unusable as a
    # missing `name` and must not silently produce a `RawFact` with a `None`
    # field value. `support_group` is deliberately excluded from this
    # null-rejection: an unassigned support group is a completely normal
    # real-world CMDB state (not malformed data), and Story 8's orphan-risk
    # detection depends on this connector being able to report a CI that has
    # no assigned support group at all, rather than refusing to ingest it.
    # `support_group` must still be a *present key*, though -- only a `None`
    # value for it is tolerated.
    missing_fields = [
        key
        for key in _EXPECTED_RESULT_FIELDS
        if key not in result
        or (result[key] is None and key != "support_group")
    ]
    if missing_fields:
        # Only the (fixed, known-in-advance) set of missing/null *field
        # names* is reported -- never the `result` object itself, which may
        # contain unrelated, real CI content (e.g. a sensitive field this
        # connector never asked for) that must not leak into this
        # exception's message.
        raise MalformedResponseError(
            f"ServiceNow CI record for {table}/{sys_id} is missing expected "
            f"field(s) {missing_fields!r} (response body omitted)"
        )

    return {key: result[key] for key in _EXPECTED_RESULT_FIELDS}


@mcp.tool(name="cmdb_get_ci_status")
def cmdb_get_ci_status(
    table: str, sys_id: str, artifact_type: str, artifact_id: str
) -> dict[str, Any]:
    """Return a RawFact-shaped dict for one ServiceNow Table API CI record.

    Read-only: issues exactly one `GET {instance_url}/api/now/table/{table}/
    {sys_id}?sysparm_display_value=true&sysparm_fields=...` request via
    `httpx`, never a `POST`/`PUT`/`PATCH`/`DELETE` (CAP-2). `table`/`sys_id`
    are percent-encoded before being placed in the request path. `table`/
    `sys_id`/`artifact_type`/`artifact_id` are validated as non-empty strings
    (rejecting non-string input, e.g. an int, with the same typed error as an
    empty one) before anything else runs, and credentials are read from
    `REZOPS_CMDB_INSTANCE_URL`/`REZOPS_CMDB_TOKEN` and checked -- including
    that the instance URL is non-blank after stripping trailing "/"
    characters and starts with "https://", and that the token contains no
    control character -- before any HTTP request is attempted. All of these
    validation failures are raised with zero HTTP calls made.

    Raises a typed error -- never lets a raw `httpx`/`KeyError`/
    `json.JSONDecodeError` exception escape -- for every failure case in the
    I/O matrix: `InvalidCIIdentifierError` for empty/whitespace-only/
    non-string `table`/`sys_id`, `InvalidArtifactIdentifierError` for empty/
    whitespace-only/non-string `artifact_type`/`artifact_id`,
    `MissingCredentialsError` when either env var is unset/blank or the
    token contains a control character, `InvalidInstanceUrlError` when the
    instance URL is blank or not `https://`, `CINotFoundError` on HTTP 404,
    `AuthenticationError` on HTTP 401/403, `MalformedResponseError` for a 200
    body missing expected fields (a `null` value for a required field counts
    as missing -- except `support_group`, which is allowed to be `null`: an
    unassigned support group is a normal CMDB state, not malformed data),
    that isn't valid JSON, or that contains a non-scalar field value, and
    `CMDBConnectorError` for any other HTTP failure or network/timeout
    error.

    Computes no confidence, staleness, `tier_sla`, or `escalation_owner`
    value -- that is ledger-core's job (AD-5, AD-9), not a connector's, and
    is deferred to a future story. Performs no auto-correlation of
    `artifact_id` to a ServiceNow CI record -- the caller supplies the exact
    `table`/`sys_id`.
    """
    _require_nonempty_ci_field("table", table)
    _require_nonempty_ci_field("sys_id", sys_id)
    _require_nonempty_identifier("artifact_type", artifact_type)
    _require_nonempty_identifier("artifact_id", artifact_id)

    instance_url, token = _read_credentials()
    instance_url = _validate_instance_url(instance_url)

    response = _fetch_ci(instance_url, token, table, sys_id)
    fields = _parse_ci_response(response, table, sys_id, instance_url)

    try:
        fact = RawFact(
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            source=_build_source(instance_url, table, sys_id),
            fields=fields,
        )
    except SchemaValidationError as exc:
        raise MalformedResponseError(
            f"ServiceNow CI record for {table}/{sys_id} could not be "
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
