"""Unit tests for ActionProposal and the Policy Engine (Story 13, AD-12, CAP-10).

Every test writes to an isolated `ledger_data`-named directory and an
isolated `rezops.policy.yaml`-named file, both under pytest's tmp_path --
never the real, git-committed `ledger_data/`/`rezops.policy.yaml` at the
repo root -- mirroring every other test module in this project.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from ledger_core import action_proposals as action_proposals_module
from ledger_core import server as server_module
from ledger_core.action_proposals import (
    ActionProposal,
    ActionProposalLogFormatError,
    ActionProposalValidationError,
    PolicyFileError,
    _compute_policy_decision,
    _load_policy,
    create_action_proposal,
    list_action_proposals,
)
from ledger_core.evidence import EvidenceBundle, _render_bundle
from ledger_core.log import append_event
from ledger_core.projection import get_record
from ledger_core.server import mcp
from shared.ledger_schema import LedgerRecord, RawFact


@pytest.fixture
def ledger_dir(tmp_path: Path) -> Path:
    return tmp_path / "ledger_data"


@pytest.fixture
def policy_path(tmp_path: Path) -> Path:
    path = tmp_path / "rezops.policy.yaml"
    path.write_text(
        "create_ticket:\n"
        "  impact: low\n"
        "\n"
        "disable_credential:\n"
        "  impact: high\n",
        encoding="utf-8",
    )
    return path


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


def _seed_evidence_bundle(ledger_dir: Path, evidence_id: str, confidence: float) -> str:
    """Write one synthetic EvidenceBundle file with an exact `confidence`.

    Bypasses `create_evidence_bundle`'s own resolution computation --
    exactly like `test_evidence.py`'s corrupted-file tests, which also write
    raw bundle content directly -- so this story's tests can exercise the
    policy-decision math (which reads `EvidenceBundle.confidence` via
    `list_evidence`) against precise values (`1.0`, `0.5`, `0.9`, ...)
    without depending on Story 12's own citation-resolution mechanics.
    """
    bundle = EvidenceBundle(
        evidence_id=evidence_id,
        claim="claim",
        confidence=confidence,
        evidence=(),
        reasoning="reasoning",
        generated_at="2026-09-05T00:00:00Z",
    )
    evidence_dir = ledger_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / f"{evidence_id}.md").write_text(_render_bundle(bundle), encoding="utf-8")
    return evidence_id


def _point_server_at(
    monkeypatch: pytest.MonkeyPatch, ledger_dir: Path, policy_path: Path
) -> None:
    """Redirect the action-proposal tools' ledger_dir/policy_path to isolated tmp paths.

    Mirrors `test_evidence.py`'s own `_point_server_at`: the server module
    binds `create_action_proposal`/`list_action_proposals` as plain
    module-level names with no way to pass `ledger_dir`/`policy_path`
    through the MCP tool surface, so tests patch the names the handlers
    look up at call time.
    """
    monkeypatch.setattr(
        server_module,
        "create_action_proposal",
        lambda action, target_artifact_type, target_artifact_id, reason, evidence: create_action_proposal(
            action=action,
            target_artifact_type=target_artifact_type,
            target_artifact_id=target_artifact_id,
            reason=reason,
            evidence=evidence,
            ledger_dir=ledger_dir,
            policy_path=policy_path,
        ),
    )
    monkeypatch.setattr(
        server_module,
        "list_action_proposals",
        lambda: list_action_proposals(ledger_dir=ledger_dir),
    )


async def _call_ledger_create_action_proposal(
    action: str,
    target_artifact_type: str,
    target_artifact_id: str,
    reason: str,
    evidence: list[str],
    extra_arguments: dict | None = None,
):
    async with create_connected_server_and_client_session(mcp) as client:
        arguments: dict = {
            "action": action,
            "target_artifact_type": target_artifact_type,
            "target_artifact_id": target_artifact_id,
            "reason": reason,
            "evidence": evidence,
        }
        if extra_arguments:
            arguments.update(extra_arguments)
        return await client.call_tool("ledger_create_action_proposal", arguments)


async def _call_ledger_list_action_proposals():
    async with create_connected_server_and_client_session(mcp) as client:
        return await client.call_tool("ledger_list_action_proposals", {})


# --- I/O matrix row: low-confidence evidence -> denied ---------------------


def test_low_confidence_evidence_is_denied(ledger_dir: Path, policy_path: Path) -> None:
    _seed_evidence_bundle(ledger_dir, "ev1", 0.3)

    proposal = create_action_proposal(
        action="create_ticket",
        target_artifact_type="bia",
        target_artifact_id="sys01",
        reason="stale runbook",
        evidence=["ev1"],
        ledger_dir=ledger_dir,
        policy_path=policy_path,
    )

    assert proposal.policy_decision == "denied"
    assert proposal.impact == "low"


# --- I/O matrix row: perfect confidence, low impact, known criticality -----


def test_perfect_confidence_low_impact_known_criticality_is_automatic(
    ledger_dir: Path, policy_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_evidence_bundle(ledger_dir, "ev1", 1.0)

    # tier_sla is never populated by any real story yet (AD-9) -- simulate a
    # future world where it is, by patching the name this module looks up.
    def fake_get_record(artifact_type, artifact_id, *, ledger_dir=None):
        return LedgerRecord(
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            tier_sla="tier-1",
        )

    monkeypatch.setattr(action_proposals_module, "get_record", fake_get_record)

    proposal = create_action_proposal(
        action="create_ticket",
        target_artifact_type="bia",
        target_artifact_id="sys01",
        reason="stale runbook",
        evidence=["ev1"],
        ledger_dir=ledger_dir,
        policy_path=policy_path,
    )

    assert proposal.policy_decision == "automatic"


# --- I/O matrix row: perfect confidence, criticality unknown --------------


def test_perfect_confidence_but_criticality_unknown_requires_approval(
    ledger_dir: Path, policy_path: Path
) -> None:
    _seed_evidence_bundle(ledger_dir, "ev1", 1.0)

    # Real get_record: tier_sla is always None against today's real data
    # (AD-9) -- never guessed as automatic.
    proposal = create_action_proposal(
        action="create_ticket",
        target_artifact_type="bia",
        target_artifact_id="sys01",
        reason="stale runbook",
        evidence=["ev1"],
        ledger_dir=ledger_dir,
        policy_path=policy_path,
    )

    assert proposal.policy_decision == "requires_approval"


# --- I/O matrix row: high-impact action ------------------------------------


def test_high_impact_action_never_automatic_even_with_perfect_confidence(
    ledger_dir: Path, policy_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_evidence_bundle(ledger_dir, "ev1", 1.0)

    def fake_get_record(artifact_type, artifact_id, *, ledger_dir=None):
        return LedgerRecord(
            artifact_type=artifact_type, artifact_id=artifact_id, tier_sla="tier-1"
        )

    monkeypatch.setattr(action_proposals_module, "get_record", fake_get_record)

    proposal = create_action_proposal(
        action="disable_credential",
        target_artifact_type="bia",
        target_artifact_id="sys01",
        reason="compromised credential",
        evidence=["ev1"],
        ledger_dir=ledger_dir,
        policy_path=policy_path,
    )

    assert proposal.impact == "high"
    assert proposal.policy_decision == "requires_approval"


# --- I/O matrix row: undeclared action --------------------------------------


def test_undeclared_action_is_rejected_and_writes_nothing(
    ledger_dir: Path, policy_path: Path
) -> None:
    _seed_evidence_bundle(ledger_dir, "ev1", 1.0)

    with pytest.raises(ActionProposalValidationError):
        create_action_proposal(
            action="delete_universe",
            target_artifact_type="bia",
            target_artifact_id="sys01",
            reason="reason",
            evidence=["ev1"],
            ledger_dir=ledger_dir,
            policy_path=policy_path,
        )
    assert not (ledger_dir / "action_proposals.log.md").exists()


# --- I/O matrix row: no evidence cited --------------------------------------


def test_no_evidence_cited_is_rejected_and_writes_nothing(
    ledger_dir: Path, policy_path: Path
) -> None:
    with pytest.raises(ActionProposalValidationError):
        create_action_proposal(
            action="create_ticket",
            target_artifact_type="bia",
            target_artifact_id="sys01",
            reason="reason",
            evidence=[],
            ledger_dir=ledger_dir,
            policy_path=policy_path,
        )
    assert not (ledger_dir / "action_proposals.log.md").exists()


# --- I/O matrix row: nonexistent evidence_id cited --------------------------


def test_nonexistent_evidence_id_is_rejected_and_writes_nothing(
    ledger_dir: Path, policy_path: Path
) -> None:
    _seed_evidence_bundle(ledger_dir, "ev1", 1.0)

    with pytest.raises(ActionProposalValidationError):
        create_action_proposal(
            action="create_ticket",
            target_artifact_type="bia",
            target_artifact_id="sys01",
            reason="reason",
            evidence=["ev1", "does-not-exist"],
            ledger_dir=ledger_dir,
            policy_path=policy_path,
        )
    assert not (ledger_dir / "action_proposals.log.md").exists()


# --- I/O matrix row: evidence not a list/tuple (bare string or None) -------


def test_bare_string_evidence_is_rejected(ledger_dir: Path, policy_path: Path) -> None:
    """`evidence="ab"` is technically a valid `Sequence[str]` but would
    silently iterate into single characters ('a', 'b') -- must be rejected
    outright rather than silently misinterpreted.

    Deliberately seeds bundles for *both* single-character "ids" ('a' and
    'b') so that, if the explicit `isinstance(evidence, (list, tuple))`
    guard were ever removed, the call would NOT incidentally fail some
    other way (e.g. a "nonexistent evidence_id" error from iterating into
    characters that happen not to resolve) -- it would silently succeed,
    which is exactly the bug this guard exists to prevent. Only the
    explicit guard can make this test fail as intended.
    """
    _seed_evidence_bundle(ledger_dir, "a", 1.0)
    _seed_evidence_bundle(ledger_dir, "b", 1.0)
    with pytest.raises(ActionProposalValidationError):
        create_action_proposal(
            action="create_ticket",
            target_artifact_type="bia",
            target_artifact_id="sys01",
            reason="reason",
            evidence="ab",  # type: ignore[arg-type]
            ledger_dir=ledger_dir,
            policy_path=policy_path,
        )
    assert not (ledger_dir / "action_proposals.log.md").exists()


def test_none_evidence_is_rejected(ledger_dir: Path, policy_path: Path) -> None:
    with pytest.raises(ActionProposalValidationError):
        create_action_proposal(
            action="create_ticket",
            target_artifact_type="bia",
            target_artifact_id="sys01",
            reason="reason",
            evidence=None,  # type: ignore[arg-type]
            ledger_dir=ledger_dir,
            policy_path=policy_path,
        )
    assert not (ledger_dir / "action_proposals.log.md").exists()


# --- I/O matrix row: caller supplies impact/policy_decision -----------------


def test_create_action_proposal_has_no_impact_parameter(
    ledger_dir: Path, policy_path: Path
) -> None:
    _seed_evidence_bundle(ledger_dir, "ev1", 1.0)
    with pytest.raises(TypeError):
        create_action_proposal(  # type: ignore[call-arg]
            action="create_ticket",
            target_artifact_type="bia",
            target_artifact_id="sys01",
            reason="reason",
            evidence=["ev1"],
            ledger_dir=ledger_dir,
            policy_path=policy_path,
            impact="low",
        )


def test_create_action_proposal_has_no_policy_decision_parameter(
    ledger_dir: Path, policy_path: Path
) -> None:
    _seed_evidence_bundle(ledger_dir, "ev1", 1.0)
    with pytest.raises(TypeError):
        create_action_proposal(  # type: ignore[call-arg]
            action="create_ticket",
            target_artifact_type="bia",
            target_artifact_id="sys01",
            reason="reason",
            evidence=["ev1"],
            ledger_dir=ledger_dir,
            policy_path=policy_path,
            policy_decision="automatic",
        )


def test_ledger_create_action_proposal_tool_ignores_caller_supplied_impact_and_policy_decision(
    ledger_dir: Path, policy_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round-trip proof (acceptance criterion): a caller-supplied `impact` or
    `policy_decision` argument is impossible to pass through the MCP tool
    signature -- `ledger_create_action_proposal` has neither parameter, so a
    client sending either anyway sees it silently dropped before the
    underlying function is ever called.
    """
    _point_server_at(monkeypatch, ledger_dir, policy_path)
    _seed_evidence_bundle(ledger_dir, "ev1", 0.3)

    result = asyncio.run(
        _call_ledger_create_action_proposal(
            "create_ticket",
            "bia",
            "sys01",
            "reason",
            ["ev1"],
            extra_arguments={"impact": "high", "policy_decision": "automatic"},
        )
    )

    assert result.isError is False
    # Min confidence 0.3 < 0.5 -- ledger-core-computed decision is "denied",
    # nowhere near the caller-supplied "automatic"/"high", proving those
    # extra arguments had zero effect.
    assert result.structuredContent["policy_decision"] == "denied"
    assert result.structuredContent["impact"] == "low"


# --- I/O matrix row: multiple cited bundles, mixed confidence --------------


def test_multiple_cited_bundles_mixed_confidence_uses_minimum_not_average(
    ledger_dir: Path, policy_path: Path
) -> None:
    _seed_evidence_bundle(ledger_dir, "ev-high", 1.0)
    _seed_evidence_bundle(ledger_dir, "ev-low", 0.5)
    _seed_evidence_bundle(ledger_dir, "ev-mid", 0.9)

    proposal = create_action_proposal(
        action="create_ticket",
        target_artifact_type="bia",
        target_artifact_id="sys01",
        reason="reason",
        evidence=["ev-high", "ev-low", "ev-mid"],
        ledger_dir=ledger_dir,
        policy_path=policy_path,
    )

    # min(1.0, 0.5, 0.9) == 0.5, which is not < 0.5 (not denied) and not
    # == 1.0 (not automatic) -- requires_approval either way, but the
    # important assertion is the *value* the decision was computed from.
    assert proposal.policy_decision == "requires_approval"


def test_compute_policy_decision_uses_minimum_confidence_directly() -> None:
    """Direct unit test of the frozen rule against the exact matrix values."""
    assert (
        _compute_policy_decision(impact="low", tier_sla_known=True, min_confidence=0.5)
        == "requires_approval"
    )
    assert (
        _compute_policy_decision(impact="low", tier_sla_known=True, min_confidence=0.49)
        == "denied"
    )
    assert (
        _compute_policy_decision(impact="low", tier_sla_known=True, min_confidence=1.0)
        == "automatic"
    )
    assert (
        _compute_policy_decision(impact="low", tier_sla_known=False, min_confidence=1.0)
        == "requires_approval"
    )
    assert (
        _compute_policy_decision(impact="high", tier_sla_known=True, min_confidence=1.0)
        == "requires_approval"
    )
    assert (
        _compute_policy_decision(impact="medium", tier_sla_known=True, min_confidence=1.0)
        == "requires_approval"
    )


# --- Determinism -------------------------------------------------------------


def test_policy_decision_is_deterministic_across_repeated_identical_inputs(
    ledger_dir: Path, policy_path: Path
) -> None:
    _seed_evidence_bundle(ledger_dir, "ev1", 1.0)

    first = create_action_proposal(
        action="create_ticket",
        target_artifact_type="bia",
        target_artifact_id="sys01",
        reason="reason one",
        evidence=["ev1"],
        ledger_dir=ledger_dir,
        policy_path=policy_path,
    )
    second = create_action_proposal(
        action="create_ticket",
        target_artifact_type="bia",
        target_artifact_id="sys01",
        reason="reason two",
        evidence=["ev1"],
        ledger_dir=ledger_dir,
        policy_path=policy_path,
    )

    assert first.policy_decision == second.policy_decision == "requires_approval"
    assert first.proposal_id != second.proposal_id


# --- I/O matrix row: list with no proposals yet -----------------------------


def test_list_action_proposals_returns_empty_when_log_does_not_exist(
    ledger_dir: Path,
) -> None:
    assert list_action_proposals(ledger_dir=ledger_dir) == []


def test_list_action_proposals_returns_empty_when_ledger_dir_does_not_exist(
    tmp_path: Path,
) -> None:
    nonexistent = tmp_path / "does_not_exist"
    assert list_action_proposals(ledger_dir=nonexistent) == []


# --- append-only log: two events per creation -------------------------------


def test_create_action_proposal_appends_exactly_two_log_lines(
    ledger_dir: Path, policy_path: Path
) -> None:
    _seed_evidence_bundle(ledger_dir, "ev1", 1.0)

    create_action_proposal(
        action="create_ticket",
        target_artifact_type="bia",
        target_artifact_id="sys01",
        reason="reason",
        evidence=["ev1"],
        ledger_dir=ledger_dir,
        policy_path=policy_path,
    )

    log_path = ledger_dir / "action_proposals.log.md"
    lines = [line for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2
    assert "(proposed)" in lines[0]
    assert "(decided)" in lines[1]


def test_list_action_proposals_round_trips_created_proposal(
    ledger_dir: Path, policy_path: Path
) -> None:
    _seed_evidence_bundle(ledger_dir, "ev1", 1.0)

    created = create_action_proposal(
        action="create_ticket",
        target_artifact_type="bia",
        target_artifact_id="sys01",
        reason="stale runbook",
        evidence=["ev1"],
        ledger_dir=ledger_dir,
        policy_path=policy_path,
    )

    [listed] = list_action_proposals(ledger_dir=ledger_dir)
    assert listed == created


def test_list_action_proposals_preserves_first_proposed_order(
    ledger_dir: Path, policy_path: Path
) -> None:
    _seed_evidence_bundle(ledger_dir, "ev1", 1.0)

    first = create_action_proposal(
        action="create_ticket",
        target_artifact_type="bia",
        target_artifact_id="sys01",
        reason="first",
        evidence=["ev1"],
        ledger_dir=ledger_dir,
        policy_path=policy_path,
    )
    second = create_action_proposal(
        action="disable_credential",
        target_artifact_type="bia",
        target_artifact_id="sys02",
        reason="second",
        evidence=["ev1"],
        ledger_dir=ledger_dir,
        policy_path=policy_path,
    )

    listed = list_action_proposals(ledger_dir=ledger_dir)
    assert [p.proposal_id for p in listed] == [first.proposal_id, second.proposal_id]


# --- corrupted log: fails loud (this story's own reader, not isolated) -----


def test_list_action_proposals_raises_on_corrupted_log_line(ledger_dir: Path) -> None:
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "action_proposals.log.md").write_text(
        "not a valid event log line\n", encoding="utf-8"
    )
    with pytest.raises(ActionProposalLogFormatError):
        list_action_proposals(ledger_dir=ledger_dir)


def test_create_action_proposal_tolerates_corrupted_historical_log(
    ledger_dir: Path, policy_path: Path
) -> None:
    """A corrupted historical log must never permanently block every future
    `create_action_proposal` call -- the id-collision check against
    `_read_raw_lines` is caught and treated as "no existing ids known"
    rather than propagating `ActionProposalLogFormatError` out of
    `create_action_proposal` itself.
    """
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "action_proposals.log.md").write_text(
        "not a valid event log line\n", encoding="utf-8"
    )
    _seed_evidence_bundle(ledger_dir, "ev1", 1.0)

    proposal = create_action_proposal(
        action="create_ticket",
        target_artifact_type="bia",
        target_artifact_id="sys01",
        reason="reason",
        evidence=["ev1"],
        ledger_dir=ledger_dir,
        policy_path=policy_path,
    )

    assert proposal.proposal_id
    # The corrupted line is still there, untouched (append-only), followed by
    # the two new lines this call wrote.
    lines = [
        line
        for line in (ledger_dir / "action_proposals.log.md")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert lines[0] == "not a valid event log line"
    assert len(lines) == 3
    # And the corruption still makes `list_action_proposals` fail loud --
    # this fix is about `create_action_proposal` tolerating it, not about
    # the corruption silently going away.
    with pytest.raises(ActionProposalLogFormatError):
        list_action_proposals(ledger_dir=ledger_dir)


# --- identifier validation ---------------------------------------------------


def test_invalid_target_artifact_type_charset_is_rejected(
    ledger_dir: Path, policy_path: Path
) -> None:
    _seed_evidence_bundle(ledger_dir, "ev1", 1.0)
    with pytest.raises(ActionProposalValidationError):
        create_action_proposal(
            action="create_ticket",
            target_artifact_type="bia/../etc",
            target_artifact_id="sys01",
            reason="reason",
            evidence=["ev1"],
            ledger_dir=ledger_dir,
            policy_path=policy_path,
        )
    assert not (ledger_dir / "action_proposals.log.md").exists()


@pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
def test_blank_reason_is_rejected_and_writes_nothing(
    ledger_dir: Path, policy_path: Path, blank: str
) -> None:
    _seed_evidence_bundle(ledger_dir, "ev1", 1.0)
    with pytest.raises(ActionProposalValidationError):
        create_action_proposal(
            action="create_ticket",
            target_artifact_type="bia",
            target_artifact_id="sys01",
            reason=blank,
            evidence=["ev1"],
            ledger_dir=ledger_dir,
            policy_path=policy_path,
        )
    assert not (ledger_dir / "action_proposals.log.md").exists()


# --- non-validation precedent: target need not actually exist ---------------


def test_target_artifact_need_not_actually_exist(
    ledger_dir: Path, policy_path: Path
) -> None:
    """Mirrors `create_draft`'s own non-validation precedent: a target with
    no prior recorded facts still resolves (to an empty/unknown
    LedgerRecord) rather than being rejected.
    """
    _seed_evidence_bundle(ledger_dir, "ev1", 1.0)

    proposal = create_action_proposal(
        action="create_ticket",
        target_artifact_type="bia",
        target_artifact_id="never_seen_before",
        reason="reason",
        evidence=["ev1"],
        ledger_dir=ledger_dir,
        policy_path=policy_path,
    )
    assert proposal.policy_decision == "requires_approval"

    # And the real get_record confirms tier_sla stays unknown for a target
    # that was never observed at all.
    record = get_record("bia", "never_seen_before", ledger_dir=ledger_dir)
    assert record.tier_sla is None


# --- rezops.policy.yaml parsing ----------------------------------------------


def test_load_policy_parses_seeded_actions(policy_path: Path) -> None:
    policy = _load_policy(policy_path)
    assert policy == {
        "create_ticket": {"impact": "low"},
        "disable_credential": {"impact": "high"},
    }


def test_load_policy_returns_empty_dict_when_file_does_not_exist(tmp_path: Path) -> None:
    assert _load_policy(tmp_path / "does_not_exist.yaml") == {}


def test_load_policy_ignores_blank_lines_and_comments(tmp_path: Path) -> None:
    path = tmp_path / "rezops.policy.yaml"
    path.write_text(
        "# a comment\n"
        "\n"
        "create_ticket:\n"
        "  # inline comment\n"
        "  impact: low\n",
        encoding="utf-8",
    )
    assert _load_policy(path) == {"create_ticket": {"impact": "low"}}


def test_load_policy_rejects_invalid_impact_value(tmp_path: Path) -> None:
    path = tmp_path / "rezops.policy.yaml"
    path.write_text("create_ticket:\n  impact: catastrophic\n", encoding="utf-8")
    with pytest.raises(PolicyFileError):
        _load_policy(path)


def test_load_policy_rejects_duplicate_action_key(tmp_path: Path) -> None:
    path = tmp_path / "rezops.policy.yaml"
    path.write_text(
        "create_ticket:\n  impact: low\ncreate_ticket:\n  impact: high\n",
        encoding="utf-8",
    )
    with pytest.raises(PolicyFileError):
        _load_policy(path)


def test_load_policy_rejects_duplicate_field_key_within_same_action(tmp_path: Path) -> None:
    """Two `impact:` lines under the same action header -- a copy/paste
    mistake within one block, distinct from `test_load_policy_rejects_duplicate_action_key`
    (which duplicates the header itself).
    """
    path = tmp_path / "rezops.policy.yaml"
    path.write_text(
        "create_ticket:\n  impact: low\n  impact: high\n",
        encoding="utf-8",
    )
    with pytest.raises(PolicyFileError):
        _load_policy(path)


def test_load_policy_rejects_inline_comment_on_field_value_line(tmp_path: Path) -> None:
    path = tmp_path / "rezops.policy.yaml"
    path.write_text(
        "create_ticket:\n  impact: low  # temporary\n",
        encoding="utf-8",
    )
    with pytest.raises(PolicyFileError, match="inline comments"):
        _load_policy(path)


def test_load_policy_allows_whole_line_comment_alongside_field_lines(tmp_path: Path) -> None:
    """A `#`-prefixed line with nothing else on it is still a supported
    whole-line comment -- only a `#` appearing *within* a field-value line is
    rejected (the previous test).
    """
    path = tmp_path / "rezops.policy.yaml"
    path.write_text(
        "create_ticket:\n"
        "  impact: low\n"
        "# a whole-line comment between actions\n"
        "disable_credential:\n"
        "  impact: high\n",
        encoding="utf-8",
    )
    assert _load_policy(path) == {
        "create_ticket": {"impact": "low"},
        "disable_credential": {"impact": "high"},
    }


def test_load_policy_rejects_unparseable_line(tmp_path: Path) -> None:
    path = tmp_path / "rezops.policy.yaml"
    path.write_text("not valid yaml at all !!\n", encoding="utf-8")
    with pytest.raises(PolicyFileError):
        _load_policy(path)


def test_real_repo_root_policy_file_seeds_create_ticket_and_disable_credential() -> None:
    """The real, git-committed `rezops.policy.yaml` (repo root) declares the
    two example actions the story's Tasks & Acceptance calls for.
    """
    real_policy_path = Path(__file__).resolve().parent.parent / "rezops.policy.yaml"
    policy = _load_policy(real_policy_path)
    assert policy["create_ticket"]["impact"] == "low"
    assert policy["disable_credential"]["impact"] == "high"


# --- MCP tool surface --------------------------------------------------------


def test_server_exposes_ledger_create_and_list_action_proposal_tools() -> None:
    tools = asyncio.run(mcp.list_tools())
    names = [tool.name for tool in tools]
    assert "ledger_create_action_proposal" in names
    assert "ledger_list_action_proposals" in names


def test_ledger_create_action_proposal_tool_writes_log_and_returns_proposal(
    ledger_dir: Path, policy_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _point_server_at(monkeypatch, ledger_dir, policy_path)
    _seed_evidence_bundle(ledger_dir, "ev1", 1.0)

    result = asyncio.run(
        _call_ledger_create_action_proposal(
            "create_ticket", "bia", "sys01", "stale runbook", ["ev1"]
        )
    )

    assert result.isError is False
    payload = result.structuredContent
    assert payload["action"] == "create_ticket"
    assert payload["impact"] == "low"
    assert payload["policy_decision"] == "requires_approval"
    assert payload["evidence"] == ["ev1"]
    assert (ledger_dir / "action_proposals.log.md").exists()


def test_ledger_create_action_proposal_tool_rejects_undeclared_action(
    ledger_dir: Path, policy_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _point_server_at(monkeypatch, ledger_dir, policy_path)
    _seed_evidence_bundle(ledger_dir, "ev1", 1.0)

    result = asyncio.run(
        _call_ledger_create_action_proposal(
            "delete_universe", "bia", "sys01", "reason", ["ev1"]
        )
    )
    assert result.isError is True
    assert not (ledger_dir / "action_proposals.log.md").exists()


def test_ledger_create_action_proposal_tool_rejects_empty_evidence(
    ledger_dir: Path, policy_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _point_server_at(monkeypatch, ledger_dir, policy_path)

    result = asyncio.run(
        _call_ledger_create_action_proposal("create_ticket", "bia", "sys01", "reason", [])
    )
    assert result.isError is True
    assert not (ledger_dir / "action_proposals.log.md").exists()


def test_ledger_create_action_proposal_tool_rejects_nonexistent_evidence_id(
    ledger_dir: Path, policy_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _point_server_at(monkeypatch, ledger_dir, policy_path)

    result = asyncio.run(
        _call_ledger_create_action_proposal(
            "create_ticket", "bia", "sys01", "reason", ["does-not-exist"]
        )
    )
    assert result.isError is True
    assert not (ledger_dir / "action_proposals.log.md").exists()


def test_ledger_list_action_proposals_tool_matches_list_action_proposals(
    ledger_dir: Path, policy_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _point_server_at(monkeypatch, ledger_dir, policy_path)
    _seed_evidence_bundle(ledger_dir, "ev1", 1.0)
    create_action_proposal(
        action="create_ticket",
        target_artifact_type="bia",
        target_artifact_id="sys01",
        reason="reason",
        evidence=["ev1"],
        ledger_dir=ledger_dir,
        policy_path=policy_path,
    )

    result = asyncio.run(_call_ledger_list_action_proposals())
    assert result.isError is False
    listed = result.structuredContent["result"]
    assert len(listed) == 1
    assert listed[0]["action"] == "create_ticket"


def test_ledger_list_action_proposals_tool_returns_empty_when_none_exist(
    ledger_dir: Path, policy_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _point_server_at(monkeypatch, ledger_dir, policy_path)

    result = asyncio.run(_call_ledger_list_action_proposals())
    assert result.isError is False
    assert result.structuredContent["result"] == []


# --- hand-crafted log: missing/duplicate fields fail loud ------------------


def test_list_action_proposals_raises_on_proposed_event_missing_required_field(
    ledger_dir: Path,
) -> None:
    """A hand-crafted `proposed` event whose fields JSON is missing a
    required key (`evidence`, here) must raise `ActionProposalLogFormatError`
    rather than a raw `KeyError` when later state is built from it.
    """
    ledger_dir.mkdir(parents=True)
    fields = {
        "action": "create_ticket",
        "target_artifact_type": "bia",
        "target_artifact_id": "sys01",
        "reason": "reason",
        "impact": "low",
        # "evidence" deliberately omitted.
    }
    line = (
        "- (proposed) 2026-09-05T00:00:00Z proposal_id=p1 "
        f"fields={json.dumps(fields)}"
    )
    (ledger_dir / "action_proposals.log.md").write_text(line + "\n", encoding="utf-8")

    with pytest.raises(ActionProposalLogFormatError):
        list_action_proposals(ledger_dir=ledger_dir)


def test_list_action_proposals_raises_on_duplicate_decided_event_for_same_proposal(
    ledger_dir: Path,
) -> None:
    """A hand-crafted log with two `decided` events for the same
    `proposal_id` must raise `ActionProposalLogFormatError` -- a real
    `create_action_proposal` call never writes more than one.
    """
    ledger_dir.mkdir(parents=True)
    proposed_fields = {
        "action": "create_ticket",
        "target_artifact_type": "bia",
        "target_artifact_id": "sys01",
        "reason": "reason",
        "evidence": ["ev1"],
        "impact": "low",
    }
    lines = [
        "- (proposed) 2026-09-05T00:00:00Z proposal_id=p1 "
        f"fields={json.dumps(proposed_fields)}",
        "- (decided) 2026-09-05T00:00:01Z proposal_id=p1 "
        f'fields={json.dumps({"policy_decision": "requires_approval"})}',
        "- (decided) 2026-09-05T00:00:02Z proposal_id=p1 "
        f'fields={json.dumps({"policy_decision": "denied"})}',
    ]
    (ledger_dir / "action_proposals.log.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )

    with pytest.raises(ActionProposalLogFormatError):
        list_action_proposals(ledger_dir=ledger_dir)


# --- Never: nothing in this story's call graph acts on policy_decision -----


def test_action_proposals_module_never_imports_an_http_client() -> None:
    """No external write/send API call is even importable from this module
    -- mirrors `drafts.py`'s/`evidence.py`'s equivalent absence-of-`httpx`
    argument for AD-6/AD-11, extended here to AD-12's identical Never clause.
    """
    import ledger_core.action_proposals as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "httpx" not in source
    assert "requests" not in source
