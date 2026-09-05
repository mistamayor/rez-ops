"""Unit tests for the evidence boundary (Story 12, AD-11, CAP-9).

Every test writes to an isolated `ledger_data`-named directory under
pytest's tmp_path, never the real, git-committed ledger_data/ at the repo
root -- mirroring every other test module in this project.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from ledger_core import server as server_module
from ledger_core.evidence import (
    EVIDENCE_FORMAT_ERROR_MARKER,
    EvidenceBundle,
    EvidenceFileFormatError,
    EvidenceRef,
    EvidenceValidationError,
    create_evidence_bundle,
    list_evidence,
)
from ledger_core.log import append_event
from ledger_core.server import mcp
from shared.ledger_schema import RawFact


@pytest.fixture
def ledger_dir(tmp_path: Path) -> Path:
    return tmp_path / "ledger_data"


def _point_server_at(monkeypatch: pytest.MonkeyPatch, ledger_dir: Path) -> None:
    """Redirect the evidence tools' ledger_dir to an isolated tmp directory.

    Mirrors `test_ledger_core.py`'s own `_point_server_at`: the server module
    binds `create_evidence_bundle`/`list_evidence` as plain module-level
    names with no way to pass a `ledger_dir` through the MCP tool surface, so
    tests patch the names the handlers look up at call time.
    """
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


async def _call_ledger_create_evidence(
    claim: str,
    reasoning: str,
    evidence: list[dict],
    extra_arguments: dict | None = None,
):
    async with create_connected_server_and_client_session(mcp) as client:
        arguments: dict = {
            "claim": claim,
            "reasoning": reasoning,
            "evidence": evidence,
        }
        if extra_arguments:
            arguments.update(extra_arguments)
        return await client.call_tool("ledger_create_evidence", arguments)


async def _call_ledger_list_evidence():
    async with create_connected_server_and_client_session(mcp) as client:
        return await client.call_tool("ledger_list_evidence", {})


def _seed_fact(
    ledger_dir: Path,
    artifact_type: str,
    artifact_id: str,
    source: str,
    fields: dict | None = None,
) -> None:
    append_event(
        RawFact(
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            source=source,
            fields=fields or {},
        ),
        ledger_dir=ledger_dir,
    )


# --- I/O matrix row: all citations resolve --------------------------------


def test_all_citations_resolve_confidence_is_one(ledger_dir: Path) -> None:
    _seed_fact(ledger_dir, "runbooks", "r1", "git:abc123")
    _seed_fact(ledger_dir, "runbooks", "r2", "git:def456", {"support_group": "sre"})

    bundle = create_evidence_bundle(
        claim="This runbook looks stale",
        reasoning="No recent commits and no assigned owner",
        evidence=[
            EvidenceRef(artifact_type="runbooks", artifact_id="r1", source="git:abc123"),
            EvidenceRef(artifact_type="runbooks", artifact_id="r2", field="escalation_owner"),
        ],
        ledger_dir=ledger_dir,
    )

    assert bundle.confidence == 1.0
    assert len(bundle.evidence) == 2


# --- I/O matrix row: some citations resolve -------------------------------


def test_two_of_three_citations_resolve_confidence_is_exact_fraction(
    ledger_dir: Path,
) -> None:
    _seed_fact(ledger_dir, "runbooks", "r1", "git:abc123")
    _seed_fact(ledger_dir, "runbooks", "r2", "git:def456", {"support_group": "sre"})

    bundle = create_evidence_bundle(
        claim="This runbook looks stale",
        reasoning="Two of three signals check out",
        evidence=[
            EvidenceRef(artifact_type="runbooks", artifact_id="r1", source="git:abc123"),
            EvidenceRef(artifact_type="runbooks", artifact_id="r2", field="escalation_owner"),
            EvidenceRef(artifact_type="runbooks", artifact_id="r1", source="jira:PROJ-999"),
        ],
        ledger_dir=ledger_dir,
    )

    assert bundle.confidence == 2 / 3
    assert bundle.confidence == 0.6666666666666666

    # Reading it back via list_evidence still shows the exact fraction and
    # all three citations, never silently rounded or dropped.
    [listed] = list_evidence(ledger_dir=ledger_dir)
    assert listed.confidence == 0.6666666666666666
    assert len(listed.evidence) == 3


# --- I/O matrix row: no citations resolve ---------------------------------


def test_no_citations_resolve_confidence_is_zero_bundle_still_created(
    ledger_dir: Path,
) -> None:
    bundle = create_evidence_bundle(
        claim="This runbook looks stale",
        reasoning="Every citation is stale or wrong",
        evidence=[
            EvidenceRef(artifact_type="runbooks", artifact_id="r1", source="git:nonexistent"),
            EvidenceRef(artifact_type="runbooks", artifact_id="r2", field="escalation_owner"),
        ],
        ledger_dir=ledger_dir,
    )

    assert bundle.confidence == 0.0
    evidence_dir = ledger_dir / "evidence"
    assert (evidence_dir / f"{bundle.evidence_id}.md").exists()


# --- I/O matrix row: source-citation --------------------------------------


def test_source_citation_resolves_on_exact_source_match(ledger_dir: Path) -> None:
    _seed_fact(ledger_dir, "bia", "sys01", "servicenow:CMDB123")

    ref = EvidenceRef(artifact_type="bia", artifact_id="sys01", source="servicenow:CMDB123")
    bundle = create_evidence_bundle(
        claim="claim", reasoning="reasoning", evidence=[ref], ledger_dir=ledger_dir
    )
    assert bundle.confidence == 1.0


def test_source_citation_does_not_resolve_on_source_mismatch(ledger_dir: Path) -> None:
    _seed_fact(ledger_dir, "bia", "sys01", "servicenow:CMDB123")

    ref = EvidenceRef(artifact_type="bia", artifact_id="sys01", source="servicenow:OTHER")
    bundle = create_evidence_bundle(
        claim="claim", reasoning="reasoning", evidence=[ref], ledger_dir=ledger_dir
    )
    assert bundle.confidence == 0.0


# --- I/O matrix row: field-citation ----------------------------------------


def test_field_citation_resolves_when_record_has_non_empty_value(
    ledger_dir: Path,
) -> None:
    _seed_fact(ledger_dir, "bia", "sys01", "cmdb:1", {"support_group": "sre-team"})

    ref = EvidenceRef(artifact_type="bia", artifact_id="sys01", field="escalation_owner")
    bundle = create_evidence_bundle(
        claim="claim", reasoning="reasoning", evidence=[ref], ledger_dir=ledger_dir
    )
    assert bundle.confidence == 1.0


def test_field_citation_does_not_resolve_when_record_field_is_blank(
    ledger_dir: Path,
) -> None:
    # No ownership-bearing field is populated -- escalation_owner stays None.
    _seed_fact(ledger_dir, "bia", "sys02", "git:local", {"author": "someone@example.com"})

    ref = EvidenceRef(artifact_type="bia", artifact_id="sys02", field="escalation_owner")
    bundle = create_evidence_bundle(
        claim="claim", reasoning="reasoning", evidence=[ref], ledger_dir=ledger_dir
    )
    assert bundle.confidence == 0.0


def test_field_citation_does_not_resolve_for_never_observed_artifact(
    ledger_dir: Path,
) -> None:
    ref = EvidenceRef(artifact_type="bia", artifact_id="never_seen", field="tier_sla")
    bundle = create_evidence_bundle(
        claim="claim", reasoning="reasoning", evidence=[ref], ledger_dir=ledger_dir
    )
    assert bundle.confidence == 0.0


# --- Regression: source-citation must also check artifact_id (Story 12 review) ---


def test_source_citation_does_not_resolve_against_a_different_artifact_id(
    ledger_dir: Path,
) -> None:
    """Two different artifact_ids of the same artifact_type each get their
    own distinct source. Citing one artifact_id's real source but naming the
    *other* artifact_id must not resolve -- `_resolve_ref` must check
    `artifact_id` in addition to `source`, since one artifact-type log holds
    events for every artifact of that type.
    """
    _seed_fact(ledger_dir, "runbooks", "r1", "git:aaa111")
    _seed_fact(ledger_dir, "runbooks", "r2", "git:bbb222")

    # r2's real source, but cited against r1.
    ref = EvidenceRef(artifact_type="runbooks", artifact_id="r1", source="git:bbb222")
    bundle = create_evidence_bundle(
        claim="claim", reasoning="reasoning", evidence=[ref], ledger_dir=ledger_dir
    )
    assert bundle.confidence == 0.0


# --- Regression: field-citations are whitelisted (Story 12 review) --------


@pytest.mark.parametrize("bogus_field", ["__class__", "__init__", "not_a_real_field"])
def test_field_citation_never_resolves_for_non_whitelisted_field(
    ledger_dir: Path, bogus_field: str
) -> None:
    _seed_fact(ledger_dir, "bia", "sys01", "cmdb:1", {"support_group": "sre-team"})

    ref = EvidenceRef(artifact_type="bia", artifact_id="sys01", field=bogus_field)
    bundle = create_evidence_bundle(
        claim="claim", reasoning="reasoning", evidence=[ref], ledger_dir=ledger_dir
    )
    assert bundle.confidence == 0.0


def test_field_citation_never_resolves_for_confidence_field(ledger_dir: Path) -> None:
    """`LedgerRecord.confidence` is a meta-judgment about verification status,
    not evidence a separate claim can point to -- deliberately excluded from
    the citable-field whitelist even though it's always a non-blank string
    (including the literal value "unknown", which means the opposite of
    resolved evidence).
    """
    _seed_fact(ledger_dir, "bia", "sys01", "cmdb:1", {"support_group": "sre-team"})

    ref = EvidenceRef(artifact_type="bia", artifact_id="sys01", field="confidence")
    bundle = create_evidence_bundle(
        claim="claim", reasoning="reasoning", evidence=[ref], ledger_dir=ledger_dir
    )
    assert bundle.confidence == 0.0


# --- Regression: duplicate citations don't inflate confidence (Story 12 review) ---


def test_duplicate_citations_do_not_inflate_confidence_past_distinct_fraction(
    ledger_dir: Path,
) -> None:
    """Citing the same resolving fact three times plus one non-resolving
    citation must produce the confidence of the *distinct* set (1 resolving
    of 2 distinct claims == 0.5), not 3 resolving of 4 citations == 0.75.
    """
    _seed_fact(ledger_dir, "runbooks", "r1", "git:abc123")

    resolving_ref = EvidenceRef(
        artifact_type="runbooks", artifact_id="r1", source="git:abc123"
    )
    non_resolving_ref = EvidenceRef(
        artifact_type="runbooks", artifact_id="r1", source="git:nonexistent"
    )

    bundle = create_evidence_bundle(
        claim="claim",
        reasoning="reasoning",
        evidence=[resolving_ref, resolving_ref, resolving_ref, non_resolving_ref],
        ledger_dir=ledger_dir,
    )

    assert bundle.confidence == 0.5
    # All four citations as given are still preserved on the bundle itself --
    # only the confidence computation de-duplicates.
    assert len(bundle.evidence) == 4


# --- I/O matrix row: corrupted artifact-type log for a cited artifact -----


def test_corrupted_log_for_source_citation_counts_as_unresolved_not_a_crash(
    ledger_dir: Path,
) -> None:
    log_path = ledger_dir / "runbooks.log.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("not a valid event log line\n", encoding="utf-8")

    ref = EvidenceRef(artifact_type="runbooks", artifact_id="r1", source="git:abc123")
    bundle = create_evidence_bundle(
        claim="claim", reasoning="reasoning", evidence=[ref], ledger_dir=ledger_dir
    )
    assert bundle.confidence == 0.0


def test_corrupted_log_for_field_citation_counts_as_unresolved_not_a_crash(
    ledger_dir: Path,
) -> None:
    log_path = ledger_dir / "runbooks.log.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("not a valid event log line\n", encoding="utf-8")

    ref = EvidenceRef(artifact_type="runbooks", artifact_id="r1", field="escalation_owner")
    bundle = create_evidence_bundle(
        claim="claim", reasoning="reasoning", evidence=[ref], ledger_dir=ledger_dir
    )
    assert bundle.confidence == 0.0


# --- I/O matrix row: empty evidence list -----------------------------------


def test_empty_evidence_list_is_rejected_and_writes_nothing(ledger_dir: Path) -> None:
    with pytest.raises(EvidenceValidationError):
        create_evidence_bundle(
            claim="claim", reasoning="reasoning", evidence=[], ledger_dir=ledger_dir
        )
    assert not (ledger_dir / "evidence").exists()


# --- I/O matrix row: caller supplies confidence ----------------------------


def test_create_evidence_bundle_has_no_confidence_parameter() -> None:
    """A caller-supplied `confidence` argument cannot be passed at all --
    the function raises TypeError (an unexpected keyword argument), not a
    value that ever reaches or influences computed confidence.
    """
    with pytest.raises(TypeError):
        create_evidence_bundle(  # type: ignore[call-arg]
            claim="claim",
            reasoning="reasoning",
            evidence=[EvidenceRef(artifact_type="bia", artifact_id="sys01", field="tier_sla")],
            confidence=0.99,
        )


def test_ledger_create_evidence_tool_ignores_caller_supplied_confidence(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round-trip proof (acceptance criterion): a caller-supplied
    `confidence` argument is impossible to pass through the MCP tool
    signature -- `ledger_create_evidence` has no `confidence` parameter, so a
    client sending one anyway sees it silently dropped before the underlying
    function is ever called; the returned `confidence` is always the one
    ledger-core computed, never the caller-supplied value.
    """
    _point_server_at(monkeypatch, ledger_dir)
    _seed_fact(ledger_dir, "bia", "sys01", "cmdb:1", {"support_group": "sre-team"})

    result = asyncio.run(
        _call_ledger_create_evidence(
            "claim",
            "reasoning",
            [{"artifact_type": "bia", "artifact_id": "sys01", "field": "escalation_owner"}],
            extra_arguments={"confidence": 0.01},
        )
    )

    assert result.isError is False
    # Every cited field resolves, so the ledger-core-computed confidence is
    # 1.0 -- nowhere near the caller-supplied 0.01, proving it had zero
    # effect on the stored/returned value.
    assert result.structuredContent["confidence"] == 1.0


# --- I/O matrix row: empty/whitespace claim/reasoning ----------------------


@pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
def test_blank_claim_is_rejected_and_writes_nothing(ledger_dir: Path, blank: str) -> None:
    with pytest.raises(EvidenceValidationError):
        create_evidence_bundle(
            claim=blank,
            reasoning="reasoning",
            evidence=[EvidenceRef(artifact_type="bia", artifact_id="sys01", field="tier_sla")],
            ledger_dir=ledger_dir,
        )
    assert not (ledger_dir / "evidence").exists()


@pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
def test_blank_reasoning_is_rejected_and_writes_nothing(
    ledger_dir: Path, blank: str
) -> None:
    with pytest.raises(EvidenceValidationError):
        create_evidence_bundle(
            claim="claim",
            reasoning=blank,
            evidence=[EvidenceRef(artifact_type="bia", artifact_id="sys01", field="tier_sla")],
            ledger_dir=ledger_dir,
        )
    assert not (ledger_dir / "evidence").exists()


# --- I/O matrix row: list with no bundles yet ------------------------------


def test_list_evidence_returns_empty_list_when_no_bundles_exist(ledger_dir: Path) -> None:
    assert list_evidence(ledger_dir=ledger_dir) == []


def test_list_evidence_returns_empty_list_when_ledger_dir_does_not_exist(
    tmp_path: Path,
) -> None:
    nonexistent = tmp_path / "does_not_exist"
    assert list_evidence(ledger_dir=nonexistent) == []


# --- EvidenceRef shape validation ------------------------------------------


def test_evidence_ref_rejects_both_source_and_field_set() -> None:
    with pytest.raises(EvidenceValidationError):
        EvidenceRef(
            artifact_type="bia", artifact_id="sys01", source="git:abc", field="tier_sla"
        )


def test_evidence_ref_rejects_neither_source_nor_field_set() -> None:
    with pytest.raises(EvidenceValidationError):
        EvidenceRef(artifact_type="bia", artifact_id="sys01")


def test_evidence_ref_rejects_invalid_identifier_charset() -> None:
    with pytest.raises(EvidenceValidationError):
        EvidenceRef(artifact_type="bia/../etc", artifact_id="sys01", field="tier_sla")


def test_create_evidence_bundle_rejects_non_evidence_ref_item(ledger_dir: Path) -> None:
    with pytest.raises(EvidenceValidationError):
        create_evidence_bundle(
            claim="claim",
            reasoning="reasoning",
            evidence=["not-a-structured-ref"],  # type: ignore[list-item]
            ledger_dir=ledger_dir,
        )
    assert not (ledger_dir / "evidence").exists()


# --- MCP tool: ledger_create_evidence / ledger_list_evidence ---------------


def test_ledger_create_evidence_tool_rejects_bare_string_citation(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A citation must be a structured object -- a bare string can't supply
    the required `artifact_type`/`artifact_id`/`source-or-field` shape, so
    it fails EvidenceRef construction before anything is written.
    """
    _point_server_at(monkeypatch, ledger_dir)

    result = asyncio.run(
        _call_ledger_create_evidence(
            "claim", "reasoning", ["bare-string-citation"]  # type: ignore[list-item]
        )
    )
    assert result.isError is True
    assert not (ledger_dir / "evidence").exists()


def test_ledger_create_evidence_tool_rejects_non_dict_citation_as_validation_error(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-dict citation item (e.g. a bare string mixed into an otherwise
    valid list) must raise `EvidenceValidationError` -- surfaced as a
    structured, non-crashing MCP error -- rather than an unguarded
    `AttributeError` from calling `.get(...)` on a non-dict item.
    """
    _point_server_at(monkeypatch, ledger_dir)

    result = asyncio.run(
        _call_ledger_create_evidence(
            "claim",
            "reasoning",
            [
                {"artifact_type": "bia", "artifact_id": "sys01", "field": "tier_sla"},
                "not-a-dict-citation",  # type: ignore[list-item]
            ],
        )
    )
    assert result.isError is True
    assert not (ledger_dir / "evidence").exists()


def test_ledger_create_evidence_tool_writes_file_and_returns_bundle(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _point_server_at(monkeypatch, ledger_dir)
    _seed_fact(ledger_dir, "runbooks", "r1", "git:abc123")

    result = asyncio.run(
        _call_ledger_create_evidence(
            "This runbook looks stale",
            "No recent verification",
            [{"artifact_type": "runbooks", "artifact_id": "r1", "source": "git:abc123"}],
        )
    )

    assert result.isError is False
    payload = result.structuredContent
    assert payload["claim"] == "This runbook looks stale"
    assert payload["reasoning"] == "No recent verification"
    assert payload["confidence"] == 1.0
    assert payload["evidence"] == [
        {
            "artifact_type": "runbooks",
            "artifact_id": "r1",
            "source": "git:abc123",
            "field": None,
        }
    ]
    assert (ledger_dir / "evidence" / f"{payload['evidence_id']}.md").exists()


def test_ledger_create_evidence_tool_rejects_empty_evidence_list(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _point_server_at(monkeypatch, ledger_dir)

    result = asyncio.run(_call_ledger_create_evidence("claim", "reasoning", []))
    assert result.isError is True
    assert not (ledger_dir / "evidence").exists()


def test_ledger_create_evidence_tool_rejects_blank_claim(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _point_server_at(monkeypatch, ledger_dir)

    result = asyncio.run(
        _call_ledger_create_evidence(
            "",
            "reasoning",
            [{"artifact_type": "bia", "artifact_id": "sys01", "field": "tier_sla"}],
        )
    )
    assert result.isError is True
    assert not (ledger_dir / "evidence").exists()


def test_ledger_list_evidence_tool_two_of_three_citations_resolve_exact_fraction(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance criterion: a bundle with 2 resolving and 1 non-resolving
    citation, read back via `ledger_list_evidence`, reports `confidence`
    exactly `0.6666666666666666` (never silently rounded), with all three
    citations still present.
    """
    _point_server_at(monkeypatch, ledger_dir)
    _seed_fact(ledger_dir, "runbooks", "r1", "git:abc123")
    _seed_fact(ledger_dir, "runbooks", "r2", "git:def456", {"support_group": "sre"})

    create_result = asyncio.run(
        _call_ledger_create_evidence(
            "This runbook looks stale",
            "Two of three signals check out",
            [
                {"artifact_type": "runbooks", "artifact_id": "r1", "source": "git:abc123"},
                {"artifact_type": "runbooks", "artifact_id": "r2", "field": "escalation_owner"},
                {"artifact_type": "runbooks", "artifact_id": "r1", "source": "jira:PROJ-999"},
            ],
        )
    )
    assert create_result.isError is False
    assert create_result.structuredContent["confidence"] == 0.6666666666666666

    list_result = asyncio.run(_call_ledger_list_evidence())
    assert list_result.isError is False
    [listed] = list_result.structuredContent["result"]
    assert listed["confidence"] == 0.6666666666666666
    assert len(listed["evidence"]) == 3


def test_ledger_list_evidence_tool_matches_list_evidence(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _point_server_at(monkeypatch, ledger_dir)
    _seed_fact(ledger_dir, "runbooks", "r1", "git:abc123")
    create_evidence_bundle(
        claim="claim",
        reasoning="reasoning",
        evidence=[EvidenceRef(artifact_type="runbooks", artifact_id="r1", source="git:abc123")],
        ledger_dir=ledger_dir,
    )

    result = asyncio.run(_call_ledger_list_evidence())
    assert result.isError is False
    listed = result.structuredContent["result"]
    assert len(listed) == 1
    assert listed[0]["confidence"] == 1.0


def test_ledger_list_evidence_tool_returns_empty_when_none_exist(
    ledger_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _point_server_at(monkeypatch, ledger_dir)

    result = asyncio.run(_call_ledger_list_evidence())
    assert result.isError is False
    assert result.structuredContent["result"] == []


def test_server_exposes_ledger_create_and_list_evidence_tools() -> None:
    tools = asyncio.run(mcp.list_tools())
    names = [tool.name for tool in tools]
    assert "ledger_create_evidence" in names
    assert "ledger_list_evidence" in names


# --- Corrupted file isolation (AD-8) ---------------------------------------


def test_list_evidence_isolates_corrupted_file_and_still_lists_healthy_bundle(
    ledger_dir: Path,
) -> None:
    _seed_fact(ledger_dir, "runbooks", "r1", "git:abc123")
    healthy = create_evidence_bundle(
        claim="claim",
        reasoning="reasoning",
        evidence=[EvidenceRef(artifact_type="runbooks", artifact_id="r1", source="git:abc123")],
        ledger_dir=ledger_dir,
    )

    corrupted_path = ledger_dir / "evidence" / "corrupted.md"
    corrupted_path.write_text("not frontmatter at all", encoding="utf-8")

    bundles = list_evidence(ledger_dir=ledger_dir)
    by_id = {bundle.evidence_id: bundle for bundle in bundles}

    assert len(bundles) == 2
    assert by_id[healthy.evidence_id].confidence == 1.0
    corrupted = by_id["corrupted"]
    assert corrupted.claim == EVIDENCE_FORMAT_ERROR_MARKER
    assert corrupted.generated_at == EVIDENCE_FORMAT_ERROR_MARKER
    assert corrupted.confidence == 0.0
    assert corrupted.evidence == ()


def test_list_evidence_isolates_unreadable_file_and_still_lists_healthy_bundle(
    ledger_dir: Path,
) -> None:
    """A file that raises `OSError`/`UnicodeDecodeError` when read (e.g. a
    permissions problem, or invalid encoding) must be isolated the same way
    a malformed-but-readable file already is -- not crash the whole listing.
    """
    _seed_fact(ledger_dir, "runbooks", "r1", "git:abc123")
    healthy = create_evidence_bundle(
        claim="claim",
        reasoning="reasoning",
        evidence=[EvidenceRef(artifact_type="runbooks", artifact_id="r1", source="git:abc123")],
        ledger_dir=ledger_dir,
    )

    unreadable_path = ledger_dir / "evidence" / "unreadable.md"
    # Invalid UTF-8 bytes -- `path.read_text(encoding="utf-8")` raises
    # UnicodeDecodeError, not EvidenceFileFormatError.
    unreadable_path.write_bytes(b"\xff\xfe not valid utf-8 frontmatter")

    bundles = list_evidence(ledger_dir=ledger_dir)
    by_id = {bundle.evidence_id: bundle for bundle in bundles}

    assert len(bundles) == 2
    assert by_id[healthy.evidence_id].confidence == 1.0
    unreadable = by_id["unreadable"]
    assert unreadable.claim == EVIDENCE_FORMAT_ERROR_MARKER
    assert unreadable.confidence == 0.0


def test_parsing_bundle_file_with_confidence_out_of_range_raises(
    ledger_dir: Path,
) -> None:
    evidence_dir = ledger_dir / "evidence"
    evidence_dir.mkdir(parents=True)
    path = evidence_dir / "bad_confidence.md"
    path.write_text(
        "---\n"
        "claim: a\n"
        "confidence: 1.5\n"
        "evidence: []\n"
        "generated_at: 2026-09-05T00:00:00Z\n"
        "---\n\n"
        "reasoning text\n",
        encoding="utf-8",
    )

    from ledger_core.evidence import _parse_bundle_file

    with pytest.raises(EvidenceFileFormatError):
        _parse_bundle_file(path)


def test_parsing_bundle_file_with_nan_confidence_raises(ledger_dir: Path) -> None:
    evidence_dir = ledger_dir / "evidence"
    evidence_dir.mkdir(parents=True)
    path = evidence_dir / "nan_confidence.md"
    path.write_text(
        "---\n"
        "claim: a\n"
        "confidence: nan\n"
        "evidence: []\n"
        "generated_at: 2026-09-05T00:00:00Z\n"
        "---\n\n"
        "reasoning text\n",
        encoding="utf-8",
    )

    from ledger_core.evidence import _parse_bundle_file

    with pytest.raises(EvidenceFileFormatError):
        _parse_bundle_file(path)


def test_parsing_bundle_file_with_duplicate_frontmatter_key_raises(
    ledger_dir: Path,
) -> None:
    evidence_dir = ledger_dir / "evidence"
    evidence_dir.mkdir(parents=True)
    path = evidence_dir / "dup.md"
    path.write_text(
        "---\n"
        "claim: a\n"
        "claim: b\n"
        "confidence: 1.0\n"
        "evidence: []\n"
        "generated_at: 2026-09-05T00:00:00Z\n"
        "---\n\n"
        "reasoning text\n",
        encoding="utf-8",
    )

    from ledger_core.evidence import _parse_bundle_file

    with pytest.raises(EvidenceFileFormatError):
        _parse_bundle_file(path)


# --- Round-trip fidelity ----------------------------------------------------


def test_create_evidence_bundle_round_trips_claim_reasoning_and_citations(
    ledger_dir: Path,
) -> None:
    _seed_fact(ledger_dir, "runbooks", "r1", "git:abc123")
    _seed_fact(ledger_dir, "bia", "sys01", "cmdb:1", {"support_group": "sre-team"})

    created = create_evidence_bundle(
        claim="This runbook looks stale",
        reasoning="Line one.\nLine two.",
        evidence=[
            EvidenceRef(artifact_type="runbooks", artifact_id="r1", source="git:abc123"),
            EvidenceRef(artifact_type="bia", artifact_id="sys01", field="escalation_owner"),
        ],
        ledger_dir=ledger_dir,
    )

    [listed] = list_evidence(ledger_dir=ledger_dir)
    assert listed.evidence_id == created.evidence_id
    assert listed.claim == created.claim
    assert listed.reasoning == created.reasoning
    assert listed.confidence == created.confidence == 1.0
    assert listed.generated_at == created.generated_at
    assert set(listed.evidence) == set(created.evidence)


def test_two_bundles_created_in_quick_succession_both_persist_as_distinct_files(
    ledger_dir: Path,
) -> None:
    ref = EvidenceRef(artifact_type="bia", artifact_id="sys01", field="tier_sla")
    first = create_evidence_bundle(
        claim="claim one", reasoning="reasoning one", evidence=[ref], ledger_dir=ledger_dir
    )
    second = create_evidence_bundle(
        claim="claim two", reasoning="reasoning two", evidence=[ref], ledger_dir=ledger_dir
    )

    assert first.evidence_id != second.evidence_id
    assert (ledger_dir / "evidence" / f"{first.evidence_id}.md").exists()
    assert (ledger_dir / "evidence" / f"{second.evidence_id}.md").exists()


def test_evidence_bundle_never_written_when_validation_fails_before_any_side_effect(
    ledger_dir: Path,
) -> None:
    with pytest.raises(EvidenceValidationError):
        create_evidence_bundle(
            claim="claim", reasoning="", evidence=[], ledger_dir=ledger_dir
        )
    assert not ledger_dir.exists()
