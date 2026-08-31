---
title: 'Draft-not-send outbound content'
type: 'feature'
created: '2026-08-26'
status: 'done'
review_loop_iteration: 0
baseline_commit: '930bc784d68579ea2e54b9aa666c6b607c7b33fb'
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/ARCHITECTURE-SPINE.md'
  - '{project-root}/_bmad-output/specs/spec-rez-ops/SPEC.md'
  - '{project-root}/shared/ledger_schema/models.py'
  - '{project-root}/ledger_core/log.py'
  - '{project-root}/ledger_core/projection.py'
  - '{project-root}/ledger_core/server.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Rez Ops can compute state (confidence, coverage, ownership, orphan-risk) but has no way to draft outbound content for a human to act on — SPEC CAP-6 has no implementation, and AD-6's drafts queue doesn't exist yet.

**Approach:** Add two ledger-core tools: `ledger_create_draft` writes one draft as its own git-tracked markdown file (`ledger_data/drafts/{draft_id}.md`, frontmatter + body) — matching the architecture's structural tree and keeping the queue human-browsable, consistent with how the rest of `ledger_data/` already works. `ledger_list_drafts` retrieves them, optionally filtered. If `recipient` isn't given, `ledger_create_draft` looks up the artifact's `escalation_owner` (Story 8) as a default; if that's also unresolved (an orphan-risk artifact), `recipient` stays unset rather than guessed — the honest behavior for exactly the case this feature exists to surface. No send capability, no draft mutation or deletion — create and list only.

## Boundaries & Constraints

**Always:**
- Drafts are created only by `ledger_create_draft` — no other component ever writes to `ledger_data/drafts/` (AD-6). Connectors have no code path to `ledger_data/` at all, already true by construction (AD-1).
- Each draft is its own file, `ledger_data/drafts/{draft_id}.md`; `draft_id` is ledger-core-generated (timestamp + random suffix — there's no natural external ID to reuse for newly-authored content, unlike a connector's fetched facts), never user-supplied, so it can never be used for a path-traversal-style attack on the filename.
- `artifact_type`/`artifact_id` are validated against the same identifier charset every other component in this project already enforces (`^[A-Za-z0-9_-]+$`).
- `ledger_create_draft` never calls an external send/write API — the tool's only side effect is writing one file under `ledger_data/drafts/`.
- If `recipient` is omitted, look up the artifact's current `escalation_owner` via the existing `get_record` and use it as the default; if unresolved, leave `recipient` unset in the draft rather than fabricating one.
- Subject/body content in error messages, if any error path needs to reference the draft, never echoes potentially sensitive full body content back raw (same discipline as every connector's non-2xx/malformed-response handling).

**Ask First:**
- Any dependency beyond what's already direct.

**Never:**
- No send capability of any kind (no email, Slack, HTTP, or any external API call) — sending is a manual, human-initiated action entirely outside this system in v1.
- No draft mutation, update, or delete tool in this story — create and list only.
- No auto-population of `recipient` beyond the `escalation_owner` lookup — no other heuristic guesses at a recipient.
- No validation or interpretation of `subject`/`body` content — they're opaque text the caller supplies; ledger-core doesn't inspect or template them.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Explicit recipient | `recipient` given | Draft file written with that recipient, unchanged | N/A |
| No recipient, artifact has a resolved owner | `recipient` omitted, artifact's `escalation_owner` resolves to a value | Draft's `recipient` defaults to that value | N/A |
| No recipient, artifact is orphan-risk | `recipient` omitted, artifact has no resolved owner | Draft's `recipient` stays unset; draft is still created, not blocked | N/A |
| List, no filters | 2+ drafts exist across different artifacts | Returns every draft | N/A |
| List filtered by artifact_type/artifact_id | Filter to one artifact | Returns only that artifact's drafts | N/A |
| List filtered by draft_type | Filter to one draft type | Returns only matching drafts | N/A |
| No drafts yet | `ledger_data/drafts/` doesn't exist | `ledger_list_drafts` returns an empty list | Never raises |
| Empty/whitespace required field | `artifact_type`, `artifact_id`, `draft_type`, `subject`, or `body` is `""`/whitespace | No file written | Raises a typed validation error |
| Concurrent-ish creation, no collision | Two drafts created for the same artifact in quick succession | Both persist as distinct files | N/A |

</frozen-after-approval>

## Code Map

- `shared/ledger_schema/models.py` -- reuse (read-only): the identifier charset pattern to mirror for `artifact_type`/`artifact_id` validation
- `ledger_core/projection.py` -- reuse: `get_record` is the source of the `escalation_owner` default lookup; no changes expected
- `ledger_core/log.py` -- reuse as pattern (read, not imported): the append-only-write discipline (open in a mode that never truncates existing content) applies to how the drafts directory is written
- `ledger_core/server.py` -- edit: add `ledger_create_draft` and `ledger_list_drafts` tools
- `ledger_core/drafts.py` -- new: draft creation/listing logic (file I/O over `ledger_data/drafts/`), kept separate from `projection.py` since drafts aren't part of the append-only artifact-type log model
- `tests/test_ledger_core.py` -- edit: add tests for every I/O matrix row

## Tasks & Acceptance

**Execution:**
- [ ] `ledger_core/drafts.py` -- implement `create_draft(artifact_type, artifact_id, draft_type, subject, body, recipient=None, *, ledger_dir=...)` (validates inputs, resolves `recipient` default via `get_record` when omitted, generates a unique `draft_id`, writes `{ledger_dir}/drafts/{draft_id}.md`) and `list_drafts(artifact_type=None, artifact_id=None, draft_type=None, *, ledger_dir=...)` (reads and optionally filters) -- AD-6
- [ ] `ledger_core/server.py` -- add `ledger_create_draft` and `ledger_list_drafts` MCP tools wrapping the above
- [ ] `tests/test_ledger_core.py` -- unit tests for every I/O matrix row

**Acceptance Criteria:**
- Given the full test suite, when `uv run pytest` runs, then all tests pass.
- Given a draft created with no `recipient` for an orphan-risk artifact, when the resulting draft is listed, then `recipient` is absent/`None`, not a guessed value.
- Given the ledger-core MCP server, when a client lists its tools, then `ledger_create_draft` and `ledger_list_drafts` both exist alongside the four existing tools, and neither `ledger_create_draft` nor any other tool calls an external send API.

## Spec Change Log

## Design Notes

`draft_id` combines a sortable UTC timestamp with a short random suffix (e.g. `20260826T140512Z-a1b2c3`) — sortable for a human browsing the directory, collision-safe without needing a natural external ID (unlike connector-sourced facts, a draft is new content ledger-core itself authors). The frontmatter/body split mirrors the project's existing `memlog.py`-adjacent convention of human-readable, git-diffable files: frontmatter carries `artifact_type`, `artifact_id`, `draft_type`, `recipient`, `created_at`; the body below is the drafted message text as-is.

## Verification

**Commands:**
- `uv sync` -- expected: resolves without error (no new dependency expected) -- ran, resolved with no changes
- `uv run pytest -v` -- expected: all tests pass, including every prior story's -- ran, 367 passed after review fixes
- `uv run python -c "import ledger_core.server"` -- expected: imports without error -- ran, imported cleanly

## Suggested Review Order

**Closing the injection risk review found (the real catch this round)**

- `draft_type` now escaped like `subject`/`recipient` already were -- the gap let a crafted value corrupt a draft file or overwrite `artifact_type` in parsed metadata.
  [`drafts.py:178`](../../../../ledger_core/drafts.py#L178)

- Duplicate-key detection in the parser -- defense in depth once escaping closed the practical attack path.
  [`drafts.py:222`](../../../../ledger_core/drafts.py#L222)

- Proof: an embedded newline in `draft_type` no longer corrupts the file or bleeds into `artifact_type`.
  [`test_ledger_core.py:2790`](../../../../tests/test_ledger_core.py#L2790)

**Applying Story 8's graceful-degradation lesson to drafts**

- A corrupted draft file is now isolated (sentinel record), not fatal to listing every other draft -- same AD-8 pattern `list_records`/`get_coverage_map` already established.
  [`drafts.py:394`](../../../../ledger_core/drafts.py#L394)

- Proof: one tampered file doesn't block the rest.
  [`test_ledger_core.py:2868`](../../../../tests/test_ledger_core.py#L2868)

**The tools themselves**

- `create_draft` -- validates inputs, resolves `recipient` from `escalation_owner` when omitted, generates a collision-safe id, writes the file.
  [`drafts.py:269`](../../../../ledger_core/drafts.py#L269)

- The two new MCP tools, bringing ledger-core to six total.
  [`server.py:178`](../../../../ledger_core/server.py#L178), [`:226`](../../../../ledger_core/server.py#L226)
