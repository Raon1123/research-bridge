# research-bridge state — 2026-11-10

Read `AGENTS.md` first. The previous text of this file (the 2026-11-05 plan with laptop-hub steps) is in git history: `git log -p -- docs/HANDOFF.md`.

Commands: `rb` below means `uv run --extra host rb`, run in the repository's main checkout with the same `RB_HOST_ROOT` (hub data root, `<data_root>`) as before. Abbreviations: SSH = Secure Shell; MCP = Model Context Protocol (the tool interface of Claude sessions); B2, B3 = the security checks and the first live run in `docs/provisioning.md`. People type the commands as shown; a session prefixes them with `rtk proxy` (plain `rtk` hides the `next:` lines of `rb doctor`).

## Node state and node-local tests (2026-11-10, session on node1)

Written by a session on node1 against `main` after PR 46 (merged into this branch on 2026-11-10 together with PR 47). It is newer than "The real link" below on what is installed on node1: the node already runs `scripts/node-install.sh` code of the `claude/node-allowed-gpus` branch (`rb_node` before this branch's `doctor`, `link` and protocol 2). Where the two disagree about the node, this section wins.

Observed on node1:

- `rb_node` is installed by `scripts/node-install.sh`; `install.json` records a clean commit of branch `claude/node-allowed-gpus` (`rb-node git-status` shows which; the installed code equals commit `db1d412`). The branch is not pushed. After it is merged, reinstall from `main` so the record names a `main` commit.
- `node.json`: `job_template` is the Hydra by-name form (`--config-dir {config_dir} --config-name {config_stem}`), `allowed_gpus` is `[4, 5, 6, 7]`, the read roots exist, `withheld_source` is the JSON pattern file (mode 600), the approval verifier is set. `rb-node config check` reports one item: `harness_root` is empty (decision 4).
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
3. **Hub side, not yet run:** `hello` (expect `withheld_extra > 0`), `send_message` with a small pdf then `poll`, `poll` for the `job_finished` event of job `rbtest-20261110` (posted by the console test, status `budget_exceeded`), `cancel_job` + `rb approve` against a console `rb-node run-job ... -- sleep 600`, and a real `submit_job` once the queue has room.
4. **Multi-GPU jobs** are refused until the queue has a way to give one job several GPUs.
5. The hub does not know the list itself: a wrong GPU in `submit_job` is refused only at approval. After the merge, `hello` carries the boolean `allowed_gpus_set` and `rb doctor --node` reports it (`node_allowed_gpus`, warn when unset); showing the list in `gpu_status` is a possible follow-up.
6. Not checked in this session (the user's to check): the options on the two bridge lines in node1's `authorized_keys`, and what `~/.ssh/research-bridge/` on node1 holds (hub private keys do not belong on the node).

## Resume snippet

> The hub is the Linux server (user decision, 2026-11-05); the laptop keeps only the vault and its 8765 dashboard. One node, `node1`, is registered and answers with rb_node 0.1.0 (code before this branch). Branch `claude/review-optimize-2026-11-10` (local, not pushed, not merged) adds one-command setup and diagnosis, unattended sync and a read-only hub page, and node 0.2.0. Next: the user decides whether to push and merge it (decision 1 in `docs/issues/2026-11-10-triage.md` §5), then runs the terminal steps below; a session then runs the live checks of `docs/provisioning.md` after a go-ahead.

## The real link

Works (checked 2026-11-06): hub keys exist and the node accepts them; the node answers over SSH with rb_node 0.1.0; MCP `gpu_status` and `queue_status` returned results.

Not done or not verified:
- The node has no withheld pattern file loaded: `hello` reported `withheld_extra = 0`, so only the five fallback patterns are active. For that reason `read_doc`, `send_message` and `poll` were deliberately not exercised.
- The 2026-11-06 hub checks did not confirm the approval verifier or `job_template`. The node1 section above (2026-11-10) found the verifier, `job_template` and `allowed_gpus` set; without `job_template` or `allowed_gpus` every job is refused.
- The node has not been updated to the code of this branch.
- The security checks (B2) and the first live run (B3) have not started.

## This branch (local only)

`claude/review-optimize-2026-11-10`: not pushed, not merged. Nothing in it runs on the real hub or node yet.

- Hub commands: `rb setup` (host.json, keys, ssh config blocks, host key comparison, agent, the node command, the MCP registration command, doctor), `rb agent` (load keys once per boot), `rb doctor [--offline]`, `rb service install|status` (systemd user units `rb-sync.timer`, `rb-sync.service`, `rb-web.service`), `rb web serve` (read-only page on `127.0.0.1:8767`; from the laptop: `ssh -N -L 8767:127.0.0.1:8767 <HUB_HOST>`).
- SSH errors carry a code and the next command (`no_agent`, `agent_empty`, `key_not_loaded`, `node_refused_key`, `host_key_unknown`, `host_key_changed`, `unknown_alias`, `unreachable`, `timeout`, `closed`). The MCP server finds the agent itself: no `SSH_AUTH_SOCK` in its entry, no session restart when the agent changes.
- `rb sync` writes `<data_root>/sync/<node>.json`; items it stores are marked undelivered, so MCP `poll` still returns them. `send_message` keeps a masked copy of each sent body under `<data_root>/outbox/`.
- Node: `scripts/node-install.sh` is the single node entry point; `rb-node doctor`; `rb-node link [DIR] [--apply]`; `hello` protocol 2 with a `state` object; defect fixes. Removed: `scripts/hub-connect.sh`, `scripts/hub-agent.sh`, `scripts/trm-link.sh`.
- Designs (`docs/design/`, 2026-11-10): setup and diagnosis, sync and hub page (both implemented here; both design documents keep the status draft until the user accepts them); project profiles, experiment records (design only). Project facts: `docs/projects/trm.md`.
- Tests: 854 passed on 2026-11-10 after merging `origin/main` (PRs 46, 47: `job_template` placeholders `{config_dir}` and `{config_stem}`, `allowed_gpus`) into this branch (Linux hub, Python 3.12). `rb-node config check` and `rb-node doctor` on the node report an empty `allowed_gpus` (check `allowed_gpus`).

## Next actions

### Only the user, at a terminal

1. Decide push and merge (decision 1). The node gets code with `git pull`, and `rb setup` and `rb service install` should run from the main checkout (setup warns in a worktree; the units call the `rb` of the installing environment). Then, on the hub, in the main checkout: `git pull` and `uv sync --extra host`. Then restart every Claude session on the hub before the first `rb sync`: an MCP server started on the old code never returns the items the new `rb sync` stores as not yet delivered.
2. Hub terminal: `rb doctor --offline`. If `withheld_hub` is not ok, copy the session-calendar withheld pattern file from the laptop to `<data_root>/withheld_patterns.json` (the path `withheld_patterns_file` in `host.json` names).
3. Node, with your own login (not the `rb-node1` alias, whose key runs only the forced command): copy the same file to `~/withheld-patterns.json`.
4. Node console, in the node's research-bridge checkout:

       git pull --ff-only
       scripts/node-install.sh --withheld-file ~/withheld-patterns.json
       rb-node approve-key set
       rb-node config set job_template '[..., "{config}"]'
       rb-node config set allowed_gpus '[4, 5, 6, 7]'
       rb-node doctor

   The installed script predates `--withheld-file`, so pull first (`git pull --ff-only`, or the installed script's `--update`), then run the new script; later updates are `scripts/node-install.sh --update`. Replace `[..., "{config}"]` with the project's job command as a JSON list containing `{config}`, `{config_dir}` or `{config_stem}` (`docs/manual/node-setup.md` §4.1.1); the value is a project fact (`docs/projects/trm.md`, decision 12). `allowed_gpus` is the list of GPU indices that belong to you (`[4, 5, 6, 7]` is the example from node1); empty, every job is refused with `no_allowed_gpus`. node1 already has both set (see the node1 section above).
5. Hub terminal: `rb setup --node node1`. It skips what exists, compares the host key when `known_hosts` has no entry, and prints `claude mcp add-json --scope user research-bridge '...'` when the registered entry differs; if so, run `claude mcp remove research-bridge`, then the printed command, and restart the Claude session once.
6. Hub terminal: `rb doctor --node node1`. Expected: `withheld_hub` ok, `node_version` 0.2.0 with protocol 2, `node_withheld`, `node_approval`, `node_job_template` and `node_allowed_gpus` ok.
7. Hub terminal: `rb service install`, then paste the `systemctl --user ...` line it prints; `rb service status`.
8. The security checks (B2) and the first live run (B3) in `docs/provisioning.md`.

### A session, after the user's go-ahead

- The MCP calls of B3 (`send_message`, `poll`, `read_doc`, `submit_job`), only after step 6 shows `withheld_hub` and `node_withheld` ok; `rb approve` stays the user's.
- Fill the Results section of `docs/provisioning.md` and write the postmortem of the first live run (`docs/postmortems/README.md`).
- Apply the GitHub actions proposed in `docs/issues/2026-11-10-triage.md` (none applied yet).
- Laptop-only items (8765 dashboard, session browser, shared status page) are listed there too (#13, #18, #19, #39).

## Pending decisions

All open decisions, with the default now in force and what changes otherwise: `docs/issues/2026-11-10-triage.md` §5. The first three: push and merge this branch; transport authentication (#25) before or after the first live run; approval surfaces (no form on the hub page, the self-approval residual). Open work by workstream: the same file, §4.

## Verification commands

Session, in this checkout, no node contact:

    rtk proxy uv run --extra host pytest -q        # 854 passed on 2026-11-10
    rtk proxy uv run --extra host rb doctor --offline    # hub side only, no SSH

User (or a session after a go-ahead, because these open an SSH connection): `rb doctor --node node1`, `rb sync --node node1`. Node console: `rb-node doctor`. Hub: `rb service status`.
