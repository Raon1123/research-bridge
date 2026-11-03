# research-bridge handoff — 2026-11-02

Read `AGENTS.md` first (rules, layout, test commands).

## Resume snippet

> research-bridge (`D:/raw/Codes/research-bridge`, branch `main` at `f9503cf`) is built through Task 12 and the Task 13 documents. All code is written and reviewed. Nothing has been installed on node1 and no SSH key or config has been created. Continue with Task 13: the user decides items 2–4 below, creates the keys and SSH entries (A1–A3 in `docs/provisioning.md`), creates `.venv` in this directory, and the session then runs the install (B1), the four security checks (B2) and the live run (B3), and records results (Step 8). The laptop subnet for `from=` is decided: `<LAPTOP_ETH_SUBNET>`.

## State

| Area | Status |
|---|---|
| Node: protocol, paths, withheld filter, mailbox, serve-remote, jobs, serve-local + responder, harness | Done (Tasks 1–7, 10). `rb_node/` |
| Host: client, ledger, store, MCP server, `rb` CLI, harness | Done (Tasks 8–10). `rb_host/` |
| 8765 approval endpoint (vault dashboard) | Done and live (Task 11). Files in `vault-export/dashboard/`. |
| Session-browser edges (vault session-calendar) | Done, no-op until a ledger exists (Task 12). Files in `vault-export/session-calendar/`. |
| Provisioning documents | Written (Task 13 Step 1): `docs/provisioning.md`, `deploy/*.example`. |
| node1 install, keys, SSH entries, live run | **Not started** (Task 13 Steps 2–8). |
| Final whole-branch review | **Not done.** The subagent-driven procedure ends with one broad review of the whole range `0af6bca..f9503cf` on the most capable model. |

Main was fast-forwarded to `f9503cf` on 2026-11-02 (the first merge to `824f1f8` was on 2026-10-27, user-approved). The branch `research-bridge/impl` and the worktree `D:/raw/Codes/research-bridge-wt` still exist and point at the same commit. Remove them when no longer needed: `git worktree remove ../research-bridge-wt` then `git branch -d research-bridge/impl`. The worktree holds a working `.venv` you can borrow until the main one exists.

## Pending decisions (user)

1. ~~Laptop subnet for `from=`~~ — decided: `<LAPTOP_ETH_SUBNET>`.
2. Does the shared key `<SHARED_KEY>` stay in node1's `authorized_keys`? Only the new keys are restricted by `restrict,from=...,command=...`; `<SHARED_KEY>` keeps an unrestricted shell, so the "no unauthorized read or write" line is not fully enforced until it is removed or restricted. Plan default: it stays; clean up after the bridge is stable.
3. `job_template` in the node's `node.json`: an argv list with a `{config}` placeholder. It ships empty and `job_submit` refuses (`no_job_template`) until it is set. The training entry point on node1 is not known to this project.
4. Harness allowlist. The plan named `60_Tools/harness-sync/deliver.ps1`, which does not exist; the allowlist in use comes from `60_Tools/sync/prepare_staging.py` (`HARNESS_FILES` = `CLAUDE.md`, `settings.json`, `rtk-reference.md`; `HARNESS_DIRS` = `commands`, `agents`, `hooks`, `workflows`). Confirm or change. `harness_root` (the node's `~/.claude`) is empty by default, so push and pull are refused until set.

## Steps still to do

**User (do not delegate):**

- A1: `ssh-keygen` two ed25519 keys under `C:/keys/research-bridge/` (with passphrase), `ssh-add` both.
- A2: add `rb-node1` and `rb-node1-harness` to `~/.ssh/config` (`IdentitiesOnly yes`, `StrictHostKeyChecking yes`).
- A3: append the two lines of `deploy/authorized_keys.example` to node1's `~/.ssh/authorized_keys` with `from="<LAPTOP_ETH_SUBNET>"` and the `.pub` contents.
- Create `.venv` here (commands in `AGENTS.md`) and register the MCP server in `~/.claude.json` pointing at **this** directory's `.venv/Scripts/python.exe -m rb_host.server`. The snippet in `docs/provisioning.md` §B3 already uses that path.
- Create `D:/raw/research-bridge/host.json`: `{"nodes": {"node1": {"alias": "rb-node1", "harness_alias": "rb-node1-harness"}}}`. Without it `rb approve` and the dashboard approve button return an error.

**Session, after the user confirms each command:**

- B1: install `rb_node` on node1 through the existing `node1` alias, write `~/.research-bridge/node.json` from `deploy/node.json.example` with decisions 3 and 4 applied.
- B2: four security checks (table in `docs/provisioning.md`).
- B3: send a test message with a small pdf, `poll`, `read_doc("node1","H-001")`, submit a tiny job with `gpu_hours=0.01`, `rb approve`. Expect `job_finished` with `budget_exceeded` or `done`.
- Step 8: fill the Results section of `docs/provisioning.md`, write the vault daily log `90_Claude/90_Daily/2026-11-02.md` (or the day of the run), commit.

## Follow-ups (not blocking)

Every item below and in §Pending decisions / §Steps still to do is also a GitHub issue; tracking issue: Raon1123/research-bridge#21. Setup instructions per role: `docs/manual/` (English, with Korean translations).

- Run the final whole-branch review (see State). Record its findings in `docs/postmortems/` (template and rules in `docs/postmortems/README.md`).
- Complete the draft postmortem `docs/postmortems/2026-10-27-sdd-build.md` (items from the ledger only; `<to fill>` fields and an audit remain). Write a postmortem after the B3 live run.
- Changes to the protocol, ledger fields or keys start from `docs/design/TEMPLATE.md`; candidates are listed in `docs/design/README.md`.
- Unified board (autoresearch on node1 + research-bridge + the 8765 portfolio and priorities boards): draft design `docs/design/2026-11-02-unified-board.md`. First step is the user's: confirm the current node paths of `STATE.md`, `events.jsonl` and the kanban data, then add them as read roots in node1's `node.json`. The read roots in `deploy/node.json.example` still use pre-restructuring names.
- Hashes in this file and in `docs/history/` predate the 2026-11-02 rewrite of `main` and no longer resolve (`f9503cf` is now `a28a30b`, `c1a4786` is now `a8bb492`; mapping for fixes in `docs/postmortems/2026-10-27-sdd-build.md`). Branch rules: `docs/CONTRIBUTING.md`.
- `render.py` in the vault session-calendar builds the main screen from transcripts and does not read `cache/agents/*.json`, so bridge edges will not show on the main screen until it does. `bridge_edges.merge` writes into that cache only for sessions whose cache file already exists.
- `verify.py --server` reported one failure ("sessions whose utterances are not in time order", 1 session) after the Task 12 refresh. No baseline was taken before the change. It is inferred to be pre-existing because the bridge step is a no-op without a ledger. Confirm by running `verify.py` with the bridge step disabled.
- Ledger records do not carry `to_session` or attachment byte totals, so bridge edges always show `<node>:responder` and `bytes` 0. Add the fields on the host side if wanted.
- `reply_to` is stored in the host ledger only; the node's `msg_begin` has no such field, so a server session cannot see which earlier message a new one answers.
- `GET /rb/pending` is loopback-only; the other 8765 routes remain reachable from the LAN as before.
- `docs/history/sdd-2026-10-27/task-11-report.md` describes the first round of Task 11 only; the loopback fix is in the ledger.
- Git reports LF to CRLF conversion warnings on this machine. Copying `rb_node/` to node1 should use LF files (check out with `core.autocrlf=input` or convert before `scp`).
- Node queue numbering is not locked against two concurrent submitters (single submitter assumed).
- `os.killpg` budget kill path and the detached responder spawn are tested only with fakes; the live run covers them.

## Verification commands

    .venv/Scripts/python -m pytest -q
    curl -s -o NUL -w "%{http_code}" http://127.0.0.1:8765/rb/pending      # 200 on the laptop
    curl -s -o NUL -w "%{http_code}" http://<LAPTOP_WIFI_IP>:8765/rb/pending # 403 from the LAN address

Vault-side state checks: `vault-export/CHECKSUMS.txt`.
