"""Pure projection: replay an artifact-type event log into current LedgerRecord state.

AD-3: current state is always a pure, recomputed projection over the
append-only log -- never hand-edited, never cached in memory across calls.
Every call to get_record, get_coverage_map, or list_records re-reads the
log(s) from disk.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ledger_core.log import (
    DEFAULT_LEDGER_DATA_DIR,
    RAWFACT_EVENT_TYPE,
    TIMESTAMP_FORMAT,
    LogFormatError,
    read_events,
)
from shared.ledger_schema import LedgerRecord

#: Suffix every artifact-type event log file uses (ledger_core.log._log_path).
_LOG_SUFFIX = ".log.md"

#: Sentinel confidence-like key `get_coverage_map` reports for an
#: artifact_type whose log fails to parse (LogFormatError), instead of
#: either aborting the whole coverage computation or silently dropping that
#: type. This makes the problem visible in the result itself (AD-8:
#: graceful degradation -- one bad log must not blind the whole coverage
#: view for every other, healthy artifact type).
LOG_FORMAT_ERROR_MARKER = "error:log_format_error"

#: Sentinel `artifact_id` `list_records` uses for the one synthetic record it
#: emits in place of a corrupted artifact_type's real artifacts (see
#: `list_records`'s docstring). Distinct from any real artifact_id a
#: connector could plausibly write: it is reserved-looking (leading `_`)
#: purely by convention here -- `artifact_id`s are never excluded by that
#: convention the way `artifact_type` filenames are, so this is just a
#: human-legible marker, not a second exclusion mechanism.
LOG_FORMAT_ERROR_ARTIFACT_ID = "_log_format_error"

#: Repo-root, git-tracked tier vocabulary + assignment config (Story 17,
#: CAP-11) -- mirrors `ledger_core.action_proposals.DEFAULT_POLICY_PATH`'s
#: role for `rezops.policy.yaml`. Callers may override for testing so no
#: test ever depends on -- or mutates -- the real, git-committed
#: `rezops.tiers.yaml`.
DEFAULT_TIERS_PATH = Path("rezops.tiers.yaml")

#: Repo-root, git-tracked annual DR testing-window config (Story 19,
#: CAP-12) -- mirrors `DEFAULT_TIERS_PATH`'s role for `rezops.tiers.yaml`.
#: Callers may override for testing so no test ever depends on -- or
#: mutates -- the real, git-committed `rezops.testing_window.yaml`.
DEFAULT_TESTING_WINDOW_PATH = Path("rezops.testing_window.yaml")

#: The medium-risk threshold as a fraction of a tier's `expiry_days`: past
#: this fraction (but not yet past the full window) is "medium" (Story 17's
#: own simple, defensible choice -- see the story's Design Notes; not
#: derived from any external source).
_MEDIUM_RISK_THRESHOLD_FRACTION = 0.75

#: A `tier.<name>.expiry_days: <int>` declaration line in `rezops.tiers.yaml`.
_TIER_DECLARATION_RE = re.compile(r"^tier\.([A-Za-z0-9_-]+)\.expiry_days:\s*(\S+)\s*$")

#: An `assign.<artifact_type>/<artifact_id>: <tier name>` assignment line in
#: `rezops.tiers.yaml`. `artifact_type`/`artifact_id` reuse the same
#: identifier charset every other component in this project enforces
#: (`shared.ledger_schema.models._IDENTIFIER_RE`, mirrored -- not imported --
#: the same way `action_proposals.py` already mirrors it for its own
#: `_IDENTIFIER_RE`).
_TIER_ASSIGNMENT_RE = re.compile(
    r"^assign\.([A-Za-z0-9_-]+)/([A-Za-z0-9_-]+):\s*(\S+)\s*$"
)

#: A `window_start: MM-DD` or `window_end: MM-DD` declaration line in
#: `rezops.testing_window.yaml` (Story 19, CAP-12).
_TESTING_WINDOW_LINE_RE = re.compile(r"^window_(start|end):\s*(\d{2})-(\d{2})\s*$")

#: `test_date` RawFact field format (Story 19, CAP-12) -- an ISO `YYYY-MM-DD`
#: string, parsed with `datetime.strptime` against this exact format.
_TEST_DATE_FORMAT = "%Y-%m-%d"


class TiersFileError(ValueError):
    """Raised when `rezops.tiers.yaml` can't be parsed into the expected shape.

    A config-file problem, not a caller-input problem -- mirrors
    `ledger_core.action_proposals.PolicyFileError`: fails loudly rather than
    silently letting a malformed declaration, or an `assign` line naming an
    undeclared tier, through.
    """


def load_tiers(tiers_path: Path) -> tuple[dict[str, int], dict[tuple[str, str], str]]:
    """Parse `rezops.tiers.yaml` into `(tiers, assignments)`.

    `tiers` maps a declared tier name to its `expiry_days` (a positive int).
    `assignments` maps `(artifact_type, artifact_id)` to the tier name
    assigned to that one artifact. A hand-rolled parser for a deliberately
    minimal, flat format -- mirrors `action_proposals._load_policy`'s own
    "no PyYAML dependency" discipline: one `tier.<name>.expiry_days: <int>`
    or `assign.<artifact_type>/<artifact_id>: <tier name>` line at a time,
    blank lines and `#`-prefixed comment lines ignored anywhere.

    Returns `({}, {})` -- never raises -- if `tiers_path` doesn't exist: no
    tiers are declared, so every artifact correctly resolves `risk="unknown"`
    rather than this function crashing on a config file that hasn't been
    created yet (mirrors `_load_policy`'s identical missing-file behavior).

    Raises `TiersFileError` -- fails loudly, never silently ignored -- for: a
    duplicate `tier.<name>.expiry_days` declaration; a non-integer or
    non-positive `expiry_days`; a duplicate `assign` entry for the same
    artifact; an unparseable line; or an `assign` line naming a tier with no
    matching `tier.<name>.expiry_days` declaration (checked only after the
    whole file is read, so a tier declared later in the file is still
    honored regardless of line order).
    """
    if not tiers_path.exists():
        return {}, {}

    text = tiers_path.read_text(encoding="utf-8")
    tiers: dict[str, int] = {}
    assignments: dict[tuple[str, str], str] = {}

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        tier_match = _TIER_DECLARATION_RE.match(line)
        if tier_match:
            name, days_text = tier_match.group(1), tier_match.group(2)
            if name in tiers:
                raise TiersFileError(
                    f"{tiers_path}:{lineno}: duplicate tier declaration {name!r}"
                )
            try:
                days = int(days_text)
            except ValueError as exc:
                raise TiersFileError(
                    f"{tiers_path}:{lineno}: tier {name!r} expiry_days must be a "
                    f"whole number of days; got {days_text!r}"
                ) from exc
            if days <= 0:
                raise TiersFileError(
                    f"{tiers_path}:{lineno}: tier {name!r} expiry_days must be "
                    f"positive; got {days}"
                )
            tiers[name] = days
            continue

        assign_match = _TIER_ASSIGNMENT_RE.match(line)
        if assign_match:
            artifact_type, artifact_id, tier_name = assign_match.groups()
            key = (artifact_type, artifact_id)
            if key in assignments:
                raise TiersFileError(
                    f"{tiers_path}:{lineno}: duplicate assignment for "
                    f"{artifact_type}/{artifact_id}"
                )
            assignments[key] = tier_name
            continue

        raise TiersFileError(f"{tiers_path}:{lineno}: unparseable tiers line: {line!r}")

    undeclared = sorted({name for name in assignments.values() if name not in tiers})
    if undeclared:
        raise TiersFileError(
            f"{tiers_path}: assignment(s) name undeclared tier(s) {undeclared!r} -- "
            "every 'assign' line must name a tier already declared via a "
            "'tier.<name>.expiry_days' line"
        )

    return tiers, assignments


class TestingWindowFileError(ValueError):
    """Raised when `rezops.testing_window.yaml` can't be parsed into the expected shape.

    A config-file problem, not a caller-input problem -- mirrors
    `TiersFileError`/`ledger_core.action_proposals.PolicyFileError`: fails
    loudly rather than silently letting a malformed declaration through.
    """


def load_testing_window(
    testing_window_path: Path,
) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """Parse `rezops.testing_window.yaml` into `((start_month, start_day), (end_month, end_day))`.

    A hand-rolled parser for a deliberately minimal, flat format -- mirrors
    `load_tiers`'s own "no PyYAML dependency" discipline: blank lines and
    `#`-prefixed comment lines are ignored anywhere, and the two declaration
    lines (`window_start: MM-DD`, `window_end: MM-DD`) may appear in either
    order.

    Returns `None` -- never raises -- if `testing_window_path` doesn't exist:
    no window is declared, so every artifact correctly resolves
    `testing_window_compliance="unknown"` rather than this function crashing
    on a config file that hasn't been created yet (mirrors `load_tiers`'s
    identical missing-file behavior).

    Raises `TestingWindowFileError` -- fails loudly, never silently ignored
    -- for any existing file that isn't exactly two valid `MM-DD` lines: an
    unparseable line, a duplicate declaration, an invalid month/day (e.g.
    month 13, day 32, or February 30), or declaring zero or exactly one of
    `window_start`/`window_end` (an empty/comment-only file included -- it
    exists but is not exactly two valid lines, so it is malformed, not
    equivalent to a missing file). Only declaring both lines, each a valid
    `MM-DD` calendar date, parses successfully.
    """
    if not testing_window_path.exists():
        return None

    text = testing_window_path.read_text(encoding="utf-8")
    values: dict[str, tuple[int, int]] = {}

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        match = _TESTING_WINDOW_LINE_RE.match(line)
        if not match:
            raise TestingWindowFileError(
                f"{testing_window_path}:{lineno}: unparseable testing-window "
                f"line: {line!r}"
            )

        key, month_text, day_text = match.groups()
        if key in values:
            raise TestingWindowFileError(
                f"{testing_window_path}:{lineno}: duplicate window_{key} declaration"
            )

        month, day = int(month_text), int(day_text)
        if not _is_valid_month_day(month, day):
            raise TestingWindowFileError(
                f"{testing_window_path}:{lineno}: window_{key} must be a valid "
                f"MM-DD calendar date; got {month_text}-{day_text}"
            )
        values[key] = (month, day)

    missing = sorted({"start", "end"} - values.keys())
    if missing:
        raise TestingWindowFileError(
            f"{testing_window_path}: must declare exactly window_start and "
            f"window_end lines; missing {[f'window_{name}' for name in missing]!r}"
        )

    return values["start"], values["end"]


def _is_valid_month_day(month: int, day: int) -> bool:
    """True iff `(month, day)` is a real calendar date in a non-leap year.

    Deliberately checked against a non-leap year (`datetime(2001, ...)`) so
    `02-29` is always rejected -- `MM-DD` has no year, so there is no way to
    know whether the declaring year was a leap year, and accepting `02-29`
    would make the declared window silently invalid three years out of four.
    """
    try:
        datetime(2001, month, day)
    except ValueError:
        return False
    return True


def _compute_test_achievement(fields: dict[str, Any]) -> tuple[float | None, float | None]:
    """Compute `(rto_achieved_pct, rpo_achieved_pct)` from a folded artifact's fields (Story 19, CAP-12).

    Identical formula applied independently to the RTO pair
    (`rto_target_minutes`/`rto_actual_minutes`) and the RPO pair
    (`rpo_target_minutes`/`rpo_actual_minutes`) via `_achieved_pct`: given a
    numeric, non-bool, positive, finite `target` and `actual`,
    `min(100.0, (target / actual) * 100)` -- capped at 100 because
    recovering faster/tighter than target is still "fully achieved," never
    "more than 100% achieved" (this story's own explicit choice -- see the
    story's Design Notes). Any other case (either field missing, non-numeric,
    `bool`, non-positive, or non-finite -- `float("inf")`/`float("nan")`,
    which would otherwise make `target / actual` an undefined ratio that
    `min()` could silently resolve to a false 100.0 "fully achieved")
    resolves that pair to `None`, never raises, never guesses.
    """
    return (
        _achieved_pct(fields.get("rto_target_minutes"), fields.get("rto_actual_minutes")),
        _achieved_pct(fields.get("rpo_target_minutes"), fields.get("rpo_actual_minutes")),
    )


def _achieved_pct(target: Any, actual: Any) -> float | None:
    if (
        isinstance(target, (int, float))
        and not isinstance(target, bool)
        and isinstance(actual, (int, float))
        and not isinstance(actual, bool)
        and target > 0
        and actual > 0
        and math.isfinite(target)
        and math.isfinite(actual)
    ):
        return min(100.0, (target / actual) * 100)
    return None


def _compute_testing_window_compliance(
    fields: dict[str, Any],
    window: tuple[tuple[int, int], tuple[int, int]] | None,
) -> str:
    """Compute `testing_window_compliance` from a folded artifact's `test_date` x the declared window (Story 19, CAP-12).

    `"unknown"` if `window` is `None` (`rezops.testing_window.yaml` is
    missing) or `test_date` is missing, non-string, or unparseable as
    `YYYY-MM-DD` -- never raises. Otherwise, `test_date`'s `(month, day)` is
    compared against the declared `(start, end)`: `"compliant"` if it falls
    inside the window (accounting for a window that wraps across a year
    boundary, i.e. `end < start`, e.g. `11-01`..`02-28`), else
    `"non_compliant"`.
    """
    if window is None:
        return "unknown"

    test_date = fields.get("test_date")
    if not isinstance(test_date, str):
        return "unknown"
    try:
        parsed_date = datetime.strptime(test_date, _TEST_DATE_FORMAT)
    except ValueError:
        return "unknown"

    month_day = (parsed_date.month, parsed_date.day)
    start, end = window
    if start <= end:
        in_window = start <= month_day <= end
    else:
        # Wraps across a year boundary (e.g. 11-01..02-28): inside the
        # window means on/after start OR on/before end, not between them.
        in_window = month_day >= start or month_day <= end

    return "compliant" if in_window else "non_compliant"


def _compute_tier_and_risk(
    artifact_type: str,
    artifact_id: str,
    *,
    last_verified: str | None,
    confidence: str,
    tiers: dict[str, int],
    assignments: dict[tuple[str, str], str],
) -> tuple[str | None, str | None, str]:
    """Compute `(tier_sla, expiry_rule, risk)` for one artifact (Story 17, CAP-11).

    The frozen rule, applied identically wherever a `LedgerRecord` is built:

    1. No `assign` entry for `(artifact_type, artifact_id)` -> no declared
       tier -> `(None, None, "unknown")`. The most conservative reading,
       never a guess (mirrors AD-10's escalate-rather-than-guess precedent).
    2. A tier is declared: `tier_sla` is that tier's name, `expiry_rule` is
       `f"{expiry_days} days"` -- both populated regardless of what follows.
    3. If `confidence == "unknown"` (equivalently, nothing has ever been
       observed for this artifact) -> `risk="unknown"` -- can't assess
       freshness against nothing. Both `"agent-verified"` and `"manual"` are
       treated as verified-enough-to-assess-freshness: a human's explicit
       attestation is exactly as good a basis for a freshness check as an
       agent's, even though no code path produces `"manual"` today (it is a
       valid `CONFIDENCE_VALUES` member the schema already allows).
    4. Otherwise: `days_since = (now - last_verified).days` against the
       tier's `expiry_days`. Past the full window -> `"high"`; past
       `_MEDIUM_RISK_THRESHOLD_FRACTION` of it -> `"medium"`; else -> `"low"`.
       A malformed/hand-edited `last_verified` timestamp that fails to parse
       degrades to `risk="unknown"` (AD-8: graceful degradation) rather than
       raising -- the same treatment step 3 already gives "nothing observed".

    Note: unlike every other `LedgerRecord` field, `risk` also depends on the
    current wall-clock time (`datetime.now(timezone.utc)` below), so two
    calls against identical log content, separated by enough real time, can
    legitimately return a different `risk` -- a deliberate exception to the
    "pure projection over the log" characterization used elsewhere in this
    codebase.
    """
    tier_name = assignments.get((artifact_type, artifact_id))
    if tier_name is None:
        return None, None, "unknown"

    expiry_days = tiers[tier_name]
    tier_sla = tier_name
    expiry_rule = f"{expiry_days} days"

    if confidence == "unknown" or last_verified is None:
        return tier_sla, expiry_rule, "unknown"

    try:
        last_verified_dt = datetime.strptime(last_verified, TIMESTAMP_FORMAT).replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        # A malformed/hand-edited last_verified timestamp degrades to
        # risk="unknown" rather than raising (AD-8).
        return tier_sla, expiry_rule, "unknown"

    days_since = (datetime.now(timezone.utc) - last_verified_dt).days
    if days_since > expiry_days:
        risk = "high"
    elif days_since > _MEDIUM_RISK_THRESHOLD_FRACTION * expiry_days:
        risk = "medium"
    else:
        risk = "low"
    return tier_sla, expiry_rule, risk


#: Fixed field-priority order `_compute_escalation_owner` resolves against
#: (AD-10, CAP-5, Story 8). Ordered most- to least-authoritative:
#: `support_group` (CMDB -- the canonical "who supports this system" record),
#: `assigned_to` (ticketing -- who's handling an active issue, may be
#: transient), `organizer_email` (calendar -- weakest signal, just who
#: scheduled a meeting). Git's `author` is deliberately excluded: it means
#: "who last touched this," not "who owns this." This is a fixed constant
#: for the four real connectors' actual field names, not a
#: configurable/pluggable priority system -- see the story's Design Notes for
#: the rationale and its explicitly judgment-call nature.
_OWNERSHIP_FIELD_PRIORITY = ("support_group", "assigned_to", "organizer_email")


def _compute_escalation_owner(fields: dict[str, Any]) -> str | None:
    """Resolve `escalation_owner` from the fixed field-priority order (AD-10).

    Returns the value of the first field in `_OWNERSHIP_FIELD_PRIORITY` that
    is present in `fields` with a *non-blank string* value; `None` if none of
    the three fields carries one. A lower-priority field is never deleted or
    hidden from `fields` just because a higher-priority one won -- this only
    decides which single value becomes `escalation_owner`.

    A value counts as present only if it is a `str` that is non-empty after
    stripping whitespace (`isinstance(value, str) and value.strip()`) --
    checking mere key presence, or even `is not None`, is not enough:

    - `organizer_email`: the calendar connector's `_flatten_organizer_field`
      always includes that key in `fields`, with a `None` value when the
      event genuinely has no organizer -- key presence alone would wrongly
      treat that as a resolved ownership signal.
    - `assigned_to`/`support_group`: real ServiceNow reference fields --
      even with `sysparm_display_value=true` -- commonly render an
      unassigned field as `""` rather than `null`, and neither connector
      rejects an empty string as a required-field value. Treating `""` as a
      resolved owner would wrongly mark a genuinely unowned artifact as
      owned, defeating orphan-risk detection. A blank string falls through
      to the next-priority field exactly as a `None`/missing value would.
    - Any non-string scalar (e.g. an int/float/bool that slipped through as
      a field value) is likewise never returned as `escalation_owner`, which
      must always be a string or `None`.
    """
    for field_name in _OWNERSHIP_FIELD_PRIORITY:
        value = fields.get(field_name)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _compute_confidence(fields: dict[str, Any]) -> str:
    """The first real, intentionally simple confidence rule (AD-5).

    "agent-verified" iff at least one field has ever been observed for this
    artifact (i.e. `fields` is non-empty after folding every RawFact event);
    "unknown" otherwise. Not the final scoring method -- see
    ARCHITECTURE-SPINE.md's Deferred section -- just the simplest thing that
    makes confidence real and demonstrable end-to-end. No "manual" value is
    ever produced yet: no human-entry path exists.
    """
    return "agent-verified" if fields else "unknown"


def _fold_events_by_artifact(
    artifact_type: str,
    *,
    ledger_dir: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Single-pass fold of one artifact-type's log into per-artifact_id state.

    Reads the log exactly once and returns two dicts, both keyed in
    first-seen artifact_id order:

    - cumulative fields (latest RawFact wins per key)
    - `last_verified`: the timestamp of that artifact_id's most recent
      folded-in event (AD-5-style computed-only field -- taken directly from
      the log's own event timestamps, never accepted as input, never
      hand-set)

    `get_record`, `get_coverage_map`, and `list_records` (every artifact_id
    for a type at once, or one at a time) all build on this one pass, so
    tallying coverage or listing across N artifacts of a type costs one log
    read per artifact type, not one read per artifact (avoiding an N+1
    re-read).
    """
    events = read_events(artifact_type, ledger_dir=ledger_dir)

    by_artifact: dict[str, dict[str, Any]] = {}
    last_verified_by_artifact: dict[str, str] = {}
    for event in events:
        # Only fold in "rawfact" events. Only one event type exists today,
        # but nothing else guards against a future event type being silently
        # merged in as if it were a plain observed fact.
        if event.event_type != RAWFACT_EVENT_TYPE:
            continue
        fields = by_artifact.setdefault(event.artifact_id, {})
        fields.update(event.fields)
        # Every folded-in event -- even one with an empty `fields` payload --
        # updates last_verified to that event's own timestamp: the latest
        # *fact recorded*, not the latest non-empty field.
        last_verified_by_artifact[event.artifact_id] = event.timestamp
    return by_artifact, last_verified_by_artifact


def get_record(
    artifact_type: str,
    artifact_id: str,
    *,
    ledger_dir: Path = DEFAULT_LEDGER_DATA_DIR,
    tiers_path: Path = DEFAULT_TIERS_PATH,
    testing_window_path: Path = DEFAULT_TESTING_WINDOW_PATH,
) -> LedgerRecord:
    """Replay the artifact-type log and fold it into a LedgerRecord for one artifact.

    Latest RawFact wins per observed field; earlier versions are not lost --
    they remain in the log's history, just not reflected in current state.

    Raises `TiersFileError` for a malformed `rezops.tiers.yaml` (Story 17)
    and `TestingWindowFileError` for a malformed `rezops.testing_window.yaml`
    (Story 19) -- both propagate unchanged from this function's own
    `load_tiers`/`load_testing_window` calls; a missing config file of
    either kind never raises (see those functions' own docstrings).

    Confidence is computed exclusively here (AD-5), never accepted as input:
    "agent-verified" if at least one field has ever been observed for this
    artifact, "unknown" otherwise -- including for an artifact_id with no
    recorded facts at all. Never raises for a missing artifact; it simply
    returns an empty-fields, unknown record.

    If the artifact-type's log fails to parse (`LogFormatError`), that
    failure is treated exactly like "no facts recorded for this artifact_id"
    -- the same empty-fields/`confidence="unknown"`/`last_verified=None`/
    `escalation_owner=None` record `get_record` already returns for a
    never-observed artifact_id -- rather than propagating the error (AD-8:
    graceful degradation, the same treatment `get_coverage_map`/`list_records`
    already give this same failure at their own granularity). A corrupted
    log is therefore indistinguishable here from an artifact that was simply
    never observed; callers wanting to detect the corruption itself should
    use `list_records`/`get_coverage_map`, which surface it via a dedicated
    sentinel/marker instead of silently absorbing it.

    `last_verified` is likewise computed exclusively here, from the latest
    folded-in event's own timestamp for this artifact_id -- `None` if no
    fact has ever been recorded for it. It reflects *append order* (the
    order events were folded in), which matches true chronological order for
    every real ingestion path: `ledger_ingest_raw_fact` never lets a caller
    supply a custom timestamp. Only tests can construct an out-of-order
    history, via `append_event`'s optional `timestamp` override.

    `escalation_owner` is computed exclusively here too (AD-10, Story 8),
    from the fixed `_OWNERSHIP_FIELD_PRIORITY` order over these same folded
    `fields` -- never accepted as input, never set by a connector. `None` if
    none of the three priority fields carries a non-blank string value (see
    `_compute_escalation_owner`), including for an artifact_id with no
    recorded facts at all.

    `tier_sla`/`expiry_rule`/`risk` are computed exclusively here too (Story
    17, CAP-11), from `rezops.tiers.yaml` (`tiers_path`, `load_tiers`) x this
    artifact's freshness x confidence (`_compute_tier_and_risk`) -- never
    accepted as input, never set by a connector. An artifact with no `assign`
    entry in that config resolves `tier_sla=None`/`expiry_rule=None`/
    `risk="unknown"`, the most conservative reading, never a guess.
    `verification_method` is intentionally always `None` on every record this
    story produces -- no verification-method data source exists yet.

    `rto_achieved_pct`/`rpo_achieved_pct`/`testing_window_compliance` are
    computed exclusively here too (Story 19, CAP-12), generically from
    whatever `rto_target_minutes`/`rto_actual_minutes`/`rpo_target_minutes`/
    `rpo_actual_minutes`/`test_date` fields happen to be present on this
    artifact (`_compute_test_achievement`,
    `_compute_testing_window_compliance`) x the declared annual window
    (`rezops.testing_window.yaml`, `testing_window_path`, `load_testing_window`)
    -- never accepted as input, never set by a connector, and independent of
    any `artifact_type` name.

    Note: unlike every other field this function computes (which are pure
    functions of the log's content), `risk` also depends on the current
    wall-clock time (`_compute_tier_and_risk` calls `datetime.now(timezone.utc)`
    internally) -- two calls against identical log content, separated by
    enough real time, can legitimately return a different `risk`. This is a
    real, deliberate exception to the "pure projection over the log"
    characterization used elsewhere in this codebase.
    """
    try:
        by_artifact, last_verified_by_artifact = _fold_events_by_artifact(
            artifact_type, ledger_dir=ledger_dir
        )
    except LogFormatError:
        by_artifact, last_verified_by_artifact = {}, {}

    fields = by_artifact.get(artifact_id, {})
    last_verified = last_verified_by_artifact.get(artifact_id)
    confidence = _compute_confidence(fields)

    tiers, assignments = load_tiers(tiers_path)
    tier_sla, expiry_rule, risk = _compute_tier_and_risk(
        artifact_type,
        artifact_id,
        last_verified=last_verified,
        confidence=confidence,
        tiers=tiers,
        assignments=assignments,
    )

    testing_window = load_testing_window(testing_window_path)
    rto_achieved_pct, rpo_achieved_pct = _compute_test_achievement(fields)
    testing_window_compliance = _compute_testing_window_compliance(
        fields, testing_window
    )

    return LedgerRecord(
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        fields=fields,
        last_verified=last_verified,
        escalation_owner=_compute_escalation_owner(fields),
        confidence=confidence,
        tier_sla=tier_sla,
        expiry_rule=expiry_rule,
        risk=risk,
        rto_achieved_pct=rto_achieved_pct,
        rpo_achieved_pct=rpo_achieved_pct,
        testing_window_compliance=testing_window_compliance,
    )


def get_coverage_map(
    *,
    ledger_dir: Path = DEFAULT_LEDGER_DATA_DIR,
) -> dict[str, dict[str, int]]:
    """Tally confidence counts per artifact_type across every known artifact.

    Groups by `artifact_type` only -- no tier/SLA/risk dimension: an
    aggregate risk/RAG view over Story 17's new per-record `tier_sla`/`risk`
    is a later story's job (see ARCHITECTURE-SPINE.md's Deferred section),
    not this function's, unchanged here. Reserved/internal log filenames (leading
    underscore, e.g. a future `_ops.log.md`) are excluded entirely and never
    treated as an artifact type. A log filename that derives an empty
    artifact_type after stripping the `.log.md` suffix (e.g. a literal
    `.log.md` file) is likewise skipped rather than silently populating the
    map under a `""` key. Returns an empty map if `ledger_dir` doesn't exist,
    exists as a non-directory file (mirroring `log.py`'s `_ensure_ledger_dir`
    guard), or holds no artifact-type logs -- never raises.

    Each artifact_id's confidence is computed with the same
    `_compute_confidence` rule `get_record` uses (never a parallel
    reimplementation), so this tally always matches what `get_record` would
    report for each individual artifact -- but folded from one single-pass
    read per artifact type (`_fold_events_by_artifact`) rather than one
    `get_record` call, and therefore one log re-read, per artifact_id.

    If one artifact_type's log fails to parse (`LogFormatError`), that
    failure is isolated to its own entry -- reported under
    `LOG_FORMAT_ERROR_MARKER` -- rather than aborting the computation for
    every other, healthy artifact type (AD-8: graceful degradation; one bad
    log must not blind the whole coverage view).
    """
    coverage: dict[str, dict[str, int]] = {}
    for artifact_type in _discover_artifact_types(ledger_dir):
        try:
            by_artifact, _ = _fold_events_by_artifact(
                artifact_type, ledger_dir=ledger_dir
            )
        except LogFormatError:
            coverage[artifact_type] = {LOG_FORMAT_ERROR_MARKER: 1}
            continue

        tally: dict[str, int] = {}
        for fields in by_artifact.values():
            confidence = _compute_confidence(fields)
            tally[confidence] = tally.get(confidence, 0) + 1
        coverage[artifact_type] = tally

    return coverage


def _is_excluded_artifact_type_name(artifact_type: str) -> bool:
    """True for an empty string or a reserved (`_`-prefixed) artifact_type name.

    The one exclusion rule every artifact_type name is checked against,
    whether it was discovered from a log filename (`_discover_artifact_types`)
    or passed explicitly as a `list_records`/`ledger_list_records` filter.
    Keeping this as a single shared predicate means an explicit filter can
    never bypass the exclusion discovery already applies -- passing a
    reserved-looking name directly is rejected the same way finding it on
    disk would be.
    """
    return not artifact_type or artifact_type.startswith("_")


def _discover_artifact_types(ledger_dir: Path) -> list[str]:
    """List every non-reserved artifact_type with a log file, sorted.

    Reuses the exact same log-filename discovery rules `get_coverage_map`
    already applies (excluding reserved `_`-prefixed and empty-derived
    names, via `_is_excluded_artifact_type_name`) so `list_records` and
    `get_coverage_map` never disagree about which artifact types exist.
    Returns an empty list if `ledger_dir` doesn't exist or isn't a
    directory -- never raises.
    """
    if not ledger_dir.exists() or not ledger_dir.is_dir():
        return []

    artifact_types: list[str] = []
    for path in sorted(ledger_dir.iterdir()):
        if not path.is_file():
            continue
        name = path.name
        if not name.endswith(_LOG_SUFFIX):
            continue
        artifact_type = name[: -len(_LOG_SUFFIX)]
        if _is_excluded_artifact_type_name(artifact_type):
            continue
        artifact_types.append(artifact_type)
    return artifact_types


def list_records(
    artifact_type: str | None = None,
    confidence: str | None = None,
    orphan_risk: bool | None = None,
    *,
    ledger_dir: Path = DEFAULT_LEDGER_DATA_DIR,
    tiers_path: Path = DEFAULT_TIERS_PATH,
    testing_window_path: Path = DEFAULT_TESTING_WINDOW_PATH,
) -> list[LedgerRecord]:
    """List every known LedgerRecord, optionally filtered.

    Lets a caller ask "what's stale" or "what's unknown" without already
    knowing every artifact's exact ID (CAP-4) -- `get_record` requires an
    exact `artifact_id`, and `get_coverage_map` only returns counts.

    Raises `TiersFileError` for a malformed `rezops.tiers.yaml` (Story 17)
    and `TestingWindowFileError` for a malformed `rezops.testing_window.yaml`
    (Story 19) -- both propagate unchanged from this function's own
    `load_tiers`/`load_testing_window` calls; a missing config file of
    either kind never raises (see those functions' own docstrings).

    `artifact_type`, if given, restricts the scan to that one type's log
    (a nonexistent type's log yields no records -- never raises). An
    explicit `artifact_type` that is an empty string or reserved
    (`_`-prefixed) is rejected the same way discovery would exclude it --
    `_is_excluded_artifact_type_name` -- yielding an empty list rather than
    treating it as a real type. Otherwise every known artifact type is
    discovered the same way `get_coverage_map` does
    (`_discover_artifact_types`). `confidence`, if given, filters the
    resulting real records to that exact value, computed with the same
    `_compute_confidence` rule every other read path uses -- never a
    parallel reimplementation. `orphan_risk`, if given, filters to records
    where `fields` is non-empty AND `escalation_owner` is `None` (when
    `True`), or the inverse -- `fields` empty OR `escalation_owner` resolved
    (when `False`) -- computed with the same `_compute_escalation_owner`
    rule `get_record` uses (AD-10, Story 8). An artifact never observed at
    all (`fields` entirely empty) is never orphan-risk -- orphan-risk means
    "known but unowned," not "unknown." `artifact_type`, `confidence`, and
    `orphan_risk` combine as an AND across all given filters.

    Reuses the same single-pass fold (`_fold_events_by_artifact`) as
    `get_record`/`get_coverage_map` -- one log read per artifact type, never
    one re-read per artifact_id.

    If one artifact_type's log fails to parse (`LogFormatError`), that type
    is *not* silently dropped: it is represented by exactly one sentinel
    LedgerRecord (`artifact_id=LOG_FORMAT_ERROR_ARTIFACT_ID`, `fields={}`,
    `last_verified=None`, `confidence="unknown"`), genuinely equivalent to
    the visibility `get_coverage_map` already gives that same failure via
    `LOG_FORMAT_ERROR_MARKER` (AD-8: graceful degradation -- one bad log
    isolates only its own type, but must never be indistinguishable from
    "no artifacts of this type exist"). That sentinel's `confidence` isn't
    a real classification of any folded fact, so it is always included
    regardless of the `confidence` or `orphan_risk` filter -- an error
    signal must not be filterable away. Never raises. Returns an empty list
    if `ledger_dir` doesn't exist, isn't a directory, holds no matching
    artifact-type logs, or no record matches the given filters.

    `last_verified`, like `get_record`'s, reflects append order, which
    matches true chronological order for every real ingestion path (only
    tests can construct an out-of-order history via `append_event`'s
    timestamp override). `verification_method` is intentionally always
    `None` on every record this story produces -- no verification-method
    data source exists yet. `tier_sla`/`expiry_rule`/`risk` are computed
    exclusively here too (Story 17, CAP-11), per record, via the same
    `_compute_tier_and_risk` rule `get_record` uses, against one shared
    `rezops.tiers.yaml` read (`tiers_path`, `load_tiers`) -- loaded once per
    call, not once per record. `escalation_owner` is computed per record via
    `_compute_escalation_owner` (AD-10, Story 8). `rto_achieved_pct`/
    `rpo_achieved_pct`/`testing_window_compliance` are computed exclusively
    here too (Story 19, CAP-12), per record, via the same
    `_compute_test_achievement`/`_compute_testing_window_compliance` rules
    `get_record` uses, against one shared `rezops.testing_window.yaml` read
    (`testing_window_path`, `load_testing_window`) -- loaded once per call,
    not once per record.
    """
    if artifact_type is not None:
        if _is_excluded_artifact_type_name(artifact_type):
            return []
        candidate_types = [artifact_type]
    else:
        candidate_types = _discover_artifact_types(ledger_dir)

    tiers, assignments = load_tiers(tiers_path)
    testing_window = load_testing_window(testing_window_path)

    records: list[LedgerRecord] = []
    for a_type in candidate_types:
        try:
            by_artifact, last_verified_by_artifact = _fold_events_by_artifact(
                a_type, ledger_dir=ledger_dir
            )
        except LogFormatError:
            error_tier_sla, error_expiry_rule, error_risk = _compute_tier_and_risk(
                a_type,
                LOG_FORMAT_ERROR_ARTIFACT_ID,
                last_verified=None,
                confidence="unknown",
                tiers=tiers,
                assignments=assignments,
            )
            records.append(
                LedgerRecord(
                    artifact_type=a_type,
                    artifact_id=LOG_FORMAT_ERROR_ARTIFACT_ID,
                    fields={},
                    last_verified=None,
                    confidence="unknown",
                    tier_sla=error_tier_sla,
                    expiry_rule=error_expiry_rule,
                    risk=error_risk,
                    rto_achieved_pct=None,
                    rpo_achieved_pct=None,
                    testing_window_compliance="unknown",
                )
            )
            continue

        for artifact_id, fields in by_artifact.items():
            record_confidence = _compute_confidence(fields)
            if confidence is not None and record_confidence != confidence:
                continue
            escalation_owner = _compute_escalation_owner(fields)
            # Orphan-risk: known (non-empty `fields`) but unowned (no
            # resolved `escalation_owner`). An artifact never observed at
            # all is never orphan-risk -- see docstring.
            record_is_orphan_risk = bool(fields) and escalation_owner is None
            if orphan_risk is not None and record_is_orphan_risk != orphan_risk:
                continue
            last_verified = last_verified_by_artifact.get(artifact_id)
            tier_sla, expiry_rule, risk = _compute_tier_and_risk(
                a_type,
                artifact_id,
                last_verified=last_verified,
                confidence=record_confidence,
                tiers=tiers,
                assignments=assignments,
            )
            rto_achieved_pct, rpo_achieved_pct = _compute_test_achievement(fields)
            testing_window_compliance = _compute_testing_window_compliance(
                fields, testing_window
            )
            records.append(
                LedgerRecord(
                    artifact_type=a_type,
                    artifact_id=artifact_id,
                    fields=fields,
                    last_verified=last_verified,
                    escalation_owner=escalation_owner,
                    confidence=record_confidence,
                    tier_sla=tier_sla,
                    expiry_rule=expiry_rule,
                    risk=risk,
                    rto_achieved_pct=rto_achieved_pct,
                    rpo_achieved_pct=rpo_achieved_pct,
                    testing_window_compliance=testing_window_compliance,
                )
            )

    return records
