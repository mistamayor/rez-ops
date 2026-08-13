# Smoke Detector, Not Fire Inspector

**An AI agent that keeps your DR program continuously true — checking all the time, quietly, instead of showing up once a year with a clipboard.**

## The Problem

DR programs are reactive because nobody checks the real state of things until an audit is looming or an incident just happened — compiling BIAs, test results, and ownership from scattered, manual sources is too slow to do any other way. The deeper issue: DR artifacts were built as one-time deliverables, not living data that gets continuously revalidated, so nothing owns staleness as a first-class concept. And the most fragile thread running through all of it is ownership — RACI docs rot the moment someone changes teams or leaves, so the one thing you need most in a real incident (who do I actually ping right now) is also the thing most likely to be quietly wrong.

## The Idea

An agent that plugs into the systems you already use — git, calendars, ticketing, CMDB — read-only to start, and builds a living, queryable model of your DR program's real state, with every artifact carrying an explicit freshness/expiry rule instead of a vibe. The real product isn't a daily email; it's the state model itself, queryable in chat any time ("what's stale, what's due, what needs me"), with the daily digest as just one view on top of it. The wedge is ownership: the agent infers who's really responsible from activity (commits, tickets, on-call), flags orphaned ownership before it becomes a crisis, and drafts (never sends) the "are you still the owner of X" message for you to approve. None of it counts unless every claim is backed by a clickable source and a human-signed approval trail, and none of it should make you worse off if it breaks — that trust layer isn't a nice-to-have, it's the entry ticket.

## What This Looks Like Day to Day

- **One thing to decide, not ten to read** — a short daily brief: what changed, what's now at risk, who to ping, with the message already drafted so all you do is hit approve.
- **A coverage map, not false confidence** — a heatmap by tier x domain showing what the agent has actually verified vs. what's still manual or unknown, so blind spots are visible instead of hidden.
- **Orphan-risk, caught early** — the moment someone leaves or a team reshuffles, the agent cross-checks it against your RACI and flags the gap that day, not the day an incident needs that person.
- **Every briefing is a receipt** — timestamped and durable, so you can replay exactly what the agent knew and said on any given day; compliance evidence becomes a byproduct instead of a scramble through emails.
- **If it goes dark, you're not worse off** — every connector is read-only and the underlying systems of record still exist, so a bad day for the agent just means you're back to today's manual baseline, not a broken one.

## Why Now

DR data already lives everywhere it needs to — git, CMDBs, calendars, ticketing — it's just never been stitched together and kept fresh. The agent doesn't ask anyone to adopt a new system of record; it just finally gives the one they already have a pulse, checking continuously instead of once a year.
