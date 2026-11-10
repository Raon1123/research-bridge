---
title: "The test suite overwrote the real ~/.claude.json — postmortem"
type: postmortem
created: 2026-11-10
period: 2026-11-10 16:26 – 2026-11-10 21:00 (+0900)
status: draft, unaudited
tags: [postmortem, research-bridge]
---

# The test suite overwrote the real ~/.claude.json — postmortem (2026-11-10 16:26 – 21:00 +0900)

This document covers one defect in the tests added by the review and simplification work of 2026-11-10 (merged as pull requests 48 and 49). It records what went wrong, how it surfaced, what was fixed and whether the fix was confirmed. It does not assign blame. The user's file is not restored by this change; see Open items. The fix was merged as pull request 50.

## How this was made

1. Sources: `tests/test_doctor.py`, `tests/conftest.py`, `tests/hubfake.py` at commit `d3db45a`; `git log -S'monkeypatch.undo()' -- tests/test_doctor.py`; the files `~/.claude.json`, `~/.claude.json.bak.20261106205323` and `~/.claude/backups/.claude.json.backup.*` on the hub, read for key names, counts and the one `research-bridge` entry only.
2. Who read what: the coordinating session (main thread) read all of it.
3. Audit: none yet.
4. Gaps in the record: the number of suite runs between 16:26 and 20:48 was not counted; Claude Code keeps five backups, so only the last five overwrites are on disk.

Abbreviations used: MCP (Model Context Protocol).

## 1. Summary

| ID | Severity | What happened | Fix verified |
|---|---|---|---|
| PM-01 | S0 | Every run of the test suite replaced the real `~/.claude.json` of the account that ran it | recorded |
| PM-02 | S3 | A warning that showed the damage was read as an expected difference | recorded |

## 2. Items

### PM-01 — every run of the suite replaced the real `~/.claude.json`

- Severity: S0 (an unauthorized write to a file that `AGENTS.md` lists under "Ask the user before").
- When: introduced by commit `d4f54cc` (2026-11-10 16:26 +0900); on `main` from the merge of pull request 48 (`c503667`); last overwrite by a run at 20:47; found at about 20:55; fixed in the change that adds this document.
- What happened: `test_config_check_runs_offline_part` called `monkeypatch.undo()` in the middle of the test and then set the fake hub up again. The undo also removed the isolation that `tests/conftest.py` applies to every test (`HOME` set to a temporary directory, `configure.claude_json_path` patched). `hubfake.install` does not set `HOME`, so the helper `_complete` wrote its fixture file through `configure.claude_json_path()` to the real `~/.claude.json`. The file became 485 bytes holding one `mcpServers` entry that points into the pytest temporary directory. Claude Code sessions that were running then wrote parts of their state back. At discovery the file had 8 top-level keys; a copy from 2026-11-06 has 86, including 15 project entries and the account keys. The user-scope `research-bridge` MCP entry pointed at a temporary path. No other real file was written: `~/.ssh/config`, `~/.ssh/known_hosts`, the key directory, the systemd user directory and the hub data root keep modification dates of 2026-11-06 or earlier.
- Cause (recorded): `tests/test_doctor.py` line 500 at `d3db45a`; `tests/hubfake.py` sets `RB_HOST_ROOT` and `configure.REPO` but not `HOME`.
- How it surfaced: the coordinating session read the MCP registration to list the user's remaining steps and found the temporary path in it.
- Fix: the test uses `monkeypatch.context()` for the one patch it needs to drop; `tests/conftest.py` sets `HOME` and `XDG_RUNTIME_DIR` to a session directory and removes `SSH_AUTH_SOCK`, `RB_HOST_ROOT`, `RB_HOST_CONFIG`, `XDG_CONFIG_HOME` and `XDG_DATA_HOME` when it is imported, so an undo falls back to those values; `test_real_home_is_out_of_reach_even_after_undo` pins it.
- Fix verified: recorded — the new test fails with the old `conftest.py` (1 failed) and passes with the new one; after a full run (919 passed) the `research-bridge` entry of the real file still named the directory of the last run before the fix. Re-checked 2026-11-10 by a second session before pushing: 919 passed in the worktree; key count, registered directory and entry hash of `~/.claude.json` the same before and after, and no new small file under `~/.claude/backups/`.
- Prevention: rule 1 below; the session-wide isolation; the new test.
- Evidence: `tests/test_doctor.py` at `d3db45a` 「monkeypatch.undo()」; `~/.claude/backups/` holds five files `.claude.json.backup.*` of 485 to 717 bytes written between 20:40 and 20:48, each with a `research-bridge` entry under `/tmp/pytest-of-<user>/pytest-<N>/test_config_check_runs_offline0/checkout`.

### PM-02 — the warning that showed the damage was misread

- Severity: S3.
- When: 2026-11-10, about 20:15, `rb doctor --offline` run by the coordinating session from the work worktree.
- What happened: the output had `warn mcp_entry  MCP entry differs from the one rb setup prints`. The session took this for the known difference between the main checkout and a worktree and passed it to the user as a step to re-register the entry. The registered entry was already the test's temporary path.
- Cause (inferred): from the session's own report to the user, which named re-registration and not a damaged file.
- How it surfaced: with PM-01.
- Fix: `mcp_entry` printed the entry it expects, not the one it found. Its warning now ends with `registered: <directory>` (the `--directory` of the registered entry, else its command) and, for a difference, `differs in: ...` (`command`, `args`, `env <KEY>`); `configure.registered_where` and `configure.entry_differences`.
- Fix verified: recorded — `test_offline_mcp_entry_problems` asserts the registered directory and the differing part for a missing path, a worktree, a missing `RB_HOST_CONFIG` and a stray directory like the pytest path of PM-01.
- Prevention: rule 2 below.
- Evidence: session transcript of 2026-11-10, the `rb doctor --offline` output.

## 3. Deviations from user instructions

### DEV-1 — `~/.claude.json` was changed without asking

- Instruction: `AGENTS.md`, "Ask the user before: editing `~/.ssh/config`, `~/.ssh/authorized_keys` on any host, or `~/.claude.json`".
- What was done instead: the suite, run many times by subagents and by the coordinating session, overwrote the file (PM-01).
- Reason (recorded): a test defect; no session intended the write.
- When the user was told: 2026-11-10, in the report that accompanies this change.
- Evidence: PM-01.

## 4. Prevention rules

- Tests do not call `monkeypatch.undo()`. A patch that must end inside a test goes in `with monkeypatch.context() as m:`. (PM-01; copied to `AGENTS.md` Conventions.)
- A warning from `rb doctor` is explained from what it found, not from what was expected: read the value it complains about before reporting the step. (PM-02)

## 5. Open items

- 2026-11-10, later: on the hub the file is whole again (87 top-level keys, the `research-bridge` entry names the main checkout); how and from which copy it was restored is not recorded (the user does not know). The steps for a damaged file stay: restoring `~/.claude.json` is the user's step, with every Claude session on the hub closed (a running session writes its own state back): keep the damaged file, copy `~/.claude.json.bak.20261106205323` over it, start Claude, and register the MCP server again with the command `rb setup --node node1` prints. Project entries and settings added after 2026-11-06 are not in that copy.
- Other accounts or machines that ran the suite between `c503667` and this fix have the same damage in their own `~/.claude.json`. The user said this may have happened (node1 included); the check is in `docs/HANDOFF.md` §Test suite and `~/.claude.json`.
