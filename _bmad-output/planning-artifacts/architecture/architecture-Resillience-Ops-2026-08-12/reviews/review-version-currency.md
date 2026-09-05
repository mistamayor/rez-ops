# Version-Currency Review — Rez Ops Architecture Spine (AD-11/AD-12 pass)

**Reviewed:** ARCHITECTURE-SPINE.md, `updated: 2026-09-05`
**Scope:** this pass covers only what's new since the 2026-08-12 baseline — AD-11 (Evidence boundary), AD-12 (ActionProposal and the Policy Engine), and the small amendments to AD-1 and AD-6 that reference them. AD-1 through AD-10 and the Stack table were verified in the prior (2026-08-12) pass and are re-examined here only where the new ADs might contradict them.
**Method:** re-read the spine in full; enumerated every named technology/library/format/protocol claim inside AD-11, AD-12, and the AD-1/AD-6 amendments; web-searched to reality-check the one area where those ADs touch external tooling (MCP's own approval/annotation primitives), and spot-re-confirmed the `mcp` SDK pin since AD-12 leans on ledger-core MCP tool calls.

## Verdict

**PASS.** AD-11 and AD-12 introduce no new external library, framework, file format, or protocol — `EvidenceBundle`, `ActionProposal`, and `rezops.policy.yaml` are Rez-Ops-internal schema/config additions layered on the Stack table's already-verified Python/`mcp`-SDK/git substrate, so there is nothing new here that required (and was skipped on) web verification. One soft gap is worth recording: AD-12's custom approval-gating design isn't shown to have been reality-checked against MCP's own native tool-annotation and elicitation primitives, which already exist in the pinned SDK and address an overlapping concern.

## What AD-11/AD-12 actually assert, checked line by line

| Claim in AD-11/AD-12 | External tech named? | Verification needed? |
| --- | --- | --- |
| `EvidenceBundle` shape (`claim`, `confidence: float 0–1`, `evidence: list[EvidenceRef]`, `reasoning`, `generated_at`) | No — new internal schema type in the existing shared schema module (AD-4/AD-9) | No — pure project-internal design, not a version-currency claim |
| `EvidenceRef` cites a `RawFact.source` or `LedgerRecord` field, never inlining content | No — internal convention | No |
| One file per bundle at `ledger_data/evidence/{evidence_id}.md` | No — filesystem convention, mirrors AD-6's existing `drafts/` mechanism | No |
| `ActionProposal` shape (`action`, `target`, `reason`, `evidence`, `impact`, `policy_decision`) | No — new internal schema type | No |
| Fixed vocabulary of action identifiers ("never freeform") | Implicit reliance on JSON-schema `enum`/`Literal` support in MCP tool input schemas | Checked — the pinned `mcp` 1.29.x Python SDK builds tool input schemas from Pydantic models, which support `Literal`/enum constraints; this is ordinary, unversioned JSON Schema capability, not a new dependency |
| `policy_decision` (`automatic` \| `requires_approval` \| `denied`) computed by ledger-core from `rezops.policy.yaml` | No — new config file, same mechanism class as the already-verified `rezops.config.yaml` | No |
| "No executor exists in this phase" / nothing calls an external write/send API | No — a *non*-claim (explicitly deferred), nothing to verify | No |
| AD-1 amendment: "Read-only by default; action is an explicit, separately-gated capability" | No | No |
| AD-6 amendment: `ActionProposal` is a distinct shape from `Draft`, never a variant of it | No | No |

No row above names a new dependency, data format, or protocol outside what the Stack table already covers (Python, `mcp` SDK, Claude Code, git). So the primary risk this review type looks for — a committed decision asserted from training data about *external* tech — doesn't arise in the new material; the new ADs are internal-design decisions, not technology-adoption decisions.

## Findings

1. **[Info / re-confirmed, not new] The `mcp` SDK `<2` pin is still correct and current.** Re-checked since AD-12 leans on ledger-core MCP tool calls for policy evaluation: the MCP Python SDK v2 line went stable on 2026-07-27/28 alongside the 2026-07-28 spec revision, and `pip install mcp` now resolves to 2.x by default — so the Stack table's explicit `mcp` pin at `1.29.x, <2` remains necessary, not just accurate as of the prior pass. v1.x continues to receive security/bugfix patches per the SDK's own docs. This isn't a new AD-11/12 claim, but it's the one place the new ADs touch the already-verified Stack row, so it was worth re-touching rather than assuming. No contradiction found.
   Sources: [MCP Python SDK — PyPI](https://pypi.org/project/mcp/), [Beta SDKs for the 2026-07-28 MCP Spec Release Candidate](https://blog.modelcontextprotocol.io/posts/sdk-betas-2026-07-28/), [modelcontextprotocol/python-sdk releases](https://github.com/modelcontextprotocol/python-sdk/releases)

2. **[Low-Medium, documentation gap rather than an error] AD-12's approval-gating design doesn't note whether it considered MCP's own native tool-annotation/elicitation primitives.** MCP already ships `readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint` tool annotations (since the 2025-03-26 spec revision) and an `elicitation` capability for mid-session user confirmation (since 2025-06-18) — both available in the pinned `mcp` 1.29.x SDK today. AD-12 builds a fully custom, ledger-core-resolved policy engine instead. That's a defensible and arguably *stronger* choice — the MCP project's own blog is explicit that annotation hints "do not replace authorization, confirmation, rate limits, input validation, or server-side policy checks," which is exactly the gap AD-12's server-side `policy_decision` fills — but the spine doesn't record that this native alternative was looked at and found insufficient for the trust-layer guarantee AD-12 exists to provide (client-supplied hints are explicitly documented as untrusted unless the server itself is trusted, whereas AD-12's decision is computed server-side by ledger-core itself). Recommend a one-line addition to AD-12 or the Deferred section noting this was a deliberate choice, so a future reader doesn't mistake the omission for an unresearched gap.
   Sources: [Tool Annotations as Risk Vocabulary](https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/), [Testing MCP Tool Annotations (July 2026)](https://sunpeak.ai/blogs/testing-mcp-tool-annotations/)

3. **[Info] AD-1 and AD-6 amendments add no new external claims.** Both amendments only cross-reference the new AD-11/AD-12 object shapes (`EvidenceBundle`, `ActionProposal`) and restate existing AD-5/AD-6 ownership rules; nothing in either amendment names a technology, version, or format that wasn't already covered by the original AD-1/AD-6 text or the Stack table.

4. **[Info] No greenfield-starter angle applies to this pass.** AD-11/AD-12 don't touch scaffolding, a project generator, or any starter template's defaults — the "greenfield: live defaults of any starter it leans on" check in the task brief doesn't have a target in this diff; the spine has no starter/scaffold dependency anywhere (confirmed by re-scanning the Stack and Structural Seed sections, unchanged from the prior pass).

5. **[Info] Internal-consistency spot-check, not version currency, but noted while reading:** AD-11/AD-12's typing style (`list[EvidenceRef]`, `list[EvidenceBundle ref]`) matches PEP 585 generic-alias syntax, valid on the Stack table's Python 3.13+ floor — consistent, no action needed.

## What was NOT re-verified (by design, per instructions)

AD-1 through AD-10, the Consistency Conventions table, and the Stack table's Python/Claude-Code/git rows were treated as already reality-checked in the 2026-08-12 pass and were not re-researched here, since AD-11/AD-12 don't contradict any of them — they extend AD-5's "ledger-core owns derived computation" principle and AD-6's draft/write-boundary mechanism rather than revising them.
