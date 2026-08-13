---
title: Rez Ops — AI-Powered DR Program Management Agent
status: draft
created: 2026-08-12
updated: 2026-08-12
---

# Product Brief: Rez Ops

## Executive summary

Rez Ops is an AI agent framework — built on coding-agent runtimes like Claude Code, Claude Cowork, Gemini CLI, or Codex, connected via MCP (Model Context Protocol) — that manages an end-to-end Disaster Recovery (DR) program without becoming a new system of record. It plugs into the tools a program already has (CMDB, ticketing, calendar, git, BIA documents) and maintains a single, structured, continuously-expiring model of the program's real state: what's been verified, what's stale, and who's accountable right now.

The problem it solves is structural, not cosmetic: DR programs are reactive because compiling their true state is manual and slow, so it only happens right before an audit or right after an incident. At global, always-on scale, that lag is where real risk hides. Nothing today treats staleness as a first-class, expiring data model; nothing infers ownership from what's actually happening versus what a RACI doc says six reorgs later.

Rez Ops's positioning: **smoke detector, not fire inspector** — continuous, ambient, low-ceremony detection replacing the scheduled, high-ceremony annual inspection, and additive rather than a replacement: if it's ever wrong or down, the program falls back to today's manual baseline, never worse off. Why now: coding-agent runtimes and MCP have made it practical, for the first time, to build a thin orchestration layer over an organization's existing tools rather than another dashboard demanding to be fed.

## The problem

DR/resilience program owners at large, complex organizations are accountable for artifacts scattered across disconnected systems — BIAs in SharePoint or GRC tools, app/service tiering in a CMDB, runbooks and playbooks in wikis, RACI in a spreadsheet or org chart nobody re-syncs, test schedules in a tracker, and everything else in someone's head. None of these systems share a concept of *freshness*. A BIA doesn't know it's 18 months overdue for review; a RACI doc doesn't know its "Accountable" owner left the company two reorgs ago.

Because assembling the true state of the program is manual and slow, it only gets done under pressure — right before an audit, or right after an incident proves a gap was real. At global scale, the cost of that lag compounds: a stale Tier-1 BIA or an unmapped dependency isn't a paperwork problem — it's the thing that turns an outage into a disaster.

## The solution

Rez Ops connects to the systems a DR program already relies on — read-only first, via MCP, API, git, and file access — and maintains a **Freshness Ledger**: for every artifact type, a structured record of last-verified state, verification method, expiry rule, tier-based SLA, and escalation owner. This ledger, not any one source system, becomes the program's living source of truth about its own currency.

Ownership — the single most fragile, highest-leverage data point in any DR program — is inferred from live activity (commit history, on-call rotation, ticket assignment, org-chart/HRIS changes) rather than trusted from a static RACI cell, with a running "orphan-risk" list for anything that's drifted.

The primary interface is chat-queryable live state — "what's stale, what's due, what needs me" — answerable on demand. A daily or periodic human-in-the-loop briefing sits on top as one view of that state, not the product itself: it tells the program owner exactly what needs a decision today, ranked by risk, with the action (a message, a ticket, an escalation) already drafted for approval.

Everything the agent does is designed around three non-negotiables: **read-only-first** (no write-back to systems of record in v1), **graceful degradation** (if Rez Ops is wrong or down, the program falls back to today's manual baseline, never worse off), and **never hide its own uncertainty** (an explicit confidence/coverage map shows what's agent-verified versus still unknown, escalating uncertainty rather than papering over it).

## What makes this different

The established DR/BCM platforms all now market "AI," but it's generative drafting or dashboard insight layered onto a proprietary system of record. The closest AI-native competitor, Fortiv, is funded and moving fast in this exact problem space, but it's also building its own SaaS system of record. The closest architectural precedent, RiskReady, proves an MCP-native, human-approval-gated agent pattern works — but for general GRC, not DR/BIA/tiering specifically.

Rez Ops's differentiator is a product-philosophy choice, not a technical moat: it refuses to be a new system of record. Every incumbent above is structurally incentivized to own the data, because that's the business model. Rez Ops stays a thin, honest orchestration layer over whatever a program already has, and directly targets the actual root cause (fragmented, non-expiring data) rather than adding another place data can go stale. That trade-off can be replicated, and likely will be, if it proves out — the bet is that being the only one refusing to compete for system-of-record status is worth more, at least for early adoption and trust, than being first.

## Who this serves

**Primary user:** a DR/resilience program owner at a large, global, always-on business. `[ASSUMPTION]` Modeled on a Booking.com/Expedia-scale travel or e-commerce company: hundreds to thousands of services across multiple regions, 24/7 revenue-critical operations, a dense third-party dependency surface (payment processors, GDS/OTA integrations, cloud providers), and constant organizational churn that outpaces manual RACI upkeep. This person is accountable for BIA currency, tiering accuracy, ownership, runbook readiness, and DR test cadence across the whole estate — today, they reconstruct the "true state" by hand, under pressure, right before it matters most.

`[ASSUMPTION]` **Secondary users**, if this extends beyond a single owner's personal use: compliance/audit stakeholders who need durable, attributable evidence on demand rather than a reconstructed report; and application/service owners who currently only hear from the DR program when something is already overdue, who'd rather get one clear, actionable ping than a form to fill out.

## Success criteria

In the program owner's own words, success means the program becomes proactive, not reactive — made concrete two ways: **everything available** (every BIA, tiering record, runbook, playbook, RACI entry, and test record instantly on hand and queryable in one place, instead of rediscovered from scratch each time it's needed) and **early catches** (staleness, ownership gaps, and dependency risk surfaced before an auditor or an actual incident finds them, not after).

`[ASSUMPTION]` Concrete signals worth tracking once in use: zero "we didn't know that was stale" moments at the next audit or review; "who owns X" answered in seconds via a live query instead of days of chasing; and the daily/periodic briefing consistently surfacing something genuinely new, not repeating what's already handled. Signal, not noise, is itself a measure of whether the model is earning trust.

## Scope

**In for v1:**
- **Data model** — git-backed memory plus a Freshness Ledger (per artifact type: last verified, verification method, expiry rule, tier-based SLA, escalation owner) as the structured, expiring source of truth. Memory is plain files/git — human-readable and self-recoverable from day one, so Rez Ops can survive its own outage.
- **Connectors** — read-only first: calendar, ticketing, git, CMDB. No write-back to systems of record.
- **Confidence/coverage map** — explicit, per domain and tier, about what's agent-verified versus still manual/unknown.
- **Signature interface** — chat-queryable live state as the primary surface; a daily/periodic briefing is one swappable view on the same model, not the product itself.
- **Wedge feature** — ownership inferred from live activity signals (commits, on-call, ticket assignees, org-chart/HRIS changes) rather than a static RACI doc, with a maintained orphan-risk list.
- **Trust layer** (required before compliance/CISO adoption) — every inferred claim shows its sources; a human-approval gate on any write or outbound action; non-punitive, transparent framing; every automated action leaves a durable, attributable, timestamped record as a byproduct of normal operation.

**Explicitly out for v1** (revisit once trust is established):
- Write-back or auto-actioning against systems of record (e.g. auto-updating RACI, auto-filing tickets) — human approval required first.
- A retroactive "would-have-caught-it" scoreboard against past incidents, published for credibility.
- Proactive or surprise micro-drills, or agent-triggered synthetic failovers.
- Auto-sending owner-reconfirmation messages — the agent may draft, a human must approve and send.
- Broadening to many low-trust data sources — v1 favors fewer, high-trust, provenance-ranked sources over breadth.
- A passive-observation, watch-only baselining period to learn "normal" behavior.

`[ASSUMPTION]` Packaging is left open by design rather than decided here: whether Rez Ops stays a personal configuration for its own program, or becomes something installable by other DR practitioners, is a decision the brief defers rather than forces.

## Vision

If it earns trust doing the boring, honest v1 work — read-only, transparent about its own uncertainty, never worse than today's baseline — Rez Ops grows into the connective tissue of a resilience program rather than one more tool competing for attention inside it. Later stages (once trust, not before) could include a retroactive credibility scoreboard against real past incidents, agent-triggered proactive micro-drills, and cautious write-back with approval.

`[ASSUMPTION]` The same architecture isn't inherently specific to DR — if it proves out, it could extend to adjacent resilience programs (compliance, vendor risk, business continuity broadly) built on the same non-negotiables.
