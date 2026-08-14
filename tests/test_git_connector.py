"""Unit tests for the git connector (Story 2).

Exercises `connectors.git_repo.server.git_get_last_touched` against a real,
throwaway git repository created under pytest's tmp_path -- this repo's own
git history is never mutated, and every subprocess call runs against the
tmp_path fixture only.
"""

from __future__ import annotations

import asyncio
import re
import subprocess
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from connectors.git_repo.server import (
    GitConnectorError,
    InvalidArtifactIdentifierError,
    InvalidPathError,
    NoGitHistoryError,
    NotAGitRepositoryError,
    git_get_last_touched,
    mcp,
)
from shared.ledger_schema import RawFact

#: Independent (not calling `_build_source`) literal re-implementation of the
#: sanitization `_build_source` performs, used to compute expected `source`
#: values in tests without being self-referential.
_SOURCE_UNSAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9_:-]")


def _expected_source(repo_path: Path, commit_sha: str) -> str:
    raw = f"git:{repo_path.resolve()}@{commit_sha}"
    return _SOURCE_UNSAFE_CHARS_RE.sub("_", raw)


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    _git("config", "user.email", "test@example.com", cwd=repo)
    _git("config", "user.name", "Test User", cwd=repo)
    (repo / "tracked.txt").write_text("hello\n", encoding="utf-8")
    _git("add", "tracked.txt", cwd=repo)
    _git("commit", "-q", "-m", "add tracked.txt", cwd=repo)
    return repo


# --- I/O matrix row 1: happy path -----------------------------------------


def test_happy_path_returns_rawfact_shaped_dict_with_commit_metadata(
    git_repo: Path,
) -> None:
    result = git_get_last_touched(
        repo_path=str(git_repo),
        file_path="tracked.txt",
        artifact_type="test_artifact",
        artifact_id="x1",
    )

    expected_sha = _git("rev-parse", "HEAD", cwd=git_repo).stdout.strip()
    expected_source = _expected_source(git_repo, expected_sha)

    assert result["artifact_type"] == "test_artifact"
    assert result["artifact_id"] == "x1"
    assert result["source"] == expected_source
    assert result["fields"]["commit_sha"] == expected_sha
    assert result["fields"]["author"] == "Test User"
    assert result["fields"]["file_path"] == "tracked.txt"

    # timestamp is a tz-aware ISO 8601 string.
    parsed = datetime.fromisoformat(result["fields"]["timestamp"])
    assert parsed.tzinfo is not None

    # The dict round-trips through RawFact construction without raising --
    # proving it is genuinely RawFact-shaped (AD-9), not merely dict-shaped.
    fact = RawFact(**result)
    assert isinstance(fact, RawFact)


def test_happy_path_against_this_repos_real_git_history() -> None:
    """The I/O matrix's row 1 example is literally this repo + `ledger_core/log.py`
    -- exercised here in addition to the throwaway-repo fixture above so the
    connector is proven against real, non-synthetic git history at least once,
    per the frozen intent ("Tested against this repo itself").
    """
    repo_root = Path(__file__).resolve().parent.parent

    result = git_get_last_touched(
        repo_path=str(repo_root),
        file_path="ledger_core/log.py",
        artifact_type="test_artifact",
        artifact_id="x1",
    )

    assert result["fields"]["file_path"] == "ledger_core/log.py"
    assert len(result["fields"]["commit_sha"]) == 40
    assert result["fields"]["author"]
    datetime.fromisoformat(result["fields"]["timestamp"])  # doesn't raise
    RawFact(**result)  # round-trips without raising


# --- I/O matrix row 2: file has no commit history -------------------------


def test_untracked_file_raises_no_git_history_error(git_repo: Path) -> None:
    (git_repo / "untracked.txt").write_text("never committed\n", encoding="utf-8")

    with pytest.raises(NoGitHistoryError):
        git_get_last_touched(
            repo_path=str(git_repo),
            file_path="untracked.txt",
            artifact_type="test_artifact",
            artifact_id="x1",
        )


def test_nonexistent_file_raises_no_git_history_error(git_repo: Path) -> None:
    with pytest.raises(NoGitHistoryError):
        git_get_last_touched(
            repo_path=str(git_repo),
            file_path="does-not-exist.txt",
            artifact_type="test_artifact",
            artifact_id="x1",
        )


# --- I/O matrix row 3: repo_path is not a git repository ------------------


def test_non_git_repo_path_raises_not_a_git_repository_error(tmp_path: Path) -> None:
    not_a_repo = tmp_path / "not_a_repo"
    not_a_repo.mkdir()

    with pytest.raises(NotAGitRepositoryError):
        git_get_last_touched(
            repo_path=str(not_a_repo),
            file_path="whatever.txt",
            artifact_type="test_artifact",
            artifact_id="x1",
        )


# --- I/O matrix row 4: file_path attempts to escape repo_path -------------


@pytest.mark.parametrize(
    "escaping_file_path",
    ["../../etc/passwd", "../outside.txt", "/etc/passwd"],
)
def test_escaping_file_path_raises_before_any_subprocess_call(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, escaping_file_path: str
) -> None:
    spy = Mock(wraps=subprocess.run)
    monkeypatch.setattr(subprocess, "run", spy)

    with pytest.raises(InvalidPathError):
        git_get_last_touched(
            repo_path=str(git_repo),
            file_path=escaping_file_path,
            artifact_type="test_artifact",
            artifact_id="x1",
        )

    spy.assert_not_called()


# --- I/O matrix row 5: repo_path or file_path is empty ---------------------


def test_empty_repo_path_raises_invalid_path_error(git_repo: Path) -> None:
    with pytest.raises(InvalidPathError):
        git_get_last_touched(
            repo_path="",
            file_path="tracked.txt",
            artifact_type="test_artifact",
            artifact_id="x1",
        )


def test_empty_file_path_raises_invalid_path_error(git_repo: Path) -> None:
    with pytest.raises(InvalidPathError):
        git_get_last_touched(
            repo_path=str(git_repo),
            file_path="",
            artifact_type="test_artifact",
            artifact_id="x1",
        )


def test_whitespace_only_repo_path_raises_invalid_path_error() -> None:
    with pytest.raises(InvalidPathError):
        git_get_last_touched(
            repo_path="   ",
            file_path="tracked.txt",
            artifact_type="test_artifact",
            artifact_id="x1",
        )


def test_whitespace_only_file_path_raises_invalid_path_error(git_repo: Path) -> None:
    with pytest.raises(InvalidPathError):
        git_get_last_touched(
            repo_path=str(git_repo),
            file_path="   ",
            artifact_type="test_artifact",
            artifact_id="x1",
        )


@pytest.mark.parametrize("bad_identifier", ["", "   "])
def test_empty_or_whitespace_artifact_type_raises_invalid_identifier_error(
    git_repo: Path, bad_identifier: str
) -> None:
    with pytest.raises(InvalidArtifactIdentifierError):
        git_get_last_touched(
            repo_path=str(git_repo),
            file_path="tracked.txt",
            artifact_type=bad_identifier,
            artifact_id="x1",
        )


@pytest.mark.parametrize("bad_identifier", ["", "   "])
def test_empty_or_whitespace_artifact_id_raises_invalid_identifier_error(
    git_repo: Path, bad_identifier: str
) -> None:
    with pytest.raises(InvalidArtifactIdentifierError):
        git_get_last_touched(
            repo_path=str(git_repo),
            file_path="tracked.txt",
            artifact_type="test_artifact",
            artifact_id=bad_identifier,
        )


# --- repo_path pointing at something that isn't a usable git working tree --


def test_nonexistent_repo_path_raises_not_a_git_repository_error(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "does-not-exist"

    with pytest.raises(NotAGitRepositoryError):
        git_get_last_touched(
            repo_path=str(missing),
            file_path="tracked.txt",
            artifact_type="test_artifact",
            artifact_id="x1",
        )


def test_repo_path_pointing_to_a_regular_file_raises_not_a_git_repository_error(
    tmp_path: Path,
) -> None:
    a_file = tmp_path / "im_a_file.txt"
    a_file.write_text("not a directory\n", encoding="utf-8")

    with pytest.raises(NotAGitRepositoryError):
        git_get_last_touched(
            repo_path=str(a_file),
            file_path="tracked.txt",
            artifact_type="test_artifact",
            artifact_id="x1",
        )


# --- git binary unavailable -------------------------------------------------


def test_missing_git_binary_raises_git_connector_error(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise_file_not_found(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("git binary not found on PATH")

    monkeypatch.setattr(subprocess, "run", _raise_file_not_found)

    with pytest.raises(GitConnectorError):
        git_get_last_touched(
            repo_path=str(git_repo),
            file_path="tracked.txt",
            artifact_type="test_artifact",
            artifact_id="x1",
        )


# --- Error hierarchy --------------------------------------------------------


@pytest.mark.parametrize(
    "error_cls", [InvalidPathError, NotAGitRepositoryError, NoGitHistoryError]
)
def test_all_typed_errors_are_git_connector_errors(error_cls: type) -> None:
    assert issubclass(error_cls, GitConnectorError)


def test_invalid_path_error_is_also_a_value_error() -> None:
    assert issubclass(InvalidPathError, ValueError)


# --- Acceptance: exactly one read-only tool, no write tool ----------------


def test_server_exposes_exactly_one_read_only_tool() -> None:
    tools = asyncio.run(mcp.list_tools())
    names = [tool.name for tool in tools]
    assert names == ["git_get_last_touched"]


# --- Acceptance: the tool is callable end-to-end over MCP -----------------


async def _call_git_get_last_touched(
    repo_path: str, file_path: str, artifact_type: str, artifact_id: str
):
    async with create_connected_server_and_client_session(mcp) as client:
        return await client.call_tool(
            "git_get_last_touched",
            {
                "repo_path": repo_path,
                "file_path": file_path,
                "artifact_type": artifact_type,
                "artifact_id": artifact_id,
            },
        )


def test_git_get_last_touched_tool_matches_direct_call(git_repo: Path) -> None:
    expected = git_get_last_touched(
        repo_path=str(git_repo),
        file_path="tracked.txt",
        artifact_type="test_artifact",
        artifact_id="x1",
    )

    result = asyncio.run(
        _call_git_get_last_touched(str(git_repo), "tracked.txt", "test_artifact", "x1")
    )

    assert result.isError is False
    assert result.structuredContent == expected


def test_git_get_last_touched_tool_returns_structured_error_for_escaping_path(
    git_repo: Path,
) -> None:
    result = asyncio.run(
        _call_git_get_last_touched(
            str(git_repo), "../../etc/passwd", "test_artifact", "x1"
        )
    )

    assert result.isError is True
    assert result.content
    assert "resolves outside" in result.content[0].text
