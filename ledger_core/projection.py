"""Pure projection: replay an artifact-type event log into current LedgerRecord state.

AD-3: current state is always a pure, recomputed projection over the
append-only log -- never hand-edited, never cached in memory across calls.
Every call to get_record, get_coverage_map, or list_records re-reads the
log(s) from disk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ledger_core.log import (
    DEFAULT_LEDGER_DATA_DIR,
    RAWFACT_EVENT_TYPE,
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
) -> LedgerRecord:
    """Replay the artifact-type log and fold it into a LedgerRecord for one artifact.

    Latest RawFact wins per observed field; earlier versions are not lost --
    they remain in the log's history, just not reflected in current state.

    Confidence is computed exclusively here (AD-5), never accepted as input:
    "agent-verified" if at least one field has ever been observed for this
    artifact, "unknown" otherwise -- including for an artifact_id with no
    recorded facts at all. Never raises for a missing artifact; it simply
    returns an empty-fields, unknown record.

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

    `verification_method`, `expiry_rule`, and `tier_sla` are intentionally
    always `None` on every record this story produces -- no tiering data
    source exists yet.
    """
    by_artifact, last_verified_by_artifact = _fold_events_by_artifact(
        artifact_type, ledger_dir=ledger_dir
    )
    fields = by_artifact.get(artifact_id, {})
    last_verified = last_verified_by_artifact.get(artifact_id)

    return LedgerRecord(
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        fields=fields,
        last_verified=last_verified,
        escalation_owner=_compute_escalation_owner(fields),
        confidence=_compute_confidence(fields),
    )


def get_coverage_map(
    *,
    ledger_dir: Path = DEFAULT_LEDGER_DATA_DIR,
) -> dict[str, dict[str, int]]:
    """Tally confidence counts per artifact_type across every known artifact.

    Groups by `artifact_type` only -- no tier/SLA dimension yet (no tiering
    data source exists). Reserved/internal log filenames (leading
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
) -> list[LedgerRecord]:
    """List every known LedgerRecord, optionally filtered.

    Lets a caller ask "what's stale" or "what's unknown" without already
    knowing every artifact's exact ID (CAP-4) -- `get_record` requires an
    exact `artifact_id`, and `get_coverage_map` only returns counts.

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
    timestamp override). `verification_method`, `expiry_rule`, and
    `tier_sla` are intentionally always `None` on every record this story
    produces -- no tiering data source exists yet. `escalation_owner` is
    computed per record via `_compute_escalation_owner` (AD-10, Story 8).
    """
    if artifact_type is not None:
        if _is_excluded_artifact_type_name(artifact_type):
            return []
        candidate_types = [artifact_type]
    else:
        candidate_types = _discover_artifact_types(ledger_dir)

    records: list[LedgerRecord] = []
    for a_type in candidate_types:
        try:
            by_artifact, last_verified_by_artifact = _fold_events_by_artifact(
                a_type, ledger_dir=ledger_dir
            )
        except LogFormatError:
            records.append(
                LedgerRecord(
                    artifact_type=a_type,
                    artifact_id=LOG_FORMAT_ERROR_ARTIFACT_ID,
                    fields={},
                    last_verified=None,
                    confidence="unknown",
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
            records.append(
                LedgerRecord(
                    artifact_type=a_type,
                    artifact_id=artifact_id,
                    fields=fields,
                    last_verified=last_verified_by_artifact.get(artifact_id),
                    escalation_owner=escalation_owner,
                    confidence=record_confidence,
                )
            )

    return records
