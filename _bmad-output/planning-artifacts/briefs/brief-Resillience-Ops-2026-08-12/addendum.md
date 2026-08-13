# Addendum: Rez Ops

Supporting depth that doesn't belong in the tight brief but is worth keeping for downstream work (PRD, architecture).

## Source Material

Full brainstorming session (13 and 8 techniques, ~115 ideas, two syntheses) preceding this brief:
`_bmad-output/brainstorming/brainstorm-disaster-recovery-ai-agent-2026-08-12/` — `brainstorm.html` (full keepsake), `brainstorm-intent.md` (distilled intent).

## Full Competitive Landscape Digest

Gathered via web research, 2026-08-12. The brief's "What Makes This Different" section is a compressed summary of this.

**Honest read:** genuinely underserved, but narrowing fast. Fortiv, backed by recent funding, is moving quickly in exactly this problem space; RiskReady proves the technical pattern is trivial to replicate for DR once someone points MCP servers at BIA/runbook/RACI schemas; incumbents already have data-gap-detection instincts and could bolt on staleness monitoring given their existing CMDB/BIA data access. The window for "refuse to be the system of record" as a differentiator is real today but not guaranteed to stay open.

### Established DR/BCM GRC players

AI features are real but shallow-to-moderate; all remain systems of record:
- **Fusion Risk Management** — most AI-forward incumbent; "Resilience Copilot" / "Fusion Intelligence" auto-completes portions of BIAs, runs scenario-simulation variants, flags data gaps in BIA/risk/plan data (staleness-adjacent). Still a proprietary system of record, not agent-pluggable. [Fusion Intelligence](https://www.fusionrm.com/platform/fusion-intelligence/) · [BC Plan inFusion launch](https://www.businesswire.com/news/home/20250219003827/en/Fusion-Risk-Management-Introduces-BC-Plan-inFusion-to-Accelerate-Business-Continuity-Planning-with-AI-Powered-Transformation)
- **ServiceNow BCM** — dependency mapping real but entirely dependent on CMDB data quality/completeness. AI layer is prediction/optimization framing, not autonomous agents. [ServiceNow BCM](https://www.servicenow.com/products/business-continuity-management.html) · [Community: BCM & AI](https://www.servicenow.com/community/innovation-office-blog/business-continuity-in-the-age-of-ai/ba-p/3388996)
- **Riskonnect** — generative AI drafts BCP/BIA/incident-template content (writing assistant, not an autonomous auditor). [Riskonnect GenAI announcement](https://riskonnect.com/press/riskonnect-announces-generative-ai-for-business-continuity-planning/)
- **MetricStream** — "continuous and autonomous" risk-management rhetoric for 2025–26; concrete product detail thin. [MetricStream 2025 outlook](https://cxotoday.com/media-coverage/ai-powered-continuity-and-autonomy-will-shape-risk-management-in-2025-metricstream/)
- **Castellan (Onspring)**, **RSA Archer Business Resiliency**, **Continuity Logic** — long-tenured, configurable, dependency-mapping-capable; AI claims are marketing language, no agentic specifics found. [Castellan platform](https://www.gartner.com/reviews/market/business-continuity-management-program-solutions/vendor/castellan-solutions/product/castellan-platform) · [Archer Business Resiliency](https://sra.io/blog/getting-started-with-business-continuity-management-in-the-rsa-archer-grc-tool/)
- **PagerDuty** — AI Agent Suite (Oct 2025), including SRE Agent generating self-updating runbooks; incident-response-native, adjacent to but not BCM/BIA-focused. [PagerDuty AI Agent Suite](https://www.pagerduty.com/newsroom/pagerduty-expands-ai-ecosystem-to-supercharge-ai-agents/)
- **xMatters (Everbridge)** — AI Agent (Nov 2025) surfaces runbook suggestions/resolver recommendations in the incident console. [Everbridge/xMatters AI Agent](https://www.everbridge.com/newsroom/article/everbridge-introduces-ai-agent-in-xmatters-to-accelerate-digital-service-resilience/)

### AI-agent-native entrants in this exact niche

- **Fortiv** (Denmark, €3M seed, Dec 2025) — closest direct analog. Claims to automate "up to 90%" of resilience workflows; voice/text agents interview stakeholders to build BIAs and map dependencies in real time; DORA/ISO 22301-aware. Still its own SaaS system of record, not an MCP-pluggable layer atop existing tools. [Fortiv seed announcement](https://www.fortiv.io/blog/fortiv-secures-eur3m-seed-round-to-reinvent-business-continuity-with-ai)
- **RiskReady** — open-source, self-hosted, explicitly MCP-native GRC platform (9 MCP servers, 254 tools, 6-agent "AI Council," including Incident Commander / Compliance Officer / Evidence Auditor, human-approval queue before any write). Nearest architectural precedent for what Rez Ops proposes — but scoped to general GRC, not DR/BIA/tiering specifically. [RiskReady](https://riskready.eu/)
- **Comply / ComplyAI MCP Server** (April 2026) — first compliance-domain MCP server (financial services), letting compliance teams build custom agents without engineers. Validates "MCP server as compliance interface," not DR-specific. [Comply MCP launch](https://www.comply.com/resource/comply-launches-financial-services-first-agentic-compliance-platform-mcp-server-enabling-teams-to-build-custom-ai-agents-without-developers/)
- No YC-backed company found targeting DR/BCM specifically as of this research. [YC Compliance directory](https://www.ycombinator.com/companies/industry/compliance)

### Adjacent patterns worth stealing

- AI SRE agents (PagerDuty, Traversal, Cleric, NeuBird) now walk dependency graphs autonomously for root-cause analysis — validates dependency-graph-driven agentic reasoning at scale (NeuBird reportedly resolved 230k alerts autonomously in 2025). [Metoro AI SRE roundup](https://metoro.io/blog/top-ai-sre-tools) · [Traversal state of field](https://www.traversal.com/blog/ai-in-incident-response-state-of-the-field-2026-sre)
- Vanta AI Agent 2.0 / Scrut Teammates / Delve — "24/7 GRC engineer" pattern for evidence collection via MCP-compatible agents, same human-in-the-loop evidence-automation shape as Rez Ops, for SOC2/ISO27001 rather than DR. [aimultiple AI GRC roundup](https://aimultiple.com/ai-grc)

## Optional Internal Vocabulary

Evocative names for v1 capabilities, coined during brainstorming — offered as naming that a downstream skill (PRD, architecture) can adopt or discard, not as additional scope:
- **OwnerGraph** — ownership modeled as a versioned graph with commit-style history, instead of a static RACI table.
- **Antibody Ledger** — the durable memory of past incidents and the checks/tests they produced, framed as an immune system that remembers every threat it's seen.
- **Black Box Briefing** — the daily/periodic briefing doubling as an immutable flight-recorder entry, replayable later as trust/compliance evidence.
- **Risk Forecast** — probabilistic ("70% chance this control is found deficient at next audit") rather than binary pass/fail compliance status.

## Open Packaging Question

Deferred rather than resolved in this brief: is Rez Ops a personal configuration Olu runs for his own program, or does it become something installable/configurable by other DR practitioners at similarly complex organizations? The v1 scope and non-negotiables hold either way; the packaging decision mainly affects how generic the connector configuration needs to be and whether documentation/onboarding becomes a first-class deliverable. Revisit once v1 is in real use.
