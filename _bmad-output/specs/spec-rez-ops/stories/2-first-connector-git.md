---
title: 'First connector: git'
type: 'feature'
created: '2026-08-14'
status: 'done'
review_loop_iteration: 0
baseline_commit: '79cbbcfcf9d88b9a048e47dcee40a1d826411315'
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/specs/spec-rez-ops/SPEC.md'
  - '{project-root}/shared/ledger_schema/models.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Rez Ops has a schema and a ledger-core foundation (Story 1) but no way yet to observe a real system. The git connector is the first Sensor, proving the read-only fetch-and-normalize pattern into `RawFact` (SPEC CAP-2, partial; AD-1, AD-2).

**Approach:** Build a standalone MCP server (`connectors/git_repo/`) exposing one tool that returns "last touched" metadata (commit SHA, author, timestamp) for a given file in a given local git repository, as a `RawFact`. Tested against this repo itself. This story stops at producing a well-formed `RawFact` — it does not wire the result into ledger-core, since ledger-core has no ingestion tool yet (that lands in Story 3).

## Boundaries & Constraints

**Always:**
- The tool is read-only: it runs `git log` only, never a write git command (`commit`, `checkout`, etc.) — CAP-2's "no write/update/delete" success criterion.
- The tool name is domain-prefixed: `git_get_last_touched` (AD-2).
- The tool constructs and returns a `RawFact` (from `shared.ledger_schema`, Story 1), serialized to a plain dict — never a `LedgerRecord`-shaped value (AD-9).
- `file_path` is validated to resolve inside `repo_path` before any subprocess call — no `..` segments or absolute-path escape (same class of check Story 1 added for identifiers).
- This connector never imports or calls `ledger_core` directly, and never writes to `ledger_data/` (AD-1: Sensors and Ledger-Core never call each other directly).
- No network calls — local `git log` only, no fetch/clone/remote operation.

**Ask First:**
- Any dependency beyond stdlib `subprocess` plus the existing `mcp` and `shared` packages (e.g. GitPython) — default to invoking the system `git` binary via `subprocess`.

**Never:**
- No wiring into ledger-core's log/projection in this story — Story 3 adds ledger-core's ingestion tool and does the wiring.
- No calendar/ticketing/CMDB connectors — Story 5.
- No confidence or staleness computation — that's ledger-core's job (AD-5), not a connector's.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path: file with commit history | `repo_path` = this repo, `file_path="ledger_core/log.py"` | Returns a `RawFact`-shaped dict: `source="git:<repo_path>@<sha>"`, `fields` containing `commit_sha`, `author`, `timestamp` (tz-aware ISO 8601), `file_path` | N/A |
| File has no commit history | `file_path` points to an untracked or nonexistent file | No `RawFact` returned | Raises a typed `NoGitHistoryError`, not a raw parse failure |
| `repo_path` is not a git repository | `repo_path` has no `.git` | No `RawFact` returned | Raises a typed `NotAGitRepositoryError` before attempting `git log` |
| `file_path` attempts to escape `repo_path` | `file_path="../../etc/passwd"` | Rejected before any subprocess call | Raises a typed validation error |
| `repo_path` or `file_path` is empty | `""` | Rejected at input validation | Raises a typed validation error |

</frozen-after-approval>

## Code Map

- `shared/ledger_schema/models.py` -- reuse: `RawFact` construction target; read-only, no changes expected
- `ledger_core/server.py` -- reuse as pattern: existing MCP server shape (`FastMCP` instance, one `@mcp.tool`) to mirror for the connector server
- `pyproject.toml` -- edit: add `connectors/git_repo` to `[tool.hatch.build.targets.wheel]` packages
- `connectors/__init__.py` -- new: package marker
- `connectors/git_repo/__init__.py` -- new: package marker
- `connectors/git_repo/server.py` -- new: MCP server exposing `git_get_last_touched`
- `tests/test_git_connector.py` -- new: covers the I/O matrix above, against this repo's own git history

## Tasks & Acceptance

**Execution:**
- [x] `pyproject.toml` -- add `connectors/git_repo` to the wheel packages list -- makes the new package importable the same way `shared`/`ledger_core` are
- [x] `connectors/git_repo/server.py` -- implement `git_get_last_touched(repo_path, file_path, artifact_type, artifact_id)` running `git log -1` via `subprocess`, validating inputs first, constructing a `RawFact` and returning it as a dict -- AD-1, AD-2, AD-9
- [x] `tests/test_git_connector.py` -- unit tests for every I/O matrix row: the happy path is proven both against this repo's own real git history (`ledger_core/log.py`, per the frozen intent) and, together with every edge case requiring throwaway state (untracked file, non-git-repo, escape attempts, empty inputs), against a hermetic git repository created under pytest's `tmp_path`

**Acceptance Criteria:**
- Given the test suite, when `uv run pytest` runs, then all tests (Story 1's and this story's) pass.
- Given an MCP client lists the git connector server's tools, then exactly one tool (`git_get_last_touched`) is present and no write tool exists.
- Given a call with a `file_path` that escapes `repo_path`, when the tool runs, then it raises before any subprocess is spawned (verifiable by asserting no `git` process runs for that case).

## Spec Change Log

- The I/O matrix's literal `source="git:<repo_path>@<sha>"` shape is unreachable as written: `RawFact.source` (shared/ledger_schema/models.py, read-only for this story) is validated against `^[A-Za-z0-9_:-]+$`, which excludes `@`. The pre-existing `_build_source` only sanitized the `repo_path` substring, leaving the literal `@` join character in place, so every real call raised `SchemaValidationError` at `RawFact` construction (caught by the added happy-path test). Fixed by sweeping the *entire* constructed string (prefix, path, and separator) through the same charset-safe substitution, so `@` becomes `_` like any other disallowed character -- preserving the intended "git:\<path\>...\<sha\>" provenance shape without touching the shared, read-only schema module.
- Added one additional happy-path test against this repo's own real git history (`ledger_core/log.py`), per the frozen intent's "Tested against this repo itself" -- the rest of the I/O matrix (untracked file, non-git-repo, path-escape, empty-input) is exercised against a hermetic throwaway repo under pytest's `tmp_path`, since those states can't be produced in this repo's real, committed history without mutating it.

## Design Notes

`git log -1 --format=%H%x1f%an%x1f%aI -- {file_path}` (using `%x1f` unit-separator to avoid delimiter collisions with author names) gives commit SHA, author, and ISO 8601 timestamp in one call. Empty stdout with exit code 0 means "no history for this path" (`NoGitHistoryError`); a nonzero exit from `git rev-parse --git-dir` up front distinguishes "not a git repo" (`NotAGitRepositoryError`) before ever touching `git log`.

## Verification

**Commands:**
- `uv sync` -- expected: resolves and installs without error (no new dependency expected)
- `uv run pytest -v` -- expected: all tests pass, including Story 1's
- `uv run python -c "import connectors.git_repo.server"` -- expected: imports without error

## Suggested Review Order

**The tool itself**

- Entry point: validates inputs, resolves commit metadata, and constructs the `RawFact` this whole story exists to produce.
  [`server.py:196`](../../../../connectors/git_repo/server.py#L196)

- Resolves "last touched" via `git log`, with `--literal-pathspecs` so `file_path` can't be reinterpreted as a git pattern.
  [`server.py:138`](../../../../connectors/git_repo/server.py#L138)

- Distinguishes "no history for this path" from a real git failure, per the Design Notes.
  [`server.py:169`](../../../../connectors/git_repo/server.py#L169)

**Safety boundary (why this connector can't escape `repo_path`)**

- Rejects a `file_path` that resolves outside `repo_path` before any subprocess runs.
  [`server.py:91`](../../../../connectors/git_repo/server.py#L91)

- Single choke point for every subprocess call: timeout, missing-binary, and typed-error translation live here once.
  [`server.py:106`](../../../../connectors/git_repo/server.py#L106)

- Confirms `repo_path` is a real git repository before `git log` is ever attempted.
  [`server.py:129`](../../../../connectors/git_repo/server.py#L129)

**Error hierarchy**

- Every failure mode from this module is one of these four typed errors — nothing propagates raw.
  [`server.py:54`](../../../../connectors/git_repo/server.py#L54)

**Peripherals**

- Packaging fix: `connectors` (not the nested `connectors/git_repo`) is the correct wheel package entry — proven with an actual build.
  [`pyproject.toml:20`](../../../../pyproject.toml#L20)

- Full I/O-matrix coverage plus the review's hardening tests (whitespace inputs, missing git binary, non-directory repo_path, independent source-string assertion).
  [`test_git_connector.py:65`](../../../../tests/test_git_connector.py#L65)
