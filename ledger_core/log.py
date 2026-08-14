"""Append-only event log: writer/reader over ledger_data/{artifact_type}.log.md.

AD-3: every state change is appended as an immutable, timestamped event to a
git-committed, per-artifact-type markdown log. This module never rewrites an
existing line -- append_event only ever opens the file in append mode, and
read_events only ever reads.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shared.ledger_schema import RawFact

#: Default root for git-committed, per-artifact-type event logs (AD-3,
#: Consistency Conventions). Callers may override for testing so that no
#: test ever writes to the real, committed ledger_data/ directory.
DEFAULT_LEDGER_DATA_DIR = Path("ledger_data")

_LINE_RE = re.compile(
    r"^-\s+\((?P<event_type>[a-z_]+)\)\s+"
    r"(?P<timestamp>\S+)\s+"
    r"source=(?P<source>\S+)\s+"
    r"artifact=(?P<artifact_type>[^/]+)/(?P<artifact_id>\S+)\s+"
    r"fields=(?P<fields_json>.+)$"
)


#: The only event type this story ever writes or recognizes. Exposed so
#: ledger_core.projection can guard against folding a future, unrelated
#: event type into projected state as if it were a plain RawFact.
RAWFACT_EVENT_TYPE = "rawfact"


class LogFormatError(ValueError):
    """Raised when an event log line cannot be parsed."""


@dataclass(frozen=True)
class LogEvent:
    """One parsed line from an artifact-type event log."""

    event_type: str
    timestamp: str
    source: str
    artifact_type: str
    artifact_id: str
    fields: dict[str, Any]


def _log_path(artifact_type: str, ledger_dir: Path) -> Path:
    return ledger_dir / f"{artifact_type}.log.md"


def _format_event(fact: RawFact, timestamp: datetime) -> str:
    ts = timestamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fields_json = json.dumps(dict(fact.fields), sort_keys=True)
    return (
        f"- ({RAWFACT_EVENT_TYPE}) {ts} source={fact.source} "
        f"artifact={fact.artifact_type}/{fact.artifact_id} fields={fields_json}"
    )


def _is_naive(timestamp: datetime) -> bool:
    return timestamp.tzinfo is None or timestamp.tzinfo.utcoffset(timestamp) is None


def _ensure_ledger_dir(ledger_dir: Path) -> None:
    if ledger_dir.exists() and not ledger_dir.is_dir():
        raise NotADirectoryError(
            f"ledger_dir {ledger_dir} exists and is not a directory"
        )
    ledger_dir.mkdir(parents=True, exist_ok=True)


def append_event(
    fact: RawFact,
    *,
    ledger_dir: Path = DEFAULT_LEDGER_DATA_DIR,
    timestamp: datetime | None = None,
) -> None:
    """Append one RawFact as a new, immutable line in its artifact-type log.

    Never rewrites or truncates existing lines: the file is only ever opened
    in append mode, and directories are created as needed but existing
    content is left untouched (AD-3).

    `timestamp`, if given, must be timezone-aware. A naive datetime is
    ambiguous -- `astimezone(timezone.utc)` would silently treat it as local
    system time and convert it, recording a wrong timestamp -- so a naive
    value is rejected outright rather than guessed at.
    """
    if timestamp is not None and _is_naive(timestamp):
        raise ValueError(
            "append_event timestamp must be timezone-aware; got a naive "
            f"datetime ({timestamp!r}) which would be silently reinterpreted "
            "as local system time"
        )

    _ensure_ledger_dir(ledger_dir)
    path = _log_path(fact.artifact_type, ledger_dir)
    line = _format_event(fact, timestamp or datetime.now(timezone.utc))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def read_events(
    artifact_type: str,
    *,
    ledger_dir: Path = DEFAULT_LEDGER_DATA_DIR,
) -> list[LogEvent]:
    """Read and parse every event for an artifact type, oldest first.

    Returns an empty list if the log file doesn't exist yet -- querying an
    artifact type with no recorded facts is not an error.
    """
    path = _log_path(artifact_type, ledger_dir)
    if not path.exists():
        return []

    events: list[LogEvent] = []
    with path.open("r", encoding="utf-8") as handle:
        for lineno, raw_line in enumerate(handle, start=1):
            line = raw_line.rstrip("\n")
            if not line.strip():
                continue
            match = _LINE_RE.match(line)
            if not match:
                raise LogFormatError(
                    f"{path}:{lineno}: unparseable event log line: {line!r}"
                )
            groups = match.groupdict()
            try:
                fields = json.loads(groups["fields_json"])
            except json.JSONDecodeError as exc:
                raise LogFormatError(
                    f"{path}:{lineno}: invalid fields JSON: {exc}"
                ) from exc
            events.append(
                LogEvent(
                    event_type=groups["event_type"],
                    timestamp=groups["timestamp"],
                    source=groups["source"],
                    artifact_type=groups["artifact_type"],
                    artifact_id=groups["artifact_id"],
                    fields=fields,
                )
            )
    return events
