"""Shared ledger schema: the RawFact / LedgerRecord split (AD-4, AD-9).

RawFact is the only shape a connector may construct: raw observed data plus a
`source` provenance reference. LedgerRecord is ledger-core-only, computed
state. Nothing may construct a RawFact carrying a LedgerRecord-only field --
that is a schema violation caught here, at construction time, before an event
is ever appended to the log.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

#: Fields that only ledger-core may ever set (AD-9). A RawFact's observed
#: `fields` mapping must never contain any of these keys.
LEDGER_ONLY_FIELDS = frozenset(
    {
        "last_verified",
        "verification_method",
        "expiry_rule",
        "tier_sla",
        "escalation_owner",
        "confidence",
    }
)

#: The only confidence states ledger-core may report (AD-5, AD-9). No
#: confidence-scoring formula is implemented yet -- "unknown" is the only
#: value this story ever produces.
CONFIDENCE_VALUES = frozenset({"agent-verified", "manual", "unknown"})


class SchemaValidationError(ValueError):
    """Raised when a RawFact or LedgerRecord is constructed with an invalid shape."""


#: Strict charset for `artifact_type` / `artifact_id`. These values flow
#: unescaped into a fixed-format log line (ledger_core/log.py's
#: `_format_event`) and `artifact_type` additionally becomes part of a log
#: filename (`_log_path`). Rejecting anything outside this charset closes two
#: issues at once: a value containing whitespace or the line's own delimiter
#: syntax could corrupt the log line (surfacing only later as a confusing
#: LogFormatError at read time), and a value containing "/" or ".." could
#: otherwise escape the intended ledger_data/ directory when used to build a
#: filename.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_-]+$")

#: Charset for `source`. Slightly wider than `_IDENTIFIER_RE` because
#: provenance references conventionally look like "connector:id" (e.g.
#: "synthetic:test", "jira:PROJ-123") -- but still rejects slashes,
#: whitespace, and whitespace-only strings for the same reasons as above.
_SOURCE_RE = re.compile(r"^[A-Za-z0-9_:-]+$")

#: JSON-primitive scalar types a RawFact.fields value may hold. Restricting
#: to these (rather than allowing arbitrary nested list/dict values) closes
#: two issues at once: it guarantees every fields value is JSON-serializable
#: at construction time -- instead of failing later as a generic TypeError
#: inside ledger_core.log.append_event -- and it means freezing the
#: top-level `fields` mapping is sufficient; there are no nested mutable
#: containers left to worry about.
_JSON_SCALAR_TYPES = (str, int, float, bool, type(None))


def _validate_identifier(owner: str, field_name: str, value: str) -> None:
    if not _IDENTIFIER_RE.match(value):
        raise SchemaValidationError(
            f"{owner}.{field_name} must be a non-empty string matching "
            f"{_IDENTIFIER_RE.pattern!r} (no slashes or whitespace); got {value!r}"
        )


def _validate_source(owner: str, value: str) -> None:
    if not _SOURCE_RE.match(value):
        raise SchemaValidationError(
            f"{owner}.source must be a non-empty string matching "
            f"{_SOURCE_RE.pattern!r} (no slashes or whitespace); got {value!r}"
        )


def _validate_fields_are_json_scalars(owner: str, fields: Mapping[str, Any]) -> None:
    for key, value in fields.items():
        if not isinstance(value, _JSON_SCALAR_TYPES):
            raise SchemaValidationError(
                f"{owner}.fields[{key!r}] must be a JSON-primitive scalar "
                "(str, int, float, bool, or None), not a nested list/dict or "
                f"other object; got {type(value).__name__}"
            )


def _freeze_fields(fields: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(fields) if fields else {})


@dataclass(frozen=True)
class RawFact:
    """Connector-writable observed data plus a provenance `source` reference.

    Never carries a confidence value or any other LedgerRecord-only field --
    constructing one that does raises SchemaValidationError (AD-9).
    """

    artifact_type: str
    artifact_id: str
    source: str
    fields: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_identifier("RawFact", "artifact_type", self.artifact_type)
        _validate_identifier("RawFact", "artifact_id", self.artifact_id)
        _validate_source("RawFact", self.source)

        offending = LEDGER_ONLY_FIELDS.intersection(self.fields.keys())
        if offending:
            raise SchemaValidationError(
                "RawFact.fields may not contain ledger-core-only field(s) "
                f"{sorted(offending)!r} -- these are computed exclusively by "
                "ledger-core (AD-9)."
            )

        _validate_fields_are_json_scalars("RawFact", self.fields)

        # Freeze the mapping so a caller can't mutate `fields` after
        # construction and smuggle a reserved key in after validation ran.
        object.__setattr__(self, "fields", _freeze_fields(self.fields))


@dataclass(frozen=True)
class LedgerRecord:
    """Ledger-core-only, computed state for one artifact (AD-9).

    Constructed exclusively by ledger_core.projection.get_record -- never by
    a connector. `fields` holds the latest observed values folded in from the
    artifact's RawFact history; the remaining attributes are ledger-core's
    own computed verification/ownership state.
    """

    artifact_type: str
    artifact_id: str
    fields: Mapping[str, Any] = field(default_factory=dict)
    last_verified: str | None = None
    verification_method: str | None = None
    expiry_rule: str | None = None
    tier_sla: str | None = None
    escalation_owner: str | None = None
    confidence: str = "unknown"

    def __post_init__(self) -> None:
        _validate_identifier("LedgerRecord", "artifact_type", self.artifact_type)
        _validate_identifier("LedgerRecord", "artifact_id", self.artifact_id)
        if self.confidence not in CONFIDENCE_VALUES:
            raise SchemaValidationError(
                f"LedgerRecord.confidence must be one of {sorted(CONFIDENCE_VALUES)!r}, "
                f"got {self.confidence!r}"
            )
        object.__setattr__(self, "fields", _freeze_fields(self.fields))
