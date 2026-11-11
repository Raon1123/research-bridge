# node1: security checks and first live run

Rewritten 2026-11-10. This file keeps only what is still to do on the real link: the security checks (B2) and the first live run (B3), with the results of 2026-11-10 in §Results. Linking a hub and a node (keys, ssh config blocks, host key, `authorized_keys` lines, node install) is now done by `rb setup` on the hub and `scripts/node-install.sh` on the node: see `README.md` and the manuals in `docs/manual/`. The earlier key and alias steps are in git history. Project facts for node1: `docs/projects/trm.md`. Open decisions: `docs/issues/2026-11-10-triage.md` §5. GitHub issue: #8.

Abbreviations: SSH = Secure Shell; MCP = Model Context Protocol (the tool interface of Claude sessions); GPU = graphics processing unit; PR = GitHub pull request.

Notation: `rb` means `uv run --extra host rb` in the hub's main checkout. `rb-node1` and `rb-node1-harness` are the ssh aliases `rb setup` writes for node `node1` (`rb-<node>`, `rb-<node>-harness`); use the aliases in `host.json` if they differ. A session runs a command only after the user's go-ahead for that command (`AGENTS.md`, "Ask the user before").

## Before B2

All of these must hold first (node steps: `docs/manual/node-setup.md` §2 and §4.2; hub steps: `README.md`, Link a node). The boxes were not ticked for the run of 2026-11-10; what was observed then is in §Results:

- [ ] The node runs rb_node 0.2.0, installed by `scripts/node-install.sh` with `--withheld-file`.
- [ ] `rb-node approve-key set` was run on the node console.
- [ ] `rb doctor --node node1` on the hub shows `withheld_hub` ok, `node_version` ok (0.2.0, protocol 2), `node_withheld` ok, `node_approval` ok.
- [ ] The MCP server `research-bridge` is registered from the main checkout (`rb setup --node node1` prints the command if not) and the Claude session was restarted after a change.

## B2. Security checks

Each row must hold. If one does not, stop and write a postmortem (`docs/postmortems/README.md`).

Scripts that run rows 1 to 8 and print PASS or FAIL per row: `scripts/b2-hub.sh [NODE] [--shared-alias SSH_ALIAS]` in a hub terminal (rows 1, 2, 3, 6; row 4 only with `--shared-alias`, recorded, not judged) and `sh scripts/b2-node.sh` on the node console (rows 5, 7, 8; rows 7 and 8 are two short paid model calls). Neither prints what the node sent for rows 1 to 3. Row 9 stays the session's.

| # | Who and where | Command | Expected |
|---|---|---|---|
| 1 | user, hub terminal | `ssh rb-node1` (type nothing, then Ctrl-D) | No shell prompt. Protocol output only. |
| 2 | user, hub terminal | `ssh rb-node1 cat /etc/passwd` | Nothing from `cat`; no passwd contents. The forced command ignores the requested command. |
| 3 | user, hub terminal | `ssh rb-node1-harness ls` | `rb-node harness-receive: unknown command`, exit status 1. |
| 4 | user, own login | log in to the node with `<SHARED_KEY>` | Record whether it gives a normal shell or a restricted one; this is not recorded yet (decision 5 of the triage file). The two bridge keys are the ones that must be restricted. |
| 5 | user, node console | `rb-node doctor` | `ak_bridge` ok (`serve-remote line N is restricted`), `ak_harness` ok, `withheld` ok (`N pattern(s) loaded besides the fallback`), `approval` ok. No `fail` line. |
| 6 | user, hub terminal | `rb doctor --node node1` | No `fail` line; `known_host`, `ssh_options`, `reachable`, `node_withheld`, `node_approval` ok. |
| 7 | user, node console | `claude -p 'Say ok.' --tools Read,Grep,Glob --setting-sources ""` then `echo $?` | A short answer and `0`. If the Claude command line rejects `--setting-sources ""`, every responder run ends in `responder_failed` (`2026-11-03-whole-branch-review.md` PM-02). |
| 8 | user, node console | `claude -p 'Run the shell command id and print its output.' --tools Read,Grep,Glob --setting-sources ""` | No output of `id`; the answer says it cannot run commands. |
| 9 | session on the hub, after go-ahead | MCP `read_doc("node1", "../../.ssh/authorized_keys")` | `denied`. |

## B3. First live run

Run only after every B2 row holds. Use test text that names no withheld series.

| # | Who and where | Command | Expected |
|---|---|---|---|
| 1 | session on the hub, after go-ahead | MCP `send_message("node1", "<short test question>", [<path of a small pdf>])` | `{"msg_id": ..., "status": "sent"}`; a masked copy under `<data_root>/outbox/node1/<msg_id>/`. |
| 2 | session, a few minutes later | MCP `poll()` | The responder's reply; its files under `<data_root>/inbox/node1/<reply id>/` with `body.txt` and `provenance.json`. |
| 3 | session | MCP `read_doc("node1", "<an EXP or H id that exists on the node>")` (for `trm`, `EXP-001` exists; `H-001` does not) | The document text, with any withheld line blanked. |
| 4 | user, hub terminal | `rb sync --node node1` | Exit 0; `<data_root>/sync/node1.json` has `"ok": true` (this is the PR 45 check "`rb sync` over a real SSH connection"). |
| 5 | session, after go-ahead | MCP `submit_job("node1", <path of a tiny config>, [<one GPU id>], 0.01, <new idempotency key>)` | A `pending_approval` record and its job id; nothing is sent to the node yet. Needs `job_template` (decision 12). |
| 6 | user, hub terminal | `rb pending`, then `rb approve <job_id>` | y/N question, then the approval passphrase; the job is queued on the node. |
| 7 | session | MCP `poll()` later | A `job_finished` event with status `done` or `budget_exceeded`. |
| 8 | user, hub terminal | `rb service install`, paste the printed `systemctl --user ...` line; after one timer interval `rb service status` and `rb doctor --node node1` | Both units active; `sync_status` ok. |
| 9 | user, laptop | `ssh -N -L 8767:127.0.0.1:8767 <HUB_HOST>`, then open `http://127.0.0.1:8767/` | The node with a recent sync time, the thread from rows 1 and 2, the job from rows 5 to 7. |

## Results

### Node-local checks (2026-11-10, run on node1's console)

The hub was not involved. The B2 and B3 results are below.

| Check | Result |
|---|---|
| Test suite on node1 (Python 3.12) | 345 passed |
| `rb-node config check` | One item: `harness_root` is empty |
| Installed code against the checkout | Identical; install record clean |
| Hydra by-name template, `--cfg job` (composition only, no training), config with `defaults: [cfg_pretrain, _self_]` | Composes; the tree's `arch` group resolves; the submitted key is present |
| Same, config without a `defaults` list | Composes to the submitted keys only (the base config is not inherited) |
| Same, config named like the tree's own primary config | The submitted file is ignored; the tree's file is loaded, no error |
| Same, after the fix: the config stored as `rbjob-<32 hex>.yaml` (the name `job_submit` now gives it) | Composes; the submitted key is present |
| Same, `.yml` and `.json` | `Cannot find primary config`; exit 1. `job_submit` now refuses these for a by-name template |
| PM-02: `rb-node respond` in a minimal non-login environment (`env -i`, system `PATH`), Claude CLI 2.1.322, scratch mailbox and scratch tree | Two queued messages answered in one run; the scratch audit log shows `local.inbox_read` and `local.reply` for each. One asked for a shell command: the reply declined |
| PM-02: the `claude` argv of `rb_node/spawn.py` run by hand in the same environment, output kept, message asking to create a file by any tool | Claude exit code 0, empty stderr, `--setting-sources ""` accepted, result `success`; reply sent through `reply`; no file was created. The session declined without calling a tool, so this does not show a tool call being blocked |
| `run-job`, GPU outside `allowed_gpus` (scratch config) | Nothing launched; `failed`, reason `gpu_not_allowed`, exit 126 |
| `run-job`, GPU 5 requested under a worker that exports GPU 6 (scratch config) | Job sees `CUDA_VISIBLE_DEVICES=6`; record has `gpus_used: [6]` |
| `run-job`, worker on a GPU outside `allowed_gpus` (scratch config) | Nothing launched; `gpu_not_allowed` |
| `run-job --gpus 4 --gpu-hours 0.001 --job-id rbtest-20261110 -- sleep 60` (real node config) | Stopped after 3.7 s (budget 3.6 s), no process left; a `job_finished` event is in the node outbox for the hub's next `poll` |

Not covered by these checks: delivery over SSH, the forced command, masking on `poll`, approval with the passphrase, and a job claimed by the real queue runner.

### Security checks (B2, 2026-11-10)

Rows 1 to 8 were run by the user with `scripts/b2-hub.sh` (hub terminal) and `scripts/b2-node.sh` (node console); row 9 by the hub session.

| Row | Result |
|---|---|
| 1 to 3 | PASS: no shell on the bridge key, the requested command ignored, the harness key refused `ls` with `unknown command` |
| 4 | recorded by the user; not judged (decision 5) |
| 5, 6 | PASS: `rb-node doctor` and `rb doctor --node node1` with no failure (the node's earlier `install` warning, record 0.1.0 against running code 0.2.0, was cleared by running `scripts/node-install.sh` again) |
| 7, 8 | PASS: the Claude command line accepted the responder's arguments (exit 0) and did not run `id` |
| 9 | PASS: `read_doc("node1", "../../.ssh/authorized_keys")` returned `denied` |

### Live run (B3, 2026-11-10)

| Row | Who | Result |
|---|---|---|
| 1 | session | PASS: `send_message` with a 639-byte test pdf returned `sent`; a masked copy is under `outbox/node1/<msg_id>/` |
| 2 | session | PASS: `poll` returned the responder's reply, which named the word in the pdf; `inbox/node1/<reply id>/` holds `body.txt` and `provenance.json`; nothing quarantined. The same `poll` returned the `job_finished` event of the console test job `rbtest-20261110` (`budget_exceeded`) |
| 3 | session | PASS: `read_doc("node1", "EXP-001")` returned the text with 13 lines blanked on the node. `H-001` gave `not_found` (no such heading in the registry); the row's example id is not a fact of this project |
| — | session | **Stopped before row 5:** `queue_status` returned withheld job names unmasked (S0). Fixed in PR 53 (node and hub); after the node reinstall and a session restart, `queue_status` returned 116 names as `(withheld)` and none that matches a fallback pattern. `docs/postmortems/2026-11-10-queue-status-withheld.md` |
| 4 | user | PASS: `rb sync --node node1` exit 0; `sync/node1.json` has `"ok": true`, node 0.2.0 protocol 2, 4 patterns on each side |
| 5 | session | PASS: `submit_job` (config with `defaults: [cfg_pretrain, _self_]`, `project_name`, `run_name`, `epochs: 1`; GPU 4; 0.01 GPU-hour) returned `pending_approval`, job `75b0b3a9df614fc4becb47f0c079b7a9` |
| 6 | user | PASS: `rb approve` at 2026-11-10 13:59Z; the ledger records `approved`, then `queued` |
| 7 | session | open: the job waits behind the research queue (about 75 jobs ahead at submission) |
| 8 | user | PASS: `rb service install`; `rb-sync.timer` and `rb-web.service` active, linger yes, the timer's sync exited with success |
| 9 | user | PASS: the hub page through the SSH forward shows the node, the thread of rows 1 and 2 and the job |

Postmortem of the run: `docs/postmortems/2026-11-10-first-live-run.md`.
