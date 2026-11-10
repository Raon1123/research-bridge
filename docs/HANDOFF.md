# research-bridge state — 2026-11-10

Read `AGENTS.md` first. The previous text of this file (the 2026-11-05 plan with laptop-hub steps) is in git history: `git log -p -- docs/HANDOFF.md`.

Commands: `rb` below means `uv run --extra host rb`, run in the repository's main checkout with the same `RB_HOST_ROOT` (hub data root, `<data_root>`) as before. Abbreviations: SSH = Secure Shell; MCP = Model Context Protocol (the tool interface of Claude sessions); B2, B3 = the security checks and the first live run in `docs/provisioning.md`. People type the commands as shown; a session prefixes them with `rtk proxy` (plain `rtk` hides the `next:` lines of `rb doctor`).

## Resume snippet

> The hub is the Linux server (user decision, 2026-11-05); the laptop keeps only the vault and its 8765 dashboard. One node, `node1`, is registered and answers with rb_node 0.1.0 (code before this branch). Branch `claude/review-optimize-2026-11-10` (local, not pushed, not merged) adds one-command setup and diagnosis, unattended sync and a read-only hub page, and node 0.2.0. Next: the user decides whether to push and merge it (decision 1 in `docs/issues/2026-11-10-triage.md` §5), then runs the terminal steps below; a session then runs the live checks of `docs/provisioning.md` after a go-ahead.

## The real link

Works (checked 2026-11-06): hub keys exist and the node accepts them; the node answers over SSH with rb_node 0.1.0; MCP `gpu_status` and `queue_status` returned results.

Not done or not verified:
- The node has no withheld pattern file loaded: `hello` reported `withheld_extra = 0`, so only the five fallback patterns are active. For that reason `read_doc`, `send_message` and `poll` were deliberately not exercised.
- The approval verifier on the node is not confirmed; `job_template` is not set, so every job is refused.
- The node has not been updated to the code of this branch.
- The security checks (B2) and the first live run (B3) have not started.

## This branch (local only)

`claude/review-optimize-2026-11-10`: not pushed, not merged. Nothing in it runs on the real hub or node yet.

- Hub commands: `rb setup` (host.json, keys, ssh config blocks, host key comparison, agent, the node command, the MCP registration command, doctor), `rb agent` (load keys once per boot), `rb doctor [--offline]`, `rb service install|status` (systemd user units `rb-sync.timer`, `rb-sync.service`, `rb-web.service`), `rb web serve` (read-only page on `127.0.0.1:8767`; from the laptop: `ssh -N -L 8767:127.0.0.1:8767 <HUB_HOST>`).
- SSH errors carry a code and the next command (`no_agent`, `agent_empty`, `key_not_loaded`, `node_refused_key`, `host_key_unknown`, `host_key_changed`, `unknown_alias`, `unreachable`, `timeout`, `closed`). The MCP server finds the agent itself: no `SSH_AUTH_SOCK` in its entry, no session restart when the agent changes.
- `rb sync` writes `<data_root>/sync/<node>.json`; items it stores are marked undelivered, so MCP `poll` still returns them. `send_message` keeps a masked copy of each sent body under `<data_root>/outbox/`.
- Node: `scripts/node-install.sh` is the single node entry point; `rb-node doctor`; `rb-node link [DIR] [--apply]`; `hello` protocol 2 with a `state` object; defect fixes. Removed: `scripts/hub-connect.sh`, `scripts/hub-agent.sh`, `scripts/trm-link.sh`.
- Designs (`docs/design/`, 2026-11-10): setup and diagnosis, sync and hub page (both built here); project profiles, experiment records (design only). Project facts: `docs/projects/trm.md`.
- Tests: 760 passed on 2026-11-10 at commit bef535b with the working tree of that day (Linux hub, Python 3.12).

## Next actions

### Only the user, at a terminal

1. Decide push and merge (decision 1). The node gets code with `git pull`, and `rb setup` and `rb service install` should run from the main checkout (setup warns in a worktree; the units call the `rb` of the installing environment). Then, on the hub, in the main checkout: `git pull` and `uv sync --extra host`.
2. Hub terminal: `rb doctor --offline`. If `withheld_hub` is not ok, copy the session-calendar withheld pattern file from the laptop to `<data_root>/withheld_patterns.json` (the path `withheld_patterns_file` in `host.json` names).
3. Node, with your own login (not the `rb-node1` alias, whose key runs only the forced command): copy the same file to `~/withheld-patterns.json`.
4. Node console, in the node's research-bridge checkout:

       git pull --ff-only
       scripts/node-install.sh --withheld-file ~/withheld-patterns.json
       rb-node approve-key set
       rb-node config set job_template '[..., "{config}"]'
       rb-node doctor

   The installed script predates `--withheld-file`, so pull first (`git pull --ff-only`, or the installed script's `--update`), then run the new script; later updates are `scripts/node-install.sh --update`. Replace `[..., "{config}"]` with the project's job command as a JSON list containing `{config}`; the value is a project fact (`docs/projects/trm.md`, decision 12).
5. Hub terminal: `rb setup --node node1`. It skips what exists, compares the host key when `known_hosts` has no entry, and prints `claude mcp add-json --scope user research-bridge '...'` when the registered entry differs; if so, run `claude mcp remove research-bridge`, then the printed command, and restart the Claude session once.
6. Hub terminal: `rb doctor --node node1`. Expected: `withheld_hub` ok, `node_version` 0.2.0 with protocol 2, `node_withheld` and `node_approval` ok.
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

    rtk proxy uv run --extra host pytest -q        # 760 passed on 2026-11-10
    rtk proxy uv run --extra host rb doctor --offline    # hub side only, no SSH

User (or a session after a go-ahead, because these open an SSH connection): `rb doctor --node node1`, `rb sync --node node1`. Node console: `rb-node doctor`. Hub: `rb service status`.
