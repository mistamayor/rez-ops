"""Ledger-core MCP server (AD-1, AD-2): ledger-core is its own MCP server.

Exposes exactly one tool, a read/query surface over projection.py. No write
or mutation tool exists in this story -- ledger state can only ever be
changed by appending to the log (AD-3), and no MCP tool does that yet.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ledger_core.projection import get_record

mcp = FastMCP("ledger-core")


@mcp.tool(name="ledger_get_record")
def ledger_get_record(artifact_type: str, artifact_id: str) -> dict[str, Any]:
    """Return the current LedgerRecord for one artifact.

    Computed by purely replaying that artifact type's append-only event log
    (AD-3) -- never a cached or hand-edited value. An artifact with no
    recorded facts returns empty fields and confidence "unknown" rather than
    an error.
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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
