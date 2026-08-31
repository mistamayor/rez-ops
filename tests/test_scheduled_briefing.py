"""Unit tests for the scheduled headless briefing wrapper (Story 11).

Exercises `ops.run_scheduled_briefing.main` against every I/O matrix row,
mocking `subprocess.run` -- pattern: `tests/test_git_connector.py`'s
`monkeypatch.setattr(subprocess, "run", ...)`. No test here ever invokes a
real `claude` process, and `_ops.log.md` is always written under
pytest's `tmp_path`, never the real, git-tracked `ledger_data/`.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from ops.run_scheduled_briefing import (
    PROMPT,
    REASON_MALFORMED_OUTPUT,
    REASON_NONZERO_EXIT,
    REASON_TIMEOUT,
    REASON_UNEXPECTED_ERROR,
    _MCP_CONFIG_PATH,
    _SUBPROCESS_TIMEOUT_SECONDS,
    main,
)

_ENTRY_RE = re.compile(
    r"^- \((?P<reason>timeout|nonzero_exit|malformed_output|unexpected_error)\) "
    r"(?P<timestamp>\S+) detail=(?P<detail>.*)$"
)


def _completed(
    returncode: int, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["claude"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


# --- I/O matrix row 1: successful run --------------------------------------


def test_successful_run_exits_zero_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured_args: list[list[str]] = []

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured_args.append(args)
        return _completed(0, stdout=json.dumps({"result": "ok"}))

    monkeypatch.setattr(subprocess, "run", fake_run)
    ops_log_path = tmp_path / "ledger_data" / "_ops.log.md"

    exit_code = main(ops_log_path=ops_log_path)

    assert exit_code == 0
    assert not ops_log_path.exists()
    # Sanity: the invocation used the documented flags and prompt, and
    # respected the timeout/capture/text discipline via a real call shape.
    (args,) = captured_args
    assert args[0] == "claude"
    assert "-p" in args
    assert "--mcp-config" in args
    # Resolved relative to this script's own file location, not the
    # caller's cwd (Story 11 review fix) -- an absolute path ending in
    # `.mcp.json`, not the bare relative string.
    assert args[args.index("--mcp-config") + 1] == _MCP_CONFIG_PATH
    assert Path(_MCP_CONFIG_PATH).is_absolute()
    assert Path(_MCP_CONFIG_PATH).name == ".mcp.json"
    assert "--output-format" in args
    assert args[args.index("--output-format") + 1] == "json"
    assert "--bare" not in args
    assert PROMPT in args


def test_successful_run_passes_timeout_capture_output_and_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured_kwargs: dict[str, object] = {}

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured_kwargs.update(kwargs)
        return _completed(0, stdout=json.dumps({"result": "ok"}))

    monkeypatch.setattr(subprocess, "run", fake_run)

    exit_code = main(ops_log_path=tmp_path / "ledger_data" / "_ops.log.md")

    assert exit_code == 0
    assert captured_kwargs["timeout"] == _SUBPROCESS_TIMEOUT_SECONDS
    assert captured_kwargs["capture_output"] is True
    assert captured_kwargs["text"] is True
    # No human is present to answer an unexpected interactive prompt --
    # stdin must be closed so the CLI fails fast rather than hanging until
    # the timeout (Story 11 review fix).
    assert captured_kwargs["stdin"] is subprocess.DEVNULL


# --- I/O matrix row 2: non-zero exit -----------------------------------------


def test_nonzero_exit_appends_one_entry_and_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return _completed(
            2, stdout="partial stdout before failure", stderr="boom: something broke"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    ops_log_path = tmp_path / "ledger_data" / "_ops.log.md"

    exit_code = main(ops_log_path=ops_log_path)

    assert exit_code != 0
    lines = _read_lines(ops_log_path)
    assert len(lines) == 1
    match = _ENTRY_RE.match(lines[0])
    assert match is not None
    assert match.group("reason") == REASON_NONZERO_EXIT
    assert "2" in match.group("detail")
    assert "boom: something broke" in match.group("detail")
    # Debugging-relevant stdout is included too, not just stderr (Story 11
    # review fix).
    assert "partial stdout before failure" in match.group("detail")


# --- I/O matrix row 3: malformed JSON output --------------------------------


def test_malformed_json_output_appends_one_entry_and_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return _completed(0, stdout="not json at all {", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ops_log_path = tmp_path / "ledger_data" / "_ops.log.md"

    exit_code = main(ops_log_path=ops_log_path)

    assert exit_code != 0
    lines = _read_lines(ops_log_path)
    assert len(lines) == 1
    match = _ENTRY_RE.match(lines[0])
    assert match is not None
    assert match.group("reason") == REASON_MALFORMED_OUTPUT
    # A snippet of the actual offending stdout is included, not just the
    # JSONDecodeError message (Story 11 review fix).
    assert "not json at all" in match.group("detail")


def test_empty_stdout_on_zero_exit_is_malformed_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return _completed(0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ops_log_path = tmp_path / "ledger_data" / "_ops.log.md"

    exit_code = main(ops_log_path=ops_log_path)

    assert exit_code != 0
    lines = _read_lines(ops_log_path)
    assert len(lines) == 1
    assert REASON_MALFORMED_OUTPUT in lines[0]


# --- I/O matrix row 4: timeout ------------------------------------------------


def test_timeout_appends_one_entry_and_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=args, timeout=kwargs.get("timeout", 0))

    monkeypatch.setattr(subprocess, "run", fake_run)
    ops_log_path = tmp_path / "ledger_data" / "_ops.log.md"

    exit_code = main(ops_log_path=ops_log_path)

    assert exit_code != 0
    lines = _read_lines(ops_log_path)
    assert len(lines) == 1
    match = _ENTRY_RE.match(lines[0])
    assert match is not None
    assert match.group("reason") == REASON_TIMEOUT


# --- I/O matrix row 5: _ops.log.md doesn't exist yet ------------------------


def test_first_ever_failure_creates_the_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return _completed(1, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ops_log_path = tmp_path / "ledger_data" / "_ops.log.md"
    assert not ops_log_path.exists()

    exit_code = main(ops_log_path=ops_log_path)

    assert exit_code != 0
    assert ops_log_path.exists()
    assert len(_read_lines(ops_log_path)) == 1


def test_first_ever_failure_creates_missing_parent_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return _completed(1, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ops_log_path = tmp_path / "does_not_exist_yet" / "_ops.log.md"
    assert not ops_log_path.parent.exists()

    exit_code = main(ops_log_path=ops_log_path)

    assert exit_code != 0
    assert ops_log_path.exists()


# --- Append-only discipline: existing lines are never altered --------------


def test_existing_entries_are_never_altered_by_a_new_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ops_log_path = tmp_path / "ledger_data" / "_ops.log.md"
    ops_log_path.parent.mkdir(parents=True)
    preexisting = "- (nonzero_exit) 2026-01-01T00:00:00Z detail=exit_code=9\n"
    ops_log_path.write_text(preexisting, encoding="utf-8")

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return _completed(1, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    exit_code = main(ops_log_path=ops_log_path)

    assert exit_code != 0
    lines = _read_lines(ops_log_path)
    assert len(lines) == 2
    assert lines[0] == preexisting.rstrip("\n")


def test_two_consecutive_failures_append_two_separate_entries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return _completed(1, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ops_log_path = tmp_path / "ledger_data" / "_ops.log.md"

    main(ops_log_path=ops_log_path)
    main(ops_log_path=ops_log_path)

    assert len(_read_lines(ops_log_path)) == 2


# --- Never a raw, unbounded dump of subprocess output -----------------------


def test_huge_stderr_is_truncated_not_dumped_raw(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    huge_stderr = "x" * 100_000

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return _completed(1, stdout="", stderr=huge_stderr)

    monkeypatch.setattr(subprocess, "run", fake_run)
    ops_log_path = tmp_path / "ledger_data" / "_ops.log.md"

    main(ops_log_path=ops_log_path)

    line = _read_lines(ops_log_path)[0]
    assert len(line) < 1_000
    assert huge_stderr not in line


# --- Unexpected/infra-level failures never escape main ----------------------


def test_unexpected_exception_from_subprocess_run_never_raises_past_main(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("claude binary not found on PATH")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ops_log_path = tmp_path / "ledger_data" / "_ops.log.md"

    exit_code = main(ops_log_path=ops_log_path)

    assert exit_code != 0
    assert ops_log_path.exists()
    lines = _read_lines(ops_log_path)
    assert len(lines) == 1
    # A genuinely unexpected error (no subprocess exit code at all) must be
    # labeled distinctly from an ordinary non-zero exit (Story 11 review
    # fix) -- it was previously mislabeled REASON_NONZERO_EXIT.
    match = _ENTRY_RE.match(lines[0])
    assert match is not None
    assert match.group("reason") == REASON_UNEXPECTED_ERROR


def test_logging_failure_itself_never_escapes_main(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression test: a failure while *logging* an ordinary, expected
    failure (`claude -p` exiting non-zero) must never itself escape `main`.

    Reproduced by pointing `ops_log_path` at a location whose parent
    already exists as a regular file -- `Path.mkdir(parents=True)` raises
    `NotADirectoryError`/`FileExistsError` in that case, which previously
    propagated straight out of `main` uncaught.
    """

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return _completed(1, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)

    # `parent_is_a_file` is a regular file, not a directory -- so
    # `ops_log_path.parent.mkdir(parents=True, exist_ok=True)` inside
    # `_append_ops_log_entry` must raise.
    parent_is_a_file = tmp_path / "parent_is_a_file"
    parent_is_a_file.write_text("not a directory", encoding="utf-8")
    ops_log_path = parent_is_a_file / "_ops.log.md"

    exit_code = main(ops_log_path=ops_log_path)

    assert isinstance(exit_code, int)
    assert exit_code != 0
    # The log entry itself could not be written -- that's expected and
    # acceptable; what matters is that `main` still returned rather than
    # raising.
    assert not ops_log_path.exists()


# --- Every log entry includes a UTC timestamp -------------------------------


def test_log_entry_timestamp_is_iso8601_utc(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return _completed(1, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ops_log_path = tmp_path / "ledger_data" / "_ops.log.md"

    main(ops_log_path=ops_log_path)

    line = _read_lines(ops_log_path)[0]
    match = _ENTRY_RE.match(line)
    assert match is not None
    assert match.group("timestamp").endswith("Z")
    # Parses cleanly as a UTC timestamp in the project's fixed format.
    from datetime import datetime

    datetime.strptime(match.group("timestamp"), "%Y-%m-%dT%H:%M:%SZ")
