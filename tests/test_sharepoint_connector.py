"""Unit tests for the SharePoint connector (Story 15).

Exercises `connectors.sharepoint.server.sharepoint_get_document_status`
entirely against `httpx.MockTransport` -- no live Microsoft account or
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

from connectors.sharepoint.server import (
    AuthenticationError,
    DocumentNotFoundError,
    InvalidArtifactIdentifierError,
    InvalidItemIdentifierError,
    MalformedResponseError,
    MissingCredentialsError,
    SharePointConnectorError,
    _build_source,
    mcp,
    sharepoint_get_document_status,
)
from shared.ledger_schema import RawFact, SchemaValidationError

_TOKEN = "s3cr3t-sharepoint-token"
_BASE_URL = "https://graph.microsoft.com/v1.0"

#: Independent (not calling `_build_source`) literal re-implementation of the
#: sanitization `_build_source` performs, used to compute expected `source`
#: values in tests without being self-referential.
_SOURCE_UNSAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9_:-]")


def _expected_source(drive_id: str, item_id: str) -> str:
    safe_drive_id = _SOURCE_UNSAFE_CHARS_RE.sub("_", drive_id)
    safe_item_id = _SOURCE_UNSAFE_CHARS_RE.sub("_", item_id)
    return f"sharepoint:{safe_drive_id}/{safe_item_id}"


def _realistic_item(**overrides: Any) -> dict[str, Any]:
    item = {
        "id": "item123",
        "lastModifiedDateTime": "2026-08-20T10:00:00Z",
        "lastModifiedBy": {"user": {"email": "program-owner@example.com"}},
    }
    item.update(overrides)
    return item


def _mock_client(handler: httpx.MockTransport | Any) -> httpx.Client:
    transport = handler if isinstance(handler, httpx.MockTransport) else httpx.MockTransport(handler)
    return httpx.Client(transport=transport, timeout=10.0)


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REZOPS_SHAREPOINT_TOKEN", _TOKEN)


# --- I/O matrix row 1: happy path --------------------------------------------


def test_happy_path_returns_rawfact_shaped_dict_with_flattened_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _realistic_item()
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200, json=item)

    monkeypatch.setattr(
        "connectors.sharepoint.server._build_client", lambda: _mock_client(handler)
    )

    result = sharepoint_get_document_status(
        drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
    )

    assert result["artifact_type"] == "test_artifact"
    assert result["artifact_id"] == "x1"
    assert result["source"] == _expected_source("drive123", "item123")
    assert result["fields"]["modified_time"] == "2026-08-20T10:00:00Z"
    assert result["fields"]["last_modified_by"] == "program-owner@example.com"

    # All fields must be scalar -- none of Graph's nested objects leaked
    # through.
    for value in result["fields"].values():
        assert not isinstance(value, (dict, list))

    # Exactly one GET request, with bearer auth, hit the expected URL and
    # requested exactly the fields this connector needs.
    assert len(captured_requests) == 1
    request = captured_requests[0]
    assert request.method == "GET"
    assert (
        str(request.url).split("?", 1)[0]
        == f"{_BASE_URL}/drives/drive123/items/item123"
    )
    assert request.headers["authorization"] == f"Bearer {_TOKEN}"
    assert dict(request.url.params)["$select"] == "id,lastModifiedDateTime,lastModifiedBy"

    # The dict round-trips through RawFact construction without raising --
    # proving it is genuinely RawFact-shaped (AD-9), not merely dict-shaped.
    fact = RawFact(**result)
    assert isinstance(fact, RawFact)


def test_modified_time_and_email_are_stored_stripped_not_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`lastModifiedDateTime`/`email` are validated with `.strip()` to reject
    blank values -- but the *stored* value must be the stripped one, not the
    original string with its leading/trailing whitespace intact.
    """
    item = _realistic_item(
        lastModifiedDateTime="  2026-08-20T10:00:00Z  ",
        lastModifiedBy={"user": {"email": "  program-owner@example.com  "}},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=item)

    monkeypatch.setattr(
        "connectors.sharepoint.server._build_client", lambda: _mock_client(handler)
    )

    result = sharepoint_get_document_status(
        drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
    )

    assert result["fields"]["modified_time"] == "2026-08-20T10:00:00Z"
    assert result["fields"]["last_modified_by"] == "program-owner@example.com"


def test_last_modified_by_falls_back_to_display_name_when_email_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _realistic_item(lastModifiedBy={"user": {"displayName": "Program Owner"}})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=item)

    monkeypatch.setattr(
        "connectors.sharepoint.server._build_client", lambda: _mock_client(handler)
    )

    result = sharepoint_get_document_status(
        drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
    )

    assert result["fields"]["last_modified_by"] == "Program Owner"


def test_last_modified_by_prefers_email_over_display_name_when_both_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _realistic_item(
        lastModifiedBy={
            "user": {
                "email": "program-owner@example.com",
                "displayName": "Program Owner",
            }
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=item)

    monkeypatch.setattr(
        "connectors.sharepoint.server._build_client", lambda: _mock_client(handler)
    )

    result = sharepoint_get_document_status(
        drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
    )

    assert result["fields"]["last_modified_by"] == "program-owner@example.com"


# --- I/O matrix row 2: item has no lastModifiedBy ----------------------------


def test_item_with_no_last_modified_by_omits_last_modified_by_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _realistic_item()
    del item["lastModifiedBy"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=item)

    monkeypatch.setattr(
        "connectors.sharepoint.server._build_client", lambda: _mock_client(handler)
    )

    result = sharepoint_get_document_status(
        drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
    )

    assert result["fields"]["last_modified_by"] is None
    # Still round-trips through RawFact -- None is a valid JSON scalar.
    fact = RawFact(**result)
    assert isinstance(fact, RawFact)


# --- I/O matrix row 3: lastModifiedBy.user present with no email/displayName -


@pytest.mark.parametrize("user", [{}, {"other_field": "x"}])
def test_last_modified_by_user_present_but_missing_both_keys_omits_last_modified_by(
    monkeypatch: pytest.MonkeyPatch, user: dict[str, Any]
) -> None:
    """Distinct from the "lastModifiedBy absent entirely" case above: here
    the `lastModifiedBy.user` object itself is present in the response, but
    has neither `email` nor `displayName` at all (as opposed to either key
    present with a `null`/non-string value, which must raise -- see the
    malformed-response tests below).
    """
    item = _realistic_item(lastModifiedBy={"user": user})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=item)

    monkeypatch.setattr(
        "connectors.sharepoint.server._build_client", lambda: _mock_client(handler)
    )

    result = sharepoint_get_document_status(
        drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
    )

    assert result["fields"]["last_modified_by"] is None


def test_last_modified_by_present_but_no_user_member_omits_last_modified_by(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _realistic_item(lastModifiedBy={"application": {"displayName": "Some App"}})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=item)

    monkeypatch.setattr(
        "connectors.sharepoint.server._build_client", lambda: _mock_client(handler)
    )

    result = sharepoint_get_document_status(
        drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
    )

    assert result["fields"]["last_modified_by"] is None


# --- I/O matrix row 4: empty/whitespace/non-string drive_id or item_id ------


@pytest.mark.parametrize("bad_value", ["", "   "])
def test_empty_or_whitespace_drive_id_raises_before_any_http_request(
    monkeypatch: pytest.MonkeyPatch, bad_value: str
) -> None:
    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.sharepoint.server._build_client", spy)

    with pytest.raises(InvalidItemIdentifierError):
        sharepoint_get_document_status(
            drive_id=bad_value, item_id="item123", artifact_type="test_artifact", artifact_id="x1"
        )

    spy.assert_not_called()


@pytest.mark.parametrize("bad_value", ["", "   "])
def test_empty_or_whitespace_item_id_raises_before_any_http_request(
    monkeypatch: pytest.MonkeyPatch, bad_value: str
) -> None:
    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.sharepoint.server._build_client", spy)

    with pytest.raises(InvalidItemIdentifierError):
        sharepoint_get_document_status(
            drive_id="drive123", item_id=bad_value, artifact_type="test_artifact", artifact_id="x1"
        )

    spy.assert_not_called()


@pytest.mark.parametrize("bad_value", [123, None, 1.5, ["drive123"]])
def test_non_string_drive_id_raises_invalid_item_identifier_error(
    monkeypatch: pytest.MonkeyPatch, bad_value: Any
) -> None:
    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.sharepoint.server._build_client", spy)

    with pytest.raises(InvalidItemIdentifierError):
        sharepoint_get_document_status(
            drive_id=bad_value, item_id="item123", artifact_type="test_artifact", artifact_id="x1"
        )

    spy.assert_not_called()


@pytest.mark.parametrize("bad_value", [123, None, 1.5, ["item123"]])
def test_non_string_item_id_raises_invalid_item_identifier_error(
    monkeypatch: pytest.MonkeyPatch, bad_value: Any
) -> None:
    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.sharepoint.server._build_client", spy)

    with pytest.raises(InvalidItemIdentifierError):
        sharepoint_get_document_status(
            drive_id="drive123", item_id=bad_value, artifact_type="test_artifact", artifact_id="x1"
        )

    spy.assert_not_called()


# --- I/O matrix row 5: empty/whitespace/non-string artifact_type/artifact_id


@pytest.mark.parametrize("bad_value", ["", "   "])
def test_empty_or_whitespace_artifact_type_raises_invalid_identifier_error(
    monkeypatch: pytest.MonkeyPatch, bad_value: str
) -> None:
    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.sharepoint.server._build_client", spy)

    with pytest.raises(InvalidArtifactIdentifierError):
        sharepoint_get_document_status(
            drive_id="drive123", item_id="item123", artifact_type=bad_value, artifact_id="x1"
        )

    spy.assert_not_called()


@pytest.mark.parametrize("bad_value", ["", "   "])
def test_empty_or_whitespace_artifact_id_raises_invalid_identifier_error(
    monkeypatch: pytest.MonkeyPatch, bad_value: str
) -> None:
    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.sharepoint.server._build_client", spy)

    with pytest.raises(InvalidArtifactIdentifierError):
        sharepoint_get_document_status(
            drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id=bad_value
        )

    spy.assert_not_called()


@pytest.mark.parametrize("bad_value", [123, None, 1.5, ["test_artifact"]])
def test_non_string_artifact_type_raises_invalid_artifact_identifier_error(
    monkeypatch: pytest.MonkeyPatch, bad_value: Any
) -> None:
    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.sharepoint.server._build_client", spy)

    with pytest.raises(InvalidArtifactIdentifierError):
        sharepoint_get_document_status(
            drive_id="drive123", item_id="item123", artifact_type=bad_value, artifact_id="x1"
        )

    spy.assert_not_called()


@pytest.mark.parametrize("bad_value", [123, None, 1.5, ["x1"]])
def test_non_string_artifact_id_raises_invalid_artifact_identifier_error(
    monkeypatch: pytest.MonkeyPatch, bad_value: Any
) -> None:
    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.sharepoint.server._build_client", spy)

    with pytest.raises(InvalidArtifactIdentifierError):
        sharepoint_get_document_status(
            drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id=bad_value
        )

    spy.assert_not_called()


# --- I/O matrix row 6: missing/blank/control-char credential -----------------


def test_missing_credential_raises_before_any_http_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REZOPS_SHAREPOINT_TOKEN", raising=False)

    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.sharepoint.server._build_client", spy)

    with pytest.raises(MissingCredentialsError):
        sharepoint_get_document_status(
            drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
        )

    spy.assert_not_called()


@pytest.mark.parametrize("blank_value", ["", "   "])
def test_blank_credential_raises_before_any_http_request(
    monkeypatch: pytest.MonkeyPatch, blank_value: str
) -> None:
    monkeypatch.setenv("REZOPS_SHAREPOINT_TOKEN", blank_value)

    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.sharepoint.server._build_client", spy)

    with pytest.raises(MissingCredentialsError):
        sharepoint_get_document_status(
            drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
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
    monkeypatch.setenv("REZOPS_SHAREPOINT_TOKEN", bad_token)

    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.sharepoint.server._build_client", spy)

    with pytest.raises(MissingCredentialsError):
        sharepoint_get_document_status(
            drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
        )

    spy.assert_not_called()


def test_token_with_incidental_whitespace_is_stripped_before_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A token env var set with incidental leading/trailing whitespace must
    be sent to Microsoft Graph stripped -- not padded verbatim.
    """
    monkeypatch.setenv("REZOPS_SHAREPOINT_TOKEN", f"  {_TOKEN}  ")
    item = _realistic_item()
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200, json=item)

    monkeypatch.setattr(
        "connectors.sharepoint.server._build_client", lambda: _mock_client(handler)
    )

    sharepoint_get_document_status(
        drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
    )

    assert len(captured_requests) == 1
    assert captured_requests[0].headers["authorization"] == f"Bearer {_TOKEN}"


def test_non_ascii_token_raises_before_any_http_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-ASCII credential (e.g. an accented character or emoji) must be
    rejected before any HTTP request is attempted, the same way a control
    character already is.
    """
    monkeypatch.setenv("REZOPS_SHAREPOINT_TOKEN", "s3cr3t-téken")

    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.sharepoint.server._build_client", spy)

    with pytest.raises(MissingCredentialsError):
        sharepoint_get_document_status(
            drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
        )

    spy.assert_not_called()


def test_token_with_trailing_control_char_raises_before_any_http_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A control character sitting at the edge of the token (e.g. a trailing
    CRLF) must still be rejected -- stripping incidental whitespace must
    never silently clean it away before the control-character check runs.
    """
    monkeypatch.setenv("REZOPS_SHAREPOINT_TOKEN", "secret\r\n")

    spy = Mock(side_effect=AssertionError("HTTP client should never be constructed"))
    monkeypatch.setattr("connectors.sharepoint.server._build_client", spy)

    with pytest.raises(MissingCredentialsError):
        sharepoint_get_document_status(
            drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
        )

    spy.assert_not_called()


# --- Story 16: _build_source per-segment sanitization is injective --------


def test_build_source_does_not_collide_for_slash_containing_segments() -> None:
    """Two distinct (drive_id, item_id) pairs that collide under the old
    join-then-sanitize-the-whole-string scheme must produce two different
    `source` strings now that each segment is sanitized individually before
    being joined with a literal `/`.
    """
    source_one = _build_source("a/b", "c")
    source_two = _build_source("a", "b/c")

    assert source_one != source_two


# --- I/O matrix row 7: item not found ----------------------------------------


def test_404_raises_document_not_found_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    monkeypatch.setattr(
        "connectors.sharepoint.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(DocumentNotFoundError):
        sharepoint_get_document_status(
            drive_id="drive123", item_id="missing", artifact_type="test_artifact", artifact_id="x1"
        )


# --- I/O matrix row 8: auth failure ------------------------------------------


@pytest.mark.parametrize("status_code", [401, 403])
def test_auth_failure_raises_authentication_error(
    monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": "unauthorized"})

    monkeypatch.setattr(
        "connectors.sharepoint.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(AuthenticationError):
        sharepoint_get_document_status(
            drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
        )


# --- I/O matrix row 9: other non-2xx -----------------------------------------


def test_other_non_success_status_raises_sharepoint_connector_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A distinctive marker standing in for real item metadata content that a
    # 500 response body might legitimately contain. It must never appear in
    # the raised exception's message -- only the status code and a generic
    # note may.
    sensitive_marker = "CONFIDENTIAL-ITEM-DETAILS-89213"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=f"internal server error: {sensitive_marker}")

    monkeypatch.setattr(
        "connectors.sharepoint.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(SharePointConnectorError) as exc_info:
        sharepoint_get_document_status(
            drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
        )

    message = str(exc_info.value)
    assert sensitive_marker not in message
    assert "500" in message


def test_connection_error_raises_sharepoint_connector_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr(
        "connectors.sharepoint.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(SharePointConnectorError):
        sharepoint_get_document_status(
            drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
        )


def test_timeout_raises_sharepoint_connector_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    monkeypatch.setattr(
        "connectors.sharepoint.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(SharePointConnectorError):
        sharepoint_get_document_status(
            drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
        )


# --- drive_id/item_id are URL-encoded in the request path -------------------


def test_drive_id_and_item_id_are_url_encoded_in_the_request_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `drive_id`/`item_id` containing "/", "?", or whitespace must not be
    able to alter the request path or inject extra query parameters -- both
    are percent-encoded before being placed in the path.
    """
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200, json=_realistic_item())

    monkeypatch.setattr(
        "connectors.sharepoint.server._build_client", lambda: _mock_client(handler)
    )

    sharepoint_get_document_status(
        drive_id="abc/../other?evil=1",
        item_id="def/../other?evil=1",
        artifact_type="test_artifact",
        artifact_id="x1",
    )

    request = captured_requests[0]
    path = str(request.url).split("?", 1)[0]
    assert path == (
        f"{_BASE_URL}/drives/abc%2F..%2Fother%3Fevil%3D1"
        "/items/def%2F..%2Fother%3Fevil%3D1"
    )
    # The injected "?evil=1" must not have become a real query parameter --
    # only the connector's own "$select" parameter is present.
    assert "evil" not in dict(request.url.params)


# --- I/O matrix row 10: malformed 200 body -----------------------------------


def test_response_missing_last_modified_date_time_raises_malformed_response_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incomplete_item = _realistic_item()
    del incomplete_item["lastModifiedDateTime"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=incomplete_item)

    monkeypatch.setattr(
        "connectors.sharepoint.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError):
        sharepoint_get_document_status(
            drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
        )


def test_response_missing_last_modified_date_time_error_message_omits_raw_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exception message for the missing-field case must not leak the
    raw response body -- consistent with the non-2xx branch's own careful
    non-leaking behavior elsewhere in this module.
    """
    sensitive_marker = "CONFIDENTIAL-ITEM-NAME-40213"
    incomplete_item = _realistic_item(name=sensitive_marker)
    del incomplete_item["lastModifiedDateTime"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=incomplete_item)

    monkeypatch.setattr(
        "connectors.sharepoint.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError) as exc_info:
        sharepoint_get_document_status(
            drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
        )

    assert sensitive_marker not in str(exc_info.value)


@pytest.mark.parametrize("bad_modified_time", [None, 12345, ["2026-08-20"], {}, "", "   "])
def test_null_empty_or_non_string_modified_time_raises_malformed_response_error(
    monkeypatch: pytest.MonkeyPatch, bad_modified_time: Any
) -> None:
    """A `null`, non-string, or blank `lastModifiedDateTime` value is just as
    unusable as a missing key and must not silently produce a `RawFact` with
    an unusable field value.
    """
    item = _realistic_item(lastModifiedDateTime=bad_modified_time)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=item)

    monkeypatch.setattr(
        "connectors.sharepoint.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError):
        sharepoint_get_document_status(
            drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
        )


def test_response_not_valid_json_raises_malformed_response_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json at all")

    monkeypatch.setattr(
        "connectors.sharepoint.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError):
        sharepoint_get_document_status(
            drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
        )


def test_response_not_an_object_raises_malformed_response_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["not", "an", "object"])

    monkeypatch.setattr(
        "connectors.sharepoint.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError):
        sharepoint_get_document_status(
            drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
        )


def test_response_not_an_object_error_message_omits_raw_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sensitive_marker = "CONFIDENTIAL-BODY-CONTENT-55901"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[sensitive_marker])

    monkeypatch.setattr(
        "connectors.sharepoint.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError) as exc_info:
        sharepoint_get_document_status(
            drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
        )

    assert sensitive_marker not in str(exc_info.value)


# --- I/O matrix row 11: lastModifiedBy/user present but malformed ----------


@pytest.mark.parametrize("bad_last_modified_by", ["a string, not an object", 12345, ["not-an-object"]])
def test_last_modified_by_not_an_object_raises_malformed_response_error(
    monkeypatch: pytest.MonkeyPatch, bad_last_modified_by: Any
) -> None:
    item = _realistic_item(lastModifiedBy=bad_last_modified_by)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=item)

    monkeypatch.setattr(
        "connectors.sharepoint.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError):
        sharepoint_get_document_status(
            drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
        )


def test_last_modified_by_not_an_object_error_message_omits_raw_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sensitive_marker = "CONFIDENTIAL-USER-NOTE-33018"
    item = _realistic_item(lastModifiedBy=sensitive_marker)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=item)

    monkeypatch.setattr(
        "connectors.sharepoint.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError) as exc_info:
        sharepoint_get_document_status(
            drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
        )

    assert sensitive_marker not in str(exc_info.value)


@pytest.mark.parametrize("bad_user", ["a string, not an object", 12345, ["not-an-object"]])
def test_last_modified_by_user_not_an_object_raises_malformed_response_error(
    monkeypatch: pytest.MonkeyPatch, bad_user: Any
) -> None:
    item = _realistic_item(lastModifiedBy={"user": bad_user})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=item)

    monkeypatch.setattr(
        "connectors.sharepoint.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError):
        sharepoint_get_document_status(
            drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
        )


@pytest.mark.parametrize("bad_email_value", [None, 12345, ["a@example.com"], {}, "", "   "])
def test_non_string_email_raises_malformed_response_error(
    monkeypatch: pytest.MonkeyPatch, bad_email_value: Any
) -> None:
    item = _realistic_item(lastModifiedBy={"user": {"email": bad_email_value}})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=item)

    monkeypatch.setattr(
        "connectors.sharepoint.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError):
        sharepoint_get_document_status(
            drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
        )


@pytest.mark.parametrize("bad_display_name_value", [None, 12345, ["Program Owner"], {}, "", "   "])
def test_non_string_display_name_raises_malformed_response_error(
    monkeypatch: pytest.MonkeyPatch, bad_display_name_value: Any
) -> None:
    item = _realistic_item(
        lastModifiedBy={"user": {"displayName": bad_display_name_value}}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=item)

    monkeypatch.setattr(
        "connectors.sharepoint.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError):
        sharepoint_get_document_status(
            drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
        )


def test_last_modified_by_user_email_error_message_omits_raw_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The `email`-flattening error path must not embed the raw nested
    object content in the exception message -- matching the exact test shape
    that caught CMDB's Story 7 redaction regression (planting a sensitive
    value in a malformed 200 body and asserting it never appears in the
    raised exception's message).
    """
    sensitive_marker = "CONFIDENTIAL-EMAIL-NOTE-77102"
    item = _realistic_item(
        lastModifiedBy={"user": {"email": None, "note": sensitive_marker}}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=item)

    monkeypatch.setattr(
        "connectors.sharepoint.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError) as exc_info:
        sharepoint_get_document_status(
            drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
        )

    assert sensitive_marker not in str(exc_info.value)


def test_non_scalar_field_value_that_reaches_rawfact_construction_raises_malformed_response_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defensive regression test for the RawFact-construction error handling.

    Flattening is expected to reduce every field to a scalar, but if a
    non-scalar value somehow still reaches `RawFact` construction, that must
    be converted to `MalformedResponseError` -- never allowed to escape as a
    raw `SchemaValidationError` -- by the narrowed `except
    SchemaValidationError` clause around that construction.

    Since `_parse_document_response` only ever emits scalars for
    `modified_time`/`last_modified_by`, this is exercised via a monkeypatched
    `_parse_document_response` returning a deliberately non-scalar field.
    """
    def fake_parse_document_response(
        response: httpx.Response, drive_id: str, item_id: str
    ) -> dict[str, Any]:
        return {"modified_time": "2026-08-20T10:00:00Z", "unexpected": {"nested": "object"}}

    monkeypatch.setattr(
        "connectors.sharepoint.server._parse_document_response",
        fake_parse_document_response,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_realistic_item())

    monkeypatch.setattr(
        "connectors.sharepoint.server._build_client", lambda: _mock_client(handler)
    )

    with pytest.raises(MalformedResponseError) as exc_info:
        sharepoint_get_document_status(
            drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
        )

    # Must not have escaped as the raw, un-translated SchemaValidationError.
    assert not isinstance(exc_info.value, SchemaValidationError)


# --- Error hierarchy ---------------------------------------------------------


@pytest.mark.parametrize(
    "error_cls",
    [
        InvalidItemIdentifierError,
        InvalidArtifactIdentifierError,
        MissingCredentialsError,
        DocumentNotFoundError,
        AuthenticationError,
        MalformedResponseError,
    ],
)
def test_all_typed_errors_are_sharepoint_connector_errors(error_cls: type) -> None:
    assert issubclass(error_cls, SharePointConnectorError)


def test_invalid_item_identifier_error_is_also_a_value_error() -> None:
    assert issubclass(InvalidItemIdentifierError, ValueError)


def test_invalid_artifact_identifier_error_is_also_a_value_error() -> None:
    assert issubclass(InvalidArtifactIdentifierError, ValueError)


# --- Acceptance: exactly one read-only tool, no write tool ------------------


def test_server_exposes_exactly_one_read_only_tool() -> None:
    tools = asyncio.run(mcp.list_tools())
    names = [tool.name for tool in tools]
    assert names == ["sharepoint_get_document_status"]


# --- Acceptance: the tool never issues any write HTTP method ----------------


def test_tool_never_issues_a_write_http_method(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200, json=_realistic_item())

    monkeypatch.setattr(
        "connectors.sharepoint.server._build_client", lambda: _mock_client(handler)
    )

    sharepoint_get_document_status(
        drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
    )

    assert len(captured_requests) == 1
    assert captured_requests[0].method == "GET"


# --- Acceptance: the tool is callable end-to-end over MCP -------------------


async def _call_sharepoint_get_document_status(
    drive_id: str, item_id: str, artifact_type: str, artifact_id: str
):
    async with create_connected_server_and_client_session(mcp) as client:
        return await client.call_tool(
            "sharepoint_get_document_status",
            {
                "drive_id": drive_id,
                "item_id": item_id,
                "artifact_type": artifact_type,
                "artifact_id": artifact_id,
            },
        )


def test_sharepoint_get_document_status_tool_matches_direct_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _realistic_item()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=item)

    monkeypatch.setattr(
        "connectors.sharepoint.server._build_client", lambda: _mock_client(handler)
    )

    expected = sharepoint_get_document_status(
        drive_id="drive123", item_id="item123", artifact_type="test_artifact", artifact_id="x1"
    )

    result = asyncio.run(
        _call_sharepoint_get_document_status("drive123", "item123", "test_artifact", "x1")
    )

    assert result.isError is False
    assert result.structuredContent == expected


def test_sharepoint_get_document_status_tool_returns_structured_error_for_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    monkeypatch.setattr(
        "connectors.sharepoint.server._build_client", lambda: _mock_client(handler)
    )

    result = asyncio.run(
        _call_sharepoint_get_document_status("drive123", "missing", "test_artifact", "x1")
    )

    assert result.isError is True
    assert result.content
    assert "no item found" in result.content[0].text
