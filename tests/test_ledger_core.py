"""Unit tests for the shared schema + ledger-core foundation (Story 1).

Every test uses only synthetic RawFacts -- no real connector exists yet -- and
writes to an isolated `ledger_data`-named directory under pytest's tmp_path,
never the real, git-committed ledger_data/ at the repo root.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from ledger_core import server as server_module
from ledger_core.log import LogFormatError, append_event, read_events
from ledger_core.projection import get_record
from ledger_core.server import mcp
from shared.ledger_schema import LedgerRecord, RawFact, SchemaValidationError


@pytest.fixture
def ledger_dir(tmp_path: Path) -> Path:
    return tmp_path / "ledger_data"


# --- I/O matrix row 1: new RawFact ingested -------------------------------


def test_new_rawfact_ingested_appends_event_and_projects_unknown_confidence(
    ledger_dir: Path,
) -> None:
    fact = RawFact(
        artifact_type="test_artifact",
        artifact_id="x1",
        source="synthetic:test",
        fields={"observed": "value"},
    )

    append_event(fact, ledger_dir=ledger_dir)

    log_path = ledger_dir / "test_artifact.log.md"
    assert log_path.exists()
    line = log_path.read_text(encoding="utf-8").strip()
    assert line.startswith("- (rawfact) ")
    assert "source=synthetic:test" in line
    assert "artifact=test_artifact/x1" in line
    assert json.dumps({"observed": "value"}, sort_keys=True) in line

    record = get_record("test_artifact", "x1", ledger_dir=ledger_dir)
    assert isinstance(record, LedgerRecord)
    assert record.fields == {"observed": "value"}
    assert record.confidence == "unknown"


# --- I/O matrix row 2: conflicting RawFacts for the same artifact ---------


def test_conflicting_rawfacts_both_appended_nothing_overwritten(
    ledger_dir: Path,
) -> None:
    first = RawFact(
        artifact_type="test_artifact",
        artifact_id="x1",
        source="synthetic:test",
        fields={"observed": "first"},
    )
    second = RawFact(
        artifact_type="test_artifact",
        artifact_id="x1",
        source="synthetic:test",
        fields={"observed": "second"},
    )

    append_event(first, ledger_dir=ledger_dir)
    append_event(second, ledger_dir=ledger_dir)

    events = read_events("test_artifact", ledger_dir=ledger_dir)
    assert len(events) == 2
    assert events[0].fields == {"observed": "first"}
    assert events[1].fields == {"observed": "second"}

    record = get_record("test_artifact", "x1", ledger_dir=ledger_dir)
    assert record.fields == {"observed": "second"}


# --- I/O matrix row 3: RawFact attempts a LedgerRecord-only field ---------


@pytest.mark.parametrize("forbidden_key", ["confidence", "tier_sla"])
def test_rawfact_rejects_ledger_record_only_field(
    ledger_dir: Path, forbidden_key: str
) -> None:
    with pytest.raises(SchemaValidationError):
        RawFact(
            artifact_type="test_artifact",
            artifact_id="x1",
            source="synthetic:test",
            fields={forbidden_key: "should-not-be-allowed"},
        )

    # Nothing was appended to the log as a result of the rejected construction.
    assert read_events("test_artifact", ledger_dir=ledger_dir) == []
    assert not (ledger_dir / "test_artifact.log.md").exists()


# --- I/O matrix row 4: query for an artifact with no recorded facts ------


def test_query_for_artifact_with_no_recorded_facts_returns_unknown_never_raises(
    ledger_dir: Path,
) -> None:
    record = get_record("test_artifact", "missing", ledger_dir=ledger_dir)

    assert record.confidence == "unknown"
    assert record.fields == {}
    assert record.last_verified is None
    assert record.verification_method is None
    assert record.expiry_rule is None
    assert record.tier_sla is None
    assert record.escalation_owner is None


# --- I/O matrix row 5: fresh replay reproduces state ----------------------


def test_fresh_replay_reproduces_identical_state_from_clean_read(
    ledger_dir: Path,
) -> None:
    facts = [
        RawFact(
            artifact_type="test_artifact",
            artifact_id="x1",
            source="synthetic:test",
            fields={"observed": "value-1"},
        ),
        RawFact(
            artifact_type="test_artifact",
            artifact_id="x2",
            source="synthetic:test",
            fields={"observed": "value-2"},
        ),
        RawFact(
            artifact_type="test_artifact",
            artifact_id="x1",
            source="synthetic:test",
            fields={"observed": "value-1-updated"},
        ),
    ]
    for fact in facts:
        append_event(fact, ledger_dir=ledger_dir)

    # No in-memory cache is held between these two calls -- get_record always
    # re-reads the log file from disk (AD-3).
    first_read = get_record("test_artifact", "x1", ledger_dir=ledger_dir)
    second_read = get_record("test_artifact", "x1", ledger_dir=ledger_dir)

    assert first_read == second_read
    assert first_read.fields == {"observed": "value-1-updated"}

    other = get_record("test_artifact", "x2", ledger_dir=ledger_dir)
    assert other.fields == {"observed": "value-2"}


# --- Additional schema-split coverage (AD-9) ------------------------------


def test_rawfact_fields_are_immutable_after_construction() -> None:
    fact = RawFact(
        artifact_type="test_artifact",
        artifact_id="x1",
        source="synthetic:test",
        fields={"observed": "value"},
    )
    with pytest.raises(TypeError):
        fact.fields["confidence"] = "agent-verified"  # type: ignore[index]


def test_ledger_record_rejects_invalid_confidence_value() -> None:
    with pytest.raises(SchemaValidationError):
        LedgerRecord(
            artifact_type="test_artifact",
            artifact_id="x1",
            confidence="definitely-certain",
        )


# --- Acceptance: MCP server exposes exactly one read tool -----------------


def test_server_exposes_exactly_one_read_only_tool() -> None:
    tools = asyncio.run(mcp.list_tools())
    names = [tool.name for tool in tools]
    assert names == ["ledger_get_record"]


def _point_server_at(monkeypatch: pytest.MonkeyPatch, ledger_dir: Path) -> None:
    """Redirect ledger_core.server's get_record to an isolated tmp ledger dir.

    The server module binds `get_record` as a plain module-level name (from
    `from ledger_core.projection import get_record`), and its tool handler
    calls it with only (artifact_type, artifact_id) -- there's no built-in
    way to pass a ledger_dir through the MCP tool surface. Patching the name
    the handler looks up at call time lets tests exercise the *real* tool
    without ever touching the real, git-committed ledger_data/ directory.
    """
    monkeypatch.setattr(
        server_module,
        "get_record",
        lambda artifact_type, artifact_id: get_record(
            artifact_type, artifact_id, ledger_dir=ledger_dir
        ),
    )


async def _call_ledger_get_record(artifact_type: str, artifact_id: str):
    async with create_connected_server_and_client_session(mcp) as client:
        return await client.call_tool(
            "ledger_get_record",
            {"artifact_type": artifact_type, "artifact_id": artifact_id},
        )


def test_ledger_get_record_tool_matches_get_record(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fact = RawFact(
        artifact_type="test_artifact",
        artifact_id="x1",
        source="synthetic:test",
        fields={"observed": "value"},
    )
    append_event(fact, ledger_dir=ledger_dir)
    _point_server_at(monkeypatch, ledger_dir)

    result = asyncio.run(_call_ledger_get_record("test_artifact", "x1"))

    assert result.isError is False
    expected = get_record("test_artifact", "x1", ledger_dir=ledger_dir)
    assert result.structuredContent == {
        "artifact_type": expected.artifact_type,
        "artifact_id": expected.artifact_id,
        "fields": dict(expected.fields),
        "last_verified": expected.last_verified,
        "verification_method": expected.verification_method,
        "expiry_rule": expected.expiry_rule,
        "tier_sla": expected.tier_sla,
        "escalation_owner": expected.escalation_owner,
        "confidence": expected.confidence,
    }


# --- ledger_get_record tool: exceptions surface as structured errors -----


def test_ledger_get_record_tool_returns_structured_error_on_log_format_error(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A LogFormatError raised deep inside get_record must not escape as a
    raw, unhandled exception -- the mcp SDK's own request-handling layer
    (mcp.server.lowlevel.server.Server.call_tool's registered handler)
    already catches any exception from a tool call and converts it into a
    structured CallToolResult(isError=True, ...). This test proves that
    behavior end-to-end for our tool rather than adding a redundant
    try/except in ledger_core/server.py.
    """
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "test_artifact.log.md").write_text(
        "this is not a valid event log line at all\n", encoding="utf-8"
    )
    _point_server_at(monkeypatch, ledger_dir)

    result = asyncio.run(_call_ledger_get_record("test_artifact", "x1"))

    assert result.isError is True
    assert result.content
    assert "unparseable event log line" in result.content[0].text


# --- LogFormatError: malformed log lines raise instead of misparsing -----


def test_read_events_raises_log_format_error_for_unparseable_line(
    ledger_dir: Path,
) -> None:
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "test_artifact.log.md").write_text(
        "this is not a valid event log line at all\n", encoding="utf-8"
    )

    with pytest.raises(LogFormatError):
        read_events("test_artifact", ledger_dir=ledger_dir)

    # get_record propagates the same error rather than silently swallowing
    # or misinterpreting the malformed line.
    with pytest.raises(LogFormatError):
        get_record("test_artifact", "x1", ledger_dir=ledger_dir)


def test_read_events_raises_log_format_error_for_invalid_fields_json(
    ledger_dir: Path,
) -> None:
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "test_artifact.log.md").write_text(
        "- (rawfact) 2026-01-01T00:00:00Z source=synthetic:test "
        "artifact=test_artifact/x1 fields={not valid json}\n",
        encoding="utf-8",
    )

    with pytest.raises(LogFormatError):
        read_events("test_artifact", ledger_dir=ledger_dir)

    with pytest.raises(LogFormatError):
        get_record("test_artifact", "x1", ledger_dir=ledger_dir)


# --- Additional review-finding coverage -----------------------------------


@pytest.mark.parametrize(
    "field_name,bad_value",
    [
        ("artifact_type", "bad/type"),
        ("artifact_type", "has space"),
        ("artifact_type", "   "),
        ("artifact_type", ".."),
        ("artifact_id", "bad/id"),
        ("artifact_id", "has space"),
        ("source", "bad/source"),
        ("source", "has space"),
    ],
)
def test_rawfact_rejects_invalid_charset_in_identifiers(
    field_name: str, bad_value: str
) -> None:
    kwargs = {
        "artifact_type": "test_artifact",
        "artifact_id": "x1",
        "source": "synthetic:test",
        "fields": {},
    }
    kwargs[field_name] = bad_value
    with pytest.raises(SchemaValidationError):
        RawFact(**kwargs)


@pytest.mark.parametrize("bad_value", [{"nested": "dict"}, ["a", "list"], object()])
def test_rawfact_rejects_non_json_scalar_field_values(bad_value: object) -> None:
    with pytest.raises(SchemaValidationError):
        RawFact(
            artifact_type="test_artifact",
            artifact_id="x1",
            source="synthetic:test",
            fields={"observed": bad_value},
        )


def test_append_event_rejects_naive_timestamp(ledger_dir: Path) -> None:
    fact = RawFact(
        artifact_type="test_artifact",
        artifact_id="x1",
        source="synthetic:test",
        fields={"observed": "value"},
    )
    naive = datetime(2026, 1, 1, 12, 0, 0)  # no tzinfo
    with pytest.raises(ValueError):
        append_event(fact, ledger_dir=ledger_dir, timestamp=naive)


def test_append_event_accepts_timezone_aware_timestamp(ledger_dir: Path) -> None:
    fact = RawFact(
        artifact_type="test_artifact",
        artifact_id="x1",
        source="synthetic:test",
        fields={"observed": "value"},
    )
    aware = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    append_event(fact, ledger_dir=ledger_dir, timestamp=aware)

    line = (ledger_dir / "test_artifact.log.md").read_text(encoding="utf-8")
    assert "2026-01-01T12:00:00Z" in line


def test_append_event_raises_not_a_directory_error_when_ledger_dir_is_a_file(
    tmp_path: Path,
) -> None:
    blocked_path = tmp_path / "ledger_data_blocked"
    blocked_path.write_text("not a directory", encoding="utf-8")

    fact = RawFact(
        artifact_type="test_artifact",
        artifact_id="x1",
        source="synthetic:test",
        fields={"observed": "value"},
    )
    with pytest.raises(NotADirectoryError):
        append_event(fact, ledger_dir=blocked_path)


def test_get_record_skips_non_rawfact_event_type(ledger_dir: Path) -> None:
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "test_artifact.log.md").write_text(
        "- (someotherevent) 2026-01-01T00:00:00Z source=synthetic:test "
        'artifact=test_artifact/x1 fields={"should_not_appear": true}\n',
        encoding="utf-8",
    )

    record = get_record("test_artifact", "x1", ledger_dir=ledger_dir)

    assert record.fields == {}
