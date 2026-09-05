"""ActionProposal and the Policy Engine (AD-12, CAP-10, Story 13).

Lets Voice propose a system-state-changing *action* -- naming it from a
fixed, config-declared vocabulary, citing at least one `EvidenceBundle`
(Story 12) -- and have ledger-core alone compute whether it would be
`automatic`, `requires_approval`, or `denied`. Nothing in this module (or
anywhere else in this story) ever *acts* on that decision: it is recorded
and returned, never consumed by an executor of any kind (AD-12's Never
clause; there is no Executor in this phase).

`action` must be a top-level key declared in `rezops.policy.yaml` (repo-root,
git-tracked, read via `_load_policy`) -- never freeform, never any other
source. Each declared action's `impact` (`low`/`medium`/`high`) is *copied*
onto the created proposal; `policy_decision` is computed from that impact,
the minimum `confidence` across every cited `EvidenceBundle` (Story 12's
`list_evidence`, never an average), and whether the target's `tier_sla` is
currently known (via `ledger_core.projection.get_record` -- AD-9 already
defers the formula that would ever populate it, so this always resolves to
its most conservative reading against today's real data, honestly, not a
bug). Neither value is ever accepted as a caller-supplied argument -- both
are computed exclusively here, exactly like `EvidenceBundle.confidence`
(AD-11) and `LedgerRecord.tier_sla`/`confidence` (AD-5/AD-9) before it.

Unlike `Draft`/`EvidenceBundle` (one file, created-only), an `ActionProposal`
has a real lifecycle -- proposed, then decided -- so this module extends
`ledger_core/log.py`'s append-only-write discipline (AD-3) to a single,
project-wide, flat log, `ledger_data/action_proposals.log.md`: a `proposed`
event immediately followed by a `decided` event, both appended by the same
`create_action_proposal` call (there is no separate, later human-approval
step in this phase). `log.py`'s own line format is specific to `RawFact`
events keyed by `artifact_type`/`source`; this story's events are keyed by
`proposal_id` instead and carry a different fields shape, so its own
reader/writer are new here, not reused -- `log.py` is read only as a pattern
(the never-truncate append-only-write discipline), mirroring how
`drafts.py`/`evidence.py` already mirror rather than import from it.

`list_action_proposals` folds that one flat log into current per-proposal
state (AD-3: state is always a pure projection over the log, never
hand-edited in place) -- one record per `proposal_id`, in first-proposed
order.
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from ledger_core.evidence import list_evidence
from ledger_core.projection import get_record

#: Default root for git-committed ledger data. Kept equal in value to
#: `ledger_core.log.DEFAULT_LEDGER_DATA_DIR`/`ledger_core.drafts.DEFAULT_LEDGER_DATA_DIR`/
#: `ledger_core.evidence.DEFAULT_LEDGER_DATA_DIR` by convention (all four name
#: the same real, git-committed `ledger_data/` directory at the repo root).
#: Deliberately not imported from any of them -- same reasoning `drafts.py`
#: and `evidence.py` already give for their own copies.
DEFAULT_LEDGER_DATA_DIR = Path("ledger_data")

#: Default location of the policy config (AD-12, ARCHITECTURE-SPINE.md's
#: Structural Seed: repo-root, git-tracked, inputs only). Callers may
#: override for testing so no test ever depends on -- or mutates -- the
#: real, git-committed `rezops.policy.yaml`.
DEFAULT_POLICY_PATH = Path("rezops.policy.yaml")

#: Filename of the one flat, project-wide action-proposal log (AD-12,
#: ARCHITECTURE-SPINE.md's Structural Seed) -- not per-artifact-type like
#: `log.py`'s logs: proposals aren't themselves an artifact type in the
#: `RawFact` sense.
_ACTION_PROPOSALS_LOG_NAME = "action_proposals.log.md"

#: The two event types this story's log ever writes or recognizes.
_PROPOSED_EVENT_TYPE = "proposed"
_DECIDED_EVENT_TYPE = "decided"

#: `secrets.token_hex(3)` -> 6 hex chars of randomness in `proposal_id`'s
#: suffix, mirroring `drafts.py`'s/`evidence.py`'s `_RANDOM_SUFFIX_BYTES`.
_RANDOM_SUFFIX_BYTES = 3

#: Upper bound on attempts to find a `proposal_id` not already present in
#: the log, mirroring `drafts.py`'s/`evidence.py`'s
#: `_MAX_DRAFT_ID_ATTEMPTS`/`_MAX_EVIDENCE_ID_ATTEMPTS`. A random 6-hex-char
#: suffix collision within the same wall-clock second is already
#: vanishingly unlikely; this is defense in depth, not the primary
#: uniqueness mechanism.
_MAX_PROPOSAL_ID_ATTEMPTS = 10

#: Same identifier charset every other component in this project enforces
#: for `artifact_type`/`artifact_id` (`shared/ledger_schema/models.py`'s
#: `_IDENTIFIER_RE`, mirrored -- not imported -- by `drafts.py`/`evidence.py`
#: for the same reason: no whitespace/delimiter characters that could
#: corrupt a log line, no "/"/".." that could escape an intended directory).
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_-]+$")

#: The only three impact values a policy entry may declare (AD-12).
_VALID_IMPACTS = frozenset({"low", "medium", "high"})

#: Every field a `proposed` event's `fields` dict must carry -- checked
#: explicitly by `list_action_proposals` so a missing/malformed key raises
#: `ActionProposalLogFormatError`, not a raw `KeyError`.
_PROPOSED_FIELD_KEYS = (
    "action",
    "target_artifact_type",
    "target_artifact_id",
    "reason",
    "evidence",
    "impact",
)

#: One log line, either event type:
#: `- (proposed|decided) {timestamp} proposal_id={id} fields={json}`
_LINE_RE = re.compile(
    r"^-\s+\((?P<event_type>[a-z_]+)\)\s+"
    r"(?P<timestamp>\S+)\s+"
    r"proposal_id=(?P<proposal_id>\S+)\s+"
    r"fields=(?P<fields_json>.+)$"
)

#: A policy-file action header: an unindented `{action}:` line with nothing
#: else on it (the nested `impact: ...` line follows on the next line(s)).
_POLICY_ACTION_HEADER_RE = re.compile(r"^([A-Za-z0-9_-]+):\s*$")

#: A policy-file field line: an indented `{key}: {value}` line belonging to
#: the most recently seen action header.
_POLICY_FIELD_RE = re.compile(r"^\s+([A-Za-z0-9_-]+):\s*(\S.*)$")


class ActionProposalValidationError(ValueError):
    """Raised when a `create_action_proposal` argument is invalid.

    Raised before anything is appended to the log -- nothing is ever
    partially created (mirrors `DraftValidationError`/`EvidenceValidationError`).
    """


class ActionProposalLogFormatError(ValueError):
    """Raised when a line in `action_proposals.log.md` cannot be parsed.

    Every line this module ever reads was written by
    `create_action_proposal` itself, so this should never fire against real
    data -- it exists so a tampered-with or hand-edited log fails loudly and
    specifically, mirroring `ledger_core.log.LogFormatError`.
    """


class PolicyFileError(ValueError):
    """Raised when `rezops.policy.yaml` can't be parsed into the expected shape.

    This is a config-file problem, not a caller-input problem -- kept
    distinct from `ActionProposalValidationError`, which is always about
    what the *caller* supplied.
    """


@dataclass(frozen=True)
class ActionProposal:
    """One proposed, then policy-decided, system-state-changing action (AD-12).

    `impact` and `policy_decision` are computed exclusively by
    `create_action_proposal` -- never accepted as caller-supplied values.
    `evidence` holds the cited `EvidenceBundle.evidence_id`s exactly as
    given, not the bundles themselves. `decided_at` is always populated by
    `list_action_proposals`/`create_action_proposal` in this phase -- both
    events are always written together, by the same call, so there is no
    "proposed but not yet decided" state a caller can observe.
    """

    proposal_id: str
    action: str
    target_artifact_type: str
    target_artifact_id: str
    reason: str
    evidence: tuple[str, ...]
    impact: str
    policy_decision: str
    proposed_at: str
    decided_at: str | None


@dataclass(frozen=True)
class _ProposedEvent:
    proposal_id: str
    timestamp: str
    action: str
    target_artifact_type: str
    target_artifact_id: str
    reason: str
    evidence: tuple[str, ...]
    impact: str


@dataclass(frozen=True)
class _DecidedEvent:
    proposal_id: str
    timestamp: str
    policy_decision: str


def _require_identifier(field_name: str, value: Any) -> None:
    if not isinstance(value, str) or not _IDENTIFIER_RE.match(value):
        raise ActionProposalValidationError(
            f"{field_name} must be a non-empty string matching "
            f"{_IDENTIFIER_RE.pattern!r} (no slashes or whitespace); got {value!r}"
        )


def _require_nonblank_text(field_name: str, value: Any) -> None:
    """Require a non-empty, non-whitespace-only string.

    Deliberately never echoes `value` itself -- `reason` is opaque
    caller-supplied text this module never inspects or templates beyond
    this blank check, mirroring `drafts.py`'s/`evidence.py`'s identical
    discipline for `subject`/`body`/`claim`/`reasoning`.
    """
    if not isinstance(value, str) or not value.strip():
        raise ActionProposalValidationError(
            f"{field_name} must be a non-empty, non-whitespace-only string"
        )


# --- rezops.policy.yaml: the fixed action vocabulary (AD-12) ---------------


def _load_policy(policy_path: Path) -> dict[str, dict[str, str]]:
    """Parse `rezops.policy.yaml` into `{action: {"impact": "low"|"medium"|"high"}}`.

    A hand-rolled parser for a deliberately minimal YAML subset -- one
    unindented `{action}:` header per action, followed by one or more
    indented `{key}: {value}` lines -- rather than a new PyYAML dependency
    this story's own verification command ("uv sync -- no new dependency
    expected") doesn't call for; the project already hand-rolls its own
    formats for `log.py`/`drafts.py`/`evidence.py` rather than reaching for
    a library. Blank lines and `#`-prefixed comment lines are ignored
    anywhere. Every declared action's `impact` must be exactly `"low"`,
    `"medium"`, or `"high"` -- anything else raises `PolicyFileError`, since
    a malformed policy file must fail loudly rather than silently letting an
    action through with a nonsensical impact.

    Returns `{}` -- never raises -- if `policy_path` doesn't exist: no
    actions are declared, so every `action` name a caller supplies is
    correctly rejected as undeclared, rather than this function crashing on
    a config file that hasn't been created yet.
    """
    if not policy_path.exists():
        return {}

    text = policy_path.read_text(encoding="utf-8")
    policy: dict[str, dict[str, str]] = {}
    current_action: str | None = None

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        header_match = _POLICY_ACTION_HEADER_RE.match(line)
        if header_match:
            current_action = header_match.group(1)
            if current_action in policy:
                raise PolicyFileError(
                    f"{policy_path}:{lineno}: duplicate action key {current_action!r}"
                )
            policy[current_action] = {}
            continue

        field_match = _POLICY_FIELD_RE.match(line)
        if field_match and current_action is not None:
            key, value = field_match.group(1), field_match.group(2).strip()
            if key in policy[current_action]:
                raise PolicyFileError(
                    f"{policy_path}:{lineno}: duplicate field key {key!r} in "
                    f"action {current_action!r}"
                )
            if "#" in value:
                raise PolicyFileError(
                    f"{policy_path}:{lineno}: inline comments are not "
                    f"supported on field-value lines (got {value!r}) -- only "
                    "a whole-line comment starting with '#' is supported"
                )
            policy[current_action][key] = value
            continue

        raise PolicyFileError(f"{policy_path}:{lineno}: unparseable policy line: {line!r}")

    for action, entry in policy.items():
        impact = entry.get("impact")
        if impact not in _VALID_IMPACTS:
            raise PolicyFileError(
                f"{policy_path}: action {action!r} must declare impact as one "
                f"of {sorted(_VALID_IMPACTS)!r}; got {impact!r}"
            )

    return policy


# --- the frozen policy-decision rule ---------------------------------------


def _compute_policy_decision(
    *, impact: str, tier_sla_known: bool, min_confidence: float
) -> str:
    """The one documented policy-decision rule (AD-12, frozen in the story's
    Boundaries & Constraints).

    `denied` if `min_confidence < 0.5`; `automatic` only if `impact == "low"`
    AND `tier_sla_known` AND `min_confidence == 1.0`; `requires_approval`
    otherwise. Pure and deterministic: identical inputs always produce the
    identical decision -- no wall-clock, randomness, or hidden state.
    Against today's real data `tier_sla_known` is always `False` (AD-9's
    formula is deferred, so `ledger_core.projection.get_record` never
    populates `tier_sla`), so `automatic` never actually fires yet -- an
    honest characteristic of v1, not a bug (see the story's Design Notes).
    """
    if min_confidence < 0.5:
        return "denied"
    if impact == "low" and tier_sla_known and min_confidence == 1.0:
        return "automatic"
    return "requires_approval"


# --- action_proposals.log.md: append-only writer/reader --------------------


def _log_path(ledger_dir: Path) -> Path:
    return ledger_dir / _ACTION_PROPOSALS_LOG_NAME


def _ensure_ledger_dir(ledger_dir: Path) -> None:
    """Mirrors `ledger_core.log._ensure_ledger_dir`'s identical guard."""
    if ledger_dir.exists() and not ledger_dir.is_dir():
        raise NotADirectoryError(f"ledger_dir {ledger_dir} exists and is not a directory")
    ledger_dir.mkdir(parents=True, exist_ok=True)


def _generate_proposal_id(now: datetime, *, taken: frozenset[str]) -> str:
    """A sortable UTC timestamp plus a short random suffix, not already `taken`.

    Mirrors `drafts.py`'s/`evidence.py`'s `_generate_*_id`, extended with an
    explicit collision check against every `proposal_id` already present in
    the log -- there is no filesystem-level exclusive-create to lean on here
    (unlike one-file-per-record `Draft`/`EvidenceBundle`), since every
    proposal's events share one flat log file.
    """
    for _attempt in range(_MAX_PROPOSAL_ID_ATTEMPTS):
        ts = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        suffix = secrets.token_hex(_RANDOM_SUFFIX_BYTES)
        candidate = f"{ts}-{suffix}"
        if candidate not in taken:
            return candidate
    raise RuntimeError(
        f"could not generate a unique proposal_id after {_MAX_PROPOSAL_ID_ATTEMPTS} attempts"
    )


def _format_proposed_line(event: _ProposedEvent) -> str:
    fields = {
        "action": event.action,
        "target_artifact_type": event.target_artifact_type,
        "target_artifact_id": event.target_artifact_id,
        "reason": event.reason,
        "evidence": list(event.evidence),
        "impact": event.impact,
    }
    fields_json = json.dumps(fields, sort_keys=True)
    return (
        f"- ({_PROPOSED_EVENT_TYPE}) {event.timestamp} "
        f"proposal_id={event.proposal_id} fields={fields_json}"
    )


def _format_decided_line(event: _DecidedEvent) -> str:
    fields_json = json.dumps({"policy_decision": event.policy_decision}, sort_keys=True)
    return (
        f"- ({_DECIDED_EVENT_TYPE}) {event.timestamp} "
        f"proposal_id={event.proposal_id} fields={fields_json}"
    )


def _read_raw_lines(ledger_dir: Path) -> list[tuple[str, str, str, dict[str, Any]]]:
    """Read and parse every line of `action_proposals.log.md`, oldest first.

    Returns `[]` if the log doesn't exist yet. Each returned tuple is
    `(event_type, timestamp, proposal_id, fields)`. Raises
    `ActionProposalLogFormatError` on the first unparseable line or invalid
    fields JSON -- mirroring `ledger_core.log.read_events`'s identical
    fail-loud discipline (this is one flat log, not per-artifact-type, so
    there is no smaller unit than the whole file to isolate a corruption to).
    """
    path = _log_path(ledger_dir)
    if not path.exists():
        return []

    events: list[tuple[str, str, str, dict[str, Any]]] = []
    with path.open("r", encoding="utf-8") as handle:
        for lineno, raw_line in enumerate(handle, start=1):
            line = raw_line.rstrip("\n")
            if not line.strip():
                continue
            match = _LINE_RE.match(line)
            if not match:
                raise ActionProposalLogFormatError(
                    f"{path}:{lineno}: unparseable action-proposal log line: {line!r}"
                )
            groups = match.groupdict()
            try:
                fields = json.loads(groups["fields_json"])
            except json.JSONDecodeError as exc:
                raise ActionProposalLogFormatError(
                    f"{path}:{lineno}: invalid fields JSON: {exc}"
                ) from exc
            events.append(
                (groups["event_type"], groups["timestamp"], groups["proposal_id"], fields)
            )
    return events


def _append_lines(ledger_dir: Path, lines: Sequence[str]) -> None:
    """Append every line to `action_proposals.log.md`, in order, in one open.

    Opened in append mode only -- never rewrites or truncates existing
    content (AD-3, mirroring `ledger_core.log.append_event`).
    """
    _ensure_ledger_dir(ledger_dir)
    path = _log_path(ledger_dir)
    with path.open("a", encoding="utf-8") as handle:
        for line in lines:
            handle.write(line + "\n")


def create_action_proposal(
    action: str,
    target_artifact_type: str,
    target_artifact_id: str,
    reason: str,
    evidence: Sequence[str],
    *,
    ledger_dir: Path = DEFAULT_LEDGER_DATA_DIR,
    policy_path: Path = DEFAULT_POLICY_PATH,
) -> ActionProposal:
    """Create one ActionProposal: validate, decide, and append both events.

    Validates, in order, before anything is appended:

    - `target_artifact_type`/`target_artifact_id` against the same
      identifier charset every other component enforces (no existence check
      beyond that -- resolving a possibly-empty/unknown `LedgerRecord` is
      enough, the same non-validation precedent `create_draft` already
      established for its own `artifact_type`/`artifact_id`).
    - `reason` as a non-empty, non-whitespace-only string.
    - `evidence` as a list or tuple (never a bare string, which is
      technically a valid `Sequence[str]` but would silently iterate into
      single characters) that is non-empty and contains only non-blank
      `evidence_id` strings.
    - `action` against `rezops.policy.yaml`'s top-level keys (`_load_policy`)
      -- naming anything else is rejected before anything is appended.
    - only then, each `evidence_id` against `ledger_core.evidence.list_evidence`
      -- citing an id that doesn't resolve to a real `EvidenceBundle` is
      rejected before anything is appended.

    `impact` is copied, unmodified, from that action's config-declared value
    -- never computed here, never accepted as an argument (this function has
    no `impact` parameter at all). `policy_decision` is computed by
    `_compute_policy_decision` from that `impact`, the **minimum**
    `confidence` across every cited bundle (never an average -- the most
    cautious evidence sets the ceiling), and whether the target's
    `LedgerRecord.tier_sla` is currently non-`None`
    (`ledger_core.projection.get_record`) -- also never accepted as an
    argument (no `policy_decision` parameter either). Both are exclusively
    ledger-core-computed (AD-12).

    A `proposed` event (carrying `action`/`target_artifact_type`/
    `target_artifact_id`/`reason`/`evidence`/`impact`) is appended,
    immediately followed by a `decided` event (carrying `policy_decision`)
    -- both by this one call, to the same flat
    `{ledger_dir}/action_proposals.log.md` (AD-3/AD-12: there is no separate,
    later human-approval step in this phase). Both events share the same
    `proposed_at`/`decided_at` wall-clock timestamp -- they are written back
    to back within the same call, not across a real time gap.
    """
    _require_identifier("target_artifact_type", target_artifact_type)
    _require_identifier("target_artifact_id", target_artifact_id)
    _require_nonblank_text("reason", reason)

    if not isinstance(evidence, (list, tuple)):
        raise ActionProposalValidationError(
            "evidence must be a list or tuple of evidence_id strings, not "
            f"{type(evidence).__name__} -- a bare string is technically a "
            "valid Sequence[str] but silently iterates into single "
            f"characters; got {evidence!r}"
        )

    evidence_ids = tuple(evidence)
    if not evidence_ids:
        raise ActionProposalValidationError(
            "evidence must contain at least one evidence_id; got an empty list"
        )
    for evidence_id in evidence_ids:
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            raise ActionProposalValidationError(
                f"each evidence_id must be a non-empty, non-whitespace-only "
                f"string; got {evidence_id!r}"
            )

    policy = _load_policy(policy_path)
    if not isinstance(action, str) or action not in policy:
        raise ActionProposalValidationError(
            f"action {action!r} is not declared in {policy_path} -- the action "
            "vocabulary is exactly that file's top-level keys, never freeform "
            "(AD-12)"
        )
    impact = policy[action]["impact"]

    bundles_by_id = {
        bundle.evidence_id: bundle for bundle in list_evidence(ledger_dir=ledger_dir)
    }
    missing = [evidence_id for evidence_id in evidence_ids if evidence_id not in bundles_by_id]
    if missing:
        raise ActionProposalValidationError(
            f"evidence id(s) {missing!r} do not resolve to any existing "
            "EvidenceBundle (ledger_core.evidence.list_evidence)"
        )

    # Minimum across the cited bundles' confidence -- never an average, and
    # never the caller's choice of which to weight (AD-12). Duplicate
    # citations of the same evidence_id don't change the minimum either way.
    min_confidence = min(bundles_by_id[evidence_id].confidence for evidence_id in evidence_ids)

    record = get_record(target_artifact_type, target_artifact_id, ledger_dir=ledger_dir)
    tier_sla_known = record.tier_sla is not None

    policy_decision = _compute_policy_decision(
        impact=impact, tier_sla_known=tier_sla_known, min_confidence=min_confidence
    )

    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Defense in depth, not the primary uniqueness mechanism (see
    # `_MAX_PROPOSAL_ID_ATTEMPTS`) -- if the historical log is corrupted
    # (`ActionProposalLogFormatError`), proceed without the collision check
    # rather than let corrupted historical data permanently block every
    # future `create_action_proposal` call. The residual collision risk this
    # accepts is already vanishingly unlikely on top of that.
    try:
        existing_ids = frozenset(
            proposal_id for _, _, proposal_id, _ in _read_raw_lines(ledger_dir)
        )
    except ActionProposalLogFormatError:
        existing_ids = frozenset()
    proposal_id = _generate_proposal_id(now, taken=existing_ids)

    proposed_event = _ProposedEvent(
        proposal_id=proposal_id,
        timestamp=timestamp,
        action=action,
        target_artifact_type=target_artifact_type,
        target_artifact_id=target_artifact_id,
        reason=reason,
        evidence=evidence_ids,
        impact=impact,
    )
    decided_event = _DecidedEvent(
        proposal_id=proposal_id, timestamp=timestamp, policy_decision=policy_decision
    )
    _append_lines(
        ledger_dir,
        [_format_proposed_line(proposed_event), _format_decided_line(decided_event)],
    )

    return ActionProposal(
        proposal_id=proposal_id,
        action=action,
        target_artifact_type=target_artifact_type,
        target_artifact_id=target_artifact_id,
        reason=reason,
        evidence=evidence_ids,
        impact=impact,
        policy_decision=policy_decision,
        proposed_at=timestamp,
        decided_at=timestamp,
    )


def list_action_proposals(
    *,
    ledger_dir: Path = DEFAULT_LEDGER_DATA_DIR,
) -> list[ActionProposal]:
    """Fold `action_proposals.log.md` into current per-proposal state (AD-3).

    Returns one `ActionProposal` per distinct `proposal_id`, in first-seen
    (i.e. first-proposed) order. Never raises for a missing log file --
    returns `[]`, the same as "no proposal has ever been created".

    Every proposal this story ever writes carries both a `proposed` and a
    `decided` event, appended together by the same `create_action_proposal`
    call, so `policy_decision`/`decided_at` are always populated here in
    practice; the fold still tolerates an *incomplete* history gracefully
    rather than crashing: a `decided` event for a `proposal_id` with no
    prior `proposed` event is ignored (there is no base record to decide),
    and a `proposed` event with no matching `decided` event yet simply
    yields `policy_decision=None`/`decided_at=None` for that proposal,
    rather than raising.
    """
    raw_events = _read_raw_lines(ledger_dir)

    state: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for event_type, timestamp, proposal_id, fields in raw_events:
        if event_type == _PROPOSED_EVENT_TYPE:
            missing_keys = [key for key in _PROPOSED_FIELD_KEYS if key not in fields]
            if missing_keys:
                raise ActionProposalLogFormatError(
                    f"proposed event for proposal_id={proposal_id!r} is missing "
                    f"field(s) {missing_keys!r}"
                )
            if proposal_id not in state:
                order.append(proposal_id)
            state[proposal_id] = {
                "action": fields["action"],
                "target_artifact_type": fields["target_artifact_type"],
                "target_artifact_id": fields["target_artifact_id"],
                "reason": fields["reason"],
                "evidence": tuple(fields["evidence"]),
                "impact": fields["impact"],
                "proposed_at": timestamp,
                "policy_decision": None,
                "decided_at": None,
            }
        elif event_type == _DECIDED_EVENT_TYPE:
            if proposal_id in state:
                if "policy_decision" not in fields:
                    raise ActionProposalLogFormatError(
                        f"decided event for proposal_id={proposal_id!r} is "
                        "missing field 'policy_decision'"
                    )
                if state[proposal_id]["policy_decision"] is not None:
                    raise ActionProposalLogFormatError(
                        f"duplicate decided event for proposal_id={proposal_id!r} "
                        "-- a real create_action_proposal call never writes "
                        "more than one decided event per proposal"
                    )
                state[proposal_id]["policy_decision"] = fields["policy_decision"]
                state[proposal_id]["decided_at"] = timestamp
            # A decided event with no prior proposed event has nothing to
            # attach to -- ignored rather than raising (AD-8 spirit).
        else:
            raise ActionProposalLogFormatError(
                f"unrecognized action-proposal event type {event_type!r}"
            )

    return [
        ActionProposal(
            proposal_id=proposal_id,
            action=state[proposal_id]["action"],
            target_artifact_type=state[proposal_id]["target_artifact_type"],
            target_artifact_id=state[proposal_id]["target_artifact_id"],
            reason=state[proposal_id]["reason"],
            evidence=state[proposal_id]["evidence"],
            impact=state[proposal_id]["impact"],
            policy_decision=state[proposal_id]["policy_decision"],
            proposed_at=state[proposal_id]["proposed_at"],
            decided_at=state[proposal_id]["decided_at"],
        )
        for proposal_id in order
    ]
