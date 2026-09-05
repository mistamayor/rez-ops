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

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from connectors.cmdb.server import cmdb_get_ci_status
from connectors.git_repo.server import git_get_last_touched
from connectors.ticketing.server import ticketing_get_ticket_status
from ledger_core import projection as projection_module
from ledger_core import server as server_module
from ledger_core.briefing import Briefing, get_briefing
from ledger_core.drafts import (
    DRAFT_FORMAT_ERROR_MARKER,
    Draft,
    DraftFileFormatError,
    DraftValidationError,
    create_draft,
    list_drafts,
)
from ledger_core.evidence import create_evidence_bundle, list_evidence
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


def test_server_exposes_exactly_eleven_tools_none_calling_an_external_send_api() -> None:
    """Acceptance criterion (Story 9, extended by Story 10, extended by Story
    12, extended by Story 13): a client listing tools sees `ledger_create_draft`
    and `ledger_list_drafts` alongside the four pre-existing tools, plus
    `ledger_get_briefing` (Story 10, CAP-7), plus `ledger_create_evidence` and
    `ledger_list_evidence` (Story 12, AD-11, CAP-9), plus
    `ledger_create_action_proposal` and `ledger_list_action_proposals` (Story
    13, AD-12, CAP-10), and (by construction -- see the
    ingestion/coverage/list/draft/briefing/evidence/action-proposal tests
    below, and `ledger_core/drafts.py`'s, `ledger_core/briefing.py`'s,
    `ledger_core/evidence.py`'s, and `ledger_core/action_proposals.py`'s
    complete absence of any `httpx`/network import) none of them calls an
    external send API.
    """
    tools = asyncio.run(mcp.list_tools())
    names = [tool.name for tool in tools]
    assert names == [
        "ledger_get_record",
        "ledger_ingest_raw_fact",
        "ledger_get_coverage",
        "ledger_list_records",
        "ledger_create_draft",
        "ledger_list_drafts",
        "ledger_create_evidence",
        "ledger_list_evidence",
        "ledger_get_briefing",
        "ledger_create_action_proposal",
        "ledger_list_action_proposals",
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
        lambda artifact_type=None, confidence=None, orphan_risk=None: list_records(
            artifact_type=artifact_type,
            confidence=confidence,
            orphan_risk=orphan_risk,
            ledger_dir=ledger_dir,
        ),
    )
    monkeypatch.setattr(
        server_module,
        "create_draft",
        lambda artifact_type, artifact_id, draft_type, subject, body, recipient=None: create_draft(
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            draft_type=draft_type,
            subject=subject,
            body=body,
            recipient=recipient,
            ledger_dir=ledger_dir,
        ),
    )
    monkeypatch.setattr(
        server_module,
        "list_drafts",
        lambda artifact_type=None, artifact_id=None, draft_type=None: list_drafts(
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            draft_type=draft_type,
            ledger_dir=ledger_dir,
        ),
    )
    monkeypatch.setattr(
        server_module,
        "get_briefing",
        lambda: get_briefing(ledger_dir=ledger_dir),
    )
    monkeypatch.setattr(
        server_module,
        "create_evidence_bundle",
        lambda claim, reasoning, evidence: create_evidence_bundle(
            claim=claim, reasoning=reasoning, evidence=evidence, ledger_dir=ledger_dir
        ),
    )
    monkeypatch.setattr(
        server_module,
        "list_evidence",
        lambda: list_evidence(ledger_dir=ledger_dir),
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
    artifact_type: str | None = None,
    confidence: str | None = None,
    orphan_risk: bool | None = None,
):
    async with create_connected_server_and_client_session(mcp) as client:
        arguments: dict = {}
        if artifact_type is not None:
            arguments["artifact_type"] = artifact_type
        if confidence is not None:
            arguments["confidence"] = confidence
        if orphan_risk is not None:
            arguments["orphan_risk"] = orphan_risk
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


def test_list_records_filtered_by_artifact_type_confidence_and_orphan_risk_together(
    ledger_dir: Path,
) -> None:
    """All three `list_records` filters combine as an AND, not just any two
    of them at once (the docstrings claim a full three-way AND, but until
    this test only artifact_type+confidence was ever exercised together).
    """
    # Matches all three filters: type_a, agent-verified, orphan-risk (known
    # but unowned -- has facts, no ownership signal among them).
    append_event(
        RawFact(
            artifact_type="type_a",
            artifact_id="matches",
            source="synthetic:test",
            fields={"author": "someone@example.com"},
        ),
        ledger_dir=ledger_dir,
    )
    # Same artifact_type and confidence, but resolved (not orphan-risk) --
    # must be excluded by the orphan_risk filter.
    append_event(
        RawFact(
            artifact_type="type_a",
            artifact_id="owned",
            source="synthetic:test",
            fields={"support_group": "DR Platform Engineering"},
        ),
        ledger_dir=ledger_dir,
    )
    # Same artifact_type and orphan-risk shape, but "unknown" confidence
    # (empty fields) -- never orphan-risk and wrong confidence; must be
    # excluded by both the confidence and orphan_risk filters.
    append_event(
        RawFact(
            artifact_type="type_a",
            artifact_id="unknown_conf",
            source="synthetic:test",
            fields={},
        ),
        ledger_dir=ledger_dir,
    )
    # Same confidence and orphan-risk shape as the match, but a different
    # artifact_type -- must be excluded by the artifact_type filter.
    append_event(
        RawFact(
            artifact_type="type_b",
            artifact_id="wrong_type",
            source="synthetic:test",
            fields={"author": "someone-else@example.com"},
        ),
        ledger_dir=ledger_dir,
    )

    records = list_records(
        artifact_type="type_a",
        confidence="agent-verified",
        orphan_risk=True,
        ledger_dir=ledger_dir,
    )

    assert len(records) == 1
    assert records[0].artifact_type == "type_a"
    assert records[0].artifact_id == "matches"


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


# ===========================================================================
# Story 8: ownership inference and arbitration
# ===========================================================================


# --- I/O matrix row: single ownership signal (support_group only) ---------


def test_escalation_owner_resolves_from_support_group_alone(
    ledger_dir: Path,
) -> None:
    append_event(
        RawFact(
            artifact_type="test_artifact",
            artifact_id="x1",
            source="synthetic:test",
            fields={"support_group": "DR Platform Engineering"},
        ),
        ledger_dir=ledger_dir,
    )

    record = get_record("test_artifact", "x1", ledger_dir=ledger_dir)

    assert record.escalation_owner == "DR Platform Engineering"


# --- I/O matrix row: single lower-priority signal (assigned_to only) ------


def test_escalation_owner_resolves_from_assigned_to_alone(
    ledger_dir: Path,
) -> None:
    append_event(
        RawFact(
            artifact_type="test_artifact",
            artifact_id="x1",
            source="synthetic:test",
            fields={"assigned_to": "jane.doe"},
        ),
        ledger_dir=ledger_dir,
    )

    record = get_record("test_artifact", "x1", ledger_dir=ledger_dir)

    assert record.escalation_owner == "jane.doe"


def test_escalation_owner_resolves_from_organizer_email_alone(
    ledger_dir: Path,
) -> None:
    append_event(
        RawFact(
            artifact_type="test_artifact",
            artifact_id="x1",
            source="synthetic:test",
            fields={"organizer_email": "owner@example.com"},
        ),
        ledger_dir=ledger_dir,
    )

    record = get_record("test_artifact", "x1", ledger_dir=ledger_dir)

    assert record.escalation_owner == "owner@example.com"


# --- I/O matrix row: blank-string field falls through, not "resolved" ------


def test_escalation_owner_blank_assigned_to_falls_through_to_organizer_email(
    ledger_dir: Path,
) -> None:
    """A real ServiceNow reference field left unassigned commonly renders as
    `""`, not `null`, even with `sysparm_display_value=true` -- and neither
    connector rejects an empty string as a required-field value. A blank
    `assigned_to` must not resolve as a valid (blank) owner; it must fall
    through to the next-priority field exactly as a missing/`None` value
    would.
    """
    append_event(
        RawFact(
            artifact_type="test_artifact",
            artifact_id="x1",
            source="synthetic:test",
            fields={"assigned_to": "", "organizer_email": "owner@example.com"},
        ),
        ledger_dir=ledger_dir,
    )

    record = get_record("test_artifact", "x1", ledger_dir=ledger_dir)

    assert record.escalation_owner == "owner@example.com"


def test_escalation_owner_all_blank_fields_resolves_to_none_and_is_orphan_risk(
    ledger_dir: Path,
) -> None:
    """When every priority field is blank (not merely absent), the artifact
    is genuinely "known but unowned": `escalation_owner` resolves to `None`
    and the record is orphan-risk -- the exact "known but unowned" case this
    story exists to detect, and the one the bug this test guards against
    would have wrongly excluded.
    """
    append_event(
        RawFact(
            artifact_type="test_artifact",
            artifact_id="x1",
            source="synthetic:test",
            fields={"support_group": "", "assigned_to": "   "},
        ),
        ledger_dir=ledger_dir,
    )

    record = get_record("test_artifact", "x1", ledger_dir=ledger_dir)
    assert record.escalation_owner is None

    orphan_records = list_records(orphan_risk=True, ledger_dir=ledger_dir)
    assert len(orphan_records) == 1
    assert orphan_records[0].artifact_id == "x1"


def test_escalation_owner_ignores_non_string_scalar_value(
    ledger_dir: Path,
) -> None:
    """A non-string scalar (e.g. an int/float/bool that reached `fields`)
    must never be returned as `escalation_owner`, which is always a string
    or `None` -- guards the bonus edge case a reviewer flagged alongside the
    main blank-string bug.
    """
    append_event(
        RawFact(
            artifact_type="test_artifact",
            artifact_id="x1",
            source="synthetic:test",
            fields={"support_group": True, "organizer_email": "owner@example.com"},
        ),
        ledger_dir=ledger_dir,
    )

    record = get_record("test_artifact", "x1", ledger_dir=ledger_dir)

    assert record.escalation_owner == "owner@example.com"


# --- I/O matrix row: multiple signals, priority wins -----------------------


def test_escalation_owner_prefers_support_group_over_assigned_to(
    ledger_dir: Path,
) -> None:
    # Two separate facts, as if a CMDB fact and a ticketing fact were both
    # ingested for the same artifact -- neither overwrites the other's field
    # in `fields`, they both fold into the same cumulative dict.
    append_event(
        RawFact(
            artifact_type="test_artifact",
            artifact_id="x1",
            source="servicenow:cmdb",
            fields={"support_group": "DR Platform Engineering"},
        ),
        ledger_dir=ledger_dir,
    )
    append_event(
        RawFact(
            artifact_type="test_artifact",
            artifact_id="x1",
            source="servicenow:ticketing",
            fields={"assigned_to": "jane.doe"},
        ),
        ledger_dir=ledger_dir,
    )

    record = get_record("test_artifact", "x1", ledger_dir=ledger_dir)

    assert record.escalation_owner == "DR Platform Engineering"
    # The lower-priority signal remains visible in `fields`, not discarded.
    assert record.fields["assigned_to"] == "jane.doe"


# --- I/O matrix row: all three signals present ------------------------------


def test_escalation_owner_prefers_support_group_when_all_three_signals_present(
    ledger_dir: Path,
) -> None:
    append_event(
        RawFact(
            artifact_type="test_artifact",
            artifact_id="x1",
            source="synthetic:test",
            fields={
                "support_group": "DR Platform Engineering",
                "assigned_to": "jane.doe",
                "organizer_email": "owner@example.com",
            },
        ),
        ledger_dir=ledger_dir,
    )

    record = get_record("test_artifact", "x1", ledger_dir=ledger_dir)

    assert record.escalation_owner == "DR Platform Engineering"
    assert record.fields["assigned_to"] == "jane.doe"
    assert record.fields["organizer_email"] == "owner@example.com"


# --- I/O matrix row: no ownership signal, but other facts exist -----------


def test_no_ownership_signal_but_other_facts_exist_is_orphan_risk(
    ledger_dir: Path,
) -> None:
    append_event(
        RawFact(
            artifact_type="test_artifact",
            artifact_id="x1",
            source="git:local",
            fields={"author": "someone@example.com", "commit_sha": "abc123"},
        ),
        ledger_dir=ledger_dir,
    )

    record = get_record("test_artifact", "x1", ledger_dir=ledger_dir)
    assert record.escalation_owner is None

    orphan_records = list_records(orphan_risk=True, ledger_dir=ledger_dir)
    assert len(orphan_records) == 1
    assert orphan_records[0].artifact_id == "x1"


# --- I/O matrix row: never observed -----------------------------------------


def test_never_observed_artifact_has_no_owner_and_is_not_orphan_risk(
    ledger_dir: Path,
) -> None:
    record = get_record("test_artifact", "never-ingested", ledger_dir=ledger_dir)
    assert record.escalation_owner is None
    assert record.fields == {}

    # Not orphan-risk: "never observed" != "known but unowned".
    orphan_records = list_records(orphan_risk=True, ledger_dir=ledger_dir)
    assert orphan_records == []


def test_fields_ingested_empty_is_not_orphan_risk(ledger_dir: Path) -> None:
    """Mirrors Story 3's `fields={}` edge case: an artifact with a fact
    recorded but an empty `fields` payload is treated the same as "never
    observed" by `_compute_confidence` -- orphan-risk must agree.
    """
    append_event(
        RawFact(
            artifact_type="test_artifact",
            artifact_id="x1",
            source="synthetic:test",
            fields={},
        ),
        ledger_dir=ledger_dir,
    )

    orphan_records = list_records(orphan_risk=True, ledger_dir=ledger_dir)
    assert orphan_records == []


# --- I/O matrix row: resolved artifact excluded from orphan-risk -----------


def test_resolved_artifact_excluded_from_orphan_risk_filter(
    ledger_dir: Path,
) -> None:
    append_event(
        RawFact(
            artifact_type="test_artifact",
            artifact_id="owned",
            source="synthetic:test",
            fields={"support_group": "DR Platform Engineering"},
        ),
        ledger_dir=ledger_dir,
    )
    append_event(
        RawFact(
            artifact_type="test_artifact",
            artifact_id="unowned",
            source="synthetic:test",
            fields={"author": "someone@example.com"},
        ),
        ledger_dir=ledger_dir,
    )

    orphan_records = list_records(orphan_risk=True, ledger_dir=ledger_dir)

    assert len(orphan_records) == 1
    assert orphan_records[0].artifact_id == "unowned"

    # The inverse filter, `orphan_risk=False`, returns exactly the resolved
    # one instead.
    resolved_records = list_records(orphan_risk=False, ledger_dir=ledger_dir)
    assert len(resolved_records) == 1
    assert resolved_records[0].artifact_id == "owned"


# --- I/O matrix row: no orphans at all --------------------------------------


def test_orphan_risk_filter_returns_empty_list_when_no_orphans_exist(
    ledger_dir: Path,
) -> None:
    append_event(
        RawFact(
            artifact_type="test_artifact",
            artifact_id="x1",
            source="synthetic:test",
            fields={"support_group": "DR Platform Engineering"},
        ),
        ledger_dir=ledger_dir,
    )

    orphan_records = list_records(orphan_risk=True, ledger_dir=ledger_dir)

    assert orphan_records == []


def test_orphan_risk_filter_returns_empty_list_when_ledger_dir_does_not_exist(
    tmp_path: Path,
) -> None:
    missing_dir = tmp_path / "does_not_exist"
    assert not missing_dir.exists()

    assert list_records(orphan_risk=True, ledger_dir=missing_dir) == []


def test_orphan_risk_filter_returns_empty_list_when_log_file_exists_but_has_no_events(
    ledger_dir: Path,
) -> None:
    """Distinct from the `ledger_dir` doesn't exist case above: here the
    artifact-type log file itself exists (and so is discovered as a real
    artifact type) but is empty, meaning zero events fold into zero
    artifact_ids -- there is simply nothing to classify as orphan-risk or
    not, for either value of the filter.
    """
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "test_artifact.log.md").write_text("", encoding="utf-8")

    assert list_records(orphan_risk=True, ledger_dir=ledger_dir) == []
    assert list_records(orphan_risk=False, ledger_dir=ledger_dir) == []


# --- LogFormatError sentinel bypasses the orphan_risk filter ---------------


def test_orphan_risk_filter_still_surfaces_corrupted_type_sentinel(
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
            fields={"support_group": "DR Platform Engineering"},
        ),
        ledger_dir=ledger_dir,
    )

    records = list_records(orphan_risk=True, ledger_dir=ledger_dir)

    # The healthy artifact has a resolved owner, so it's excluded by
    # orphan_risk=True -- but the sentinel is never filterable away.
    assert len(records) == 1
    assert records[0].artifact_id == LOG_FORMAT_ERROR_ARTIFACT_ID


# --- Acceptance criterion: escalation_owner + fields both visible via -----
# ------------------------------------------------- ledger_get_record tool --


def test_ledger_get_record_tool_reports_escalation_owner_with_assigned_to_still_in_fields(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    append_event(
        RawFact(
            artifact_type="test_artifact",
            artifact_id="x1",
            source="servicenow:cmdb",
            fields={"support_group": "DR Platform Engineering"},
        ),
        ledger_dir=ledger_dir,
    )
    append_event(
        RawFact(
            artifact_type="test_artifact",
            artifact_id="x1",
            source="servicenow:ticketing",
            fields={"assigned_to": "jane.doe"},
        ),
        ledger_dir=ledger_dir,
    )
    _point_server_at(monkeypatch, ledger_dir)

    result = asyncio.run(_call_ledger_get_record("test_artifact", "x1"))

    assert result.isError is False
    assert result.structuredContent["escalation_owner"] == "DR Platform Engineering"
    assert result.structuredContent["fields"]["assigned_to"] == "jane.doe"


# --- Acceptance criterion: ledger_list_records(orphan_risk=True) tool -----


def test_ledger_list_records_tool_orphan_risk_filter_matches_list_records(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    append_event(
        RawFact(
            artifact_type="test_artifact",
            artifact_id="owned",
            source="synthetic:test",
            fields={"support_group": "DR Platform Engineering"},
        ),
        ledger_dir=ledger_dir,
    )
    append_event(
        RawFact(
            artifact_type="test_artifact",
            artifact_id="unowned",
            source="synthetic:test",
            fields={"author": "someone@example.com"},
        ),
        ledger_dir=ledger_dir,
    )
    _point_server_at(monkeypatch, ledger_dir)

    result = asyncio.run(_call_ledger_list_records(orphan_risk=True))

    assert result.isError is False
    records = result.structuredContent["result"]
    assert len(records) == 1
    assert records[0]["artifact_id"] == "unowned"
    assert records[0]["escalation_owner"] is None


def test_ledger_list_records_tool_orphan_risk_true_empty_result_never_raises(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    append_event(
        RawFact(
            artifact_type="test_artifact",
            artifact_id="owned",
            source="synthetic:test",
            fields={"support_group": "DR Platform Engineering"},
        ),
        ledger_dir=ledger_dir,
    )
    _point_server_at(monkeypatch, ledger_dir)

    result = asyncio.run(_call_ledger_list_records(orphan_risk=True))

    assert result.isError is False
    assert result.structuredContent == {"result": []}


# --- I/O matrix row: end-to-end, real CMDB + ticketing connectors ---------


def test_end_to_end_cmdb_and_ticketing_facts_resolve_escalation_owner_to_cmdb(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ingests a *real* CMDB fact and a *real* ticketing fact (via the actual
    connector tools, against `httpx.MockTransport` -- no live ServiceNow
    instance is used) for the same artifact, and confirms
    `escalation_owner` resolves to the CMDB value -- proving the
    ownership-arbitration wiring end-to-end rather than with synthetic
    RawFacts.
    """
    monkeypatch.setenv("REZOPS_CMDB_INSTANCE_URL", "https://dev12345.service-now.com")
    monkeypatch.setenv("REZOPS_CMDB_TOKEN", "s3cr3t-cmdb-token")
    monkeypatch.setenv(
        "REZOPS_TICKETING_INSTANCE_URL", "https://dev12345.service-now.com"
    )
    monkeypatch.setenv("REZOPS_TICKETING_TOKEN", "s3cr3t-ticketing-token")

    def cmdb_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "result": {
                    "name": "dr-failover-db01",
                    "sys_class_name": "cmdb_ci_db_instance",
                    "operational_status": "Operational",
                    "install_status": "Installed",
                    "support_group": "DR Platform Engineering",
                    "sys_updated_on": "2026-08-14 10:15:00",
                }
            },
        )

    def ticketing_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "result": {
                    "number": "INC0012345",
                    "state": "2",
                    "assigned_to": "jane.doe",
                    "sys_updated_on": "2026-08-14 10:15:00",
                    "short_description": "Investigate failed DR failover test",
                }
            },
        )

    monkeypatch.setattr(
        "connectors.cmdb.server._build_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(cmdb_handler), timeout=10.0
        ),
    )
    monkeypatch.setattr(
        "connectors.ticketing.server._build_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(ticketing_handler), timeout=10.0
        ),
    )

    cmdb_fact = cmdb_get_ci_status(
        table="cmdb_ci_db_instance",
        sys_id="abc123",
        artifact_type="test_artifact",
        artifact_id="e2e-ownership",
    )
    ticketing_fact = ticketing_get_ticket_status(
        table="incident",
        sys_id="inc123",
        artifact_type="test_artifact",
        artifact_id="e2e-ownership",
    )

    _point_server_at(monkeypatch, ledger_dir)

    cmdb_ingest = asyncio.run(
        _call_ledger_ingest_raw_fact(
            cmdb_fact["artifact_type"],
            cmdb_fact["artifact_id"],
            cmdb_fact["source"],
            cmdb_fact["fields"],
        )
    )
    assert cmdb_ingest.isError is False

    ticketing_ingest = asyncio.run(
        _call_ledger_ingest_raw_fact(
            ticketing_fact["artifact_type"],
            ticketing_fact["artifact_id"],
            ticketing_fact["source"],
            ticketing_fact["fields"],
        )
    )
    assert ticketing_ingest.isError is False

    record_result = asyncio.run(
        _call_ledger_get_record("test_artifact", "e2e-ownership")
    )

    assert record_result.isError is False
    assert (
        record_result.structuredContent["escalation_owner"]
        == "DR Platform Engineering"
    )
    assert record_result.structuredContent["fields"]["assigned_to"] == "jane.doe"


# ===========================================================================
# Story 9: draft-not-send outbound content
# ===========================================================================


# --- I/O matrix row: explicit recipient given -------------------------------


def test_create_draft_with_explicit_recipient_is_unchanged(ledger_dir: Path) -> None:
    draft = create_draft(
        artifact_type="bia",
        artifact_id="sys01",
        draft_type="owner_reconfirmation",
        subject="Please reconfirm ownership of sys01",
        body="Hi -- can you confirm you still own this system?",
        recipient="jane.doe@example.com",
        ledger_dir=ledger_dir,
    )

    assert draft.recipient == "jane.doe@example.com"
    path = ledger_dir / "drafts" / f"{draft.draft_id}.md"
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "recipient: jane.doe@example.com" in text
    assert "artifact_type: bia" in text
    assert "artifact_id: sys01" in text
    assert "draft_type: owner_reconfirmation" in text
    assert "Please reconfirm ownership of sys01" in text
    assert "Hi -- can you confirm you still own this system?" in text


# --- I/O matrix row: no recipient, artifact has a resolved owner -----------


def test_create_draft_no_recipient_defaults_to_resolved_escalation_owner(
    ledger_dir: Path,
) -> None:
    append_event(
        RawFact(
            artifact_type="bia",
            artifact_id="sys01",
            source="synthetic:test",
            fields={"support_group": "DR Platform Engineering"},
        ),
        ledger_dir=ledger_dir,
    )

    draft = create_draft(
        artifact_type="bia",
        artifact_id="sys01",
        draft_type="owner_reconfirmation",
        subject="Please reconfirm ownership of sys01",
        body="Hi -- can you confirm you still own this system?",
        ledger_dir=ledger_dir,
    )

    assert draft.recipient == "DR Platform Engineering"


# --- I/O matrix row: no recipient, artifact is orphan-risk -----------------


def test_create_draft_no_recipient_orphan_risk_artifact_stays_unset_but_creates(
    ledger_dir: Path,
) -> None:
    """The exact case this feature exists to surface: an unresolved owner
    must never be guessed at, but the draft is still created, not blocked.
    """
    append_event(
        RawFact(
            artifact_type="bia",
            artifact_id="sys02",
            source="git:local",
            fields={"author": "someone@example.com"},
        ),
        ledger_dir=ledger_dir,
    )

    draft = create_draft(
        artifact_type="bia",
        artifact_id="sys02",
        draft_type="owner_reconfirmation",
        subject="Who owns sys02?",
        body="No resolved owner was found for this artifact.",
        ledger_dir=ledger_dir,
    )

    assert draft.recipient is None
    path = ledger_dir / "drafts" / f"{draft.draft_id}.md"
    assert path.exists()

    # Also true for an artifact never observed at all (never ingested).
    never_observed_draft = create_draft(
        artifact_type="bia",
        artifact_id="never-ingested",
        draft_type="owner_reconfirmation",
        subject="Who owns this?",
        body="No facts at all exist for this artifact.",
        ledger_dir=ledger_dir,
    )
    assert never_observed_draft.recipient is None


# --- I/O matrix row: list, no filters ---------------------------------------


def test_list_drafts_no_filters_returns_every_draft(ledger_dir: Path) -> None:
    first = create_draft(
        artifact_type="bia",
        artifact_id="sys01",
        draft_type="owner_reconfirmation",
        subject="subject one",
        body="body one",
        recipient="a@example.com",
        ledger_dir=ledger_dir,
    )
    second = create_draft(
        artifact_type="tiering",
        artifact_id="sys02",
        draft_type="tier_review",
        subject="subject two",
        body="body two",
        recipient="b@example.com",
        ledger_dir=ledger_dir,
    )

    drafts = list_drafts(ledger_dir=ledger_dir)

    seen_ids = {draft.draft_id for draft in drafts}
    assert seen_ids == {first.draft_id, second.draft_id}


# --- I/O matrix row: list filtered by artifact_type/artifact_id ------------


def test_list_drafts_filtered_by_artifact_type_and_artifact_id(
    ledger_dir: Path,
) -> None:
    target = create_draft(
        artifact_type="bia",
        artifact_id="sys01",
        draft_type="owner_reconfirmation",
        subject="subject one",
        body="body one",
        ledger_dir=ledger_dir,
    )
    create_draft(
        artifact_type="bia",
        artifact_id="sys02",
        draft_type="owner_reconfirmation",
        subject="subject two",
        body="body two",
        ledger_dir=ledger_dir,
    )
    create_draft(
        artifact_type="tiering",
        artifact_id="sys01",
        draft_type="owner_reconfirmation",
        subject="subject three",
        body="body three",
        ledger_dir=ledger_dir,
    )

    by_type = list_drafts(artifact_type="bia", ledger_dir=ledger_dir)
    assert len(by_type) == 2
    assert all(d.artifact_type == "bia" for d in by_type)

    by_artifact_id = list_drafts(artifact_id="sys01", ledger_dir=ledger_dir)
    assert len(by_artifact_id) == 2
    assert all(d.artifact_id == "sys01" for d in by_artifact_id)

    by_both = list_drafts(
        artifact_type="bia", artifact_id="sys01", ledger_dir=ledger_dir
    )
    assert len(by_both) == 1
    assert by_both[0].draft_id == target.draft_id


# --- I/O matrix row: list filtered by draft_type ----------------------------


def test_list_drafts_filtered_by_draft_type(ledger_dir: Path) -> None:
    target = create_draft(
        artifact_type="bia",
        artifact_id="sys01",
        draft_type="owner_reconfirmation",
        subject="subject one",
        body="body one",
        ledger_dir=ledger_dir,
    )
    create_draft(
        artifact_type="bia",
        artifact_id="sys01",
        draft_type="tier_review",
        subject="subject two",
        body="body two",
        ledger_dir=ledger_dir,
    )

    drafts = list_drafts(draft_type="owner_reconfirmation", ledger_dir=ledger_dir)

    assert len(drafts) == 1
    assert drafts[0].draft_id == target.draft_id
    assert drafts[0].draft_type == "owner_reconfirmation"


# --- I/O matrix row: no drafts yet -------------------------------------------


def test_list_drafts_returns_empty_when_drafts_dir_does_not_exist(
    ledger_dir: Path,
) -> None:
    assert not (ledger_dir / "drafts").exists()

    assert list_drafts(ledger_dir=ledger_dir) == []


def test_list_drafts_returns_empty_when_ledger_dir_does_not_exist(
    tmp_path: Path,
) -> None:
    missing_dir = tmp_path / "does_not_exist"
    assert not missing_dir.exists()

    assert list_drafts(ledger_dir=missing_dir) == []


# --- I/O matrix row: empty/whitespace required field ------------------------


@pytest.mark.parametrize(
    "field_name",
    ["artifact_type", "artifact_id", "draft_type", "subject", "body"],
)
@pytest.mark.parametrize("bad_value", ["", "   "])
def test_create_draft_rejects_empty_or_whitespace_required_field(
    ledger_dir: Path, field_name: str, bad_value: str
) -> None:
    kwargs = {
        "artifact_type": "bia",
        "artifact_id": "sys01",
        "draft_type": "owner_reconfirmation",
        "subject": "subject",
        "body": "body",
        "ledger_dir": ledger_dir,
    }
    kwargs[field_name] = bad_value

    with pytest.raises(DraftValidationError):
        create_draft(**kwargs)

    # Nothing was written as a result of the rejected creation.
    assert list_drafts(ledger_dir=ledger_dir) == []


def test_create_draft_rejects_invalid_charset_in_artifact_identifiers(
    ledger_dir: Path,
) -> None:
    with pytest.raises(DraftValidationError):
        create_draft(
            artifact_type="bad/type",
            artifact_id="sys01",
            draft_type="owner_reconfirmation",
            subject="subject",
            body="body",
            ledger_dir=ledger_dir,
        )

    assert list_drafts(ledger_dir=ledger_dir) == []


# --- I/O matrix row: concurrent-ish creation, no collision ------------------


def test_two_drafts_created_in_quick_succession_both_persist_as_distinct_files(
    ledger_dir: Path,
) -> None:
    first = create_draft(
        artifact_type="bia",
        artifact_id="sys01",
        draft_type="owner_reconfirmation",
        subject="first",
        body="first body",
        ledger_dir=ledger_dir,
    )
    second = create_draft(
        artifact_type="bia",
        artifact_id="sys01",
        draft_type="owner_reconfirmation",
        subject="second",
        body="second body",
        ledger_dir=ledger_dir,
    )

    assert first.draft_id != second.draft_id
    drafts_dir = ledger_dir / "drafts"
    assert (drafts_dir / f"{first.draft_id}.md").exists()
    assert (drafts_dir / f"{second.draft_id}.md").exists()

    drafts = list_drafts(ledger_dir=ledger_dir)
    assert len(drafts) == 2
    assert {d.subject for d in drafts} == {"first", "second"}


def test_create_draft_id_collision_is_retried_not_overwritten(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Forces two consecutive `_generate_draft_id` calls to collide (fixed
    timestamp, fixed random suffix on the first call) and proves the second
    `create_draft` call still succeeds with a distinct file rather than
    silently overwriting the first draft.
    """
    import ledger_core.drafts as drafts_module

    fixed_now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(drafts_module, "datetime", _FixedDateTime)

    suffixes = iter(["aaaaaa", "aaaaaa", "bbbbbb"])
    monkeypatch.setattr(
        drafts_module.secrets, "token_hex", lambda _n: next(suffixes)
    )

    first = create_draft(
        artifact_type="bia",
        artifact_id="sys01",
        draft_type="owner_reconfirmation",
        subject="first",
        body="first body",
        ledger_dir=ledger_dir,
    )
    second = create_draft(
        artifact_type="bia",
        artifact_id="sys01",
        draft_type="owner_reconfirmation",
        subject="second",
        body="second body",
        ledger_dir=ledger_dir,
    )

    assert first.draft_id != second.draft_id
    assert first.draft_id == "20260101T120000Z-aaaaaa"
    assert second.draft_id == "20260101T120000Z-bbbbbb"

    drafts_dir = ledger_dir / "drafts"
    assert (drafts_dir / f"{first.draft_id}.md").read_text(
        encoding="utf-8"
    ).count("first body") == 1
    assert (drafts_dir / f"{second.draft_id}.md").read_text(
        encoding="utf-8"
    ).count("second body") == 1


# --- Fresh read reproduces what create_draft returned ------------------------


def test_list_drafts_round_trips_every_field_create_draft_returned(
    ledger_dir: Path,
) -> None:
    created = create_draft(
        artifact_type="bia",
        artifact_id="sys01",
        draft_type="owner_reconfirmation",
        subject="Please reconfirm ownership",
        body="Line one.\nLine two.",
        recipient="jane.doe@example.com",
        ledger_dir=ledger_dir,
    )

    [read_back] = list_drafts(ledger_dir=ledger_dir)

    assert read_back == created


# --- Never a mutation/delete tool: drafts.py exposes only create + list ----


def test_drafts_module_exposes_only_create_and_list() -> None:
    import ledger_core.drafts as drafts_module

    public_callables = {
        name
        for name in dir(drafts_module)
        if not name.startswith("_") and callable(getattr(drafts_module, name))
    }
    assert "create_draft" in public_callables
    assert "list_drafts" in public_callables
    # No update/delete surface exists.
    assert not any(
        name in public_callables
        for name in ("update_draft", "delete_draft", "edit_draft", "remove_draft")
    )


# --- MCP tool wiring: ledger_create_draft / ledger_list_drafts -------------


async def _call_ledger_create_draft(
    artifact_type: str,
    artifact_id: str,
    draft_type: str,
    subject: str,
    body: str,
    recipient: str | None = None,
):
    async with create_connected_server_and_client_session(mcp) as client:
        arguments: dict = {
            "artifact_type": artifact_type,
            "artifact_id": artifact_id,
            "draft_type": draft_type,
            "subject": subject,
            "body": body,
        }
        if recipient is not None:
            arguments["recipient"] = recipient
        return await client.call_tool("ledger_create_draft", arguments)


async def _call_ledger_list_drafts(
    artifact_type: str | None = None,
    artifact_id: str | None = None,
    draft_type: str | None = None,
):
    async with create_connected_server_and_client_session(mcp) as client:
        arguments: dict = {}
        if artifact_type is not None:
            arguments["artifact_type"] = artifact_type
        if artifact_id is not None:
            arguments["artifact_id"] = artifact_id
        if draft_type is not None:
            arguments["draft_type"] = draft_type
        return await client.call_tool("ledger_list_drafts", arguments)


def test_ledger_create_draft_tool_writes_file_and_returns_draft(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _point_server_at(monkeypatch, ledger_dir)

    result = asyncio.run(
        _call_ledger_create_draft(
            "bia",
            "sys01",
            "owner_reconfirmation",
            "Please reconfirm ownership of sys01",
            "Hi -- can you confirm you still own this system?",
            "jane.doe@example.com",
        )
    )

    assert result.isError is False
    payload = result.structuredContent
    assert payload["artifact_type"] == "bia"
    assert payload["artifact_id"] == "sys01"
    assert payload["draft_type"] == "owner_reconfirmation"
    assert payload["recipient"] == "jane.doe@example.com"
    assert payload["subject"] == "Please reconfirm ownership of sys01"
    assert payload["body"] == "Hi -- can you confirm you still own this system?"
    assert (ledger_dir / "drafts" / f"{payload['draft_id']}.md").exists()


def test_ledger_create_draft_tool_no_recipient_orphan_risk_stays_none(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance criterion: a draft created with no recipient for an
    orphan-risk artifact reports `recipient` absent/`None` when listed, not
    a guessed value.
    """
    append_event(
        RawFact(
            artifact_type="bia",
            artifact_id="sys02",
            source="git:local",
            fields={"author": "someone@example.com"},
        ),
        ledger_dir=ledger_dir,
    )
    _point_server_at(monkeypatch, ledger_dir)

    create_result = asyncio.run(
        _call_ledger_create_draft(
            "bia",
            "sys02",
            "owner_reconfirmation",
            "Who owns sys02?",
            "No resolved owner was found for this artifact.",
        )
    )
    assert create_result.isError is False
    assert create_result.structuredContent["recipient"] is None

    list_result = asyncio.run(_call_ledger_list_drafts(artifact_id="sys02"))
    assert list_result.isError is False
    listed = list_result.structuredContent["result"]
    assert len(listed) == 1
    assert listed[0]["recipient"] is None


def test_ledger_create_draft_tool_rejects_blank_field_without_writing(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _point_server_at(monkeypatch, ledger_dir)

    result = asyncio.run(
        _call_ledger_create_draft("bia", "sys01", "owner_reconfirmation", "", "body")
    )

    assert result.isError is True
    assert not (ledger_dir / "drafts").exists()


def test_ledger_list_drafts_tool_no_filters_matches_list_drafts(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_draft(
        artifact_type="bia",
        artifact_id="sys01",
        draft_type="owner_reconfirmation",
        subject="subject",
        body="body",
        ledger_dir=ledger_dir,
    )
    _point_server_at(monkeypatch, ledger_dir)

    result = asyncio.run(_call_ledger_list_drafts())

    assert result.isError is False
    assert len(result.structuredContent["result"]) == 1


def test_ledger_list_drafts_tool_returns_empty_when_none_exist(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _point_server_at(monkeypatch, ledger_dir)

    result = asyncio.run(_call_ledger_list_drafts())

    assert result.isError is False
    assert result.structuredContent == {"result": []}


def test_ledger_list_drafts_tool_filtered_by_draft_type(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_draft(
        artifact_type="bia",
        artifact_id="sys01",
        draft_type="owner_reconfirmation",
        subject="subject one",
        body="body one",
        ledger_dir=ledger_dir,
    )
    create_draft(
        artifact_type="bia",
        artifact_id="sys01",
        draft_type="tier_review",
        subject="subject two",
        body="body two",
        ledger_dir=ledger_dir,
    )
    _point_server_at(monkeypatch, ledger_dir)

    result = asyncio.run(_call_ledger_list_drafts(draft_type="tier_review"))

    assert result.isError is False
    listed = result.structuredContent["result"]
    assert len(listed) == 1
    assert listed[0]["draft_type"] == "tier_review"


# ===========================================================================
# Story 9 review follow-ups: draft_type escaping, duplicate-key detection,
# per-file error isolation, recipient round-trip, exhausted-attempts /
# NotADirectoryError branches, and sort-order assertion.
# ===========================================================================


# --- Main bug: draft_type with an embedded newline is escaped, not raw -----


def test_create_draft_escapes_draft_type_embedded_newline_and_round_trips(
    ledger_dir: Path,
) -> None:
    """An unescaped `draft_type` with an embedded newline could either break
    the frontmatter fence or inject a fake extra "key: value" line that
    silently overwrites a real field (e.g. `artifact_type`) in the parsed
    metadata. Proves `draft_type` is escaped the same way `subject`/
    `recipient` already are, and that the resulting file round-trips
    cleanly rather than corrupting or being misparsed.
    """
    malicious_draft_type = "tier_review\nartifact_type: injected_type"

    draft = create_draft(
        artifact_type="bia",
        artifact_id="sys01",
        draft_type=malicious_draft_type,
        subject="subject",
        body="body",
        ledger_dir=ledger_dir,
    )

    path = ledger_dir / "drafts" / f"{draft.draft_id}.md"
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Exactly two "---" fence lines: the newline never broke the frontmatter
    # structure into more sections than intended.
    assert lines.count("---") == 2
    # The embedded newline was collapsed to a space, not left as a raw
    # newline -- so no second, injected "artifact_type:" *line* exists
    # anywhere in the file (the escaped draft_type value line legitimately
    # contains "artifact_type:" as plain text within it, which is fine --
    # what matters is it is never its own frontmatter line).
    assert sum(1 for line in lines if line.startswith("artifact_type:")) == 1
    assert "artifact_type: injected_type" not in lines

    [read_back] = list_drafts(ledger_dir=ledger_dir)
    # The real artifact_type was never overwritten by the injected line.
    assert read_back.artifact_type == "bia"
    assert read_back.artifact_id == "sys01"
    # The embedded newline is collapsed to a space at write time (like
    # subject/recipient already were), so this is what round-trips back --
    # not the raw multi-line value `create_draft` was originally given.
    assert read_back.draft_type == "tier_review artifact_type: injected_type"


# --- Duplicate frontmatter key detection (defense in depth) ----------------


def test_parsing_draft_file_with_duplicate_frontmatter_key_raises(
    ledger_dir: Path,
) -> None:
    from ledger_core.drafts import _parse_draft_file

    drafts_dir = ledger_dir / "drafts"
    drafts_dir.mkdir(parents=True)
    tampered = drafts_dir / "20260101T000000Z-abcdef.md"
    tampered.write_text(
        "---\n"
        "artifact_type: bia\n"
        "artifact_id: sys01\n"
        "draft_type: owner_reconfirmation\n"
        "subject: subject\n"
        "recipient: \n"
        "created_at: 2026-01-01T00:00:00Z\n"
        "artifact_type: injected\n"
        "---\n\n"
        "body\n",
        encoding="utf-8",
    )

    with pytest.raises(DraftFileFormatError):
        _parse_draft_file(tampered)


# --- Fix 3: a corrupted/tampered draft file isolates to itself -------------


def test_list_drafts_isolates_corrupted_file_and_still_lists_healthy_drafts(
    ledger_dir: Path,
) -> None:
    healthy = create_draft(
        artifact_type="bia",
        artifact_id="sys01",
        draft_type="owner_reconfirmation",
        subject="healthy subject",
        body="healthy body",
        ledger_dir=ledger_dir,
    )

    drafts_dir = ledger_dir / "drafts"
    tampered_path = drafts_dir / "20260101T000000Z-abcdef.md"
    tampered_path.write_text("not a draft file at all", encoding="utf-8")

    drafts = list_drafts(ledger_dir=ledger_dir)

    by_id = {draft.draft_id: draft for draft in drafts}
    assert len(drafts) == 2
    # The healthy draft is unaffected.
    assert by_id[healthy.draft_id] == healthy
    # The corrupted file is surfaced, not silently dropped.
    sentinel = by_id[tampered_path.stem]
    assert sentinel.artifact_type == DRAFT_FORMAT_ERROR_MARKER
    assert sentinel.artifact_id == DRAFT_FORMAT_ERROR_MARKER
    assert sentinel.draft_type == DRAFT_FORMAT_ERROR_MARKER
    assert sentinel.recipient is None

    # The sentinel is always included, even under a filter it doesn't match.
    filtered = list_drafts(artifact_type="bia", ledger_dir=ledger_dir)
    filtered_ids = {draft.draft_id for draft in filtered}
    assert healthy.draft_id in filtered_ids
    assert tampered_path.stem in filtered_ids


# --- Fix 4: empty-string recipient behaves exactly like an omitted one -----


def test_create_draft_empty_string_recipient_triggers_escalation_owner_lookup(
    ledger_dir: Path,
) -> None:
    append_event(
        RawFact(
            artifact_type="bia",
            artifact_id="sys01",
            source="synthetic:test",
            fields={"support_group": "DR Platform Engineering"},
        ),
        ledger_dir=ledger_dir,
    )

    draft = create_draft(
        artifact_type="bia",
        artifact_id="sys01",
        draft_type="owner_reconfirmation",
        subject="subject",
        body="body",
        recipient="   ",
        ledger_dir=ledger_dir,
    )

    # An empty/whitespace-only recipient is treated exactly like an omitted
    # one -- it triggers the escalation_owner lookup, not left as "".
    assert draft.recipient == "DR Platform Engineering"

    [read_back] = list_drafts(ledger_dir=ledger_dir)
    assert read_back == draft


def test_create_draft_empty_string_recipient_with_no_owner_matches_read_back(
    ledger_dir: Path,
) -> None:
    """Even with no resolvable owner, the created Draft and the Draft
    `list_drafts` reads back later must agree (both `None`, never one `""`
    and the other `None`).
    """
    draft = create_draft(
        artifact_type="bia",
        artifact_id="never-ingested",
        draft_type="owner_reconfirmation",
        subject="subject",
        body="body",
        recipient="",
        ledger_dir=ledger_dir,
    )

    assert draft.recipient is None
    [read_back] = list_drafts(ledger_dir=ledger_dir)
    assert read_back == draft


# --- Fix 5: a corrupted target-artifact log degrades to recipient=None -----


def test_create_draft_recipient_lookup_log_format_error_falls_back_to_none(
    ledger_dir: Path,
) -> None:
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "bia.log.md").write_text(
        "this is not a valid event log line\n", encoding="utf-8"
    )

    draft = create_draft(
        artifact_type="bia",
        artifact_id="sys01",
        draft_type="owner_reconfirmation",
        subject="subject",
        body="body",
        ledger_dir=ledger_dir,
    )

    assert draft.recipient is None


# --- Untested RuntimeError branch: _MAX_DRAFT_ID_ATTEMPTS exhausted --------


def test_create_draft_raises_runtime_error_when_max_attempts_exhausted(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ledger_core.drafts as drafts_module

    fixed_now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(drafts_module, "datetime", _FixedDateTime)
    # Every attempt generates the exact same draft_id, so every attempt
    # after the file is first created collides.
    monkeypatch.setattr(drafts_module.secrets, "token_hex", lambda _n: "aaaaaa")

    drafts_dir = ledger_dir / "drafts"
    drafts_dir.mkdir(parents=True)
    (drafts_dir / "20260101T120000Z-aaaaaa.md").write_text(
        "already taken", encoding="utf-8"
    )

    with pytest.raises(RuntimeError):
        create_draft(
            artifact_type="bia",
            artifact_id="sys01",
            draft_type="owner_reconfirmation",
            subject="subject",
            body="body",
            ledger_dir=ledger_dir,
        )


# --- Untested NotADirectoryError branch in _ensure_drafts_dir --------------


def test_create_draft_raises_not_a_directory_error_when_drafts_dir_is_a_file(
    ledger_dir: Path,
) -> None:
    ledger_dir.mkdir(parents=True)
    blocked_drafts_path = ledger_dir / "drafts"
    blocked_drafts_path.write_text("not a directory", encoding="utf-8")

    with pytest.raises(NotADirectoryError):
        create_draft(
            artifact_type="bia",
            artifact_id="sys01",
            draft_type="owner_reconfirmation",
            subject="subject",
            body="body",
            ledger_dir=ledger_dir,
        )


# --- Fix 7: a failed write after successful exclusive create is cleaned up -


def test_create_draft_removes_partial_file_when_write_fails(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ledger_core.drafts as drafts_module

    fixed_now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(drafts_module, "datetime", _FixedDateTime)
    monkeypatch.setattr(drafts_module.secrets, "token_hex", lambda _n: "aaaaaa")

    def _boom(_draft: Draft) -> str:
        raise ValueError("boom")

    monkeypatch.setattr(drafts_module, "_render_draft", _boom)

    with pytest.raises(ValueError, match="boom"):
        create_draft(
            artifact_type="bia",
            artifact_id="sys01",
            draft_type="owner_reconfirmation",
            subject="subject",
            body="body",
            ledger_dir=ledger_dir,
        )

    drafts_dir = ledger_dir / "drafts"
    assert not (drafts_dir / "20260101T120000Z-aaaaaa.md").exists()


# --- Sort-order assertion: list_drafts really returns chronological order --


def test_list_drafts_returns_drafts_in_chronological_filename_order(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Existing list_drafts tests only ever compare *sets* of draft_ids;
    this asserts the claimed chronological/filename sort order actually
    holds for the returned list itself.
    """
    import ledger_core.drafts as drafts_module

    times = iter(
        [
            datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 1, 1, 12, 0, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 1, 12, 0, 2, tzinfo=timezone.utc),
        ]
    )

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return next(times)

    monkeypatch.setattr(drafts_module, "datetime", _FixedDateTime)
    monkeypatch.setattr(drafts_module.secrets, "token_hex", lambda _n: "aaaaaa")

    first = create_draft(
        artifact_type="bia",
        artifact_id="sys01",
        draft_type="owner_reconfirmation",
        subject="created first",
        body="body",
        ledger_dir=ledger_dir,
    )
    second = create_draft(
        artifact_type="bia",
        artifact_id="sys01",
        draft_type="owner_reconfirmation",
        subject="created second",
        body="body",
        ledger_dir=ledger_dir,
    )
    third = create_draft(
        artifact_type="bia",
        artifact_id="sys01",
        draft_type="owner_reconfirmation",
        subject="created third",
        body="body",
        ledger_dir=ledger_dir,
    )

    drafts = list_drafts(ledger_dir=ledger_dir)

    # Not merely the same *set* of draft_ids -- the same order, matching
    # creation order (which the sortable timestamp-prefixed draft_id
    # guarantees also matches filename sort order).
    assert [d.draft_id for d in drafts] == [
        first.draft_id,
        second.draft_id,
        third.draft_id,
    ]


# --- Story 10: periodic briefing (CAP-7) ------------------------------------


def _assert_generated_at_is_utc_timestamp(generated_at: str) -> None:
    # Raises ValueError if the shape doesn't match -- proves `generated_at`
    # really is rendered in the project's one UTC timestamp format, not just
    # "some string".
    parsed = datetime.strptime(generated_at, "%Y-%m-%dT%H:%M:%SZ")
    assert parsed.tzinfo is None  # strptime never attaches tzinfo; format ends "Z"


# --- I/O matrix row: happy path ---------------------------------------------


def test_get_briefing_happy_path_all_sections_populated(ledger_dir: Path) -> None:
    # Orphan-risk: a known artifact with no resolvable escalation_owner.
    append_event(
        RawFact(
            artifact_type="bia",
            artifact_id="sys01",
            source="git:local",
            fields={"author": "someone@example.com"},
        ),
        ledger_dir=ledger_dir,
    )
    # Unknown-confidence: an artifact_id folded in with genuinely no fields.
    append_event(
        RawFact(
            artifact_type="tiering",
            artifact_id="sys02",
            source="synthetic:test",
            fields={},
        ),
        ledger_dir=ledger_dir,
    )
    draft = create_draft(
        artifact_type="bia",
        artifact_id="sys01",
        draft_type="owner_reconfirmation",
        subject="Please reconfirm ownership of sys01",
        body="No resolved owner was found for this artifact.",
        ledger_dir=ledger_dir,
    )

    briefing = get_briefing(ledger_dir=ledger_dir)

    assert isinstance(briefing, Briefing)
    assert [r.artifact_id for r in briefing.orphan_risk] == ["sys01"]
    assert [r.artifact_id for r in briefing.unknown_confidence] == ["sys02"]
    assert [d.draft_id for d in briefing.pending_drafts] == [draft.draft_id]
    assert briefing.data_quality_issues == {}
    _assert_generated_at_is_utc_timestamp(briefing.generated_at)


# --- I/O matrix row: empty ledger -------------------------------------------


def test_get_briefing_empty_ledger_all_sections_empty_never_raises(
    ledger_dir: Path,
) -> None:
    assert not ledger_dir.exists()

    briefing = get_briefing(ledger_dir=ledger_dir)

    assert briefing.orphan_risk == ()
    assert briefing.unknown_confidence == ()
    assert briefing.pending_drafts == ()
    assert briefing.data_quality_issues == {}
    _assert_generated_at_is_utc_timestamp(briefing.generated_at)
    # A pure read never creates the ledger_dir as a side effect.
    assert not ledger_dir.exists()


# --- I/O matrix rows: content matches a direct, live query -----------------


def _seed_mixed_ledger_state(ledger_dir: Path) -> None:
    append_event(
        RawFact(
            artifact_type="bia",
            artifact_id="sys01",
            source="git:local",
            fields={"author": "someone@example.com"},
        ),
        ledger_dir=ledger_dir,
    )
    append_event(
        RawFact(
            artifact_type="cmdb",
            artifact_id="sys03",
            source="cmdb:snow",
            fields={"support_group": "platform-team"},
        ),
        ledger_dir=ledger_dir,
    )
    append_event(
        RawFact(
            artifact_type="tiering",
            artifact_id="sys02",
            source="synthetic:test",
            fields={},
        ),
        ledger_dir=ledger_dir,
    )
    create_draft(
        artifact_type="bia",
        artifact_id="sys01",
        draft_type="owner_reconfirmation",
        subject="subject",
        body="body",
        ledger_dir=ledger_dir,
    )


def test_get_briefing_orphan_risk_section_matches_direct_list_records_call(
    ledger_dir: Path,
) -> None:
    _seed_mixed_ledger_state(ledger_dir)

    briefing = get_briefing(ledger_dir=ledger_dir)
    direct = list_records(orphan_risk=True, ledger_dir=ledger_dir)

    assert briefing.orphan_risk == tuple(direct)
    assert briefing.orphan_risk  # not vacuously true -- at least one record


def test_get_briefing_unknown_confidence_section_matches_direct_list_records_call(
    ledger_dir: Path,
) -> None:
    _seed_mixed_ledger_state(ledger_dir)

    briefing = get_briefing(ledger_dir=ledger_dir)
    direct = list_records(confidence="unknown", ledger_dir=ledger_dir)

    assert briefing.unknown_confidence == tuple(direct)
    assert briefing.unknown_confidence


def test_get_briefing_pending_drafts_section_matches_direct_list_drafts_call(
    ledger_dir: Path,
) -> None:
    _seed_mixed_ledger_state(ledger_dir)

    briefing = get_briefing(ledger_dir=ledger_dir)
    direct = list_drafts(ledger_dir=ledger_dir)

    assert briefing.pending_drafts == tuple(direct)
    assert briefing.pending_drafts


# --- I/O matrix row: corrupted artifact-type log ----------------------------


def test_get_briefing_corrupted_artifact_type_log_surfaces_in_data_quality_issues(
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

    briefing = get_briefing(ledger_dir=ledger_dir)

    # The rest of the briefing still generates -- not aborted by the
    # corrupted type (AD-8: graceful degradation).
    assert briefing.data_quality_issues == {
        "broken_type": {LOG_FORMAT_ERROR_MARKER: 1}
    }
    # The corrupted type's sentinel is real, visible content, per
    # list_records' own existing behavior -- not deduped away here.
    orphan_ids = {r.artifact_id for r in briefing.orphan_risk}
    unknown_ids = {r.artifact_id for r in briefing.unknown_confidence}
    assert LOG_FORMAT_ERROR_ARTIFACT_ID in orphan_ids
    assert LOG_FORMAT_ERROR_ARTIFACT_ID in unknown_ids
    _assert_generated_at_is_utc_timestamp(briefing.generated_at)


def test_get_briefing_multiple_corrupted_artifact_types_all_accumulate(
    ledger_dir: Path,
) -> None:
    """Two (or more) simultaneously-corrupted artifact-type logs must each
    show up in `data_quality_issues` -- not just the first one encountered,
    and not collapsed into a single entry.
    """
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "broken_type_one.log.md").write_text(
        "this is not a valid event log line at all\n", encoding="utf-8"
    )
    (ledger_dir / "broken_type_two.log.md").write_text(
        "also not a valid event log line\n", encoding="utf-8"
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

    briefing = get_briefing(ledger_dir=ledger_dir)

    assert briefing.data_quality_issues == {
        "broken_type_one": {LOG_FORMAT_ERROR_MARKER: 1},
        "broken_type_two": {LOG_FORMAT_ERROR_MARKER: 1},
    }
    # The healthy type is unaffected and not itself flagged.
    assert "healthy_type" not in briefing.data_quality_issues
    _assert_generated_at_is_utc_timestamp(briefing.generated_at)


def test_get_briefing_healthy_types_data_quality_issues_stays_empty(
    ledger_dir: Path,
) -> None:
    append_event(
        RawFact(
            artifact_type="healthy_type",
            artifact_id="h1",
            source="synthetic:test",
            fields={"observed": "value"},
        ),
        ledger_dir=ledger_dir,
    )

    briefing = get_briefing(ledger_dir=ledger_dir)

    assert briefing.data_quality_issues == {}


# --- I/O matrix row: corrupted draft file -----------------------------------


def test_get_briefing_corrupted_draft_file_included_as_sentinel_no_crash(
    ledger_dir: Path,
) -> None:
    healthy = create_draft(
        artifact_type="bia",
        artifact_id="sys01",
        draft_type="owner_reconfirmation",
        subject="healthy subject",
        body="healthy body",
        ledger_dir=ledger_dir,
    )
    drafts_dir = ledger_dir / "drafts"
    tampered_path = drafts_dir / "20260101T000000Z-abcdef.md"
    tampered_path.write_text("not a draft file at all", encoding="utf-8")

    briefing = get_briefing(ledger_dir=ledger_dir)

    by_id = {draft.draft_id: draft for draft in briefing.pending_drafts}
    assert len(briefing.pending_drafts) == 2
    assert by_id[healthy.draft_id] == healthy
    sentinel = by_id[tampered_path.stem]
    assert sentinel.artifact_type == DRAFT_FORMAT_ERROR_MARKER
    _assert_generated_at_is_utc_timestamp(briefing.generated_at)


# --- get_briefing performs no mutation --------------------------------------


def test_get_briefing_writes_nothing(ledger_dir: Path) -> None:
    _seed_mixed_ledger_state(ledger_dir)
    before = {
        path.name: path.read_bytes()
        for path in sorted(ledger_dir.rglob("*"))
        if path.is_file()
    }

    get_briefing(ledger_dir=ledger_dir)

    after = {
        path.name: path.read_bytes()
        for path in sorted(ledger_dir.rglob("*"))
        if path.is_file()
    }
    assert before == after


# --- ledger_get_briefing MCP tool -------------------------------------------


async def _call_ledger_get_briefing():
    async with create_connected_server_and_client_session(mcp) as client:
        return await client.call_tool("ledger_get_briefing", {})


def test_ledger_get_briefing_tool_matches_get_briefing(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_mixed_ledger_state(ledger_dir)
    _point_server_at(monkeypatch, ledger_dir)

    result = asyncio.run(_call_ledger_get_briefing())

    assert result.isError is False
    expected = get_briefing(ledger_dir=ledger_dir)
    assert result.structuredContent == {
        "orphan_risk": [
            server_module._record_to_dict(r) for r in expected.orphan_risk
        ],
        "unknown_confidence": [
            server_module._record_to_dict(r) for r in expected.unknown_confidence
        ],
        "pending_drafts": [
            server_module._draft_to_dict(d) for d in expected.pending_drafts
        ],
        "data_quality_issues": expected.data_quality_issues,
        "generated_at": expected.generated_at,
    }


def test_ledger_get_briefing_tool_empty_ledger_never_raises(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _point_server_at(monkeypatch, ledger_dir)

    result = asyncio.run(_call_ledger_get_briefing())

    assert result.isError is False
    assert result.structuredContent["orphan_risk"] == []
    assert result.structuredContent["unknown_confidence"] == []
    assert result.structuredContent["pending_drafts"] == []
    assert result.structuredContent["data_quality_issues"] == {}
    assert result.structuredContent["generated_at"]


def test_ledger_get_briefing_tool_performs_no_write(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance criterion: `ledger_get_briefing` performs no write of any
    kind -- calling it never creates `ledger_dir`, a log file, or a draft.
    """
    assert not ledger_dir.exists()
    _point_server_at(monkeypatch, ledger_dir)

    result = asyncio.run(_call_ledger_get_briefing())

    assert result.isError is False
    assert not ledger_dir.exists()


def test_ledger_get_briefing_tool_surfaces_corrupted_type_in_data_quality_issues(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "broken_type.log.md").write_text(
        "this is not a valid event log line at all\n", encoding="utf-8"
    )
    _point_server_at(monkeypatch, ledger_dir)

    result = asyncio.run(_call_ledger_get_briefing())

    assert result.isError is False
    assert result.structuredContent["data_quality_issues"] == {
        "broken_type": {LOG_FORMAT_ERROR_MARKER: 1}
    }
