# Brainstorm Intent: AI-Powered DR Program Agent

## Topic
An AI-powered pluggable agent/framework (Claude Code/Cowork, Gemini, Codex, etc.) to manage an end-to-end Disaster Recovery program.

## Goal
Shift DR program management from reactive to proactive while minimizing manual effort and keeping a human in the loop; never miss a dependency/impact from changes; automate documentation and compliance evidence.

## Positioning
**Smoke detector, not fire inspector.** Continuous, ambient, low-ceremony detection — not a scheduled, high-ceremony annual inspection with a clipboard.

## Proposed V1 Scope (core intent)
- **Data model**: git-backed memory + a Freshness Ledger (per artifact type: last verified, verification method, expiry rule, tier-based SLA, escalation owner) as the structured, expiring source of truth — not a static one-time deliverable. Memory is human-readable and self-recoverable from day one (plain files/git, not a proprietary DB) — the DR tool must itself survive its own outage.
- **Connectors**: read-only first — calendar, ticketing, git, CMDB. No write-back to systems of record in v1.
- **Confidence/coverage map**: the agent is explicit about what it can vs cannot verify yet (agent-verified vs manual/unknown per domain/tier).
- **Signature UI**: chat-queryable live state (what's stale, what's due, what needs me) is the primary interface; a daily/periodic digest is just one swappable view on top of the same model, not the product itself.
- **Wedge feature**: ownership fragility — infer RACI/ownership from live activity signals (commits, on-call, ticket assignees, org-chart/HRIS changes) rather than trusting a static RACI doc; maintain a live orphan-risk list. (Optional naming: "OwnerGraph" — ownership as a versioned graph with commit-style history.)
- **Trust layer (required before compliance/CISO adoption)**: every inferred claim shows its sources; human-approval gate on any write/action; non-punitive, transparent framing to avoid corrupting the data it observes. Every automated action leaves a durable, attributable, timestamped record as a byproduct, not a separate task. (Optional naming: "Antibody Ledger" for incident-derived checks/immunity memory; "Black Box Briefing" for replayable daily-briefing-as-flight-recorder; "Risk Forecast" for probabilistic rather than binary compliance status.)

### Hard non-negotiables (design constraints, not aspirations)
1. **Read-only-first.** No write-back to systems of record in v1; every connector reads before it ever writes.
2. **Graceful degradation.** If the agent is down or wrong, the program falls back to today's manual baseline — never worse off. It is additive, not a replacement for systems of record.
3. **Never hide its own uncertainty.** The confidence/coverage map must show agent-verified vs unknown explicitly; escalate uncertainty rather than paper over it. This is the designed-in antidote to false confidence, not a bolt-on.

## Why this scope (compressed rationale)
1. Staleness must be a first-class, expiring data model (Freshness Ledger + staleness-heartbeat root cause + hard-expire-by-default) — the single strongest convergence.
2. Architecture follows from this: git-backed, human-readable memory; live-regenerated artifacts (runbooks-as-cache, not source of truth); ledger doubling as the audit/compliance trail. Fast-to-start, durable, and self-recoverable are not in tension once the substrate is git-backed from day one.
3. Ownership is the most fragile, highest-leverage data domain — everything else depends on knowing who to ping right now, so it's the wedge, ahead of BIA or runbooks.
4. The product is a trust-building live/verifiable state model, not a notification bot — the daily catch-up is just the friendliest UI on top of it.
5. Trust and psychological safety are first-class design constraints, not afterthoughts — gamed metrics, hidden dependencies, notification fatigue, and self-starving budget optics are real failure modes if ignored.
6. A natural, honest v1 boundary: read-only connectors + a confidence/coverage map that is upfront about what the agent can't see yet, rather than overclaiming coverage. The agent introduces a new dependency by existing at all — net risk-reducing only if the three non-negotiables above hold.

## Explicitly Out of Scope for V1 (later, once trust is established)
- Write-back / auto-actioning against systems of record (e.g., auto-updating RACI, auto-filing tickets) — human approval gate required first.
- **Blast Radius Rewind**: retroactive "would-have-caught-it" scoreboard against past incidents, published for credibility.
- Proactive/surprise micro-drills or agent-triggered synthetic failovers.
- Auto-sending owner-reconfirmation messages (agent may draft, human must approve/send).
- Broadening to many low-trust data sources — v1 favors fewer, high-trust, provenance-ranked sources.
- Passive-observation behavioral-anomaly baselining (watch-only week to learn "normal").
