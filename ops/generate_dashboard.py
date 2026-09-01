"""Read-only local dashboard for Rez Ops: renders a snapshot of
`ledger_data/`'s current state as one self-contained static HTML file.

Local-first by design (AD-7): no server process, no external hosting --
run this whenever you want to look at the current state, then open the
file in a browser. Pure presentation over ledger-core's existing read
functions (`get_coverage_map`, `get_briefing`) -- computes nothing new
about artifact state, and writes only to `output_path` (default
`dashboard.html`, kept out of `ledger_data/` itself -- ledger-core remains
the only writer to that directory, AD-3).
"""

from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

from ledger_core.briefing import Briefing, get_briefing
from ledger_core.drafts import Draft
from ledger_core.log import DEFAULT_LEDGER_DATA_DIR
from ledger_core.projection import LOG_FORMAT_ERROR_MARKER, get_coverage_map
from shared.ledger_schema import LedgerRecord

#: Default output location -- a repo-root sibling of `ledger_data/`, not a
#: file inside it (see module docstring: ledger-core is the only writer to
#: `ledger_data/`, AD-3).
DEFAULT_OUTPUT_PATH = Path("dashboard.html")

_CONFIDENCE_ORDER = ("agent-verified", "manual", "unknown")


def _esc(value: object) -> str:
    """HTML-escape any value that might end up on the page as text.

    Every dynamic value here is caller-authored content (a RawFact field,
    a draft's subject/body, an artifact_id) -- never trusted as markup.
    """
    return html.escape(str(value), quote=True)


def _render_coverage_table(coverage: dict[str, dict[str, int]]) -> str:
    if not coverage:
        return '<p class="empty">No artifacts ingested yet.</p>'
    rows = []
    for artifact_type in sorted(coverage):
        tally = coverage[artifact_type]
        if LOG_FORMAT_ERROR_MARKER in tally:
            rows.append(
                f'<tr class="error-row"><td>{_esc(artifact_type)}</td>'
                '<td colspan="3">⚠ corrupted log -- see data quality issues below</td></tr>'
            )
            continue
        counts = "".join(f"<td>{tally.get(c, 0)}</td>" for c in _CONFIDENCE_ORDER)
        rows.append(f"<tr><td>{_esc(artifact_type)}</td>{counts}</tr>")
    header = "".join(f"<th>{c}</th>" for c in _CONFIDENCE_ORDER)
    return (
        f"<table><thead><tr><th>artifact_type</th>{header}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _render_record_table(
    records: tuple[LedgerRecord, ...], empty_message: str
) -> str:
    if not records:
        return f'<p class="empty">{_esc(empty_message)}</p>'
    rows = []
    for record in records:
        rows.append(
            "<tr>"
            f"<td>{_esc(record.artifact_type)}</td>"
            f"<td>{_esc(record.artifact_id)}</td>"
            f"<td>{_esc(record.confidence)}</td>"
            f"<td>{_esc(record.last_verified or '—')}</td>"
            f"<td>{_esc(record.escalation_owner or '—')}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>type</th><th>id</th><th>confidence</th>"
        "<th>last verified</th><th>owner</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _render_drafts_table(drafts: tuple[Draft, ...]) -> str:
    if not drafts:
        return '<p class="empty">No pending drafts.</p>'
    rows = []
    for draft in drafts:
        rows.append(
            "<tr>"
            f"<td>{_esc(draft.artifact_type)}/{_esc(draft.artifact_id)}</td>"
            f"<td>{_esc(draft.draft_type)}</td>"
            f"<td>{_esc(draft.subject)}</td>"
            f"<td>{_esc(draft.recipient or '— unresolved —')}</td>"
            f"<td>{_esc(draft.created_at)}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>artifact</th><th>draft_type</th><th>subject</th>"
        "<th>recipient</th><th>created</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _render_issues_list(data_quality_issues: dict[str, dict[str, int]]) -> str:
    if not data_quality_issues:
        return '<p class="empty">No corrupted logs detected.</p>'
    items = "".join(f"<li>{_esc(t)}</li>" for t in sorted(data_quality_issues))
    return f"<ul>{items}</ul>"


def _severity_class(count: int, *, bad_when_nonzero: bool) -> str:
    """A stat tile's color signals whether its count needs attention.

    `bad_when_nonzero=True` for counts that are always a problem (orphan-risk,
    unknown-confidence, data-quality issues) -- zero is good, anything else
    is a warning/critical. `bad_when_nonzero=False` for counts that are just
    informational (types tracked, pending drafts) -- neutral regardless.
    """
    if not bad_when_nonzero:
        return "sev-neutral"
    return "sev-ok" if count == 0 else "sev-warn"


def _render_stat_strip(coverage: dict[str, dict[str, int]], briefing: Briefing) -> str:
    n_issues = len(briefing.data_quality_issues)
    tiles = [
        ("Types tracked", len(coverage), "sev-neutral"),
        ("Orphan-risk", len(briefing.orphan_risk), _severity_class(len(briefing.orphan_risk), bad_when_nonzero=True)),
        ("Unknown confidence", len(briefing.unknown_confidence), _severity_class(len(briefing.unknown_confidence), bad_when_nonzero=True)),
        ("Pending drafts", len(briefing.pending_drafts), "sev-neutral"),
        ("Data quality issues", n_issues, "sev-critical" if n_issues else "sev-ok"),
    ]
    cells = "".join(
        f'<div class="stat {sev}"><span class="stat-value">{count}</span>'
        f'<span class="stat-label">{_esc(label)}</span></div>'
        for label, count, sev in tiles
    )
    return f'<div class="stat-strip">{cells}</div>'


_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rez Ops Dashboard</title>
<style>
  :root {{
    color-scheme: light dark;
    --bg: #f3f1ec;
    --surface: #ffffff;
    --border: #ddd8cd;
    --text: #1f2430;
    --muted: #6b7080;
    --accent: #c97a1f;
    --ok: #2f8a63;
    --warn: #c97a1f;
    --critical: #b8422f;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #12151b;
      --surface: #1a1e26;
      --border: #262b35;
      --text: #e5e8ee;
      --muted: #8891a3;
      --accent: #e0983a;
      --ok: #49b087;
      --warn: #e0983a;
      --critical: #d15a4d;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    max-width: 1040px;
    margin: 0 auto;
    padding: 2.5rem 1.5rem 4rem;
    line-height: 1.5;
  }}
  .mono {{
    font-family: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;
  }}
  header.top {{
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    padding-bottom: 1.5rem;
    border-bottom: 1px solid var(--border);
  }}
  h1 {{
    font-family: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;
    font-size: 1.4rem;
    letter-spacing: 0.02em;
    margin: 0;
    text-wrap: balance;
  }}
  .meta {{
    color: var(--muted);
    font-size: 0.85rem;
  }}
  .stat-strip {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 1px;
    background: var(--border);
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
    margin-top: 1.75rem;
  }}
  .stat {{
    background: var(--surface);
    padding: 1.1rem 1.2rem;
    border-top: 3px solid var(--muted);
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
  }}
  .stat.sev-ok {{ border-top-color: var(--ok); }}
  .stat.sev-warn {{ border-top-color: var(--warn); }}
  .stat.sev-critical {{ border-top-color: var(--critical); }}
  .stat-value {{
    font-family: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;
    font-variant-numeric: tabular-nums;
    font-size: 1.9rem;
    font-weight: 600;
  }}
  .stat-label {{
    color: var(--muted);
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }}
  section {{ margin-top: 2rem; }}
  .card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1.25rem 1.4rem 1.4rem;
  }}
  .eyebrow {{
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.75rem;
  }}
  h2 {{
    font-family: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
    margin: 0;
  }}
  .table-scroll {{ overflow-x: auto; margin-top: 0.9rem; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.92rem; }}
  th, td {{ text-align: left; padding: 0.5rem 0.7rem; border-bottom: 1px solid var(--border); white-space: nowrap; }}
  th {{
    font-family: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--muted);
    font-weight: 500;
  }}
  tbody tr:last-child td {{ border-bottom: none; }}
  .empty {{
    color: var(--muted);
    font-style: italic;
    margin: 0.9rem 0 0;
    padding: 0.9rem;
    border: 1px dashed var(--border);
    border-radius: 8px;
    font-size: 0.9rem;
  }}
  .error-row td {{ color: var(--critical); }}
  ul {{ margin: 0.9rem 0 0; padding-left: 1.2rem; }}
  li {{ color: var(--critical); }}
</style>
</head>
<body>
<header class="top">
  <h1>REZ OPS // DASHBOARD</h1>
  <p class="meta mono">generated {generated_at} &middot; ledger dir: {ledger_dir}</p>
</header>

{stat_strip}

<section>
<div class="card">
<div class="eyebrow"><h2>Coverage</h2></div>
<div class="table-scroll">{coverage_table}</div>
</div>
</section>

<section>
<div class="card">
<div class="eyebrow"><h2>Orphan-risk</h2></div>
<div class="table-scroll">{orphan_table}</div>
</div>
</section>

<section>
<div class="card">
<div class="eyebrow"><h2>Unknown confidence</h2></div>
<div class="table-scroll">{unknown_table}</div>
</div>
</section>

<section>
<div class="card">
<div class="eyebrow"><h2>Pending drafts</h2></div>
<div class="table-scroll">{drafts_table}</div>
</div>
</section>

<section>
<div class="card">
<div class="eyebrow"><h2>Data quality issues</h2></div>
{issues_list}
</div>
</section>

</body>
</html>
"""


def generate_dashboard(
    *,
    ledger_dir: Path = DEFAULT_LEDGER_DATA_DIR,
    output_path: Path = DEFAULT_OUTPUT_PATH,
) -> Path:
    """Render a self-contained static HTML snapshot of `ledger_dir`'s state.

    Pure presentation: composes `get_coverage_map` and `get_briefing`
    (which itself composes `list_records`/`list_drafts`/`get_coverage_map`)
    -- no new computation about artifact state, matching the project's
    thin-orchestration-layer principle (AD-1). A corrupted artifact-type
    log is never hidden -- it surfaces both as an `⚠` marker in the
    coverage table and in the Data quality issues section, same visibility
    `ledger_get_coverage`/`ledger_get_briefing` already give it (AD-8).
    """
    coverage = get_coverage_map(ledger_dir=ledger_dir)
    briefing = get_briefing(ledger_dir=ledger_dir)

    page = _PAGE_TEMPLATE.format(
        generated_at=_esc(briefing.generated_at),
        ledger_dir=_esc(ledger_dir),
        stat_strip=_render_stat_strip(coverage, briefing),
        coverage_table=_render_coverage_table(coverage),
        orphan_table=_render_record_table(
            briefing.orphan_risk, "No orphan-risk artifacts."
        ),
        unknown_table=_render_record_table(
            briefing.unknown_confidence, "No unknown-confidence artifacts."
        ),
        drafts_table=_render_drafts_table(briefing.pending_drafts),
        issues_list=_render_issues_list(briefing.data_quality_issues),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(page, encoding="utf-8")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ledger-dir",
        type=Path,
        default=DEFAULT_LEDGER_DATA_DIR,
        help="Ledger data directory to read (default: ./ledger_data)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Path to write the HTML snapshot to (default: ./dashboard.html)",
    )
    args = parser.parse_args()

    output_path = generate_dashboard(ledger_dir=args.ledger_dir, output_path=args.output)
    print(f"Dashboard written to {output_path.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
