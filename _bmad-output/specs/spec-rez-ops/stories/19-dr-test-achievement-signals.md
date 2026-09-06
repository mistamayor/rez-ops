---
title: 'DR test achievement signals'
type: 'feature'
created: '2026-09-06'
status: 'done'
review_loop_iteration: 0
baseline_commit: 'fe3785384d42881f5d1dfb11c57ed6f78996d199'
context:
  - '{project-root}/_bmad-output/specs/spec-rez-ops/SPEC.md'
  - '{project-root}/ledger_core/projection.py'
  - '{project-root}/rezops.tiers.yaml'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** A DR test result today is only ever pass/fail -- no signal for *how well* it performed against its declared recovery targets, and no independent check that it ran inside the program's mandated annual testing window.

**Approach:** Ledger-core computes two new signals per artifact, generically -- for any artifact_type, not a hardcoded "test_records" name -- from fields already present in its folded `RawFact` history: `rto_achieved_pct`/`rpo_achieved_pct` (target-vs-actual recovery time/point, as a percentage) and `testing_window_compliance` (whether a test's date falls inside a new config-declared annual window). A new git-tracked config, `rezops.testing_window.yaml`, declares the window -- the same declare-in-config/ledger-core-computes pattern `rezops.tiers.yaml`/`rezops.policy.yaml` already established.

## Boundaries & Constraints

**Always:**
- Raw fields a caller may report on any artifact (already permitted -- `RawFact.fields` already accepts int/float/str scalars, no schema change needed here): `rto_target_minutes`, `rto_actual_minutes`, `rpo_target_minutes`, `rpo_actual_minutes` (numbers), `test_date` (ISO `YYYY-MM-DD` string).
- Two new `LedgerRecord` fields, ledger-core-exclusive (added to `LEDGER_ONLY_FIELDS`, never connector/caller-writable, same constraint class as `risk`/`tier_sla`): `rto_achieved_pct: float | None`, `rpo_achieved_pct: float | None`.
- Achieved-percentage formula (identical for RTO and RPO, applied independently): given `target` and `actual` both present and numeric (`int`/`float`, not `bool`) with `target > 0` and `actual > 0`, `achieved_pct = min(100.0, (target / actual) * 100)` -- capped at 100 (can't "achieve more than 100%"). Any other case (either field missing, non-numeric, `bool`, or non-positive) -> `None`, never raises, never guesses.
- One new `LedgerRecord` field, `testing_window_compliance: str`, values restricted to exactly `{"compliant", "non_compliant", "unknown"}` (new `TESTING_WINDOW_COMPLIANCE_VALUES`, validated in `__post_init__` like `CONFIDENCE_VALUES`/`RISK_VALUES`), also ledger-core-exclusive.
- `rezops.testing_window.yaml` (repo root): exactly two lines, `window_start: MM-DD` and `window_end: MM-DD` (no year -- the window recurs annually). If `window_end`'s month/day is earlier in the calendar than `window_start`'s, the window wraps across a year boundary (e.g. `11-01`/`02-28` means Nov 1 through Feb 28). Missing file -> `testing_window_compliance="unknown"` for every artifact, never raises (mirrors `load_tiers`'s missing-file behavior). Malformed file (not exactly two `MM-DD` lines, an invalid month/day) fails loudly (`TestingWindowFileError`), mirroring `load_tiers`/`_load_policy`'s discipline -- never silently ignored.
- `testing_window_compliance` resolution: `"unknown"` if `test_date` is missing, non-string, or unparseable as `YYYY-MM-DD`, OR if `rezops.testing_window.yaml` is missing. Otherwise `"compliant"` if `test_date`'s `(month, day)` falls inside the declared window (accounting for wraparound), else `"non_compliant"`.
- Both computations wired into `get_record` and `list_records` identically (same pattern as Story 17's `tier_sla`/`risk`), each gaining a `testing_window_path: Path = DEFAULT_TESTING_WINDOW_PATH` keyword parameter mirroring `tiers_path`'s.
- `ledger_core/server.py`'s `_record_to_dict` includes `rto_achieved_pct`, `rpo_achieved_pct`, `testing_window_compliance` -- every read tool that already serializes a `LedgerRecord` exposes them automatically.

**Ask First:**
- Any change to the achieved-percentage formula or window-wraparound logic beyond what's specified above.

**Never:**
- No connector or caller may supply `rto_achieved_pct`, `rpo_achieved_pct`, or `testing_window_compliance` directly -- ledger-core-exclusive.
- No hardcoded artifact_type name -- this computes generically from whatever fields are present on any artifact, the same genericity CAP-2's artifact model already has.
- No change to Story 17's `_compute_tier_and_risk`/`risk` formula, and no dependency on `tier_sla` existing -- this story is fully independent of Stories 17/18.
- No wiring into `ledger_get_dr_readiness_summary` (Story 18) or any other aggregate view -- that's a future story's decision, not this one's.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Recovered within target | `rto_target_minutes=60`, `rto_actual_minutes=45` | `rto_achieved_pct=100.0` (capped) | N/A |
| Recovered slower than target | `rto_target_minutes=70`, `rto_actual_minutes=100` | `rto_achieved_pct=70.0` | N/A |
| Missing actual/target field | Only one of the pair present | `rto_achieved_pct=None` | N/A |
| Non-numeric or non-positive target/actual | `rto_actual_minutes=0`, or a string, or `bool` | `rto_achieved_pct=None` | N/A |
| Test date inside the window | `test_date` within `window_start`..`window_end` | `testing_window_compliance="compliant"` | N/A |
| Test date outside the window | `test_date` outside the range | `testing_window_compliance="non_compliant"` | N/A |
| Window wraps a year boundary | `window_start=11-01`, `window_end=02-28`, `test_date` in December | `testing_window_compliance="compliant"` | N/A |
| Missing `test_date` or `rezops.testing_window.yaml` | Either absent | `testing_window_compliance="unknown"` | Never raises |
| Malformed `rezops.testing_window.yaml` | Not exactly two valid `MM-DD` lines | -- | Raises `TestingWindowFileError` |
| `RawFact` carries a computed field | `fields={"rto_achieved_pct": 90.0, ...}` | -- | Rejected at construction (`LEDGER_ONLY_FIELDS`) |

</frozen-after-approval>

## Code Map

- `ledger_core/projection.py:82` (`load_tiers`), `:166` (`_compute_tier_and_risk`), `:337`/`:524` (`get_record`/`list_records`) -- the exact structural precedent to mirror: a public config loader + a pure per-record compute function + wiring at both call sites
- `shared/ledger_schema/models.py:19-28` (`LEDGER_ONLY_FIELDS`), `:33` (`CONFIDENCE_VALUES`/`RISK_VALUES` pattern), `:143-171` (`LedgerRecord`) -- add the three new fields
- `rezops.tiers.yaml` -- reuse as the config-file precedent (flat, hand-rollable, comment-friendly, fails loudly on malformed input)
- `rezops.testing_window.yaml` -- new: the two-line window declaration
- `ledger_core/server.py:63-81` (`_record_to_dict`) -- add the three new keys
- `tests/test_ledger_core.py` -- existing suite; add coverage for every I/O matrix row above

## Tasks & Acceptance

**Execution:**
- [x] `rezops.testing_window.yaml` -- new config file, `window_start`/`window_end` in `MM-DD` format
- [x] `shared/ledger_schema/models.py` -- add `TESTING_WINDOW_COMPLIANCE_VALUES`, add all three new field names to `LEDGER_ONLY_FIELDS`, add `rto_achieved_pct: float | None`, `rpo_achieved_pct: float | None`, `testing_window_compliance: str = "unknown"` to `LedgerRecord` with `__post_init__` validation
- [x] `ledger_core/projection.py` -- `load_testing_window(testing_window_path)` parser (mirrors `load_tiers`'s missing-file/malformed-file discipline), `_compute_test_achievement(fields)` (RTO/RPO formula) and `_compute_testing_window_compliance(fields, window)` (wraparound-aware date comparison), wired into both `get_record` and `list_records`
- [x] `ledger_core/server.py` -- `_record_to_dict` includes the three new keys
- [x] `tests/test_ledger_core.py` -- full I/O matrix coverage

**Acceptance Criteria:**
- Given the full test suite, when `uv run pytest` runs, then all tests pass.
- Given `rto_target_minutes=70`/`rto_actual_minutes=100` on any artifact, when `ledger_get_record` is called, then `rto_achieved_pct=70.0`.
- Given a `RawFact` with `fields={"testing_window_compliance": "compliant"}`, when constructed, then `SchemaValidationError` is raised before anything is appended to the log.
- Given a `test_date` in December and a window declared `11-01`..`02-28`, when `ledger_get_record` is called, then `testing_window_compliance="compliant"` -- proving the wraparound case works.

## Design Notes

The 100%-cap on achieved percentage is this story's own explicit choice: recovering in half the allotted time is still "fully achieved," not "200% achieved" -- there is no reward signal here, only a shortfall signal. `MM-DD` (no year) for the window mirrors the real-world "annual testing window" concept from the reference design this capability was shaped against -- a fixed calendar range that recurs every year, not a one-time date range.

## Spec Change Log

## Verification

**Commands:**
- `uv sync` -- expected: resolves without error -- ran, resolved with no changes
- `uv run pytest -v` -- expected: all tests pass, including every prior story's -- ran, 802 passed (up from 786 baseline)
- Manually construct one artifact per I/O matrix row and confirm the expected `rto_achieved_pct`/`rpo_achieved_pct`/`testing_window_compliance` values -- confirmed for all 10 rows, including both wraparound directions

Adversarial review ran (3 lenses). Findings triaged: 7 patched, 2 lower-priority gaps logged to `deferred-work.md`, 5 other findings checked and rejected as matching pre-existing precedent or expected behavior:
1. Missing `[0,100]` range validation on `rto_achieved_pct`/`rpo_achieved_pct` (2 reviewers converged) -- added, matching every other guarded `LedgerRecord` field.
2. Unguarded `inf`/`nan` inputs to the achieved-pct formula (2 reviewers converged) -- a `math.isfinite` check now rejects them, closing a false-`100.0` result for an undefined `inf/inf` ratio.
3. Missing test coverage: empty/comment-only config, single-day window -- both added.
4. Story 18's deliberate exclusion of these new fields was undocumented in `dr_readiness.py` itself -- corrected.
5. `get_record`/`list_records` docstrings didn't mention `TestingWindowFileError` -- corrected.
6. `README.md` was never updated for the new config file or fields -- corrected.

**Post-fix-round correction (caught in my own independent verification, not by the 3-lens review):** patch 3's fix introduced a real deviation from this story's own frozen spec -- it special-cased an empty/comment-only `rezops.testing_window.yaml` to resolve `None` (silently equivalent to a missing file) rather than raising `TestingWindowFileError`. The frozen I/O matrix is explicit: a file that is "not exactly two valid `MM-DD` lines" is malformed and fails loudly, with no carve-out for zero declared lines. Reverted the special case and rewrote both affected tests to assert the correct (raising) behavior -- confirmed against the full suite (802 passed) after the correction, so this is my own fix-dispatch imprecision, not the implementer inventing scope.

Rejected findings (checked, not real or out of scope): `strptime`'s non-zero-padded-date leniency (more permissive, not incorrect); leading-whitespace-before-declaration parsing (confirmed to exactly match Story 17's existing parser behavior); the leap-day boundary asymmetry (correct given the literal declared boundary); the config's placeholder default values (matches every other shipped config's sample-data precedent); `list_records`' all-or-nothing failure mode on a malformed config (the finding itself acknowledges this mirrors `load_tiers`'s pre-existing behavior).

## Suggested Review Order

**The two computations (independent of each other and of Stories 17/18)**

- `_achieved_pct`: the RTO/RPO formula, now with the finiteness guard.
  [`projection.py:296`](../../../../ledger_core/projection.py#L296)

- `_compute_testing_window_compliance`: the wraparound-aware date comparison.
  [`projection.py:311`](../../../../ledger_core/projection.py#L311)

- The config parser -- fails loudly on anything short of exactly two valid lines, including the post-review-round correction (an empty file is malformed, not equivalent to missing).
  [`projection.py:190`](../../../../ledger_core/projection.py#L190)

**The wraparound cases (the one genuinely tricky piece of logic here)**

- December, inside an `11-01..02-28` window.
  [`test_ledger_core.py:4949`](../../../../tests/test_ledger_core.py#L4949)

- January, same window, still inside.
  [`test_ledger_core.py:4960`](../../../../tests/test_ledger_core.py#L4960)

- Summer, same window, correctly outside.
  [`test_ledger_core.py:4970`](../../../../tests/test_ledger_core.py#L4970)

**Fix-round additions (peripheral, but worth a look)**

- The out-of-range `LedgerRecord` validation the review caught (2 reviewers converged).
  [`test_ledger_core.py:254`](../../../../tests/test_ledger_core.py#L254)

- The `inf`/`nan` regression test.
  [`test_ledger_core.py:4916`](../../../../tests/test_ledger_core.py#L4916)
