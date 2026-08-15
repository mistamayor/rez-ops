"""Unit tests for the ticketing connector (Story 5).

Exercises `connectors.ticketing.server.ticketing_get_ticket_status` entirely
against `httpx.MockTransport` -- no live ServiceNow instance or credentials
are used or required. `_build_client` is monkeypatched per-test to return an
`httpx.Client` wired to a `MockTransport` (or, for the missing-credentials
case, to a spy that must never be called).
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from unittest.mock import Mock

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from connectors.ticketing.server import (
    AuthenticationError,
    InvalidArtifactIdentifierError,
    InvalidInstanceUrlError,
    InvalidTicketIdentifierError,
    MalformedResponseError,
    MissingCredentialsError,
    TicketNotFoundError,
    TicketingConnectorError,
    ticketing_get_ticket_status,
    mcp,
)
from shared.ledger_schema import RawFact, SchemaValidationError

_INSTANCE_URL = "https://dev12345.service-now.com"
_TOKEN = "s3cr3t-token"

#: Independent (not calling `_build_source`) literal re-implementation of the
#: sanitization `_build_source` performs, used to compute expected `source`
#: values in tests without being self-referential.
_SOURCE_UNSAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9_:-]")


def _expected_source(instance_url: str, table: str, sys_id: str) -> str:
    raw = f"servicenow:{instance_url}/{table}/{sys_id}"
    return _SOURCE_UNSAFE_CHARS_RE.sub("_", raw)


def _realistic_record(**overrides: Any) -> dict[str, Any]:
    record = {
        "number": "INC0012345",
        "state": "2",
        "assigned_to": "jane.doe",
        "sys_updated_on": "2026-08-14 10:15:00",
        "short_description": "Investigate failed DR failover test",
    }
    record.update(overrides)
    return record


def _mock_client(handler: httpx.MockTransport | Any) -> httpx.Client:
    transport = handler if isinstance(handler, httpx.MockTransport) else httpx.MockTransport(handler)
    return httpx.Client(transport=transport, timeout=10.0)


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REZOPS_TICKETING_INSTANCE_URL", _INSTANCE_URL)
    monkeypatch.setenv("REZOPS_TICKETING_TOKEN", _TOKEN)


# --- I/O matrix row 1: happy path ------------------------------------------


def test_happy_path_returns_rawfact_shaped_dict_with_ticket_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _realistic_record()
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200, json={"result": record})

    monkeypatch.setattr(
        "connectors.ticketing.server._build_client", lambda: _mock_client(handler)
    )

    result = ticketing_get_ticket_status(
        table="incident",
        sys_id="abc123",
        artifact_type="test_artifact",
        artifact_id="x1",
    )

    assert result["artifact_type"] == "test_artifact"
    assert result["artifact_id"] == "x1"
    assert result["source"] == _expected_source(_INSTANCE_URL, "incident", "abc123")
    assert result["fields"]["number"] == "INC0012345"
    assert result["fields"]["state"] == "2"
    assert result["fields"]["assigned_to"] == "jane.doe"
    assert result["fields"]["sys_updated_on"] == "2026-08-14 10:15:00"
    assert result["fields"]["short_description"] == "Investigate failed DR failover test"

    # Exactly one GET request, with bearer auth, hit the expected URL.
    assert len(captured_requests) == 1
    request = captured_requests[0]
    assert request.method == "GET"
    assert str(request.url).split("?", 1)[0] == f"{_INSTANCE_URL}/api/now/table/incident/abc123"
    assert request.headers["authorization"] == f"Bearer {_TOKEN}"

    # The single most important fix (review layer #1): sysparm_display_value
    # must be requested, or real ServiceNow reference fields like
    # assigned_to come back as nested {"link": ..., "value": ...} objects
    # instead of a flat display string -- and sysparm_fields restricts the
    # response to just the fields this connector reads.
    query = dict(request.url.params)
    assert query["sysparm_display_value"] == "true"
    assert query["sysparm_fields"] == "number,state,assigned_to,sys_updated_on,short_description"

    # The dict round-trips through RawFact construction without raising --
    # proving it is genuinely RawFact-shaped (AD-9), not merely dict-shaped.
    fact = RawFact(**result)
    assert isinstance(fact, RawFact)


def test_happy_path_strips_trailing_slash_from_instance_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REZOPS_TICKETING_INSTANCE_URL", _INSTANCE_URL + "/")
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200, json={"result": _realistic_record()})

    monkeypatch.setattr(
        "connectors.ticketing.server._build_client", lambda: _mock_client(handler)
    )

    ticketing_get_ticket_status(
        table="incident", sys_id="abc123", artifact_type="test_artifact", artifact_id="x1"
    )

    assert (
        str(captured_requests[0].url).split("?", 1)[0]
        == f"{_INSTANCE_URL}/api/now/table/incident/abc123"
    )


def test_table_and_sys_id_are_url_encoded_in_the_request_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `table`/`sys_id` containing "/", "?", "#", or whitespace must not be
    able to alter the request path or inject extra query parameters -- both
    values are percent-encoded before being placed in the path.
    """
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200, json={"result": _realistic_record()})

    monkeypatch.setattr(
        "connectors.ticketing.server._build_client", lambda: _mock_client(handler)
    )

    ticketing_get_ticket_status(
        table="incident/../sys_user",
        sys_id="abc 123?evil=1",
        artifact_type="test_artifact",
        artifact_id="x1",
    )

    request = captured_requests[0]
    path = str(request.url).split("?", 1)[0]
    assert path == (
        f"{_INSTANCE_URL}/api/now/table/incident%2F..%2Fsys_user/abc%20123%3Fevil%3D1"
    )
    # The injected "?evil=1" must not have become a real query parameter.
    assert "evil" not in dict(request.url.params)


# --- Instance URL validation -------------------------------------------------


@pytest.mark.parametrize(
    "bad_instance_url",
    [
        "http://dev12345.service-now.com",
        "dev12345.service-now.com",
        "ftp://dev12345.service-now.com",
    ],
)
def test_non_https_instance_url_raises_before_any_http_request(
    monkeypatch: pytest.MonkeyPatch, bad_instance_url: str
) -> None:
    monkeypatch.setenv("REZOPS_TICKETING_INSTANCE_URL", bad_instance_url)

    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.ticketing.server._build_client", spy)

    with pytest.raises(InvalidInstanceUrlError):
        ticketing_get_ticket_status(
            table="incident", sys_id="abc123", artifact_type="test_artifact", artifact_id="x1"
        )

    spy.assert_not_called()


@pytest.mark.parametrize("slashes_only", ["/", "///", "////////"])
def test_instance_url_of_only_slashes_raises_invalid_instance_url_error(
    monkeypatch: pytest.MonkeyPatch, slashes_only: str
) -> None:
    """A value that collapses to "" after `rstrip("/")` must be rejected --
    it passes the pre-existing non-blank check on the raw value but must not
    be allowed to reach request construction.
    """
    monkeypatch.setenv("REZOPS_TICKETING_INSTANCE_URL", slashes_only)

    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.ticketing.server._build_client", spy)

    with pytest.raises(InvalidInstanceUrlError):
        ticketing_get_ticket_status(
            table="incident", sys_id="abc123", artifact_type="test_artifact", artifact_id="x1"
        )

    spy.assert_not_called()


def test_invalid_instance_url_error_is_a_ticketing_connector_error() -> None:
    assert issubclass(InvalidInstanceUrlError, TicketingConnectorError)
    assert issubclass(InvalidInstanceUrlError, ValueError)


# --- Non-string identifier inputs --------------------------------------------


@pytest.mark.parametrize("bad_value", [123, None, 1.5, ["incident"]])
def test_non_string_table_raises_invalid_ticket_identifier_error(
    monkeypatch: pytest.MonkeyPatch, bad_value: Any
) -> None:
    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.ticketing.server._build_client", spy)

    with pytest.raises(InvalidTicketIdentifierError):
        ticketing_get_ticket_status(
            table=bad_value, sys_id="abc123", artifact_type="test_artifact", artifact_id="x1"
        )

    spy.assert_not_called()


@pytest.mark.parametrize("bad_value", [123, None, 1.5])
def test_non_string_sys_id_raises_invalid_ticket_identifier_error(
    monkeypatch: pytest.MonkeyPatch, bad_value: Any
) -> None:
    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.ticketing.server._build_client", spy)

    with pytest.raises(InvalidTicketIdentifierError):
        ticketing_get_ticket_status(
            table="incident", sys_id=bad_value, artifact_type="test_artifact", artifact_id="x1"
        )

    spy.assert_not_called()


@pytest.mark.parametrize("bad_value", [123, None, 1.5])
def test_non_string_artifact_type_raises_invalid_artifact_identifier_error(
    monkeypatch: pytest.MonkeyPatch, bad_value: Any
) -> None:
    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.ticketing.server._build_client", spy)

    with pytest.raises(InvalidArtifactIdentifierError):
        ticketing_get_ticket_status(
            table="incident", sys_id="abc123", artifact_type=bad_value, artifact_id="x1"
        )

    spy.assert_not_called()


@pytest.mark.parametrize("bad_value", [123, None, 1.5])
def test_non_string_artifact_id_raises_invalid_artifact_identifier_error(
    monkeypatch: pytest.MonkeyPatch, bad_value: Any
) -> None:
    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.ticketing.server._build_client", spy)

    with pytest.raises(InvalidArtifactIdentifierError):
        ticketing_get_ticket_status(
            table="incident", sys_id="abc123", artifact_type="test_artifact", artifact_id=bad_value
        )

    spy.assert_not_called()


# --- I/O matrix row 2: record not found ------------------------------------


def test_404_raises_ticket_not_found_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    monkeypatch.setattr(
        "connectors.ticketing.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(TicketNotFoundError):
        ticketing_get_ticket_status(
            table="incident", sys_id="missing", artifact_type="test_artifact", artifact_id="x1"
        )


# --- I/O matrix row 3: auth failure -----------------------------------------


@pytest.mark.parametrize("status_code", [401, 403])
def test_auth_failure_raises_authentication_error(
    monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": "unauthorized"})

    monkeypatch.setattr(
        "connectors.ticketing.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(AuthenticationError):
        ticketing_get_ticket_status(
            table="incident", sys_id="abc123", artifact_type="test_artifact", artifact_id="x1"
        )


def test_other_non_success_status_raises_ticketing_connector_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A distinctive marker standing in for real ticket content that a 500
    # response body might legitimately contain (e.g. an error page rendering
    # back submitted data). It must never appear in the raised exception's
    # message -- only the status code and a generic note may.
    sensitive_marker = "CONFIDENTIAL-INCIDENT-DETAILS-89213"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=f"internal server error: {sensitive_marker}")

    monkeypatch.setattr(
        "connectors.ticketing.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(TicketingConnectorError) as exc_info:
        ticketing_get_ticket_status(
            table="incident", sys_id="abc123", artifact_type="test_artifact", artifact_id="x1"
        )

    message = str(exc_info.value)
    assert sensitive_marker not in message
    assert "500" in message


# --- I/O matrix row 4: missing credentials ----------------------------------


@pytest.mark.parametrize(
    "missing_var",
    ["REZOPS_TICKETING_INSTANCE_URL", "REZOPS_TICKETING_TOKEN"],
)
def test_missing_credential_raises_before_any_http_request(
    monkeypatch: pytest.MonkeyPatch, missing_var: str
) -> None:
    monkeypatch.delenv(missing_var, raising=False)

    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.ticketing.server._build_client", spy)

    with pytest.raises(MissingCredentialsError):
        ticketing_get_ticket_status(
            table="incident", sys_id="abc123", artifact_type="test_artifact", artifact_id="x1"
        )

    spy.assert_not_called()


@pytest.mark.parametrize("blank_value", ["", "   "])
def test_blank_credential_raises_before_any_http_request(
    monkeypatch: pytest.MonkeyPatch, blank_value: str
) -> None:
    monkeypatch.setenv("REZOPS_TICKETING_INSTANCE_URL", blank_value)

    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.ticketing.server._build_client", spy)

    with pytest.raises(MissingCredentialsError):
        ticketing_get_ticket_status(
            table="incident", sys_id="abc123", artifact_type="test_artifact", artifact_id="x1"
        )

    spy.assert_not_called()


# --- I/O matrix row 5: network/timeout failure ------------------------------


def test_connection_error_raises_ticketing_connector_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr(
        "connectors.ticketing.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(TicketingConnectorError):
        ticketing_get_ticket_status(
            table="incident", sys_id="abc123", artifact_type="test_artifact", artifact_id="x1"
        )


def test_timeout_raises_ticketing_connector_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    monkeypatch.setattr(
        "connectors.ticketing.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(TicketingConnectorError):
        ticketing_get_ticket_status(
            table="incident", sys_id="abc123", artifact_type="test_artifact", artifact_id="x1"
        )


# --- I/O matrix row 6: empty/whitespace table or sys_id ---------------------


@pytest.mark.parametrize("bad_value", ["", "   "])
def test_empty_or_whitespace_table_raises_before_any_http_request(
    monkeypatch: pytest.MonkeyPatch, bad_value: str
) -> None:
    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.ticketing.server._build_client", spy)

    with pytest.raises(InvalidTicketIdentifierError):
        ticketing_get_ticket_status(
            table=bad_value, sys_id="abc123", artifact_type="test_artifact", artifact_id="x1"
        )

    spy.assert_not_called()


@pytest.mark.parametrize("bad_value", ["", "   "])
def test_empty_or_whitespace_sys_id_raises_before_any_http_request(
    monkeypatch: pytest.MonkeyPatch, bad_value: str
) -> None:
    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.ticketing.server._build_client", spy)

    with pytest.raises(InvalidTicketIdentifierError):
        ticketing_get_ticket_status(
            table="incident", sys_id=bad_value, artifact_type="test_artifact", artifact_id="x1"
        )

    spy.assert_not_called()


@pytest.mark.parametrize("bad_value", ["", "   "])
def test_empty_or_whitespace_artifact_type_raises_invalid_identifier_error(
    monkeypatch: pytest.MonkeyPatch, bad_value: str
) -> None:
    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.ticketing.server._build_client", spy)

    with pytest.raises(InvalidArtifactIdentifierError):
        ticketing_get_ticket_status(
            table="incident", sys_id="abc123", artifact_type=bad_value, artifact_id="x1"
        )

    spy.assert_not_called()


@pytest.mark.parametrize("bad_value", ["", "   "])
def test_empty_or_whitespace_artifact_id_raises_invalid_identifier_error(
    monkeypatch: pytest.MonkeyPatch, bad_value: str
) -> None:
    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.ticketing.server._build_client", spy)

    with pytest.raises(InvalidArtifactIdentifierError):
        ticketing_get_ticket_status(
            table="incident", sys_id="abc123", artifact_type="test_artifact", artifact_id=bad_value
        )

    spy.assert_not_called()


# --- I/O matrix row 7: malformed response body ------------------------------


def test_response_missing_expected_field_raises_malformed_response_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incomplete_record = _realistic_record()
    del incomplete_record["assigned_to"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": incomplete_record})

    monkeypatch.setattr(
        "connectors.ticketing.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError):
        ticketing_get_ticket_status(
            table="incident", sys_id="abc123", artifact_type="test_artifact", artifact_id="x1"
        )


def test_response_missing_result_envelope_raises_malformed_response_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    monkeypatch.setattr(
        "connectors.ticketing.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError):
        ticketing_get_ticket_status(
            table="incident", sys_id="abc123", artifact_type="test_artifact", artifact_id="x1"
        )


def test_response_not_valid_json_raises_malformed_response_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json at all")

    monkeypatch.setattr(
        "connectors.ticketing.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError):
        ticketing_get_ticket_status(
            table="incident", sys_id="abc123", artifact_type="test_artifact", artifact_id="x1"
        )


def test_response_result_not_an_object_raises_malformed_response_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": "not-an-object"})

    monkeypatch.setattr(
        "connectors.ticketing.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError):
        ticketing_get_ticket_status(
            table="incident", sys_id="abc123", artifact_type="test_artifact", artifact_id="x1"
        )


def test_non_scalar_field_value_that_reaches_rawfact_construction_raises_malformed_response_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defensive regression test for the RawFact-construction error handling.

    `sysparm_display_value=true` (fix #1) is expected to make ServiceNow
    return flat scalar values for every field, but `_parse_ticket_response`
    only checks that expected keys are *present* -- it never checks their
    *type*. If a non-scalar value (e.g. a raw reference-field object) somehow
    still reaches `RawFact` construction, `RawFact.__post_init__` raises
    `SchemaValidationError`, and this must be converted to
    `MalformedResponseError` -- never allowed to escape as a raw
    `SchemaValidationError` -- by the narrowed `except SchemaValidationError`
    clause around that construction.
    """
    record = _realistic_record(
        assigned_to={"link": "https://dev12345.service-now.com/sys_user/abc", "value": "abc"}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": record})

    monkeypatch.setattr(
        "connectors.ticketing.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError) as exc_info:
        ticketing_get_ticket_status(
            table="incident", sys_id="abc123", artifact_type="test_artifact", artifact_id="x1"
        )

    # Must not have escaped as the raw, un-translated SchemaValidationError.
    assert not isinstance(exc_info.value, SchemaValidationError)


# --- Error hierarchy ---------------------------------------------------------


@pytest.mark.parametrize(
    "error_cls",
    [
        InvalidTicketIdentifierError,
        InvalidArtifactIdentifierError,
        InvalidInstanceUrlError,
        MissingCredentialsError,
        TicketNotFoundError,
        AuthenticationError,
        MalformedResponseError,
    ],
)
def test_all_typed_errors_are_ticketing_connector_errors(error_cls: type) -> None:
    assert issubclass(error_cls, TicketingConnectorError)


def test_invalid_ticket_identifier_error_is_also_a_value_error() -> None:
    assert issubclass(InvalidTicketIdentifierError, ValueError)


def test_invalid_artifact_identifier_error_is_also_a_value_error() -> None:
    assert issubclass(InvalidArtifactIdentifierError, ValueError)


# --- Acceptance: exactly one read-only tool, no write tool ------------------


def test_server_exposes_exactly_one_read_only_tool() -> None:
    tools = asyncio.run(mcp.list_tools())
    names = [tool.name for tool in tools]
    assert names == ["ticketing_get_ticket_status"]


# --- Acceptance: the tool is callable end-to-end over MCP -------------------


async def _call_ticketing_get_ticket_status(
    table: str, sys_id: str, artifact_type: str, artifact_id: str
):
    async with create_connected_server_and_client_session(mcp) as client:
        return await client.call_tool(
            "ticketing_get_ticket_status",
            {
                "table": table,
                "sys_id": sys_id,
                "artifact_type": artifact_type,
                "artifact_id": artifact_id,
            },
        )


def test_ticketing_get_ticket_status_tool_matches_direct_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _realistic_record()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": record})

    monkeypatch.setattr(
        "connectors.ticketing.server._build_client", lambda: _mock_client(handler)
    )

    expected = ticketing_get_ticket_status(
        table="incident", sys_id="abc123", artifact_type="test_artifact", artifact_id="x1"
    )

    result = asyncio.run(
        _call_ticketing_get_ticket_status("incident", "abc123", "test_artifact", "x1")
    )

    assert result.isError is False
    assert result.structuredContent == expected


def test_ticketing_get_ticket_status_tool_returns_structured_error_for_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    monkeypatch.setattr(
        "connectors.ticketing.server._build_client", lambda: _mock_client(handler)
    )

    result = asyncio.run(
        _call_ticketing_get_ticket_status("incident", "missing", "test_artifact", "x1")
    )

    assert result.isError is True
    assert result.content
    assert "no record found" in result.content[0].text
