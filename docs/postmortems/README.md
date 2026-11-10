# Postmortems

A postmortem records what went wrong, under what conditions, how it surfaced, what was fixed, and whether the fix was confirmed. It does not assign blame. Open problems that are not yet fixed go to a GitHub issue or, until one exists, to the triage file `docs/issues/2026-11-10-triage.md`; a postmortem item may point to them.

Copy [TEMPLATE.md](TEMPLATE.md) to `docs/postmortems/YYYY-MM-DD-<slug>.md`. The date is the start of the period covered.

## When to write one

- After the Task 13 live run (B3), whatever its outcome.
- After the final whole-branch review, covering the defects it found.
- Whenever a B2 security check in `docs/provisioning.md` does not hold.
- Whenever a defect is found after a task was marked complete, or a reviewer finds a defect that the implementer's tests passed.
- Whenever an anti-goal of the design (severity S0 below) occurs, immediately, before any other write-up.

## Severity

The scale comes from the anti-goals in the research-bridge design §4.

| Level | Meaning |
|---|---|
| S0 | An anti-goal occurred: an unauthorized read or write, withheld content left the node, a key opened a shell, a path escaped a root, a job ran twice or without approval, agent text reached a manuscript. |
| S1 | A defect that would have let an anti-goal occur, found before it did. |
| S2 | Wrong behaviour not tied to an anti-goal: protocol, concurrency, wrong output, broken command. |
| S3 | Procedure or documentation: wrong instructions, stale reports, mis-stated facts. |

## Item rules

- IDs are `PM-01`, `PM-02`, … per document. Deviations from user instructions are `DEV-1`, `DEV-2`, … in their own section.
- Tag every cause as **recorded** (a ledger line, report, commit message or transcript says so; cite it) or **inferred** (reasoned back from the fix; say from what).
- "Fix verified" takes one of: `recorded` (a test run or live check is in the record), `unclear` (a fix exists but no check is recorded), `not verified`, `n/a`.
- Evidence is a short quote with its source (file and line, commit, or timestamp). Quote only; do not paraphrase into the quote.
- If a separate-context audit reads the document, add its findings to each item as an `Audit:` line and the corrected sentence as `Audit correction:`; do not silently rewrite the item. Later changes go in an `Afterwards:` line with a date.

## Content rules

- No withheld content, no experiment results, no verdict prose (`AGENTS.md` hard rule 3 and Conventions). If such content entered a session, record only that it did, and where; never what it was.
- No message bodies and no secrets (hard rule 6).
- Placeholders only for server facts (`<NODE_HOST>`, `<NODE_USER>`, `<LAPTOP_ETH_SUBNET>`, `<SHARED_KEY>`). Real addresses go in the gitignored `private/` directory.

## Index

| Date | Document | Status |
|---|---|---|
| 2026-10-27 | [First build (Tasks 0–13 Step 1)](2026-10-27-sdd-build.md) | draft, unaudited |
| 2026-11-03 | [Final whole-branch review (issue 10)](2026-11-03-whole-branch-review.md) | draft, unaudited |
| 2026-11-06 | [One SSH error message for two causes (hub key-agent setup)](2026-11-06-hub-key-agent-setup.md) | draft, unaudited |
| 2026-11-10 | [Node-local review and checks on node1](2026-11-10-node-local-checks.md) | draft, unaudited |
| 2026-11-10 | [The test suite overwrote the real ~/.claude.json](2026-11-10-test-suite-overwrote-claude-json.md) | draft, unaudited |

The format follows the vault postmortem `90_Claude/60_Tools/session-calendar/POSTMORTEM-20261004.md` (fields and audit lines), adapted to this project's severity scale.
