---
title: 'Tier assignment & DR risk classification'
type: 'feature'
created: '2026-09-06'
status: 'done'
review_loop_iteration: 0
baseline_commit: '2442d3715c11f2ed0a9d8e089cd797cbae13bedc'
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/specs/spec-rez-ops/SPEC.md'
  - '{project-root}/ledger_core/action_proposals.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `LedgerRecord.tier_sla`/`expiry_rule` have existed in the schema since Story 1 but every story since has left them `None` -- "no tiering data source exists yet" is `get_record`'s own documented reality. This silently blocks `action_proposals.py`'s policy engine: `_compute_policy_decision`'s `automatic` branch requires `tier_sla_known=True`, which is always `False` against real data today.

**Approach:** A new git-tracked config, `rezops.tiers.yaml`, declares which tier an artifact belongs to and each tier's expiry SLA in days -- the same declare-in-config/ledger-core-computes-the-derived-value pattern `rezops.policy.yaml` already established (AD-12). `ledger_core.projection` alone computes `tier_sla`, `expiry_rule`, and a new `risk` field (`high`/`medium`/`low`/`unknown`) from tier x freshness (`last_verified` against the tier's expiry window) x `confidence` -- never accepted as connector/caller input.

## Boundaries & Constraints

**Always:**
- `rezops.tiers.yaml` (repo root) has two entry kinds, one per line, mirroring `rezops.policy.yaml`'s flat, hand-rollable-parser style (no PyYAML dependency): `tier.<name>.expiry_days: <int>` declares the tier vocabulary; `assign.<artifact_type>/<artifact_id>: <tier name>` assigns exactly one declared tier to one artifact. An `assign` line naming an undeclared tier is a malformed-config error (fail loudly, matching `_load_policy`'s discipline), not silently ignored.
- Missing `rezops.tiers.yaml` returns `{}` (no tiers declared) -- never raises -- matching `_load_policy`'s existing missing-file behavior.
- `risk` is a new `LedgerRecord` field (`shared/ledger_schema/models.py`), values restricted to exactly `{"high", "medium", "low", "unknown"}` (new `RISK_VALUES`, validated in `__post_init__` the same way `CONFIDENCE_VALUES` already is), added to `LEDGER_ONLY_FIELDS` (a `RawFact` may never carry a `risk` key), default `"unknown"`.
- Risk formula, computed in `ledger_core/projection.py`, applied identically wherever `get_record`/`list_records` already compute `escalation_owner`/`confidence` per record:
  1. No declared tier for this artifact (no `assign` entry) -> `risk = "unknown"`.
  2. Declared tier exists but `confidence != "agent-verified"` (i.e. `last_verified is None`) -> `risk = "unknown"` -- can't assess freshness with nothing observed.
  3. Declared tier exists and `confidence == "agent-verified"`: let `days_since = (now - last_verified).days` and `expiry_days` = the tier's declared SLA. `days_since > expiry_days` -> `"high"`; `days_since > 0.75 * expiry_days` -> `"medium"`; else -> `"low"`.
- `tier_sla` is set to the declared tier name (e.g. `"platinum"`) whenever an `assign` entry exists, `None` otherwise. `expiry_rule` is set to `f"{expiry_days} days"` (e.g. `"90 days"`) under the same condition, `None` otherwise.
- `ledger_core/server.py`'s `_record_to_dict` includes the new `risk` key -- every read tool that already serializes a `LedgerRecord` (`ledger_get_record`, `ledger_list_records`, `ledger_get_briefing`) exposes it automatically, no per-tool change needed beyond that one shared function.
- `action_proposals.py`'s `_compute_policy_decision` docstring (and the inline comment at its `tier_sla_known = record.tier_sla is not None` call site) currently assert `tier_sla_known` is always `False` against real data -- both must be corrected since this story makes that claim false. No other change to `action_proposals.py`: its existing `record.tier_sla is not None` check already does the right thing once `tier_sla` is populated.

**Ask First:**
- Any tier-vocabulary or risk-threshold change beyond what's specified above.

**Never:**
- No connector or caller may supply `tier_sla`, `expiry_rule`, or `risk` directly -- ledger-core-exclusive, same constraint class as `EvidenceBundle.confidence`/`ActionProposal.policy_decision`.
- No automatic tier discovery from a CMDB field or any live system -- tier assignment is config-only (SPEC non-goal).
- No change to `get_coverage_map`'s existing per-type confidence tally -- an aggregate risk/RAG view is Story 18's job, not this one's.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Fresh, tiered artifact | Declared tier, `last_verified` within 75% of expiry window | `risk="low"`, `tier_sla`/`expiry_rule` populated | N/A |
| Approaching expiry | Declared tier, `last_verified` between 75% and 100% of expiry window | `risk="medium"` | N/A |
| Past expiry | Declared tier, `last_verified` beyond expiry window | `risk="high"` | N/A |
| No declared tier | No `assign` entry for this artifact | `risk="unknown"`, `tier_sla`/`expiry_rule` both `None` | N/A |
| Declared tier, never observed | `assign` entry exists, no fact ever recorded (`last_verified is None`) | `risk="unknown"` | N/A |
| Missing `rezops.tiers.yaml` | File doesn't exist | Every artifact resolves `risk="unknown"` | Never raises |
| Malformed config | An `assign` line names a tier with no matching `tier.<name>.expiry_days` declaration | -- | Raises a typed, `PolicyFileError`-equivalent config error |
| `RawFact` carries a `risk` field | Connector/caller-supplied `fields={"risk": "high", ...}` | -- | Rejected at `RawFact` construction (`LEDGER_ONLY_FIELDS`) |

</frozen-after-approval>

## Code Map

- `rezops.policy.yaml` -- reuse as the exact config-file precedent (flat, hand-rollable, comment-friendly)
- `ledger_core/action_proposals.py:228-` (`_load_policy`) -- reuse as the parser-style template; `:125` (`_POLICY_ACTION_HEADER_RE`) for the header-line regex pattern; `:304-323` (`_compute_policy_decision`) and `:537-541` -- the stale docstring/comment to correct
- `shared/ledger_schema/models.py:19-28` (`LEDGER_ONLY_FIELDS`), `:33` (`CONFIDENCE_VALUES` -- pattern for the new `RISK_VALUES`), `:143-171` (`LedgerRecord`) -- add the `risk` field
- `ledger_core/projection.py:53-101` (`_OWNERSHIP_FIELD_PRIORITY`/`_compute_escalation_owner`/`_compute_confidence` -- the exact per-record-computation pattern to mirror), `:145-194` (`get_record`), `:302-` (`list_records`) -- both need the new tier/risk computation wired in identically
- `ledger_core/server.py:63-81` (`_record_to_dict`) -- add `"risk"` to the shared dict shape
- `rezops.tiers.yaml` -- new: the tier vocabulary + assignment config
- `tests/test_ledger_core.py` -- existing suite; add coverage for every I/O matrix row above

## Tasks & Acceptance

**Execution:**
- [x] `rezops.tiers.yaml` -- new config file with at least 2 declared tiers and 2+ assignments, documented inline like `rezops.policy.yaml`
- [x] `shared/ledger_schema/models.py` -- add `RISK_VALUES`, add `"risk"` to `LEDGER_ONLY_FIELDS`, add `risk: str = "unknown"` to `LedgerRecord` with `__post_init__` validation
- [x] `ledger_core/projection.py` -- `_load_tiers(tiers_path)` parser (mirrors `_load_policy`'s missing-file/malformed-file discipline), tier/risk computation wired into both `get_record` and `list_records`
- [x] `ledger_core/server.py` -- `_record_to_dict` includes `risk`
- [x] `ledger_core/action_proposals.py` -- correct the stale tier_sla-always-False references (module docstring, `_compute_policy_decision` docstring, inline comment at the call site -- all three, not just the two the spec named), no other change
- [x] `tests/test_ledger_core.py` -- full I/O matrix coverage, plus one integration test proving `create_action_proposal`'s `tier_sla_known` becomes `True` for a target with a declared tier and fresh `last_verified` (Story 13's dormant code path actually firing)

**Acceptance Criteria:**
- Given the full test suite, when `uv run pytest` runs, then all tests pass.
- Given an artifact with a declared tier and `last_verified` past its expiry window, when `ledger_get_record` is called, then `risk="high"` and `tier_sla`/`expiry_rule` are both populated.
- Given a `RawFact` with `fields={"risk": "high"}`, when constructed, then `SchemaValidationError` is raised before anything is appended to the log.
- Given an artifact with a declared tier, fresh `last_verified`, and `min_confidence=1.0`, citing a low-impact action, when `create_action_proposal` evaluates it, then `policy_decision="automatic"` -- proving the previously-dormant branch now fires.

## Design Notes

The 75%-of-expiry-window threshold for `"medium"` is this story's own simple, defensible choice (mirrors Story 3's "agent-verified iff at least one field observed" precedent for keeping a first derivation rule simple rather than over-engineered) -- not derived from any external source, documented here so a future story can revisit it deliberately rather than archaeology-dig the constant. `tier_sla` holds the tier *name*, not the day-count, so a human reading a `LedgerRecord` sees "platinum" (meaningful) rather than "90" (needs the config to interpret) -- `expiry_rule`'s `"90 days"` string carries the actual number.

## Spec Change Log

## Verification

**Commands:**
- `uv sync` -- expected: resolves without error -- ran, resolved with no changes
- `uv run pytest -v` -- expected: all tests pass, including every prior story's -- ran, 710 passed (up from 705 baseline)
- Manually construct one artifact per I/O matrix row and confirm the expected `risk`/`tier_sla`/`expiry_rule` values -- confirmed for all 8 rows

Adversarial review ran (3 lenses). Findings triaged: 10 patched and independently re-verified, 4 lower-priority gaps logged to `deferred-work.md`, 4 other findings checked and rejected as matching pre-existing precedent or the frozen spec's own explicit intent:
1. Unhandled `strptime` ValueError on a malformed `last_verified` -- now degrades to `risk="unknown"` (AD-8) rather than raising.
2. `create_action_proposal` had no `tiers_path` override, contradicting `DEFAULT_TIERS_PATH`'s own stated testing design -- added, and the flagship acceptance test now uses an isolated fixture instead of the real committed config.
3. `ARCHITECTURE-SPINE.md` was stale (wrong config filename in two places, a Deferred item this story resolves) -- corrected.
4. The corrupted-log sentinel's `tier_sla`/`expiry_rule`/`risk` wiring was untested -- a demonstrated regression gap (dropping the wiring produced byte-identical test output). Added a genuine regression guard.
5. `_TIMESTAMP_FORMAT` was a copy-pasted duplicate of `log.py`'s private literal -- now a shared, exported constant.
6. `confidence == "manual"` collapsed to the same risk as never-observed -- now treated as verified-enough-to-assess-freshness alongside `"agent-verified"`.
7. The flagship acceptance test didn't assert the resulting `risk` value -- added.
8. Missing exact-boundary tests (`days_since == expiry_days`, exactly the 75% threshold) -- added, locking in the documented `>` semantics.
9. `briefing.py`'s docstring claimed no tier/SLA data exists -- corrected to note it now exists but `Briefing` still deliberately doesn't rank by it.
10. Added a docstring note that `risk`, unlike every other computed field, depends on wall-clock time.

## Suggested Review Order

**The risk formula (the core of this story)**

- The frozen rule itself: no tier → unknown; tier but unverified → unknown; then days-since vs. expiry at the 75%/100% thresholds, now with the malformed-timestamp fail-open path.
  [`projection.py:166`](../../../../ledger_core/projection.py#L166)

- The config parser it depends on: fails loudly on a malformed/undeclared-tier config, never silently ignores.
  [`projection.py:82`](../../../../ledger_core/projection.py#L82)

- The declared vocabulary and assignments this story ships with.
  [`rezops.tiers.yaml:23`](../../../../rezops.tiers.yaml#L23)

**Wiring into the read paths**

- `get_record`: the single-artifact path, now with the wall-clock-dependency note.
  [`projection.py:337`](../../../../ledger_core/projection.py#L337)

- `list_records`: the same computation applied per record, including the corrupted-log sentinel.
  [`projection.py:524`](../../../../ledger_core/projection.py#L524)

**The integration this story unblocks**

- `create_action_proposal`'s new `tiers_path` parameter -- the fix-round patch that makes the flagship test independent of the real committed config.
  [`action_proposals.py:438`](../../../../ledger_core/action_proposals.py#L438)

- The acceptance test proving Story 13's dormant `automatic` branch actually fires now.
  [`test_ledger_core.py:4169`](../../../../tests/test_ledger_core.py#L4169)

**Fix-round regression guards (peripheral, but worth a look)**

- The sentinel-wiring regression guard verification-gap review caught -- a genuine "would silently break" test.
  [`test_ledger_core.py:1276`](../../../../tests/test_ledger_core.py#L1276)

- The two exact-boundary tests locking in the `>` (not `>=`) semantics.
  [`test_ledger_core.py:3882`](../../../../tests/test_ledger_core.py#L3882)
