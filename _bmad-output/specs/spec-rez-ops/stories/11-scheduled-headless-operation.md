---
title: 'Scheduled headless operation'
type: 'feature'
created: '2026-08-31'
status: 'done'
review_loop_iteration: 0
baseline_commit: 'e39ccd910fcbea2376b54021e055492f054a9c40'
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/specs/spec-rez-ops/SPEC.md'
  - '{project-root}/ledger_core/briefing.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** SPEC CAP-8 has no implementation, and `.mcp.json` — the project-scoped MCP server registration every other piece of AD-7 depends on — doesn't exist yet. Nothing wires the periodic briefing to unattended, OS-scheduled invocation, and a failed scheduled run has nowhere to surface.

**Approach:** Add `.mcp.json` registering all five stdio servers (ledger-core + four connectors), each launched as `uv run python -m {module}.server` per their existing `if __name__ == "__main__": mcp.run()` entry points — no new server code. Add `ops/run_scheduled_briefing.py`, a wrapper that invokes `claude -p --mcp-config .mcp.json --output-format json` with a fixed prompt asking for the periodic briefing, as a `subprocess.run` call with a timeout (same discipline as `connectors/git_repo/server.py`'s `_run_git`). On non-zero exit, a timeout, or output that isn't parseable JSON, it appends one entry to `ledger_data/_ops.log.md` and exits non-zero; on success it exits 0 and writes nothing (the briefing content itself isn't ops-log's concern — AD-7 only requires failures to be visible). Document cron/launchd registration in `ops/README.md`; do not install a scheduler job on this machine.

## Boundaries & Constraints

**Always:**
- `.mcp.json` registers exactly the five existing servers by their current `mcp.run()` entry points — no new MCP tool, no change to any server module.
- `ops/run_scheduled_briefing.py` never parses or acts on the briefing's *content* — success is exit-code-and-valid-JSON only, matching this story's sole scope (invocation plumbing, not briefing interpretation).
- `_ops.log.md` is opened in append mode only, never truncated or rewritten (AD-3's discipline, applied here even though this file isn't the artifact-type event log).
- Every `_ops.log.md` entry includes a UTC timestamp and the failure reason (`timeout`, `nonzero_exit`, `malformed_output`), never a raw, unbounded dump of subprocess output.
- The subprocess call has a wall-clock timeout (mirroring `_run_git`'s pattern) so a hung `claude` invocation can't hang the scheduled run forever.

**Ask First:**
- Any dependency beyond what's already direct.

**Never:**
- No actual cron/launchd job installed on this machine — `ops/README.md` documents the registration command; running it is a manual step left to the human.
- No retry/backoff on a failed scheduled run in this story — one invocation, one outcome, logged.
- No new MCP tool, no ledger-core or connector code change.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Successful run | `claude -p` exits 0 with valid JSON on stdout | Wrapper exits 0; nothing appended to `_ops.log.md` | N/A |
| Non-zero exit | `claude -p` exits non-zero | One entry appended to `_ops.log.md` (`nonzero_exit`, includes exit code); wrapper exits non-zero | Never raises past the wrapper's own `main` |
| Malformed JSON output | Process exits 0 but stdout isn't valid JSON | One entry appended (`malformed_output`); wrapper exits non-zero | Never raises |
| Timeout | Process exceeds the wall-clock budget | One entry appended (`timeout`); wrapper exits non-zero | Never raises |
| `_ops.log.md` doesn't exist yet | First-ever failure | File is created; entry appended | Never raises |

</frozen-after-approval>

## Code Map

- `connectors/git_repo/server.py:106` (`_run_git`) -- reuse as pattern: `subprocess.run` with timeout, typed-exception translation; no import, mirror the shape
- `ledger_core/log.py` -- reuse as pattern (read, not imported): append-only-write discipline (open in a mode that never truncates)
- `ledger_core/server.py`, `connectors/*/server.py` -- reuse: each module's existing `if __name__ == "__main__": mcp.run()` entry point is what `.mcp.json` launches; no changes expected
- `.mcp.json` -- new: project-scoped registration of all five servers
- `ops/run_scheduled_briefing.py` -- new: subprocess wrapper + `_ops.log.md` writer
- `ops/README.md` -- new: cron/launchd registration instructions (documentation only, nothing installed)
- `tests/test_scheduled_briefing.py` -- new: tests for every I/O matrix row, mocking `subprocess.run` (pattern: `tests/test_git_connector.py`'s `monkeypatch.setattr(subprocess, "run", ...)`)

## Tasks & Acceptance

**Execution:**
- [x] `.mcp.json` -- register `ledger-core` + four connectors as stdio servers via `uv run python -m {module}.server` -- AD-7
- [x] `ops/run_scheduled_briefing.py` -- implement `main()`: `subprocess.run(["claude", "-p", "--mcp-config", ".mcp.json", "--output-format", "json", PROMPT], timeout=..., capture_output=True, text=True)`; on non-zero exit/timeout/malformed-JSON stdout, append a typed entry to `ledger_data/_ops.log.md` and exit non-zero; on success exit 0 -- CAP-8, AD-7
- [x] `ops/README.md` -- document a sample crontab line and a sample launchd plist invoking `ops/run_scheduled_briefing.py`, and that installing either is a manual step
- [x] `tests/test_scheduled_briefing.py` -- unit tests for every I/O matrix row

**Acceptance Criteria:**
- Given the full test suite, when `uv run pytest` runs, then all tests pass.
- Given `claude -p` times out or exits non-zero, when `ops/run_scheduled_briefing.py` runs, then `ledger_data/_ops.log.md` gains exactly one new entry and no existing line in that file is altered.
- Given `.mcp.json`, when inspected, then it registers all five servers (`ledger-core`, `git-repo`, `ticketing`, `calendar-google`, `cmdb`) and none are given a config-file-sourced credential (AD-7: credentials come only from the OS keychain/env, never a git-tracked file).

## Design Notes

`ops/` is a new top-level directory, sibling to `connectors/`/`ledger_core/` — this is operational tooling, not a Sensor or the Ledger, so it doesn't belong under either. `_ops.log.md`'s line format doesn't need to match `ledger_core/log.py`'s `_LINE_RE`-parseable event grammar: nothing in this story reads `_ops.log.md` back programmatically, it exists for human/audit visibility (AD-7's own wording: "appends an error entry," not "appends a parseable event"), so a simple timestamped markdown bullet per entry is sufficient — no reader/parser is being built.

## Verification

**Commands:**
- `uv sync` -- expected: resolves without error (no new dependency expected) -- ran, resolved with no changes
- `uv run pytest -v` -- expected: all tests pass, including every prior story's -- ran, 399 passed after review fixes
- `uv run python -c "import json; json.load(open('.mcp.json'))"` -- expected: valid JSON, five server entries -- ran, confirmed

## Suggested Review Order

**Closing the "never raises past `main()`" gap review found (the real catch this round, confirmed with a concrete repro)**

- `_safe_append_ops_log_entry` -- every failure branch now logs through this wrapper instead of the raw logger, so a logging failure itself (e.g. the log's parent path already exists as a regular file) can never escape `main()` and break the story's own Acceptance Criterion.
  [`ops/run_scheduled_briefing.py:198`](../../../../ops/run_scheduled_briefing.py#L198)

- Proof: pointing `ops_log_path` at a location whose parent is a regular file, with an ordinary non-zero-exit failure, still returns non-zero instead of raising.
  [`tests/test_scheduled_briefing.py:323`](../../../../tests/test_scheduled_briefing.py#L323)

**Closing the packaging gap Story 2's review already caught once**

- `ops` added to the wheel's package list -- the exact bug class (a built wheel silently dropping a package) that Story 2's review found for the git connector.
  [`pyproject.toml:21`](../../../../pyproject.toml#L21)

**Closing the untested-contract gap between this story's AC and CI**

- `.mcp.json`'s shape (five servers, correct `command`/`args`, no credential-shaped fields) is now checked by the automated suite, not just a manual verification command.
  [`tests/test_mcp_config.py:33`](../../../../tests/test_mcp_config.py#L33)

**Smaller hardening and cleanup**

- `REASON_UNEXPECTED_ERROR` -- the catch-all branch no longer mislabels an infra-level failure (e.g. a missing `claude` binary) as `nonzero_exit`.
  [`ops/run_scheduled_briefing.py:76`](../../../../ops/run_scheduled_briefing.py#L76)

- `.mcp.json`'s path now resolves relative to the script's own location, not the caller's cwd; `stdin=subprocess.DEVNULL` added so an unexpected interactive prompt fails fast instead of hanging until timeout.
  [`ops/run_scheduled_briefing.py:49`](../../../../ops/run_scheduled_briefing.py#L49)
