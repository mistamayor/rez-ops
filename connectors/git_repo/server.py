"""Git connector MCP server (AD-1, AD-2): the first Sensor.

Exposes exactly one read-only tool, `git_get_last_touched`, which shells out
to the system `git` binary (`git log -1`) to find the most recent commit
that touched a given file and returns it as a `RawFact`-shaped dict (AD-9).

This module never imports or calls `ledger_core`, and never writes to
`ledger_data/` -- Sensors and Ledger-Core never call each other directly
(AD-1). It never runs a git command capable of mutating repository state
(`commit`, `checkout`, etc.) -- only `git rev-parse` and `git log`, both
read-only (CAP-2). It performs no network calls: `git log` operates on the
local repository only, never a `fetch`/`clone`/remote operation.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from shared.ledger_schema import RawFact

mcp = FastMCP("git-repo")

#: Unit separator (0x1F) used to delimit `git log --format` fields. Chosen
#: over a printable delimiter (comma, pipe, etc.) because it can never
#: collide with a commit SHA, author name, or ISO 8601 timestamp.
_FIELD_SEP = "\x1f"

#: `shared.ledger_schema.RawFact.source` is validated against a strict
#: charset (`^[A-Za-z0-9_:-]+$` -- see shared/ledger_schema/models.py,
#: read-only for this story) that excludes both "/" and "@". A repo's
#: filesystem path legitimately contains "/", and the "git:<repo_path>@<sha>"
#: shape from the spec's I/O matrix introduces a literal "@" -- so the whole
#: constructed string is swept for any character outside this charset, not
#: just the `repo_path` substring, and each such character (including the
#: "@" separator itself) is replaced with "_". Because "/" and "@" both
#: collapse to the same "_" replacement, the result is NOT a structured,
#: parseable "git:<path>...<sha>" value -- it is an opaque, human-readable
#: provenance string. Nothing in this codebase parses `source` back into its
#: parts today; only its charset-validity and human-readability are load
#: bearing.
_SOURCE_UNSAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9_:-]")

#: Wall-clock budget for each `git` subprocess call. A hung git process
#: (e.g. blocked on a lock file or a stalled filesystem) must not block this
#: tool indefinitely.
_SUBPROCESS_TIMEOUT_SECONDS = 30


class GitConnectorError(Exception):
    """Base class for every error this connector raises."""


class InvalidPathError(GitConnectorError, ValueError):
    """Raised when `repo_path`/`file_path` fail input validation.

    Always raised before any subprocess is spawned -- covers both empty
    (or whitespace-only) inputs and a `file_path` that would resolve outside
    `repo_path`.
    """


class InvalidArtifactIdentifierError(GitConnectorError, ValueError):
    """Raised when `artifact_type`/`artifact_id` fail input validation."""


class NotAGitRepositoryError(GitConnectorError):
    """Raised when `repo_path` is not inside a git working tree."""


class NoGitHistoryError(GitConnectorError):
    """Raised when `file_path` has no commit history in `repo_path`."""


def _require_nonempty(name: str, value: str) -> None:
    if not value or not value.strip():
        raise InvalidPathError(f"{name} must be a non-empty string; got {value!r}")


def _require_nonempty_identifier(name: str, value: str) -> None:
    if not value or not value.strip():
        raise InvalidArtifactIdentifierError(
            f"{name} must be a non-empty string; got {value!r}"
        )


def _ensure_file_path_inside_repo(repo_path: str, file_path: str) -> None:
    """Validate that `file_path` resolves inside `repo_path`.

    Pure path arithmetic -- no filesystem existence check, and critically no
    subprocess call, so a `..`/absolute-path escape attempt is rejected
    before `git` (or anything else) ever runs.
    """
    repo_root = Path(repo_path).resolve()
    candidate = (repo_root / file_path).resolve()
    if candidate != repo_root and repo_root not in candidate.parents:
        raise InvalidPathError(
            f"file_path {file_path!r} resolves outside repo_path {repo_path!r}"
        )


def _run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a `git` subprocess with a timeout, translating infra failures.

    Both "git binary not on PATH" (`FileNotFoundError`) and a hung git
    process (`subprocess.TimeoutExpired`) are translated into a typed
    `GitConnectorError` here -- neither should ever propagate raw out of
    this module.
    """
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise GitConnectorError(f"could not run git ({args[0]!r}): {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitConnectorError(
            f"git command timed out after {_SUBPROCESS_TIMEOUT_SECONDS}s: {args!r}"
        ) from exc


def _ensure_git_repository(repo_path: str) -> None:
    """Raise NotAGitRepositoryError before ever attempting `git log`."""
    result = _run_git(["git", "-C", repo_path, "rev-parse", "--git-dir"])
    if result.returncode != 0:
        raise NotAGitRepositoryError(
            f"{repo_path!r} is not a git repository: {result.stderr.strip()}"
        )


def _last_touched(repo_path: str, file_path: str) -> tuple[str, str, str]:
    """Run `git log -1` and return (commit_sha, author, timestamp).

    Empty stdout with a zero exit code -- what `git log` returns for a
    pathspec with no matching history -- means "no history for this path"
    -> NoGitHistoryError. Any other non-zero exit is a real git error and
    raises a typed `GitConnectorError` carrying stderr, distinct from "no
    history".

    `--literal-pathspecs` disables git's pathspec "magic" syntax (e.g.
    `:(glob)`, `:(icase)`, `:!`, `:/`) so `file_path` -- already validated as
    a literal path resolving inside `repo_path` -- is always interpreted
    literally by git too, instead of potentially matching files outside what
    was validated.
    """
    result = _run_git(
        [
            "git",
            "--literal-pathspecs",
            "-C",
            repo_path,
            "log",
            "-1",
            f"--format=%H{_FIELD_SEP}%an{_FIELD_SEP}%aI",
            "--",
            file_path,
        ]
    )
    stdout = result.stdout.strip()

    if result.returncode != 0:
        raise GitConnectorError(
            f"git log failed for {file_path!r} in {repo_path!r}: "
            f"{result.stderr.strip()}"
        )

    if not stdout:
        raise NoGitHistoryError(
            f"no commit history for {file_path!r} in {repo_path!r}"
        )

    parts = stdout.split(_FIELD_SEP, 2)
    if len(parts) != 3:
        raise GitConnectorError(
            "unexpected `git log` output shape (expected 3 "
            f"{_FIELD_SEP!r}-separated fields, got {len(parts)}): {stdout!r}"
        )

    commit_sha, author, timestamp = parts
    return commit_sha, author, timestamp


def _build_source(repo_path: str, commit_sha: str) -> str:
    resolved_repo = str(Path(repo_path).resolve())
    raw_source = f"git:{resolved_repo}@{commit_sha}"
    return _SOURCE_UNSAFE_CHARS_RE.sub("_", raw_source)


@mcp.tool(name="git_get_last_touched")
def git_get_last_touched(
    repo_path: str, file_path: str, artifact_type: str, artifact_id: str
) -> dict[str, Any]:
    """Return a RawFact-shaped dict for the last commit that touched `file_path`.

    Read-only: runs only `git rev-parse --git-dir` and `git log -1`, never a
    write git command, and never a network/fetch/clone operation (CAP-2).
    `file_path` is validated to resolve inside `repo_path` before any
    subprocess call (no `..` segments or absolute-path escape). Raises a
    typed error -- never returns a RawFact, and never lets a raw
    `subprocess`/`ValueError`/OS-level exception escape -- for every failure
    case in the I/O matrix: `InvalidPathError` for empty/whitespace-only or
    escaping `repo_path`/`file_path`, `InvalidArtifactIdentifierError` for
    empty/whitespace-only `artifact_type`/`artifact_id`,
    `NotAGitRepositoryError` when `repo_path` has no `.git`,
    `NoGitHistoryError` when `file_path` has no commit history, and
    `GitConnectorError` for any other git/subprocess-level failure (a real
    git error, a hung process, a missing git binary, or an unexpected
    `RawFact` construction failure).

    Computes no confidence or staleness value -- that is ledger-core's job
    (AD-5), not a connector's.
    """
    _require_nonempty("repo_path", repo_path)
    _require_nonempty("file_path", file_path)
    _require_nonempty_identifier("artifact_type", artifact_type)
    _require_nonempty_identifier("artifact_id", artifact_id)

    # Path-escape check first, and with no subprocess call of its own, so
    # that an escaping file_path is rejected before *any* subprocess runs --
    # including the repo-validity check below.
    _ensure_file_path_inside_repo(repo_path, file_path)

    _ensure_git_repository(repo_path)

    commit_sha, author, timestamp = _last_touched(repo_path, file_path)

    try:
        fact = RawFact(
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            source=_build_source(repo_path, commit_sha),
            fields={
                "commit_sha": commit_sha,
                "author": author,
                "timestamp": timestamp,
                "file_path": file_path,
            },
        )
    except Exception as exc:  # noqa: BLE001 -- re-raised as a typed error below
        raise GitConnectorError(f"failed to construct RawFact: {exc}") from exc

    return {
        "artifact_type": fact.artifact_type,
        "artifact_id": fact.artifact_id,
        "source": fact.source,
        "fields": dict(fact.fields),
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
