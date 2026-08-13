---
name: 'Rez Ops — Adversarial Spine Review'
type: architecture-review
lens: adversarial-two-units
target: architecture-Resillience-Ops-2026-08-12/ARCHITECTURE-SPINE.md
created: '2026-08-12'
---

# Adversarial Review — Rez Ops Architecture Spine

**Method:** for each pair below, two engineers each read only the spine (ADs 1–7 + conventions), each implements a unit one level down (a connector, ledger-core, or the shared schema module) that satisfies every AD it is bound by *to the letter*, and the two units still build incompatibly — a clashing shared-data shape, two owners of one entity, or two conflicting mutation paths. Each pair closes with the AD (new or tightened) that would have prevented it.

**Verdict:** the spine's layering (AD-1, AD-2) is sound, but it under-specifies *ownership at the seams* — which connector may assert which field, who is the only writer to a shared directory, and whether the shared schema has one shape or two. Five load-bearing holes found; all are closable with narrow AD additions/tightenings, none require re-architecting the paradigm.

---

## Pair 1 — Tool-name collision across Sensor MCP servers

**Unit A:** Calendar-connector engineer, following AD-1 ("dumb, stateless, read-only fetch-and-normalize") and AD-2 ("minimal, domain-scoped toolset"), ships tools `list_items`, `get_item`, `normalize`.

**Unit B:** CMDB-connector engineer, following the same two ADs equally literally, ships tools `list_items`, `get_item`, `normalize` for CI records.

**The clash:** both servers are registered in the same `.mcp.json` and both load into every Voice session (AD-2's own stated rationale: "every connected server's tools load into every session"). MCP tool identifiers must be unique per session; two servers exposing identically-named tools produce ambiguous invocation or silent shadowing in the runtime, with no domain logic anywhere to blame — each server individually is fully AD-1/AD-2 compliant.

**Root gap:** AD-2 mandates *one server per domain* but never mandates *namespaced tool identifiers* within that server. Nothing in the spine assigns a naming convention for tools or for server keys in `.mcp.json`.

**Close with:** tighten AD-2 (or add AD-8) — every connector MCP server prefixes every exposed tool name with its domain (`calendar_list_events`, `cmdb_list_cis`), and server registration keys in `.mcp.json` follow a fixed `<domain>-sensor` / `ledger-core` convention. Make this a rule, not a convention-table footnote, since it is exactly the kind of thing two independent engineers will not converge on by accident.

---

## Pair 2 — Two connectors, one entity, no reconciliation rule

**Unit A:** Ticketing-connector engineer, per AD-1 (fetch-and-normalize) and AD-5 ("connectors report only raw timestamps and records — never a confidence score"), emits a raw fact for artifact-type `tiering`, artifact-id `payment-service`: `escalation_owner: "ops-oncall"`, derived from the ticket's current assignee field.

**Unit B:** CMDB-connector engineer, equally AD-1/AD-5-compliant, emits a raw fact for the same artifact-type/artifact-id: `escalation_owner: "platform-team"`, derived from the CI's owner attribute.

**The clash:** both payloads conform to AD-4's shared schema (same field name, same artifact-id), both are legitimately "raw connector facts" per AD-5's letter, yet they assert contradictory values for the same entity's same field. AD-5 says ledger-core computes confidence/coverage "from raw connector facts, using one documented method" — but nothing says what happens when two connectors' raw facts about the *same* field disagree. Whichever git commit lands second wins by silent overwrite, with no signal that a conflict occurred.

**Root gap:** no artifact-type-to-connector ownership map, and no conflict-handling rule for ledger-core when two Sensors both speak to the same field of the same entity.

**Close with:** add AD-9 — the shared schema module declares, per field per artifact-type, which connector(s) are authoritative sources; ledger-core treats a disagreement between two non-designated (or co-equal) sources not as last-write-wins but as an explicit low-confidence/`unknown`-escalation case (consistent with the existing "never silently drop, escalate to unknown" convention) — i.e., extend the *existing* Consistency Convention row into a binding AD rather than leaving it as prose.

---

## Pair 3 — Two writers to the same mutation path

**Unit A:** Ledger-core engineer implements AD-3 to the letter: a single internal append-only writer module is the only code path that touches `ledger_data/`, including `ledger_data/drafts/`, exposing it as an MCP tool (e.g. `ledger_core.queue_draft`) so every write — draft or otherwise — is logged with actor/timestamp/reason per the Consistency Convention.

**Unit B:** A future write-capable connector engineer (e.g., an email-outreach connector) implements AD-6 to the letter: "any agent-authored outbound content is written only to a git-tracked `drafts/` queue as a pending record. No component calls an external send/write API directly." AD-6 explicitly *binds* "any future write-capable connector," and its rule says nothing about routing through ledger-core — only that no external send API is called. So the connector engineer has its process write the draft file straight into `ledger_data/drafts/{id}.yaml` itself, fully satisfying AD-6's literal text.

**The clash:** now `ledger_data/` — a directory AD-3 (scoped to "ledger-core") and the Consistency Convention ("all mutation goes through ledger-core's single append-only writer") both implicitly assume has one writer — has two. The connector's direct write has no append-only event log entry, no actor/timestamp/reason record, and bypasses ledger-core entirely; ledger-core's projection logic, built assuming it is the sole mutator, has no way to know the draft exists until a projection recompute happens to notice a file it didn't write.

**Root gap:** AD-6 authorizes a class of writer ("any future write-capable connector") without designating *how* that writer's output reaches the ledger. AD-3's "single writer" guarantee is stated as a convention-table aside, not as an explicit constraint AD-6 is required to honor.

**Close with:** tighten AD-6 — a write-capable connector never touches `ledger_data/` directly; it must submit drafts through ledger-core's write-path MCP tool (the same one AD-3 designates), so the "sole owner of the Freshness Ledger" in AD-1 and "single append-only writer" in the conventions table extend, unambiguously, to drafts too. This also closes a quiet contradiction between AD-1 ("Connectors and Ledger-Core never call each other directly — the Runtime mediates all data flow") and a connector writing straight to a ledger-core-owned directory — AD-6 as written is the one place that contradiction can sneak in.

---

## Pair 4 — Shared schema conflates raw-input shape and derived-output shape

**Unit A:** Calendar-connector engineer, obeying AD-4 to the letter ("every connector... import it; none declares ad hoc fields"), imports the *one* shared schema module and instantiates its full per-artifact-type record type for every record it emits — including the `confidence` field the Consistency Convention says "every record carries... per the shared schema (AD-4)." Since no separate connector-input variant exists, the engineer sets `confidence: "unknown"` as a structurally-required default rather than omitting the field.

**Unit B:** Git-repo-connector engineer, obeying AD-5 to the letter ("connectors report only raw timestamps and records — never a confidence score"), strips the `confidence` key from every emitted record entirely — technically not "declaring an ad hoc field" (AD-4's actual prohibition), just omitting a schema-defined one.

**The clash:** ledger-core now receives two structurally different payloads — one with a populated (if placeholder) confidence field, one missing it — for what AD-4 calls "one shared, versioned schema module [that] defines every artifact-type record shape." Both connectors can point to a literal AD they satisfied; neither violated AD-4's stated prohibition (ad hoc fields) or AD-5's stated prohibition (asserting *a* confidence score, as opposed to a placeholder/absent one) unambiguously.

**Root gap:** AD-4 describes one schema shape per artifact type, used by both raw connector output and ledger-computed output, without distinguishing which fields are connector-writable versus ledger-core-only. AD-5 states the *intent* (connectors never assert confidence) but the schema itself doesn't enforce it structurally.

**Close with:** add AD-10 — the shared schema module defines two explicit variants per artifact type: a `RawFact` shape (connector-writable: ids, timestamps, raw domain fields only — no `confidence`/`coverage`/`escalation_owner` fields exist on this type at all) and a `LedgerRecord` shape (ledger-core-only, a superset). Connectors import and can only construct `RawFact`; the derived fields are not merely "not to be populated by convention," they don't exist on the type available to connector code. This turns AD-5 from a documentation-enforced rule into a type-enforced one.

---

## Pair 5 — `tier_sla` has three plausible owners

**Unit A:** Runtime/config-focused engineer reads the Stack/config line — "`rezops.config.yaml` — enabled connectors, tier SLAs" — and, since AD-1 only forbids the *runtime* from holding domain logic (not from reading static config), has the Voice layer read `tier_sla` directly out of `rezops.config.yaml` at prompt time to annotate output, skipping a ledger-core round trip for what looks like a static lookup table.

**Unit B:** CMDB-connector engineer notes that real CMDBs commonly store a service-tier attribute per CI, and — since AD-1 says connectors "fetch and normalize" domain facts, and `tier_sla` is listed as a field every record carries "per the shared schema (AD-4)" — reports `tier_sla` as an observed `RawFact` field for CMDB artifacts, expecting ledger-core to merge it in.

**The clash:** there are now three candidate sources of truth for the same field — static config (read directly by the runtime), a connector-observed raw fact, and whatever ledger-core would otherwise compute/carry forward — with no AD stating which wins, and Unit A's path additionally reintroduces exactly the "domain logic in the runtime" leakage AD-1 exists to prevent, without technically breaking AD-1's one explicit prohibition (computing freshness/confidence/ownership — SLA lookup isn't named).

**Root gap:** `tier_sla` is mentioned in two unconnected places (Stack/config table and the shared-schema field list) with no AD reconciling them, and AD-1's "no domain logic in the runtime" is scoped by example (freshness/confidence/ownership) rather than by a general principle covering any ledger-relevant field.

**Close with:** tighten AD-5 (or add AD-11) — ledger-core is the sole owner of `tier_sla` as it appears in ledger records: `rezops.config.yaml` supplies only the default SLA *policy table*, which ledger-core reads once and merges into records it produces; no connector may report `tier_sla` as an observed raw fact unless a field-ownership map (per Pair 2's AD-9) explicitly whitelists it for that artifact type; and the runtime may only ever read `tier_sla` off a ledger-core-produced record, never off `rezops.config.yaml` directly — generalizing AD-1's prohibition from "freshness/confidence/ownership" to "any field the shared schema defines."

---

## Summary table

| # | Clashing units | Shared thing that breaks | Close with |
| --- | --- | --- | --- |
| 1 | Any two Sensor connectors | MCP tool-name identifiers | Tighten AD-2: mandatory `<domain>_`-prefixed tool names + fixed server-key convention |
| 2 | Ticketing connector vs. CMDB connector | `escalation_owner` (or any shared field) for one entity | New AD-9: per-field connector ownership map + conflict → `unknown`-escalation, not last-write-wins |
| 3 | Ledger-core vs. future write-capable connector | Write access to `ledger_data/drafts/` | Tighten AD-6: drafts submitted only through ledger-core's write tool, never direct filesystem writes |
| 4 | Two connectors (e.g., calendar vs. git) | Shape of the record payload (confidence field present/absent) | New AD-10: schema splits into `RawFact` (connector) vs `LedgerRecord` (ledger-core) types |
| 5 | Runtime/config path vs. CMDB connector | `tier_sla` source of truth | Tighten AD-5/new AD-11: ledger-core sole owner of schema-defined fields incl. `tier_sla`; config supplies policy only, runtime reads only ledger records |

None of these require abandoning Sensors–Ledger–Voice; all five are seam-ownership gaps the paradigm's layering doesn't itself resolve. Recommend folding AD-9 through AD-11 (or equivalent tightenings of AD-2/5/6) into the spine before any second connector or ledger-core implementation begins — Pair 2 and Pair 5 in particular will silently corrupt ledger state rather than fail loudly, which is the worst failure mode for a system whose entire value proposition is trustworthy freshness data.
