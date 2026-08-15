"""Google Calendar connector MCP server (AD-1, AD-2): the calendar Sensor.

Exposes exactly one read-only tool, `calendar_get_event_status`, which fetches
a single event from the Google Calendar API v3
(`GET https://www.googleapis.com/calendar/v3/calendars/{calendarId}/events/
{eventId}`) via `httpx` and returns it as a `RawFact`-shaped dict (AD-9).

Like the git and ticketing connectors, this module never imports or calls
`ledger_core` (AD-1), never computes a confidence/staleness value (AD-5), and
never attempts to auto-correlate an artifact to a calendar event -- the
caller supplies the exact `calendar_id`/`event_id`. It only ever issues `GET`
requests -- never `POST`/`PUT`/`PATCH`/`DELETE` -- against the Calendar API
(CAP-2). The credential comes only from the `REZOPS_CALENDAR_TOKEN` env var
(AD-7) -- never a config file or hardcoded value; obtaining/refreshing that
token is out of scope for this connector.

Google's response nests several fields as objects (`start`, `end`,
`organizer`) rather than scalars. Each is flattened to a scalar at extraction
time -- `start`/`end` to their `dateTime` value (or `date` for an all-day
event with no `dateTime`), `organizer` to its `email` -- before ever reaching
`RawFact`, since `RawFact.fields` cannot hold a nested object (AD-9). This is
designed in from the start, learning directly from the ticketing connector's
`sysparm_display_value` review finding rather than rediscovering the same
class of bug.
"""

from __future__ import annotations

import os
import re
import urllib.parse
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from shared.ledger_schema import RawFact, SchemaValidationError

mcp = FastMCP("calendar-google")

#: `shared.ledger_schema.RawFact.source` is validated against a strict
#: charset (`^[A-Za-z0-9_:-]+$` -- see shared/ledger_schema/models.py,
#: read-only for this story) that excludes "/" and other characters a
#: `calendar_id` (often an email address) or `event_id` legitimately
#: contains. Mirroring the git/ticketing connectors' `_build_source`, the
#: whole constructed "google-calendar:<calendar_id>/<event_id>" string is
#: swept for any character outside this charset and each is replaced with
#: "_" -- producing an opaque, human-readable provenance string, not a
#: structured, parseable one.
_SOURCE_UNSAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9_:-]")

#: Wall-clock budget for each HTTP request to the Calendar API. A hung
#: connection must not block this tool indefinitely -- same lesson the git
#: and ticketing connectors' reviews already surfaced.
_HTTP_TIMEOUT_SECONDS = 10.0

_TOKEN_ENV_VAR = "REZOPS_CALENDAR_TOKEN"

#: A credential containing a control character (e.g. an embedded CR/LF) must
#: never reach `httpx`'s header-encoding machinery -- that could either
#: inject an extra header/line into the request or raise an untyped,
#: connector-specific exception that escapes this module uncaught. Rejected
#: up front, before any HTTP request is attempted, as a typed
#: `MissingCredentialsError`.
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")

_CALENDAR_API_BASE_URL = "https://www.googleapis.com/calendar/v3"

#: Top-level fields expected in a Google Calendar API v3 event body, beyond
#: `organizer` (which is optional -- some events have no organizer at all).
#: Missing any of these is treated as a malformed response (typed error),
#: never a raw `KeyError`.
_REQUIRED_EVENT_FIELDS = ("summary", "status", "start", "end", "updated")


class CalendarConnectorError(Exception):
    """Base class for every error this connector raises."""


class InvalidEventIdentifierError(CalendarConnectorError, ValueError):
    """Raised when `calendar_id`/`event_id` fail input validation
    (empty/whitespace-only/non-string).

    Always raised before any HTTP request is attempted.
    """


class InvalidArtifactIdentifierError(CalendarConnectorError, ValueError):
    """Raised when `artifact_type`/`artifact_id` fail input validation
    (empty/whitespace-only/non-string).

    Always raised before any HTTP request is attempted.
    """


class MissingCredentialsError(CalendarConnectorError):
    """Raised when `REZOPS_CALENDAR_TOKEN` is unset, empty/whitespace-only, or
    contains a control character (e.g. an embedded CR/LF) that would be unsafe
    to place in an HTTP header.

    Always raised before any HTTP request is attempted.
    """


class EventNotFoundError(CalendarConnectorError):
    """Raised when the Calendar API returns HTTP 404 for the given
    `calendar_id`/`event_id`.
    """


class AuthenticationError(CalendarConnectorError):
    """Raised when the Calendar API returns HTTP 401 or 403."""


class MalformedResponseError(CalendarConnectorError):
    """Raised when a 200 response body is not valid JSON, is not an object,
    or is missing an expected field -- never a raw `KeyError` or
    `json.JSONDecodeError`.
    """


def _require_nonempty_event_field(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InvalidEventIdentifierError(
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


def _build_source(calendar_id: str, event_id: str) -> str:
    raw_source = f"google-calendar:{calendar_id}/{event_id}"
    return _SOURCE_UNSAFE_CHARS_RE.sub("_", raw_source)


def _build_client() -> httpx.Client:
    """Construct the `httpx.Client` used for every Calendar API request.

    Isolated behind a factory so tests can monkeypatch this to inject an
    `httpx.MockTransport`-backed client instead of a live one -- the same
    seam the git and ticketing connectors' factories provide.
    """
    return httpx.Client(timeout=_HTTP_TIMEOUT_SECONDS)


def _fetch_event(token: str, calendar_id: str, event_id: str) -> httpx.Response:
    """Issue the single `GET` request against the Calendar API.

    Translates every network-level failure (timeout, connection error, etc.)
    into a typed `CalendarConnectorError` -- never lets a raw `httpx`
    exception escape this module.

    `calendar_id`/`event_id` are percent-encoded (`safe=""`) before being
    interpolated into the request path -- both have already been validated
    as non-empty strings, but neither is validated against a restrictive
    charset, so a value containing "/", "?", "#", or whitespace must not be
    allowed to alter the request path or inject extra query parameters.
    """
    encoded_calendar_id = urllib.parse.quote(calendar_id, safe="")
    encoded_event_id = urllib.parse.quote(event_id, safe="")
    url = (
        f"{_CALENDAR_API_BASE_URL}/calendars/{encoded_calendar_id}"
        f"/events/{encoded_event_id}"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    with _build_client() as client:
        try:
            return client.get(url, headers=headers)
        except httpx.TimeoutException as exc:
            raise CalendarConnectorError(
                f"request to Google Calendar timed out: {calendar_id}/{event_id}: {exc}"
            ) from exc
        except httpx.RequestError as exc:
            raise CalendarConnectorError(
                f"request to Google Calendar failed: {calendar_id}/{event_id}: {exc}"
            ) from exc


def _flatten_datetime_field(value: Any, field_name: str) -> str:
    """Flatten a Google Calendar `start`/`end` object to a scalar string.

    Returns the `dateTime` value for a timed event, or the `date` value for
    an all-day event with no `dateTime`. Raises `MalformedResponseError` --
    never a raw `KeyError` -- if `value` is not an object, if it is an object
    with neither key, or if the extracted `dateTime`/`date` value itself is
    not a non-empty string (e.g. `null`) -- a `None`/non-string value must
    not silently flow through to `RawFact.fields`.

    The raised messages deliberately omit the raw object/value content --
    consistent with the non-2xx branch of `_parse_event_response` -- since it
    may contain real event content that must not leak into an exception
    message.
    """
    if not isinstance(value, dict):
        raise MalformedResponseError(f"event {field_name!r} is not an object")
    if "dateTime" in value:
        extracted = value["dateTime"]
    elif "date" in value:
        extracted = value["date"]
    else:
        raise MalformedResponseError(
            f"event {field_name!r} object has neither 'dateTime' nor 'date'"
        )
    if not isinstance(extracted, str) or not extracted.strip():
        raise MalformedResponseError(
            f"event {field_name!r} has a non-string or empty 'dateTime'/'date' value"
        )
    return extracted


def _flatten_organizer_field(value: Any) -> str | None:
    """Flatten a Google Calendar `organizer` object to its `email` scalar.

    Returns `None` if `organizer` is absent from the response entirely, or if
    present but with no `email` key. Raises `MalformedResponseError` if
    `organizer` is present but is not an object, or if its `email` key is
    present but its value is not a non-empty string (e.g. `null`) -- a
    `None`/non-string `email` must not silently flow through to
    `RawFact.fields`.

    The raised messages deliberately omit the raw object/value content --
    consistent with the non-2xx branch of `_parse_event_response`.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise MalformedResponseError("event 'organizer' is not an object")
    if "email" not in value:
        return None
    email = value["email"]
    if not isinstance(email, str) or not email.strip():
        raise MalformedResponseError(
            "event 'organizer' has a non-string or empty 'email' value"
        )
    return email


def _parse_event_response(
    response: httpx.Response, calendar_id: str, event_id: str
) -> dict[str, Any]:
    """Map a Calendar API HTTP response to the raw `fields` mapping for a
    `RawFact`.

    Raises `EventNotFoundError` (404), `AuthenticationError` (401/403),
    `CalendarConnectorError` (any other non-2xx), or `MalformedResponseError`
    (invalid JSON, non-object body, or missing an expected field) -- never a
    raw `KeyError`/`json.JSONDecodeError`.
    """
    if response.status_code == 404:
        raise EventNotFoundError(
            f"no event found for {calendar_id}/{event_id}"
        )
    if response.status_code in (401, 403):
        raise AuthenticationError(
            f"authentication failed for Google Calendar (HTTP {response.status_code})"
        )
    if not response.is_success:
        # The response body is deliberately omitted -- it may contain real
        # event content (e.g. summary/description text) that must not leak
        # into logs, error channels, or an agent transcript via this
        # exception's message.
        raise CalendarConnectorError(
            f"Google Calendar returned HTTP {response.status_code} for "
            f"{calendar_id}/{event_id} (response body omitted)"
        )

    try:
        body = response.json()
    except ValueError as exc:  # httpx surfaces json.JSONDecodeError, a ValueError
        raise MalformedResponseError(
            f"Google Calendar response body for {calendar_id}/{event_id} is "
            f"not valid JSON: {exc}"
        ) from exc

    if not isinstance(body, dict):
        # The raw body is deliberately omitted from the message -- same
        # reasoning as the non-2xx branch above: it may contain real event
        # content that must not leak into an exception message.
        raise MalformedResponseError(
            f"Google Calendar response for {calendar_id}/{event_id} is not "
            "an object (response body omitted)"
        )

    # A required field whose value is `None` is treated the same as an
    # absent key -- a `null` `summary`, for example, is just as unusable as a
    # missing `summary` and must not silently produce a `RawFact` with a
    # `None` field value.
    missing_fields = [
        key
        for key in _REQUIRED_EVENT_FIELDS
        if key not in body or body[key] is None
    ]
    if missing_fields:
        # The raw body is deliberately omitted -- same reasoning as the
        # non-2xx branch above.
        raise MalformedResponseError(
            f"Google Calendar event {calendar_id}/{event_id} is missing "
            f"expected field(s) {missing_fields!r} (response body omitted)"
        )

    fields: dict[str, Any] = {
        "summary": body["summary"],
        "status": body["status"],
        "start": _flatten_datetime_field(body["start"], "start"),
        "end": _flatten_datetime_field(body["end"], "end"),
        "updated": body["updated"],
        "organizer_email": _flatten_organizer_field(body.get("organizer")),
    }
    return fields


@mcp.tool(name="calendar_get_event_status")
def calendar_get_event_status(
    calendar_id: str, event_id: str, artifact_type: str, artifact_id: str
) -> dict[str, Any]:
    """Return a RawFact-shaped dict for one Google Calendar API v3 event.

    Read-only: issues exactly one `GET https://www.googleapis.com/calendar/
    v3/calendars/{calendar_id}/events/{event_id}` request via `httpx`, never
    a `POST`/`PUT`/`PATCH`/`DELETE` (CAP-2). `calendar_id`/`event_id` are
    percent-encoded before being placed in the request path. `calendar_id`/
    `event_id`/`artifact_type`/`artifact_id` are validated as non-empty
    strings (rejecting non-string input, e.g. an int, with the same typed
    error as an empty one) before anything else runs, and the credential is
    read from `REZOPS_CALENDAR_TOKEN` and checked before any HTTP request is
    attempted.

    Google's nested `start`/`end`/`organizer` objects are flattened to
    scalars before ever reaching `RawFact`: `start`/`end` to their `dateTime`
    value (or `date` for an all-day event), `organizer` to its `email` (or
    `None` if absent) -- `RawFact.fields` cannot hold a nested object (AD-9).

    Raises a typed error -- never lets a raw `httpx`/`KeyError`/
    `json.JSONDecodeError` exception escape -- for every failure case in the
    I/O matrix: `InvalidEventIdentifierError` for empty/whitespace-only/
    non-string `calendar_id`/`event_id`, `InvalidArtifactIdentifierError` for
    empty/whitespace-only/non-string `artifact_type`/`artifact_id`,
    `MissingCredentialsError` when `REZOPS_CALENDAR_TOKEN` is unset, blank, or
    contains a control character, `EventNotFoundError` on HTTP 404,
    `AuthenticationError` on HTTP 401/403, `MalformedResponseError` for a 200
    body missing expected fields (a `null` value for a required field counts
    as missing), that isn't valid JSON, that contains a non-scalar field
    value, or whose `start`/`end`/`organizer.email` value is `null` or
    non-string, and `CalendarConnectorError` for any other HTTP failure or
    network/timeout error.

    Computes no confidence or staleness value -- that is ledger-core's job
    (AD-5), not a connector's. Performs no auto-correlation of `artifact_id`
    to a calendar event -- the caller supplies the exact `calendar_id`/
    `event_id`.
    """
    _require_nonempty_event_field("calendar_id", calendar_id)
    _require_nonempty_event_field("event_id", event_id)
    _require_nonempty_identifier("artifact_type", artifact_type)
    _require_nonempty_identifier("artifact_id", artifact_id)

    token = _read_credential()

    response = _fetch_event(token, calendar_id, event_id)
    fields = _parse_event_response(response, calendar_id, event_id)

    try:
        fact = RawFact(
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            source=_build_source(calendar_id, event_id),
            fields=fields,
        )
    except SchemaValidationError as exc:
        raise MalformedResponseError(
            f"Google Calendar event {calendar_id}/{event_id} could not be "
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
