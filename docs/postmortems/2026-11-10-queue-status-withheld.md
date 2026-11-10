---
title: "queue_status sent withheld job names to the hub — postmortem"
type: postmortem
created: 2026-11-10
period: 2026-11-10 22:13 – 2026-11-10 22:40 +0900
status: draft, unaudited
tags: [postmortem, research-bridge]
---

# queue_status sent withheld job names to the hub — postmortem (2026-11-10 22:13 – 22:40 +0900)

This document covers one defect found during the first live run (`docs/provisioning.md` B3) on 2026-11-10, after every B2 row had held. It records what went wrong, how it surfaced, what was fixed and whether the fix was confirmed. It does not assign blame. Problems still open are in `docs/issues/2026-11-10-triage.md`.

## How this was made

1. Sources: the MCP `queue_status` result in the hub session `013fd97b-6c7a-41dc-8548-900b149809c2` (read for counts only); `rb_node/remote.py` and `rb_host/server.py` at `origin/main` `a469d9e`; `git log -S'def queue_status' -- rb_node/remote.py`; a pattern search of the hub data root (file names only).
2. Who read what: the coordinating session (main thread) read all of it.
3. Audit: none yet.
4. Gaps in the record: the count below is by the five fallback patterns of `AGENTS.md` hard rule 3 only; how many more names the four project patterns would hide was not measured.

Abbreviations used: MCP (Model Context Protocol, the tool interface of Claude sessions); B2, B3 (the security checks and the first live run of `docs/provisioning.md`).

## 1. Summary

| ID | Severity | What happened | Fix verified |
|---|---|---|---|
| PM-01 | S0 | `queue_status` returned queue file names that match withheld patterns, unmasked, to the hub | recorded (tests); node not yet updated |

## 2. Items

### PM-01 — `queue_status` returned withheld job names to the hub

- Severity: S0 (withheld content left the node: hard rule 3).
- When: introduced with the first node server, commit `4f7a1c7` (2026-10-27, `feat(node): serve-remote`); first exercised from the hub at 2026-11-10 22:13 +0900 (B3, before `submit_job`); found in the same minute.
- What happened: the node op `queue_status` lists up to 200 file names per queue state and returned them as they are. Queue file names carry run names. Of the entries returned, at least 95 matched the five fallback patterns; none was masked. The hub tool `queue_status` passed the result through without its own check. Every other node op that returns names or text checks them (`poll`, attachments, `read_doc`, `get_file`, `git_status`); `queue_status` and the hub tool were the only ones without a check.
- Where the names went: the MCP result of one hub Claude session, so the session's transcript (`~/.claude/projects/<project>/013fd97b-….jsonl` on the hub) and the model conversation. No file under the hub data root holds them (pattern search of the data root, 2026-11-10 22:20: no hit outside `withheld_patterns.json`); `rb board` reduces queue results to counts per state and audits only size and hash; `rb sync` stores the same counts. No report, commit or log written by the session names them.
- Cause (inferred, from the code): the withheld rule was applied to documents, files and message bodies, and file names in the queue directory were not treated as content. The 2026-11-03 whole-branch review and the 2026-11-10 node-local checks did not list `queue_status` among the egress points.
- How it surfaced: the session read the `queue_status` result before `submit_job` (B3 row 5) and saw fallback-pattern names in it.
- Fix: node `queue_status` replaces a name that hits a withheld pattern with `(withheld)` (state and modification time kept) and returns `withheld_entries`; the hub tool `queue_status` checks every name again with the hub's patterns, so a node that has not been updated is covered; the hub tool `read_doc` also blanks lines again with the hub's patterns (`hub_withheld_lines`), as `poll` already does.
- Fix verified: recorded — `tests/test_remote.py::test_queue_and_gpu_status` (node) and `tests/test_host_tools.py::test_queue_names_and_doc_text_checked_again_on_hub` (hub, with a node result that carries unchecked names) fail on the code before the fix (2 failed) and pass after; full suite 920 passed (Linux hub, Python 3.12). Not yet verified on the real node: the node runs the code before the fix until it is reinstalled; the hub check covers it in the meantime once the hub's MCP server runs the fixed code.
- Prevention: every node op that returns names or text passes through the withheld check on the node and again on the hub; a new op names its check in its review. The tests above pin both checks for `queue_status`.
- Evidence: `rb_node/remote.py` at `a469d9e`, `queue_status` 「entries.append({"name": name, "mtime": mtime, "state": state})」.

## 3. Deviations from user instructions

None. The B3 run was stopped at row 5; `submit_job` was not called.

## 4. Open items

- The session transcript above holds the names; whether to delete or keep it is the user's call.
- Reinstall the node from `main` after the fix is merged (`scripts/node-install.sh --update` on the node console), then restart the hub's Claude sessions so the MCP server runs the fixed hub check.
- B3 continues from row 4 (`rb sync`) after that.
