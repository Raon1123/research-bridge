---
title: "One SSH error message for two causes during the hub key-agent setup — postmortem"
type: postmortem
created: 2026-11-10
period: 2026-11-06 – 2026-11-10
status: draft, unaudited
tags: [postmortem, research-bridge]
---

# One SSH error message for two causes during the hub key-agent setup — postmortem (2026-11-06 – 2026-11-10)

This document covers one defect that surfaced on 2026-11-06 while the bridge keys were loaded into an SSH agent on the Linux hub, and its fix on branch `claude/review-optimize-2026-11-10` (2026-11-10). It records what went wrong, how it surfaced, what was fixed and whether the fix was confirmed. It does not assign blame. Problems still open are in `docs/issues/2026-11-10-triage.md`.

Trigger (`docs/postmortems/README.md`, "When to write one"): a defect found after a task was marked complete. The message came from the first build (commit `d99f703`, 2026-10-27) and was found in use on 2026-11-06.

## How this was made

1. Sources: `rb_host/client.py` at `0b16b47` (`main` at the merge of PR 45) and at the tip of this branch; the body of PR 44 (`scripts/hub-agent.sh`, merge commit `b1b553f`); `git log` of `rb_host/client.py`.
2. Who read what: the session that wrote the 2026-11-10 state page and triage read all sources itself.
3. Audit: none yet.
4. Gaps in the record: the date 2026-11-06 comes from the brief of the 2026-11-10 review, not from a tracked file (PR 44 was merged on 2026-11-10). The session transcript of that day was not read; the number of setup rounds and the exact error lines are not in the repository, only PR 44's summary.

Abbreviations used: SSH = Secure Shell; MCP = Model Context Protocol (the tool interface Claude sessions use).

## 1. Summary

| ID | Severity | What happened | Fix verified |
|---|---|---|---|
| PM-01 | S2 | Every `Permission denied (publickey` failure was reported as `ssh key unavailable (agent locked?)`, including the case where the node refuses a loaded key. | recorded (unit tests); not verified on the real link |

## 2. Items

### PM-01 — One message for "no key in the agent" and "the node refused the key"

- Severity: S2 (wrong output).
- When: introduced in `d99f703` (2026-10-27, "feat(host): client, ledger, store"); surfaced 2026-11-06 during the hub agent setup; fixed in `d3f8de5` on branch `claude/review-optimize-2026-11-10` (2026-11-10, not merged).
- What happened: `NodeClient` mapped any exit status 255 whose stderr contained `Permission denied (publickey` to `AgentLockedError("ssh key unavailable (agent locked?)")`. The same text appeared when the agent was missing, when the key was not loaded, and when the node refused a loaded key (for example a `from=` address that does not match the hub). The message pointed the user at the agent in every case.
- Cause (inferred, from the code at `0b16b47`): the client looked only at the exit status and one stderr substring; it did not ask the agent which keys it held, so it could not tell the cases apart.
- How it surfaced: user setup on the Linux hub; recorded afterwards in PR 44, whose manual change notes that the message "is also returned when the node refuses the key (for example a `from=` mismatch)".
- Fix: `rb_host/client.py` classifies SSH failures into ten codes (`no_agent`, `agent_empty`, `key_not_loaded`, `node_refused_key`, `host_key_unknown`, `host_key_changed`, `unknown_alias`, `unreachable`, `timeout`, `closed`), each with a next command (`TransportError.code`, `.hint`); for a key refusal it checks whether the agent holds the alias's key. `AgentLockedError` stays a subclass for the three agent codes.
- Fix verified: recorded for unit tests: `tests/test_client_errors.py` (for example `test_publickey_key_loaded_is_node_refused`, `test_publickey_key_not_loaded`), part of 760 passed on 2026-11-10. Not verified on the real link: the hub and the node do not run this code yet.
- Prevention: an error message names one cause only when the code has checked that cause; otherwise it lists the possible causes. A test per cause pins the message.
- Evidence: `rb_host/client.py` at `0b16b47`, line 107 「return AgentLockedError("ssh key unavailable (agent locked?)")」; PR 44 body 「`ssh key unavailable (agent locked?)` is also returned when the node refuses the key (for example a `from=` mismatch)」.
- Afterwards (2026-11-11): merged to `main` in PR 48 (merge commit `c503667`); the hub has run it since 2026-11-10, and `rb doctor --node node1` passed (`docs/provisioning.md` B2 row 6). No SSH failure occurred in that run, so the error classification is still verified by unit tests only. The open item "Live confirmation" below stays open, for a real failure case.

## 3. Deviations from user instructions

None recorded.

## 4. Prevention rules

- An error message names a single cause only after the code has checked it; otherwise it lists the candidates and the command that tells them apart. (PM-01)

## 5. Open items

- The MCP results carry the code and the hint inside one error string; a separate `code` field is proposed as N-06 in `docs/issues/2026-11-10-triage.md`.
- Live confirmation on the real link: part of the security checks in `docs/provisioning.md` (row 6, `rb doctor --node node1`).
