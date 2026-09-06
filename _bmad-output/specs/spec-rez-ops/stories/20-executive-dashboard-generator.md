---
title: 'Executive dashboard generator'
type: 'feature'
created: '2026-09-06'
status: 'done'
review_loop_iteration: 0
baseline_commit: 'a628f16786320186ebc10659f2abe3de783f3788'
context:
  - '{project-root}/_bmad-output/specs/spec-rez-ops/SPEC.md'
  - '{project-root}/ops/run_scheduled_briefing.py'
  - '{project-root}/ledger_core/dr_readiness.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Home view of a design prototype (validated live, iteratively, with the user) shows what DR readiness *could* look like, but every number in it is hand-typed placeholder data -- it has never queried Rez Ops's real ledger.

**Approach:** A new script, `ops/generate_dashboard.py`, mirrors `ops/run_scheduled_briefing.py`'s operational-script convention (non-interactive, no subprocess/Voice needed here since this calls ledger-core's Python functions directly, not through MCP) to compose a self-contained HTML file from real ledger state. Only the Home view (KPI tiles + RAG status) gets real data this pass; every other prototype view stays in the page but is visibly relabeled as not yet wired.

## Boundaries & Constraints

**Always:**
- `generate_dashboard(*, ledger_dir=DEFAULT_LEDGER_DATA_DIR, tiers_path=DEFAULT_TIERS_PATH, output_path=DEFAULT_OUTPUT_PATH) -> Path` composes exactly four existing read functions -- `ledger_core.dr_readiness.get_dr_readiness_summary`, `ledger_core.projection.list_records` (once unfiltered, once `orphan_risk=True`, once `confidence="unknown"`), `ledger_core.drafts.list_drafts`, `ledger_core.projection.get_coverage_map` -- and performs no other computation. Writes the composed HTML to `output_path` (default `ledger_data/dashboard.html`) and returns that path. No write of any kind beyond that one file.
- Six KPI tiles, each a plain count from the above, redesigned around what Rez Ops actually computes (not the prototype's CEVA-specific tiles): **Artifacts Tracked** (`len(list_records())`), **Orphan-Risk** (`len(list_records(orphan_risk=True))`), **Unknown Confidence** (`len(list_records(confidence="unknown"))`), **Pending Drafts** (`len(list_drafts())`), **Tiers At Risk** (count of `get_dr_readiness_summary().tiers` with `status in ("high", "medium")`), **Data-Quality Issues** (count of `get_coverage_map()` entries containing `LOG_FORMAT_ERROR_MARKER`).
- RAG Status panel: one row per `get_dr_readiness_summary().tiers` entry -- tier name, a pill (`status="low"` → green "Good"; `"medium"` → amber "At Risk"; `"high"` → red "Critical"; `"unknown"` → a new neutral-gray "Unknown" pill style, since the prototype never needed a fourth state), and a detail line showing the actual risk-count breakdown (e.g. "2 high · 1 medium · 0 low · 1 unknown") -- replacing the prototype's per-field confidence-dot device, which doesn't correspond to any real aggregate value this function computes.
- Every other prototype view (Dependency Map, "Ask Rez Ops", Upcoming/Recent DR Tests tables) stays in the generated page's markup and nav, each carrying a permanent, visible "Not yet wired to real data" banner (matching the design language already used for `roadmap.md`'s "Later"/"Open Question" phase tags) -- never silently removed, never populated with the prototype's placeholder numbers presented as real.
- `generated_at`: the UTC timestamp the page was composed, displayed in the header, matching every other `generated_at` field's format in this project.
- HTML/CSS/JS generation is hand-rolled Python string composition (dynamic fragments spliced into a static template via HTML-comment markers and plain `.replace()`, e.g. `<!-- KPI_TILES -->`) -- no new dependency, no `.format()`-based templating (its `{`/`}` escaping would fight the CSS's own braces).
- CLI: `python -m ops.generate_dashboard [--output PATH]`, printing the resolved output path on success, a one-line error to stderr and a non-zero exit on failure -- mirrors `run_scheduled_briefing.py`'s never-raise-past-`main` discipline.

**Ask First:**
- Any KPI tile or RAG-cell design beyond what's specified above.

**Never:**
- No new computation -- every displayed value is exactly what its underlying function already returns; this story never reimplements risk/confidence/coverage logic.
- No hosted server, no auto-refresh, no live query from the HTML page itself -- a fresh run of the script is the only way to update it (CAP-13's non-goal).
- No fabricated numbers on an unwired view, ever -- a banner, not a number, represents "not real yet."

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Populated ledger | Real facts recorded, some orphan-risk, some unknown-confidence, some drafts pending | All six KPI tiles show correct non-zero counts | N/A |
| Empty ledger (`ledger_data/` doesn't exist) | No facts ever recorded | All list-based tiles show `0`; RAG panel still shows one row per *declared* tier (from `rezops.tiers.yaml`'s config, independent of whether any facts exist), each `status="unknown"` | N/A |
| Corrupted artifact-type log | One type's log fails to parse | Data-Quality Issues tile reflects it; that type's records still degrade gracefully elsewhere (existing AD-8 behavior, unchanged) | N/A |
| Missing `rezops.tiers.yaml` | File doesn't exist | RAG panel is empty (`tiers=[]`); KPI tiles unaffected | Never raises |
| `--output` given a path whose parent doesn't exist | e.g. `--output /tmp/nested/dir/dashboard.html` | Parent directories created, same as `ledger_core.log.append_event`'s own `_ensure_ledger_dir` behavior | N/A |
| Write failure (permission denied, disk full) | `output_path` unwritable | -- | `main` catches it, prints one error line to stderr, returns 1 -- never a raw traceback |

</frozen-after-approval>

## Code Map

- `ops/run_scheduled_briefing.py` -- reuse as the exact operational-script template: module docstring style, `main(...) -> int` never-raises discipline, `if __name__ == "__main__": sys.exit(main())`
- `ledger_core/dr_readiness.py:135` (`get_dr_readiness_summary`), `ledger_core/projection.py:732` (`list_records`), `:641` (`get_coverage_map`, `LOG_FORMAT_ERROR_MARKER`), `ledger_core/drafts.py:394` (`list_drafts`) -- the four read functions this story composes, never reimplements
- The iterated Claude Artifact prototype (this session's conversation history -- Vero-inspired warm palette, Newsreader/Public Sans, confidence-dot device, Cytoscape dependency graph, "Ask Rez Ops" panel) -- the visual shape to preserve; not a file in this repo, so the static HTML/CSS/JS shell must be authored fresh here matching that validated design, not copy-pasted from anywhere
- `ops/generate_dashboard.py` -- new: the script
- `tests/test_generate_dashboard.py` -- new: unit tests for every I/O matrix row

## Tasks & Acceptance

**Execution:**
- [x] `ops/generate_dashboard.py` -- new script: HTML template (static shell + the two dynamic fragments), the six KPI tiles, the RAG panel, the "not yet wired" banners on unwired views, `generate_dashboard`, `main`, CLI arg parsing
- [x] `tests/test_generate_dashboard.py` -- full I/O matrix coverage, plus a test asserting every KPI tile's displayed count matches a direct call to its underlying function at the same point in time (CAP-13's own success criterion, mirroring CAP-7's "must match a live query" test pattern)

**Acceptance Criteria:**
- Given the full test suite, when `uv run pytest` runs, then all tests pass.
- Given a populated ledger, when `generate_dashboard()` runs, then every KPI tile's number exactly equals what the corresponding function call returns independently, at the same point in time.
- Given the generated HTML, when inspected, then the Dependency Map/Ask Rez Ops/test tables carry a visible "not yet wired" banner and no fabricated numbers.
- Given `python -m ops.generate_dashboard`, when run from a fresh checkout with no `ledger_data/`, then it exits 0, writes a valid HTML file, and every KPI tile shows `0` rather than raising.

## Design Notes

The RAG cell's secondary line changes meaning from the prototype: it showed a per-field confidence percentage there (borrowed from the Vero reference's own field-level device), but `get_dr_readiness_summary` doesn't compute an aggregate confidence value per tier -- only a risk-count breakdown. Showing that breakdown instead is the honest substitute, not a downgrade: it's real data in the same visual slot, rather than a repurposed prototype number.

## Spec Change Log

## Verification

**Commands:**
- `uv sync` -- expected: resolves without error -- ran, resolved with no changes
- `uv run pytest -v` -- expected: all tests pass, including every prior story's -- ran, 820 passed (up from 815 baseline)
- `python -m ops.generate_dashboard` -- expected: writes `ledger_data/dashboard.html`, prints its path, exits 0 -- ran against the real repo: all six KPI tiles show `0` (correct -- no real ledger facts exist yet), the RAG panel shows all 5 real `rezops.tiers.yaml` tiers each `status="unknown"` with risk-counts exactly matching the config's `assign` line counts per tier, and all 4 unwired views carry the honest banner with no fabricated numbers

**Recovery note:** mid-fix-round, an implementer agent accidentally destroyed `ops/generate_dashboard.py` via an errant `git checkout` (the git index held an empty placeholder from an earlier `git add -N` used to construct the review diff) before being cut off by an unrelated system interruption. Recovered by extracting the file's pre-patch-round content back out of the already-saved review diff, verified against a clean 815-test run, then re-dispatched the remaining patches with an explicit instruction against destructive git commands. No work was actually lost -- the diff used for review already held the full content.

Adversarial review ran (3 lenses). Findings triaged: 10 patched and independently re-verified (including actually running the generator and inspecting real output, not just the test suite), 5 lower-priority gaps logged to `deferred-work.md`, 4 other findings checked and rejected as matching pre-existing precedent or the frozen spec's own explicit boundary:
1. `_NOT_WIRED_BANNER` was defined but unused (4 inline duplicates that could drift) -- now the single source of truth for all four unwired-view banners.
2. Docstring said "two dynamic fragments," code has three -- corrected.
3. `html.escape` calls existed but were untested -- added a test with unsafe characters in a tier name.
4. `.gitignore`'s `dashboard.html` entry had no directory prefix -- scoped to `ledger_data/dashboard.html`.
5. No test for a malformed (not just missing) `rezops.tiers.yaml` reaching `main()` -- added.
6. Neither README documented the new script -- added to both.
7. `output_path.write_text(...)` wasn't atomic -- now writes to a temp file and `os.replace`s it into place.
8. **KPI tile label/value binding was only weakly tested** (verified via mutation: swapping two kwargs left all tests green) -- added a test binding each label to its own tile's value.
9. **Medium/high RAG pill mapping was never exercised** (verified via mutation the same way -- every test's seeded data resolved to low/unknown only) -- added tests seeding stale timestamps to force medium/high/low and asserting the exact pill per tier.
10. A test fixture's comment didn't match its own code, and "Unknown Confidence" wasn't actually demonstrated tied to a specific artifact -- fixed the fixture and added a dedicated test.

Rejected findings (checked, not real or out of scope): missing `--ledger-dir`/`--tiers-path` CLI flags (matches the frozen spec's explicit `[--output PATH]`-only boundary); `list_drafts()` "pending-only" concern (confirmed -- `Draft` has no status field at all, AD-6 never marks anything sent); no JS/browser behavioral testing (no precedent in this Python-only suite); `IsADirectoryError` propagating from `generate_dashboard()` uncaught (matches the frozen spec's own library-raises/`main`-catches split).

## Suggested Review Order

**The composing function (the core of this story)**

- `generate_dashboard`: loads the four read functions, builds the two dynamic fragments, atomically writes the file. Read this first.
  [`generate_dashboard.py:149`](../../../../ops/generate_dashboard.py#L149)

- `_render_kpi_tiles`: the six real KPI tiles, redesigned around Rez Ops's own capabilities.
  [`generate_dashboard.py:86`](../../../../ops/generate_dashboard.py#L86)

- `_render_rag_panel`: one row per declared tier, the pill mapping including the new "Unknown" state.
  [`generate_dashboard.py:113`](../../../../ops/generate_dashboard.py#L113)

- `main`: the CLI entry point, never-raises discipline mirroring `run_scheduled_briefing.py`.
  [`generate_dashboard.py:476`](../../../../ops/generate_dashboard.py#L476)

**The fix-round regression guards (the two real gaps the review found)**

- Proves each KPI tile's value is bound to its own label, not just present somewhere on the page.
  [`test_generate_dashboard.py:518`](../../../../tests/test_generate_dashboard.py#L518)

- Proves the medium/high/low RAG pill mapping is actually correct, not just inferred.
  [`test_generate_dashboard.py:258`](../../../../tests/test_generate_dashboard.py#L258)

**Peripheral**

- The HTML-escaping regression test.
  [`test_generate_dashboard.py:327`](../../../../tests/test_generate_dashboard.py#L327)

- `_NOT_WIRED_BANNER`: the single source of truth for all four unwired-view banners.
  [`generate_dashboard.py:77`](../../../../ops/generate_dashboard.py#L77)
