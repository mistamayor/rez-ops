"""Pure projection: replay an artifact-type event log into current LedgerRecord state.

AD-3: current state is always a pure, recomputed projection over the
append-only log -- never hand-edited, never cached in memory across calls.
Every call to get_record re-reads the log from disk.
"""

from __future__ import annotations

from pathlib import Path

from ledger_core.log import DEFAULT_LEDGER_DATA_DIR, RAWFACT_EVENT_TYPE, read_events
from shared.ledger_schema import LedgerRecord


def get_record(
    artifact_type: str,
    artifact_id: str,
    *,
    ledger_dir: Path = DEFAULT_LEDGER_DATA_DIR,
) -> LedgerRecord:
    """Replay the artifact-type log and fold it into a LedgerRecord for one artifact.

    Latest RawFact wins per observed field; earlier versions are not lost --
    they remain in the log's history, just not reflected in current state.

    No verification-event mechanism exists yet (deferred per
    ARCHITECTURE-SPINE.md), so confidence is always "unknown" -- including
    for an artifact_id with no recorded facts at all. Never raises for a
    missing artifact; it simply returns an empty-fields, unknown record.
    """
    events = read_events(artifact_type, ledger_dir=ledger_dir)

    fields: dict = {}
    for event in events:
        # Only fold in "rawfact" events. Only one event type exists today,
        # but nothing else guards against a future event type being silently
        # merged in as if it were a plain observed fact.
        if event.event_type != RAWFACT_EVENT_TYPE:
            continue
        if event.artifact_id != artifact_id:
            continue
        fields.update(event.fields)

    return LedgerRecord(
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        fields=fields,
        confidence="unknown",
    )
