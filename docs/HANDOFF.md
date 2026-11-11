# research-bridge state — 2026-11-10 (after the first live run)

Read `AGENTS.md` first. The previous text of this file (the 2026-11-05 plan with laptop-hub steps) is in git history: `git log -p -- docs/HANDOFF.md`.

Commands: `rb` below means `uv run --extra host rb`, run in the repository's main checkout with the same `RB_HOST_ROOT` (hub data root, `<data_root>`) as before. Abbreviations: SSH = Secure Shell; MCP = Model Context Protocol (the tool interface of Claude sessions); B2, B3 = the security checks and the first live run in `docs/provisioning.md`. People type the commands as shown; a session prefixes them with `rtk proxy` (plain `rtk` hides the `next:` lines of `rb doctor`).

## Audit of 2026-11-11

A session read the whole repository (code, tests, documents) on 2026-11-11 and changed it in two steps.

- PR 56 (branch `claude/audit-2026-11-11`): status lines and index rows that named merged branches, broken references, places where a manual or `AGENTS.md` disagreed with the code, three small code defects, unused code. The records of the first build and the two finished plans moved to `docs/99_Archive/` (index: `docs/99_Archive/README.md`).
- PR 57 (branch `claude/audit-fixes-2026-11-11`, on top of PR 56): the fifteen code defects the audit listed (a job stuck in `approved` after a node refusal, wrong-typed `node.json` values, a `poll` stopped by one malformed item, uncleaned board text, and others), duplicated code, code only tests used, and the documents that lagged (triage rows, designs, postmortems, manuals; Appendix A of the manuals is in the archive).

What was fixed, and what is left for the user to decide: `docs/issues/2026-11-11-audit.md`.

A third change, on branch `claude/hub-status-page` (on top of PR 57), answers audit row U3 as the user decided on 2026-11-11: the hub page gets the route `/status` (queue counts, GPUs in use, pending approvals, GPU-hours requested, one row per day of bridge activity, sessions and runs when `host.json` `share.*` names their files), and `rb share build|serve` with `rb_host/share_serve.py` moved to `docs/99_Archive/shared-status-page/` (`docs/design/2026-11-11-hub-status-page.md`). The route is visible only after the post-merge step below (restart of `rb-web.service`). Step 4 of that design, a read-only render against the real data root, has not been run.

What has run against node1: the hub code of PR 56 only. The main checkout has been on the PR 56 branch since the audit, and the sync timer runs that checkout, so its passes from 2026-11-11 16:17 on used the PR 56 `rb_host` (the 16:17 pass and the last pass before PR 57 was opened both ended with `Result=success` in `rb service status`). PR 57 has not run against node1, and no `rb_node` change of either PR is installed there: the node-side changes reach the node with its next `scripts/node-install.sh --update` after the merge.

## Node state and node-local tests (2026-11-10, session on node1)

Superseded on the node's code (2026-11-10, later): node1 was reinstalled from `main` and runs rb_node 0.2.0 (protocol 2) with the `queue_status` fix of PR 53; `rb-node doctor` reports no warning. The observations below are from before that.

Observed on node1:

- `rb_node` is installed by `scripts/node-install.sh`; `install.json` records a clean commit of branch `claude/node-allowed-gpus` (`rb-node git-status` shows which; the installed code equals commit `db1d412`). The branch is not pushed. After it is merged, reinstall from `main` so the record names a `main` commit.
- `node.json`: `job_template` is the Hydra by-name form (`--config-dir {config_dir} --config-name {config_stem}`), `allowed_gpus` is `[4, 5, 6, 7]`, the read roots exist, `withheld_source` is the JSON pattern file (mode 600), the approval verifier is set. `rb-node config check` reports one item: `harness_root` is empty (triage §5 item 15).
- The node audit log has hub ops from 2026-11-06 on (`hello`, `git_status`, `queue_status`, `gpu_status`, `read_doc`). It has no `msg_*`, `respond` or `job_submit` entry: the message and job paths have not run from the hub.
- The research queue is busy: four workers on GPUs 4–7 and about 50 queued jobs. A bridge job gets the highest number plus one, so it starts only after those.

Changed by PRs 46 and 47 (345 tests passed on node1 before the merge):

- `allowed_gpus` (new `node.json` key). Before, `job_submit` accepted every index `nvidia-smi` reports and `run-job` replaced the worker's `CUDA_VISIBLE_DEVICES` with the requested ids, so an approved job could run on another user's GPU (0–3) or on a GPU a second worker was using. Now: empty or malformed `allowed_gpus` refuses `job_submit` (`no_allowed_gpus`); a GPU outside the list or more than one GPU is `invalid`; `run-job` runs a one-GPU job on the worker's GPU (record and event carry `gpus_used`) and starts nothing outside the list (`failed`, reason `gpu_not_allowed`, exit 126).
- A by-name template (`{config_stem}`) takes `.yaml` only.
- The uploaded config is stored as `rbjob-<job_id><ext>`, not under the submitted name (user decision 2026-11-10). Before, a config named like one of the tree's own configs was ignored by Hydra without an error and the job would have run the tree's file.

Design: `docs/design/2026-11-10-allowed-gpus.md`. Postmortem: `docs/postmortems/2026-11-10-node-local-checks.md`.

Node-local test results: `docs/provisioning.md` §Results.

Open after these tests:

1. ~~Config name collision~~ — fixed 2026-11-10 (stored as `rbjob-<job_id>.yaml`).
2. **Config content.** A submitted config is the whole primary config. It must start with `defaults: [cfg_pretrain, _self_]` to inherit the base; without it the job gets only the keys in the file. Queue jobs written by hand pass `+project_name` and `+run_name` as overrides; a submitted config has to set them itself.
3. **Hub side:** run in B3 on 2026-11-10 (`docs/provisioning.md` §Results): the node's pattern file loaded (4 patterns, row 4), `send_message` with a pdf then `poll` (rows 1, 2), the `job_finished` event of job `rbtest-20261110` (`budget_exceeded`, row 2), and a real `submit_job` (rows 5, 6). Not run: `cancel_job` + `rb approve` against a console `rb-node run-job ... -- sleep 600`.
4. **Multi-GPU jobs** are refused until the queue has a way to give one job several GPUs.
5. The hub does not know the list itself: a wrong GPU in `submit_job` is refused only at approval. `hello` carries the boolean `allowed_gpus_set` and `rb doctor --node` reports it (`node_allowed_gpus`, warn when unset); showing the list in `gpu_status` is a possible follow-up.
6. Not checked in this session (the user's to check): the options on the two bridge lines in node1's `authorized_keys`, and what `~/.ssh/research-bridge/` on node1 holds (hub private keys do not belong on the node).

## Resume snippet

> The hub is the Linux server; the laptop keeps only the vault and its 8765 dashboard and views the hub page through an SSH forward. One node, `node1`, runs rb_node 0.2.0 from `main`. On 2026-11-10 the security checks (B2, rows 1 to 9) all held and the first live run (B3) passed rows 1 to 6, 8 and 9: a message with a pdf was answered, a document was read with withheld lines blanked, `rb sync` ran over SSH, a job was approved with `rb approve` and is queued on the node, and the sync timer and the hub page run as systemd user units. Row 7 (the job's `job_finished` event) waits for the research queue to reach the job. During B3, `queue_status` was found returning withheld job names (S0, fixed in PR 53). Next: `poll` for the job's event; then the open decisions.

## The real link

State on 2026-11-10 (B2 and B3, `docs/provisioning.md` §Results "Live run"):

- Works: SSH with the forced commands (B2 rows 1 to 3), node and hub doctor with no failure, the responder's argument list and its refusal to run commands (rows 7, 8), path escape refused (row 9); `send_message` with a pdf and the responder's reply through `poll`; `read_doc` with withheld lines blanked on the node; `rb sync` with `"ok": true`; `submit_job`, `rb approve` and the job queued on the node; `rb-sync.timer` and `rb-web.service` active with linger on; the hub page shows the node, the thread and the job.
- Withheld pattern files are loaded on both sides (4 patterns each besides the fallbacks).
- Open: B3 row 7, the `job_finished` event of job `75b0b3a9df614fc4becb47f0c079b7a9` (queued behind the research queue; budget 0.01 GPU-hour, so `budget_exceeded` is the expected status).
- Found and fixed: `queue_status` returned withheld job names to the hub (`docs/postmortems/2026-11-10-queue-status-withheld.md`, PR 53). Postmortem of the run: `docs/postmortems/2026-11-10-first-live-run.md`.

## On `main` since 2026-11-10 (PRs 48, 49, 50)

B2 and B3 on 2026-11-10 ran these on the real link: `node-install.sh` and `rb-node doctor` on the node, `rb doctor --node node1`, `rb sync`, `rb approve`, `rb service install` and the hub page through the forward (`docs/provisioning.md` §Results). The rest is covered by tests only.

- Hub commands: `rb setup` (host.json, keys, ssh config blocks, host key comparison, agent, the node command, the MCP registration command, doctor), `rb agent` (load keys once per boot), `rb doctor [--offline]`, `rb service install|status` (systemd user units `rb-sync.timer`, `rb-sync.service`, `rb-web.service`), `rb web serve` (read-only page on `127.0.0.1:8767`; from the laptop: `ssh -N -L 8767:127.0.0.1:8767 <HUB_HOST>`).
- SSH errors carry a code and the next command (`no_agent`, `agent_empty`, `key_not_loaded`, `node_refused_key`, `host_key_unknown`, `host_key_changed`, `unknown_alias`, `unreachable`, `timeout`, `closed`). The MCP server finds the agent itself: no `SSH_AUTH_SOCK` in its entry, no session restart when the agent changes.
- `rb sync` writes `<data_root>/sync/<node>.json`; items it stores are marked undelivered, so MCP `poll` still returns them. `send_message` keeps a masked copy of each sent body under `<data_root>/outbox/`.
- Node: `scripts/node-install.sh` is the single node entry point; `rb-node doctor`; `rb-node link [DIR] [--apply]`; `hello` protocol 2 with a `state` object; defect fixes. Removed: `scripts/hub-connect.sh`, `scripts/hub-agent.sh`, `scripts/trm-link.sh`.
- Designs (`docs/design/`, 2026-11-10): setup and diagnosis, sync and hub page (both implemented; both design documents keep the status draft until the user accepts them); project profiles, experiment records (design only). Project facts: `docs/projects/trm.md`.
- Tests: 919 passed on 2026-11-10 at PR 50 (Linux hub, Python 3.12); PRs 46, 47 added the `job_template` placeholders `{config_dir}` and `{config_stem}` and `allowed_gpus`. `rb-node config check` and `rb-node doctor` on the node report an empty `allowed_gpus` (check `allowed_gpus`).

## Next actions

### A session

- `poll` until the `job_finished` event of job `75b0b3a9df614fc4becb47f0c079b7a9` arrives; record its status in `docs/provisioning.md` §Results (row 7) and close the run's postmortem item.
- Apply the GitHub actions proposed in `docs/issues/2026-11-10-triage.md` after the user's go-ahead (none applied yet); #7 can be closed with the B2 results; #8 after B3 row 7 is recorded.
- Laptop-only items (8765 dashboard, session browser, shared status page) are listed there too (#13, #18, #19, #39).

### Only the user

- Decide whether to keep or delete the hub session transcript that holds the leaked names (queue postmortem, open items).
- The open decisions below; the first is transport authentication (#25), which was ordered after the first live run.
- After PRs 56 and 57 are merged (56 first, each with a merge commit: 57 is stacked on 56): the systemd units of the hub run the code of the main checkout, which was left on branch `claude/audit-2026-11-11`. In that checkout: `git switch main && git pull --ff-only`, `uv sync --extra host --python '>=3.10'`, then `systemctl --user restart rb-web.service` (the sync timer picks the code up by itself). The MCP server of a Claude session is also started from the main checkout (`uv run --directory <main checkout> ... python -m rb_host.server`) and keeps the code it loaded: a session that was open before the update serves the old `rb_host` until it is restarted or its MCP server is reconnected.
- Node updates from now on: on the node console, in the checkout (on `main`): `scripts/node-install.sh --update` (it runs `git pull --ff-only` itself).

## Pending decisions

All open decisions, with the default now in force and what changes otherwise: `docs/issues/2026-11-10-triage.md` §5. Decision 1 (push and merge) is done: PRs 48 and 49. The first open one: transport authentication (#25), which was ordered after the first live run; that run has passed. Open work by workstream: the same file, §4.

Decided by the user on 2026-11-11: PRs merge to `main` with merge commits only, and GitHub deletes a PR branch after the merge (`docs/CONTRIBUTING.md` §1 rule 3; PR 55). Also on 2026-11-11: MCP tools may gain optional arguments (the ten tools and their names stay; this refines default (2) of 2026-11-10 below and answers triage §5 item 7 and the open questions of the project-profiles and experiment-records designs, which remain drafts); research family identifiers are not withheld content, and new text names them only when needed (`AGENTS.md` Conventions); merged branches were deleted (`docs/issues/2026-11-11-audit.md` rows U2, U7, U9).

Decided by the user on 2026-11-10 (no longer waiting; items 3, 7, 8, 11, 13 and 20 of the triage list §5 are closed except where noted):

- The user confirmed the six defaults: (1) outgoing bodies are stored under `outbox/` after the withheld check, masked; (2) the ten MCP tools stay with their names and arguments; (3) the hub page has no approval form, approval stays `rb approve` in a hub terminal (the self-approval residual of PM-04 in `2026-11-03-whole-branch-review.md` stays accepted, as before); (4) unattended sync runs only through `rb service install`, run by the user; (5) the Windows instructions shrink to an appendix (the appendix moved to `docs/99_Archive/manual-appendix-a/` on 2026-11-11); (6) the `trm` names in config keys and on the wire are not renamed now.
- The user chose a one-time access key for the hub page: `rb web key` in a hub terminal prints an address; the browser exchanges the key once for a session cookie (defaults 10 minutes for the key, 12 hours for the session). No password and no login form. Design: `docs/design/2026-11-10-sync-and-hub-page.md` §6.6a. The page also refuses connections from other accounts (owner of the client socket, `/proc/net/tcp`). Residual risk: the cookie goes to every port on 127.0.0.1 and can be overwritten from there, which can sign the user out but gives another account nothing it can use against the page; anything running as the hub user is out of scope. A Unix-socket forward is only an alternative transport. Open the address by pasting it into the browser, not as a command-line argument; use `http://127.0.0.1:8767/`, not `localhost`.

## Test suite and `~/.claude.json` (2026-11-10)

From PR 48 (`c503667`) until PR 50, every run of the test suite replaced the real `~/.claude.json` of the account that ran it with a one-entry fixture. Do not run the suite on a checkout between those two commits. Postmortem: `docs/postmortems/2026-11-10-test-suite-overwrote-claude-json.md`.

- On the hub the file is whole again (87 top-level keys, `research-bridge` entry naming the main checkout, checked 2026-11-10); how it was restored is not recorded.
- The user said other accounts or machines may have run the suite in that window (node1 included). Each such account checks its `~/.claude.json` (top-level key count, the `research-bridge` entry) and restores from `~/.claude/backups/` or an older copy if it holds one `mcpServers` entry pointing into a pytest temporary directory.
- `rb doctor --offline` now names the directory the registered MCP entry runs (`registered: ...`) and what differs.

## Verification commands

Session, in this checkout, no node contact:

    rtk proxy uv run --extra host pytest -q        # 978 passed on 2026-11-11 (branch claude/hub-status-page; 975 on claude/audit-fixes-2026-11-11; 923 on PR 56; 921 on 2026-11-10 after PR 53)
    rtk proxy uv run --extra host rb doctor --offline    # hub side only, no SSH

User (or a session after a go-ahead, because these open an SSH connection): `rb doctor --node node1`, `rb sync --node node1`. Node console: `rb-node doctor`. Hub: `rb service status`.
