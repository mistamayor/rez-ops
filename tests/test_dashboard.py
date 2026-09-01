"""Unit tests for the local read-only dashboard generator (`ops/generate_dashboard.py`).

Exercises `generate_dashboard` against a real, tmp_path-isolated ledger --
never mocked -- since it's pure presentation over already-tested read
functions (`get_coverage_map`, `get_briefing`); the thing worth verifying
here is the rendering, not the underlying computation.
"""

from __future__ import annotations

from pathlib import Path

from ledger_core.drafts import create_draft
from ledger_core.log import append_event
from ops.generate_dashboard import generate_dashboard
from shared.ledger_schema import RawFact


def test_empty_ledger_renders_without_error(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "ledger_data"
    output_path = tmp_path / "dashboard.html"

    result_path = generate_dashboard(ledger_dir=ledger_dir, output_path=output_path)

    assert result_path == output_path
    html_text = output_path.read_text(encoding="utf-8")
    assert "<title>Rez Ops Dashboard</title>" in html_text
    assert "No artifacts ingested yet." in html_text
    assert "No orphan-risk artifacts." in html_text
    assert "No unknown-confidence artifacts." in html_text
    assert "No pending drafts." in html_text
    assert "No corrupted logs detected." in html_text


def test_orphan_risk_artifact_appears_in_orphan_section(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "ledger_data"
    append_event(
        RawFact(
            artifact_type="runbooks",
            artifact_id="payments",
            source="git:abc123",
            fields={"author": "Someone"},
        ),
        ledger_dir=ledger_dir,
    )
    output_path = tmp_path / "dashboard.html"

    generate_dashboard(ledger_dir=ledger_dir, output_path=output_path)

    html_text = output_path.read_text(encoding="utf-8")
    assert "runbooks" in html_text
    assert "payments" in html_text
    # The orphan-risk badge count reflects exactly one artifact.
    assert '<h2>Orphan-risk <span class="badge">1</span></h2>' in html_text


def test_owned_artifact_is_excluded_from_orphan_risk(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "ledger_data"
    append_event(
        RawFact(
            artifact_type="runbooks",
            artifact_id="checkout",
            source="cmdb:x1",
            fields={"support_group": "Platform Team"},
        ),
        ledger_dir=ledger_dir,
    )
    output_path = tmp_path / "dashboard.html"

    generate_dashboard(ledger_dir=ledger_dir, output_path=output_path)

    html_text = output_path.read_text(encoding="utf-8")
    assert '<h2>Orphan-risk <span class="badge">0</span></h2>' in html_text


def test_pending_draft_appears_with_unresolved_recipient(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "ledger_data"
    create_draft(
        artifact_type="runbooks",
        artifact_id="payments",
        draft_type="nudge",
        subject="Please review",
        body="It's stale.",
        ledger_dir=ledger_dir,
    )
    output_path = tmp_path / "dashboard.html"

    generate_dashboard(ledger_dir=ledger_dir, output_path=output_path)

    html_text = output_path.read_text(encoding="utf-8")
    assert '<h2>Pending drafts <span class="badge">1</span></h2>' in html_text
    assert "Please review" in html_text
    assert "— unresolved —" in html_text


def test_corrupted_log_surfaces_in_coverage_and_data_quality_sections(
    tmp_path: Path,
) -> None:
    ledger_dir = tmp_path / "ledger_data"
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "broken_type.log.md").write_text(
        "not a valid event log line\n", encoding="utf-8"
    )
    output_path = tmp_path / "dashboard.html"

    generate_dashboard(ledger_dir=ledger_dir, output_path=output_path)

    html_text = output_path.read_text(encoding="utf-8")
    assert "broken_type" in html_text
    assert "corrupted log" in html_text
    assert '<h2>Data quality issues <span class="badge">1</span></h2>' in html_text


def test_dynamic_content_is_html_escaped(tmp_path: Path) -> None:
    # The record table renders only computed LedgerRecord state (type, id,
    # confidence, owner) -- never raw `fields` -- so exercise escaping via
    # a draft's subject/artifact_id, which are the caller-authored strings
    # that actually reach the page.
    ledger_dir = tmp_path / "ledger_data"
    create_draft(
        artifact_type="runbooks",
        artifact_id="payments",
        draft_type="<b>nudge</b>",
        subject="<img src=x onerror=alert(2)>",
        body="body text",
        ledger_dir=ledger_dir,
    )
    output_path = tmp_path / "dashboard.html"

    generate_dashboard(ledger_dir=ledger_dir, output_path=output_path)

    html_text = output_path.read_text(encoding="utf-8")
    assert "<img src=x onerror=alert(2)>" not in html_text
    assert "&lt;img" in html_text
    assert "<b>nudge</b>" not in html_text
    assert "&lt;b&gt;nudge&lt;/b&gt;" in html_text


def test_output_path_is_configurable_and_ledger_data_is_never_written_to(
    tmp_path: Path,
) -> None:
    ledger_dir = tmp_path / "ledger_data"
    output_path = tmp_path / "snapshots" / "custom-name.html"

    result_path = generate_dashboard(ledger_dir=ledger_dir, output_path=output_path)

    assert result_path == output_path
    assert output_path.exists()
    # The dashboard is never written inside ledger_data/ itself -- ledger-core
    # remains the only writer to that directory (AD-3).
    assert not (ledger_dir / "custom-name.html").exists()
    assert not any(ledger_dir.glob("*.html")) if ledger_dir.exists() else True
