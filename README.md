# research-bridge

research-bridge connects Claude sessions on a **hub** to Claude sessions on an experiment server, the **node**, over SSH (Secure Shell). The hub is the machine that holds the keys and the data; here it is a Linux server. From the hub, a session can send messages with attachments to a session on the node, read the node's hypothesis (H-xxx) and experiment (EXP-xxx) documents with withheld material masked, see the job queue and GPU (graphics processing unit) use, and request jobs. The hub side is an MCP (Model Context Protocol) server, `rb-host-mcp`, and a command-line tool, `rb`. The node side, `rb-node`, is standard-library Python that the hub reaches over SSH.

![research-bridge concept](docs/images/concept.svg)

The figure was drawn when the laptop was the hub. Since 2026-11-05 the hub is a Linux server. The 8765 dashboard in the figure stays on the laptop, and the hub has its own read-only page on port 8767 (see [Daily use](#daily-use)).

- **Only the hub opens connections.** The node answers on the same connection and never connects to the hub.
- **A session can request a job but cannot approve it.** You approve it in a hub terminal with `rb approve` and type the approval passphrase. The node checks a key derived from that passphrase against a verifier it stores.
- **Withheld material is filtered on the node and checked again on the hub** before anything is stored or shown.

## Requirements

| | Hub | Node |
|---|---|---|
| System | Linux; a systemd user manager for the optional timer and page | Linux (the installer uses GNU `mv -T`) |
| Python | installed by uv (3.10 or later) | `python3` 3.8 or later on `PATH` |
| Programs | [uv](https://docs.astral.sh/uv/), git, OpenSSH client (`ssh`, `ssh-keygen`, `ssh-agent`, `ssh-add`, `ssh-keyscan`), the Claude command-line interface (CLI, `claude`; used to register the MCP server), `ip` (optional; used to find the hub address) | git, OpenSSH server; optional: `pdftotext` (without it pdf files are denied), the Claude CLI (the responder that answers messages when no live session does) |
| Access | a terminal for the commands that ask questions | a console login as the node user |

## Try it without a node

In a terminal, from a clone of this repository:

```
uv sync --extra host
uv run --extra host python scripts/demo_dashboard.py
```

The demo starts a throwaway node process on the same machine (no SSH), with made-up jobs, fake GPUs and one stored conversation, all in a new temporary directory. It prints:

```
demo data: /tmp/rb-demo-...
open http://127.0.0.1:8799/board and /rb/pending (passphrase: demo passphrase)
hub page: http://127.0.0.1:8800/ (also /threads, /jobs, /nodes)
```

`/board` and `/rb/pending` are copies of the laptop's 8765 dashboard pages. Approving one of the two pending jobs on `/rb/pending` with the passphrase `demo passphrase` runs the real approval path against the demo node, and `/board` then shows the queued job. Port 8800 serves the hub page described under [Daily use](#daily-use); it shows a banner because the demo node has no pattern file. Stop the demo with Ctrl+C. If the demo runs on a hub without a browser, forward both ports from the laptop: `ssh -N -L 8799:127.0.0.1:8799 -L 8800:127.0.0.1:8800 <HUB_HOST>`.

| Unified board (`/board`) | Pending approval (`/rb/pending`) |
|---|---|
| ![Unified board](docs/images/board.png) | ![Pending approval](docs/images/rb-pending.png) |

## Link a node

**How to run `rb`.** In a hub terminal, inside the checkout, every `rb` command below is typed as `uv run --extra host rb ...`. To type `rb` alone from any directory, add this line to your shell profile, with the path of your checkout:

```
alias rb='uv run --directory ~/research-bridge --extra host rb'
```

**Who types what.** `rb setup`, `rb agent`, `rb service install`, `rb approve`, `rb reject`, `rb-node approve-key set` and the `authorized_keys` change refuse to run unless stdin and stdout are a terminal, so a Claude session cannot run them: you type them. A session can run `rb setup --node node1 --yes-print-only` (shows every change and command, writes and asks nothing; a first run also needs `--host` and `--user`), `rb doctor`, `rb sync`, `rb pending` and `rb service status`. Claude sessions on this machine prefix shell commands with `rtk`; for `rb`, use `rtk proxy uv run --extra host rb doctor`, because plain `rtk` hides the `next:` lines. A session needs your go-ahead before any command that contacts the node.

**Files outside the repository.** On the hub, `rb setup` creates two key pairs in `~/.ssh/research-bridge/` (`node1_ed25519`, `node1_harness_ed25519`), appends two `Host` blocks to `~/.ssh/config` and host key lines to `~/.ssh/known_hosts`; `rb service install` writes three unit files to `~/.config/systemd/user/`. Each of these edits is shown first and made only after you type `y`, and an existing file is first copied to `<name>.bak.<timestamp>`. The data root and `host.json` are created without a question. `rb` never edits `~/.claude.json`; you run the `claude mcp add-json` command it prints. On the node, `scripts/node-install.sh` writes its own files without asking (code under `~/.local/share/research-bridge/`, the wrapper `~/.local/bin/rb-node`, and `~/.research-bridge/` with `node.json`, the mailbox and an install record). It changes `~/.ssh/authorized_keys` only with `--apply-authorized-keys`, on a terminal, after showing the change and a `y` answer, with a backup first.

1. **Hub terminal: install.** Use the main checkout, not a git worktree: the MCP entry and the unit files hold this path.
   ```
   git clone <REPO_URL> research-bridge && cd research-bridge
   uv sync --extra host
   ```
2. **Hub terminal: hub pattern file.** The data root is `$RB_HOST_ROOT` if set, otherwise `~/.local/share/research-bridge`. Copy the withheld pattern file (the session-calendar JSON, JavaScript Object Notation, export kept in the vault on the laptop, for example with `scp` from the laptop) into it as `withheld_patterns.json`. Without it, `rb doctor` reports a fail and `rb setup` prints a node command without a pattern file.
   ```
   mkdir -p -m 700 ~/.local/share/research-bridge
   ```
3. **Hub terminal: `rb setup` with the four facts** (node name, host, SSH port, user). Optional: `--research-root DIR` (the research tree on the node, copied into the node command), `--hub-from ADDR` (the address the node sees this hub as; otherwise derived with `ip route get`), `--keydir DIR`.
   ```
   rb setup --node node1 --host <NODE_HOST> --port <NODE_PORT> --user <NODE_USER>
   ```
   It runs nine steps, each printed as `step N/9 ...` and ending in `-> done`, `skipped`, `printed` or `failed: ...`: (1) data root and `host.json`; (2) node entry with the aliases `rb-node1` and `rb-node1-harness`; (3) keys: asks `Generate ...? [y/N]`, then `ssh-keygen` asks a passphrase twice per key (the same passphrase may serve both); (4) shows the two `Host` blocks and asks `Append to ~/.ssh/config? [y/N]` (aliases that already exist with other values are reported, not rewritten); (5) host key: deferred on this first run; (6) loads both keys into an ssh-agent under `$XDG_RUNTIME_DIR`, starting `rb-ssh-agent` there if none answers, and `ssh-add` asks the key passphrase; (7) prints the node command for step 5 below; (8) prints `claude mcp add-json --scope user research-bridge '...'`; (9) runs `rb doctor`, whose online part fails until the node is installed. A hub linked earlier with the removed scripts `hub-connect.sh` and `hub-agent.sh` runs the same command; existing keys and blocks are kept.
4. **Hub terminal: pattern file to the node,** with your own login (the bridge key can only run `rb-node serve-remote`). Note the hyphen in the node's file name.
   ```
   scp -P <NODE_PORT> ~/.local/share/research-bridge/withheld_patterns.json <NODE_USER>@<NODE_HOST>:withheld-patterns.json
   ```
5. **Node console: install.** Get a checkout and paste the command that step 7 of `rb setup` printed. It looks like this:
   ```
   git clone <REPO_URL> research-bridge && cd research-bridge
   scripts/node-install.sh \
       --research-root DIR \
       --hub-key 'ssh-ed25519 AAAA... research-bridge-hub' \
       --harness-key 'ssh-ed25519 AAAA... research-bridge-harness' \
       --hub-from <HUB_ADDR> --withheld-file ~/withheld-patterns.json --apply-authorized-keys
   ```
   It checks `python3` and git, installs the code as a new release, writes `node.json` with `trm_root` set to the research tree and the queue and write paths derived from it, sets `claude_bin` if `claude` is on `PATH`, validates the pattern file, copies it to `~/.research-bridge/withheld-patterns.json` and sets `withheld_source`, shows the `authorized_keys` change and asks y/N, prints the node's host key fingerprints, runs `rb-node doctor` and ends with `Next (you, on this console): rb-node approve-key set`. Without `--research-root` and without a `node.json`, it asks `Research tree on this node:`. `--dry-run` prints every action and writes nothing.
6. **Node console: approval passphrase.** At least 12 characters, typed twice. It is not the SSH key passphrase; you type it at every `rb approve`. If `~/.local/bin` is not on `PATH`, type `~/.local/bin/rb-node`.
   ```
   rb-node approve-key set
   ```
   To run jobs, the node also needs the command line for one job, with `{config}` where the config path goes. The value is project-specific; the project's page under `docs/projects/` records what is known about it. Without it the node refuses job submissions (`no_job_template`).
   ```
   rb-node config set job_template '["...", "{config}"]'
   ```
7. **Hub terminal: host key.** `rb setup` takes host, port and user from the `Host` block, scans the node's host key once, shows the fingerprint and asks whether it equals the line of the same type that `node-install.sh` printed; `y` appends it to `~/.ssh/known_hosts`. If they differ, answer `n` and do not connect. Its last step then connects and sends `hello`.
   ```
   rb setup --node node1
   ```
8. **Hub terminal: MCP server.** Paste the `claude mcp add-json --scope user research-bridge '...'` line that `rb setup` printed (`rb doctor` prints it again under `mcp_entry` while it is missing). The entry runs `uv run --directory <checkout> --extra host python -m rb_host.server`. Then start a new Claude session: MCP servers load when a session starts.
9. **Hub terminal: check.** Repeat until the last line reads `summary: N ok, N warn, 0 fail`, fixing each problem with the command on its `next:` line. Warnings that normally remain: `local_json` (only the harness path mapping needs it), `service_sync` and `service_web` until you install the services below, `node_job_template` until `job_template` is set. `node_withheld` is only a warning, but it must read `node loaded N pattern(s)` before anyone uses `read_doc`, `send_message` or `poll`, runs `rb sync`, or enables the timer below (see [Troubleshooting](#troubleshooting)).
   ```
   rb doctor
   ```

## Daily use

**After a reboot**, in a hub terminal: `rb agent`. It loads both keys into the agent under `$XDG_RUNTIME_DIR` (starting one if none answers), asks the key passphrase and prints the agent's socket path, plus an `export SSH_AUTH_SOCK=...` line for `rb harness` in the same shell. The MCP server, `rb sync` and the timer find that agent themselves, so no Claude session needs a restart.

**Automatic sync and the hub page**, once, in a hub terminal, after `rb doctor` reports that the node loaded its pattern file:

```
rb service install
systemctl --user daemon-reload && systemctl --user enable --now rb-sync.timer rb-web.service
```

`rb service install` shows `rb-sync.service`, `rb-sync.timer` and `rb-web.service`, writes each after `y`, and prints the `systemctl` line (it never runs it), plus `loginctl enable-linger <user>` when lingering is off: without it user units stop at logout, and it may need an administrator. Options: `--interval SECONDS` (default 300, at least 30), `--port PORT` (default 8767), `--print` (show, write nothing). The timer starts `rb sync` 60 s after it starts and then 300 s after each pass ends. One pass opens one connection, sends `hello`, `poll` and `git_status`, stores new replies and events on the hub as not yet delivered, refreshes the board cache, and records the result in `<data root>/sync/node1.json`. It never approves a job and never touches the harness channel. Sessions still call the MCP `poll` tool: it returns the items the timer stored, each once, marked `stored: true`. Check with `rb service status` or `rb doctor`. Without systemd, run `rb sync` for one pass or `rb sync --watch 300` in the foreground.

**Opening the hub page from the laptop.** The page listens on 127.0.0.1 only. Forward the same port on both sides (the page accepts only requests addressed to its own port) and open `http://localhost:8767/`:

```
ssh -N -L 8767:127.0.0.1:8767 <HUB_HOST>
```

The page only reads hub files: it opens no node connection, accepts only GET and HEAD, has no forms, and masks text with the hub pattern file. A banner appears when a node reports `withheld_extra 0` or the hub pattern file is unusable.

| Page | Shows |
|---|---|
| `/` | per node: sync state, last success, node version, protocol, `withheld_extra`, research tree commit, undelivered replies; pending approvals with the `rb approve` and `rb reject` commands to type; the 10 latest conversations |
| `/threads`, `/thread/<id>` | all conversations; one conversation with each message's time, direction, session label, status, attachments and masked body, marking replies no `poll` has returned yet |
| `/jobs` | job records grouped by status, with their `job_finished` events |
| `/nodes` | the last sync status of each node and the board cache (queue, GPU, state, events, kanban) |

**What a Claude session can do** through the ten MCP tools:

| Tool | Does |
|---|---|
| `nodes` | lists the nodes and the state of the last sync pass (node version, staleness, undelivered replies) |
| `send_message` | sends a message with attachments (50 MB each at most); a masked copy of the body is kept in `outbox/` on the hub |
| `poll` | returns new replies and events, each once |
| `thread` | lists the ledger records of a message and its direct replies, with the folder of each stored body |
| `read_doc` | reads an H-xxx or EXP-xxx document, or a path under a node read root, masked on the node |
| `fetch_file` | downloads a node file through the node's read policy and checks it again on the hub |
| `queue_status` | reads the node's job queue |
| `gpu_status` | reads the node's GPU use |
| `submit_job` | requests a job: writes only a `pending_approval` record and opens no connection |
| `cancel_job` | requests a cancel, the same way |

**Approving a job**, in a hub terminal:

```
rb pending
rb approve <job_id>
rb reject <job_id>
```

`rb approve` prints the record (node, config, its sha256, GPUs, GPU-hours, note), asks `Approve? [y/N]` and then `Approval passphrase:`. The hub derives the key and sends the job; the node checks it against its verifier and queues the job. Nothing else approves: no MCP tool, no flag, no file or environment variable holds the passphrase, and the hub page only shows the commands. The approval route of the laptop's 8765 dashboard does not reach this hub's ledger.

## Updating the node code

On the node console, in the checkout:

```
scripts/node-install.sh --update
```

It runs `git pull --ff-only`, installs the code as a new release and switches to it in one rename; `node.json`, the pattern file, the approval verifier and `authorized_keys` are kept, and the two newest releases stay on disk. Update the hub with `git pull` and `uv sync --extra host` in its checkout. The hub shows the node's version in `rb doctor --node node1` (`node runs X`, `node runs X, hub has Y`, or `node code X predates protocol 2`, with `next: on the node: scripts/node-install.sh --update`), in the `nodes` tool and on the hub page; `rb git-status --node node1` adds the installed commit and the git state of the research tree. Node code before 0.2.0 has no `rb-node doctor` and does not report its approval verifier, `job_template` or responder; the hub shows those as `unknown (node code predates protocol 2)`.

## Troubleshooting

`rb doctor` prints `fail reachable  CODE: MESSAGE` and a `next:` line; the MCP tools and `rb approve` print `MESSAGE (next: COMMAND)`.

| Code | Message | Cause | Run |
|---|---|---|---|
| `no_agent` | no ssh-agent reachable for ALIAS | no agent running (after a reboot) | `rb agent` |
| `agent_empty` | the ssh-agent holds no keys | agent running, keys not loaded | `rb agent` |
| `key_not_loaded` | the key for ALIAS is not in the ssh-agent | other keys loaded, not this one | `rb agent --node NODE` |
| `node_refused_key` | ALIAS refused the key | `authorized_keys` line missing or old, or `from=` does not match the hub address | on the node: `rb-node doctor` (see below) |
| `host_key_unknown` | no known_hosts entry for ALIAS | step 7 not done | `rb setup --node NODE` |
| `host_key_changed` | host key of ALIAS changed | the node was reinstalled, or another machine answers | do not connect; compare fingerprints on the node console, then `rb doctor --node NODE` |
| `unknown_alias` | ssh has no Host block for ALIAS | step 3 not done or block removed | `rb setup --node NODE --host HOST --user USER` |
| `unreachable` | cannot reach ALIAS (network or address) | wrong host, network down, SSH server (`sshd`) not running | `rb doctor --node NODE` |
| `timeout` | ALIAS did not answer in time | slow network or node | retry; if it repeats, `rb doctor --node NODE` |
| `closed` | connection to ALIAS closed (exit N) | the node side failed | on the node: `rb-node doctor` (old code: `scripts/node-install.sh --update` first, or `rb-node config check`) |

When `rb agent` or `rb setup` cannot start an agent it prints one of: `no usable runtime directory for an ssh-agent socket` (no `/run/user/<uid>`; log in directly instead of through `su`), `<path> exists and is not a dead socket owned by you`, or `ssh-agent did not start (...)`.

**Keys not in the agent after a reboot.** Sessions get `no_agent`, `agent_empty` or `key_not_loaded`. Run `rb agent` in a hub terminal; no session restart is needed. If `rb doctor` warns `agent_location`, the key is only in an agent outside `$XDG_RUNTIME_DIR` (for example one forwarded by your own SSH login), which the timer cannot use; run `rb agent`.

**The node refuses the key** (`node_refused_key`). On the node console, `rb-node doctor` checks the `authorized_keys` lines (present, restricted, `from=` set, no duplicate). If the lines are right, `from=` probably holds an address other than the one the node sees, for example when a router translates addresses. Log in to the node from the hub with your own account and run `echo $SSH_CLIENT`; the first field is the address the node sees. Then run `rb setup --node node1 --hub-from ADDR` on the hub and paste the printed node command again: it replaces the line for the same key, after a backup.

**The node runs without a withheld pattern file.** The hub page shows a banner, and `rb doctor` reports `node_withheld` (`no node pattern file: five fallback patterns only`, or `node reports 0 extra patterns` for old node code); only the five built-in patterns are applied on the node. Do not use `read_doc`, `send_message` or `poll` until this is fixed. Copy the file as in step 4, then on the node console run `scripts/node-install.sh --withheld-file ~/withheld-patterns.json` (replacing a different file asks `y`; node code before 0.2.0 has no such flag, so run `scripts/node-install.sh --update` first). `rb doctor --node node1` then reports `node loaded N pattern(s)`. A missing or empty hub file is the `withheld_hub` fail; see step 2.

## Using it for another research project

A node serves one research project today: its root, readable directories, queue, `job_template` and pattern file are `node.json` keys set with `rb-node config set` on the node console. To describe a new project, copy [docs/projects/TEMPLATE.md](docs/projects/TEMPLATE.md) to `docs/projects/<name>.md`; [docs/projects/trm.md](docs/projects/trm.md) is the first one. A second node is linked by running `rb setup --node NAME ...` again; each node has its own keys and aliases. Several projects on one node, and experiment requests with result records, are designed but not built: [project profiles](docs/design/2026-11-10-project-profiles.md), [experiment records](docs/design/2026-11-10-experiment-records.md).

## Documentation

| Topic | Where |
|---|---|
| Current state and the next action | [docs/HANDOFF.md](docs/HANDOFF.md) |
| Open issues, triaged | [docs/issues/2026-11-10-triage.md](docs/issues/2026-11-10-triage.md) |
| Rules for Claude sessions in this repository | [AGENTS.md](AGENTS.md) |
| Reference manuals per role (English and 국문) | [docs/manual/](docs/manual/README.md) |
| Designs: index, setup and diagnosis, sync and hub page | [docs/design/](docs/design/README.md), [setup](docs/design/2026-11-10-setup-and-diagnosis.md), [sync and page](docs/design/2026-11-10-sync-and-hub-page.md) |
| Research projects served by nodes | [docs/projects/](docs/projects/TEMPLATE.md) |
| The laptop's 8765 dashboard | [docs/session-dashboard.md](docs/session-dashboard.md) |
| Branches, commits, tests (`uv run --extra host pytest -q`), what must never be published | [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) |

Real host names, addresses, ports and user names never go into tracked files. Use the placeholders (`node1`, `<NODE_HOST>`, `<NODE_PORT>`, `<NODE_USER>`, `<HUB_HOST>`, `<HUB_ADDR>`) and keep real values in the gitignored `private/` directory.
