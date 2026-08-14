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

from connectors.git_repo.server import git_get_last_touched
from ledger_core import projection as projection_module
from ledger_core import server as server_module
from ledger_core.log import LogFormatError, append_event, read_events
from ledger_core.projection import (
    LOG_FORMAT_ERROR_ARTIFACT_ID,
    LOG_FORMAT_ERROR_MARKER,
    get_coverage_map,
    get_record,
    list_records,
)
from ledger_core.server import mcp
from shared.ledger_schema import LedgerRecord, RawFact, SchemaValidationError


@pytest.fixture
def ledger_dir(tmp_path: Path) -> Path:
    return tmp_path / "ledger_data"


# --- I/O matrix row 1: new RawFact ingested -------------------------------


def test_new_rawfact_ingested_appends_event_and_projects_agent_verified_confidence(
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

    # Story 3 (AD-5): a real, non-empty observed field now projects
    # confidence "agent-verified" instead of the old hardcoded "unknown".
    record = get_record("test_artifact", "x1", ledger_dir=ledger_dir)
    assert isinstance(record, LedgerRecord)
    assert record.fields == {"observed": "value"}
    assert record.confidence == "agent-verified"


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


def test_server_exposes_exactly_four_tools_none_writing_outside_the_log() -> None:
    """Acceptance criterion: a client listing tools sees exactly four, and
    (by construction -- see the ingestion/coverage/list tests below) none of
    them writes anywhere outside the append-only log.
    """
    tools = asyncio.run(mcp.list_tools())
    names = [tool.name for tool in tools]
    assert names == [
        "ledger_get_record",
        "ledger_ingest_raw_fact",
        "ledger_get_coverage",
        "ledger_list_records",
    ]


def _point_server_at(monkeypatch: pytest.MonkeyPatch, ledger_dir: Path) -> None:
    """Redirect every ledger_dir-touching name ledger_core.server binds to an
    isolated tmp ledger dir.

    The server module binds `get_record`, `append_event`, `get_coverage_map`,
    and `list_records` as plain module-level names (`from ... import ...`),
    and each tool handler calls its name with no way to pass a ledger_dir
    through the MCP tool surface. Patching the names the handlers look up at
    call time lets tests exercise the *real* tools without ever touching the
    real, git-committed ledger_data/ directory.
    """
    monkeypatch.setattr(
        server_module,
        "get_record",
        lambda artifact_type, artifact_id: get_record(
            artifact_type, artifact_id, ledger_dir=ledger_dir
        ),
    )
    monkeypatch.setattr(
        server_module,
        "append_event",
        lambda fact: append_event(fact, ledger_dir=ledger_dir),
    )
    monkeypatch.setattr(
        server_module,
        "get_coverage_map",
        lambda: get_coverage_map(ledger_dir=ledger_dir),
    )
    monkeypatch.setattr(
        server_module,
        "list_records",
        lambda artifact_type=None, confidence=None: list_records(
            artifact_type=artifact_type, confidence=confidence, ledger_dir=ledger_dir
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


# ===========================================================================
# Story 3: confidence and coverage computation
# ===========================================================================


async def _call_ledger_ingest_raw_fact(
    artifact_type: str, artifact_id: str, source: str, fields: dict
):
    async with create_connected_server_and_client_session(mcp) as client:
        return await client.call_tool(
            "ledger_ingest_raw_fact",
            {
                "artifact_type": artifact_type,
                "artifact_id": artifact_id,
                "source": source,
                "fields": fields,
            },
        )


async def _call_ledger_get_coverage():
    async with create_connected_server_and_client_session(mcp) as client:
        return await client.call_tool("ledger_get_coverage", {})


# --- I/O matrix row: end-to-end connector fact ingested -------------------


def test_end_to_end_git_connector_fact_ingested_shows_agent_verified(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Feeds a *real* git connector fact (for a real, tracked file in this
    repo) into `ledger_ingest_raw_fact`, then confirms `ledger_get_record`
    reflects it -- proving the Sensor -> Ledger wiring end-to-end rather than
    with a synthetic RawFact.
    """
    repo_root = Path(__file__).resolve().parents[1]
    connector_result = git_get_last_touched(
        repo_path=str(repo_root),
        file_path="pyproject.toml",
        artifact_type="test_artifact",
        artifact_id="e2e1",
    )

    _point_server_at(monkeypatch, ledger_dir)

    ingest_result = asyncio.run(
        _call_ledger_ingest_raw_fact(
            connector_result["artifact_type"],
            connector_result["artifact_id"],
            connector_result["source"],
            connector_result["fields"],
        )
    )
    assert ingest_result.isError is False

    record_result = asyncio.run(
        _call_ledger_get_record("test_artifact", "e2e1")
    )
    assert record_result.isError is False
    assert record_result.structuredContent["confidence"] == "agent-verified"
    assert record_result.structuredContent["fields"] == connector_result["fields"]


# --- I/O matrix row: query before any fact exists (unchanged from Story 1) -


def test_ledger_get_record_tool_reports_unknown_before_any_fact_exists(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _point_server_at(monkeypatch, ledger_dir)

    result = asyncio.run(_call_ledger_get_record("test_artifact", "never-ingested"))

    assert result.isError is False
    assert result.structuredContent["confidence"] == "unknown"
    assert result.structuredContent["fields"] == {}


# --- I/O matrix row: ingest payload violates the schema --------------------


def test_ledger_ingest_raw_fact_tool_rejects_ledger_only_field_without_appending(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _point_server_at(monkeypatch, ledger_dir)

    result = asyncio.run(
        _call_ledger_ingest_raw_fact(
            "test_artifact",
            "x1",
            "synthetic:test",
            {"confidence": "agent-verified"},
        )
    )

    assert result.isError is True
    assert result.content
    assert "confidence" in result.content[0].text

    # Nothing was appended as a result of the rejected ingestion.
    assert read_events("test_artifact", ledger_dir=ledger_dir) == []
    assert not (ledger_dir / "test_artifact.log.md").exists()


def test_ledger_ingest_raw_fact_tool_appends_and_is_visible_via_get_record(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _point_server_at(monkeypatch, ledger_dir)

    ingest_result = asyncio.run(
        _call_ledger_ingest_raw_fact(
            "test_artifact", "x1", "synthetic:test", {"observed": "value"}
        )
    )
    assert ingest_result.isError is False
    assert ingest_result.structuredContent == {
        "artifact_type": "test_artifact",
        "artifact_id": "x1",
        "source": "synthetic:test",
        "fields": {"observed": "value"},
    }

    record_result = asyncio.run(_call_ledger_get_record("test_artifact", "x1"))
    assert record_result.structuredContent["confidence"] == "agent-verified"
    assert record_result.structuredContent["fields"] == {"observed": "value"}


# --- I/O matrix row: coverage map, multiple types and confidence states ---


def test_coverage_map_tallies_confidence_per_artifact_type_matching_get_record(
    ledger_dir: Path,
) -> None:
    # type_a/a1: a real observed field -> agent-verified.
    append_event(
        RawFact(
            artifact_type="type_a",
            artifact_id="a1",
            source="synthetic:test",
            fields={"observed": "value"},
        ),
        ledger_dir=ledger_dir,
    )
    # type_a/a2: ingested with no observed fields at all -> unknown, despite
    # a fact having been appended (the confidence rule keys off `fields`
    # being non-empty, not merely "some event exists").
    append_event(
        RawFact(
            artifact_type="type_a",
            artifact_id="a2",
            source="synthetic:test",
            fields={},
        ),
        ledger_dir=ledger_dir,
    )
    # type_b/b1: a different artifact_type, also agent-verified.
    append_event(
        RawFact(
            artifact_type="type_b",
            artifact_id="b1",
            source="synthetic:test",
            fields={"observed": "value"},
        ),
        ledger_dir=ledger_dir,
    )

    coverage = get_coverage_map(ledger_dir=ledger_dir)

    assert coverage == {
        "type_a": {"agent-verified": 1, "unknown": 1},
        "type_b": {"agent-verified": 1},
    }

    # Matches exactly what ledger_get_record reports for each artifact.
    assert get_record("type_a", "a1", ledger_dir=ledger_dir).confidence == (
        "agent-verified"
    )
    assert get_record("type_a", "a2", ledger_dir=ledger_dir).confidence == "unknown"
    assert get_record("type_b", "b1", ledger_dir=ledger_dir).confidence == (
        "agent-verified"
    )
    # An artifact never ingested at all is "unknown" via get_record but,
    # having no log entry, cannot appear in the coverage tally.
    assert get_record("type_a", "never-ingested", ledger_dir=ledger_dir).confidence == (
        "unknown"
    )


def test_ledger_get_coverage_tool_matches_get_coverage_map(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    append_event(
        RawFact(
            artifact_type="type_a",
            artifact_id="a1",
            source="synthetic:test",
            fields={"observed": "value"},
        ),
        ledger_dir=ledger_dir,
    )
    _point_server_at(monkeypatch, ledger_dir)

    result = asyncio.run(_call_ledger_get_coverage())

    assert result.isError is False
    assert result.structuredContent == get_coverage_map(ledger_dir=ledger_dir)


# --- I/O matrix row: coverage map with no data yet --------------------------


def test_coverage_map_returns_empty_when_ledger_dir_does_not_exist(
    tmp_path: Path,
) -> None:
    missing_dir = tmp_path / "does_not_exist"
    assert not missing_dir.exists()

    assert get_coverage_map(ledger_dir=missing_dir) == {}


def test_coverage_map_returns_empty_when_ledger_dir_is_empty(
    ledger_dir: Path,
) -> None:
    ledger_dir.mkdir(parents=True)

    assert get_coverage_map(ledger_dir=ledger_dir) == {}


# --- I/O matrix row: coverage map ignores reserved logs ---------------------


def test_coverage_map_excludes_reserved_underscore_prefixed_logs(
    ledger_dir: Path,
) -> None:
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "_ops.log.md").write_text(
        "- (rawfact) 2026-01-01T00:00:00Z source=synthetic:test "
        'artifact=_ops/incident-1 fields={"note": "scheduled run failed"}\n',
        encoding="utf-8",
    )
    append_event(
        RawFact(
            artifact_type="test_artifact",
            artifact_id="x1",
            source="synthetic:test",
            fields={"observed": "value"},
        ),
        ledger_dir=ledger_dir,
    )

    coverage = get_coverage_map(ledger_dir=ledger_dir)

    assert "_ops" not in coverage
    assert coverage == {"test_artifact": {"agent-verified": 1}}


# ===========================================================================
# Story 3 review findings: get_coverage_map robustness across multiple
# artifact-type logs.
# ===========================================================================


# --- Finding 1: ledger_dir exists but is a non-directory file --------------


def test_coverage_map_returns_empty_when_ledger_dir_is_a_file(
    tmp_path: Path,
) -> None:
    blocked_path = tmp_path / "ledger_data_blocked"
    blocked_path.write_text("not a directory", encoding="utf-8")

    assert get_coverage_map(ledger_dir=blocked_path) == {}


# --- Finding 2: a log file with no artifact-type prefix (literal ".log.md") -


def test_coverage_map_skips_log_file_with_empty_artifact_type(
    ledger_dir: Path,
) -> None:
    ledger_dir.mkdir(parents=True)
    # Content is irrelevant -- the empty artifact_type derived from the
    # filename itself is what must be skipped, before any attempt to parse.
    (ledger_dir / ".log.md").write_text(
        "this is not a valid event log line at all\n", encoding="utf-8"
    )
    append_event(
        RawFact(
            artifact_type="test_artifact",
            artifact_id="x1",
            source="synthetic:test",
            fields={"observed": "value"},
        ),
        ledger_dir=ledger_dir,
    )

    coverage = get_coverage_map(ledger_dir=ledger_dir)

    assert "" not in coverage
    assert coverage == {"test_artifact": {"agent-verified": 1}}


# --- Finding 3: one corrupted artifact-type log must not blind the rest ----


def test_coverage_map_isolates_log_format_error_to_its_own_artifact_type(
    ledger_dir: Path,
) -> None:
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "broken_type.log.md").write_text(
        "this is not a valid event log line at all\n", encoding="utf-8"
    )
    append_event(
        RawFact(
            artifact_type="healthy_type",
            artifact_id="h1",
            source="synthetic:test",
            fields={"observed": "value"},
        ),
        ledger_dir=ledger_dir,
    )

    coverage = get_coverage_map(ledger_dir=ledger_dir)

    # The healthy type's tally is unaffected by the other type's corruption.
    assert coverage["healthy_type"] == {"agent-verified": 1}
    # The corrupted type's problem is visible, not silently dropped.
    assert coverage["broken_type"] == {LOG_FORMAT_ERROR_MARKER: 1}


# --- Finding 4: coverage tallying reads each artifact-type log once -------


def test_get_coverage_map_reads_each_artifact_type_log_once_not_once_per_artifact(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for artifact_id in ["a1", "a2", "a3"]:
        append_event(
            RawFact(
                artifact_type="test_artifact",
                artifact_id=artifact_id,
                source="synthetic:test",
                fields={"observed": "value"},
            ),
            ledger_dir=ledger_dir,
        )

    call_count = 0
    original_read_events = projection_module.read_events

    def counting_read_events(artifact_type: str, *, ledger_dir: Path):
        nonlocal call_count
        call_count += 1
        return original_read_events(artifact_type, ledger_dir=ledger_dir)

    monkeypatch.setattr(projection_module, "read_events", counting_read_events)

    coverage = get_coverage_map(ledger_dir=ledger_dir)

    assert coverage == {"test_artifact": {"agent-verified": 3}}
    # One read of the artifact-type log total -- not one per artifact_id
    # (an N+1 re-read across 3 artifacts would make call_count == 4: the
    # initial pass to discover artifact_ids plus one get_record per id).
    assert call_count == 1


# --- Finding 6: a directory matching the *.log.md naming is skipped --------


def test_coverage_map_skips_directory_named_like_a_log_file(
    ledger_dir: Path,
) -> None:
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "not_a_file.log.md").mkdir()
    append_event(
        RawFact(
            artifact_type="test_artifact",
            artifact_id="x1",
            source="synthetic:test",
            fields={"observed": "value"},
        ),
        ledger_dir=ledger_dir,
    )

    coverage = get_coverage_map(ledger_dir=ledger_dir)

    assert "not_a_file" not in coverage
    assert coverage == {"test_artifact": {"agent-verified": 1}}


# --- Finding 5: ledger_ingest_raw_fact tool with fields={} via the tool ----
# ----------------------------------------------------------------- path ---


def test_ledger_ingest_raw_fact_tool_with_empty_fields_reports_unknown_via_get_record_tool(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fields={} -> "unknown" edge case, exercised through the actual
    ledger_ingest_raw_fact and ledger_get_record MCP tool calls rather than
    the direct projection/log functions.
    """
    _point_server_at(monkeypatch, ledger_dir)

    ingest_result = asyncio.run(
        _call_ledger_ingest_raw_fact("test_artifact", "x1", "synthetic:test", {})
    )
    assert ingest_result.isError is False

    record_result = asyncio.run(_call_ledger_get_record("test_artifact", "x1"))

    assert record_result.isError is False
    assert record_result.structuredContent["confidence"] == "unknown"
    assert record_result.structuredContent["fields"] == {}


# --- Finding 7: ledger_ingest_raw_fact tool rejects empty identifiers ------


@pytest.mark.parametrize("field_name", ["artifact_type", "artifact_id"])
def test_ledger_ingest_raw_fact_tool_rejects_empty_identifier(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch, field_name: str
) -> None:
    """RawFact's Story-1 charset validation already rejects an empty
    artifact_type/artifact_id at construction time (the identifier regex
    requires at least one character) -- this proves that rejection surfaces
    correctly through the ledger_ingest_raw_fact tool call path itself.
    """
    _point_server_at(monkeypatch, ledger_dir)

    kwargs = {
        "artifact_type": "test_artifact",
        "artifact_id": "x1",
        "source": "synthetic:test",
        "fields": {},
    }
    kwargs[field_name] = ""

    result = asyncio.run(
        _call_ledger_ingest_raw_fact(
            kwargs["artifact_type"],
            kwargs["artifact_id"],
            kwargs["source"],
            kwargs["fields"],
        )
    )

    assert result.isError is True
    assert result.content
    assert field_name in result.content[0].text

    # Nothing was appended anywhere as a result of the rejected ingestion.
    assert not ledger_dir.exists()


# ===========================================================================
# Story 4: chat-queryable live state (last_verified + list_records)
# ===========================================================================


# --- I/O matrix row: first fact populates last_verified ---------------------


def test_first_fact_populates_last_verified_matching_event_timestamp(
    ledger_dir: Path,
) -> None:
    fact = RawFact(
        artifact_type="test_artifact",
        artifact_id="x1",
        source="synthetic:test",
        fields={"observed": "value"},
    )
    timestamp = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    append_event(fact, ledger_dir=ledger_dir, timestamp=timestamp)

    record = get_record("test_artifact", "x1", ledger_dir=ledger_dir)
    assert record.last_verified == "2026-01-01T12:00:00Z"


# --- I/O matrix row: no facts yet -> last_verified stays None --------------
# Already covered by
# test_query_for_artifact_with_no_recorded_facts_returns_unknown_never_raises,
# which asserts record.last_verified is None and record.confidence ==
# "unknown".


# --- I/O matrix row: multiple facts, last_verified tracks the latest ------


def test_last_verified_tracks_the_latest_of_two_facts_not_the_first(
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
    first_ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    second_ts = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)

    append_event(first, ledger_dir=ledger_dir, timestamp=first_ts)
    append_event(second, ledger_dir=ledger_dir, timestamp=second_ts)

    record = get_record("test_artifact", "x1", ledger_dir=ledger_dir)
    assert record.last_verified == "2026-06-01T00:00:00Z"


def test_ledger_get_record_tool_reports_last_verified_matching_get_record(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fact = RawFact(
        artifact_type="test_artifact",
        artifact_id="x1",
        source="synthetic:test",
        fields={"observed": "value"},
    )
    timestamp = datetime(2026, 3, 1, 8, 30, 0, tzinfo=timezone.utc)
    append_event(fact, ledger_dir=ledger_dir, timestamp=timestamp)
    _point_server_at(monkeypatch, ledger_dir)

    result = asyncio.run(_call_ledger_get_record("test_artifact", "x1"))

    assert result.isError is False
    expected = get_record("test_artifact", "x1", ledger_dir=ledger_dir)
    assert result.structuredContent["last_verified"] == expected.last_verified
    assert result.structuredContent["last_verified"] == "2026-03-01T08:30:00Z"


# --- list_records: I/O matrix rows -----------------------------------------


async def _call_ledger_list_records(
    artifact_type: str | None = None, confidence: str | None = None
):
    async with create_connected_server_and_client_session(mcp) as client:
        arguments: dict = {}
        if artifact_type is not None:
            arguments["artifact_type"] = artifact_type
        if confidence is not None:
            arguments["confidence"] = confidence
        return await client.call_tool("ledger_list_records", arguments)


def test_list_records_no_filters_returns_every_artifact_across_all_types(
    ledger_dir: Path,
) -> None:
    append_event(
        RawFact(
            artifact_type="type_a",
            artifact_id="a1",
            source="synthetic:test",
            fields={"observed": "value"},
        ),
        ledger_dir=ledger_dir,
    )
    append_event(
        RawFact(
            artifact_type="type_b",
            artifact_id="b1",
            source="synthetic:test",
            fields={"observed": "value"},
        ),
        ledger_dir=ledger_dir,
    )
    append_event(
        RawFact(
            artifact_type="type_b",
            artifact_id="b2",
            source="synthetic:test",
            fields={"observed": "value"},
        ),
        ledger_dir=ledger_dir,
    )

    records = list_records(ledger_dir=ledger_dir)

    seen = {(record.artifact_type, record.artifact_id) for record in records}
    assert seen == {("type_a", "a1"), ("type_b", "b1"), ("type_b", "b2")}


def test_list_records_filtered_by_artifact_type_returns_only_that_type(
    ledger_dir: Path,
) -> None:
    append_event(
        RawFact(
            artifact_type="type_a",
            artifact_id="a1",
            source="synthetic:test",
            fields={"observed": "value"},
        ),
        ledger_dir=ledger_dir,
    )
    append_event(
        RawFact(
            artifact_type="type_b",
            artifact_id="b1",
            source="synthetic:test",
            fields={"observed": "value"},
        ),
        ledger_dir=ledger_dir,
    )

    records = list_records(artifact_type="type_a", ledger_dir=ledger_dir)

    assert len(records) == 1
    assert records[0].artifact_type == "type_a"
    assert records[0].artifact_id == "a1"


def test_list_records_filtered_by_confidence_returns_only_matching_records(
    ledger_dir: Path,
) -> None:
    append_event(
        RawFact(
            artifact_type="type_a",
            artifact_id="a1",
            source="synthetic:test",
            fields={"observed": "value"},
        ),
        ledger_dir=ledger_dir,
    )
    # Ingested with fields={} -- Story 3's edge case -- projects "unknown".
    append_event(
        RawFact(
            artifact_type="type_a",
            artifact_id="a2",
            source="synthetic:test",
            fields={},
        ),
        ledger_dir=ledger_dir,
    )

    records = list_records(confidence="unknown", ledger_dir=ledger_dir)

    assert len(records) == 1
    assert records[0].artifact_id == "a2"
    assert records[0].confidence == "unknown"


def test_list_records_with_corrupted_type_present_surfaces_sentinel_and_healthy(
    ledger_dir: Path,
) -> None:
    """A corrupted type is no longer silently dropped (finding #1): it's
    represented by exactly one sentinel record alongside the healthy type's
    real records -- never indistinguishable from "no artifacts of this
    type exist".
    """
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "broken_type.log.md").write_text(
        "this is not a valid event log line at all\n", encoding="utf-8"
    )
    append_event(
        RawFact(
            artifact_type="healthy_type",
            artifact_id="h1",
            source="synthetic:test",
            fields={"observed": "value"},
        ),
        ledger_dir=ledger_dir,
    )

    records = list_records(ledger_dir=ledger_dir)

    by_type = {record.artifact_type: record for record in records}
    assert len(records) == 2
    assert by_type["healthy_type"].artifact_id == "h1"
    sentinel = by_type["broken_type"]
    assert sentinel.artifact_id == LOG_FORMAT_ERROR_ARTIFACT_ID
    assert sentinel.confidence == "unknown"
    assert sentinel.last_verified is None


def test_list_records_filtered_directly_to_corrupted_type_returns_sentinel(
    ledger_dir: Path,
) -> None:
    """Finding #5: filtering directly to the corrupted type's own name (not
    just encountering it during an unfiltered scan) still surfaces the
    sentinel rather than an empty list.
    """
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "broken_type.log.md").write_text(
        "this is not a valid event log line at all\n", encoding="utf-8"
    )

    records = list_records(artifact_type="broken_type", ledger_dir=ledger_dir)

    assert len(records) == 1
    assert records[0].artifact_type == "broken_type"
    assert records[0].artifact_id == LOG_FORMAT_ERROR_ARTIFACT_ID


def test_list_records_corrupted_type_sentinel_survives_confidence_filter(
    ledger_dir: Path,
) -> None:
    """The sentinel isn't a real confidence classification, so it must
    remain visible even when a `confidence` filter that wouldn't otherwise
    match "unknown" is absent, and even when filtering *for* "unknown" --
    it should never be silently excluded by the confidence dimension.
    """
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "broken_type.log.md").write_text(
        "this is not a valid event log line at all\n", encoding="utf-8"
    )
    append_event(
        RawFact(
            artifact_type="healthy_type",
            artifact_id="h1",
            source="synthetic:test",
            fields={"observed": "value"},
        ),
        ledger_dir=ledger_dir,
    )

    records = list_records(confidence="agent-verified", ledger_dir=ledger_dir)

    by_type = {record.artifact_type: record for record in records}
    assert by_type["healthy_type"].confidence == "agent-verified"
    assert by_type["broken_type"].artifact_id == LOG_FORMAT_ERROR_ARTIFACT_ID


def test_list_records_filtered_to_nonexistent_artifact_type_returns_empty(
    ledger_dir: Path,
) -> None:
    append_event(
        RawFact(
            artifact_type="type_a",
            artifact_id="a1",
            source="synthetic:test",
            fields={"observed": "value"},
        ),
        ledger_dir=ledger_dir,
    )

    records = list_records(artifact_type="does_not_exist", ledger_dir=ledger_dir)

    assert records == []


@pytest.mark.parametrize("bad_artifact_type", ["", "_reserved"])
def test_list_records_rejects_empty_or_reserved_artifact_type_filter(
    ledger_dir: Path, bad_artifact_type: str
) -> None:
    """Finding #2: an explicit `artifact_type` filter can't bypass the
    empty/reserved-name exclusion discovery already applies -- it must
    yield an empty list, the same as if that name had never been
    discovered on disk.
    """
    append_event(
        RawFact(
            artifact_type="type_a",
            artifact_id="a1",
            source="synthetic:test",
            fields={"observed": "value"},
        ),
        ledger_dir=ledger_dir,
    )

    assert list_records(artifact_type=bad_artifact_type, ledger_dir=ledger_dir) == []


def test_list_records_returns_empty_when_ledger_dir_does_not_exist(
    tmp_path: Path,
) -> None:
    missing_dir = tmp_path / "does_not_exist"
    assert not missing_dir.exists()

    assert list_records(ledger_dir=missing_dir) == []


def test_list_records_returns_empty_when_ledger_dir_missing_and_artifact_type_given(
    tmp_path: Path,
) -> None:
    """Finding #3: the missing-ledger_dir and explicit-artifact_type-filter
    edge cases combined -- previously only tested independently.
    """
    missing_dir = tmp_path / "does_not_exist"
    assert not missing_dir.exists()

    assert (
        list_records(artifact_type="type_a", ledger_dir=missing_dir) == []
    )


def test_list_records_filtered_by_artifact_type_and_confidence_together(
    ledger_dir: Path,
) -> None:
    """Finding #4: the AND interaction between `artifact_type` and
    `confidence` filters together, not just each dimension in isolation.
    """
    append_event(
        RawFact(
            artifact_type="type_a",
            artifact_id="a1",
            source="synthetic:test",
            fields={"observed": "value"},
        ),
        ledger_dir=ledger_dir,
    )
    # Ingested with fields={} -- projects "unknown" -- same artifact_type.
    append_event(
        RawFact(
            artifact_type="type_a",
            artifact_id="a2",
            source="synthetic:test",
            fields={},
        ),
        ledger_dir=ledger_dir,
    )
    # A different artifact_type also with an "unknown" record -- must be
    # excluded by the artifact_type filter even though its confidence matches.
    append_event(
        RawFact(
            artifact_type="type_b",
            artifact_id="b1",
            source="synthetic:test",
            fields={},
        ),
        ledger_dir=ledger_dir,
    )

    records = list_records(
        artifact_type="type_a", confidence="unknown", ledger_dir=ledger_dir
    )

    assert len(records) == 1
    assert records[0].artifact_type == "type_a"
    assert records[0].artifact_id == "a2"


# --- ledger_list_records tool: matches list_records end-to-end ------------


def _expected_list_records_payload(records) -> list[dict]:
    return [
        {
            "artifact_type": record.artifact_type,
            "artifact_id": record.artifact_id,
            "fields": dict(record.fields),
            "last_verified": record.last_verified,
            "verification_method": record.verification_method,
            "expiry_rule": record.expiry_rule,
            "tier_sla": record.tier_sla,
            "escalation_owner": record.escalation_owner,
            "confidence": record.confidence,
        }
        for record in records
    ]


def test_ledger_list_records_tool_no_filters_matches_list_records(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    append_event(
        RawFact(
            artifact_type="type_a",
            artifact_id="a1",
            source="synthetic:test",
            fields={"observed": "value"},
        ),
        ledger_dir=ledger_dir,
    )
    _point_server_at(monkeypatch, ledger_dir)

    result = asyncio.run(_call_ledger_list_records())

    assert result.isError is False
    expected = _expected_list_records_payload(list_records(ledger_dir=ledger_dir))
    assert result.structuredContent == {"result": expected}


def test_ledger_list_records_tool_filtered_by_artifact_type(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    append_event(
        RawFact(
            artifact_type="type_a",
            artifact_id="a1",
            source="synthetic:test",
            fields={"observed": "value"},
        ),
        ledger_dir=ledger_dir,
    )
    append_event(
        RawFact(
            artifact_type="type_b",
            artifact_id="b1",
            source="synthetic:test",
            fields={"observed": "value"},
        ),
        ledger_dir=ledger_dir,
    )
    _point_server_at(monkeypatch, ledger_dir)

    result = asyncio.run(_call_ledger_list_records(artifact_type="type_a"))

    assert result.isError is False
    assert result.structuredContent == {
        "result": _expected_list_records_payload(
            list_records(artifact_type="type_a", ledger_dir=ledger_dir)
        )
    }
    assert len(result.structuredContent["result"]) == 1
    assert result.structuredContent["result"][0]["artifact_type"] == "type_a"


def test_ledger_list_records_tool_filtered_by_confidence(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    append_event(
        RawFact(
            artifact_type="type_a",
            artifact_id="a1",
            source="synthetic:test",
            fields={"observed": "value"},
        ),
        ledger_dir=ledger_dir,
    )
    append_event(
        RawFact(
            artifact_type="type_a",
            artifact_id="a2",
            source="synthetic:test",
            fields={},
        ),
        ledger_dir=ledger_dir,
    )
    _point_server_at(monkeypatch, ledger_dir)

    result = asyncio.run(_call_ledger_list_records(confidence="unknown"))

    assert result.isError is False
    records = result.structuredContent["result"]
    assert len(records) == 1
    assert records[0]["artifact_id"] == "a2"
    assert records[0]["confidence"] == "unknown"


def test_ledger_list_records_tool_with_corrupted_type_surfaces_sentinel_and_healthy(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "broken_type.log.md").write_text(
        "this is not a valid event log line at all\n", encoding="utf-8"
    )
    append_event(
        RawFact(
            artifact_type="healthy_type",
            artifact_id="h1",
            source="synthetic:test",
            fields={"observed": "value"},
        ),
        ledger_dir=ledger_dir,
    )
    _point_server_at(monkeypatch, ledger_dir)

    result = asyncio.run(_call_ledger_list_records())

    assert result.isError is False
    records = result.structuredContent["result"]
    by_type = {record["artifact_type"]: record for record in records}
    assert len(records) == 2
    assert by_type["healthy_type"]["artifact_id"] == "h1"
    assert by_type["broken_type"]["artifact_id"] == LOG_FORMAT_ERROR_ARTIFACT_ID
    assert by_type["broken_type"]["confidence"] == "unknown"


def test_ledger_list_records_tool_filtered_to_nonexistent_type_returns_empty(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    append_event(
        RawFact(
            artifact_type="type_a",
            artifact_id="a1",
            source="synthetic:test",
            fields={"observed": "value"},
        ),
        ledger_dir=ledger_dir,
    )
    _point_server_at(monkeypatch, ledger_dir)

    result = asyncio.run(_call_ledger_list_records(artifact_type="does_not_exist"))

    assert result.isError is False
    assert result.structuredContent == {"result": []}


# --- Reuse of the single-pass fold: list_records never re-reads per artifact


def test_list_records_reads_each_artifact_type_log_once_not_once_per_artifact(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for artifact_id in ["a1", "a2", "a3"]:
        append_event(
            RawFact(
                artifact_type="test_artifact",
                artifact_id=artifact_id,
                source="synthetic:test",
                fields={"observed": "value"},
            ),
            ledger_dir=ledger_dir,
        )

    call_count = 0
    original_read_events = projection_module.read_events

    def counting_read_events(artifact_type: str, *, ledger_dir: Path):
        nonlocal call_count
        call_count += 1
        return original_read_events(artifact_type, ledger_dir=ledger_dir)

    monkeypatch.setattr(projection_module, "read_events", counting_read_events)

    records = list_records(ledger_dir=ledger_dir)

    assert len(records) == 3
    # One read of the artifact-type log total -- not one per artifact_id.
    assert call_count == 1


def test_list_records_reads_each_of_n_distinct_artifact_types_exactly_once(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding #6: N *distinct artifact types* cost exactly N log reads --
    the existing read-count test above only proves 1 type with multiple
    artifact_ids costs 1 read, not that scanning multiple types itself
    stays linear rather than re-reading any one of them.
    """
    for artifact_type, artifact_ids in [
        ("type_a", ["a1", "a2"]),
        ("type_b", ["b1"]),
        ("type_c", ["c1", "c2", "c3"]),
    ]:
        for artifact_id in artifact_ids:
            append_event(
                RawFact(
                    artifact_type=artifact_type,
                    artifact_id=artifact_id,
                    source="synthetic:test",
                    fields={"observed": "value"},
                ),
                ledger_dir=ledger_dir,
            )

    call_count = 0
    original_read_events = projection_module.read_events

    def counting_read_events(artifact_type: str, *, ledger_dir: Path):
        nonlocal call_count
        call_count += 1
        return original_read_events(artifact_type, ledger_dir=ledger_dir)

    monkeypatch.setattr(projection_module, "read_events", counting_read_events)

    records = list_records(ledger_dir=ledger_dir)

    assert len(records) == 6
    # Exactly one read per distinct artifact_type (3), never one per
    # artifact_id (6) and never a re-read of any type already scanned.
    assert call_count == 3
