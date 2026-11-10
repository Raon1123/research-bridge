---
title: "<title> — postmortem"
type: postmortem
created: YYYY-MM-DD
period: YYYY-MM-DD HH:MM – YYYY-MM-DD HH:MM
status: draft, unaudited
tags: [postmortem, research-bridge]
---

# <title> — postmortem (<period>)

<!--
Copy to docs/postmortems/YYYY-MM-DD-<slug>.md. Rules: docs/postmortems/README.md.
No withheld content, no experiment results, no message bodies, no secrets, placeholders only for server facts (<NODE_HOST>, <NODE_USER>, <HUB_ADDR>, <HUB_SUBNET>).
-->

This document covers <what work, which commits or sessions>. It records what went wrong, how it surfaced, what was fixed and whether the fix was confirmed. It does not assign blame. Problems still open are in `docs/issues/2026-11-10-triage.md`.

## How this was made

1. Sources: <ledger, task reports, commits `<a>..<b>`, session transcripts with ids>.
2. Who read what: <main thread / agents and their models>.
3. Audit: <none yet | separate-context audit by <model> on <date>, counts by verdict>.
4. Gaps in the record: <periods or outputs not in the sources>.

Abbreviations used: <spell out each one at first use, or link its source>.

## 1. Summary

| ID | Severity | What happened | Fix verified |
|---|---|---|---|
| PM-01 | S? | | recorded / unclear / not verified / n/a |

## 2. Items

### PM-01 — <one-line statement of what happened>

- Severity: S?
- When: <task, commit, or timestamp of introduction, discovery, fix>
- What happened: <facts only; numbers with where they were measured>
- Cause (recorded | inferred): <cause; for recorded, cite the source; for inferred, say what it was inferred from>
- How it surfaced: <test, reviewer, live check, user report>
- Fix: <change, commit>
- Fix verified: recorded / unclear / not verified / n/a — <the check and its result>
- Prevention: <a rule or a test that would catch it next time>
- Evidence: <source> 「<short quote>」

<!-- Optional, added later:
- Audit (<verdict>): <finding>
- Audit correction: <corrected sentence>
- Afterwards (YYYY-MM-DD): <what changed later>
-->

## 3. Deviations from user instructions

### DEV-1 — <one-line statement>

- Instruction: <date, the user's words>
- What was done instead:
- Reason (recorded | inferred):
- When the user was told:
- Evidence:

<!-- Write "None recorded." if there are none. -->

## 4. Prevention rules

- <Rule.> (PM-NN)

<!-- One line per rule, each pointing to the items it comes from. Rules that belong in AGENTS.md hard rules or
     Conventions are copied there in the same change. -->

## 5. Open items

- <Item, and where it is tracked (`docs/issues/2026-11-10-triage.md` or a design candidate).>
