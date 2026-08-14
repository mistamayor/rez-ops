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

    `verification_method`, `expiry_rule`, `tier_sla`, and `escalation_owner`
    are intentionally always `None` on every record this story produces --
    no tiering/ownership data source exists yet.
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
    parallel reimplementation.

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
    regardless of the `confidence` filter -- an error signal must not be
    filterable away. Never raises. Returns an empty list if `ledger_dir`
    doesn't exist, isn't a directory, holds no matching artifact-type logs,
    or no record matches the given filters.

    `last_verified`, like `get_record`'s, reflects append order, which
    matches true chronological order for every real ingestion path (only
    tests can construct an out-of-order history via `append_event`'s
    timestamp override). `verification_method`, `expiry_rule`, `tier_sla`,
    and `escalation_owner` are intentionally always `None` on every record
    this story produces -- no tiering/ownership data source exists yet.
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
            records.append(
                LedgerRecord(
                    artifact_type=a_type,
                    artifact_id=artifact_id,
                    fields=fields,
                    last_verified=last_verified_by_artifact.get(artifact_id),
                    confidence=record_confidence,
                )
            )

    return records
