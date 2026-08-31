"""Draft-not-send outbound content queue (AD-6, CAP-6, Story 9).

Each draft is its own git-tracked markdown file at
`{ledger_dir}/drafts/{draft_id}.md` -- frontmatter (structured metadata) plus
a body (the drafted message text, as-is), mirroring the project's existing
`memlog.py`-adjacent convention of human-readable, git-diffable files. This
module is kept separate from `projection.py`/`log.py`: drafts are new
content ledger-core itself authors, not append-only observed facts replayed
from a per-artifact-type event log, so they don't fit that model.

`create_draft` is the *only* place anything is ever written under
`{ledger_dir}/drafts/` (AD-6) -- no other component has a code path to
`ledger_data/` at all (AD-1). It never calls an external send/write API; its
only side effect is writing one new file. `draft_id` is always generated
here (a sortable UTC timestamp plus a short random suffix) -- never accepted
from a caller -- so it can never be used for a path-traversal-style attack
on the filename (there is no user-suppliable component in the path at all).

`list_drafts` only ever reads; it never mutates a draft file, and this story
adds no update/delete tool of any kind (create and list only).
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ledger_core.log import LogFormatError
from ledger_core.projection import get_record

#: Default root for git-committed ledger data. Deliberately *not* imported
#: from `ledger_core.log` -- the story's Code Map calls out `log.py` as a
#: pattern to mirror (its never-truncate append-only-write discipline),
#: read but not imported, since drafts.py's one-file-per-draft write model
#: is a different write path, never `log.append_event`. Kept equal in value
#: to `ledger_core.log.DEFAULT_LEDGER_DATA_DIR` by convention (both name the
#: same real, git-committed `ledger_data/` directory at the repo root).
DEFAULT_LEDGER_DATA_DIR = Path("ledger_data")

#: Subdirectory under `ledger_dir` where every draft file lives (AD-6,
#: ARCHITECTURE-SPINE.md's Structural Seed: `ledger_data/drafts/`).
_DRAFTS_SUBDIR = "drafts"

#: Same identifier charset shared/ledger_schema/models.py enforces for
#: RawFact's artifact_type/artifact_id (`_IDENTIFIER_RE` there). Mirrored
#: here rather than imported -- it's a private name in that module -- per
#: the story's Code Map ("reuse (read-only): the identifier charset pattern
#: to mirror"). Keeping the same charset here closes the same two issues
#: that module's docstring calls out: no whitespace/delimiter characters
#: that could corrupt a frontmatter line, and no "/"/".." that could escape
#: the intended directory if this value were ever used to build a path.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_-]+$")

#: `secrets.token_hex(3)` -> 6 hex chars of randomness in `draft_id`'s
#: suffix. Not itself a uniqueness *guarantee* -- `create_draft`'s retry
#: loop over `open(..., "x")` guarantees that -- just wide enough that two
#: drafts created in the same wall-clock second essentially never collide on
#: the first attempt.
_RANDOM_SUFFIX_BYTES = 3

#: Upper bound on attempts to find a filename not already taken, so a
#: pathological run of collisions fails loudly (`RuntimeError`) instead of
#: looping forever. Never expected to be hit in practice.
_MAX_DRAFT_ID_ATTEMPTS = 10

#: Sentinel value `list_drafts` uses for every field of the one synthetic
#: Draft it emits in place of a single corrupted/tampered draft file it
#: can't parse (`DraftFileFormatError`) -- except `draft_id`, which stays
#: the real, still-useful filename stem, and `recipient`/`body`, which stay
#: `None`/`""` since `Draft.recipient` is typed `str | None` and an empty
#: body is more honest than a fabricated non-blank one. Mirrors
#: `ledger_core.projection`'s `LOG_FORMAT_ERROR_MARKER`/
#: `LOG_FORMAT_ERROR_ARTIFACT_ID` (AD-8): a corrupted draft must not
#: silently vanish from the list, nor abort listing every other, healthy
#: draft.
DRAFT_FORMAT_ERROR_MARKER = "error:draft_format_error"

#: Frontmatter keys, in the order they're written. `draft_id` is not among
#: them -- it's the filename itself (mirroring `ledger_core.log`'s
#: `artifact_type` being the log filename rather than a repeated field
#: inside it), so there is exactly one place a draft's identity lives.
_FRONTMATTER_KEYS = (
    "artifact_type",
    "artifact_id",
    "draft_type",
    "subject",
    "recipient",
    "created_at",
)


class DraftValidationError(ValueError):
    """Raised when `create_draft` is given an invalid or blank required field.

    Raised before any file is written -- nothing is ever partially created.
    """


class DraftFileFormatError(ValueError):
    """Raised when a file under `{ledger_dir}/drafts/` can't be parsed back.

    Every draft `list_drafts` ever reads was written by `create_draft`
    itself, so this should never fire against real data; it exists so a
    tampered-with or hand-edited file fails loudly and specifically rather
    than as an opaque `IndexError`/`KeyError` deep in the parser.
    """


@dataclass(frozen=True)
class Draft:
    """One drafted, not-yet-sent piece of outbound content.

    `recipient` is `None` when no explicit recipient was given *and* the
    artifact's `escalation_owner` was unresolved at creation time (an
    orphan-risk artifact) -- never a guessed value (AD-6, Story 9 Intent).
    """

    draft_id: str
    artifact_type: str
    artifact_id: str
    draft_type: str
    subject: str
    body: str
    recipient: str | None
    created_at: str


def _require_identifier(field_name: str, value: Any) -> None:
    if not isinstance(value, str) or not _IDENTIFIER_RE.match(value):
        raise DraftValidationError(
            f"{field_name} must be a non-empty string matching "
            f"{_IDENTIFIER_RE.pattern!r} (no slashes or whitespace); got {value!r}"
        )


def _require_nonblank_text(field_name: str, value: Any) -> None:
    """Require a non-empty, non-whitespace-only string.

    Deliberately never echoes `value` itself in the error message: unlike an
    identifier, `subject`/`draft_type`/`body` are opaque caller-supplied text
    that may carry real (if here, blank/whitespace) message content, and this
    module never inspects or templates that content -- the same discipline
    every connector's non-2xx/malformed-response handling already applies to
    not leaking response bodies into an error channel.
    """
    if not isinstance(value, str) or not value.strip():
        raise DraftValidationError(
            f"{field_name} must be a non-empty, non-whitespace-only string"
        )


def _ensure_drafts_dir(drafts_dir: Path) -> None:
    """Mirrors `ledger_core.log._ensure_ledger_dir`'s same guard."""
    if drafts_dir.exists() and not drafts_dir.is_dir():
        raise NotADirectoryError(
            f"drafts_dir {drafts_dir} exists and is not a directory"
        )
    drafts_dir.mkdir(parents=True, exist_ok=True)


def _generate_draft_id(now: datetime) -> str:
    """A sortable UTC timestamp plus a short random suffix.

    Sortable so a human browsing `ledger_data/drafts/` sees creation order
    for free; collision-safe without needing a natural external ID to reuse
    (unlike a connector's fetched facts, a draft is new content ledger-core
    itself authors -- Design Notes).
    """
    ts = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = secrets.token_hex(_RANDOM_SUFFIX_BYTES)
    return f"{ts}-{suffix}"


def _escape_frontmatter_value(value: str) -> str:
    """Collapse embedded newlines to spaces for a single-line frontmatter field.

    A serialization-safety measure over how a value is *stored* in the
    single-line `key: value` frontmatter block (mirroring
    `_bmad/scripts/memlog.py`'s own handling -- the "memlog.py-adjacent
    convention" the story's Design Notes reference) -- not a rejection or
    semantic interpretation of the caller's content. `subject` is
    conventionally a single line already; `body` (the drafted message text)
    is never passed through this function and is stored exactly as given.
    """
    return " ".join(value.splitlines())


def _render_draft(draft: Draft) -> str:
    values = {
        "artifact_type": draft.artifact_type,
        "artifact_id": draft.artifact_id,
        # Escaped the same way subject/recipient already are: an
        # unescaped draft_type with an embedded newline would either break
        # the frontmatter fence (a genuine corrupt-file/DraftFileFormatError
        # risk) or, worse, inject a fake extra "key: value" line that
        # _parse_draft_file's last-write-wins fold would silently let
        # overwrite a real field (e.g. artifact_type) in the parsed
        # metadata -- a security-relevant corruption, not just a cosmetic
        # one.
        "draft_type": _escape_frontmatter_value(draft.draft_type),
        # `.strip()` after escaping to match `_parse_draft_file`'s
        # `value.strip()` on every frontmatter value it reads back -- so a
        # subject with incidental leading/trailing whitespace round-trips
        # to the same value `_parse_draft_file` would produce, rather than
        # write-time and read-time whitespace handling silently disagreeing.
        "subject": _escape_frontmatter_value(draft.subject).strip(),
        "recipient": (
            _escape_frontmatter_value(draft.recipient)
            if draft.recipient is not None
            else ""
        ),
        "created_at": draft.created_at,
    }
    frontmatter = "\n".join(f"{key}: {values[key]}" for key in _FRONTMATTER_KEYS)
    return f"---\n{frontmatter}\n---\n\n{draft.body.rstrip('\n')}\n"


def _parse_draft_file(path: Path) -> Draft:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise DraftFileFormatError(f"{path}: missing frontmatter opening fence")
    end = next((i for i in range(1, len(lines)) if lines[i] == "---"), None)
    if end is None:
        raise DraftFileFormatError(f"{path}: frontmatter is not terminated")

    meta: dict[str, str] = {}
    for line in lines[1:end]:
        if ":" not in line:
            raise DraftFileFormatError(f"{path}: unparseable frontmatter line: {line!r}")
        key, value = line.split(":", 1)
        key = key.strip()
        if key in meta:
            # Defense in depth: escaping draft_type/subject/recipient at
            # write time (`_escape_frontmatter_value`) already closes the
            # practical path for a caller-supplied value to inject a second
            # "key: value" line, but the parser itself should not be more
            # lenient than that -- a duplicate key (however it got there,
            # e.g. a hand-tampered file) must fail loudly rather than let
            # the later line silently win over the earlier one.
            raise DraftFileFormatError(
                f"{path}: duplicate frontmatter key {key!r}"
            )
        meta[key] = value.strip()

    missing = [key for key in _FRONTMATTER_KEYS if key not in meta]
    if missing:
        raise DraftFileFormatError(f"{path}: missing frontmatter field(s) {missing!r}")

    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    recipient = meta["recipient"] or None

    return Draft(
        draft_id=path.stem,
        artifact_type=meta["artifact_type"],
        artifact_id=meta["artifact_id"],
        draft_type=meta["draft_type"],
        subject=meta["subject"],
        body=body,
        recipient=recipient,
        created_at=meta["created_at"],
    )


def create_draft(
    artifact_type: str,
    artifact_id: str,
    draft_type: str,
    subject: str,
    body: str,
    recipient: str | None = None,
    *,
    ledger_dir: Path = DEFAULT_LEDGER_DATA_DIR,
) -> Draft:
    """Create one draft and write it to `{ledger_dir}/drafts/{draft_id}.md`.

    Validates every required field first -- `artifact_type`/`artifact_id`
    against the same identifier charset every other component enforces,
    `draft_type`/`subject`/`body` as non-empty/non-whitespace-only strings
    -- raising `DraftValidationError` and writing nothing if any fails.

    If `recipient` is omitted (`None`) -- or given as an empty or
    whitespace-only string, which is normalized to `None` *before* this
    check, so both are treated identically -- looks up the artifact's
    current `escalation_owner` via `ledger_core.projection.get_record` and
    uses it as the default. (Without this normalization, an explicit `""`
    would skip the lookup and produce a Draft with `recipient=""`, while a
    later `list_drafts` read of that same file would normalize `""` back to
    `None`, on read -- the object returned here and the object read back
    later would disagree.) If that's also unresolved (an orphan-risk
    artifact, an artifact never observed at all -- `get_record` treats both
    the same way, returning `escalation_owner=None` -- or the artifact
    type's log is corrupted, raising `LogFormatError`, caught here and
    treated the same as an unresolved owner rather than aborting draft
    creation), `recipient` stays `None` in the resulting draft rather than
    being guessed at (AD-6, Story 9 Intent). Any other, non-blank
    `recipient` is used unchanged; no heuristic other than the
    `escalation_owner` lookup is ever applied.

    `subject`/`body` content is never validated or interpreted beyond the
    non-blank check above -- they're opaque text this function stores as
    given, never inspects or templates.

    The only side effect is writing exactly one new file, opened with `"x"`
    (exclusive create) so this can never silently overwrite an existing
    draft -- mirroring `ledger_core.log.append_event`'s never-truncate
    discipline, applied here to "never overwrite" instead of "never
    truncate" since each draft is its own whole file rather than a line
    appended to a shared one. `draft_id` collisions (same wall-clock second)
    are handled by regenerating a new random suffix and retrying, up to
    `_MAX_DRAFT_ID_ATTEMPTS` times.
    """
    _require_identifier("artifact_type", artifact_type)
    _require_identifier("artifact_id", artifact_id)
    _require_nonblank_text("draft_type", draft_type)
    _require_nonblank_text("subject", subject)
    _require_nonblank_text("body", body)

    # An explicit empty/whitespace-only recipient is normalized to `None`
    # *before* the "was a recipient given" check below, not treated as
    # "explicitly given". Without this, `create_draft("", ...)` would skip
    # the `escalation_owner` lookup and return a Draft with
    # `recipient=""`, while a later `list_drafts` read of that same file
    # would normalize `""` back to `None` (`meta["recipient"] or None`) --
    # the object returned at creation time and the object read back later
    # would disagree. Normalizing here means both paths always agree.
    if recipient is not None and not recipient.strip():
        recipient = None

    if recipient is None:
        try:
            record = get_record(artifact_type, artifact_id, ledger_dir=ledger_dir)
        except LogFormatError:
            # Graceful degradation (AD-8 spirit, mirroring
            # get_coverage_map/list_records's LogFormatError isolation): a
            # corrupted log for the target artifact's type must not abort
            # draft creation outright -- fall back to the same "recipient
            # stays unset" behavior as an artifact with no resolved owner,
            # rather than crashing.
            recipient = None
        else:
            recipient = record.escalation_owner

    drafts_dir = ledger_dir / _DRAFTS_SUBDIR
    _ensure_drafts_dir(drafts_dir)

    now = datetime.now(timezone.utc)
    created_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    draft_id: str | None = None
    for _attempt in range(_MAX_DRAFT_ID_ATTEMPTS):
        candidate_id = _generate_draft_id(now)
        candidate_path = drafts_dir / f"{candidate_id}.md"
        draft = Draft(
            draft_id=candidate_id,
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            draft_type=draft_type,
            subject=subject,
            body=body,
            recipient=recipient,
            created_at=created_at,
        )
        try:
            with candidate_path.open("x", encoding="utf-8") as handle:
                handle.write(_render_draft(draft))
        except FileExistsError:
            continue
        except Exception:
            # The exclusive create ("x" mode) already succeeded by the time
            # any other exception could be raised here (e.g. _render_draft
            # itself failing, or the write() call failing partway through),
            # so an empty or partially-written file may now exist on disk
            # with no Draft ever returned for it. Clean it up rather than
            # leaving an orphaned file behind.
            candidate_path.unlink(missing_ok=True)
            raise
        draft_id = candidate_id
        break

    if draft_id is None:
        raise RuntimeError(
            f"could not generate a unique draft_id after "
            f"{_MAX_DRAFT_ID_ATTEMPTS} attempts"
        )

    return draft


def list_drafts(
    artifact_type: str | None = None,
    artifact_id: str | None = None,
    draft_type: str | None = None,
    *,
    ledger_dir: Path = DEFAULT_LEDGER_DATA_DIR,
) -> list[Draft]:
    """List every draft under `{ledger_dir}/drafts/`, optionally filtered.

    `artifact_type`, `artifact_id`, and `draft_type` combine as an AND
    across whichever are given; omitted filters (`None`) don't restrict the
    result. Returns every draft, sorted by filename (which sorts
    chronologically -- `draft_id`'s timestamp prefix) when no filter is
    given.

    Never raises for a missing `ledger_dir` or `drafts/` subdirectory --
    returns `[]`, the same as "no drafts exist yet".

    If one draft file fails to parse (`DraftFileFormatError` -- a
    tampered-with or hand-edited file), that failure is isolated to its own
    file: it is represented by exactly one sentinel Draft (every field
    `DRAFT_FORMAT_ERROR_MARKER` except `draft_id`, which stays that file's
    real filename stem, `recipient`, which stays `None`, and `body`, which
    stays `""`) rather than aborting listing for every other, healthy draft
    (AD-8: the same graceful-degradation pattern Story 8 applied to
    `get_coverage_map`/`list_records` for a corrupted artifact-type log --
    a corrupted item shouldn't blind the whole view). That sentinel is
    always included in the result regardless of any `artifact_type`,
    `artifact_id`, or `draft_type` filter -- a genuinely unparseable file
    has no real values for those fields to filter on, and an error signal
    must not be silently filterable away.
    """
    drafts_dir = ledger_dir / _DRAFTS_SUBDIR
    if not drafts_dir.exists() or not drafts_dir.is_dir():
        return []

    drafts: list[Draft] = []
    for path in sorted(drafts_dir.iterdir()):
        if not path.is_file() or path.suffix != ".md":
            continue
        try:
            draft = _parse_draft_file(path)
        except DraftFileFormatError:
            drafts.append(
                Draft(
                    draft_id=path.stem,
                    artifact_type=DRAFT_FORMAT_ERROR_MARKER,
                    artifact_id=DRAFT_FORMAT_ERROR_MARKER,
                    draft_type=DRAFT_FORMAT_ERROR_MARKER,
                    subject=DRAFT_FORMAT_ERROR_MARKER,
                    body="",
                    recipient=None,
                    created_at=DRAFT_FORMAT_ERROR_MARKER,
                )
            )
            continue
        if artifact_type is not None and draft.artifact_type != artifact_type:
            continue
        if artifact_id is not None and draft.artifact_id != artifact_id:
            continue
        if draft_type is not None and draft.draft_type != draft_type:
            continue
        drafts.append(draft)
    return drafts
