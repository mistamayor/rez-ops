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

from ledger_core.briefing import get_briefing
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


_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Rez Ops Dashboard</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 960px;
          margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }}
  h1 {{ margin-bottom: 0; }}
  .generated-at {{ color: #767676; font-size: 0.9rem; margin-top: 0.25rem; }}
  section {{ margin-top: 2.5rem; }}
  h2 {{ border-bottom: 2px solid #ccc; padding-bottom: 0.3rem; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 0.75rem; }}
  th, td {{ text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid #ddd; }}
  th {{ background: rgba(127,127,127,0.15); }}
  .empty {{ color: #767676; font-style: italic; }}
  .error-row {{ background: rgba(220, 50, 47, 0.15); }}
  .badge {{ display: inline-block; padding: 0.1rem 0.5rem; border-radius: 999px;
            font-size: 0.8rem; background: rgba(127,127,127,0.18); }}
</style>
</head>
<body>
<h1>Rez Ops Dashboard</h1>
<p class="generated-at">Snapshot generated {generated_at} &middot; ledger dir: {ledger_dir}</p>

<section>
<h2>Coverage <span class="badge">{n_types} artifact type(s)</span></h2>
{coverage_table}
</section>

<section>
<h2>Orphan-risk <span class="badge">{n_orphan}</span></h2>
{orphan_table}
</section>

<section>
<h2>Unknown confidence <span class="badge">{n_unknown}</span></h2>
{unknown_table}
</section>

<section>
<h2>Pending drafts <span class="badge">{n_drafts}</span></h2>
{drafts_table}
</section>

<section>
<h2>Data quality issues <span class="badge">{n_issues}</span></h2>
{issues_list}
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
        n_types=len(coverage),
        coverage_table=_render_coverage_table(coverage),
        n_orphan=len(briefing.orphan_risk),
        orphan_table=_render_record_table(
            briefing.orphan_risk, "No orphan-risk artifacts."
        ),
        n_unknown=len(briefing.unknown_confidence),
        unknown_table=_render_record_table(
            briefing.unknown_confidence, "No unknown-confidence artifacts."
        ),
        n_drafts=len(briefing.pending_drafts),
        drafts_table=_render_drafts_table(briefing.pending_drafts),
        n_issues=len(briefing.data_quality_issues),
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
