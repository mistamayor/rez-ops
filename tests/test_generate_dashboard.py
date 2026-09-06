"""Unit tests for the executive dashboard generator (CAP-13, Story 20).

Every test writes to an isolated `ledger_data`-named directory under
pytest's `tmp_path`, and every `tiers_path` is an isolated file under
`tmp_path` too -- never the real, git-committed `ledger_data/` or
`rezops.tiers.yaml` at the repo root. Covers every I/O matrix row in the
story spec, plus the "every KPI tile must match a direct call to its
underlying function" success criterion (mirroring CAP-7's own
`test_ledger_core.py` "content matches a direct, live query" test pattern).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from html import escape as html_escape
from pathlib import Path

import pytest

from ledger_core.drafts import create_draft, list_drafts
from ledger_core.dr_readiness import TierReadiness, get_dr_readiness_summary
from ledger_core.log import append_event
from ledger_core.projection import (
    LOG_FORMAT_ERROR_MARKER,
    get_coverage_map,
    list_records,
)
from ops.generate_dashboard import (
    DEFAULT_OUTPUT_PATH,
    _render_rag_panel,
    generate_dashboard,
    main,
)
from shared.ledger_schema import RawFact


@pytest.fixture
def ledger_dir(tmp_path: Path) -> Path:
    return tmp_path / "ledger_data"


@pytest.fixture
def tiers_path(tmp_path: Path) -> Path:
    return tmp_path / "rezops.tiers.yaml"


@pytest.fixture
def output_path(tmp_path: Path) -> Path:
    return tmp_path / "out" / "dashboard.html"


def _write_tiers_file(tiers_path: Path, text: str) -> None:
    tiers_path.write_text(text, encoding="utf-8")


_SAMPLE_TIERS = (
    "tier.platinum.expiry_days: 30\n"
    "tier.gold.expiry_days: 90\n"
    "assign.bia/payments-checkout: platinum\n"
    "assign.raci/payments-checkout: gold\n"
)


def _seed_mixed_ledger_state(ledger_dir: Path) -> None:
    # Orphan-risk: known (non-empty fields) but no ownership field resolved.
    append_event(
        RawFact(
            artifact_type="bia",
            artifact_id="payments-checkout",
            source="git:local",
            fields={"some_field": "some_value"},
        ),
        ledger_dir=ledger_dir,
    )
    # Owned, non-orphan-risk.
    append_event(
        RawFact(
            artifact_type="raci",
            artifact_id="payments-checkout",
            source="cmdb:snow",
            fields={"support_group": "platform-team"},
        ),
        ledger_dir=ledger_dir,
    )
    # Unknown confidence: a genuinely distinct artifact_id from the two
    # above -- an event was appended for it (so it's discoverable via
    # list_records, whose per-artifact records only come from folded-in
    # events) but with an empty `fields` payload, so no field was ever
    # actually observed and confidence stays "unknown" (never conflated
    # with "payments-checkout" above, which does carry a real field and
    # resolves "agent-verified").
    append_event(
        RawFact(
            artifact_type="bia",
            artifact_id="checkout-unknown",
            source="git:local",
            fields={},
        ),
        ledger_dir=ledger_dir,
    )
    # Pending draft, for the Pending Drafts KPI tile -- independent of the
    # confidence scenario above.
    create_draft(
        artifact_type="bia",
        artifact_id="payments-checkout",
        draft_type="owner_reconfirmation",
        subject="subject",
        body="body",
        ledger_dir=ledger_dir,
    )


# --- I/O matrix row: populated ledger ---------------------------------------


def test_populated_ledger_kpi_tiles_match_direct_underlying_calls(
    ledger_dir: Path, tiers_path: Path, output_path: Path
) -> None:
    _write_tiers_file(tiers_path, _SAMPLE_TIERS)
    _seed_mixed_ledger_state(ledger_dir)

    generate_dashboard(
        ledger_dir=ledger_dir, tiers_path=tiers_path, output_path=output_path
    )
    html = output_path.read_text(encoding="utf-8")

    all_records = list_records(ledger_dir=ledger_dir, tiers_path=tiers_path)
    orphan_risk_records = list_records(
        orphan_risk=True, ledger_dir=ledger_dir, tiers_path=tiers_path
    )
    unknown_confidence_records = list_records(
        confidence="unknown", ledger_dir=ledger_dir, tiers_path=tiers_path
    )
    drafts = list_drafts(ledger_dir=ledger_dir)
    readiness = get_dr_readiness_summary(ledger_dir=ledger_dir, tiers_path=tiers_path)
    coverage = get_coverage_map(ledger_dir=ledger_dir)

    tiers_at_risk = sum(
        1 for tier in readiness.tiers if tier.status in ("high", "medium")
    )
    data_quality_issues = sum(
        1 for tally in coverage.values() if LOG_FORMAT_ERROR_MARKER in tally
    )

    # Sanity: at least one non-zero value in this seeded scenario, so the
    # match assertions below aren't vacuously true against all-zero tiles.
    assert len(orphan_risk_records) > 0
    assert len(unknown_confidence_records) > 0

    assert f'<div class="kpi-value">{len(all_records)}</div>' in html
    assert f'<div class="kpi-value">{len(orphan_risk_records)}</div>' in html
    assert f'<div class="kpi-value">{len(unknown_confidence_records)}</div>' in html
    assert f'<div class="kpi-value">{len(drafts)}</div>' in html
    assert f'<div class="kpi-value">{tiers_at_risk}</div>' in html
    assert f'<div class="kpi-value">{data_quality_issues}</div>' in html

    assert "Artifacts Tracked" in html
    assert "Orphan-Risk" in html
    assert "Unknown Confidence" in html
    assert "Pending Drafts" in html
    assert "Tiers At Risk" in html
    assert "Data-Quality Issues" in html


def test_unknown_confidence_kpi_is_tied_to_its_distinctly_seeded_artifact(
    ledger_dir: Path, tiers_path: Path, output_path: Path
) -> None:
    """`_seed_mixed_ledger_state` seeds exactly one genuinely never-observed
    artifact (`bia/checkout-unknown`: an event was appended for it, but with
    an empty `fields` payload, so no field was ever actually recorded) --
    distinct from `bia/payments-checkout` (has a real field, resolves
    "agent-verified") and `raci/payments-checkout` (owned, also
    "agent-verified"). The Unknown Confidence tile must reflect exactly
    that one artifact, not a count that happens to also be produced by
    unrelated seeded data.
    """
    _write_tiers_file(tiers_path, _SAMPLE_TIERS)
    _seed_mixed_ledger_state(ledger_dir)

    generate_dashboard(
        ledger_dir=ledger_dir, tiers_path=tiers_path, output_path=output_path
    )
    html = output_path.read_text(encoding="utf-8")

    unknown_confidence_records = list_records(
        confidence="unknown", ledger_dir=ledger_dir, tiers_path=tiers_path
    )
    assert [
        (record.artifact_type, record.artifact_id)
        for record in unknown_confidence_records
    ] == [("bia", "checkout-unknown")]
    assert len(unknown_confidence_records) == 1

    assert (
        '<div class="kpi-tile"><div class="kpi-value">1</div>'
        '<div class="kpi-label">Unknown Confidence</div></div>'
    ) in html


def test_populated_ledger_rag_panel_shows_one_row_per_declared_tier(
    ledger_dir: Path, tiers_path: Path, output_path: Path
) -> None:
    _write_tiers_file(tiers_path, _SAMPLE_TIERS)
    _seed_mixed_ledger_state(ledger_dir)

    generate_dashboard(
        ledger_dir=ledger_dir, tiers_path=tiers_path, output_path=output_path
    )
    html = output_path.read_text(encoding="utf-8")

    readiness = get_dr_readiness_summary(ledger_dir=ledger_dir, tiers_path=tiers_path)
    assert len(readiness.tiers) == 2  # platinum, gold

    for tier in readiness.tiers:
        assert tier.name in html
        detail = (
            f"{tier.risk_counts['high']} high · "
            f"{tier.risk_counts['medium']} medium · "
            f"{tier.risk_counts['low']} low · "
            f"{tier.risk_counts['unknown']} unknown"
        )
        assert detail in html


def test_rag_pill_labels_match_tier_status(
    ledger_dir: Path, tiers_path: Path, output_path: Path
) -> None:
    # No facts ever recorded for either assigned artifact -> both tiers'
    # artifacts resolve confidence="unknown" -> risk="unknown".
    _write_tiers_file(tiers_path, _SAMPLE_TIERS)

    generate_dashboard(
        ledger_dir=ledger_dir, tiers_path=tiers_path, output_path=output_path
    )
    html = output_path.read_text(encoding="utf-8")

    assert '<span class="rag-pill rag-pill-unknown">Unknown</span>' in html
    assert html.count('<span class="rag-pill rag-pill-unknown">Unknown</span>') == 2


def _rag_row_pill(html: str, tier_name: str) -> tuple[str, str]:
    """Return `(pill_css_class, pill_label)` from the RAG row for `tier_name`.

    Binds the pill to *that tier's own row* (not just "this pill class
    appears somewhere on the page") -- the same tier/row a mutation that
    swapped the "medium"/"high" pill-style mapping would get wrong.
    """
    match = re.search(
        rf'<td class="rag-tier-name">{re.escape(tier_name)}</td>'
        r'<td><span class="rag-pill (rag-pill-[a-z]+)">([^<]+)</span></td>',
        html,
    )
    assert match, f"no RAG row found for tier {tier_name!r} in html"
    return match.group(1), match.group(2)


def test_rag_pill_medium_high_and_low_risk_are_correctly_mapped(
    ledger_dir: Path, tiers_path: Path, output_path: Path
) -> None:
    """Every prior test seeds artifacts with `append_event`'s default
    (current) timestamp, so every tier in every other test resolves
    risk="low" or "unknown" -- "medium" and "high" (and the "low" pill
    itself) are otherwise never actually exercised. Seeds three tiers, each
    with one artifact at an explicit, stale `timestamp` chosen relative to
    that tier's own `expiry_days` to land squarely in one risk bucket, and
    asserts the exact pill class/label for each tier's own row.
    """
    _write_tiers_file(
        tiers_path,
        "tier.platinum.expiry_days: 30\n"
        "tier.gold.expiry_days: 20\n"
        "tier.silver.expiry_days: 100\n"
        "assign.bia/platinum-app: platinum\n"
        "assign.bia/gold-app: gold\n"
        "assign.bia/silver-app: silver\n",
    )
    now = datetime.now(timezone.utc)

    # High risk: 40 days since last verified, well past platinum's 30-day
    # expiry window.
    append_event(
        RawFact(
            artifact_type="bia",
            artifact_id="platinum-app",
            source="git:local",
            fields={"support_group": "platform-team"},
        ),
        ledger_dir=ledger_dir,
        timestamp=now - timedelta(days=40),
    )
    # Medium risk: 18 days since last verified, past 0.75 * 20 = 15 days but
    # not past the full 20-day window.
    append_event(
        RawFact(
            artifact_type="bia",
            artifact_id="gold-app",
            source="git:local",
            fields={"support_group": "platform-team"},
        ),
        ledger_dir=ledger_dir,
        timestamp=now - timedelta(days=18),
    )
    # Low risk: 1 day since last verified, well within silver's 100-day
    # window.
    append_event(
        RawFact(
            artifact_type="bia",
            artifact_id="silver-app",
            source="git:local",
            fields={"support_group": "platform-team"},
        ),
        ledger_dir=ledger_dir,
        timestamp=now - timedelta(days=1),
    )

    generate_dashboard(
        ledger_dir=ledger_dir, tiers_path=tiers_path, output_path=output_path
    )
    html = output_path.read_text(encoding="utf-8")

    assert _rag_row_pill(html, "platinum") == ("rag-pill-critical", "Critical")
    assert _rag_row_pill(html, "gold") == ("rag-pill-warn", "At Risk")
    assert _rag_row_pill(html, "silver") == ("rag-pill-good", "Good")


def test_rag_panel_escapes_unsafe_tier_name_characters() -> None:
    """The `html.escape` calls in `_render_rag_panel` protect against unsafe
    tier-name characters -- exercised directly against `_render_rag_panel`,
    since `rezops.tiers.yaml`'s own parser (`_TIER_DECLARATION_RE`)
    restricts a declared tier name to a safe identifier charset, so this
    protection is never reachable via the full `generate_dashboard`
    pipeline. Every other test's tier names ("platinum", "gold", ...) are
    all clean, so a regression in the escaping itself would otherwise go
    uncaught.
    """
    unsafe_name = '<script>alert("x")</script>&'
    unsafe_tier = TierReadiness(
        name=unsafe_name,
        artifact_count=1,
        risk_counts={"high": 0, "medium": 0, "low": 1, "unknown": 0},
        status="low",
    )

    html = _render_rag_panel((unsafe_tier,))

    assert unsafe_name not in html
    assert html_escape(unsafe_name) in html


# --- I/O matrix row: empty ledger (ledger_data/ doesn't exist) --------------


def test_empty_ledger_all_list_based_tiles_show_zero(
    ledger_dir: Path, tiers_path: Path, output_path: Path
) -> None:
    assert not ledger_dir.exists()
    _write_tiers_file(tiers_path, _SAMPLE_TIERS)

    result_path = generate_dashboard(
        ledger_dir=ledger_dir, tiers_path=tiers_path, output_path=output_path
    )

    assert result_path == output_path
    html = output_path.read_text(encoding="utf-8")

    # With no facts recorded at all, every declared tier's assigned artifacts
    # resolve confidence="unknown" -> risk="unknown" (never "high"/"medium"),
    # so all six tiles -- including Tiers At Risk -- show 0.
    assert html.count('<div class="kpi-value">0</div>') == 6

    # RAG panel still shows one row per *declared* tier, each status=unknown,
    # independent of whether any facts exist.
    assert "platinum" in html
    assert "gold" in html
    assert html.count('<span class="rag-pill rag-pill-unknown">Unknown</span>') == 2

    # A pure read (no facts ingested) never creates ledger_dir as a side
    # effect of generating the dashboard.
    assert not ledger_dir.exists()


def test_empty_ledger_no_tiers_declared_still_writes_valid_file(
    ledger_dir: Path, tiers_path: Path, output_path: Path
) -> None:
    assert not ledger_dir.exists()
    assert not tiers_path.exists()

    generate_dashboard(
        ledger_dir=ledger_dir, tiers_path=tiers_path, output_path=output_path
    )
    html = output_path.read_text(encoding="utf-8")

    assert html.count('<div class="kpi-value">0</div>') == 6
    assert "No tiers declared" in html


# --- I/O matrix row: corrupted artifact-type log ----------------------------


def test_corrupted_log_surfaces_in_data_quality_issues_tile(
    ledger_dir: Path, tiers_path: Path, output_path: Path
) -> None:
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "broken_type.log.md").write_text(
        "this is not a valid event log line at all\n", encoding="utf-8"
    )
    _write_tiers_file(tiers_path, _SAMPLE_TIERS)

    generate_dashboard(
        ledger_dir=ledger_dir, tiers_path=tiers_path, output_path=output_path
    )
    html = output_path.read_text(encoding="utf-8")

    coverage = get_coverage_map(ledger_dir=ledger_dir)
    data_quality_issues = sum(
        1 for tally in coverage.values() if LOG_FORMAT_ERROR_MARKER in tally
    )
    assert data_quality_issues == 1
    assert f'<div class="kpi-value">{data_quality_issues}</div>' in html

    # That type's records still degrade gracefully elsewhere (existing AD-8
    # behavior, unchanged): the corrupted type still shows up in
    # Artifacts Tracked via list_records's sentinel record, never crashes.
    all_records = list_records(ledger_dir=ledger_dir, tiers_path=tiers_path)
    assert f'<div class="kpi-value">{len(all_records)}</div>' in html


# --- I/O matrix row: missing rezops.tiers.yaml ------------------------------


def test_missing_tiers_file_rag_panel_empty_kpi_tiles_unaffected(
    ledger_dir: Path, tiers_path: Path, output_path: Path
) -> None:
    assert not tiers_path.exists()
    _seed_mixed_ledger_state(ledger_dir)

    generate_dashboard(
        ledger_dir=ledger_dir, tiers_path=tiers_path, output_path=output_path
    )
    html = output_path.read_text(encoding="utf-8")

    all_records = list_records(ledger_dir=ledger_dir, tiers_path=tiers_path)
    assert f'<div class="kpi-value">{len(all_records)}</div>' in html
    assert len(all_records) > 0

    assert "No tiers declared" in html
    assert '<span class="rag-pill' not in html


# --- I/O matrix row: --output given a path whose parent doesn't exist ------


def test_output_path_parent_directories_are_created(
    ledger_dir: Path, tiers_path: Path, tmp_path: Path
) -> None:
    nested_output = tmp_path / "nested" / "dir" / "dashboard.html"
    assert not nested_output.parent.exists()

    result_path = generate_dashboard(
        ledger_dir=ledger_dir, tiers_path=tiers_path, output_path=nested_output
    )

    assert result_path == nested_output
    assert nested_output.exists()


# --- generate_dashboard: default parameters ---------------------------------


def test_default_output_path_constant() -> None:
    assert DEFAULT_OUTPUT_PATH == Path("ledger_data") / "dashboard.html"


# --- Every unwired view carries its banner, no fabricated numbers ----------


def test_unwired_views_carry_banner_and_no_fabricated_numbers(
    ledger_dir: Path, tiers_path: Path, output_path: Path
) -> None:
    _write_tiers_file(tiers_path, _SAMPLE_TIERS)
    _seed_mixed_ledger_state(ledger_dir)

    generate_dashboard(
        ledger_dir=ledger_dir, tiers_path=tiers_path, output_path=output_path
    )
    html = output_path.read_text(encoding="utf-8")

    assert html.count("Not yet wired to real data") == 4  # one per unwired view
    assert "Dependency Map" in html
    assert "Ask Rez Ops" in html
    assert "Upcoming DR Tests" in html
    assert "Recent DR Tests" in html


# --- KPI tile label/value binding --------------------------------------------


def _kpi_tile_value(html: str, label: str) -> str:
    """Return the numeric value from the KPI tile whose label is `label`.

    Locates the value *inside that same tile's own block* -- not just
    "this value string appears somewhere on the page" -- so a regression
    that swaps two of `_render_kpi_tiles`'s keyword arguments (e.g.
    `orphan_risk` <-> `pending_drafts`) produces a mismatch here even though
    every individual count and label string still independently appears
    somewhere in the page.
    """
    match = re.search(
        r'<div class="kpi-tile"><div class="kpi-value">(\d+)</div>'
        rf'<div class="kpi-label">{re.escape(label)}</div></div>',
        html,
    )
    assert match, f"no KPI tile found for label {label!r} in html"
    return match.group(1)


def test_kpi_tile_values_are_bound_to_their_own_label(
    ledger_dir: Path, tiers_path: Path, output_path: Path
) -> None:
    # Seeded so all six KPI values are pairwise distinct (7, 5, 3, 4, 0, 2)
    # -- guarantees a swap between *any* two tiles is detectable, not just
    # the specific orphan_risk<->pending_drafts swap this test was written
    # against.
    #
    # Orphan-risk (3 real + 2 always-included corrupted-log sentinels = 5).
    append_event(
        RawFact(artifact_type="bia", artifact_id="orphan-1", source="git:local",
                fields={"some_field": "a"}),
        ledger_dir=ledger_dir,
    )
    append_event(
        RawFact(artifact_type="bia", artifact_id="orphan-2", source="git:local",
                fields={"some_field": "b"}),
        ledger_dir=ledger_dir,
    )
    append_event(
        RawFact(artifact_type="bia", artifact_id="orphan-3", source="git:local",
                fields={"some_field": "c"}),
        ledger_dir=ledger_dir,
    )
    # Owned, non-orphan, non-unknown.
    append_event(
        RawFact(artifact_type="bia", artifact_id="owned-1", source="cmdb:snow",
                fields={"support_group": "platform-team"}),
        ledger_dir=ledger_dir,
    )
    # Unknown confidence (1 real + 2 always-included sentinels = 3).
    append_event(
        RawFact(artifact_type="bia", artifact_id="unknown-1", source="git:local",
                fields={}),
        ledger_dir=ledger_dir,
    )
    # Two corrupted artifact-type logs -> Data-Quality Issues = 2, and each
    # contributes one always-included sentinel record to every list_records
    # call regardless of filter (see projection.list_records's docstring).
    (ledger_dir / "broken_a.log.md").write_text(
        "not a valid event log line\n", encoding="utf-8"
    )
    (ledger_dir / "broken_b.log.md").write_text(
        "also not a valid event log line\n", encoding="utf-8"
    )
    # Pending drafts = 4, independent of the confidence/orphan-risk scenario.
    for i in range(4):
        create_draft(
            artifact_type="bia",
            artifact_id="owned-1",
            draft_type="owner_reconfirmation",
            subject=f"subject-{i}",
            body="body",
            ledger_dir=ledger_dir,
        )
    # No tiers.yaml at all -> Tiers At Risk = 0.
    assert not tiers_path.exists()

    generate_dashboard(
        ledger_dir=ledger_dir, tiers_path=tiers_path, output_path=output_path
    )
    html = output_path.read_text(encoding="utf-8")

    all_records = list_records(ledger_dir=ledger_dir, tiers_path=tiers_path)
    orphan_risk_records = list_records(
        orphan_risk=True, ledger_dir=ledger_dir, tiers_path=tiers_path
    )
    unknown_confidence_records = list_records(
        confidence="unknown", ledger_dir=ledger_dir, tiers_path=tiers_path
    )
    drafts = list_drafts(ledger_dir=ledger_dir)
    readiness = get_dr_readiness_summary(ledger_dir=ledger_dir, tiers_path=tiers_path)
    coverage = get_coverage_map(ledger_dir=ledger_dir)
    tiers_at_risk = sum(
        1 for tier in readiness.tiers if tier.status in ("high", "medium")
    )
    data_quality_issues = sum(
        1 for tally in coverage.values() if LOG_FORMAT_ERROR_MARKER in tally
    )

    expected = {
        "Artifacts Tracked": len(all_records),
        "Orphan-Risk": len(orphan_risk_records),
        "Unknown Confidence": len(unknown_confidence_records),
        "Pending Drafts": len(drafts),
        "Tiers At Risk": tiers_at_risk,
        "Data-Quality Issues": data_quality_issues,
    }
    # Sanity: this fixture must actually produce six pairwise-distinct
    # values, or the per-tile assertions below couldn't detect a swap
    # between whichever two tiles happened to tie.
    assert len(set(expected.values())) == len(expected) == 6

    for label, count in expected.items():
        assert _kpi_tile_value(html, label) == str(count)


# --- CLI: python -m ops.generate_dashboard ----------------------------------


def test_cli_main_prints_output_path_and_exits_zero(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    output_path = tmp_path / "cli_dashboard.html"

    exit_code = main(["--output", str(output_path)])

    assert exit_code == 0
    assert output_path.exists()
    captured = capsys.readouterr()
    assert captured.out.strip() == str(output_path)
    assert captured.err == ""


def test_cli_main_default_output_path(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Run from a fresh, empty cwd with no ledger_data/ at all -- must exit 0,
    # write a valid HTML file, every KPI tile shows 0, never raises.
    monkeypatch.chdir(tmp_path)

    exit_code = main([])

    assert exit_code == 0
    default_path = tmp_path / DEFAULT_OUTPUT_PATH
    assert default_path.exists()
    html = default_path.read_text(encoding="utf-8")
    assert html.count('<div class="kpi-value">0</div>') == 6
    captured = capsys.readouterr()
    assert captured.out.strip() == str(default_path.resolve())


def test_cli_main_write_failure_prints_one_error_line_and_returns_nonzero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    # Make output_path's parent an unwritable location by pointing it at a
    # path whose parent already exists as a regular file (mkdir(parents=True)
    # will raise FileExistsError/NotADirectoryError there), simulating a
    # write failure without relying on OS-specific permission semantics.
    blocking_file = tmp_path / "blocking_file"
    blocking_file.write_text("not a directory", encoding="utf-8")
    bad_output = blocking_file / "dashboard.html"

    exit_code = main(["--output", str(bad_output)])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    error_lines = captured.err.strip().splitlines()
    assert len(error_lines) == 1
    assert "failed to generate dashboard" in error_lines[0]


def test_cli_main_malformed_tiers_file_prints_error_and_returns_nonzero(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A malformed (not just missing) `rezops.tiers.yaml` -- here, a
    duplicate tier declaration, matching Story 17/18's own
    `TiersFileError`-triggering fixtures -- makes `get_dr_readiness_summary`'s
    initial `load_tiers` call raise. `main()` must still catch it via its
    generic-Exception safety net, print exactly one error line to stderr,
    and return 1 -- never a raw traceback.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "rezops.tiers.yaml").write_text(
        "tier.platinum.expiry_days: 30\n"
        "tier.platinum.expiry_days: 60\n",  # duplicate declaration
        encoding="utf-8",
    )
    output_path = tmp_path / "dashboard.html"

    exit_code = main(["--output", str(output_path)])

    assert exit_code == 1
    assert not output_path.exists()
    captured = capsys.readouterr()
    assert captured.out == ""
    error_lines = captured.err.strip().splitlines()
    assert len(error_lines) == 1
    assert "failed to generate dashboard" in error_lines[0]
    assert "Traceback" not in captured.err
