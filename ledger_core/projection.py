"""Pure projection: replay an artifact-type event log into current LedgerRecord state.

AD-3: current state is always a pure, recomputed projection over the
append-only log -- never hand-edited, never cached in memory across calls.
Every call to get_record (or get_coverage_map) re-reads the log from disk.
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
) -> dict[str, dict[str, Any]]:
    """Single-pass fold of one artifact-type's log into per-artifact_id fields.

    Reads the log exactly once and returns every artifact_id's cumulative
    fields (latest RawFact wins per key), keyed in first-seen artifact_id
    order. Both `_fold_fields` (a single artifact) and `get_coverage_map`
    (every artifact_id for a type at once) build on this one pass, so
    tallying coverage across N artifacts of a type costs one log read per
    artifact type, not one read per artifact (avoiding an N+1 re-read).
    """
    events = read_events(artifact_type, ledger_dir=ledger_dir)

    by_artifact: dict[str, dict[str, Any]] = {}
    for event in events:
        # Only fold in "rawfact" events. Only one event type exists today,
        # but nothing else guards against a future event type being silently
        # merged in as if it were a plain observed fact.
        if event.event_type != RAWFACT_EVENT_TYPE:
            continue
        fields = by_artifact.setdefault(event.artifact_id, {})
        fields.update(event.fields)
    return by_artifact


def _fold_fields(
    artifact_type: str,
    artifact_id: str,
    *,
    ledger_dir: Path,
) -> dict[str, Any]:
    by_artifact = _fold_events_by_artifact(artifact_type, ledger_dir=ledger_dir)
    return by_artifact.get(artifact_id, {})


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
    """
    fields = _fold_fields(artifact_type, artifact_id, ledger_dir=ledger_dir)

    return LedgerRecord(
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        fields=fields,
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
    if not ledger_dir.exists() or not ledger_dir.is_dir():
        return {}

    coverage: dict[str, dict[str, int]] = {}
    for path in sorted(ledger_dir.iterdir()):
        if not path.is_file():
            continue
        name = path.name
        if name.startswith("_"):
            continue
        if not name.endswith(_LOG_SUFFIX):
            continue
        artifact_type = name[: -len(_LOG_SUFFIX)]
        if not artifact_type:
            continue

        try:
            by_artifact = _fold_events_by_artifact(
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
