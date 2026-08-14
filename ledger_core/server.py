"""Ledger-core MCP server (AD-1, AD-2): ledger-core is its own MCP server.

Exposes four tools: a read/query surface over projection.py
(`ledger_get_record`, `ledger_get_coverage`, `ledger_list_records`), and the
one and only ingestion path into the append-only log
(`ledger_ingest_raw_fact`). Ledger state can only ever be changed by
appending to the log (AD-3) -- `ledger_ingest_raw_fact` constructs a
`RawFact` and calls `append_event`; it has no other side effect and no
`confidence` parameter (confidence is computed exclusively by
`projection.get_record`, AD-5).
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ledger_core.log import append_event
from ledger_core.projection import get_coverage_map, get_record, list_records
from shared.ledger_schema import RawFact

mcp = FastMCP("ledger-core")


@mcp.tool(name="ledger_get_record")
def ledger_get_record(artifact_type: str, artifact_id: str) -> dict[str, Any]:
    """Return the current LedgerRecord for one artifact.

    Computed by purely replaying that artifact type's append-only event log
    (AD-3) -- never a cached or hand-edited value. An artifact with no
    recorded facts returns empty fields and confidence "unknown" rather than
    an error. `verification_method`, `expiry_rule`, `tier_sla`, and
    `escalation_owner` are intentionally always `None` in this story --
    nothing populates them yet.
    """
    record = get_record(artifact_type, artifact_id)
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
    artifact_type: str | None = None, confidence: str | None = None
) -> list[dict[str, Any]]:
    """List every known LedgerRecord, optionally filtered by artifact_type and/or confidence.

    Lets a caller ask "what's stale" or "what's unknown" without already
    knowing every artifact's exact ID (CAP-4) -- `ledger_get_record` needs
    an exact `artifact_id`, and `ledger_get_coverage` only returns counts.
    Computed by replaying the relevant artifact-type log(s) (AD-3) -- never
    cached -- reusing the same single-pass fold `ledger_get_record` and
    `ledger_get_coverage` already use, so listing never re-reads a log once
    per artifact.

    If one artifact_type's log is corrupted, that type is not silently
    dropped: it is represented by exactly one sentinel record
    (`artifact_id="_log_format_error"`, `confidence="unknown"`) rather than
    being indistinguishable from "no artifacts of this type exist" --
    genuinely equivalent to `ledger_get_coverage`'s visibility for the same
    failure (AD-8), returned regardless of any `confidence` filter. Returns
    an empty list rather than raising for a nonexistent, empty-string, or
    reserved (`_`-prefixed) `artifact_type`, or when no record matches the
    given filters. `verification_method`, `expiry_rule`, `tier_sla`, and
    `escalation_owner` are intentionally always `None` in this story --
    nothing populates them yet.
    """
    records = list_records(artifact_type=artifact_type, confidence=confidence)
    return [
        {
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
        for record in records
    ]


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
