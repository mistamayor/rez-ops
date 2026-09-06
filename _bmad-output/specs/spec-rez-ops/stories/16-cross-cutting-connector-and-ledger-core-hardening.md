---
title: 'Cross-cutting connector and ledger-core hardening'
type: 'refactor'
created: '2026-09-05'
status: 'done'
review_loop_iteration: 0
baseline_commit: 'd81ae67343016f795ad10d890845c3e67411f5e0'
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/specs/spec-rez-ops/SPEC.md'
  - '{project-root}/_bmad-output/implementation-artifacts/deferred-work.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `deferred-work.md` has accumulated ~40 review-surfaced gaps across Stories 1-15. Four are converged (≥2 independent reviewers or ≥3 connectors), well-evidenced, and cheaply fixable: a non-injective `_build_source` join (6 connectors), an unstripped credential (5 connectors), a non-ASCII-credential crash risk (5 connectors), and `get_record` not degrading gracefully on a corrupted log (ledger_core) -- inconsistent with `list_records`/`get_coverage_map`'s existing AD-8 treatment of the same failure.

**Approach:** Fix exactly these 4, each with a regression test. No new capability -- hardens CAP-1/CAP-2/CAP-3's existing implementations. The user explicitly scoped this to these 4; the other ~35 deferred items stay deferred as-is.

## Boundaries & Constraints

**Always:**
- `_build_source` in each of `git_repo`, `ticketing`, `calendar_google`, `cmdb`, `google_drive`, `sharepoint`: sanitize each identifier segment individually with the existing `_SOURCE_UNSAFE_CHARS_RE` regex, THEN join with `"/"` -- not sanitize-the-whole-joined-string-at-once (today's pattern). Since `/` is itself outside the allowed charset, it can never survive inside an individually-sanitized segment, so joining afterward with `/` is guaranteed injective. Keep the same `"prefix:seg1/seg2/..."` visible shape.
- `_read_credential`/`_read_credentials` in `ticketing`, `calendar_google`, `cmdb`, `google_drive`, `sharepoint`: return the token `.strip()`ped, and reject a non-ASCII token (`not token.isascii()`) the same way a control character is already rejected -- a typed error, before any HTTP request, using each connector's own existing error class.
- `ledger_core/projection.py`'s `get_record`: catch `LogFormatError` around its `_fold_events_by_artifact` call and return the same empty-fields/`confidence="unknown"`/`last_verified=None`/`escalation_owner=None` record it already returns for a never-observed artifact_id -- extending its own documented "never raises for a missing artifact" invariant to a corrupted log too.
- Once `get_record` itself never raises `LogFormatError`, remove the now-redundant `try/except LogFormatError` around its call in `action_proposals.create_action_proposal` (~line 539-543) -- simplification only, `tier_sla_known` stays behaviorally identical.
- Update the 3 existing tests in `tests/test_ledger_core.py` that currently assert `get_record` raises/propagates `LogFormatError` (lines ~368-389, ~395-409, ~412-426) -- this is a deliberate reversal of a prior tested decision (confirmed with the user), not an oversight; those tests must be changed to assert the new fail-open behavior, not deleted silently.

**Ask First:**
- Any other existing test found to assert old `_build_source`/credential/`get_record` behavior beyond the ones named above.

**Never:**
- No change to any connector's or ledger-core's public tool signature, return shape, or any other behavior outside these 4 fixes.
- No touching any of the ~35 other deferred-work.md entries.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Source collision inputs | Two distinct multi-identifier inputs that collide under today's join-then-sanitize (e.g. `("a/b","c")` vs `("a","b/c")`) | Produce two DIFFERENT `source` strings | N/A |
| Credential with incidental whitespace | Token env var set to `"  realtoken  "` | Stored/sent value is `"realtoken"`, not the padded original | N/A |
| Non-ASCII credential | Token contains e.g. `"é"` or an emoji | Rejected before any HTTP request | Raises the connector's existing typed credential error |
| `get_record` against a corrupted log | Artifact-type log has an unparseable line | Empty-fields, `confidence="unknown"` record for the requested artifact_id | N/A (no longer raises) |

</frozen-after-approval>

## Code Map

- `connectors/git_repo/server.py:46,190-193` -- `_build_source(repo_path, commit_sha)`, join-then-sanitize -> per-segment-then-join
- `connectors/ticketing/server.py:45,175-198,201-203` -- `_read_credentials` (tuple return, strip token only), `_build_source(instance_url, table, sys_id)`
- `connectors/calendar_google/server.py:45,136-164,153-155` -- `_read_credential`, `_build_source(calendar_id, event_id)`
- `connectors/cmdb/server.py:59,109,240-271,274-276` -- `_read_credentials` (tuple return, strip token only), `_build_source(instance_url, table, sys_id)`
- `connectors/google_drive/server.py:48,63,145-159,162-164` -- `_read_credential`, `_build_source(file_id)` (single-identifier, no join risk, but strip/non-ASCII fix still applies)
- `connectors/sharepoint/server.py` (mirrors google_drive's line shape) -- `_read_credential`, `_build_source(drive_id, item_id)`
- `ledger_core/projection.py:145-194` -- `get_record`, add the `try/except LogFormatError` fail-open
- `ledger_core/action_proposals.py:539-543` -- remove the now-redundant try/except around its `get_record` call
- `tests/test_ledger_core.py:368-389,395-409,412-426` -- 3 existing tests to update for the new fail-open behavior, plus one new corrupted-log-via-`get_record` test mirroring `list_records`'s existing sentinel-pattern tests
- `tests/test_git_connector.py`, `tests/test_ticketing_connector.py`, `tests/test_calendar_connector.py`, `tests/test_cmdb_connector.py`, `tests/test_google_drive_connector.py`, `tests/test_sharepoint_connector.py` -- one new source-non-collision test each (two colliding-shaped inputs -> distinct `source`); the 5 credential-bearing ones also get one new stripped-credential test and one new non-ASCII-credential test each

## Tasks & Acceptance

**Execution:**
- [x] Fix `_build_source` in all 6 connectors (per-segment sanitize, then join) + one non-collision test each
- [x] Fix `_read_credential`/`_read_credentials` in all 5 credential-bearing connectors (strip + reject non-ASCII) + one stripped-value test and one non-ASCII-rejection test each
- [x] Fix `ledger_core/projection.py`'s `get_record` (fail-open on `LogFormatError`) + update the 3 existing tests + add one new corrupted-log test
- [x] Simplify `ledger_core/action_proposals.py`'s now-redundant try/except around its `get_record` call

**Acceptance Criteria:**
- Given the full test suite, when `uv run pytest` runs, then all tests pass (658 existing + new regression tests).
- Given two multi-identifier inputs that collide under the old join-then-sanitize scheme, when each connector's `_build_source` (or equivalent) runs, then it produces two different `source` strings.
- Given a credential env var with leading/trailing whitespace, when any of the 5 connectors reads it, then the value used in the request is stripped.
- Given a non-ASCII credential, when any of the 5 connectors validates it, then a typed error is raised before any HTTP request.
- Given a corrupted artifact-type log, when `ledger_get_record`/`get_record` is called for an artifact in that type, then it returns an empty-fields, unknown-confidence record rather than raising or erroring.

## Design Notes

`_build_source`'s fix must NOT change the visible `"prefix:seg1/seg2"` shape for already-clean inputs (e.g. `git_repo`'s existing tests with normal repo paths and commit SHAs must still pass unchanged) -- only inputs that previously collided should now differ. `get_record`'s fix reuses `get_record`'s own existing "no facts recorded" return shape verbatim (same fields, same values) -- a corrupted log is treated exactly like "nothing observed yet" for this specific tool, trading distinguishability for consistency with AD-8's graceful-degradation bar, per the user's explicit confirmation to reverse the prior design choice.

## Spec Change Log

- **Unplanned but required change, flagged for human confirmation -- CONFIRMED by user.** `shared/ledger_schema/models.py`'s `_SOURCE_RE` (`RawFact.source`'s charset) had to be widened from `^[A-Za-z0-9_:-]+$` to `^[A-Za-z0-9_:/-]+$` (adding `/`). This file is outside the Code Map and is documented elsewhere as "read-only for this story," but the fix as specified (sanitize each segment individually, THEN join with a literal `"/"`) is mathematically impossible to implement without it: any scheme that sweeps the final joined string a second time (to strip the `/` back out and satisfy the old charset) collapses the join separator and in-segment characters back together, exactly reproducing the original collision bug. A literal `/` must therefore survive, unswept, in the final `source` value for the six connectors' fixes to be genuinely injective. Verified safe (independently, not just per the implementer's own claim): `source` is never used to build a filesystem path or log filename (unlike `artifact_type`/`artifact_id`, where `_IDENTIFIER_RE` excludes `/` for exactly that reason -- confirmed unchanged); every `.source` consumer in the codebase was grepped and each treats it as an opaque string (`ledger_core.log`'s `_LINE_RE`, which splits on whitespace via `\S+`, not `/`; `evidence.py`'s equality comparisons; every connector's dict/JSON serialization). One existing test (`test_rawfact_rejects_invalid_charset_in_identifiers`'s `("source", "bad/source")` case in `tests/test_ledger_core.py`) asserted the old behavior and was updated (not deleted) to reflect that `/` is now valid in `source`; a new `test_rawfact_accepts_slash_in_source` test was added. User confirmed via explicit approval prompt.

## Verification

**Commands:**
- `uv sync` -- expected: resolves without error -- ran, resolved with no changes
- `uv run pytest -v` -- expected: all tests pass, including every prior story's, plus new regression tests -- ran, 682 passed (up from 658 baseline)
- Manually construct one colliding-shaped input pair per multi-identifier connector and confirm distinct `source` values -- confirmed for all 6

Adversarial review ran (3 lenses; blind-hunter needed 2 retries after a system-sleep interruption). Findings triaged: 3 patched and independently re-verified, 2 pre-existing gaps logged to `deferred-work.md` (one -- ticketing's missing control-char check -- was then incidentally resolved anyway while fixing patch 1, and the deferred-work.md entry was annotated RESOLVED rather than left stale), 8 other findings checked and rejected as not real or already deliberately decided:
1. A validation-order bug: the new `.strip()` ran before the control-char/non-ASCII checks in all 5 credential-bearing connectors, letting an edge-positioned control character slip through silently instead of being rejected. Fixed by checking the raw token first, stripping only the returned value. Ticketing had no control-char check at all prior to this fix -- added uniformly here rather than left inconsistent.
2. Docstring line-wrap inconsistency in 3 of 4 files, rewrapped to match `cmdb`'s style.
3. `_build_source` injectivity tests for `cmdb`/`ticketing` only covered one segment boundary -- added a second test covering the `instance_url`/`table` boundary.

Rejected findings (checked, not real or out of scope): git's `@`→`/` separator shape change (verified Story 2's own spec already documented the literal `@` as unreachable/always-swept, no live contract requires it); a source-format migration/compat concern (verified `source` is write-once/read-verbatim everywhere, never recomputed and compared against log history); `get_record`'s silent fail-open (verified this non-logging characteristic already existed in the try/except this story removed); non-ASCII-rejection rollout risk and "only documented in test docstrings" (both re-litigate a decision already made deliberately with the user's explicit sign-off, the latter also factually incomplete -- it's documented in this spec's Design Notes and `projection.py`'s own docstring too); a stale `LogFormatError` reference in `action_proposals.py` (grepped, confirmed clean); `_SOURCE_RE`'s docstring claim about no future path-like use (non-actionable, already caveated); a redundant `.strip()` call (folded into patch 1's reordering).

## Suggested Review Order

**Schema widening (the flagged, user-confirmed change -- review this first)**

- The one line that makes everything else possible: `/` added to `source`'s allowed charset, with the full injectivity reasoning inline.
  [`models.py:68`](../../../../shared/ledger_schema/models.py#L68)

**`_build_source` injectivity fix (6 connectors, same pattern)**

- The canonical shape: sanitize each segment individually, then join with a literal `/` -- read this one first, the other 5 mirror it.
  [`git_repo/server.py:192`](../../../../connectors/git_repo/server.py#L192)

- Three-segment variant: same pattern, one more segment to sanitize independently.
  [`cmdb/server.py:288`](../../../../connectors/cmdb/server.py#L288)

- Three-segment variant, ticketing's own copy.
  [`ticketing/server.py:229`](../../../../connectors/ticketing/server.py#L229)

- Two-segment variant.
  [`calendar_google/server.py:169`](../../../../connectors/calendar_google/server.py#L169)

- Two-segment variant.
  [`sharepoint/server.py:182`](../../../../connectors/sharepoint/server.py#L182)

- Single-identifier case -- no join risk, included only for the credential fix below.
  [`google_drive/server.py:170`](../../../../connectors/google_drive/server.py#L170)

**Credential hardening: strip + non-ASCII rejection, in the corrected order (5 connectors)**

- The corrected check order after the fix-round patch: control-char and non-ASCII checked on the raw token, stripped only on return.
  [`calendar_google/server.py:145`](../../../../connectors/calendar_google/server.py#L145)

- Tuple-returning variant (`instance_url` + token) -- strips only the token, not the URL.
  [`cmdb/server.py:248`](../../../../connectors/cmdb/server.py#L248)

- Tuple-returning variant -- this connector gained its control-char check for the first time in this same patch round.
  [`ticketing/server.py:189`](../../../../connectors/ticketing/server.py#L189)

- Single-credential variant.
  [`google_drive/server.py:146`](../../../../connectors/google_drive/server.py#L146)

- Single-credential variant.
  [`sharepoint/server.py:158`](../../../../connectors/sharepoint/server.py#L158)

**`get_record` fail-open (ledger_core)**

- The reversed design decision: `LogFormatError` now degrades to the same empty record `get_record` already returns for a never-observed artifact.
  [`projection.py:145`](../../../../ledger_core/projection.py#L145)

- The now-simplified call site: the redundant try/except this fix made unnecessary.
  [`action_proposals.py:540`](../../../../ledger_core/action_proposals.py#L540)

**Tests (peripheral)**

- The fix-round regression test proving a trailing control character is still rejected, not silently stripped away.
  [`test_calendar_google_connector.py:378`](../../../../tests/test_calendar_google_connector.py#L378)

- The 3 existing `get_record` tests updated from asserting a raise to asserting the new fail-open behavior.
  [`test_ledger_core.py:368`](../../../../tests/test_ledger_core.py#L368)
