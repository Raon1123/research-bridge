---
title: "First live run over the real link (B2 and B3) — postmortem"
type: postmortem
created: 2026-11-10
period: 2026-11-10 21:50 – 2026-11-10 23:10 +0900
status: draft, unaudited
tags: [postmortem, research-bridge]
---

# First live run over the real link (B2 and B3) — postmortem (2026-11-10 21:50 – 23:10 +0900)

This document covers the security checks (B2) and the first live run (B3) of `docs/provisioning.md` on 2026-11-10, from the hub's move to `main` to the job queued after `rb approve`. It records what went wrong, how it surfaced, what was fixed and whether the fix was confirmed. It does not assign blame. Problems still open are in `docs/issues/2026-11-10-triage.md`.

## How this was made

1. Sources: the hub session `013fd97b-6c7a-41dc-8548-900b149809c2` (MCP results, `rb doctor` output pasted by the user, `b2-hub.sh` and `b2-node.sh` results reported by the user), the hub ledger and `sync/node1.json` (fields only), PRs 50 to 53.
2. Who read what: the coordinating session (main thread) read all of it.
3. Audit: none yet.
4. Gaps in the record: the user ran rows 1 to 8 of B2 and rows 4, 6, 8 and 9 of B3; their outputs are recorded as reported ("all pass", "passed", "visible"), not as full text. Row 4 of B2 (the shared key) is recorded by the user, not here.

Abbreviations used: B2, B3 (the security checks and the first live run of `docs/provisioning.md`); MCP (Model Context Protocol, the tool interface of Claude sessions).

## 1. Summary

| ID | Severity | What happened | Fix verified |
|---|---|---|---|
| PM-01 | S0 | `queue_status` returned withheld job names to the hub | recorded (separate postmortem) |
| PM-02 | S3 | B3 row 3 named a document id that does not exist in the project | n/a |
| PM-03 | S2 | The node's install record stayed at 0.1.0 after an update to 0.2.0 | recorded (test) |
| PM-04 | S3 | The handoff's node steps omitted switching the node checkout to `main` | n/a |

## 2. Items

### PM-01 — `queue_status` returned withheld job names to the hub

- Severity: S0.
- Everything about it is in `docs/postmortems/2026-11-10-queue-status-withheld.md` (fixed in PR 53, confirmed on the real link: 116 names returned as `(withheld)`). The run stopped before B3 row 5 and continued from row 4 after the fix was installed on both sides.

### PM-02 — B3 row 3 named `H-001`, which the project does not have

- Severity: S3.
- When: written with the provisioning table; surfaced 2026-11-10 at B3 row 3.
- What happened: `read_doc("node1", "H-001")` returned `not_found`; `EXP-001` returned the document with 13 lines blanked.
- Cause (recorded): the row's example id was a placeholder, and `docs/projects/trm.md` lists identifier forms, not identifiers.
- How it surfaced: live check.
- Fix: row 3 now asks for an id that exists on the node and names `EXP-001` for `trm`.
- Fix verified: n/a (documentation).
- Prevention: example values in check tables are facts of the project sheet or marked as placeholders.
- Evidence: MCP result 「{"error": "not_found"}」.

### PM-03 — the install record stayed at 0.1.0 after the node was updated to 0.2.0

- Severity: S2.
- When: the node update before B2 (2026-11-10, about 22:00); `rb-node doctor` warned `installed record 0.1.0 differs from running code 0.2.0`; a second run of `scripts/node-install.sh` cleared it.
- What happened: the installed code was 0.2.0 (the hub's `hello` reported it) but `~/.research-bridge/install.json` still said 0.1.0.
- Cause (inferred, from the script and the order of steps; the node's terminal output was not kept): `--update` runs `git pull` from inside `scripts/node-install.sh`. The pull replaced the file that `sh` was still reading; `sh` reads a script as it runs, so the rest of that run executed parts of the new file from the old file's byte offset, and the step that writes the install record did not run as written. The same hazard was still in the script on `main`.
- How it surfaced: `rb-node doctor`, pasted by the user.
- Fix: when the pull moves `HEAD`, the script starts the updated `scripts/node-install.sh` with the same options minus `--update` (`exec`, from inside the `if` block, which `sh` parses whole before running it).
- Fix verified: recorded — `tests/test_node_install.py::test_script_update_runs_the_pulled_script` (a checkout whose upstream has a newer script) fails on the old script and passes on the new one, and the install record names the pulled commit.
- Prevention: the test above; a script that updates its own checkout re-executes itself.
- Evidence: `rb-node doctor` 「[warn] install: installed record 0.1.0 differs from running code 0.2.0」.

### PM-04 — the handoff's node steps did not switch the node checkout to `main`

- Severity: S3.
- When: `docs/HANDOFF.md` after PR 51; noticed before the node update.
- What happened: the node checkout was on `claude/node-allowed-gpus`, fully contained in `main`. `git pull --ff-only` on that branch changes nothing, so the old script would have run without `--withheld-file`. The session gave the user `git switch main` first; the user's update worked.
- Cause (recorded): the handoff was written from the install record, which named the branch, without turning that into a step.
- Fix: the handoff's node steps now assume a checkout on `main` and say so.
- Fix verified: n/a (documentation).
- Prevention: a node step that pulls names the branch it expects (`git status -sb` first).

## 3. Deviations from user instructions

None recorded. Merging PRs 52 and 53 from the session was refused by the session's permission check; the user merged them on GitHub.

## 4. Prevention rules

- Example values in check tables are facts of the project sheet or are marked as placeholders. (PM-02)
- A script that updates its own checkout re-executes itself after the pull moves `HEAD`; a test pins it. (PM-03)
- A node step that pulls names the branch it expects (`git status -sb` first). (PM-04)

## 5. Open items

- B3 row 7: the `job_finished` event of job `75b0b3a9df614fc4becb47f0c079b7a9`, after the research queue reaches it.
