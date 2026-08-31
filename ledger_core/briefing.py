"""Periodic briefing (AD-1, CAP-7, Story 10): pure aggregation, no new reads.

`get_briefing` answers "what needs a decision today" by composing three
already-existing read functions -- `projection.list_records(orphan_risk=True)`,
`projection.list_records(confidence="unknown")`, and `drafts.list_drafts()` --
plus a `data_quality_issues` section pulled straight from
`projection.get_coverage_map()`'s existing per-type corruption marker
(`LOG_FORMAT_ERROR_MARKER`). Nothing here computes anything new about
artifact state: every value in a `Briefing` is exactly what a caller would
get back from calling the underlying function directly, at the same point in
time (CAP-7's "must match what a live query returns" requirement is
satisfied by construction -- this *is* that same read path, just composed,
never a parallel reimplementation).

Section order on `Briefing` is fixed -- `orphan_risk`, `unknown_confidence`,
`pending_drafts`, `data_quality_issues` -- not a computed priority ranking:
there's no tier/SLA data yet to rank by (see ARCHITECTURE-SPINE.md's
Deferred section), so this doesn't pretend to have one.

Read-only: `get_briefing` never appends to a log, never writes a draft, and
never touches `ledger_dir` if it doesn't already exist -- it only calls
existing read functions, each of which already tolerates a missing
`ledger_dir` by returning an empty result rather than raising.

Delivery channel (Slack, email, terminal, ...) is entirely out of scope
here and for this whole story -- this module returns structured data only;
whatever calls `get_briefing` decides how to present it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ledger_core.drafts import Draft, list_drafts
from ledger_core.log import DEFAULT_LEDGER_DATA_DIR
from ledger_core.projection import (
    LOG_FORMAT_ERROR_MARKER,
    get_coverage_map,
    list_records,
)
from shared.ledger_schema import LedgerRecord

#: Timestamp format `generated_at` is rendered in -- matches
#: `ledger_core.log`'s own event-timestamp format and `ledger_core.drafts`'
#: `created_at` format, so every ISO-8601-UTC-looking string in this project
#: is rendered the same one way.
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


@dataclass(frozen=True)
class Briefing:
    """The periodic briefing: what needs a decision today (CAP-7).

    `orphan_risk` is exactly `projection.list_records(orphan_risk=True)`'s
    result; `unknown_confidence` is exactly
    `projection.list_records(confidence="unknown")`'s result;
    `pending_drafts` is exactly `drafts.list_drafts()`'s result -- including,
    in each case, whatever `LOG_FORMAT_ERROR_ARTIFACT_ID`/
    `DRAFT_FORMAT_ERROR_MARKER` sentinel record those functions would already
    include for a corrupted log or draft file (Story 8/9's existing
    graceful-degradation behavior, unchanged here). A corrupted-log sentinel
    can, in principle, appear in both `orphan_risk` and `unknown_confidence`
    if the underlying artifact type is corrupted -- this story doesn't
    dedupe that across sections; see the story's Design Notes.

    `data_quality_issues` is the subset of `projection.get_coverage_map()`'s
    result whose per-artifact-type tally carries `LOG_FORMAT_ERROR_MARKER`
    -- i.e. exactly the artifact types `get_coverage_map` already flags as
    corrupted, keyed by `artifact_type`, with no re-derivation of that signal
    a second way.

    `generated_at` is the UTC timestamp this `Briefing` was assembled at, so
    a caller can tell how fresh it is.

    `orphan_risk`, `unknown_confidence`, and `pending_drafts` are tuples
    (not lists), and each `data_quality_issues` value is its own dict, not a
    shared reference into `get_coverage_map()`'s internals -- `Briefing` is
    `frozen=True`, but a frozen dataclass only blocks reassigning its
    fields; a plain `list`/mutable-dict field would still let a caller
    mutate this "immutable snapshot"'s contents in place, or (worse) alias
    back into ledger-core's own internal state. Tuples and per-key-copied
    dicts close that gap.
    """

    orphan_risk: tuple[LedgerRecord, ...]
    unknown_confidence: tuple[LedgerRecord, ...]
    pending_drafts: tuple[Draft, ...]
    data_quality_issues: dict[str, dict[str, int]]
    generated_at: str


def get_briefing(*, ledger_dir: Path = DEFAULT_LEDGER_DATA_DIR) -> Briefing:
    """Compose the periodic briefing from existing read functions only.

    Calls `projection.list_records(orphan_risk=True, ledger_dir=ledger_dir)`,
    `projection.list_records(confidence="unknown", ledger_dir=ledger_dir)`,
    `drafts.list_drafts(ledger_dir=ledger_dir)`, and
    `projection.get_coverage_map(ledger_dir=ledger_dir)` -- each already
    handles a missing/empty/nonexistent `ledger_dir` by returning an empty
    result rather than raising, so `get_briefing` never raises for an empty
    ledger either: every `Briefing` field is simply empty (`generated_at`
    is still populated).

    Never mutates anything: every call here is one of the four existing
    read functions above: no log is appended to, no draft is written, and
    no directory is created as a side effect of reading.
    """
    orphan_risk = tuple(list_records(orphan_risk=True, ledger_dir=ledger_dir))
    unknown_confidence = tuple(
        list_records(confidence="unknown", ledger_dir=ledger_dir)
    )
    pending_drafts = tuple(list_drafts(ledger_dir=ledger_dir))
    coverage = get_coverage_map(ledger_dir=ledger_dir)
    # `dict(tally)` copies each per-type tally too, not just the outer dict --
    # otherwise these would stay shared references into `coverage`'s own
    # dicts, and `Briefing` is meant to be an immutable snapshot.
    data_quality_issues = {
        artifact_type: dict(tally)
        for artifact_type, tally in coverage.items()
        if LOG_FORMAT_ERROR_MARKER in tally
    }
    generated_at = datetime.now(timezone.utc).strftime(_TIMESTAMP_FORMAT)

    return Briefing(
        orphan_risk=orphan_risk,
        unknown_confidence=unknown_confidence,
        pending_drafts=pending_drafts,
        data_quality_issues=data_quality_issues,
        generated_at=generated_at,
    )
