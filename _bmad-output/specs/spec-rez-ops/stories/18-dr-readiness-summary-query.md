---
title: 'DR readiness summary query'
type: 'feature'
created: '2026-09-06'
status: 'done'
review_loop_iteration: 0
baseline_commit: '2fb1288a98a970e56d3a33a8bccf5e86a431c924'
context:
  - '{project-root}/_bmad-output/specs/spec-rez-ops/SPEC.md'
  - '{project-root}/ledger_core/briefing.py'
  - '{project-root}/ledger_core/projection.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Story 17 computes `risk`/`tier_sla` per artifact, but there's no single call to see readiness rolled up across every declared tier -- a caller wanting "what's our overall DR posture" must call `ledger_get_record` once per artifact and tally manually.

**Approach:** One new read-only MCP tool, `ledger_get_dr_readiness_summary`, aggregating risk counts and an overall status per declared tier from `rezops.tiers.yaml` -- extending CAP-4's existing "ask what needs attention" intent, the same way `ledger_get_briefing` composes existing reads rather than computing anything new about artifact state. "Three independent axes" (application tier, infrastructure, data centres) resolves to *however many tiers are actually declared* -- no hardcoded axis list in code. `rezops.tiers.yaml` gains two more example declarations (`infrastructure`, `data_centre`) so the shipped example genuinely demonstrates more than one kind of tier.

## Boundaries & Constraints

**Always:**
- `get_dr_readiness_summary()` (new, `ledger_core/dr_readiness.py`, mirroring `briefing.py`'s module shape: a frozen dataclass + one composing function) iterates every tier declared in `rezops.tiers.yaml` (sorted alphabetically by name, for determinism), and for each, every `(artifact_type, artifact_id)` assigned to it -- calling `ledger_core.projection.get_record` for each (never a parallel reimplementation of risk computation).
- Per tier: `artifact_count` (how many artifacts are assigned to it), `risk_counts` (`{"high": int, "medium": int, "low": int, "unknown": int}`, always all four keys present even at zero), and `status` -- the single worst risk level present among that tier's artifacts, using the fixed severity order `high > medium > unknown > low` (documented here, not left to the implementer to invent: `unknown` outranks `low` because "we don't know" must never look as safe as "confirmed low risk," matching this project's own never-hide-uncertainty principle). A tier with zero assigned artifacts has `artifact_count=0`, every `risk_counts` value `0`, `status="low"`.
- `_load_tiers` (`ledger_core/projection.py`) becomes a public, exported function (rename, drop the leading underscore) -- reused directly by `dr_readiness.py`, never a second hand-rolled parser for the same file format. Every existing internal call site in `projection.py` updates to the new name.
- Read-only: no log append, no config write, no draft. Never raises for a missing `rezops.tiers.yaml` (`_load_tiers`'s existing missing-file behavior: `({}, {})`, so the summary's `tiers` list is simply empty) or an empty `ledger_dir`.
- New MCP tool `ledger_get_dr_readiness_summary` in `ledger_core/server.py`, mirroring `ledger_get_briefing`'s exact shape (no parameters, returns structured data only, `generated_at` populated).

**Ask First:**
- Any change to the severity-order rule or the zero-artifact default beyond what's specified above.

**Never:**
- No hardcoded list of exactly three axis names anywhere in code -- the set of tiers is always read from config.
- No change to `_compute_tier_and_risk`'s frozen risk formula (Story 17) -- this story only aggregates its existing output, never recomputes it differently.
- No UI, no delivery channel -- structured data only, same as `ledger_get_briefing`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Multiple tiers, mixed risk | 3+ declared tiers, artifacts at varying risk levels | One row per tier, correct `risk_counts` and `status` per tier | N/A |
| Tier with a high-risk artifact | At least one `risk="high"` in the tier | `status="high"` regardless of any `low`/`medium` also present | N/A |
| Tier with only `unknown`-risk artifacts | Every artifact in the tier resolves `risk="unknown"` | `status="unknown"`, ranks above a tier whose worst is `low` | N/A |
| Tier declared but unassigned | Tier in `tiers.<name>.expiry_days` config, no `assign` entries reference it | `artifact_count=0`, all `risk_counts` zero, `status="low"` | N/A |
| No `rezops.tiers.yaml` | File doesn't exist | `tiers=[]` | Never raises |
| Empty ledger | No log files at all | Every tier's `artifact_count=0` (nothing to tally) | Never raises |

</frozen-after-approval>

## Code Map

- `ledger_core/briefing.py` -- reuse as the exact structural template: frozen dataclass + one composing function, `generated_at` population, read-only discipline, module docstring style
- `ledger_core/projection.py:82` (`_load_tiers`) -- rename to public `load_tiers`, update internal call sites at `:337`+ (`get_record`) and `:524`+ (`list_records`)
- `ledger_core/projection.py:166` (`_compute_tier_and_risk`) -- read-only reference, never modified
- `ledger_core/dr_readiness.py` -- new: `TierReadiness`/`DrReadinessSummary` dataclasses, `get_dr_readiness_summary()`
- `ledger_core/server.py:405` (`ledger_get_briefing`) -- reuse as the exact MCP-tool wrapper template; add the new tool nearby
- `rezops.tiers.yaml` -- add `tier.infrastructure.expiry_days`/`tier.data_centre.expiry_days` declarations plus a couple of `assign` entries under each, so the shipped example has more than application tiers to roll up
- `tests/test_ledger_core.py` -- full I/O matrix coverage for the new module and tool

## Tasks & Acceptance

**Execution:**
- [x] `ledger_core/projection.py` -- rename `_load_tiers` to public `load_tiers`, update all internal call sites
- [x] `rezops.tiers.yaml` -- add `infrastructure`/`data_centre` tier declarations and assignments
- [x] `ledger_core/dr_readiness.py` -- new module: dataclasses + `get_dr_readiness_summary()`
- [x] `ledger_core/server.py` -- new `ledger_get_dr_readiness_summary` MCP tool
- [x] `tests/test_ledger_core.py` -- full I/O matrix coverage, plus a test proving the tool's output matches calling `get_dr_readiness_summary()` directly (same shape-fidelity discipline as `ledger_get_briefing`)

**Acceptance Criteria:**
- Given the full test suite, when `uv run pytest` runs, then all tests pass.
- Given a tier with one `risk="high"` artifact and several `risk="low"` ones, when `ledger_get_dr_readiness_summary` is called, then that tier's `status="high"`.
- Given no `rezops.tiers.yaml`, when the tool is called, then it returns `{"tiers": [], "generated_at": ...}` rather than raising.
- Given the ledger-core-independent MCP server, when a client lists its tools, then `ledger_get_dr_readiness_summary` is exposed and issues no write of any kind.

## Design Notes

The severity order `high > medium > unknown > low` is this story's own explicit, documented choice (mirrors Story 17's "keep it simple, document the choice rather than archaeology-dig it later" precedent) -- ranking `unknown` above `low` is deliberate: an aggregate view that let "nothing observed yet" look identical to "confirmed safe" would hide exactly the kind of uncertainty this whole project exists to surface.

## Spec Change Log

## Verification

**Commands:**
- `uv sync` -- expected: resolves without error -- ran, resolved with no changes
- `uv run pytest -v` -- expected: all tests pass, including every prior story's -- ran, 723 passed (up from 721 baseline)
- Manually call `ledger_get_dr_readiness_summary` against the shipped `rezops.tiers.yaml` and confirm one row per declared tier -- confirmed: 5 rows (`data_centre`, `gold`, `infrastructure`, `platinum`, `silver`), alphabetically sorted

Adversarial review ran (3 lenses). Findings triaged: 5 patched and independently re-verified, 4 lower-priority gaps logged to `deferred-work.md`, 5 other findings checked and rejected as matching pre-existing precedent or out of this story's scope:
1. A stale test name (asserted twelve tools, still said "eleven") -- renamed.
2. `README.md` was never updated for the new tool -- unlike Story 17 (field-only), this story adds a genuine new MCP tool; tool counts and the tool table corrected.
3. The "never raises" docstring language didn't distinguish a missing config (never raises) from a malformed one (still raises `TiersFileError`, per Story 17's own fail-loudly design) -- corrected, with a new test proving the malformed-config path through both the function and the MCP tool.
4. `load_tiers` gets re-parsed once per artifact (redundant with the function's own initial call) -- an unacknowledged I/O cost. Documented as a deliberate, accepted tradeoff (reusing `get_record`'s one true risk path wins over avoiding a cheap redundant re-read) rather than restructured, since restructuring would violate the frozen "never reimplement risk" boundary.
5. `_RISK_LEVELS`/`_RISK_SEVERITY` enumerated the same four values in two unsynced orders -- a module-load assertion now enforces they stay in sync.

Rejected findings (checked, not real or out of scope): "demo data" in the production tiers config (matches Story 17's own established example-config precedent); the feature not being wired into the briefing/dashboard (out of scope, same as every other on-demand CAP-4 query tool); no defensive check for an out-of-range `risk` value (verification-gap reviewer confirmed `LedgerRecord`'s own validation already makes this impossible); a runtime frozen-dataclass immutability test (tests stdlib behavior, not this story's logic); an import-absence regression test (unconventional, low value).

## Suggested Review Order

**The aggregation itself**

- `get_dr_readiness_summary`: the composing function -- loads tiers, groups assignments, calls `get_record` per artifact, derives `status`. Read this first.
  [`dr_readiness.py:127`](../../../../ledger_core/dr_readiness.py#L127)

- The two dataclasses it returns, including the tuple-vs-list immutability reasoning.
  [`dr_readiness.py:90`](../../../../ledger_core/dr_readiness.py#L90)

- The MCP tool wrapper, mirroring `ledger_get_briefing`'s exact shape.
  [`server.py:536`](../../../../ledger_core/server.py#L536)

**The severity rule (the one real design decision this story made)**

- `high > medium > unknown > low` -- why `unknown` outranks `low`, and the sync-guard assertion the fix round added.
  [`dr_readiness.py:64`](../../../../ledger_core/dr_readiness.py#L64)

- The test proving high-risk dominance regardless of what else is present.
  [`test_ledger_core.py:4335`](../../../../tests/test_ledger_core.py#L4335)

- The test proving `unknown` ranks above `low`, not below it.
  [`test_ledger_core.py:4366`](../../../../tests/test_ledger_core.py#L4366)

**Fix-round additions (peripheral, but worth a look)**

- The malformed-config test -- proves `TiersFileError` still propagates for a bad config, distinct from the missing-file case.
  [`test_ledger_core.py:4422`](../../../../tests/test_ledger_core.py#L4422)

- The two new tier declarations in the shipped example config.
  [`rezops.tiers.yaml:26`](../../../../rezops.tiers.yaml#L26)
