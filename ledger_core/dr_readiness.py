"""DR readiness summary (AD-1/AD-3, CAP-4, Story 18): pure aggregation, no new reads.

`get_dr_readiness_summary` answers "what's our overall DR posture" by rolling
up, per tier declared in `rezops.tiers.yaml`, the risk already computed for
every artifact assigned to it. Nothing here computes risk a second way:
every per-artifact `risk` value is exactly what
`ledger_core.projection.get_record` would return for that
`(artifact_type, artifact_id)`, called once per assigned artifact (never a
parallel reimplementation of `_compute_tier_and_risk`'s frozen formula --
Story 17). This mirrors `briefing.py`'s own discipline: a frozen dataclass +
one composing function, over already-existing reads.

"Three independent axes" (application tier, infrastructure, data centres) in
this project's intent resolves to however many tiers are actually declared
in config -- there is no hardcoded axis list anywhere in this module; the set
of tiers, and which artifacts are assigned to each, comes entirely from
`ledger_core.projection.load_tiers(tiers_path)`.

Tiers are iterated sorted alphabetically by name for determinism -- the
config file's own line order is not guaranteed to reflect anything a caller
should depend on.

Per tier, `status` is the single worst risk level present among that tier's
assigned artifacts, using the fixed severity order `high > medium > unknown >
low` (`_RISK_SEVERITY` below) -- documented here, not left to the
implementer to invent: `unknown` outranks `low` because "we don't know" must
never look as safe as "confirmed low risk," matching this project's own
never-hide-uncertainty principle (AD-9's confidence discipline, extended to
this aggregate view). A tier with zero assigned artifacts is the one case
with no risk to roll up at all: `artifact_count=0`, every `risk_counts`
value `0`, and `status="low"` -- the absence of any assigned artifact is not
itself a risk signal.

Read-only: `get_dr_readiness_summary` never appends to a log, never writes a
draft, never writes config. Never raises for a *missing*
`rezops.tiers.yaml` (`load_tiers`'s existing missing-file behavior, `({},
{})`, so `tiers` is simply an empty tuple) or an empty/nonexistent
`ledger_dir` (each underlying `get_record` call already tolerates that by
returning an empty-fields, `confidence="unknown"` record). A *malformed*
`rezops.tiers.yaml` (a duplicate tier declaration, an assignment naming an
undeclared tier, etc.) still raises `TiersFileError` via the initial
`load_tiers` call -- consistent with Story 17's own deliberate fail-loudly-
on-malformed-config design, this is not a case the never-raises guarantee
covers.

No UI, no delivery channel -- this module returns structured data only, the
same as `briefing.py`.

Deliberately excluded: this module never passes a `testing_window_path` to
`get_record`, and does not roll up `rto_achieved_pct`/`rpo_achieved_pct`/
`testing_window_compliance` (Story 19, CAP-12) into `TierReadiness` or
anywhere else in this aggregate view. Story 19 is independent of Story 18's
aggregate view; wiring DR-test-achievement signals into this readiness
rollup is a future story's decision, not something implied by either
existing story.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ledger_core.log import DEFAULT_LEDGER_DATA_DIR
from ledger_core.projection import DEFAULT_TIERS_PATH, get_record, load_tiers

#: Timestamp format `generated_at` is rendered in -- matches
#: `ledger_core.briefing`'s own `_TIMESTAMP_FORMAT`, so every ISO-8601-UTC-
#: looking string in this project is rendered the same one way.
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

#: The four risk levels `LedgerRecord.risk` can ever take
#: (`shared.ledger_schema`), and the fixed set of keys `risk_counts` always
#: carries -- every key present even at zero, never omitted just because no
#: artifact in a tier happened to resolve to it.
_RISK_LEVELS = ("high", "medium", "low", "unknown")

#: This story's own explicit, documented severity order (Design Notes):
#: `high > medium > unknown > low`. `unknown` deliberately outranks `low` --
#: "nothing observed yet" must never look as safe as "confirmed low risk" in
#: an aggregate view. Higher number = more severe = wins as a tier's
#: `status`.
_RISK_SEVERITY = {"low": 0, "unknown": 1, "medium": 2, "high": 3}

# `_RISK_LEVELS` and `_RISK_SEVERITY` enumerate the same four risk levels in
# two different, unrelated orders (declaration order vs. severity order) --
# easy to update one and forget the other if a risk level is ever added or
# removed. Enforce that they stay in sync rather than just hoping so.
assert set(_RISK_LEVELS) == set(_RISK_SEVERITY)

#: `status` for a tier with zero assigned artifacts -- there is no risk to
#: roll up, so this is not a computed severity-order result, just the fixed
#: default the I/O matrix specifies.
_NO_ARTIFACTS_STATUS = "low"


@dataclass(frozen=True)
class TierReadiness:
    """Rolled-up DR readiness for one declared tier (CAP-4, Story 18).

    `name` is the tier name exactly as declared in `rezops.tiers.yaml`
    (`tier.<name>.expiry_days`). `artifact_count` is how many
    `(artifact_type, artifact_id)` pairs are assigned to this tier via an
    `assign` entry. `risk_counts` always carries all four
    `_RISK_LEVELS` keys, even at zero. `status` is the single worst risk
    level present, per `_RISK_SEVERITY` -- `"low"` if `artifact_count` is 0
    (nothing to roll up).
    """

    name: str
    artifact_count: int
    risk_counts: dict[str, int]
    status: str


@dataclass(frozen=True)
class DrReadinessSummary:
    """The DR readiness summary: risk rolled up per declared tier (Story 18).

    `tiers` is one `TierReadiness` per tier declared in `rezops.tiers.yaml`,
    sorted alphabetically by tier name -- `()` if the file doesn't exist or
    declares no tiers. `generated_at` is the UTC timestamp this summary was
    assembled at.

    `tiers` is a tuple (not a list) -- `DrReadinessSummary` is `frozen=True`,
    but a frozen dataclass only blocks reassigning its own fields; a plain
    list field would still let a caller mutate this "immutable snapshot"'s
    contents in place (mirrors `Briefing`'s identical discipline).
    """

    tiers: tuple[TierReadiness, ...]
    generated_at: str


def get_dr_readiness_summary(
    *,
    ledger_dir: Path = DEFAULT_LEDGER_DATA_DIR,
    tiers_path: Path = DEFAULT_TIERS_PATH,
) -> DrReadinessSummary:
    """Compose the DR readiness summary from `load_tiers` + `get_record` only.

    For every tier declared in `rezops.tiers.yaml` (`load_tiers(tiers_path)`,
    sorted alphabetically by name), finds every `(artifact_type,
    artifact_id)` assigned to it and calls
    `projection.get_record(artifact_type, artifact_id, ledger_dir=ledger_dir,
    tiers_path=tiers_path)` for each -- exactly the same read path
    `ledger_get_record` uses, never a parallel reimplementation of Story
    17's frozen `_compute_tier_and_risk` formula. Tallies each artifact's
    already-computed `risk` into that tier's `risk_counts`, and derives
    `status` as the worst present per `_RISK_SEVERITY`.

    Never raises for a *missing* `rezops.tiers.yaml`: `load_tiers` already
    returns `({}, {})` for one (so `tiers` is simply `()`), and `get_record`
    already tolerates a missing/empty `ledger_dir` or a corrupted
    artifact-type log by degrading to an empty-fields, `confidence="unknown"`
    record (which resolves `risk="unknown"` here exactly as it would via a
    direct `ledger_get_record` call). This guarantee does not extend to a
    *malformed* `rezops.tiers.yaml` -- the initial `load_tiers(tiers_path)`
    call below still raises `TiersFileError` for a duplicate tier
    declaration, an assignment naming an undeclared tier, or any other
    malformed line, exactly as a direct `load_tiers` call would, per Story
    17's own fail-loudly-on-malformed-config design.

    Read-only: only ever reads `rezops.tiers.yaml` and each artifact-type's
    event log via `get_record` -- no log append, no config write, no draft.

    Note on I/O cost: `load_tiers(tiers_path)` is called once here, but each
    `get_record` call in the loop below internally re-parses
    `rezops.tiers.yaml` again via its own `load_tiers` call -- so the file is
    read and parsed once per assigned artifact, not once total. This is a
    deliberate, accepted tradeoff: the frozen spec requires reusing
    `get_record`'s exact read path rather than reimplementing risk
    computation (Story 17's `_compute_tier_and_risk` formula), and that one
    true risk-computation path matters more than avoiding a redundant, cheap
    file re-read -- fine at v1's expected config-file size and artifact
    count, but a cost that grows with artifact count.
    """
    tiers, assignments = load_tiers(tiers_path)

    # Group assigned artifacts by tier name, so each tier's roll-up only
    # walks the artifacts actually assigned to it.
    artifacts_by_tier: dict[str, list[tuple[str, str]]] = {name: [] for name in tiers}
    for (artifact_type, artifact_id), tier_name in assignments.items():
        artifacts_by_tier[tier_name].append((artifact_type, artifact_id))

    tier_readiness: list[TierReadiness] = []
    for tier_name in sorted(tiers):
        assigned = artifacts_by_tier.get(tier_name, [])
        risk_counts = {level: 0 for level in _RISK_LEVELS}
        for artifact_type, artifact_id in assigned:
            # Each call below re-parses `rezops.tiers.yaml` from scratch via
            # `get_record`'s own internal `load_tiers` call -- a deliberate,
            # accepted tradeoff (see the docstring's "Note on I/O cost"):
            # reusing `get_record`'s exact risk-computation path is worth a
            # redundant, cheap re-read at v1's expected config/artifact size.
            record = get_record(
                artifact_type,
                artifact_id,
                ledger_dir=ledger_dir,
                tiers_path=tiers_path,
            )
            risk_counts[record.risk] += 1

        artifact_count = len(assigned)
        if artifact_count == 0:
            status = _NO_ARTIFACTS_STATUS
        else:
            status = max(
                (level for level, count in risk_counts.items() if count > 0),
                key=lambda level: _RISK_SEVERITY[level],
            )

        tier_readiness.append(
            TierReadiness(
                name=tier_name,
                artifact_count=artifact_count,
                risk_counts=risk_counts,
                status=status,
            )
        )

    generated_at = datetime.now(timezone.utc).strftime(_TIMESTAMP_FORMAT)

    return DrReadinessSummary(
        tiers=tuple(tier_readiness),
        generated_at=generated_at,
    )
