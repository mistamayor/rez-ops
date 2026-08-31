"""Ledger-core MCP server (AD-1, AD-2): ledger-core is its own MCP server.

Exposes seven tools: a read/query surface over projection.py
(`ledger_get_record`, `ledger_get_coverage`, `ledger_list_records`), the one
and only ingestion path into the append-only log (`ledger_ingest_raw_fact`),
the draft-not-send outbound content queue over drafts.py
(`ledger_create_draft`, `ledger_list_drafts` -- AD-6, CAP-6, Story 9), and the
periodic briefing over briefing.py (`ledger_get_briefing` -- CAP-7, Story
10). Ledger state can only ever be changed by appending to the log (AD-3) --
`ledger_ingest_raw_fact` constructs a `RawFact` and calls `append_event`; it
has no other side effect and no `confidence` parameter (confidence is
computed exclusively by `projection.get_record`, AD-5). `ledger_create_draft`
is the only other tool with a write side effect -- it writes exactly one new
file under `ledger_data/drafts/` and calls no external send/write API of any
kind (AD-6). `ledger_get_briefing`, like every other read tool here, performs
no write of any kind -- it composes `get_record`/`list_records`/`list_drafts`/
`get_coverage_map`'s own results, nothing more.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ledger_core.briefing import get_briefing
from ledger_core.drafts import Draft, create_draft, list_drafts
from ledger_core.log import append_event
from ledger_core.projection import get_coverage_map, get_record, list_records
from shared.ledger_schema import LedgerRecord, RawFact

mcp = FastMCP("ledger-core")


def _record_to_dict(record: LedgerRecord) -> dict[str, Any]:
    """The one LedgerRecord-to-dict shape every read tool below serializes.

    Shared by `ledger_get_record`, `ledger_list_records`, and
    `ledger_get_briefing` so a future `LedgerRecord` field only needs to be
    added here once -- not kept in sync across three independent call
    sites.
    """
    return {
        "artifact_type": record.artifact_type,
        "artifact_id": record.artifact_id,
        "fields": dict(record.fields),
        "last_verified": record.last_verified,
        "verification_method": record.verification_method,
        "expiry_rule": record.expiry_rule,
        "tier_sla": record.tier_sla,
        "escalation_owner": record.escalation_owner,
        "confidence": record.confidence,
    }


def _draft_to_dict(draft: Draft) -> dict[str, Any]:
    """The one Draft-to-dict shape every read/write tool below serializes.

    Shared by `ledger_create_draft`, `ledger_list_drafts`, and
    `ledger_get_briefing`.
    """
    return {
        "draft_id": draft.draft_id,
        "artifact_type": draft.artifact_type,
        "artifact_id": draft.artifact_id,
        "draft_type": draft.draft_type,
        "subject": draft.subject,
        "body": draft.body,
        "recipient": draft.recipient,
        "created_at": draft.created_at,
    }


@mcp.tool(name="ledger_get_record")
def ledger_get_record(artifact_type: str, artifact_id: str) -> dict[str, Any]:
    """Return the current LedgerRecord for one artifact.

    Computed by purely replaying that artifact type's append-only event log
    (AD-3) -- never a cached or hand-edited value. An artifact with no
    recorded facts returns empty fields and confidence "unknown" rather than
    an error. `verification_method`, `expiry_rule`, and `tier_sla` are
    intentionally always `None` in this story -- nothing populates them yet.
    `escalation_owner` is computed from a fixed field-priority order over
    `support_group` (CMDB) > `assigned_to` (ticketing) > `organizer_email`
    (calendar) -- `None` if none of those three fields carries a non-blank
    string value (a missing/`None` value, a blank/whitespace-only string,
    and a non-string scalar all fall through the same way) (AD-10).
    """
    record = get_record(artifact_type, artifact_id)
    return _record_to_dict(record)


@mcp.tool(name="ledger_ingest_raw_fact")
def ledger_ingest_raw_fact(
    artifact_type: str, artifact_id: str, source: str, fields: dict[str, Any]
) -> dict[str, Any]:
    """Ingest one observed RawFact by appending it to its artifact-type log.

    The only ledger-core write path (AD-3): constructs a `RawFact` from the
    given fields and calls `append_event` -- no other file write, no direct
    log-file manipulation. Has no `confidence` parameter; confidence is
    never accepted as input, only ever computed by `projection.get_record`
    (AD-5). A `fields` payload carrying a LedgerRecord-only key (e.g.
    `confidence`) fails `RawFact` construction with `SchemaValidationError`
    before anything is appended -- that exception is left to propagate and
    is converted into a structured, non-crashing MCP error by the mcp SDK's
    own tool-call handling (the same mechanism proven for `ledger_get_record`
    in Story 1), not by a redundant try/except here.
    """
    fact = RawFact(
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        source=source,
        fields=fields,
    )
    append_event(fact)
    return {
        "artifact_type": fact.artifact_type,
        "artifact_id": fact.artifact_id,
        "source": fact.source,
        "fields": dict(fact.fields),
    }


@mcp.tool(name="ledger_get_coverage")
def ledger_get_coverage() -> dict[str, dict[str, int]]:
    """Return a per-artifact_type tally of confidence counts.

    Computed by purely replaying every known artifact-type log (AD-3) --
    never cached. Groups by `artifact_type` only, no tier/SLA dimension yet
    (AD-5; no tiering data source exists). Reserved/internal log filenames
    (leading underscore) are excluded. Returns an empty map rather than
    raising when no ledger data exists yet. If one artifact_type's log is
    corrupted, that type's entry reports
    `ledger_core.projection.LOG_FORMAT_ERROR_MARKER` instead of a normal
    confidence tally -- every other artifact type's coverage is still
    computed and returned (AD-8: graceful degradation).
    """
    return get_coverage_map()


@mcp.tool(name="ledger_list_records")
def ledger_list_records(
    artifact_type: str | None = None,
    confidence: str | None = None,
    orphan_risk: bool | None = None,
) -> list[dict[str, Any]]:
    """List every known LedgerRecord, optionally filtered by artifact_type, confidence, and/or orphan_risk.

    Lets a caller ask "what's stale", "what's unknown", or "what's at risk
    of having no owner" without already knowing every artifact's exact ID
    (CAP-4, CAP-5) -- `ledger_get_record` needs an exact `artifact_id`, and
    `ledger_get_coverage` only returns counts. Computed by replaying the
    relevant artifact-type log(s) (AD-3) -- never cached -- reusing the same
    single-pass fold `ledger_get_record` and `ledger_get_coverage` already
    use, so listing never re-reads a log once per artifact.

    `orphan_risk`, if given, filters to records where `fields` is non-empty
    AND `escalation_owner` is `None` (when `True`), or the inverse (when
    `False`) -- computed with the same fixed field-priority order
    `ledger_get_record` uses (AD-10). An artifact never observed at all
    (`fields` entirely empty) is never orphan-risk -- orphan-risk means
    "known but unowned," not "unknown." `artifact_type`, `confidence`, and
    `orphan_risk` combine as an AND across all given filters. An empty
    result (e.g. no orphans at all) is returned as `[]`, never an error.

    If one artifact_type's log is corrupted, that type is not silently
    dropped: it is represented by exactly one sentinel record
    (`artifact_id="_log_format_error"`, `confidence="unknown"`) rather than
    being indistinguishable from "no artifacts of this type exist" --
    genuinely equivalent to `ledger_get_coverage`'s visibility for the same
    failure (AD-8), returned regardless of any `confidence` or `orphan_risk`
    filter. Returns an empty list rather than raising for a nonexistent,
    empty-string, or reserved (`_`-prefixed) `artifact_type`, or when no
    record matches the given filters. `verification_method`, `expiry_rule`,
    and `tier_sla` are intentionally always `None` in this story -- nothing
    populates them yet.
    """
    records = list_records(
        artifact_type=artifact_type, confidence=confidence, orphan_risk=orphan_risk
    )
    return [_record_to_dict(record) for record in records]


@mcp.tool(name="ledger_create_draft")
def ledger_create_draft(
    artifact_type: str,
    artifact_id: str,
    draft_type: str,
    subject: str,
    body: str,
    recipient: str | None = None,
) -> dict[str, Any]:
    """Create one draft of outbound content and write it to `ledger_data/drafts/`.

    The only side effect is writing exactly one new git-tracked markdown
    file, `ledger_data/drafts/{draft_id}.md` -- `draft_id` is always
    generated here (a sortable UTC timestamp plus a short random suffix),
    never accepted from the caller. Never calls an external send/write API
    of any kind (no email, Slack, HTTP, or other outbound call) -- sending is
    a manual, human-initiated action entirely outside this system in v1
    (AD-6). This story adds no update/delete tool: creation is the only
    mutation a draft ever undergoes.

    `artifact_type`/`artifact_id` are validated against the same identifier
    charset every other component in this project already enforces.
    `draft_type`/`subject`/`body` must each be non-empty and
    non-whitespace-only. All five raise a typed, non-crashing MCP error
    (surfaced by the mcp SDK's own tool-call handling, the same mechanism
    proven for every other tool here) and write nothing if invalid.

    If `recipient` is omitted, defaults to the artifact's current
    `escalation_owner` (via `ledger_core.projection.get_record`, Story 8). If
    that's unresolved too -- an orphan-risk artifact, or one never observed
    at all -- `recipient` stays unset (`None`) in the created draft rather
    than being guessed at; that's the honest behavior for exactly the case
    this tool exists to surface. No other heuristic ever guesses a
    recipient. `subject`/`body` content is never validated, inspected, or
    templated beyond the non-blank check -- they're opaque text the caller
    supplies.
    """
    draft = create_draft(
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        draft_type=draft_type,
        subject=subject,
        body=body,
        recipient=recipient,
    )
    return _draft_to_dict(draft)


@mcp.tool(name="ledger_list_drafts")
def ledger_list_drafts(
    artifact_type: str | None = None,
    artifact_id: str | None = None,
    draft_type: str | None = None,
) -> list[dict[str, Any]]:
    """List every draft under `ledger_data/drafts/`, optionally filtered.

    Read-only: never mutates a draft file. `artifact_type`, `artifact_id`,
    and `draft_type` combine as an AND across whichever are given; an
    omitted filter doesn't restrict the result. Returns `[]` -- never
    raises -- when `ledger_data/drafts/` doesn't exist yet (no draft has
    ever been created) or no draft matches the given filters.
    """
    drafts = list_drafts(
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        draft_type=draft_type,
    )
    return [_draft_to_dict(draft) for draft in drafts]


@mcp.tool(name="ledger_get_briefing")
def ledger_get_briefing() -> dict[str, Any]:
    """Return the periodic briefing: what needs a decision today (CAP-7, Story 10).

    Composes only existing read functions -- `ledger_core.projection.list_records`
    (once with `orphan_risk=True`, once with `confidence="unknown"`),
    `ledger_core.drafts.list_drafts`, and
    `ledger_core.projection.get_coverage_map` -- no new computation is
    performed about artifact state. Section order is fixed: `orphan_risk`,
    `unknown_confidence`, `pending_drafts`, `data_quality_issues` -- not a
    computed priority ranking (no tier/SLA data source exists yet to rank
    by). Because each section is exactly what the corresponding direct query
    would return at the same point in time, this briefing's content always
    matches a live query -- by construction, not by a parallel
    reimplementation that could drift out of sync.

    Read-only: performs no write of any kind (no log append, no draft
    file). `generated_at` is the UTC timestamp this briefing was assembled,
    so a caller can tell how fresh it is. Never raises for an empty ledger --
    every section is simply empty, `generated_at` is still populated. The
    delivery channel (Slack, email, terminal, ...) is entirely out of scope
    here: this tool returns structured data only.
    """
    briefing = get_briefing()
    return {
        "orphan_risk": [_record_to_dict(record) for record in briefing.orphan_risk],
        "unknown_confidence": [
            _record_to_dict(record) for record in briefing.unknown_confidence
        ],
        "pending_drafts": [_draft_to_dict(draft) for draft in briefing.pending_drafts],
        # `dict(tally)` copies each per-type tally too, not just the outer
        # dict -- `briefing.data_quality_issues`'s nested dicts must not
        # leak out as shared references a client-side mutation could alias
        # back into ledger-core's internal state.
        "data_quality_issues": {
            artifact_type: dict(tally)
            for artifact_type, tally in briefing.data_quality_issues.items()
        },
        "generated_at": briefing.generated_at,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
