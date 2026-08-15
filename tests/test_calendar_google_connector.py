"""Unit tests for the Google Calendar connector (Story 6).

Exercises `connectors.calendar_google.server.calendar_get_event_status`
entirely against `httpx.MockTransport` -- no live Google account or
credentials are used or required. `_build_client` is monkeypatched per-test
to return an `httpx.Client` wired to a `MockTransport` (or, for the
missing-credentials case, to a spy that must never be called).
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from unittest.mock import Mock

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from connectors.calendar_google.server import (
    AuthenticationError,
    CalendarConnectorError,
    EventNotFoundError,
    InvalidArtifactIdentifierError,
    InvalidEventIdentifierError,
    MalformedResponseError,
    MissingCredentialsError,
    calendar_get_event_status,
    mcp,
)
from shared.ledger_schema import RawFact, SchemaValidationError

_TOKEN = "s3cr3t-calendar-token"
_BASE_URL = "https://www.googleapis.com/calendar/v3"

#: Independent (not calling `_build_source`) literal re-implementation of the
#: sanitization `_build_source` performs, used to compute expected `source`
#: values in tests without being self-referential.
_SOURCE_UNSAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9_:-]")


def _expected_source(calendar_id: str, event_id: str) -> str:
    raw = f"google-calendar:{calendar_id}/{event_id}"
    return _SOURCE_UNSAFE_CHARS_RE.sub("_", raw)


def _realistic_timed_event(**overrides: Any) -> dict[str, Any]:
    event = {
        "summary": "DR Tabletop Exercise",
        "status": "confirmed",
        "start": {"dateTime": "2026-08-20T10:00:00-07:00"},
        "end": {"dateTime": "2026-08-20T11:00:00-07:00"},
        "updated": "2026-08-14T09:00:00Z",
        "organizer": {"email": "program-owner@example.com"},
    }
    event.update(overrides)
    return event


def _mock_client(handler: httpx.MockTransport | Any) -> httpx.Client:
    transport = handler if isinstance(handler, httpx.MockTransport) else httpx.MockTransport(handler)
    return httpx.Client(transport=transport, timeout=10.0)


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REZOPS_CALENDAR_TOKEN", _TOKEN)


# --- I/O matrix row 1: happy path, timed event ------------------------------


def test_happy_path_timed_event_returns_rawfact_shaped_dict_with_flattened_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = _realistic_timed_event()
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200, json=event)

    monkeypatch.setattr(
        "connectors.calendar_google.server._build_client", lambda: _mock_client(handler)
    )

    result = calendar_get_event_status(
        calendar_id="primary",
        event_id="evt123",
        artifact_type="test_artifact",
        artifact_id="x1",
    )

    assert result["artifact_type"] == "test_artifact"
    assert result["artifact_id"] == "x1"
    assert result["source"] == _expected_source("primary", "evt123")
    assert result["fields"]["summary"] == "DR Tabletop Exercise"
    assert result["fields"]["status"] == "confirmed"
    assert result["fields"]["start"] == "2026-08-20T10:00:00-07:00"
    assert result["fields"]["end"] == "2026-08-20T11:00:00-07:00"
    assert result["fields"]["updated"] == "2026-08-14T09:00:00Z"
    assert result["fields"]["organizer_email"] == "program-owner@example.com"

    # All fields must be scalar -- none of Google's nested objects leaked
    # through.
    for value in result["fields"].values():
        assert not isinstance(value, (dict, list))

    # Exactly one GET request, with bearer auth, hit the expected URL.
    assert len(captured_requests) == 1
    request = captured_requests[0]
    assert request.method == "GET"
    assert str(request.url) == f"{_BASE_URL}/calendars/primary/events/evt123"
    assert request.headers["authorization"] == f"Bearer {_TOKEN}"

    # The dict round-trips through RawFact construction without raising --
    # proving it is genuinely RawFact-shaped (AD-9), not merely dict-shaped.
    fact = RawFact(**result)
    assert isinstance(fact, RawFact)


# --- I/O matrix row 2: happy path, all-day event ----------------------------


def test_happy_path_all_day_event_flattens_date_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = _realistic_timed_event(
        start={"date": "2026-08-20"},
        end={"date": "2026-08-21"},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=event)

    monkeypatch.setattr(
        "connectors.calendar_google.server._build_client", lambda: _mock_client(handler)
    )

    result = calendar_get_event_status(
        calendar_id="primary", event_id="evt123", artifact_type="test_artifact", artifact_id="x1"
    )

    assert result["fields"]["start"] == "2026-08-20"
    assert result["fields"]["end"] == "2026-08-21"


# --- I/O matrix row 3: event with no organizer ------------------------------


def test_event_with_no_organizer_omits_organizer_email_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = _realistic_timed_event()
    del event["organizer"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=event)

    monkeypatch.setattr(
        "connectors.calendar_google.server._build_client", lambda: _mock_client(handler)
    )

    result = calendar_get_event_status(
        calendar_id="primary", event_id="evt123", artifact_type="test_artifact", artifact_id="x1"
    )

    assert result["fields"]["organizer_email"] is None
    # Still round-trips through RawFact -- None is a valid JSON scalar.
    fact = RawFact(**result)
    assert isinstance(fact, RawFact)


@pytest.mark.parametrize("organizer", [{"displayName": "Program Owner"}, {}])
def test_event_with_organizer_present_but_missing_email_key_omits_organizer_email(
    monkeypatch: pytest.MonkeyPatch, organizer: dict[str, Any]
) -> None:
    """Distinct from the "organizer absent entirely" case above: here the
    `organizer` object itself is present in the response, but has no `email`
    key at all (as opposed to an `email` key present with a `null`/non-string
    value, which must raise -- see the malformed-response tests below).
    """
    event = _realistic_timed_event(organizer=organizer)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=event)

    monkeypatch.setattr(
        "connectors.calendar_google.server._build_client", lambda: _mock_client(handler)
    )

    result = calendar_get_event_status(
        calendar_id="primary", event_id="evt123", artifact_type="test_artifact", artifact_id="x1"
    )

    assert result["fields"]["organizer_email"] is None


# --- I/O matrix row 4: event not found ---------------------------------------


def test_404_raises_event_not_found_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    monkeypatch.setattr(
        "connectors.calendar_google.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(EventNotFoundError):
        calendar_get_event_status(
            calendar_id="primary", event_id="missing", artifact_type="test_artifact", artifact_id="x1"
        )


# --- I/O matrix row 5: auth failure ------------------------------------------


@pytest.mark.parametrize("status_code", [401, 403])
def test_auth_failure_raises_authentication_error(
    monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": "unauthorized"})

    monkeypatch.setattr(
        "connectors.calendar_google.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(AuthenticationError):
        calendar_get_event_status(
            calendar_id="primary", event_id="evt123", artifact_type="test_artifact", artifact_id="x1"
        )


def test_other_non_success_status_raises_calendar_connector_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A distinctive marker standing in for real event content that a 500
    # response body might legitimately contain. It must never appear in the
    # raised exception's message -- only the status code and a generic note
    # may.
    sensitive_marker = "CONFIDENTIAL-EVENT-DETAILS-89213"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=f"internal server error: {sensitive_marker}")

    monkeypatch.setattr(
        "connectors.calendar_google.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(CalendarConnectorError) as exc_info:
        calendar_get_event_status(
            calendar_id="primary", event_id="evt123", artifact_type="test_artifact", artifact_id="x1"
        )

    message = str(exc_info.value)
    assert sensitive_marker not in message
    assert "500" in message


# --- I/O matrix row 6: missing credential -----------------------------------


def test_missing_credential_raises_before_any_http_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REZOPS_CALENDAR_TOKEN", raising=False)

    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.calendar_google.server._build_client", spy)

    with pytest.raises(MissingCredentialsError):
        calendar_get_event_status(
            calendar_id="primary", event_id="evt123", artifact_type="test_artifact", artifact_id="x1"
        )

    spy.assert_not_called()


@pytest.mark.parametrize("blank_value", ["", "   "])
def test_blank_credential_raises_before_any_http_request(
    monkeypatch: pytest.MonkeyPatch, blank_value: str
) -> None:
    monkeypatch.setenv("REZOPS_CALENDAR_TOKEN", blank_value)

    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.calendar_google.server._build_client", spy)

    with pytest.raises(MissingCredentialsError):
        calendar_get_event_status(
            calendar_id="primary", event_id="evt123", artifact_type="test_artifact", artifact_id="x1"
        )

    spy.assert_not_called()


@pytest.mark.parametrize(
    "bad_token",
    ["s3cr3t\r\nX-Injected: 1", "s3cr3t\nX-Injected: 1", "s3cr3t\ttoken"],
)
def test_control_character_in_credential_raises_before_any_http_request(
    monkeypatch: pytest.MonkeyPatch, bad_token: str
) -> None:
    """A token containing a control character (e.g. an embedded CR/LF) must
    never reach `httpx`'s header-encoding machinery -- it must be rejected as
    a typed `MissingCredentialsError` before any HTTP request is attempted,
    rather than risking header injection or an untyped exception escaping
    from `httpx`.

    (A null byte, the other classic injection payload, cannot even be set
    via `os.environ`/`monkeypatch.setenv` -- the OS environment itself
    rejects it -- so it is not exercised here; the CR/LF and tab cases above
    are the realistic, OS-representable threat.)
    """
    monkeypatch.setenv("REZOPS_CALENDAR_TOKEN", bad_token)

    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.calendar_google.server._build_client", spy)

    with pytest.raises(MissingCredentialsError):
        calendar_get_event_status(
            calendar_id="primary", event_id="evt123", artifact_type="test_artifact", artifact_id="x1"
        )

    spy.assert_not_called()


# --- I/O matrix row 7: network/timeout failure ------------------------------


def test_connection_error_raises_calendar_connector_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr(
        "connectors.calendar_google.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(CalendarConnectorError):
        calendar_get_event_status(
            calendar_id="primary", event_id="evt123", artifact_type="test_artifact", artifact_id="x1"
        )


def test_timeout_raises_calendar_connector_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    monkeypatch.setattr(
        "connectors.calendar_google.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(CalendarConnectorError):
        calendar_get_event_status(
            calendar_id="primary", event_id="evt123", artifact_type="test_artifact", artifact_id="x1"
        )


# --- I/O matrix row 8: empty/whitespace calendar_id or event_id ------------


@pytest.mark.parametrize("bad_value", ["", "   "])
def test_empty_or_whitespace_calendar_id_raises_before_any_http_request(
    monkeypatch: pytest.MonkeyPatch, bad_value: str
) -> None:
    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.calendar_google.server._build_client", spy)

    with pytest.raises(InvalidEventIdentifierError):
        calendar_get_event_status(
            calendar_id=bad_value, event_id="evt123", artifact_type="test_artifact", artifact_id="x1"
        )

    spy.assert_not_called()


@pytest.mark.parametrize("bad_value", ["", "   "])
def test_empty_or_whitespace_event_id_raises_before_any_http_request(
    monkeypatch: pytest.MonkeyPatch, bad_value: str
) -> None:
    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.calendar_google.server._build_client", spy)

    with pytest.raises(InvalidEventIdentifierError):
        calendar_get_event_status(
            calendar_id="primary", event_id=bad_value, artifact_type="test_artifact", artifact_id="x1"
        )

    spy.assert_not_called()


@pytest.mark.parametrize("bad_value", ["", "   "])
def test_empty_or_whitespace_artifact_type_raises_invalid_identifier_error(
    monkeypatch: pytest.MonkeyPatch, bad_value: str
) -> None:
    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.calendar_google.server._build_client", spy)

    with pytest.raises(InvalidArtifactIdentifierError):
        calendar_get_event_status(
            calendar_id="primary", event_id="evt123", artifact_type=bad_value, artifact_id="x1"
        )

    spy.assert_not_called()


@pytest.mark.parametrize("bad_value", ["", "   "])
def test_empty_or_whitespace_artifact_id_raises_invalid_identifier_error(
    monkeypatch: pytest.MonkeyPatch, bad_value: str
) -> None:
    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.calendar_google.server._build_client", spy)

    with pytest.raises(InvalidArtifactIdentifierError):
        calendar_get_event_status(
            calendar_id="primary", event_id="evt123", artifact_type="test_artifact", artifact_id=bad_value
        )

    spy.assert_not_called()


# --- Non-string identifier inputs --------------------------------------------


@pytest.mark.parametrize("bad_value", [123, None, 1.5, ["primary"]])
def test_non_string_calendar_id_raises_invalid_event_identifier_error(
    monkeypatch: pytest.MonkeyPatch, bad_value: Any
) -> None:
    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.calendar_google.server._build_client", spy)

    with pytest.raises(InvalidEventIdentifierError):
        calendar_get_event_status(
            calendar_id=bad_value, event_id="evt123", artifact_type="test_artifact", artifact_id="x1"
        )

    spy.assert_not_called()


@pytest.mark.parametrize("bad_value", [123, None, 1.5, ["evt123"]])
def test_non_string_event_id_raises_invalid_event_identifier_error(
    monkeypatch: pytest.MonkeyPatch, bad_value: Any
) -> None:
    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.calendar_google.server._build_client", spy)

    with pytest.raises(InvalidEventIdentifierError):
        calendar_get_event_status(
            calendar_id="primary", event_id=bad_value, artifact_type="test_artifact", artifact_id="x1"
        )

    spy.assert_not_called()


@pytest.mark.parametrize("bad_value", [123, None, 1.5, ["test_artifact"]])
def test_non_string_artifact_type_raises_invalid_artifact_identifier_error(
    monkeypatch: pytest.MonkeyPatch, bad_value: Any
) -> None:
    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.calendar_google.server._build_client", spy)

    with pytest.raises(InvalidArtifactIdentifierError):
        calendar_get_event_status(
            calendar_id="primary", event_id="evt123", artifact_type=bad_value, artifact_id="x1"
        )

    spy.assert_not_called()


@pytest.mark.parametrize("bad_value", [123, None, 1.5, ["x1"]])
def test_non_string_artifact_id_raises_invalid_artifact_identifier_error(
    monkeypatch: pytest.MonkeyPatch, bad_value: Any
) -> None:
    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.calendar_google.server._build_client", spy)

    with pytest.raises(InvalidArtifactIdentifierError):
        calendar_get_event_status(
            calendar_id="primary", event_id="evt123", artifact_type="test_artifact", artifact_id=bad_value
        )

    spy.assert_not_called()


# --- I/O matrix row 9: special characters are URL-encoded -------------------


def test_calendar_id_and_event_id_are_url_encoded_in_the_request_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `calendar_id`/`event_id` containing "/", "?", or whitespace must not
    be able to alter the request path or inject extra query parameters --
    both values are percent-encoded before being placed in the path.
    """
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200, json=_realistic_timed_event())

    monkeypatch.setattr(
        "connectors.calendar_google.server._build_client", lambda: _mock_client(handler)
    )

    calendar_get_event_status(
        calendar_id="team@example.com/../other",
        event_id="evt 123?evil=1",
        artifact_type="test_artifact",
        artifact_id="x1",
    )

    request = captured_requests[0]
    path = str(request.url).split("?", 1)[0]
    assert path == (
        f"{_BASE_URL}/calendars/team%40example.com%2F..%2Fother"
        "/events/evt%20123%3Fevil%3D1"
    )
    # The injected "?evil=1" must not have become a real query parameter.
    assert "evil" not in dict(request.url.params)


# --- I/O matrix row 10: malformed response body -----------------------------


def test_response_missing_expected_field_raises_malformed_response_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incomplete_event = _realistic_timed_event()
    del incomplete_event["status"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=incomplete_event)

    monkeypatch.setattr(
        "connectors.calendar_google.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError):
        calendar_get_event_status(
            calendar_id="primary", event_id="evt123", artifact_type="test_artifact", artifact_id="x1"
        )


def test_response_missing_expected_field_error_message_omits_raw_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exception message for the missing-fields case must not leak the
    raw response body -- consistent with the non-2xx branch's own careful
    non-leaking behavior elsewhere in this module.
    """
    sensitive_marker = "CONFIDENTIAL-SUMMARY-TEXT-40213"
    incomplete_event = _realistic_timed_event(summary=sensitive_marker)
    del incomplete_event["status"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=incomplete_event)

    monkeypatch.setattr(
        "connectors.calendar_google.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError) as exc_info:
        calendar_get_event_status(
            calendar_id="primary", event_id="evt123", artifact_type="test_artifact", artifact_id="x1"
        )

    assert sensitive_marker not in str(exc_info.value)


def test_response_not_an_object_error_message_omits_raw_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sensitive_marker = "CONFIDENTIAL-BODY-CONTENT-55901"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[sensitive_marker])

    monkeypatch.setattr(
        "connectors.calendar_google.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError) as exc_info:
        calendar_get_event_status(
            calendar_id="primary", event_id="evt123", artifact_type="test_artifact", artifact_id="x1"
        )

    assert sensitive_marker not in str(exc_info.value)


@pytest.mark.parametrize("required_field", ["summary", "status", "start", "end", "updated"])
def test_null_required_field_raises_malformed_response_error(
    monkeypatch: pytest.MonkeyPatch, required_field: str
) -> None:
    """A `null` value for a required field is just as unusable as a missing
    key and must not silently produce a `RawFact` with a `None` field value.
    """
    event = _realistic_timed_event(**{required_field: None})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=event)

    monkeypatch.setattr(
        "connectors.calendar_google.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError):
        calendar_get_event_status(
            calendar_id="primary", event_id="evt123", artifact_type="test_artifact", artifact_id="x1"
        )


@pytest.mark.parametrize("bad_datetime_value", [None, 12345, ["2026-08-20"], {}])
def test_null_or_non_string_datetime_value_raises_malformed_response_error(
    monkeypatch: pytest.MonkeyPatch, bad_datetime_value: Any
) -> None:
    event = _realistic_timed_event(start={"dateTime": bad_datetime_value})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=event)

    monkeypatch.setattr(
        "connectors.calendar_google.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError):
        calendar_get_event_status(
            calendar_id="primary", event_id="evt123", artifact_type="test_artifact", artifact_id="x1"
        )


@pytest.mark.parametrize("bad_email_value", [None, 12345, ["a@example.com"], {}])
def test_non_string_organizer_email_raises_malformed_response_error(
    monkeypatch: pytest.MonkeyPatch, bad_email_value: Any
) -> None:
    event = _realistic_timed_event(organizer={"email": bad_email_value})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=event)

    monkeypatch.setattr(
        "connectors.calendar_google.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError):
        calendar_get_event_status(
            calendar_id="primary", event_id="evt123", artifact_type="test_artifact", artifact_id="x1"
        )


def test_response_not_valid_json_raises_malformed_response_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json at all")

    monkeypatch.setattr(
        "connectors.calendar_google.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError):
        calendar_get_event_status(
            calendar_id="primary", event_id="evt123", artifact_type="test_artifact", artifact_id="x1"
        )


def test_response_not_an_object_raises_malformed_response_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["not", "an", "object"])

    monkeypatch.setattr(
        "connectors.calendar_google.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError):
        calendar_get_event_status(
            calendar_id="primary", event_id="evt123", artifact_type="test_artifact", artifact_id="x1"
        )


def test_start_field_with_neither_datetime_nor_date_raises_malformed_response_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = _realistic_timed_event(start={"timeZone": "UTC"})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=event)

    monkeypatch.setattr(
        "connectors.calendar_google.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError):
        calendar_get_event_status(
            calendar_id="primary", event_id="evt123", artifact_type="test_artifact", artifact_id="x1"
        )


def test_start_field_not_an_object_raises_malformed_response_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = _realistic_timed_event(start="2026-08-20T10:00:00-07:00")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=event)

    monkeypatch.setattr(
        "connectors.calendar_google.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError):
        calendar_get_event_status(
            calendar_id="primary", event_id="evt123", artifact_type="test_artifact", artifact_id="x1"
        )


def test_datetime_and_organizer_flattening_error_messages_omit_raw_object_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The datetime/organizer flattening error paths must not embed the raw
    nested object content in the exception message -- consistent with the
    non-2xx branch's own careful non-leaking behavior elsewhere in this
    module.
    """
    sensitive_marker = "CONFIDENTIAL-TIMEZONE-NOTE-77102"
    event = _realistic_timed_event(start={"timeZone": sensitive_marker})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=event)

    monkeypatch.setattr(
        "connectors.calendar_google.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError) as exc_info:
        calendar_get_event_status(
            calendar_id="primary", event_id="evt123", artifact_type="test_artifact", artifact_id="x1"
        )

    assert sensitive_marker not in str(exc_info.value)


def test_organizer_not_an_object_error_message_omits_raw_object_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sensitive_marker = "CONFIDENTIAL-ORGANIZER-NOTE-33018"
    event = _realistic_timed_event(organizer=sensitive_marker)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=event)

    monkeypatch.setattr(
        "connectors.calendar_google.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError) as exc_info:
        calendar_get_event_status(
            calendar_id="primary", event_id="evt123", artifact_type="test_artifact", artifact_id="x1"
        )

    assert sensitive_marker not in str(exc_info.value)


def test_non_scalar_field_value_that_reaches_rawfact_construction_raises_malformed_response_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defensive regression test for the RawFact-construction error handling.

    Flattening is expected to reduce every field to a scalar, but if a
    non-scalar value somehow still reaches `RawFact` construction (e.g. a
    future field addition that forgets to flatten), `RawFact.__post_init__`
    raises `SchemaValidationError`, and this must be converted to
    `MalformedResponseError` -- never allowed to escape as a raw
    `SchemaValidationError` -- by the narrowed `except SchemaValidationError`
    clause around that construction.
    """
    event = _realistic_timed_event(summary={"unexpected": "nested-object"})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=event)

    monkeypatch.setattr(
        "connectors.calendar_google.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError) as exc_info:
        calendar_get_event_status(
            calendar_id="primary", event_id="evt123", artifact_type="test_artifact", artifact_id="x1"
        )

    # Must not have escaped as the raw, un-translated SchemaValidationError.
    assert not isinstance(exc_info.value, SchemaValidationError)


# --- Error hierarchy ---------------------------------------------------------


@pytest.mark.parametrize(
    "error_cls",
    [
        InvalidEventIdentifierError,
        InvalidArtifactIdentifierError,
        MissingCredentialsError,
        EventNotFoundError,
        AuthenticationError,
        MalformedResponseError,
    ],
)
def test_all_typed_errors_are_calendar_connector_errors(error_cls: type) -> None:
    assert issubclass(error_cls, CalendarConnectorError)


def test_invalid_event_identifier_error_is_also_a_value_error() -> None:
    assert issubclass(InvalidEventIdentifierError, ValueError)


def test_invalid_artifact_identifier_error_is_also_a_value_error() -> None:
    assert issubclass(InvalidArtifactIdentifierError, ValueError)


# --- Acceptance: exactly one read-only tool, no write tool ------------------


def test_server_exposes_exactly_one_read_only_tool() -> None:
    tools = asyncio.run(mcp.list_tools())
    names = [tool.name for tool in tools]
    assert names == ["calendar_get_event_status"]


# --- Acceptance: the tool is callable end-to-end over MCP -------------------


async def _call_calendar_get_event_status(
    calendar_id: str, event_id: str, artifact_type: str, artifact_id: str
):
    async with create_connected_server_and_client_session(mcp) as client:
        return await client.call_tool(
            "calendar_get_event_status",
            {
                "calendar_id": calendar_id,
                "event_id": event_id,
                "artifact_type": artifact_type,
                "artifact_id": artifact_id,
            },
        )


def test_calendar_get_event_status_tool_matches_direct_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = _realistic_timed_event()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=event)

    monkeypatch.setattr(
        "connectors.calendar_google.server._build_client", lambda: _mock_client(handler)
    )

    expected = calendar_get_event_status(
        calendar_id="primary", event_id="evt123", artifact_type="test_artifact", artifact_id="x1"
    )

    result = asyncio.run(
        _call_calendar_get_event_status("primary", "evt123", "test_artifact", "x1")
    )

    assert result.isError is False
    assert result.structuredContent == expected


def test_calendar_get_event_status_tool_returns_structured_error_for_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    monkeypatch.setattr(
        "connectors.calendar_google.server._build_client", lambda: _mock_client(handler)
    )

    result = asyncio.run(
        _call_calendar_get_event_status("primary", "missing", "test_artifact", "x1")
    )

    assert result.isError is True
    assert result.content
    assert "no event found" in result.content[0].text
