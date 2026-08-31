"""Scheduled headless briefing wrapper (CAP-8, AD-7): invocation plumbing only.

Invoked by an OS scheduler (cron/launchd -- see `ops/README.md`) with no
human present. Runs `claude -p --mcp-config .mcp.json --output-format json`
with a fixed prompt asking for the periodic briefing (CAP-7), as a single
`subprocess.run` call with a wall-clock timeout -- the same discipline as
`connectors/git_repo/server.py`'s `_run_git` (typed-exception translation,
never a hung process blocking forever).

This module never parses or acts on the briefing's *content* -- success is
exit-code-and-valid-JSON only, matching this story's sole scope (invocation
plumbing, not briefing interpretation). On a non-zero exit, a timeout, or
stdout that isn't parseable JSON, it appends exactly one entry to
`ledger_data/_ops.log.md` (created if missing, opened in append mode only --
AD-3's discipline, applied here even though this file isn't the artifact-type
event log `ledger_core/log.py` owns) and exits non-zero. On success it exits
0 and writes nothing to `_ops.log.md` at all.

No retry/backoff: one invocation, one outcome, logged (frozen intent).
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

#: Fixed prompt asking for the periodic briefing (CAP-7). This wrapper never
#: inspects the resulting content -- the prompt text itself is the only
#: "content" decision this module makes.
PROMPT = (
    "Generate the periodic Rez Ops briefing: call ledger-core's "
    "ledger_get_briefing tool and report what needs a decision today "
    "(orphan-risk entities, unknown-confidence records, pending drafts, "
    "and any data-quality issues)."
)

#: Project-scoped MCP server registration (Story 11's `.mcp.json`, sibling
#: to this file's parent directory) `claude -p` is invoked against. Never
#: `--bare` -- `--bare` skips MCP-server autodiscovery entirely and would
#: run the briefing with no Sensors or Ledger attached (AD-7).
#:
#: Resolved relative to this script's own file location, not the caller's
#: cwd -- a scheduler (cron/launchd) is not guaranteed to `cd` into the repo
#: root before invoking this script, and an unresolved relative path would
#: silently fail to find the file (or find nothing) in that case.
_MCP_CONFIG_PATH = str(Path(__file__).resolve().parent.parent / ".mcp.json")

#: Wall-clock budget for the `claude -p` subprocess call, mirroring
#: `connectors/git_repo/server.py`'s `_run_git` pattern: a hung invocation
#: must not hang the scheduled run forever.
_SUBPROCESS_TIMEOUT_SECONDS = 600

#: AD-7: scheduled-run failure log, sibling to the other `ledger_data/`
#: artifact-type logs but not one of them -- see Design Notes.
DEFAULT_OPS_LOG_PATH = Path("ledger_data") / "_ops.log.md"

#: Matches `ledger_core.log`/`ledger_core.briefing`'s own timestamp format,
#: so every ISO-8601-UTC-looking string in this project renders one way.
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

#: Bound on how much raw subprocess text is folded into a log entry's
#: `detail=` field -- never a raw, unbounded dump (frozen intent).
_DETAIL_MAX_CHARS = 200

#: The three failure reasons a `_run_scheduled_briefing` typed error maps
#: to, plus a fourth for the genuinely-unexpected catch-all in `main`
#: (frozen intent for the first three; the fourth exists so a failure with
#: no subprocess exit code at all -- e.g. a missing `claude` binary -- is
#: never mislabeled as `nonzero_exit`).
REASON_TIMEOUT = "timeout"
REASON_NONZERO_EXIT = "nonzero_exit"
REASON_MALFORMED_OUTPUT = "malformed_output"
REASON_UNEXPECTED_ERROR = "unexpected_error"


class ScheduledBriefingError(Exception):
    """Base class for every typed failure `_run_scheduled_briefing` raises."""


class BriefingTimeoutError(ScheduledBriefingError):
    """Raised when the `claude -p` subprocess exceeds its wall-clock budget."""


class BriefingNonZeroExitError(ScheduledBriefingError):
    """Raised when the `claude -p` subprocess exits non-zero."""

    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(f"claude -p exited {returncode}")


class BriefingMalformedOutputError(ScheduledBriefingError):
    """Raised when the subprocess exits 0 but stdout isn't valid JSON."""

    def __init__(self, json_error: str, stdout: str) -> None:
        self.json_error = json_error
        self.stdout = stdout
        super().__init__(
            f"claude -p exited 0 but stdout was not valid JSON: {json_error}"
        )


def _truncate(text: str) -> str:
    """Bound `text` to `_DETAIL_MAX_CHARS`, collapsed to one line.

    Never lets a raw, unbounded subprocess dump land in `_ops.log.md`
    (frozen intent) -- long stdout/stderr is truncated, not omitted.
    """
    collapsed = " ".join(text.split())
    if len(collapsed) <= _DETAIL_MAX_CHARS:
        return collapsed
    return collapsed[:_DETAIL_MAX_CHARS] + "..."


def _run_claude() -> subprocess.CompletedProcess[str]:
    """Run `claude -p` with a timeout, translating a hang into a typed error.

    Mirrors `connectors/git_repo/server.py`'s `_run_git`: a hung process
    (`subprocess.TimeoutExpired`) is translated here rather than propagating
    raw. A non-zero exit is *not* translated here -- that's `main`'s job,
    since the caller decides what to do with a `CompletedProcess`.

    `stdin=subprocess.DEVNULL` because this wrapper runs with no human
    present (cron/launchd): an unexpected interactive prompt from the
    `claude` CLI must fail fast against a closed stdin rather than hang
    until `_SUBPROCESS_TIMEOUT_SECONDS` expires.
    """
    try:
        return subprocess.run(
            [
                "claude",
                "-p",
                "--mcp-config",
                _MCP_CONFIG_PATH,
                "--output-format",
                "json",
                PROMPT,
            ],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        raise BriefingTimeoutError(
            f"claude -p timed out after {_SUBPROCESS_TIMEOUT_SECONDS}s"
        ) from exc


def _run_scheduled_briefing() -> None:
    """Run the scheduled briefing once; raise a typed error on any failure.

    Never parses or acts on the briefing's *content* -- success is
    exit-code-and-valid-JSON only (this story's sole scope is invocation
    plumbing, not briefing interpretation).
    """
    result = _run_claude()

    if result.returncode != 0:
        raise BriefingNonZeroExitError(result.returncode, result.stdout, result.stderr)

    try:
        json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise BriefingMalformedOutputError(str(exc), result.stdout) from exc


def _append_ops_log_entry(reason: str, detail: str, *, ops_log_path: Path) -> None:
    """Append one failure entry to `_ops.log.md`.

    Opened in append mode only ("a") -- never truncates or rewrites an
    existing line (AD-3's discipline, mirrored here even though
    `_ops.log.md` isn't a `ledger_core.log`-parseable event log: see the
    story's Design Notes -- nothing reads this file back programmatically,
    so a plain timestamped markdown bullet is sufficient). The parent
    directory is created if it doesn't exist yet, matching
    `ledger_core.log.append_event`'s own `_ensure_ledger_dir` behavior.

    May raise (e.g. `ops_log_path`'s parent already exists as a regular
    file, disk full, permission denied) -- callers that must never raise
    past their own body (`main`) are responsible for catching this
    themselves; see `_safe_append_ops_log_entry`.
    """
    ops_log_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc)
    line = (
        f"- ({reason}) {ts.strftime(_TIMESTAMP_FORMAT)} detail={_truncate(detail)}\n"
    )
    with ops_log_path.open("a", encoding="utf-8") as handle:
        handle.write(line)


def _safe_append_ops_log_entry(reason: str, detail: str, *, ops_log_path: Path) -> None:
    """Best-effort wrapper around `_append_ops_log_entry` for use in `main`.

    An ordinary, expected failure (e.g. `claude -p` merely exiting
    non-zero) must still produce a non-zero return code from `main`, even
    if the *logging* of that failure itself raises -- e.g. `ops_log_path`'s
    parent already exists as a regular file, the disk is full, or
    permissions are denied. Any exception raised while appending the log
    entry is swallowed here (never re-raised); a best-effort note is
    printed to stderr so the failure isn't entirely silent.
    """
    try:
        _append_ops_log_entry(reason, detail, ops_log_path=ops_log_path)
    except Exception as exc:  # noqa: BLE001 -- logging must never raise past main
        print(
            f"ops/run_scheduled_briefing.py: failed to append ops log entry "
            f"(reason={reason}): {exc}",
            file=sys.stderr,
        )


def main(*, ops_log_path: Path = DEFAULT_OPS_LOG_PATH) -> int:
    """Run the scheduled briefing once; log and return non-zero on failure.

    Never raises: every typed failure from `_run_scheduled_briefing`
    (timeout, non-zero exit, malformed output) is caught here, appends
    exactly one entry to `_ops.log.md` (best-effort -- a failure while
    logging can never itself escape this function, see
    `_safe_append_ops_log_entry`), and becomes a non-zero return code. Any
    other unexpected exception is also caught and logged under
    `REASON_UNEXPECTED_ERROR` -- this function must never raise past its
    own body, regardless of cause. On success, nothing is appended and
    this returns 0 (the briefing content itself isn't ops-log's concern).
    """
    try:
        _run_scheduled_briefing()
    except BriefingTimeoutError as exc:
        _safe_append_ops_log_entry(REASON_TIMEOUT, str(exc), ops_log_path=ops_log_path)
        return 1
    except BriefingNonZeroExitError as exc:
        _safe_append_ops_log_entry(
            REASON_NONZERO_EXIT,
            f"exit_code={exc.returncode} stdout={_truncate(exc.stdout)} "
            f"stderr={_truncate(exc.stderr)}",
            ops_log_path=ops_log_path,
        )
        return 1
    except BriefingMalformedOutputError as exc:
        _safe_append_ops_log_entry(
            REASON_MALFORMED_OUTPUT,
            f"{exc} stdout={_truncate(exc.stdout)}",
            ops_log_path=ops_log_path,
        )
        return 1
    except Exception as exc:  # noqa: BLE001 -- last resort: never raise past main
        _safe_append_ops_log_entry(
            REASON_UNEXPECTED_ERROR,
            f"unexpected error: {exc}",
            ops_log_path=ops_log_path,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
