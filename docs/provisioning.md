# node1: security checks and first live run

Rewritten 2026-11-10. This file keeps only what is still to do on the real link: the security checks (B2) and the first live run (B3), with an empty Results section. Linking a hub and a node (keys, ssh config blocks, host key, `authorized_keys` lines, node install) is now done by `rb setup` on the hub and `scripts/node-install.sh` on the node: see `README.md` and the manuals in `docs/manual/`. The earlier key and alias steps are in git history. Project facts for node1: `docs/projects/trm.md`. Open decisions: `docs/issues/2026-11-10-triage.md` §5. GitHub issue: #8.

Abbreviations: SSH = Secure Shell; MCP = Model Context Protocol (the tool interface of Claude sessions); GPU = graphics processing unit; PR = GitHub pull request.

Notation: `rb` means `uv run --extra host rb` in the hub's main checkout. `rb-node1` and `rb-node1-harness` are the ssh aliases `rb setup` writes for node `node1` (`rb-<node>`, `rb-<node>-harness`); use the aliases in `host.json` if they differ. A session runs a command only after the user's go-ahead for that command (`AGENTS.md`, "Ask the user before").

## Before B2

All of these must hold first (steps 1 to 6 of `docs/HANDOFF.md` §Next actions):

- [ ] The node runs rb_node 0.2.0, installed by `scripts/node-install.sh` with `--withheld-file`.
- [ ] `rb-node approve-key set` was run on the node console.
- [ ] `rb doctor --node node1` on the hub shows `withheld_hub` ok, `node_version` ok (0.2.0, protocol 2), `node_withheld` ok, `node_approval` ok.
- [ ] The MCP server `research-bridge` is registered from the main checkout (`rb setup --node node1` prints the command if not) and the Claude session was restarted after a change.

## B2. Security checks

Each row must hold. If one does not, stop and write a postmortem (`docs/postmortems/README.md`).

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
| 3 | session | MCP `read_doc("node1", "H-001")` (or another document id from `docs/projects/trm.md`) | The document text, with any withheld line blanked. |
| 4 | user, hub terminal | `rb sync --node node1` | Exit 0; `<data_root>/sync/node1.json` has `"ok": true` (this is the PR 45 check "`rb sync` over a real SSH connection"). |
| 5 | session, after go-ahead | MCP `submit_job("node1", <path of a tiny config>, [<one GPU id>], 0.01, <new idempotency key>)` | A `pending_approval` record and its job id; nothing is sent to the node yet. Needs `job_template` (decision 12). |
| 6 | user, hub terminal | `rb pending`, then `rb approve <job_id>` | y/N question, then the approval passphrase; the job is queued on the node. |
| 7 | session | MCP `poll()` later | A `job_finished` event with status `done` or `budget_exceeded`. |
| 8 | user, hub terminal | `rb service install`, paste the printed `systemctl --user ...` line; after one timer interval `rb service status` and `rb doctor --node node1` | Both units active; `sync_status` ok. |
| 9 | user, laptop | `ssh -N -L 8767:127.0.0.1:8767 <HUB_HOST>`, then open `http://127.0.0.1:8767/` | The node with a recent sync time, the thread from rows 1 and 2, the job from rows 5 to 7. |

## Results

As of 2026-11-10: not run.

(Fill in after the run: date, who ran each row, outcome per row, deviations. Then write the postmortem of the first live run.)
