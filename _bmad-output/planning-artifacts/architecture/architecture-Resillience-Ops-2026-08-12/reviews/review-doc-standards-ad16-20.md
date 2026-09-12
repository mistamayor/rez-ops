# Doc-standards review — AD-16 through AD-20 prose (structure + prose lenses)

**Date:** 2026-09-12
**Skill:** `bmad-review lenses=structure,prose` (bmad-architecture doc-standards step)
**Reader type:** humans (configured default); style guide: Microsoft Writing Style Guide (configured default). No `project-context.md` found in the repo, so no persistent facts were loaded.
**Content class:** docs. Lenses run: `structure`, then `prose` on top of its findings.
**Scope:** three prose files. `ARCHITECTURE-SPINE.md` was not touched.
**Mode:** clear edits applied directly to the files, per the caller's instruction; rows below record what was applied and what is left as a QUESTION for the author.

Constraints honoured: every AD reference, failure code, dated vendor fact, and checklist item survives (verified by grep before/after — AD set, failure-code set, and date set are unchanged in all three files). No rule softened, no architectural claim added; the two cross-reference lines added to `architecture-next.md` point at sections that already exist.

---

## Word counts

| File | Before | After | Δ |
| --- | --- | --- | --- |
| `solution-design.md` (whole file) | 8,662 | 8,566 | −96 (−1.1%) |
| └ `### Opening the next generation (AD-16 – AD-20)` section | 1,076 | 954 | −122 (−11%) |
| `docs/architecture-next.md` | 1,541 | 1,559 | +18 (two cross-reference lines) |
| `docs/provider-adapter-contract.md` | 1,687 | 1,701 | +14 |

Density note for the AD-16–20 section: the caller's comparators are the AD-11/12 section (701 words, two ADs, ~350/AD) and the AD-13/14/15 section (814 words, three ADs, ~270/AD). The AD-16–20 section now runs 954 words over five ADs plus a deferred-items paragraph, ~180/AD. It is still the longest cluster in absolute terms, but it is the densest per decision; further cuts would remove named review findings (who found what, and the fix), which the caller asked to preserve.

---

## 1. `solution-design.md` — today's additions only

**Purpose/audience read:** this document exists to help a reader of the spine understand *why* each AD looks the way it does; today's additions extend that to AD-16–20. **Structure model:** Explanation (Conceptual) — abstract to concrete, scaffolding on established foundations.

| Pass | Original Text | Revised Text | Changes |
| --- | --- | --- | --- |
| structure | §Opening the next generation, closing paragraph "What the plan asked for that the spine deliberately withheld" (~170 words) | CONDENSE to a pointer (~70 words) — **applied** | The paragraph restated, nearly verbatim, three Deferred entries added the same day ("The plan's Phase 4 and beyond", "Automating the commit and push", and the two conflicts). Deferred is the single home for those; the AD section now names the list and says the conflicts and the git gap are recorded there. Saves ~100 words; no finding lost — the `approvals` conflict, the AD-1 relay conflict, and the untracked-`ledger_data/` observation all remain in Deferred, now with the AD-12 + AD-14 citation and the "git-committed" wording moved there from the cut paragraph. |
| structure | §Reading this alongside the brief — the new "AD-16 through AD-20 map to a different source" paragraph sat *between* "None of these mappings were free" and the existing "AD-11 through AD-15 are the exception" paragraph | MOVE to after the AD-11–15 paragraph — **applied** | Chronological order: the AD-11–15 exception is introduced first, then the AD-16–20 one ("a different source *again*"). Reader no longer meets the newer exception before the older one it builds on. |
| structure | Missing blank line between the AD-13/14/15 section's last paragraph and `### Opening the next generation` | Insert blank line — **applied** | Markdown rendering: some renderers fold a heading into the preceding paragraph without it. |
| structure | §Overview, third-amendment paragraph, last sentence: "Its own section below explains why … and which of the plan's ideas were deliberately left for later phases." | "…explains why the five new decisions look the way they do; the Deferred section lists which of the plan's ideas were left for later phases." — **applied** | The section no longer carries the deferred list (see row 1), so the forward reference now points at the right place. |
| structure | §Stack rationale, "Three provider CLIs" paragraph | PRESERVE | Reads long next to its neighbours but every sentence is a distinct dated verification (Claude live, Codex from docs, Google's route change). Only the framing was trimmed (see prose rows). |
| structure | §Deferred, five new/amended entries | PRESERVE (light copy-edit only) | Each is a distinct deferral with an owning phase; no overlap among them once the AD-section duplicate was removed. |
| prose | "in the fortnight before this session, Google's Gemini CLI stopped serving individual subscriptions, … and Claude Code's headless MCP loading had regressed once earlier in the year" | "Google's Gemini CLI stopped serving individual subscriptions on 2026-06-18, this machine's Codex install turned out to be an npm wrapper with no binary behind it, and Claude Code's headless MCP loading had regressed once earlier in the year." — **applied** | The "fortnight" framing contradicted the dated fact in the same document (2026-06-18 is twelve weeks before 2026-09-12) and could not cover the third item, which the sentence itself places "earlier in the year". Dated the first item and removed the false time box; no fact changed. |
| prose | "This cluster distils … and that ratio is the first thing worth explaining. Most of the plan restates … Those were inherited silently rather than re-decided." | "…a long Deferred list. The ratio is deliberate: most of the plan restates … so those were inherited, not re-decided." — **applied** | Removed throat-clearing ("the first thing worth explaining") and the odd "inherited silently". |
| prose | "The version-currency research then forced a tightening nobody had asked for: the three real CLIs read three different MCP config formats, so 'the same `.mcp.json`' had to become …. Two hand-maintained server lists is precisely the divergence a spine exists to prevent." | "Version-currency research then tightened 'the same `.mcp.json`' into '…', because the three real CLIs read three different MCP config formats, and two hand-maintained server lists is precisely the divergence a spine exists to prevent." — **applied** | One sentence, cause before effect; drops "nobody had asked for" and "had to become". |
| prose | "The version reviewer added the detail that turned this from principle to rule" | "The version reviewer turned principle into rule" — **applied** | Shorter, same meaning. |
| prose | "Putting them in `ledger_data/` would have been the path of least resistance and would have made ledger-core the writer of state it never derives" | "Putting them in `ledger_data/` would have made ledger-core the writer of state it never derives" — **applied** | "Path of least resistance" added nothing the next clause did not. |
| prose | AD-19: "reasoning that those are where an LLM makes claims"; "That is the plan's … path, open on the tool surface the amendment had just granted. The fix stamps every write. The *mechanism* matters as much as the coverage: …"; "the same forgeable self-report AD-14 closed"; "which would put credentials on disk" | "the two places an LLM makes claims"; ": the plan's … path, open on the tool surface the amendment had just granted. The fix stamps every write, and the mechanism matters as much as the coverage: …"; "the forgeable self-report AD-14 closed"; "— values in a generated config file — puts credentials on disk" — **applied** | Joined fragments, removed emphasis italics and filler; every reviewer finding (four write tools, freeform `source`, env-whitelist, by-name forwarding, brownfield null) is intact. |
| prose | AD-20: "The plan is explicit: design the `AgentProvider` interface after inspecting the real runtimes, and do not build fake abstractions early. The spine honours that by fixing seven things every adapter must do and refusing to fix method names. Two of those clauses were reshaped by review." | "The plan says to design the `AgentProvider` interface after inspecting the real runtimes, not to build fake abstractions early, so the spine fixes seven things every adapter must do and refuses to fix method names. Review reshaped two of the seven." — **applied** | Two sentences from three; active voice. |
| prose | Stack rationale: "every claim about them in the Stack table carries a date"; "which also settled whether a March regression in headless MCP loading still applied (it did not)"; "AD-17 exists precisely so the runtime re-probes" | "in the spine's Stack table"; "which also settled that a March regression in headless MCP loading no longer applied"; "AD-17 exists so the runtime re-probes" — **applied** | The Stack table lives in the spine, not this document — the reference was ambiguous; parenthetical folded into the clause; "precisely" cut. |
| prose | `mcp` paragraph: "the deferral now has a deadline — before Phase 3 — rather than" | "the deferral now has a deadline, before Phase 3, rather than" — **applied** | Sentence already carried two em-dash asides; commas keep the last one readable. |
| prose | Deferred, "Exact `AgentProvider` signatures…": one 60-word sentence joined by a semicolon and an em dash | Split into two sentences — **applied** | Readability only. |
| prose | Deferred, "Automating the commit and push…": "recorded here rather than papered over" | "recorded here rather than hidden behind the word 'git-committed.'" — **applied** | Carried the sharper phrasing over from the paragraph condensed in row 1 so it is not lost. |
| prose | "Reading this alongside the brief": "map to a different source — … — rather than to the brief, and the traceability runs the other way"; "is now a clause of AD-1 itself, not a new AD, because it is a restatement of what" | "map to a different source again — … — and the traceability runs the other way"; "is a clause of AD-1 itself, not a new AD, because it restates what" — **applied** | "Rather than to the brief" was redundant with "a different source"; "again" links it to the AD-11–15 paragraph it now follows. |

**Structure summary for this file:** 4 structure recommendations (1 CONDENSE, 1 MOVE, 1 formatting insert, 1 forward-reference fix), 2 PRESERVE; all applied. Reduction 96 words on the whole file (−1.1%), 122 on the section (−11%). No length target was given. Comprehension trade-off: none — the condensed paragraph's content lives one section down and is now pointed at rather than repeated.

---

## 2. `docs/architecture-next.md` — whole file

**Purpose/audience read:** this document exists to help a Phase 1 implementer (human or coding agent) understand what changed in the architecture and what their story must satisfy. **Structure model:** Strategic/Context (Pyramid) — status first, then what did not change, then the five decisions, then obligations. The document already fits the model; ordering is right (unchanged → picture → decisions → amendments → ownership → done-criteria → carried conflicts → vendor facts). Nothing is mergeable within the file. The document is already lean (1,541 words, 8 sections, every AD with a one-paragraph "Why"); the edits below are small.

| Pass | Original Text | Revised Text | Changes |
| --- | --- | --- | --- |
| structure | §6 "What a Phase 1 story must check" vs `provider-adapter-contract.md` §11 "Definition of done for an adapter PR" | PRESERVE both; add one-line cross-reference from §6 to the contract §11 — **applied** | The two lists overlap (820 tests, `tests/providers/`, doctor, negative launches, git-status) but serve different readers: a story author here, an adapter PR reviewer there. Merging would force one audience to read the other's document. The pointer removes the risk of the two drifting unnoticed. |
| structure | §8 "Vendor facts" table vs `provider-adapter-contract.md` §12 runtime matrix | PRESERVE both; add one-line cross-reference from §8 to the contract §12 — **applied** | §8 is the four dated facts the *amendment rests on*; §12 is the per-flag build matrix. Different grain, same source. The pointer tells the implementer where the fuller table is. |
| structure | §7 "Conflicts carried forward" placed after §6 done-criteria | PRESERVE | Could sit after §4 (they are architecture-level), but reading order "what you must do → what is knowingly unresolved" serves an implementer better. No change. |
| prose | §1: "The plan's own phrase applies: a new door was added, not a wall removed." | "The earlier amendment's phrase still applies: a new door was added, not a wall removed." — **applied** | Misattribution: the phrase is from `solution-design.md`'s AD-11/12 overview, and `docs/product-direction.md` does not contain it (grep confirmed). |
| prose | §2: "The Ledger never knows or cares which mode is talking to it, except that from Phase 3 every record it writes says who wrote it." | "The Ledger does not care which mode is talking to it; from Phase 3 it stamps every record it writes with who wrote it." — **applied** | "Never knows … except that … says who" contradicted itself for the reader; the ledger does know from Phase 3 — that is AD-19. |
| prose | §3 AD-17 Why: "in the two weeks before this amendment, one vendor CLI stopped serving individual subscriptions, this machine's Codex install had a missing binary behind a present npm wrapper, and Claude Code's headless MCP loading had regressed once earlier in the year." | "this year alone, Gemini CLI stopped serving individual subscriptions (2026-06-18), this machine's Codex install turned out to be an npm wrapper with no binary behind it, and Claude Code's headless MCP loading regressed once (2.1.77)." — **applied** | Same defect as in `solution-design.md`: "two weeks" contradicted §8's own 2026-06-18 date and could not cover the third item. Named the vendor (§8 already does) and added the version §8 already carries. No new facts. |
| prose | §8 closing: "Re-probe at every run. That is the whole point of AD-17." | "Re-probe at every run; that is what AD-17 is for." — **applied** | "The whole point" is filler emphasis. |

**Structure summary for this file:** 2 cross-reference additions, 1 PRESERVE; +18 words. No cuts recommended — every section justifies itself for the implementer audience. No length target given. No comprehension trade-offs.

---

## 3. `docs/provider-adapter-contract.md` — whole file

**Purpose/audience read:** this document exists to help an adapter author or PR reviewer check an `agents/providers/<name>/` package against AD-16–20, item by item. **Structure model:** Reference/Database — random access by section, consistent schema (heading → AD citation → checkbox items). The document fits the model well: every section 1–10 cites its AD, every item is a checkable rule, §11 is the roll-up, §12 the facts table. Order follows an adapter's lifecycle (auth → isolation → probe → launch → scope → provenance → events → failure → fake → selection). Nothing is mergeable; nothing belongs in `architecture-next.md` instead (the "why" is deliberately absent here and present there).

| Pass | Original Text | Revised Text | Changes |
| --- | --- | --- | --- |
| structure | §11 "Definition of done" repeats items from §1, §2, §5, §6, §9 (the four negative launches, the grep, the git-status check) | PRESERVE | A DoD roll-up is reinforcement, not redundancy: a reviewer works from §11 and drills into §1–10. Cutting it would make the reviewer reconstruct it. |
| structure | §10 "Selection" sits last among the rule sections although selection logically precedes launching | QUESTION — left in place | Only two items, both saying "the adapter does not do this". Moving it before §4 would put a non-obligation among obligations; keeping it last reads as an appendix. Author's call; no change made. |
| structure | §12 runtime matrix vs `architecture-next.md` §8 | PRESERVE (see file 2, row 2) | This is the fuller table and the right home for it. |
| prose | §0: "One Python package … that knows how to launch, drive, observe, and stop **one** vendor's official local agent runtime in Driven mode, and to report honestly what that runtime can do right now." | "One Python package … that launches, drives, observes, and stops **one** vendor's official local agent runtime in Driven mode, and reports honestly what that runtime can do right now." — **applied** | "Knows how to … and to report" was ungrammatical after the parallel; direct verbs. |
| prose | §8: "The enum is a closed set in code; the ellipses in the spine are elision." | "The enum is a closed set in code; where the spine writes an ellipsis it is abbreviating, not licensing new codes." — **applied** | "Are elision" is opaque to an adapter author who has not read the spine's wording; the spine's own sentence ("elision, not an open-ended license") is restated plainly. Rule unchanged. |
| prose | §9: "Anything it writes carries `provider: fake`. That is the point." | "Anything it writes carries `provider: fake`; the stamp is how a fake session is told apart from a real one." — **applied** | "That is the point" asserted significance without saying what it was. The replacement states the reason the spine gives (AD-20 §6, "which is how `provider: fake` stamps arise"). |
| prose | §11: "Nothing changed under `ledger_core/`, `connectors/`, `shared/` (Phase 1)." | "… (a Phase 1 constraint)." — **applied** | Bare "(Phase 1)" read as a tag rather than a scope qualifier. |
| prose | §12 row "Subscription auth — Claude login" is vaguer than its Codex and Antigravity neighbours | Consider: name the command or mechanism (e.g. the interactive `claude` login) if the author has it? | Left as-is: filling it would add a vendor fact the review did not verify. |

**Structure summary for this file:** 0 cuts, 2 PRESERVE, 1 QUESTION; +14 words from the two clarified sentences. No length target given. No comprehension trade-offs.

---

## Cross-file observations

- **Overlap between lenses:** the "two weeks / fortnight" defect surfaced under prose in both `solution-design.md` and `architecture-next.md`; it is the same sentence transcribed twice. Fixed consistently in both. This is the one edit in the set that touches wording of a fact rather than pure expression — it was made because the framing contradicted a dated fact in the same file, and it is flagged here so the author can reject it if the "two weeks" referred to something the documents do not record (e.g. when the change was *discovered* rather than when it happened).
- **`architecture-next.md` ↔ `provider-adapter-contract.md`:** the two docs are correctly partitioned (why vs. what-to-check) and now cross-reference each other at the two points where a reader would otherwise wonder which list is authoritative.
- **Not touched:** `ARCHITECTURE-SPINE.md`, `walkthrough-deck.html`, `.memlog.md`, and the pre-existing sections of `solution-design.md`.
