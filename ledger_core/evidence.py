"""Evidence-backed claims: `EvidenceBundle` / `EvidenceRef` (AD-11, CAP-9, Story 12).

Lets Voice make a reasoning-layer claim ("this runbook looks stale") as a
structured, citable object instead of unattributed chat prose. Each
`EvidenceRef` names one artifact (`artifact_type`/`artifact_id`) and cites
either the `source` of a specific ingested `RawFact` or the `field` name of a
computed `LedgerRecord` value -- never both, never neither (validated at
`EvidenceRef` construction, mirroring `shared/ledger_schema/models.py`'s
`RawFact`/`LedgerRecord` construction-time validation).

`EvidenceBundle.confidence` is computed exclusively here, in
`create_evidence_bundle`, as the fraction of citations that resolve against
*current* ledger state -- never accepted as a caller-supplied value (AD-11,
extending AD-5/AD-9's ledger-core-exclusive-computation principle to the
reasoning layer). Resolution is checked once, at creation time, and baked
into the bundle: a bundle is a point-in-time snapshot, like a `LedgerRecord`,
never re-validated on read.

Like `ledger_core/drafts.py`'s `Draft` (AD-6) -- the closest precedent, also
Voice-only, also not connector-facing -- an `EvidenceBundle` is new content
ledger-core itself authors, not an append-only observed fact replayed from a
per-artifact-type event log, so it doesn't fit `projection.py`/`log.py`'s
model. This module mirrors `drafts.py`'s file-per-record shape (frontmatter +
body, `_generate_*_id`-style id generation, `_escape_frontmatter_value`/parse
round-trip, per-file error isolation in `list_evidence` -- AD-8) rather than
importing from it, the same way `drafts.py` itself mirrors rather than
imports from `log.py`.

Despite ARCHITECTURE-SPINE.md's AD-11 literal wording ("the shared schema
module adds `EvidenceBundle`"), this type lives here, in `ledger_core/`, not
`shared/ledger_schema/` -- see the story's Design Notes: `shared/` exists for
the connector-writable RawFact/LedgerRecord contract, and nothing here is
connector-relevant, exactly like `Draft` before it.

`create_evidence_bundle` is the *only* place anything is ever written under
`{ledger_dir}/evidence/` -- one file per bundle, created-only (no
update/delete): a bundle is never itself approved or denied, only ever cited
by a later `ActionProposal` (Story 13), so it needs no lifecycle beyond
creation.
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from ledger_core.log import LogFormatError, read_events
from ledger_core.projection import get_record

#: Default root for git-committed ledger data. Deliberately *not* imported
#: from `ledger_core.log`/`ledger_core.drafts` -- kept equal in value to
#: `ledger_core.log.DEFAULT_LEDGER_DATA_DIR` by convention (both name the
#: same real, git-committed `ledger_data/` directory at the repo root).
DEFAULT_LEDGER_DATA_DIR = Path("ledger_data")

#: Subdirectory under `ledger_dir` where every bundle file lives (AD-11,
#: ARCHITECTURE-SPINE.md's Structural Seed: `ledger_data/evidence/`).
_EVIDENCE_SUBDIR = "evidence"

#: Same identifier charset `shared/ledger_schema/models.py` enforces for
#: RawFact's/LedgerRecord's `artifact_type`/`artifact_id` (`_IDENTIFIER_RE`
#: there), and `ledger_core/drafts.py` already mirrors for the same reason:
#: no whitespace/delimiter characters that could corrupt a frontmatter line
#: or the evidence-citation JSON, and no "/"/".." that could escape the
#: intended directory if this value were ever used to build a path.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_-]+$")

#: `secrets.token_hex(3)` -> 6 hex chars of randomness in `evidence_id`'s
#: suffix, mirroring `drafts.py`'s `_RANDOM_SUFFIX_BYTES`.
_RANDOM_SUFFIX_BYTES = 3

#: Upper bound on attempts to find a filename not already taken, mirroring
#: `drafts.py`'s `_MAX_DRAFT_ID_ATTEMPTS`.
_MAX_EVIDENCE_ID_ATTEMPTS = 10

#: The only `LedgerRecord` attribute names a field-citation may cite
#: (`shared/ledger_schema/models.py`'s `LedgerRecord` fields, minus
#: `artifact_type`/`artifact_id` -- those identify the artifact, they aren't
#: evidence about it -- and minus `confidence`, deliberately excluded: it's a
#: meta-judgment about verification status (`agent-verified`/`manual`/
#: `unknown`), not a fact a separate claim can point to as evidence, and
#: `"unknown"` in particular means "we know nothing", which would otherwise
#: perversely resolve as `True` via `_field_is_populated`'s truthy check).
#: A `ref.field` outside this whitelist never resolves (`_resolve_ref`
#: returns `False`) -- including any dunder/method name `getattr` would
#: otherwise happily look up on the record instance.
_CITABLE_FIELDS = frozenset(
    {
        "last_verified",
        "verification_method",
        "expiry_rule",
        "tier_sla",
        "escalation_owner",
        "fields",
    }
)

#: Sentinel value `list_evidence` uses for every field of the one synthetic
#: EvidenceBundle it emits in place of a corrupted/tampered bundle file it
#: can't parse (`EvidenceFileFormatError`) -- except `evidence_id`, which
#: stays the real, still-useful filename stem, `confidence`, which stays
#: `0.0` (the type's own float, never a string sentinel), and `evidence`,
#: which stays `()` since it's typed `tuple[EvidenceRef, ...]`. Mirrors
#: `ledger_core.drafts`'s `DRAFT_FORMAT_ERROR_MARKER` (AD-8): a corrupted
#: bundle must not silently vanish from the list, nor abort listing every
#: other, healthy bundle.
EVIDENCE_FORMAT_ERROR_MARKER = "error:evidence_format_error"

#: Frontmatter keys, in the order they're written. `evidence_id` is not among
#: them -- it's the filename itself, mirroring `drafts.py`'s `draft_id`.
#: `reasoning` is likewise not among them -- like `Draft.body`, it's stored
#: as the file's body, not a single-line frontmatter field, since reasoning
#: text may be long and multi-line.
_FRONTMATTER_KEYS = (
    "claim",
    "confidence",
    "evidence",
    "generated_at",
)


class EvidenceValidationError(ValueError):
    """Raised when an `EvidenceRef`/`create_evidence_bundle` argument is invalid.

    Raised before any file is written -- nothing is ever partially created.
    """


class EvidenceFileFormatError(ValueError):
    """Raised when a file under `{ledger_dir}/evidence/` can't be parsed back.

    Every bundle `list_evidence` ever reads was written by
    `create_evidence_bundle` itself, so this should never fire against real
    data; it exists so a tampered-with or hand-edited file fails loudly and
    specifically rather than as an opaque `IndexError`/`KeyError` deep in the
    parser.
    """


@dataclass(frozen=True)
class EvidenceRef:
    """One structured citation: one artifact, and exactly one of `source`/`field`.

    `source` cites a specific ingested `RawFact`'s `source` value (resolves
    if that artifact's log has an event with that exact `source`). `field`
    cites the name of a computed `LedgerRecord` value (resolves if
    `ledger_core.projection.get_record(artifact_type, artifact_id)` has a
    non-empty value for that attribute). Never both, never neither --
    enforced here, at construction time, exactly like
    `shared.ledger_schema.RawFact`/`LedgerRecord` validate their own shape in
    `__post_init__` before anything downstream can use a malformed instance.
    """

    artifact_type: str
    artifact_id: str
    source: str | None = None
    field: str | None = None

    def __post_init__(self) -> None:
        _require_identifier("artifact_type", self.artifact_type)
        _require_identifier("artifact_id", self.artifact_id)

        if (self.source is None) == (self.field is None):
            raise EvidenceValidationError(
                "EvidenceRef must set exactly one of source/field; got "
                f"source={self.source!r}, field={self.field!r}"
            )
        if self.source is not None:
            _require_nonblank_text("EvidenceRef.source", self.source)
        if self.field is not None:
            _require_nonblank_text("EvidenceRef.field", self.field)


@dataclass(frozen=True)
class EvidenceBundle:
    """One evidence-backed reasoning-layer claim (AD-11, CAP-9).

    `confidence` (claim-level plausibility, a float in `[0.0, 1.0]`) is a
    distinct concept from `LedgerRecord.confidence`'s
    `agent-verified`/`manual`/`unknown` enum (AD-5) -- the two are never
    conflated. It is computed exclusively by `create_evidence_bundle`, never
    accepted as a caller-supplied value.
    """

    evidence_id: str
    claim: str
    confidence: float
    evidence: tuple[EvidenceRef, ...]
    reasoning: str
    generated_at: str


def _require_identifier(field_name: str, value: Any) -> None:
    if not isinstance(value, str) or not _IDENTIFIER_RE.match(value):
        raise EvidenceValidationError(
            f"{field_name} must be a non-empty string matching "
            f"{_IDENTIFIER_RE.pattern!r} (no slashes or whitespace); got {value!r}"
        )


def _require_nonblank_text(field_name: str, value: Any) -> None:
    """Require a non-empty, non-whitespace-only string.

    Deliberately never echoes `value` itself for `claim`/`reasoning` -- like
    `drafts.py`'s `_require_nonblank_text`, these are opaque caller-supplied
    text this module never inspects or templates beyond this blank check.
    `EvidenceRef.source`/`.field` are narrower, connector-provenance-shaped
    identifiers rather than free text, so echoing those is fine and more
    useful for debugging a malformed citation.
    """
    if not isinstance(value, str) or not value.strip():
        if field_name in ("claim", "reasoning"):
            raise EvidenceValidationError(
                f"{field_name} must be a non-empty, non-whitespace-only string"
            )
        raise EvidenceValidationError(
            f"{field_name} must be a non-empty, non-whitespace-only string; "
            f"got {value!r}"
        )


def _ensure_evidence_dir(evidence_dir: Path) -> None:
    """Mirrors `ledger_core.log._ensure_ledger_dir`/`drafts._ensure_drafts_dir`."""
    if evidence_dir.exists() and not evidence_dir.is_dir():
        raise NotADirectoryError(
            f"evidence_dir {evidence_dir} exists and is not a directory"
        )
    evidence_dir.mkdir(parents=True, exist_ok=True)


def _generate_evidence_id(now: datetime) -> str:
    """A sortable UTC timestamp plus a short random suffix (mirrors `drafts.py`)."""
    ts = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = secrets.token_hex(_RANDOM_SUFFIX_BYTES)
    return f"{ts}-{suffix}"


def _escape_frontmatter_value(value: str) -> str:
    """Collapse embedded newlines to spaces for a single-line frontmatter field.

    Mirrors `drafts.py`'s function of the same name -- a serialization-safety
    measure over how `claim` is *stored*, not a rejection or interpretation
    of its content. `reasoning` (the drafted-claim's free-form justification
    text) is never passed through this function and is stored exactly as
    given, like `Draft.body`.
    """
    return " ".join(value.splitlines())


def _field_is_populated(value: Any) -> bool:
    """True iff a `LedgerRecord` attribute counts as a "non-empty value".

    A `str` counts only if non-blank after stripping (mirrors
    `projection._compute_escalation_owner`'s own blank-string handling); any
    other non-`None` value (e.g. `LedgerRecord.fields`, a non-empty mapping)
    counts if it is truthy. `None` (an unresolved attribute, or a
    non-existent field name `getattr`'s default falls back to) never counts.
    """
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


def _resolve_ref(ref: EvidenceRef, *, ledger_dir: Path) -> bool:
    """Resolve one citation against *current* ledger state.

    A source-citation resolves if `ref.artifact_type`'s log has an event
    for that exact `artifact_id` with that exact `source`
    (`ledger_core.log.read_events`) -- both, never `source` alone: one
    artifact-type log holds events for every artifact of that type, so
    checking only `source` would let a citation naming one `artifact_id`
    resolve off a same-named `source` that only ever appeared against a
    *different* artifact_id, defeating the whole reason `EvidenceRef` is
    scoped to one artifact. A field-citation resolves if `ref.field` is one
    of `_CITABLE_FIELDS` and `ledger_core.projection.get_record` reports a
    non-empty value for that attribute name -- a field name outside that
    whitelist never resolves (returns `False`, not a lookup against
    arbitrary object attributes). Either check fails open -- a corrupted
    artifact-type log (`LogFormatError`) counts the citation as unresolved
    rather than aborting bundle creation (AD-8), the same
    graceful-degradation discipline `drafts.create_draft`'s
    `escalation_owner` lookup already applies.
    """
    if ref.source is not None:
        try:
            events = read_events(ref.artifact_type, ledger_dir=ledger_dir)
        except LogFormatError:
            return False
        return any(
            event.artifact_id == ref.artifact_id and event.source == ref.source
            for event in events
        )

    if ref.field not in _CITABLE_FIELDS:
        return False

    try:
        record = get_record(ref.artifact_type, ref.artifact_id, ledger_dir=ledger_dir)
    except LogFormatError:
        return False
    return _field_is_populated(getattr(record, ref.field, None))


def _render_bundle(bundle: EvidenceBundle) -> str:
    evidence_json = json.dumps(
        [
            {
                "artifact_type": ref.artifact_type,
                "artifact_id": ref.artifact_id,
                "source": ref.source,
                "field": ref.field,
            }
            for ref in bundle.evidence
        ],
        sort_keys=True,
    )
    values = {
        "claim": _escape_frontmatter_value(bundle.claim).strip(),
        # `repr` (not `str`) so a value like `2/3` round-trips through
        # `float(...)` byte-for-byte as `0.6666666666666666` -- never
        # silently rounded to a coarser display form.
        "confidence": repr(bundle.confidence),
        "evidence": evidence_json,
        "generated_at": bundle.generated_at,
    }
    frontmatter = "\n".join(f"{key}: {values[key]}" for key in _FRONTMATTER_KEYS)
    reasoning = bundle.reasoning.rstrip("\n")
    return f"---\n{frontmatter}\n---\n\n{reasoning}\n"


def _parse_bundle_file(path: Path) -> EvidenceBundle:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise EvidenceFileFormatError(f"{path}: missing frontmatter opening fence")
    end = next((i for i in range(1, len(lines)) if lines[i] == "---"), None)
    if end is None:
        raise EvidenceFileFormatError(f"{path}: frontmatter is not terminated")

    meta: dict[str, str] = {}
    for line in lines[1:end]:
        if ":" not in line:
            raise EvidenceFileFormatError(
                f"{path}: unparseable frontmatter line: {line!r}"
            )
        key, value = line.split(":", 1)
        key = key.strip()
        if key in meta:
            # Defense in depth, mirroring `drafts.py`'s identical duplicate-key
            # guard: escaping `claim` at write time already closes the
            # practical path for a caller-supplied value to inject a second
            # "key: value" line, but the parser itself should not be more
            # lenient than that.
            raise EvidenceFileFormatError(f"{path}: duplicate frontmatter key {key!r}")
        meta[key] = value.strip()

    missing = [key for key in _FRONTMATTER_KEYS if key not in meta]
    if missing:
        raise EvidenceFileFormatError(
            f"{path}: missing frontmatter field(s) {missing!r}"
        )

    try:
        confidence = float(meta["confidence"])
    except ValueError as exc:
        raise EvidenceFileFormatError(
            f"{path}: invalid confidence value {meta['confidence']!r}"
        ) from exc
    # `float("nan")` parses without raising, and `nan < 0.0` /
    # `nan > 1.0` are both False, so the range check alone wouldn't catch
    # it -- checked explicitly, consistent with how every other parsed
    # field here is validated rather than trusted as-is.
    if confidence != confidence or not (0.0 <= confidence <= 1.0):
        raise EvidenceFileFormatError(
            f"{path}: confidence value {confidence!r} is out of range [0.0, 1.0]"
        )

    try:
        raw_evidence = json.loads(meta["evidence"])
    except json.JSONDecodeError as exc:
        raise EvidenceFileFormatError(f"{path}: invalid evidence JSON: {exc}") from exc

    if not isinstance(raw_evidence, list):
        raise EvidenceFileFormatError(
            f"{path}: evidence field must be a JSON array, got {type(raw_evidence).__name__}"
        )

    try:
        refs = tuple(
            EvidenceRef(
                artifact_type=item["artifact_type"],
                artifact_id=item["artifact_id"],
                source=item.get("source"),
                field=item.get("field"),
            )
            for item in raw_evidence
        )
    except (KeyError, TypeError, AttributeError, EvidenceValidationError) as exc:
        raise EvidenceFileFormatError(f"{path}: invalid evidence citation: {exc}") from exc

    body = "\n".join(lines[end + 1 :]).lstrip("\n")

    return EvidenceBundle(
        evidence_id=path.stem,
        claim=meta["claim"],
        confidence=confidence,
        evidence=refs,
        reasoning=body,
        generated_at=meta["generated_at"],
    )


def create_evidence_bundle(
    claim: str,
    reasoning: str,
    evidence: Sequence[EvidenceRef],
    *,
    ledger_dir: Path = DEFAULT_LEDGER_DATA_DIR,
) -> EvidenceBundle:
    """Create one evidence bundle and write it to `{ledger_dir}/evidence/{evidence_id}.md`.

    Validates `claim`/`reasoning` as non-blank strings and `evidence` as a
    non-empty sequence of `EvidenceRef` (each already self-validated at
    construction -- exactly one of `source`/`field` set); raises
    `EvidenceValidationError` and writes nothing if any check fails.

    `confidence` is computed here, exclusively, as `resolved / total` over
    the *distinct* citations in `evidence` -- never accepted as an
    argument, so a caller has no way to influence it (AD-11). Citations are
    de-duplicated by their full `(artifact_type, artifact_id, source,
    field)` tuple before that fraction is computed, so citing the same
    resolving fact three times counts once, not three times -- otherwise a
    bundle could inflate its confidence past what the distinct set of
    citations would produce, without adding any real evidence (`evidence`
    on the returned bundle still holds every citation as given, duplicates
    included -- only the confidence computation de-duplicates). Resolution
    (`_resolve_ref`) is checked exactly once, right now, against current
    ledger state; the result is baked into the bundle and never
    re-checked -- a bundle is a point-in-time snapshot, like a
    `LedgerRecord`. A bundle citing nothing that resolves still gets
    created, with `confidence: 0.0` -- never rejected (matching this
    project's standing refusal to hide bad states rather than surface
    them).

    The only side effect is writing exactly one new file, opened with `"x"`
    (exclusive create) so this can never silently overwrite an existing
    bundle -- mirroring `drafts.create_draft`'s identical discipline.
    `evidence_id` collisions (same wall-clock second) are handled by
    regenerating a new random suffix and retrying, up to
    `_MAX_EVIDENCE_ID_ATTEMPTS` times.
    """
    _require_nonblank_text("claim", claim)
    _require_nonblank_text("reasoning", reasoning)

    refs = tuple(evidence)
    if not refs:
        raise EvidenceValidationError(
            "evidence must contain at least one EvidenceRef; got an empty list"
        )
    for ref in refs:
        if not isinstance(ref, EvidenceRef):
            raise EvidenceValidationError(
                f"evidence must be a sequence of EvidenceRef; got {type(ref).__name__}"
            )

    # De-duplicate by the full (artifact_type, artifact_id, source, field)
    # tuple before computing confidence -- a bundle that cites the same
    # resolving fact three times must not thereby inflate its confidence
    # past what the distinct set of citations would produce (each repeated,
    # identical citation counts once).
    distinct_refs = {
        (ref.artifact_type, ref.artifact_id, ref.source, ref.field): ref for ref in refs
    }.values()
    resolved_count = sum(
        1 for ref in distinct_refs if _resolve_ref(ref, ledger_dir=ledger_dir)
    )
    confidence = resolved_count / len(distinct_refs)

    evidence_dir = ledger_dir / _EVIDENCE_SUBDIR
    _ensure_evidence_dir(evidence_dir)

    now = datetime.now(timezone.utc)
    generated_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    evidence_id: str | None = None
    bundle: EvidenceBundle | None = None
    for _attempt in range(_MAX_EVIDENCE_ID_ATTEMPTS):
        candidate_id = _generate_evidence_id(now)
        candidate_path = evidence_dir / f"{candidate_id}.md"
        bundle = EvidenceBundle(
            evidence_id=candidate_id,
            claim=claim,
            confidence=confidence,
            evidence=refs,
            reasoning=reasoning,
            generated_at=generated_at,
        )
        try:
            with candidate_path.open("x", encoding="utf-8") as handle:
                handle.write(_render_bundle(bundle))
        except FileExistsError:
            continue
        except Exception:
            # The exclusive create ("x" mode) already succeeded by the time
            # any other exception could be raised here, so an empty or
            # partially-written file may now exist with no bundle ever
            # returned for it. Clean it up rather than leaving an orphaned
            # file behind (mirrors `drafts.create_draft`).
            candidate_path.unlink(missing_ok=True)
            raise
        evidence_id = candidate_id
        break

    if evidence_id is None or bundle is None:
        raise RuntimeError(
            f"could not generate a unique evidence_id after "
            f"{_MAX_EVIDENCE_ID_ATTEMPTS} attempts"
        )

    return bundle


def list_evidence(
    *,
    ledger_dir: Path = DEFAULT_LEDGER_DATA_DIR,
) -> list[EvidenceBundle]:
    """List every bundle under `{ledger_dir}/evidence/`.

    Never raises for a missing `ledger_dir` or `evidence/` subdirectory --
    returns `[]`, the same as "no bundles exist yet".

    If one bundle file fails to parse (`EvidenceFileFormatError` -- a
    tampered-with or hand-edited file) or simply can't be read (`OSError` --
    e.g. a permissions problem -- or `UnicodeDecodeError` -- invalid
    encoding), that failure is isolated to its own file: it is represented
    by exactly one sentinel EvidenceBundle (`evidence_id` stays that file's
    real filename stem; every other field is `EVIDENCE_FORMAT_ERROR_MARKER`,
    `0.0`, or `()` as appropriate to its type) rather than aborting listing
    for every other, healthy bundle (AD-8, mirroring `drafts.list_drafts`'s
    identical isolation).
    """
    evidence_dir = ledger_dir / _EVIDENCE_SUBDIR
    if not evidence_dir.exists() or not evidence_dir.is_dir():
        return []

    bundles: list[EvidenceBundle] = []
    for path in sorted(evidence_dir.iterdir()):
        if not path.is_file() or path.suffix != ".md":
            continue
        try:
            bundle = _parse_bundle_file(path)
        except (EvidenceFileFormatError, OSError, UnicodeDecodeError):
            bundles.append(
                EvidenceBundle(
                    evidence_id=path.stem,
                    claim=EVIDENCE_FORMAT_ERROR_MARKER,
                    confidence=0.0,
                    evidence=(),
                    reasoning="",
                    generated_at=EVIDENCE_FORMAT_ERROR_MARKER,
                )
            )
            continue
        bundles.append(bundle)
    return bundles
