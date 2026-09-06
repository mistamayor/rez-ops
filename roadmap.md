# Rez Ops Roadmap

What's shipped, what's next, and what's still an open question — kept up to date as the project moves, so anyone can see where it stands without reading the full spec.

This is the human-facing narrative. The machine contract — capabilities, constraints, and the story-by-story build record — lives in [`_bmad-output/specs/spec-rez-ops/SPEC.md`](_bmad-output/specs/spec-rez-ops/SPEC.md), [`ARCHITECTURE-SPINE.md`](_bmad-output/planning-artifacts/architecture/architecture-Resillience-Ops-2026-08-12/ARCHITECTURE-SPINE.md), and [`stories.yaml`](_bmad-output/specs/spec-rez-ops/stories.yaml); lower-priority hardening items are tracked in [`deferred-work.md`](_bmad-output/implementation-artifacts/deferred-work.md). This file should always be safe to hand to someone who's never opened any of those.

**Legend:** 🟢 Shipped · 🟡 In Progress · ⚪ Planned · ❓ Open Question

---

## Now — Shipped

16 stories, 682 tests. The Sensors → Ledger → Voice paradigm, end to end:

- 🟢 **Freshness Ledger core** — append-only event log, pure projection, explicit confidence (`agent-verified` / `manual` / `unknown`) on every derived value.
- 🟢 **Six Sensors** (read-only, metadata only) — git, ServiceNow ticketing, Google Calendar, ServiceNow CMDB, Google Drive, SharePoint (Microsoft Graph).
- 🟢 **Ownership inference & arbitration** — an authoritative owner resolved from conflicting signals; orphan-risk surfaced, never guessed.
- 🟢 **Draft-not-send outbound content** — every drafted message sits in a queue; no auto-send path exists.
- 🟢 **Periodic briefing + scheduled headless operation** — a daily briefing an OS scheduler can run unattended, with explicit failure logging.
- 🟢 **Evidence-backed claims** (`EvidenceBundle`) — confidence computed exclusively by ledger-core from cited facts, never asserted by the caller.
- 🟢 **Policy-gated action proposals** (`ActionProposal`) — `policy_decision` computed from config-declared risk and target criticality; no Executor exists yet, so nothing acts on it.
- 🟢 **Cross-cutting hardening** — unambiguous per-connector provenance strings, stripped/validated credentials, graceful degradation on a corrupted ledger log.

## Next

Extends existing machinery — no new architecture decision required.

- ⚪ **DR risk classification (rules engine)** — populate `tier_sla`/expiry rules (defined in the schema since the project's foundation, never populated by any story) and compute a risk level from tier × freshness × confidence, feeding directly into the already-built policy engine. Sharpened against a real reference design rather than left generic: RTO/RPO achieved as a percentage against target (not bare pass/fail), a mandated annual testing-window compliance check, and RAG broken down across three independent axes (application tier, infrastructure, data centres) rather than one flat list.
- ⚪ **DR readiness summary query** — one new read-only MCP tool aggregating the above into a single call, the same shape as the existing `ledger_get_briefing`. A data endpoint, not a UI.
- ⚪ **Executive dashboard, phase 1** — a regenerate-on-demand static HTML snapshot (no hosted server; stays inside the local-first constraint) rendering KPI tiles, RAG status, upcoming/recent tests, and the dependency map below. Look and feel already validated in a live prototype: warm-neutral palette, a single accent color, confidence expressed as a dot-fill (not just a bare percentage) everywhere a number claims to be known.
- ⚪ **Evidence investigation panel ("Ask Rez Ops")** — a UI expression of the already-built `EvidenceBundle`: a cited, confidence-scored answer to a plain-language question, with explicit next actions (draft a message, propose an action) that stay inside the existing never-auto-act discipline — never a one-click "accept."
- ⚪ **Dependency mapping (first cut)** — a generic `depends_on` edge on the existing artifact substrate, not the full typed domain model below; most likely sourced by extending the existing CMDB connector to also fetch ServiceNow's CI relationship data. *Placed here rather than Later because it doesn't require the domain-model decision to ship real value — flagged for confirmation, not yet locked in.*

## Later — pending a dedicated architecture session

Each of these changes a real, current design decision (the generic `artifact_type`/`artifact_id` substrate, or the metadata-only connector boundary) and needs its own threat-modeled AD before a story gets written — not a default extrapolation from anything above.

- ⚪ **Structured DR domain model** — typed entities (`Application`, `DRPlan`, `DRTest`, `Dependency`, etc.) layered over, not replacing, the generic substrate.
- ⚪ **Document-content ingestion** — SharePoint/Drive connectors move beyond last-modified metadata to actual document content; needs its own threat model given the prompt-injection surface this opens for the LLM-based Voice layer.
- ⚪ **DR test-management domain** — test / plan / scenario, expected vs. achieved RTO/RPO, remediation, retest. Folds into the domain-model decision above.
- ⚪ **Compliance/audit lifecycle** — framework-scoped evidence (e.g. ISO 27001): requirement → control → evidence → finding → closure, rather than one generic audit-finding bucket.
- ⚪ **Lessons Learned** — retrospective capture tied to a test or incident, and whether the resulting improvement action actually closed. A real gap an early written review of this roadmap's source material missed entirely; confirmed against a reference design.
- ⚪ **Executive dashboard, phase 2** — a real hosted/live web app (auto-refreshing, no manual regenerate step). Requires deliberately revisiting the local-first, no-persistent-server constraint — not something to fall into by accident.
- ⚪ **Richer dependency relationships** — once the domain model lands, a dependency can carry a typed kind (runtime dependency vs. data dependency vs. shared infrastructure) instead of one generic edge.

## Open Questions

- ❓ **Customer Assurance** — curated, external-facing evidence for a named customer is a real, distinct capability in the reference design this roadmap was shaped against. Not committed to any phase — may not apply to this project's actual use case.

## Explicitly Not Planned

- Rez Ops replacing an organization's own portal or reporting tool outright — it stays the intelligence layer underneath one, never the human-facing system of record.
- Auto-executing any DR action — the Executor interface is designed (three architecture decisions describe it in full) but deliberately not built; every proposal stops at a human approval gate.
- Human-initiated actions like "report an issue" — stay human-driven, never something Rez Ops auto-files on someone's behalf.
- Multi-tenant or multi-user support.

---

*Update this file whenever a Next/Later item ships or a new one gets scoped. Last updated 2026-09-06.*
