# Hub setup

The hub runs `rb_host`: the MCP server (Model Context Protocol, the interface Claude sessions use to call tools), the `rb` command, the ledger and the stored messages. Since 2026-11-05 the hub is a Linux server (user decision, §12). The laptop is no longer the hub; the vault and its 8765 dashboard exist only on the laptop. Everything in this manual runs on the hub unless a step says otherwise. Windows and laptop-hub instructions are collected in Appendix A and are not maintained. For the node side see [node-setup.md](node-setup.md); for the roles see [README.md](README.md).

## How to read this manual

- **Who runs a command.** "Hub terminal" means a terminal the user has open on the hub. Commands that ask a question (`y/N`, a passphrase) refuse to run without a terminal (stdin and stdout must both be a terminal), so a Claude session cannot run them. A session may run the forms marked "session-safe": `rb setup --yes-print-only`, `rb doctor --offline`, `rb service install --print`, `rb config path`, `rb config show`, `rb config check`, `rb config mcp`, `rb board show`. The other `rb config` forms (`init`, `add-node`, `remove-node`, `set`, `local`) write `host.json` or `private/local.json` without asking, and `rb web serve` starts a process, so a session needs your go-ahead for them (`AGENTS.md`, "Ask the user before"); `rb doctor` without `--offline` and `rb sync` contact the node and need it too.
- **How `rb` is run.** The runtime is managed by uv. In this manual `rb ...` stands for `uv run --extra host rb ...` run in the main checkout (or `.venv/bin/rb ...`). A session prefixes shell commands with `rtk`; people type the plain command.
- **Placeholders.** `node1` is the node name used in examples. `<NODE_HOST>`, `<NODE_PORT>`, `<NODE_USER>` are the node's address, SSH port and login name. `<HUB_ADDR>` is the hub's address as the node sees it; `<HUB_SUBNET>` is the hub's network range; `<HUB_HOST>` is a name by which you log in to the hub from the laptop. The full list is in `docs/manual/README.md`. Real values go only in files that git ignores.
- **Abbreviations.** SSH = Secure Shell. MCP = Model Context Protocol. TOFU = trust on first use (accepting a host key the first time it is seen). systemd = the Linux service manager; "user units" run under your account.

### Order of a first setup

| Step | Where | What | Section |
|---|---|---|---|
| 1 | hub | Install, run the tests | §1, §2 |
| 2 | hub | `rb setup --node node1 --host <NODE_HOST> --port <NODE_PORT> --user <NODE_USER>`: config, keys, SSH blocks, agent; it prints the node command and the MCP command | §4 |
| 3 | node console | Run the printed `scripts/node-install.sh ...`, then `rb-node approve-key set` | [node-setup.md](node-setup.md) §2, §4 |
| 4 | hub | `rb setup --node node1` again: host key comparison | §4 |
| 5 | hub | Run the printed `claude mcp add-json ...`, start a new Claude session | §6 |
| 6 | hub | `rb doctor` | §10 |
| 7 | hub | `rb service install`, then the printed `systemctl` commands | §13, §14 |

## 1. Requirements

- Linux with a systemd user manager (for the timer and the page; §13) and a runtime directory `/run/user/<uid>` of mode 700 (created by a normal login session).
- Python 3.10 or later; the `--python '>=3.10'` option of the install command makes uv select it (3.12 on the first Linux hub). Without the option uv can pick an older Python that comes first on `PATH`, and the command then fails. The `mcp` package, version 1.27 or later and below 2, is installed by that command.
- uv, git, and the OpenSSH client tools: `ssh`, `ssh-keygen`, `ssh-keyscan`, `ssh-agent`, `ssh-add`. `ip` (from iproute2) is used once to guess the hub address; `loginctl` and `systemctl` are used for the units.
- The Claude Code CLI (`claude`), only to register the MCP server (§6). `rb` itself never edits `~/.claude.json`.
- Network: the hub opens SSH connections to the node (hub to node only). The node never connects to the hub.

## 2. Install

In the main checkout of the repository (not in a git worktree, because a worktree is deleted later and the MCP entry and the unit files would point at a missing path):

    uv sync --extra host --python '>=3.10'
    uv run --extra host pytest -q

Do not use `python -m venv` or `pip`. The tests start a local subprocess as the node and never contact a real node; the dashboard and bridge-edge tests use the repository's `vault-export/` copies, so the vault is not needed.

## 3. Data directory and config files

The data root holds everything the hub stores. It is outside the repository and outside any cloud-synced folder.

| Path under the data root | Content | Written by |
|---|---|---|
| `host.json` | node list and options (§5, §16); mode 600 | `rb setup`, `rb config` |
| `ledger.jsonl` | one record per message, event and job | MCP server, `rb`, `rb sync` |
| `inbox/<node>/<msg_id>/` | stored node messages: `body.txt`, `provenance.json`, attachments | `poll`, `rb sync` |
| `outbox/<node>/<msg_id>/` | masked copy of each sent body, plus name, size and hash of each attachment (the files are not copied) | `send_message` |
| `quarantine/<node>/` | files that failed the hub-side withheld re-check | `poll`, `rb sync` |
| `fetched/<node>/` | files from `fetch_file` | `fetch_file` |
| `sync/<node>.json` | status of the last sync pass (§13.2); mode 600 | `rb sync` |
| `board/` | unified board cache | `rb board refresh`, `rb sync` |
| `share/` | shared status page snapshot | `rb share build` |
| `harness-staging/<stamp>/` | harness pulls (§8) | `rb harness pull` |
| `withheld_patterns.json` | hub copy of the withheld patterns (§3.1) | you copy it |

Where the data root is: the `RB_HOST_ROOT` environment variable if set, otherwise `~/.local/share/research-bridge`. `RB_HOST_CONFIG` overrides the path of `host.json` alone. The `data_root` key in `host.json` sets where everything else is stored; `rb config init --data-root DIR` writes it. Create the directory with mode 700 (`rb setup` does this).

`private/local.json` in the checkout (gitignored) holds `laptop_home` and `node_home` for the harness path mapping only (§8); `rb config local --laptop-home DIR --node-home DIR` writes it. Nothing else needs it.

### 3.1 Withheld pattern file on the hub

The hub re-checks everything it stores against the five built-in fallback patterns (`AGENTS.md` hard rule 3) and, if present, a pattern file. There is no vault on this hub, so the file is a copy of the session-calendar export. Put it at `<data root>/withheld_patterns.json` (underscore in the name) or point `withheld_patterns_file` in `host.json` at it.

Format: JSON, one of: a list of regular-expression strings; `{"patterns": [...]}`; `{"families": [{"patterns": [...]}, ...]}`. YAML is not read, and `exp_id_patterns` keys are ignored. Example with an invented pattern: `{"patterns": ["secretproject_[0-9]+"]}`. A file that cannot be read, is not valid JSON, has no pattern, or holds a pattern that does not compile makes `rb doctor` report `withheld_hub` as `fail`, and the hub then applies only the five built-in patterns. The node has its own copy with a different name (`withheld-patterns.json`, hyphen; node manual §4.3).

## 4. Link a node: `rb setup`

`rb setup --node NAME` does in one command what used to take several documents: it creates the config, the two keys, the SSH blocks and the known-hosts entry, loads the keys into an agent, and prints the two commands you must run yourself (the node command and the MCP command). It is idempotent: every step is skipped when already satisfied, so you can rerun it at any time.

    rb setup --node node1 --host <NODE_HOST> --port <NODE_PORT> --user <NODE_USER>

| Flag | Meaning |
|---|---|
| `--node NAME` | Required. Node name: letters, digits, `_`, `-`, at most 32, first character a letter or digit. |
| `--host`, `--user` | Required on the first run. Later runs read them back from `ssh -G rb-NAME` (the block step 4 wrote). |
| `--port` | SSH port; default 22 (or the port in an existing block). |
| `--keydir DIR` | Where the keys are (default `~/.ssh/research-bridge`). Refused if the directory is inside a git work tree that does not ignore it. |
| `--hub-from ADDR` | The address the node sees this hub as; goes into the printed node command. Default: the source address of `ip -o route get <NODE_HOST>`. Give it explicitly if a router translates addresses between the machines. |
| `--research-root DIR` | The research tree on the node; only copied into the printed node command, stored nowhere on the hub. |
| `--yes-print-only` | Show every change and every command; write nothing, ask nothing, scan nothing, make no network traffic (session-safe). Despite the name it confirms nothing. |

Without `--yes-print-only` a terminal is required, because steps 3 to 6 ask questions.

### 4.1 What the nine steps do

| # | Step | Reads | Writes | Asks |
|---|---|---|---|---|
| 1 | Data root and `host.json` | `RB_HOST_ROOT`, `RB_HOST_CONFIG`, `host.json` | The data root (mode 700) and `host.json` (mode 600, refused if git would track it) | Nothing. An existing `host.json` that is not valid JSON stops setup. |
| 2 | Node entry | `host.json` | `nodes.NAME = {alias: rb-NAME, harness_alias: rb-NAME-harness}` | Nothing. An existing entry with other aliases is kept and its aliases are used. |
| 3 | Two keys | `<keydir>/NAME_ed25519{,.pub}`, `<keydir>/NAME_harness_ed25519{,.pub}` | The missing pairs by `ssh-keygen -t ed25519`, comments `research-bridge-hub` and `research-bridge-harness`; directory mode 700 | `Generate ...? [y/N]`, then `ssh-keygen` asks for a passphrase twice per key (the same passphrase may be used for both). A private key without `.pub` is reported, not repaired. |
| 4 | SSH blocks | `ssh -G` for both aliases | Appends the two `Host` blocks to `~/.ssh/config` after a backup `config.bak.<stamp>` | Shows the blocks, then `Append to ...? [y/N]`. If an alias is already defined, nothing is appended; setup lists each differing option and prints the expected block for you to merge. A symbolic-link target, or a file git would track, is never written: the text is printed instead. |
| 5 | Host key | `ssh -G`, `known_hosts` | Appends the scanned host key lines (`ssh-keyscan` tries `ed25519`, then `ecdsa`, then `rsa`, and keeps the first type that answers) to the first known-hosts file after a backup | Only when the node command has already been run: scans once with `ssh-keyscan`, shows the fingerprint, asks `... Does the fingerprint equal the node's? Append to ...? [y/N]`. In the run that generated keys it scans nothing and tells you to rerun after the node command. |
| 6 | Agent and keys | Agent sockets in `$XDG_RUNTIME_DIR` only (§4.3) | Starts an agent at `$XDG_RUNTIME_DIR/rb-ssh-agent` if none answers; `ssh-add` for each key not yet listed | `ssh-add` asks each passphrase. |
| 7 | Node command | Both `.pub` files, `--hub-from` or `ip route get`, the hub withheld file, the checkout's `origin` URL | Nothing | Nothing. Prints the `scripts/node-install.sh ...` command with both public keys inline, `--hub-from`, `--withheld-file` (only if the hub pattern file exists) and `--research-root` (only if given). |
| 8 | MCP registration | `~/.claude.json` (read only), `uv` on `PATH`, the checkout path | Nothing | Nothing. Prints `claude mcp add-json --scope user research-bridge '<json>'` unless an equal entry exists (§6). |
| 9 | Doctor | as `rb doctor --node NAME` (offline only with `--yes-print-only`) | Nothing | Nothing. Until the node command has run, the online part is expected to fail. |

Each step ends with `-> done`, `-> skipped`, `-> printed` or `-> failed: <reason>`. A failure in step 1 or 2 stops setup; a failure in 3 to 8 is reported at the end (`setup did not finish: ...`, exit 1) and the other steps still run. The exit code does not reflect the step 9 doctor result; run `rb doctor` for that.

### 4.2 The two-pass first run

1. Hub terminal: `rb setup --node node1 --host <NODE_HOST> --port <NODE_PORT> --user <NODE_USER>`. Steps 1 to 4 and 6 run; step 5 is deferred; step 7 prints the node command.
2. Copy the hub withheld pattern file to `~/withheld-patterns.json` on the node (`scp`, hub to node). If `known_hosts` has no entry for the node yet, `scp` asks its own yes/no question and writes the entry, and step 5 of `rb setup` then skips its comparison (it finds the entry). Before you answer `yes`, compare the fingerprint `scp` shows with `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` on the node console; answer `no` if they differ. Then run the printed command on the node console in a checkout of this repository (node manual §2). At its end it prints the node's host key fingerprints.
3. Hub terminal: `rb setup --node node1`. Step 5 now shows the fingerprint it scanned. Answer `y` only if it equals the line of the same type that the node printed. If they differ, do not connect; check on the node console with `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` and find the cause first.
4. Run the MCP command from step 8 (§6).

### 4.3 Which agent `rb` uses

Two rules, deliberately different.

- **Loading keys** (`rb setup` step 6, `rb agent`): only a socket under your runtime directory is used, tried in the order `$XDG_RUNTIME_DIR/gcr/ssh` (the desktop keyring agent), `openssh_agent`, `rb-ssh-agent`, then `$SSH_AUTH_SOCK` if it lies in that directory. If none answers, `rb` starts `ssh-agent -a $XDG_RUNTIME_DIR/rb-ssh-agent`. A key is never added to an inherited agent outside that directory (for example a forwarded agent), so unattended sync can use it later.
- **Connecting** (MCP server, `rb sync`, `rb doctor`): `$SSH_AUTH_SOCK` first, then the same three runtime-directory sockets; among the sockets that answer, the one that holds the key of that alias wins. A found socket is remembered for 30 seconds. Because of this the MCP entry needs no `SSH_AUTH_SOCK`, and a changed agent needs no session restart.

After a reboot the agent is empty: run `rb agent` in a hub terminal (§4.4).

### 4.4 `rb agent`

    rb agent [--node NAME]

Hub terminal only. Reads the key file names from `ssh -G` of each node's two aliases in `host.json` (all nodes, or `--node`), loads the ones not yet in the agent (asks each passphrase), prints the agent socket path and `export SSH_AUTH_SOCK=...` for other shells (needed only for `rb harness`). A missing harness block is a note, not an error. Exit 1 if a bridge key file is missing, an `ssh-add` fails, or no agent can be reached.

### 4.5 By hand

<details>
<summary>By hand: keys, SSH blocks, host key, agent</summary>

Use this only if `rb setup` cannot run (for example its output does not suit a custom `~/.ssh/config`).

Keys, two per node, each with a passphrase; the private keys never leave the hub:

    mkdir -p ~/.ssh/research-bridge && chmod 700 ~/.ssh/research-bridge
    ssh-keygen -t ed25519 -f ~/.ssh/research-bridge/node1_ed25519 -C research-bridge-hub
    ssh-keygen -t ed25519 -f ~/.ssh/research-bridge/node1_harness_ed25519 -C research-bridge-harness

Add to `~/.ssh/config` (this is exactly what step 4 writes):

```
Host rb-node1
    HostName <NODE_HOST>
    Port <NODE_PORT>
    User <NODE_USER>
    IdentityFile ~/.ssh/research-bridge/node1_ed25519
    IdentitiesOnly yes
    StrictHostKeyChecking yes
    ServerAliveInterval 15
    ServerAliveCountMax 3

Host rb-node1-harness
    HostName <NODE_HOST>
    Port <NODE_PORT>
    User <NODE_USER>
    IdentityFile ~/.ssh/research-bridge/node1_harness_ed25519
    IdentitiesOnly yes
    StrictHostKeyChecking yes
    ServerAliveInterval 15
    ServerAliveCountMax 3
```

- `IdentitiesOnly yes` stops the agent from offering any other key.
- `StrictHostKeyChecking yes` refuses an unknown or changed host key, so the node's key must be in `known_hosts` first.

Host key (trust on first use done safely): scan, print the fingerprint, compare it with the one printed on the node console, and only then append:

    ssh-keyscan -t ed25519 -p <NODE_PORT> <NODE_HOST> > /tmp/node1.hostkey
    ssh-keygen -lf /tmp/node1.hostkey
    # compare with: ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub  (on the node console)
    cat /tmp/node1.hostkey >> ~/.ssh/known_hosts

If `HashKnownHosts yes` is set, add `-H` to `ssh-keyscan`.

Agent:

    ssh-agent -a "$XDG_RUNTIME_DIR/rb-ssh-agent"      # only if no agent answers
    SSH_AUTH_SOCK="$XDG_RUNTIME_DIR/rb-ssh-agent" ssh-add ~/.ssh/research-bridge/node1_ed25519 ~/.ssh/research-bridge/node1_harness_ed25519

The `authorized_keys` lines on the node are written by `scripts/node-install.sh`; the by-hand form is in node manual §5.

</details>

## 5. `host.json`

`rb setup` creates and fills `host.json` (steps 1 and 2). Edit it with `rb config`, not by hand, where a command exists (§15). The JSON of the usual case:

```json
{"nodes": {"node1": {"alias": "rb-node1", "harness_alias": "rb-node1-harness"}}}
```

Only the aliases in this file are used: the hub never connects to a host name given in a tool argument. All keys are in §16.1. Optional parts:

- **Unified board** (`rb board refresh|show`, and the board part of every sync pass). Node paths per node, relative to the node's research root and inside one of the node's `read_roots`: `nodes.node1.board.state|events|kanban` (`rb config set nodes.node1.board.state PATH`). A path left out is recorded as `no_path`. A `.jsonl` file is refused by the node (`deny_unscannable`), so the events source needs a `.json` export. Sources on the laptop (`board.portfolio`, `board.priorities`) point at local copies of laptop files; without them those two board rows show as missing on this hub.
- **Shared status page** (`rb share`): `share.calendar_sessions|calendar_status|runs` set by `rb config set`; `share.labels` (a list of allowed project and track labels) has no command and is added to `host.json` by hand; without it every label shows as `other`.

Without a usable `host.json`, every `rb` command that needs it prints one line, `error: no usable host.json at <path>; run: rb setup --node NAME --host HOST --user USER`, and exits 1.

## 6. Register the MCP server for Claude sessions

`rb setup` step 8 prints the command; run it yourself in a hub terminal from the main checkout (`rb` never edits `~/.claude.json`):

    claude mcp add-json --scope user research-bridge '{"type": "stdio", "command": "/usr/bin/uv", "args": ["run", "--directory", "/path/to/research-bridge", "--extra", "host", "python", "-m", "rb_host.server"], "env": {"RB_HOST_CONFIG": "/path/to/host.json"}}'

The real command carries your paths. `env` always has `RB_HOST_CONFIG` (absolute path of `host.json`) and has `RB_HOST_ROOT` only if the shell that ran `rb setup` had it set; run `rb setup` or `rb config mcp` in the same shell setting you use daily. The entry has no `SSH_AUTH_SOCK` (§4.3). An older entry that has one still works.

`rb config mcp` prints the same entry as the `claude mcp add-json ...` command. `rb doctor` check `mcp_entry` warns if the registered entry is missing, points at a missing path or a worktree, or differs from the one `rb setup` prints; remove it (`claude mcp remove research-bridge`) and register again. It also warns (`from_worktree`) when this `rb` runs from a git worktree and the registered entry differs only in the checkout path; the next step is to run `rb` from the main checkout.

A new Claude session then has exactly ten tools: `nodes`, `send_message`, `poll`, `thread`, `read_doc`, `fetch_file`, `queue_status`, `gpu_status`, `submit_job`, `cancel_job`. A test pins this set. There is no approval tool: `submit_job` and `cancel_job` only write a `pending_approval` record and make no SSH call.

- `nodes` also returns, per node, the last sync result: `synced`, `ok`, `error`, `stage`, `last_attempt_at`, `last_ok_at`, `age_s`, `stale` (no successful pass in 900 s), `node_seen_at`, `node_version`, `protocol`, `withheld_extra`, `undelivered`.
- `poll` returns each node item once. Items that `rb sync` stored earlier are included with `stored: true`, and a node that cannot be reached still yields its stored items.
- `send_message` keeps a masked copy of the body in `outbox/` (§3); `thread` returns `has_body` and `stored_dir` for each record so a session can read the stored body.

## 7. Approving jobs

Approval happens only outside Claude, in a hub terminal:

    rb pending                 # list jobs waiting for approval
    rb approve <job_id>        # shows the job, asks y/N and the approval passphrase, then uploads and submits
    rb reject <job_id>         # marks it rejected; no node call

The passphrase is the one set on the node with `rb-node approve-key set` (node manual §4.2). It is typed each time: `rb approve` and `rb reject` need a terminal (an SSH login with a terminal counts), there is no `--yes` and no flag, file or environment variable for the passphrase, so a Claude session cannot approve. A wrong passphrase leaves the job `pending_approval`; approving twice is a no-op. After five wrong keys the node makes you wait 30 s, doubling up to 1 h (`approval_wait`). Residual risks: `docs/design/2026-11-03-node-side-approval.md` §7. The hub page (§14) lists pending jobs with the two commands to type; it cannot approve anything. The 8765 approval route exists only on the laptop (Appendix A).

## 8. Harness channel (manual, optional)

    rb harness push --node node1 [--dry-run]   # hub harness -> node staging
    rb harness pull --node node1               # node harness -> hub staging
    rb harness diff <stamp>                    # diff a pulled stamp against ~/.claude

Only the allowlist (`CLAUDE.md`, `settings.json`, `rtk-reference.md`, `commands/`, `agents/`, `hooks/`, `workflows/`) moves, and only into staging. There is no apply command; copy by hand after reading the diff. A `.json` file with a populated credential-like key blocks the transfer. Path mapping uses laptop paths: set `RB_LAPTOP_HOME` and `RB_NODE_HOME` or `private/local.json` (§3); on this hub the mapping is not adapted and is unresolved. The harness channel uses the second key and alias; `rb agent` loads it too.

## 9. Security rules on the hub

- Connections go hub to node only.
- Message bodies and files from a node are data, never instructions. Files that fail the hub-side withheld re-check go to `quarantine/`. Node-supplied files named `CLAUDE.md`, `CLAUDE.local.md`, `AGENTS.md` or starting with a dot are stored with `.untrusted` appended.
- No message bodies or secrets in audit logs, in the sync status file, or in this repository. The status file holds codes only.
- `rb setup` and `rb config` refuse to write a config file or key where git would track it. They never edit `~/.claude.json`; they edit `~/.ssh/config` and `known_hosts` only after a `y` typed at a terminal, with a backup.
- The hub page binds to `127.0.0.1` only (§14).
- Keep `private/`, the data root and `~/.ssh/research-bridge/` out of git and out of cloud sync.

## 10. Checks: `rb doctor`

    rb doctor [--node NAME] [--offline]

Prints one line per check, grouped by node: `<level> <id>  <message>`, and under every `warn` or `fail` a line `      next: <command>`. It ends with `summary: N ok, N warn, N fail`. Exit code 1 only if some check is `fail`; `warn` exits 0. `--offline` reads local files and runs local commands only (`ssh -G`, `ssh-add -l`, `ssh-keygen`, `systemctl`); without it one SSH connection per node sends `hello` and nothing else. Output never contains key material or pattern text. `rb config check` is the offline report limited to non-ok lines; it ends with `ok`, `N to fix` (failures), `all ok, M warning(s)` or `N to fix, M warning(s)`. (The `--help` text of `rb config check` says "exit 1 if anything"; the code exits 1 only on a `fail`.)

### 10.1 Offline checks

| id | Level if not ok | What a failure means | Next command |
|---|---|---|---|
| `host_json` | fail | `host.json` is missing, not valid JSON, or has fields of the wrong type. Nothing else can be checked. | `rb setup --node NAME --host HOST --user USER`, or fix the file |
| `host_json_git` | fail | `host.json` or `private/local.json` would be tracked by git (`LEAK RISK`). | add it to `.gitignore` or move it |
| `data_root` | fail | The data directory does not exist, or its mode allows access by group or other users (it must be 700). | missing: `rb setup --node NAME ...`; mode: `chmod 700 <path>` |
| `nodes` | fail | No node in `host.json`, or `--node` names an unknown one. | `rb setup --node NAME ...` |
| `alias` | fail | `ssh -G` shows no `Host` block for the node's bridge alias. | `rb setup --node NAME ...` |
| `alias_harness` | warn | Same for the harness alias; only the harness channel is affected. | same |
| `ssh_options` | warn | An alias lacks `IdentitiesOnly yes` or `StrictHostKeyChecking yes`, so other keys might be offered or an unknown host key accepted. | `rb setup --node NAME` |
| `key_file` | fail | No `IdentityFile` named like a key `rb setup` generates is configured for the alias (`no bridge IdentityFile configured for <alias>`), or the bridge key file is missing, readable by group or others (mode), or has no `.pub`. | `rb setup --node NAME` / `chmod 600 KEY` / `ssh-keygen -y -f KEY > KEY.pub` |
| `key_file_harness` | warn | Same for the harness key. | same |
| `agent` | fail if some bridge key has a passphrase, else warn | No agent socket answers. | `rb agent` |
| `key_loaded` | fail | The bridge key is not in the agent (a key without a passphrase counts as loaded). | `rb agent --node NAME` |
| `key_loaded_harness` | warn | Same for the harness key. | same |
| `agent_location` | warn | The key is only in an agent outside `$XDG_RUNTIME_DIR` (for example a forwarded agent); the timer and other shells cannot use it. | `rb agent --node NAME` |
| `known_host` | fail | `known_hosts` has no entry for the node, so the strict SSH option refuses to connect. | `rb setup --node NAME` |
| `withheld_hub` | fail | The hub pattern file is missing, not valid JSON, empty, or has patterns that do not compile (indexes are listed). Only the five built-in patterns apply. | copy the pattern file to the path shown (§3.1) |
| `mcp_entry` | warn | The MCP server is not registered, points at a missing path or a worktree, or differs from the entry `rb setup` prints. Also `from_worktree`: this `rb` runs from a git worktree and the entry differs only in its checkout path. | the `claude mcp add-json ...` command shown; for `from_worktree`, `run rb from the main checkout` |
| `local_json` | warn | `private/local.json` is missing; only the harness path mapping needs it. | `rb config local --laptop-home ... --node-home ...` |
| `service_sync` | warn | The sync timer is not installed or not active, or the systemd user manager is unavailable. | `rb service install` / `systemctl --user enable --now rb-sync.timer` |
| `service_web` | warn | The page service is not installed or not active. | `rb service install` / `systemctl --user enable --now rb-web.service` |
| `linger` | warn | Reported only if a unit is installed: user units stop when you log out. | `loginctl enable-linger <user>` (may need an administrator) |
| `sync_status` | warn | Reported only if `sync/<node>.json` exists: no successful pass in the last 900 s, with the error code of the last attempt; or `a sync pass started N ago and never finished` (a pass recorded as running for more than 900 s). | `rb sync --node NAME` |

### 10.2 Online checks (one `hello` per node)

| id | Level if not ok | What a failure means | Next command |
|---|---|---|---|
| `reachable` | fail | The connection or `hello` failed. The message is one of the codes in §10.3, or `node reachable but not configured` (the node has no valid `node.json`). | the hint shown; for an unconfigured node, on the node: `rb-node doctor` |
| `node_version` | warn | The node runs another version than the hub, or code before protocol 2. | on the node: `scripts/node-install.sh --update` |
| `node_withheld` | fail (protocol 2) when a pattern file is set but loaded no pattern or has patterns that do not compile; warn when no file is set or the node is old | The node applies only the five built-in patterns, or its file is broken. An old node (protocol 1) counts patterns before compiling, so it is never better than warn. | on the node: `rb-node doctor` |
| `node_approval` | fail (protocol 2), warn (old node) | No approval verifier on the node: every `job_submit` and `job_cancel` is refused with `not_authorized`. | on the node: `rb-node approve-key set` |
| `node_job_template` | warn | `job_template` is empty or lacks a config placeholder (`{config}`, `{config_dir}` or `{config_stem}`): jobs are refused with `no_job_template`. | on the node: `rb-node config set job_template '[...,"{config}"]'` |
| `node_allowed_gpus` | warn | `allowed_gpus` is empty on the node: jobs are refused with `no_allowed_gpus`. | on the node: `rb-node config set allowed_gpus '[4, 5, 6, 7]'` (your own GPU indices) |
| `node_responder` | warn | `claude_bin` is not an executable on the node: messages wait for a live session. | on the node: `rb-node doctor` |
| `node_queue` | warn | The queue directory is missing on the node. | on the node: `rb-node doctor` |

For an old node the hint for these rows is "scripts/node-install.sh --update, then rb-node doctor", because code before 0.2.0 has no `doctor`. A value the node did not report shows as `unknown` with level warn.

### 10.3 Connection errors

A failed SSH connection is reported as `<message> (next: <command>)`; the code is also what `rb sync` records in the status file.

| Code | Message | Cause | Next |
|---|---|---|---|
| `no_agent` | no ssh-agent reachable for ALIAS | No agent socket answers, and the key has a passphrase. | `rb agent` |
| `agent_empty` | the ssh-agent holds no keys | The agent runs but is empty (after a reboot). | `rb agent` |
| `key_not_loaded` | the key for ALIAS is not in the ssh-agent | The agent has other keys but not this one. | `rb agent --node NAME` |
| `node_refused_key` | ALIAS refused the key | The key is loaded but the node rejected it: the `authorized_keys` line is missing, or its `from=` does not match the address the node sees (`--hub-from`; wrong if a router translates addresses). | on the node: `rb-node doctor` (checks `ak_bridge`) |
| `host_key_unknown` | no known_hosts entry for ALIAS | Host key not yet accepted. | `rb setup --node NAME` |
| `host_key_changed` | host key of ALIAS changed | The node's host key differs from the stored one. Do not connect; compare fingerprints on the node console. | `rb doctor --node NAME` |
| `unknown_alias` | ssh has no Host block for ALIAS | The SSH config lost the block. | `rb setup --node NAME --host HOST --user USER` |
| `unreachable` | cannot reach ALIAS (network or address) | Name does not resolve, connection refused, no route. | `rb doctor --node NAME` |
| `timeout` | ALIAS did not answer in time | No answer within 15 s of connecting or after three missed keepalives. | retry; if it repeats `rb doctor --node NAME` |
| `closed` | connection to ALIAS closed (exit N) | The node ended the session, for example the forced command crashed. | on the node: `rb-node doctor` |

## 11. Removing a node

    rb config remove-node node1

Then remove its two `Host` blocks from `~/.ssh/config`, delete its two keys, and ask the node's owner to delete the two `authorized_keys` lines. Keep the ledger; it is the record of what was exchanged.

## 12. Linux hub

From 2026-11-05 this Linux server is the hub (user decision). Platform facts:

- **Python:** 3.12 on the first Linux hub; the host side needs 3.10 or later. The node side stays compatible with 3.8.
- **Data root:** `RB_HOST_ROOT` if set, else `~/.local/share/research-bridge` (§3). The Windows default `D:/raw/research-bridge` applies only on Windows.
- **Keys:** `~/.ssh/research-bridge/` (directory mode 700, keys mode 600), unless `--keydir` says otherwise. Only a key file with the name `rb setup` generates (`<node>_ed25519` for the bridge alias, `<node>_harness_ed25519` for the harness alias) counts as a bridge key. An alias whose `IdentityFile` has any other name makes `rb setup` create keys at the default path, and `rb doctor` and `rb agent` report `no bridge IdentityFile configured for <alias>`.
- **Runtime directory:** agent sockets and the `rb-ssh-agent` live in `$XDG_RUNTIME_DIR` (normally `/run/user/<uid>`, mode 700). A shell without a login session may lack it; then `rb agent` stops with `no usable runtime directory for an ssh-agent socket`.
- **`from=` on the node:** the hub's own address or subnet (`<HUB_ADDR>`, `<HUB_SUBNET>`), never the laptop's.
- **Approval:** `rb approve` and `rb reject` in a hub terminal. The 8765 dashboard and its `/rb/approve` route are vault-side and are not installed here.
- **Not available here:** the `rb board` laptop sources (portfolio, priorities) unless `board.portfolio` and `board.priorities` point at local copies; the harness path mapping assumes laptop paths (§8).
- **Removed scripts:** `scripts/hub-connect.sh`, `scripts/hub-agent.sh` and `scripts/trm-link.sh` no longer exist. `rb setup` and `rb agent` replace the first two; `rb-node link` (node manual §10) replaces the third. A hub that was linked with the old scripts needs no re-linking: `rb setup --node NAME` finds the keys, blocks and known-hosts entry and only reports differences.

## 13. Unattended sync and the timer

### 13.1 `rb sync`

After updating the hub with `git pull` and `uv sync --extra host`, restart every Claude session on the hub before the first `rb sync` or before enabling `rb-sync.timer`: an MCP server process started on the old code has no claim step, so it never returns the items that the new `rb sync` stores as not yet delivered. Also make sure no other data root (for example the laptop's MCP server) polls the same node.

    rb sync [--node NAME] [--watch SECONDS]

One pass per node (all nodes, or `--node`), hub to node only; it never approves a job and never touches the harness channel. A pass opens one connection and sends `hello`, `poll` and `git_status`, closes it, then refreshes the board sources that are due (cache missing, last result not ok, or older than half the source's cadence: queue 600 s, gpu 600 s, state 3600 s, events 1800 s, kanban 3600 s). Fetched node messages are stored in `inbox/` and acknowledged on the node, and are marked not delivered, so the next MCP `poll` still returns them (with `stored: true`). Each pass prints one JSON line per node: `node`, `ok`, `error`, `stage`, `new_items`, `rejected`, `board`, `tree_head`, `tree_dirty`; exit 1 if any pass failed. `--watch SECONDS` repeats (minimum 30); Ctrl-C ends it with exit 0. Stderr gets `sync: <stage> failed: <ExceptionName>`, never message text.

### 13.2 Status file

`<data root>/sync/<node>.json` (mode 600, replaced atomically) holds: `schema`, `node`, `last_attempt_at`, `last_ok_at`, `ok`, `error` (a code or null), `stage` (where the last failure happened: `connect`, `hello`, `poll`, `git`, `board`; `running` while a pass is in progress), `new_items`, `rejected`, `board` (per source: `ok`, `skipped`, `no_path`, `gpu_status_unavailable`, `no_gpus`, `source_error`, or an error code), `node_version`, `protocol`, `withheld_extra`, `node_seen_at`, `tree_head`, `tree_dirty`, `git_error`, `duration_s`. A pass fails on a transport error, a poll error, or a board source error other than `no_path`, `gpu_status_unavailable` and `no_gpus`. The file is stale when `last_ok_at` is older than 900 s; the `nodes` tool, the page and `rb doctor` use that one rule. The hub reads the node's git state from the key `tree` and falls back to `trm`, which is what the current node sends.

### 13.3 `rb service`

    rb service install [--interval SECONDS] [--port PORT] [--print]
    rb service status

`install` (hub terminal; `--print` is session-safe) writes three systemd user units into `${XDG_CONFIG_HOME:-~/.config}/systemd/user/`, each after showing the text, a diff against an installed file, and a `y/N`; a replaced file is saved as `NAME.bak.<stamp>`. It never runs `systemctl` or `loginctl`; it prints the commands:

    systemctl --user daemon-reload && systemctl --user enable --now rb-sync.timer rb-web.service
    loginctl enable-linger <user>        # printed only if linger is off; may need an administrator

| Unit | Content |
|---|---|
| `rb-sync.service` | `Type=oneshot`; `ExecStart=<.venv/bin/rb> sync`; `TimeoutStartSec=240`; `NoNewPrivileges=yes`; `Environment=RB_HOST_CONFIG=<absolute host.json>`, plus `Environment=RB_HOST_ROOT=...` only if `RB_HOST_ROOT` was set in the shell that ran `install`; `ConditionPathExists=<host.json>` |
| `rb-sync.timer` | `OnActiveSec=60`, `OnUnitInactiveSec=<interval>` (default 300), `RandomizedDelaySec=20`, `AccuracySec=10s`; `WantedBy=timers.target` |
| `rb-web.service` | `Type=simple`; `ExecStart=<.venv/bin/rb> web serve --port <port> --bind 127.0.0.1` (default port 8767); `Restart=on-failure`, `RestartSec=5`; same environment lines; `WantedBy=default.target` |

No unit holds `SSH_AUTH_SOCK`, a key path or a passphrase. The unit finds the agent by the rules of §4.3, so after each reboot you must run `rb agent` in a hub terminal; until then every pass fails with `agent_empty` or `no_agent`. `install` refuses paths with a space or `%`, and warns when run from a worktree. `status` prints enabled and active state of the three units, the result of the last sync service run, and whether linger is on. Logs: `journalctl --user -u rb-sync.service -n 20`.

## 14. Hub page

`rb web serve [--port PORT] [--bind 127.0.0.1]` (default port 8767) serves a read-only page: conversations, job records, pending approvals and the sync state. A request reads files only; the page opens no node connection, starts no process and writes nothing. `--bind` accepts only `127.0.0.1`; any other value is refused with a message that names the SSH forward below. It is normally started by `rb-web.service` (§13.3). It changes no data, but starting it is not session-safe: a session needs the user's go-ahead (`AGENTS.md`).

| Route | Content | Refresh |
|---|---|---|
| `/` | node table, pending approvals, ten latest conversations | 30 s |
| `/threads` | all conversations (first 500) | 30 s |
| `/thread/<id>` | one conversation: every record with time, direction, status, body, attachments | 60 s |
| `/jobs` | job records by status, with `job_finished` events | 60 s |
| `/nodes` | status file and board sources per node | 60 s |
| `/healthz` | JSON `{"ok": true, "ledger_mtime_ns": ...}` | none |

Only `GET` and `HEAD` are answered (other methods get 405, unknown routes 404). The `Host` header must be `127.0.0.1:PORT`, `localhost:PORT` or `[::1]:PORT`, otherwise 403. The page carries no script, form or external resource. Every text from a record is masked again with the hub patterns; a banner appears if the pattern file is unusable or a node reports `withheld_extra` 0.

**From the laptop,** use an SSH local forward through your own login to the hub (not a bridge key; the node is not involved), with the same port on both sides:

    ssh -N -L 8767:127.0.0.1:8767 <HUB_HOST>

then open `http://localhost:8767/`. The browser's `Host` header carries the laptop-side port, so a forward to a different local port (for example one an editor chose automatically) gets 403 by design. Loopback is reachable by every account on the hub; on a hub with other accounts this page is readable by them.

## 15. Reference: `rb` commands

| Command | Terminal needed | Does |
|---|---|---|
| `rb setup --node NAME [--host H] [--port N] [--user U] [--keydir D] [--hub-from A] [--research-root D] [--yes-print-only]` | yes, unless `--yes-print-only` | §4 |
| `rb agent [--node NAME]` | yes | §4.4 |
| `rb doctor [--node NAME] [--offline]` | no | §10 |
| `rb service install [--interval S] [--port N] [--print]` | yes, unless `--print` | §13.3 |
| `rb service status` | no | §13.3 |
| `rb sync [--node NAME] [--watch SECONDS]` | no | §13.1 |
| `rb web serve [--port N] [--bind 127.0.0.1]` | no | §14 |
| `rb pending` | no | List jobs waiting for approval. |
| `rb approve JOB_ID` | yes | §7 |
| `rb reject JOB_ID` | yes | §7 |
| `rb harness push --node N [--dry-run]`, `pull --node N`, `diff STAMP` | no | §8 |
| `rb board refresh [--node N] [--source queue\|gpu\|state\|events\|kanban]` | no | Fetch board sources through the bridge into the cache. |
| `rb board show [--json]` | no | Print the board from the cache; opens no connection. |
| `rb git-status [--node N]` | no | Print the node's git state (research tree and installed code) as JSON. |
| `rb share build [--days N] [--tier shared\|owner]` | no | Write `share/snapshot.json` and `index.html` from local caches; exit 1 if the withheld re-check dropped items. |
| `rb share serve [--port 8766] [--bind 127.0.0.1]` | no | Serve the `share/` directory read-only. |
| `rb config path` | no | Print where `host.json` and `private/local.json` are. |
| `rb config init [--data-root D] [--force]` | no | Create `host.json` (mode 600). |
| `rb config add-node NAME [--alias A] [--harness-alias A] [--force]` | no | Register a node (default aliases `rb-NAME`, `rb-NAME-harness`). |
| `rb config remove-node NAME` | no | Delete a node entry. |
| `rb config set KEY VALUE` | no | Set one key (§16.1). |
| `rb config local [--laptop-home D] [--node-home D]` | no | Write `private/local.json`. |
| `rb config show` | no | Print both config files. |
| `rb config mcp` | no | Print the MCP entry (§6). |
| `rb config check` | no | Offline `rb doctor`, non-ok lines only. |

`rb-host-mcp` (and `python -m rb_host.server`) starts the MCP server; Claude starts it from the registered entry.

## 16. Reference: configuration

### 16.1 `host.json`

Unknown top-level keys are ignored.

| Key | Meaning | Default | Set by |
|---|---|---|---|
| `nodes` | Object: node name to its entry. | `{}` | `rb setup`, `rb config add-node` |
| `nodes.NAME.alias` | SSH alias of the bridge key. | `rb-NAME` | `rb config set nodes.NAME.alias V` |
| `nodes.NAME.harness_alias` | SSH alias of the harness key. | `rb-NAME-harness` | `rb config set nodes.NAME.harness_alias V` |
| `nodes.NAME.board.state`, `.events`, `.kanban` | Node paths for the board sources, relative to the node's research root and inside a node read root. | none (`no_path`) | `rb config set nodes.NAME.board.state V` (likewise the others) |
| `data_root` | Where the hub stores everything (§3). | `RB_HOST_ROOT`, else `~/.local/share/research-bridge` | `rb config set data_root V`, `rb config init --data-root` |
| `withheld_patterns_file` | Hub withheld pattern file (§3.1). | `<data_root>/withheld_patterns.json` | `rb config set withheld_patterns_file V` |
| `board.portfolio`, `board.priorities` | Laptop files for the paper kanban and the priorities board. | none | `rb config set board.portfolio V` |
| `share.calendar_sessions`, `.calendar_status`, `.runs` | Input files for `rb share`. | none | `rb config set share.calendar_sessions V` |
| `share.labels` | List of allowed project and track labels for `rb share`. | none (all `other`) | by hand |

### 16.2 Environment variables and other files

| Name | Meaning |
|---|---|
| `RB_HOST_ROOT` | Data root and directory of the default `host.json`. Copied into the MCP entry and the units if set when they are made. |
| `RB_HOST_CONFIG` | Path of `host.json` alone. Always copied into the MCP entry and the units. |
| `RB_LAPTOP_HOME`, `RB_NODE_HOME` | Override `laptop_home` and `node_home` of `private/local.json` (harness path mapping). |
| `XDG_RUNTIME_DIR` | Directory of the agent sockets (§4.3). |
| `XDG_CONFIG_HOME` | Base of the systemd user unit directory. |
| `SSH_AUTH_SOCK` | Tried first when connecting; used for loading only if it lies in `$XDG_RUNTIME_DIR`. |

## 17. Troubleshooting: messages from the node

Errors that come back from the node, as codes in tool results and in `rb approve` output.

| Code | Meaning | What to do |
|---|---|---|
| `not_authorized` | The node has no approval verifier, or the passphrase did not match. | On the node console: `rb-node approve-key set`; retype the passphrase. |
| `approval_wait` | Too many wrong passphrases. | Wait (30 s, doubling to 1 h), then try once. |
| `no_job_template` | `job_template` is not set on the node. | The node's owner: `rb-node config set job_template ...` (node manual §4.1). |
| `no_harness_root` | `harness_root` is not set on the node. | The node's owner sets it, or do not use the harness channel. |
| `denied` | The path is outside the node's read roots, or the file type is not scannable (`deny_unscannable`). | Check `read_roots` on the node; for events use a `.json` file. |
| `withheld` | `fetch_file` downloaded a file whose content matches a withheld pattern; the hub deleted it. | Nothing: this is the rule working. |
| `not_found` | No such document, or the id matches more than one file. | Check `experiments_dir` and `hypotheses_path` (node manual §4.1). |
| `not_configured` | The node has no valid `node.json`. | On the node: `rb-node doctor`. |
| `ledger_locked` | Another process held the ledger lock too long. | Retry. |
| `no usable host.json at ...` | `host.json` missing or invalid. | `rb setup --node NAME --host HOST --user USER`. |
| `LEAK RISK ...` | A config file would be tracked by git. | Add it to `.gitignore` or move it. |

## Appendix A. Windows or laptop hub (not maintained since 2026-11-05)

This appendix keeps the instructions of the first hub, the Windows laptop. They were last checked on 2026-11-05 and are not kept in step with the code. `rb setup`, `rb agent`, `rb doctor`, `rb service` and the timer were written for Linux and were not tried on Windows. Paths are examples.

- **Requirements:** Python 3.14 (tests ran there), the OpenSSH client and the "OpenSSH Authentication Agent" service set to start automatically, the repository at `D:/raw/Codes/research-bridge` (the 8765 dashboard imports `rb_host` from `RB_REPO` in `vault-export/dashboard/rb_pending.py`).
- **Data directory:** `D:/raw/research-bridge/` is the default on Windows when `RB_HOST_ROOT` is not set; keep it outside the vault and any cloud-synced folder. The default withheld pattern file is the session-calendar export `D:/raw/session-calendar/server/withheld_patterns.json`.
- **Keys:** `ssh-keygen -t ed25519 -f C:/keys/research-bridge/node1_ed25519 -C research-bridge-hub` and the same for the harness key; `ssh-add` both; the passphrase is entered once per logon. Use the `C:/keys/...` paths as `IdentityFile` in the blocks of §4.5. `from=` on the node is the laptop's subnet.
- **MCP entry** in `~/.claude.json` under `mcpServers`: `"research-bridge": {"type": "stdio", "command": "uv", "args": ["run", "--directory", "D:/raw/Codes/research-bridge", "--extra", "host", "python", "-m", "rb_host.server"]}`.
- **Approval** in PowerShell or Windows Terminal (redirected input and Git Bash's mintty are refused), or on `http://127.0.0.1:8765/rb/pending` (loopback only, per-process CSRF token, passphrase field). Install the dashboard route from `vault-export/` (see `vault-export/README.md`) and restart the 8765 dashboard; both need the user's go-ahead.
- **Checks:** `curl -s -o NUL -w "%{http_code}" http://127.0.0.1:8765/rb/pending` should print 200 and the same URL on the laptop's LAN address 403.
- **Tests:** `tests/test_rb_pending.py` and `tests/test_bridge_edges.py` use the repository's `vault-export/` copies; the vault is not needed.
