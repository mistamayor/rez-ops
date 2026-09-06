"""Executive dashboard generator (CAP-13, Story 20): pure presentation, no new reads.

`generate_dashboard` composes exactly four existing read functions --
`ledger_core.dr_readiness.get_dr_readiness_summary`,
`ledger_core.projection.list_records` (once unfiltered, once
`orphan_risk=True`, once `confidence="unknown"`), `ledger_core.drafts.list_drafts`,
and `ledger_core.projection.get_coverage_map` -- into a single self-contained
static HTML snapshot written to disk. Nothing here computes risk, confidence,
or coverage a second way: every KPI tile and RAG-panel value is exactly what
one of those four functions already returns, at the same point in time
(CAP-13's own "must match a live query" success criterion is satisfied by
construction, mirroring `briefing.py`'s identical discipline for CAP-7).

Only the Home view (six KPI tiles + the RAG status panel) is wired to real
data this pass. Every other view from the validated prototype (Dependency
Map, "Ask Rez Ops", Upcoming/Recent DR Tests) stays in the generated page's
markup and nav, each carrying a permanent, visible "Not yet wired to real
data" banner -- never silently removed, never populated with the prototype's
placeholder numbers presented as real.

HTML/CSS/JS is hand-rolled Python string composition: a static template with
three dynamic fragments spliced in via HTML-comment markers and plain
`.replace()` -- no `.format()`-based templating (its `{`/`}` escaping would
fight the CSS's own braces), no new dependency.

No hosted server, no auto-refresh, no live query from the HTML page itself
(CAP-13's non-goal) -- a fresh run of this script is the only way to update
the generated file.
"""

from __future__ import annotations

import argparse
import html
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from ledger_core.dr_readiness import TierReadiness, get_dr_readiness_summary
from ledger_core.drafts import list_drafts
from ledger_core.log import DEFAULT_LEDGER_DATA_DIR
from ledger_core.projection import (
    DEFAULT_TIERS_PATH,
    LOG_FORMAT_ERROR_MARKER,
    get_coverage_map,
    list_records,
)

#: Default output location for the generated snapshot -- a sibling of every
#: other `ledger_data/` artifact this project writes, even though the
#: dashboard itself is never read back programmatically (mirrors
#: `run_scheduled_briefing.DEFAULT_OPS_LOG_PATH`'s "lives under ledger_data/
#: but isn't one of the artifact-type event logs" pattern).
DEFAULT_OUTPUT_PATH = Path("ledger_data") / "dashboard.html"

#: Matches every other `generated_at` field's format in this project
#: (`ledger_core.log.TIMESTAMP_FORMAT`, `briefing.py`, `dr_readiness.py`).
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

#: Tier `status` -> (CSS class, pill label). `"unknown"` is a new pill style
#: the prototype never needed -- see the story's Design Notes -- because
#: `get_dr_readiness_summary` has a fourth status the prototype's own
#: confidence-dot device never modeled.
_STATUS_PILLS: dict[str, tuple[str, str]] = {
    "low": ("rag-pill-good", "Good"),
    "medium": ("rag-pill-warn", "At Risk"),
    "high": ("rag-pill-critical", "Critical"),
    "unknown": ("rag-pill-unknown", "Unknown"),
}

#: Fixed display order for a tier's risk-count breakdown (e.g. "2 high · 1
#: medium · 0 low · 1 unknown") -- matches `dr_readiness._RISK_LEVELS`'s own
#: declared order, not an independently invented one.
_RISK_LEVEL_DISPLAY_ORDER = ("high", "medium", "low", "unknown")

_NOT_WIRED_BANNER = (
    '<div class="not-wired-banner">'
    '<span class="not-wired-tag">Not yet wired to real data</span>'
    "<p>This view preserves the validated prototype's layout only -- no "
    "ledger-core query backs it yet. A future story may wire it up.</p>"
    "</div>"
)


def _render_kpi_tiles(
    *,
    artifacts_tracked: int,
    orphan_risk: int,
    unknown_confidence: int,
    pending_drafts: int,
    tiers_at_risk: int,
    data_quality_issues: int,
) -> str:
    """Render the six KPI tiles, each a plain count -- no computation here."""
    tiles = (
        ("Artifacts Tracked", artifacts_tracked),
        ("Orphan-Risk", orphan_risk),
        ("Unknown Confidence", unknown_confidence),
        ("Pending Drafts", pending_drafts),
        ("Tiers At Risk", tiers_at_risk),
        ("Data-Quality Issues", data_quality_issues),
    )
    return "\n".join(
        '<div class="kpi-tile">'
        f'<div class="kpi-value">{count}</div>'
        f'<div class="kpi-label">{html.escape(label)}</div>'
        "</div>"
        for label, count in tiles
    )


def _render_rag_panel(tiers: tuple[TierReadiness, ...]) -> str:
    """Render one row per declared tier: name, status pill, risk breakdown.

    Empty (`tiers=()`) when `rezops.tiers.yaml` doesn't exist or declares no
    tiers -- `get_dr_readiness_summary` already returns `()` for that case,
    never raises.
    """
    if not tiers:
        return (
            '<p class="rag-empty">No tiers declared in '
            "<code>rezops.tiers.yaml</code>.</p>"
        )

    rows = []
    for tier in tiers:
        pill_class, pill_label = _STATUS_PILLS.get(tier.status, ("rag-pill-unknown", "Unknown"))
        detail = " · ".join(
            f"{tier.risk_counts.get(level, 0)} {level}"
            for level in _RISK_LEVEL_DISPLAY_ORDER
        )
        rows.append(
            "<tr>"
            f'<td class="rag-tier-name">{html.escape(tier.name)}</td>'
            f'<td><span class="rag-pill {pill_class}">{html.escape(pill_label)}</span></td>'
            f'<td class="rag-detail">{html.escape(detail)}</td>'
            "</tr>"
        )

    return (
        '<table class="rag-table">'
        "<thead><tr><th>Tier</th><th>Status</th><th>Risk breakdown</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )


def generate_dashboard(
    *,
    ledger_dir: Path = DEFAULT_LEDGER_DATA_DIR,
    tiers_path: Path = DEFAULT_TIERS_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
) -> Path:
    """Compose the executive dashboard HTML and write it to `output_path`.

    Calls exactly four existing read functions -- `get_dr_readiness_summary`,
    `list_records` (unfiltered, `orphan_risk=True`, `confidence="unknown"`),
    `list_drafts`, `get_coverage_map` -- and performs no other computation.
    Every KPI tile is a plain `len(...)`/count over one of those results;
    every RAG row is a direct field of one `TierReadiness`. Never raises for
    a missing `ledger_dir` or `tiers_path`: each underlying read function
    already tolerates that by returning an empty result (see their own
    docstrings), so every count degrades to `0` and the RAG panel to empty
    rather than this function crashing.

    Creates `output_path`'s parent directories if they don't exist (mirrors
    `ledger_core.log.append_event`'s own `_ensure_ledger_dir` behavior), then
    writes the composed HTML there and returns that path. No write of any
    kind beyond that one file.
    """
    readiness = get_dr_readiness_summary(ledger_dir=ledger_dir, tiers_path=tiers_path)
    all_records = list_records(ledger_dir=ledger_dir, tiers_path=tiers_path)
    orphan_risk_records = list_records(
        orphan_risk=True, ledger_dir=ledger_dir, tiers_path=tiers_path
    )
    unknown_confidence_records = list_records(
        confidence="unknown", ledger_dir=ledger_dir, tiers_path=tiers_path
    )
    drafts = list_drafts(ledger_dir=ledger_dir)
    coverage = get_coverage_map(ledger_dir=ledger_dir)

    tiles_html = _render_kpi_tiles(
        artifacts_tracked=len(all_records),
        orphan_risk=len(orphan_risk_records),
        unknown_confidence=len(unknown_confidence_records),
        pending_drafts=len(drafts),
        tiers_at_risk=sum(
            1 for tier in readiness.tiers if tier.status in ("high", "medium")
        ),
        data_quality_issues=sum(
            1 for tally in coverage.values() if LOG_FORMAT_ERROR_MARKER in tally
        ),
    )
    rag_html = _render_rag_panel(readiness.tiers)
    generated_at = datetime.now(timezone.utc).strftime(_TIMESTAMP_FORMAT)

    page = _PAGE_TEMPLATE
    page = page.replace("<!-- GENERATED_AT -->", html.escape(generated_at))
    page = page.replace("<!-- KPI_TILES -->", tiles_html)
    page = page.replace("<!-- RAG_PANEL -->", rag_html)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Write-then-rename rather than a direct `write_text`: `os.replace` is
    # atomic on both POSIX and Windows, so a viewer refreshing this file in
    # a browser mid-regeneration always sees either the old complete file or
    # the new complete file, never a truncated partial write. The temp file
    # is created in the same directory as `output_path` so the rename can
    # never cross a filesystem boundary (which would break atomicity).
    temp_path = output_path.with_name(f".{output_path.name}.tmp")
    temp_path.write_text(page, encoding="utf-8")
    os.replace(temp_path, output_path)
    return output_path


_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rez Ops -- Executive Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,wght@0,500;0,600;1,500&family=Public+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #faf5ee;
    --surface: #ffffff;
    --border: #e7dccb;
    --text: #2b2420;
    --muted: #8a7b68;
    --accent: #a8482a;
    --good: #2f7a4d;
    --good-bg: #e6f2ea;
    --warn: #a06a10;
    --warn-bg: #fbf0dc;
    --critical: #a8342a;
    --critical-bg: #fbe7e4;
    --unknown: #6b6459;
    --unknown-bg: #ece7de;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: "Public Sans", -apple-system, BlinkMacSystemFont, sans-serif;
  }
  h1, h2, h3 { font-family: "Newsreader", Georgia, serif; font-weight: 600; margin: 0; }
  header.page-header {
    padding: 28px 32px 20px;
    border-bottom: 1px solid var(--border);
    background: var(--surface);
  }
  header.page-header h1 { font-size: 28px; color: var(--accent); }
  header.page-header .subtitle {
    margin-top: 6px;
    color: var(--muted);
    font-size: 13px;
  }
  nav.tabs {
    display: flex;
    gap: 4px;
    padding: 0 32px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
  }
  nav.tabs button {
    font-family: inherit;
    font-size: 14px;
    padding: 12px 16px;
    border: none;
    background: none;
    color: var(--muted);
    cursor: pointer;
    border-bottom: 2px solid transparent;
  }
  nav.tabs button.active {
    color: var(--accent);
    border-bottom-color: var(--accent);
    font-weight: 600;
  }
  main { padding: 28px 32px 48px; max-width: 1080px; margin: 0 auto; }
  section.view { display: none; }
  section.view.active { display: block; }
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 20px 24px;
    margin-bottom: 24px;
  }
  .card h2 { font-size: 18px; margin-bottom: 14px; }
  .kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
  }
  .kpi-tile {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 18px 16px;
    text-align: left;
  }
  .kpi-value {
    font-family: "Newsreader", Georgia, serif;
    font-size: 32px;
    font-variant-numeric: tabular-nums;
    color: var(--accent);
  }
  .kpi-label {
    margin-top: 4px;
    font-size: 12.5px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  table.rag-table { width: 100%; border-collapse: collapse; }
  table.rag-table th, table.rag-table td {
    text-align: left;
    padding: 10px 8px;
    border-bottom: 1px solid var(--border);
    font-size: 14px;
  }
  table.rag-table th { color: var(--muted); font-weight: 500; font-size: 12.5px; text-transform: uppercase; }
  .rag-tier-name { font-weight: 600; }
  .rag-detail { color: var(--muted); font-size: 13px; }
  .rag-pill {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 12.5px;
    font-weight: 600;
  }
  .rag-pill-good { color: var(--good); background: var(--good-bg); }
  .rag-pill-warn { color: var(--warn); background: var(--warn-bg); }
  .rag-pill-critical { color: var(--critical); background: var(--critical-bg); }
  .rag-pill-unknown { color: var(--unknown); background: var(--unknown-bg); }
  .rag-empty { color: var(--muted); font-size: 14px; }
  .not-wired-banner {
    display: flex;
    align-items: center;
    gap: 12px;
    background: var(--unknown-bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 18px;
  }
  .not-wired-tag {
    flex: none;
    background: var(--unknown);
    color: var(--surface);
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 4px 10px;
    border-radius: 999px;
  }
  .not-wired-banner p { margin: 0; color: var(--muted); font-size: 13.5px; }
  .placeholder-box {
    border: 1px dashed var(--border);
    border-radius: 8px;
    padding: 32px;
    text-align: center;
    color: var(--muted);
    font-size: 14px;
  }
</style>
</head>
<body>
<header class="page-header">
  <h1>Rez Ops -- Executive Dashboard</h1>
  <div class="subtitle">Generated <!-- GENERATED_AT --> UTC -- static snapshot, regenerate on demand via <code>python -m ops.generate_dashboard</code></div>
</header>
<nav class="tabs">
  <button class="active" data-target="view-home">Home</button>
  <button data-target="view-dependency-map">Dependency Map</button>
  <button data-target="view-ask-rez-ops">Ask Rez Ops</button>
  <button data-target="view-upcoming-tests">Upcoming DR Tests</button>
  <button data-target="view-recent-tests">Recent DR Tests</button>
</nav>
<main>
  <section id="view-home" class="view active">
    <div class="kpi-grid">
<!-- KPI_TILES -->
    </div>
    <div class="card">
      <h2>DR Readiness by Tier</h2>
<!-- RAG_PANEL -->
    </div>
  </section>

  <section id="view-dependency-map" class="view">
    <div class="card">
      <h2>Dependency Map</h2>
<!-- NOT_WIRED_BANNER -->
      <div class="placeholder-box">Dependency graph will render here once this view is wired to real data.</div>
    </div>
  </section>

  <section id="view-ask-rez-ops" class="view">
    <div class="card">
      <h2>Ask Rez Ops</h2>
<!-- NOT_WIRED_BANNER -->
      <div class="placeholder-box">A natural-language query panel will render here once this view is wired to real data.</div>
    </div>
  </section>

  <section id="view-upcoming-tests" class="view">
    <div class="card">
      <h2>Upcoming DR Tests</h2>
<!-- NOT_WIRED_BANNER -->
      <div class="placeholder-box">A table of upcoming DR tests will render here once this view is wired to real data.</div>
    </div>
  </section>

  <section id="view-recent-tests" class="view">
    <div class="card">
      <h2>Recent DR Tests</h2>
<!-- NOT_WIRED_BANNER -->
      <div class="placeholder-box">A table of recent DR tests will render here once this view is wired to real data.</div>
    </div>
  </section>
</main>
<script>
  // View-switching only -- no data fetch, no auto-refresh, no live query:
  // this page never talks back to ledger-core (CAP-13's non-goal). A fresh
  // run of ops/generate_dashboard.py is the only way to update this file.
  document.querySelectorAll("nav.tabs button").forEach(function (button) {
    button.addEventListener("click", function () {
      document.querySelectorAll("nav.tabs button").forEach(function (b) {
        b.classList.remove("active");
      });
      document.querySelectorAll("section.view").forEach(function (section) {
        section.classList.remove("active");
      });
      button.classList.add("active");
      document.getElementById(button.dataset.target).classList.add("active");
    });
  });
</script>
</body>
</html>
"""

# Bakes the single `_NOT_WIRED_BANNER` constant into all four unwired-view
# placeholders above, once, at import time -- so those four sections can
# never drift out of sync with each other or with the constant. This is a
# static, always-identical-content substitution (unlike the three dynamic,
# per-generation fragments `generate_dashboard` splices in below), so it
# does not count among -- and is deliberately kept separate from -- those
# three `.replace()` calls.
_PAGE_TEMPLATE = _PAGE_TEMPLATE.replace("<!-- NOT_WIRED_BANNER -->", _NOT_WIRED_BANNER)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a static executive dashboard HTML snapshot from real "
            "ledger state (CAP-13)."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"output HTML file path (default: {DEFAULT_OUTPUT_PATH})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Generate the dashboard once; print its path on success, else fail cleanly.

    Never raises past its own body -- mirrors
    `run_scheduled_briefing.main`'s never-raise-past-`main` discipline. Any
    exception during generation (e.g. a write failure -- permission denied,
    disk full) is caught here, printed as one error line to stderr, and
    becomes a non-zero return code.
    """
    args = _parse_args(argv)
    try:
        output_path = generate_dashboard(output_path=args.output)
    except Exception as exc:  # noqa: BLE001 -- last resort: never raise past main
        print(
            f"ops/generate_dashboard.py: failed to generate dashboard: {exc}",
            file=sys.stderr,
        )
        return 1

    # Printed resolved (absolute) so the reported path is unambiguous
    # regardless of the caller's cwd -- `generate_dashboard` itself still
    # returns (and writes to) the caller-given `output_path` unchanged.
    print(str(output_path.resolve()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
