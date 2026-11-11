# Setup and diagnosis: one hub command, one node command — design

Date: 2026-11-10 · Status: draft · Author: session research-bridge-f6 (2026-11-10) · Code: `rb_host/sshenv.py` (new), `rb_host/client.py`, `rb_host/setup.py` (new), `rb_host/doctor.py` (new), `rb_host/service.py` (new), `rb_host/configure.py`, `rb_host/cli.py`, `rb_node/__init__.py`, `rb_node/remote.py`, `rb_node/cli.py`, `rb_node/config.py`, `rb_node/configure.py`, `rb_node/doctor.py` (new), `rb_node/install.py` (new), `rb_node/link.py` (new), `rb_node/local.py`, `rb_node/jobs.py`, `rb_node/mailbox.py`, `rb_node/spawn.py`, `rb_node/withheld.py`, `scripts/node-install.sh`, `deploy/*`; deleted: `scripts/hub-connect.sh`, `scripts/hub-agent.sh`, `scripts/trm-link.sh` · Data: hub `~/.ssh/config`, `~/.ssh/known_hosts`, `~/.ssh/research-bridge/`, `~/.config/systemd/user/rb-*`; node `~/.ssh/authorized_keys`, `~/.research-bridge/{node.json,withheld-patterns.json,install.json}`, `~/.local/share/research-bridge/`, `~/.local/bin/rb-node`

Status history:
- 2026-11-10 draft. Not shown to the user. Scope fixed by the coordinator contract of the 2026-11-10 review (sections 1.1, 1.2, 1.4), which the user has not approved either.
- 2026-11-10 independent audit (verdict: accept with fixes) applied: B1, B2, I1 to I13, M1 to M10. Changes that touch the contract (B1, B2's step order note, M2, M8) are marked "My call (user to check)" or listed in §12.
- 2026-11-10 coordinator rulings R1 to R9 and R13 (kept in the gitignored review working directory `.superpowers/review-2026-11-10/design/`, which this repository does not contain; §12 states each ruling) applied. They are listed in §12 as "My calls (user to check)" approved by the coordinator on 2026-11-10; the user has not approved them. Implementation on branch `claude/review-optimize-2026-11-10`.
- Line numbers such as `rb_host/client.py:106-107` quoted in this document are those of the code before this branch, unless a sentence says otherwise; after the build, those lines hold other code.
- 2026-11-10 implemented on branch claude/review-optimize-2026-11-10 (not merged); verification table updated. Text that the build made false is corrected in place, and each correction has a row in §13.
- 2026-11-11 merged to `main` on 2026-11-10 in PR 48 (merge commit c503667). The status stays draft until the user accepts the design.
- 2026-11-11 note: the survey files (`user-steps.md`, `code-host.md`), the contract and the briefs (`brief-node.md`, `brief-hub-setup.md`) that this document names are working material of the 2026-11-10 review and are not in this repository (`git ls-files` lists none of them). Sections 9 and 14 are kept as the record of the build phase.
- 2026-11-11 corrected in place after the audit of that day (`docs/issues/2026-11-11-audit.md`), where the code differs from the text: the three `job_template` placeholders (§6.3, §6.5), the node check `allowed_gpus` and the `hello.state` key `allowed_gpus_set` (§6.3, §6.5), the mode 700 condition of the hub data root (§6.3), the re-run of the pulled script by `--update` (§6.6), and the four guarded keys of `rb-node config set` and `config init --force` (§7.1, §13 row 12). Each has a row in §13 (rows 14 to 18). The design stays a draft.
- 2026-11-11, later: corrected for the node fixes of that day (their branch was not yet merged when this line was written): the `approval_path` check uses the submit rule, the new `max_file` check, and the removed `spawn._launcher` alias (§5, §6.3; §13 rows 19 to 21).

Terms used below: **hub** = the Linux server that runs `rb` and the MCP server; **node** = the experiment server (`node1`); **MCP** = Model Context Protocol, the tool interface a Claude session uses; **agent** = `ssh-agent`, the process that holds decrypted SSH (Secure Shell) keys in memory; **JSON** = JavaScript Object Notation; **uid** = numeric user id; **pid** = process id; **gcr** = the GNOME keyring's SSH agent, whose socket is `$XDG_RUNTIME_DIR/gcr/ssh`; **CLI** = command line interface (the Claude CLI is the `claude` command); **DNS** = Domain Name System; **CIDR** = an address with a prefix length, for example `192.0.2.0/24`; **`$XDG_RUNTIME_DIR`** = the per-user runtime directory set by the login manager, normally `/run/user/<uid>`; **PR** = pull request, a change merged into `main` on GitHub.

## 1. Intent

Linking the hub to a node today takes 24 user steps across 7 documents, with 3 hand transfers between machines and 6 files outside the repository edited by hand or by flags that do not ask (survey `user-steps.md` §2). The steps repeat the same facts: node name, host, port and user are typed into `hub-connect.sh`, then reappear in `rb config add-node`, the `Host` blocks, `ssh-keyscan` and every manual. Two scripts (`hub-connect.sh`, `hub-agent.sh`) and a third on the node (`trm-link.sh`) each cover part of the job, and none is named in the README.

When something fails, the user sees one of two messages. Every `Permission denied (publickey` with exit 255 becomes `ssh key unavailable (agent locked?)`, including the case where the agent holds the key and the node refuses it because of `from=` (`rb_host/client.py:106-107`). Every other failure, including an unknown alias, a missing `known_hosts` entry, a network failure and a node without `node.json`, becomes `connection to <alias> closed (exit N)` (`rb_host/client.py:108`). This misled the user on 2026-11-06 (survey `code-host.md` finding 1; the ambiguity is admitted in `docs/manual/hub-setup.md:150`).

The hub cannot see the node's state. `hello` returns only `node`, `version` and `withheld_extra` (`rb_node/remote.py:62-64`), `rb_host` never calls it, and `__version__` has stayed `0.1.0` since the first two commits (`git log -- rb_node/__init__.py`) although ops were added later (`git_status`, configurable `read_doc` paths). Whether the approval verifier exists, whether `job_template` is set and whether the withheld pattern file loaded can only be checked on the node console.

This design replaces the three scripts with one hub command (`rb setup`) that ends by printing one node command (`scripts/node-install.sh ...`), adds a diagnosis command on each side (`rb doctor`, `rb-node doctor`), classifies SSH failures into ten codes that each name the next command, and extends `hello` additively so the hub doctor can report node state.

## 2. Goals

- G1. The number of user steps from a fresh clone to a working link falls from 24 to at most 17, counted the same way as the survey (each command, pasted command or hand action the user performs, including the per-boot agent step). Hand transfers from hub to node fall from 3 kinds to 2 (one pasted command and the withheld pattern file); the host key fingerprint is compared by eye, as in survey step H6. Files outside the repository edited by hand or by a command that does not ask (the survey's definition) fall from 6 to 3: `~/.claude.json` (through the `claude mcp add-json` command the user pastes), and on the node `node.json` and `~/.local/bin/rb-node` (written by `node-install.sh`, as today). None is edited by hand.
- G2. The README alone is enough for setup: no step needs a manual section. (The README is rewritten in the documentation part of this review, contract §1.5; this design supplies the commands.)
- G3. `rb setup` is idempotent: a second run with the same arguments changes no file and asks nothing except where a step was not completed.
- G4. Every SSH failure seen by `NodeClient` carries one of ten codes and a next command, and the message contains no host name other than the alias.
- G5. The MCP server finds the agent itself: no `SSH_AUTH_SOCK` in the MCP entry and no Claude session restart after the agent is started or reloaded.
- G6. A connection that stops answering fails within about 45 seconds instead of blocking forever.
- G7. `rb doctor` lists every check with `ok`, `warn` or `fail` and one next command, exits 1 only when a `fail` exists, and reports node state from one `hello` call.
- G8. `rb-node doctor` does the same on the node, including the two `authorized_keys` lines.
- G9. A new hub works against the node code installed today (protocol 1), and the current hub works against the new node code (protocol 2).
- G10. The seven node defects listed in contract §1.4 (cancel match, `.part`/`.tmp` names, `approve-key set` without a terminal, bare launcher in the job script, discarded responder output, dead-pid lock, withheld pattern counting) and the configuration fixes of the same section are fixed, each with a test that failed before the fix.

## 3. Non-goals

- Host key pinning in code and request authentication (GitHub issue 25). The host key is still checked by OpenSSH through `known_hosts`.
- Connection reuse (`ControlMaster`). Deferred, contract §2.
- Responder arbitration between a spawned responder and a live session (issue 41). `rb-node link` keeps today's behaviour and prints a warning.
- Changing `rb config mcp` output, `rb sync`, `rb web`, the board or the share page. Those belong to the sync-and-page design of the same review.
- Supporting a Windows hub in the new commands. Existing Windows code paths stay as they are.
- Renaming `trm_root` or the `git_status` result key `trm` (contract §3 item 6).
- Agent discovery for the harness channel. `rb_host/harness.py` starts its own ssh with the caller's environment (`harness.py:218-231`) and is outside this design's files. With `hub-agent.sh --persist` gone, nothing writes `SSH_AUTH_SOCK` into the user's shell, so `rb harness` works only when the shell already has it. Workaround: `rb agent` ends by printing the socket it used and the line `export SSH_AUTH_SOCK=<socket>` for the current shell (it writes no file). Moving `harness.transport` onto `sshenv.agent_socket` is a later change (§15).

## 4. Anti-goals (failure even if it works)

- Any command writes `~/.claude.json` or `~/.bashrc`.
- A command edits `~/.ssh/config`, `~/.ssh/known_hosts`, `~/.ssh/authorized_keys` or `~/.config/systemd/user/*` without a terminal, without showing the change, without a `y` answer, or without a backup first.
- A Claude session can run `rb setup`, `rb agent`, `rb service install`, `rb-node approve-key set` or the `authorized_keys` step of `node-install.sh` to completion.
- A host key is added to `known_hosts` that the user was not shown, or is added from a second scan different from the one shown.
- A private key is added to an agent socket that another user could have created, or to a socket outside the hub user's runtime directory (an agent forwarded from the laptop, or a per-login agent under `/tmp`), §7.4.
- A `hello` result, a hub error message or a hub doctor line contains a path on the node. Any of these, or any node doctor line, contains a pattern text, key material, or ssh's stderr (which carries `user@host` and addresses). `rb-node doctor` and `rb-node config check`, which run on the node console and send nothing over the bridge, may print node paths.
- `hello` on an unconfigured node creates directories or reads paths.
- The current hub breaks against new node code, or a new hub breaks against the installed node.
- AGENTS.md hard rules 1 to 9 change in substance. In particular, the MCP tool set stays at exactly ten tools.

## 5. Constraints

- Contract §0: hard rules unchanged; every wire change additive; old node answers `hello` with three keys, unknown ops return `unknown_op`, unknown arguments are ignored.
- Node code: standard library only, Python 3.8 or later, `from __future__ import annotations` in every module (including `rb_node/__init__.py` once it gains code).
- Hub: Linux, Python 3.10 or later, environment managed by uv.
- OpenSSH reads `~/.ssh/config` and the default `known_hosts` from the home directory in the password database, not from `$HOME` (checked on this hub: with `HOME` set to a temporary directory, `ssh -F /dev/null -G <alias>` still printed `userknownhostsfile` under the real home). So tests cannot isolate ssh by changing `HOME`; every external command goes through one replaceable function per side, and a test guard fails any unreplaced call (§9, briefs).
- `ssh -G <alias>` prints the effective configuration without connecting. For an alias with no matching `Host` block, it prints `hostname <alias>` (checked with OpenSSH 9.6 and `-F /dev/null`).
- `ssh-add -l` exits 0 when the agent lists keys, 1 when it holds none, 2 when no agent answers (checked).
- `ssh-keygen -F '[host]:port' -f FILE` exits 0 when an entry exists and 1 otherwise; a non-default port must use the bracket form (checked).
- Connecting to a Unix socket file that has no listener raises `ConnectionRefusedError` (checked). This is how a dead agent socket is told from a live one.
- Reused code: `rb_node.configure.write_json` and `git_exposure` for config writes; `rb_host.cli._interactive` for the terminal check; `rb_node.approval._load` for verifier parsing; `spawn.launcher_argv` (formerly `spawn._launcher`; the alias was removed on 2026-11-11, §13 row 21) for the node launcher path.

## 6. Architecture

```
hub terminal (user)                                    node terminal (user)
  rb setup ──┬─ host.json, node entry (data root)
             ├─ ssh-keygen x2 ──> ~/.ssh/research-bridge/
             ├─ [show, y] ~/.ssh/config blocks
             ├─ host key: first run (keys just generated) ─> deferred, "rerun after the node command"
             ├─ ssh-add (runtime-directory agent found or started)
             ├─ prints: scripts/node-install.sh --hub-key '...' --harness-key '...' --hub-from ADDR ...
             │                                         paste ─> node-install.sh
             │                                                 ├─ code (symlink swap), wrapper, node.json
             │                                                 ├─ [show, y] authorized_keys
             │                                                 ├─ prints host key fingerprints ──┐
             │                                                 └─ rb-node doctor                  │
             ├─ prints: claude mcp add-json --scope user research-bridge '...'                   │
             └─ rb doctor (offline + one hello; first run: host_key_unknown expected)            │
                                                                                                  │
  rb setup --node NAME (rerun) ── ssh-keyscan once ─> temp file ─> fingerprint shown              │
             user compares with the node-install output <─────────────────────────────────────────┘
             [y] same bytes ──> known_hosts ── rb doctor (online part now reaches the node)

MCP server / rb sync / rb doctor ── NodeClient ── ssh (BatchMode, keepalive, SSH_AUTH_SOCK = discovered socket) ──> node: rb-node serve-remote
```

Every connection goes from the hub to the node (hard rule 2). `rb setup` and `node-install.sh` never contact each other; the user carries the node command by copy and paste, and compares the host key fingerprint by eye.

### 6.1 Interfaces

| Name | Kind | Notes |
|---|---|---|
| `rb setup` | hub, terminal, writes after `y` | §6.2 |
| `rb agent [--node NAME]` | hub, terminal | Loads the bridge and harness keys of each node (or one) into the first runtime-directory agent that answers (the load order of §7.4, which never uses an inherited `$SSH_AUTH_SOCK` outside the runtime directory), starting one in `$XDG_RUNTIME_DIR/rb-ssh-agent` only when none answers. Key files come from `ssh -G`: among the alias's `identityfile` values, only a file named `<node>_ed25519` (harness: `<node>_harness_ed25519`), the names `rb setup` generates, counts, so any `--keydir` works but no other key is ever loaded; an alias without such a value gives `no bridge IdentityFile configured for <alias>` (§13 row 1). Writes no file; ends by printing the socket and `export SSH_AUTH_SOCK=<socket>` for the current shell. Replaces `scripts/hub-agent.sh`. |
| `rb doctor [--node NAME] [--offline]` | hub, read only, one SSH connection per node unless `--offline` | §6.3 |
| `rb config check` | hub, read only | Runs the offline part of `rb doctor` (`doctor.main(None, offline_only=True, only_problems=True)`) and prints only non-`ok` lines, as today; it has no checks of its own. |
| `rb service install [--interval SECONDS] [--port N] [--print]` | hub, terminal unless `--print`, writes after `y` | Writes `rb-sync.service`, `rb-sync.timer`, `rb-web.service` under `~/.config/systemd/user/` with the text fixed in the sync-and-page design §6.10 (ruling R6); prints, never runs, the `systemctl` and `loginctl` commands. Defaults: interval 300, port 8767. |
| `rb service status` | hub, read only | `systemctl --user is-enabled/is-active` for the three units, last result of `rb-sync.service`, linger state. |
| `TransportError.code`, `.hint` | hub, internal | §6.4 |
| `normalize_hello(raw)` | hub, internal (`rb_host/client.py`) | Returns `{node, version, protocol, ops, state, withheld_extra}`; `protocol` is 1 when absent or not an int; `ops` and `state` are `None` when the node did not send them; `withheld_extra` is `None` when not an int; a result that is not a JSON object raises `TransportError` with code `closed`. `rb doctor` and `rb sync` both read `hello` through it (ruling R10, closed at integration, commit ceb27f9). |
| `hello` (node op) | read | Protocol 2 result, §6.5 |
| `rb-node doctor` | node console, read only | §6.3 |
| `rb-node config check` | node console, read only | The configuration part of `rb-node doctor`, non-`ok` lines only. |
| `rb-node link [DIR] [--apply]` | node console | Prints the project MCP entry for a live session; with `--apply` writes `<DIR>/.mcp.json` only if absent. `DIR` defaults to `trm_root`. Flags in any position. Replaces `scripts/trm-link.sh`. |
| `rb-node approve-key set\|clear` | node console | Now refuses unless stdin and stdout are a terminal; `clear` asks `y/N`. |
| `scripts/node-install.sh` | node console | §6.6 |

The MCP tool set is unchanged: exactly ten tools, same names.

### 6.2 `rb setup`

```
rb setup --node NAME [--host HOST] [--port N] [--user USER] [--keydir DIR]
         [--hub-from ADDR] [--research-root DIR] [--yes-print-only]
```

A terminal is required (stdin and stdout), except with `--yes-print-only`, which shows every change and every command to paste, asks nothing, writes nothing and sends no network traffic: it skips the host key scan (step 5 prints the `ssh-keyscan` command instead), does not resolve HOST (step 7 prints `--hub-from <HUB_ADDR>` with the note of step 7 unless `--hub-from` is given), and runs only the offline part of the doctor (step 9). The flag name comes from contract §1.2, although the mode confirms nothing. It is the only mode a session can run. `--host` and `--user` are required on the first run; on a later run they may be left out, and the values come from `ssh -G rb-<NAME>` (the block written by step 4). `--port` defaults to 22, `--keydir` to `~/.ssh/research-bridge`. `--research-root` only fills the printed node command (step 7); the hub stores it nowhere.

Each step is skipped when already satisfied. A step that cannot complete prints the reason and the command to run, and setup continues with the steps that do not depend on it; a failed step 1 or 2 stops setup, because every later step needs `host.json` and the node entry. Before step 1 the arguments are checked (node name as for `rb config add-node`; `--host` and `--user` without whitespace, control characters or `#`; `--port` 1 to 65535; a `host.json` whose keys have the wrong types; bridge and harness keys resolving to the same file); a failure prints one `error:` line and exits 2 (wrong types: exit 1), and nothing is written (§13 row 4). On a rerun without `--host`, `--port` also comes from `ssh -G`.

| # | Step | Reads | Writes | Asks |
|---|---|---|---|---|
| 1 | Data root and `host.json` | `RB_HOST_ROOT`, `RB_HOST_CONFIG`, `host.json` | data root (mode 700) and `host.json` through `configure.init` (mode 600, refused if git would track it) | nothing. If `host.json` exists but is not valid JSON, setup stops with the path and the parse error and does not overwrite it. |
| 2 | Node entry | `host.json` | `nodes.<NAME> = {alias: rb-<NAME>, harness_alias: rb-<NAME>-harness}` through `configure.add_node` | nothing. An existing entry with other aliases is kept and those aliases are used for the rest of the run; setup says so. |
| 3 | Two keys | `<keydir>/<NAME>_ed25519{,.pub}`, `<keydir>/<NAME>_harness_ed25519{,.pub}` | the missing key pair(s) via `ssh-keygen -t ed25519 -f FILE -C research-bridge-hub` (or `research-bridge-harness`); `<keydir>` mode 700 | `Generate <paths>? [y/N]`, then `ssh-keygen` asks for the passphrase twice per key (setup says the same passphrase may be used for both). An existing private key without `.pub` is reported with `ssh-keygen -y -f FILE > FILE.pub`; setup does not create it. A `<keydir>` for which `git_exposure(<keydir>/x)` is not `None` (inside a git work tree and not ignored) is refused with the reason, so `--keydir ./keys` in the checkout cannot put private keys in the repository. |
| 4 | SSH config blocks `rb-<NAME>`, `rb-<NAME>-harness` | `ssh -G` for both aliases (effective values); the user's `~/.ssh/config` (home from the password database) | appended blocks, after a backup `config.bak.<YYYYmmddHHMMSS>`; file mode 600, `~/.ssh` mode 700. Written to a temporary file in the same directory and renamed. Not written when the file is a symbolic link (a rename would replace the link with a regular file, and following it would put `HostName`, `Port` and `User` into the link's target, often a dotfiles repository) or when `git_exposure` of the resolved path is not `None`: setup prints the blocks and the reason for the user to add by hand. | The two blocks are shown, then `Append to <path>? [y/N]`. |
| 5 | Host key | `ssh -G rb-<NAME>` (`hostname`, `port`, `hostkeyalias`, `userknownhostsfile`, `hashknownhosts`); the scan goes to the `hostname` and `port` that `ssh -G` reports when the alias is defined, with a note when they differ from `--host`/`--port` (integration item 10, commit ef49060); `ssh-keygen -F` on each known-hosts file | the scanned lines, appended to the first `userknownhostsfile` after a backup (`ssh -G` prints all of them on one line, separated by spaces and unexpanded, for example `~/.ssh/known_hosts ~/.ssh/known_hosts2`: the line is split, `~` and `%d` are expanded to the home directory, and a path that is still not absolute is never written); not written when that file is a symbolic link or `git_exposure` of its resolved path is not `None` (the lines and the reason are printed instead) | §7.3. On a run in which step 3 generated a key, the node cannot have run the command yet, so there is nothing to compare with: the step scans nothing, asks nothing and prints "host key: run the node command below first; it prints the node's host key fingerprints; then run: rb setup --node NAME". |
| 6 | Agent and keys | load order of §7.4 (runtime-directory sockets only); `ssh-add -l` on the chosen socket; fingerprints of both `.pub` files (`ssh-keygen -lf`) | starts `ssh-agent -a $XDG_RUNTIME_DIR/rb-ssh-agent` only when no runtime-directory socket answers; `ssh-add FILE` for each key not yet listed. Never adds a key to an inherited `$SSH_AUTH_SOCK` outside the runtime directory. | `ssh-add` asks each passphrase |
| 7 | Node command | both `.pub` files; `--hub-from` or `ip -o route get <address of HOST>`; `--research-root`; whether the hub pattern file `withheld_patterns_file` from `host.json` exists (`HostConfig.withheld_patterns_file`, which may lie outside the data root); the checkout's `origin` URL | nothing | nothing. Prints §6.2.1. |
| 8 | MCP registration | `~/.claude.json` (read only, same lookup as doctor check `mcp_entry`); `shutil.which("uv")`; the checkout path | nothing | nothing. Prints `claude mcp add-json --scope user research-bridge '<json>'` unless an equal entry is present. The JSON's `env` carries the same `RB_HOST_*` variables as the units (ruling R6): `RB_HOST_CONFIG` always, `RB_HOST_ROOT` only when the shell running `rb setup` has it set. Warns when the checkout path contains `/.claude/worktrees/` (a worktree is deleted later). When `rb` runs from a worktree and the registered entry differs only in the checkout path (`--directory`), the entry counts as registered (`from_worktree`) and nothing is printed (integration item 9). An entry whose command, arguments or `RB_HOST_*` variables differ (`differs`) is reported with `claude mcp remove research-bridge` and the command again. |
| 9 | Doctor | as `rb doctor --node NAME` | nothing | nothing. While step 5 is not done, the online part is expected to fail with `host_key_unknown`; setup says "after running the command on the node, run: rb setup --node NAME" (the rerun completes step 5 and runs the doctor again). |

Step 4 detail. Expected effective values for `rb-<NAME>`: `hostname` = HOST, `port` = N, `user` = USER, an `identityfile` whose file name is the bridge key's name equals the bridge key (the position in the list does not matter, so a `Host *` value read first does not hide it; a difference shows the value picked by name, §13 row 1), `identitiesonly yes`, `stricthostkeychecking true`; the same for the harness alias with the harness key. The keepalive lines are written into a new block but are not compared, because `default_argv` passes them on the command line for every `rb` connection. If `ssh -G` shows the alias is already defined (its `hostname` differs from the alias, which also covers blocks reached through `Include` or wildcards), setup does not append. It compares the effective values and lists each difference as `<alias>: <option> is X, expected Y`, then prints the expected block for the user to merge by hand. After an append, setup runs `ssh -G` again: if a value still differs (an earlier `Host *` block wins, because OpenSSH uses the first value it reads), it prints which option is overridden. The written block:

```
# research-bridge: rb setup <YYYY-MM-DD>
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
    (same, IdentityFile ~/.ssh/research-bridge/node1_harness_ed25519)
```

Step 7 detail. `--hub-from` defaults to the `src` field of `ip -o route get <ADDR>`, where `ADDR` is HOST resolved with `getaddrinfo` (DNS only; no packet goes to the node). Setup prints "the node will see this hub as <HUB_ADDR> (from `ip route get`); if a router translates addresses between the two machines, pass --hub-from with the address the node sees". If HOST does not resolve or `ip` fails, the command is printed with `--hub-from <HUB_ADDR>` and a note to fill it in.

Running on a hub linked by the old scripts. The hub was linked before this design with `hub-connect.sh` and `hub-agent.sh`, so the first real run is an upgrade. Step 1 and step 2 find `host.json` and the node entry. Step 3 finds the keys, because `hub-connect.sh` used the same names (`<keydir>/<node>_ed25519`, `<node>_harness_ed25519`). Step 4 finds both aliases defined and compares only the six options above, so blocks without keepalive lines are not reported. Step 5 finds the `known_hosts` entry. Step 6 finds the gcr or `rb-ssh-agent` socket. Step 8 finds the MCP entry; if that entry still carries `env.SSH_AUTH_SOCK` from `hub-agent.sh --persist`, setup notes that the variable is no longer needed and may stay (discovery tries it first and moves on when it is dead). An entry made by the old scripts has no `RB_HOST_CONFIG`, so it is not equal to the new one and step 8 prints the `claude mcp add-json` command again for the user to run. Steps 7 and 9 print the node command and the doctor report.

#### 6.2.1 Printed node command

```
On the node, in a research-bridge checkout (git clone <REPO_URL>; cd research-bridge):

  scripts/node-install.sh --research-root <DIR> \
    --hub-key 'ssh-ed25519 AAAA... research-bridge-hub' \
    --harness-key 'ssh-ed25519 AAAA... research-bridge-harness' \
    --hub-from <HUB_ADDR> --withheld-file ~/withheld-patterns.json --apply-authorized-keys

  Before running it, copy the withheld pattern file to ~/withheld-patterns.json on the node.
  At the end it prints the node's host key fingerprints. Then run on the hub:
    rb setup --node <NAME>
  which shows the fingerprint it scanned; answer y only if it equals the line of the same type.
```

`--research-root` is printed only when given to `rb setup`; otherwise it is left out and `node-install.sh` keeps the value in an existing `node.json`, or asks once on a terminal, or stops with "give --research-root". `--withheld-file` is printed only when the hub's `withheld_patterns_file` exists; the note names that path as the file to copy, and otherwise says that it is missing. The copy on the node may have any name, because `--withheld-file` copies it to `~/.research-bridge/withheld-patterns.json`; `~/withheld-patterns.json` is only the suggested place. The command text contains both public keys, so no key file is copied. `<REPO_URL>` is the checkout's `origin` URL when it is an `https://` URL, otherwise a placeholder.

### 6.3 Doctor checks

Output, one line per check: `<level> <id>  <message>` on the hub and `[<level>] <id>: <message>` on the node, followed by `      next: <command>` for `warn` and `fail`. `rb doctor` prints all lines grouped by node and ends with `summary: N ok, N warn, N fail`; `rb config check` and `rb-node config check` print only non-`ok` lines and end with `ok`, `N to fix`, `all ok, M warning(s)` or `N to fix, M warning(s)` (failures and warnings counted apart; a later change); `rb-node doctor` prints all lines and ends the same way (§13 row 9). Exit 1 only when a `fail` exists.

#### Hub, offline (`rb doctor --offline`, also part of `rb doctor` and `rb config check`)

Checks marked "per node" run for every node in `host.json`, or only `--node`.

| id | level when not ok | Condition for ok | Message when not ok | Next command |
|---|---|---|---|---|
| `host_json` | fail | `host.json` exists, parses as a JSON object, and `nodes` (an object of objects), `data_root` and `withheld_patterns_file` (strings) have the right types; on wrong types the remaining checks are skipped | `no host.json at <path>` / `<path> is not valid JSON (line L)` / `host.json has wrong types: <list>` (integration item 8) | `rb setup --node NAME --host HOST --user USER` / fix or move the file, then `rb setup ...` |
| `host_json_git` | fail | `git_exposure(host.json)` and `git_exposure(private/local.json)` are `None` | `LEAK RISK: <reason>` | `add the file to .gitignore or move it` |
| `data_root` | fail | data root is a directory with mode 700 (no group or other permission bits; not tested on Windows) | `data root does not exist: <path>` / `data root <path> has mode <mode>: other accounts can read stored messages and attachments` | `rb setup --node NAME ...` / `chmod 700 <path>` |
| `nodes` | fail | at least one node entry | `no node in host.json` | `rb setup --node NAME --host HOST --user USER` |
| `alias` (per node) | fail | `ssh -G <alias>` prints a `hostname` different from the alias | `ssh has no Host block for <alias>` | `rb setup --node NAME --host HOST --user USER` |
| `alias_harness` (per node) | warn | same for the harness alias | `ssh has no Host block for <harness alias> (harness channel only)` | same |
| `ssh_options` (per node) | warn | for both aliases, effective `identitiesonly yes` and `stricthostkeychecking true`. Step 4 compares all six options with the values given to `rb setup` (`identityfile` as an expanded absolute path on both sides); the doctor has no expected values for `hostname`, `port`, `user` and `identityfile` (and `ssh -G` prints a default for each of them), so it leaves them to `alias` and `key_file` | `<alias>: <option> is X, expected Y` | `rb setup --node NAME` (prints the expected block) |
| `key_file` (per node) | fail | the alias's `identityfile` named `<node>_ed25519` (chosen by name, never by position; §13 row 1) exists, mode has no group or other bits, `.pub` exists | `no bridge IdentityFile configured for <alias>` (no such value; OpenSSH's default list or a `Host *` key never counts) / `key file missing: <path>` / `key file mode is <mode>` / `public key missing: <path>.pub` | `rb setup --node NAME` / `chmod 600 <path>` / `ssh-keygen -y -f <path> > <path>.pub` |
| `key_file_harness` (per node) | warn | same for the harness alias and `<node>_harness_ed25519` | same, with "(harness channel only)" | same |
| `agent` | fail when some node's bridge key needs a passphrase, else warn | discovery (§7.4) returns a socket | `no ssh-agent reachable` | `rb agent` |
| `key_loaded` (per node) | fail | fingerprint of the bridge `.pub` is listed by `ssh-add -l` on that socket, or the key file has no passphrase | `key for <alias> is not in the agent` | `rb agent --node NAME` |
| `key_loaded_harness` (per node) | warn | same for the harness key | same, "(harness channel only)" | `rb agent --node NAME` |
| `agent_location` (per node) | warn | the bridge key is listed by at least one socket of the load order (§7.4: runtime directory only), or the key file has no passphrase; skipped when `key_loaded` is not ok | `key for <alias> is only in an agent outside the runtime directory: unattended sync and other shells cannot use it` | `rb agent --node NAME` |
| `known_host` (per node) | fail | `ssh-keygen -F` finds `hostkeyalias`, or `HOST` (port 22), or `[HOST]:PORT`, in a `userknownhostsfile` | `no known_hosts entry for <alias>` | `rb setup --node NAME` (step 5 compares the fingerprint) |
| `withheld_hub` | fail (missing, unparseable, no pattern, or a pattern fails to compile). A missing file stays a `fail` so that `rb config check` keeps exiting 1 for it, as today (`rb_host/cli.py:281-285`). | `withheld_patterns_file` exists, loads with no `source_error`, has at least one compiled pattern, and every pattern compiles (counted with `Withheld.rejected_count` / `rejected_indexes` from `rb_node/withheld.py`, ruling R10 closed at integration, commit ceb27f9) | `withheld_patterns_file does not exist: <path> (the hub re-check falls back to the five built-in patterns only)` / `... is not valid JSON` / `... has no pattern` / `N pattern(s) do not compile (indexes i, j)` | `copy the session-calendar pattern file to <path>` |
| `mcp_entry` | warn | a `research-bridge` entry exists in `~/.claude.json` under `mcpServers`, or under `projects.<checkout>.mcpServers`, or in `<checkout>/.mcp.json`; its command exists; its `--directory` exists and is not under `/.claude/worktrees/`; its arguments and `RB_HOST_*` variables equal the entry setup step 8 prints | `MCP server not registered` / `MCP entry points at a missing path` / `MCP entry points at a worktree` / `MCP entry differs from the one rb setup prints; ...; differs in: <command, args, env KEY>` / `this rb runs from a git worktree; the registered MCP entry points at another checkout` (only the checkout path differs; integration item 9); every warning about a found entry ends with `registered: <its --directory, else its command>` (postmortem `2026-11-10-test-suite-overwrote-claude-json.md` PM-02) | the `claude mcp add-json ...` command (as setup step 8); for the worktree case `run rb from the main checkout` |
| `local_json` | warn | `private/local.json` exists | `no private/local.json (only the harness path mapping needs it)` | `rb config local --laptop-home ... --node-home ...` |
| `service_sync` | warn | `rb-sync.timer` is enabled and active | `unattended sync not installed` / `rb-sync.timer is not active` / `systemd user manager not available` | `rb service install` / `systemctl --user enable --now rb-sync.timer` |
| `service_web` | warn | `rb-web.service` is active | `hub page service not installed` / `not active` | `rb service install` / `systemctl --user enable --now rb-web.service` |
| `linger` | warn (only when a unit is installed) | `loginctl show-user <user> -p Linger` says `yes` | `user units stop at logout (linger off)` | `loginctl enable-linger <user>` (may need an administrator) |
| `sync_status` (per node) | warn | `<data_root>/sync/<node>.json` (sync-and-page design §6.3) is not stale by the single staleness rule of the sync-and-page design §6.8, which the page and the MCP `nodes` result also use (read through `threads.read_status` / `threads.summary`, ruling R10 closed at integration, commit ceb27f9); not a pass left at `stage: "running"` with a `last_attempt_at` older than 900 s; skipped when the file does not exist | `last successful sync <age> ago (error: <code>)` / `no successful sync yet (error: <code>)` / `a sync pass started <age> ago and never finished` / `sync status file unreadable` | `rb sync --node NAME` |

#### Hub, online (`rb doctor`, one SSH connection per node, `hello` only)

Every `state` key is read with `.get`; a missing key (or a missing `state`) means "unknown" and gives `warn`, never an exception.

| id | level when not ok | Condition for ok | Message when not ok | Next command |
|---|---|---|---|---|
| `reachable` | fail | `hello` returns a result and, for protocol 2, `state.get("configured")` is not `False` | `<code>: <message>` from §6.4, or `node reachable but not configured` when protocol 2 `hello` has `state.configured` false (an unconfigured node answers `hello` normally, §6.5; a `not_configured` error from `hello` is handled the same way as a safeguard); any other error code from `hello`: `node answered hello with an error: <code>` | the hint of the code; for an unconfigured node: `on the node: rb-node doctor (or rerun scripts/node-install.sh)`. The remaining online checks are skipped. |
| `node_version` | warn | `protocol` is 2 and `version` equals the hub's `rb_node.__version__` | `node code <version> predates protocol 2` / `node runs <v>, hub has <w>` | `on the node: scripts/node-install.sh --update` |
| `node_withheld` | protocol 2: fail when `withheld_source_set` and (`withheld_loaded` is 0 or `withheld_rejected` > 0), warn when not set. Protocol 1: always warn | protocol 2: `withheld_loaded` > 0 and `withheld_rejected` = 0; protocol 1: never ok, because the old node's count is taken before compiling (`rb_node/withheld.py:45`) | `node pattern file did not load or has no pattern` / `N node pattern(s) do not compile` / `no node pattern file: five fallback patterns only` / (protocol 1) `node reports 0 extra patterns: pattern file not loaded or not configured` or `old node reports N patterns, counted before compiling; update the node` | `on the node: rb-node doctor` |
| `node_approval` | protocol 2: fail; protocol 1: warn | `state.approval_verifier` is true | `approval verifier not set on the node` / `unknown (node code predates protocol 2)` | `on the node: rb-node approve-key set` |
| `node_job_template` | warn | `state.job_template_set` is true | `job_template not set: jobs are refused` / `unknown (node code predates protocol 2)` | `on the node: rb-node config set job_template '[...,"{config}"]'` |
| `node_allowed_gpus` | warn | `state.allowed_gpus_set` is true (added when `allowed_gpus` was merged in from PR 47) | `allowed_gpus not set: jobs are refused` / unknown | `on the node: rb-node config set allowed_gpus '[4, 5, 6, 7]'` (your own GPU indices) |
| `node_responder` | warn | `state.claude_bin_found` is true | `claude not found on the node: messages wait for a live session` / unknown | `on the node: rb-node doctor` |
| `node_queue` | warn | `state.queue_dir_exists` is true | `queue directory missing on the node` / unknown | `on the node: rb-node doctor` |

For a protocol 1 node, every row whose next command names `rb-node doctor` uses `on the node: scripts/node-install.sh --update, then rb-node doctor` instead, because the old node has no `doctor` subcommand.

#### Node (`rb-node doctor`; the rows marked C also form `rb-node config check`)

| id | C | level when not ok | Condition for ok | Message when not ok | Next command |
|---|---|---|---|---|---|
| `config` | C | fail | `node.json` exists and is a JSON object | `no node.json at <path>` / `<path> is not valid JSON` | `rb-node config init` (or rerun `scripts/node-install.sh`) |
| `config_keys` | C | warn | no unknown keys (keys starting with `_`, such as `_withheld_source_note` in `deploy/node.json.example`, are notes and ignored) and no known key with a value of the wrong type | `unknown key 'k' is ignored` / `key 'k' has the wrong type and is ignored` | `rb-node config show` |
| `max_file` | C | fail | `max_file` is at most 52428800 (hard rule 5; §13 row 20) | `max_file is above 52428800 (hard rule 5); 52428800 applies` | `rb-node config set max_file 52428800` |
| `research_root` | C | fail | `trm_root` is a directory | `research root does not exist: <path>` | `rb-node config set trm_root DIR` |
| `read_roots` | C | warn | each read root (relative ones under `trm_root`) is a directory; the mailbox entries are covered by `mailbox` | `read root does not exist: <path>` | `mkdir -p <path>` or `rb-node config set read_roots '[...]'` |
| `doc_paths` | C | warn | `experiments_dir` and `hypotheses_path` lie inside a read root | `<key> is outside the read roots: read_doc by id is denied` | `rb-node config set <key> PATH` |
| `queue_dir` | C | warn | `queue_dir` is a directory and `queue_dir/jobs` is writable or creatable | `queue directory missing: jobs would be written where no runner watches` | `mkdir -p <path>/jobs` or `rb-node config set queue_dir DIR` |
| `withheld` | C | fail when the source file is missing, unreadable, unparseable, has no pattern, or has a pattern that does not compile; warn when `withheld_source` is unset | source set, loads, at least one pattern compiles, every pattern compiles (the same rule as the hub's `node_withheld`) | `withheld pattern file not found` / `... is not valid JSON` / `... has no pattern` / `N pattern(s) do not compile (indexes i, j)` / `no pattern file: five fallback patterns only` | `scripts/node-install.sh --withheld-file FILE` or `rb-node config set withheld_source PATH` |
| `approval` | C | fail | `approval._load(approval_path)` returns a record | `approval verifier missing` / `approval verifier unreadable` | `rb-node approve-key set` |
| `approval_path` | C | fail | `approval_path` lies outside every read, write and mailbox root, symbolic links resolved (`approval.root_holding_path`, the rule of `hello` and `job_submit`; §13 row 19) | `approval_path is inside a read/write or mailbox root: <root>` | `rb-node config set approval_path ~/.research-bridge/approve.json` |
| `job_template` | C | warn when empty; fail when it has none of `{config}`, `{config_dir}`, `{config_stem}` | non-empty list with an element containing at least one of the three placeholders (PR 46; `{config_dir}` and `{config_stem}` serve a loader that finds the config by name) | `job_template is empty: job_submit is refused (no_job_template)` / `job_template has no {config}, {config_dir} or {config_stem} placeholder` | `rb-node config set job_template '["uv","run","train.py","--config","{config}"]'` |
| `allowed_gpus` | C | warn | `allowed_gpus` is a non-empty list of non-negative integers (a malformed value counts as empty) | `allowed_gpus is empty: job_submit is refused (no_allowed_gpus)` | `rb-node config set allowed_gpus '[4, 5, 6, 7]'` (your own GPU indices) |
| `claude_bin` | C | warn | `claude_bin` is an executable file | `claude not found: the responder cannot start` | `rb-node config set claude_bin PATH` |
| `pdftotext` | | warn | `pdftotext` on `PATH` | `pdftotext missing: pdf files are denied` | `install poppler-utils` |
| `ak_bridge` | | fail | `~/.ssh/authorized_keys` has a line whose `command=` runs `<abs>/rb-node serve-remote`, with `restrict`, a `from=` option, and an absolute command path that exists and is executable | `no serve-remote line` / `serve-remote line <n> lacks restrict` / `... lacks from=` / `... command path is not absolute or missing` | `scripts/node-install.sh --hub-key '...' --hub-from ADDR --apply-authorized-keys` |
| `ak_harness` | | warn | same for `rb-node harness-receive` | same, "(harness channel only)" | the same command plus `--harness-key '...'` (it keeps `--hub-key`; corrected 2026-11-11, the hint first replaced `--hub-key`) |
| `ak_duplicate` | | fail | the key blob of each bridge line appears on no other line | `the serve-remote key also appears on line <n> without the forced command` / `the serve-remote key is also the harness key on line <n> (AGENTS.md hard rule 9)` / `line <n> also holds this key (a second serve-remote line): remove it by hand` (integration item 15, commit bef535b) | `remove line <n> from ~/.ssh/authorized_keys` |
| `mailbox` | | warn | `mailbox_root/{in,out,state}` exist with mode 700 | `mailbox directory missing: <name>` | `scripts/node-install.sh` (creates them) |
| `responder_lock` | | warn | no `state/responder.lock`, or its holder is alive by the rule of §6.7 (process or process group exists) and its age is below the stale threshold | `stale responder lock (pid not running)` / `responder lock older than <n> s` | `rm ~/.research-bridge/mailbox/state/responder.lock` |
| `stuck_messages` | | warn | no `new` message older than 10 minutes while no lock is held, and no `responding` message older than the stale threshold | `<n> message(s) waiting since <age>` / `<n> message(s) stuck in responding` | `rb-node respond <msg_id>` / `tail ~/.research-bridge/mailbox/state/respond-<msg_id>.log` |
| `install` | | warn | `install.json` exists and its `version` equals the running `__version__` | `no install record` / `installed record <v> differs from running code <w>` | `scripts/node-install.sh` |
| `wrapper` | | warn | `~/.local/bin/rb-node` names an absolute python that exists and is 3.8 or later | `wrapper runs python from PATH` / `wrapper python missing` | `scripts/node-install.sh` |

Doctor lines print line numbers and counts, never key material or pattern text.

### 6.4 SSH error classification

`TransportError(message, code="closed", hint="")`. `str(exc)` is `message` when `hint` is empty, else `"<message> (next: <hint>)"`. `AgentLockedError` stays a subclass of `TransportError` and is raised for `no_agent`, `agent_empty` and `key_not_loaded`, so existing `except` clauses keep working. Existing `TransportError("...")` call sites keep working with code `closed`.

Inputs: ssh exit status, the collected stderr (matched only, never copied into the message), the socket that was passed to the child (`None` if none), and local lookups through `sshenv` (`ssh -G <alias>`, `ssh-add -l`, `ssh-keygen -lf`, `ssh-keygen -y -P '' -f`). Rules are tried in order; the first match wins.

| # | code | Detected by | Message | Hint |
|---|---|---|---|---|
| 1 | `host_key_changed` | exit 255 and stderr contains `REMOTE HOST IDENTIFICATION HAS CHANGED` | `host key of <alias> changed` | `do not connect; compare fingerprints on the node console, see rb doctor --node <node>` |
| 2 | `host_key_unknown` | exit 255 and stderr contains `host key is known for` (OpenSSH: `No <type> host key is known for ... and you have requested strict checking.`) or `Host key verification failed` | `no known_hosts entry for <alias>` | `rb setup --node <node>` |
| 3 | `unknown_alias` | exit 255, stderr contains `Could not resolve hostname <h>` and `<h>` equals the alias (equivalently, `ssh -G <alias>` prints `hostname <alias>`) | `ssh has no Host block for <alias>` | `rb setup --node <node> --host HOST --user USER` |
| 4 | `timeout` | exit 255 and stderr contains `Timeout, server` (keepalive expired), `timed out during banner exchange`, or `Connection timed out` | `<alias> did not answer in time` | `retry; if it repeats: rb doctor --node <node>` |
| 5 | `unreachable` | exit 255 and stderr contains `Could not resolve hostname` (other host), `Could not resolve host`, `Connection refused`, `No route to host` or `Network is unreachable` | `cannot reach <alias> (network or address)` | `rb doctor --node <node>` |
| 6 | `no_agent` | exit 255, `Permission denied (publickey`, the key file needs a passphrase, and no socket was passed or `ssh-add -l` on it exits 2 | `no ssh-agent reachable for <alias>` | `rb agent` |
| 7 | `agent_empty` | as 6, `ssh-add -l` exits 1 | `the ssh-agent holds no keys` | `rb agent` |
| 8 | `key_not_loaded` | as 6, `ssh-add -l` exits 0 and the fingerprint of the alias's `.pub` is not listed | `the key for <alias> is not in the ssh-agent` | `rb agent --node <node>` |
| 9 | `node_refused_key` | exit 255, `Permission denied (publickey`, and either the key is listed by the agent, or the key file has no passphrase (`ssh-keygen -y -P '' -f` succeeds), or its fingerprint cannot be computed | `<alias> refused the key` | `<NODE_DOCTOR> (authorized_keys line and from=); --hub-from may be wrong if a router translates addresses` |
| 10 | `closed` | anything else: exit 255 without a match, a nonzero remote exit (1 or 127 when `rb-node` fails before the protocol starts), end of stream with exit 0, a malformed response, or `ssh` missing (`OSError` at start) | `connection to <alias> closed (exit N)` / `cannot start ssh (<exception name>)` / `bad response from <alias>` | `<NODE_DOCTOR>` / `install openssh-client` |

`<NODE_DOCTOR>` is the text `on the node: rb-node doctor (node code before 0.2.0 has no doctor: run scripts/node-install.sh --update first, or rb-node config check)`. After a transport failure the hub does not know the node's protocol, and the node installed today has no `doctor` subcommand (`rb_node/cli.py:9-10`; argparse rejects it with exit 2), so every transport hint that sends the user to the node names the update as well. `rb-node config check` exists in the old code.

The node refuses `from=` mismatches with the same `Permission denied (publickey).` line as an unknown key, so rule 9 covers both. Rules 6 to 9 run `ssh-add -l` against the same socket given to the ssh child, so the classification describes the agent that ssh actually used.

Classification consults `ssh -G` only for rules 3 and 6 to 9, and only after a failure. Discovery (§7.4) runs before a connection when its 30-second cache for the alias is empty: at most 2 + (number of candidate sockets) short processes per alias (`ssh -G`, `ssh-keygen -lf`, one `ssh-add -l` per candidate), at most once every 30 seconds.

As built after commit 252345c, rules 6 to 9, discovery's preference and the doctor's `key_loaded` check find the alias's key by the node's key names (`sshenv.key_names(node)`), like `key_file` and `rb agent`, so a custom alias in `host.json` finds its key (§13 row 2).

### 6.5 `hello` protocol 2

New node result (all old keys kept with the same meaning, except that `withheld_extra` now counts compiled patterns; the two differ only when a pattern fails to compile):

```json
{
  "node": "<hostname>",
  "version": "0.2.0",
  "withheld_extra": 12,
  "protocol": 2,
  "ops": ["ack", "approve_params", "get_file", "git_status", "gpu_status", "hello",
          "job_cancel", "job_submit", "msg_begin", "msg_commit", "poll", "put_chunk",
          "queue_status", "read_doc"],
  "state": {
    "configured": true,
    "approval_verifier": true,
    "job_template_set": false,
    "allowed_gpus_set": false,
    "withheld_source_set": true,
    "withheld_loaded": 12,
    "withheld_rejected": 0,
    "harness_root_set": false,
    "claude_bin_found": true,
    "queue_dir_exists": true,
    "python": "3.8.20"
  }
}
```

Types: `protocol` int; `ops` sorted list of strings; every `state` value is a boolean or an int except `python`, a version string. No path, pattern text or user name appears. `approval_verifier` is true when `approval._load` parses the file. `job_template_set` is true when the list is non-empty and an element contains `{config}`, `{config_dir}` or `{config_stem}`. `allowed_gpus_set` is true when `allowed_gpus` is a non-empty list of non-negative integers. `withheld_loaded` is the number of compiled patterns from the source file, excluding the five fallback patterns; `withheld_rejected` the number from the source that failed to compile. `claude_bin_found` is true when `claude_bin` is an executable file.

**Unconfigured node.** Today `serve-remote` exits 1 when `node.json` is missing (`rb_node/cli.py:187-191`), which the hub sees as `closed (exit 1)`. With protocol 2, `serve-remote` without `node.json` (or with an unparseable one) starts a minimal dispatcher that answers `hello` with `{"node", "version", "withheld_extra": 0, "protocol": 2, "ops": ["hello"], "state": {"configured": false}}` and every other op with the error code `not_configured`. It creates no directory, opens no audit file and reads no other path. `configured` is otherwise always true.

Compatibility:

| Hub | Node | `hello` | Other ops | What the user sees |
|---|---|---|---|---|
| new | old (installed today, 0.1.0, protocol absent) | three keys; `normalize_hello` sets `protocol: 1`, `ops: None`, `state: None` | unchanged; a newer op returns `unknown_op` | `node_version` warn with the update command; `node_approval`, `node_job_template`, `node_responder`, `node_queue` report "unknown (node code predates protocol 2)" as warn; `node_withheld` is `warn` in every case, because `withheld_extra` is a pre-compile count on old nodes and is the only value a new hub would otherwise read optimistically from an old node. Error classification is entirely on the hub, so it works. An old node without `node.json` still exits 1: `closed` with the `<NODE_DOCTOR>` hint of §6.4, which names `scripts/node-install.sh --update` because the old node has no `doctor` subcommand. |
| new | new | protocol 2 | unchanged | full doctor report |
| old (current `main`) | new | `rb_host` never sends `hello` outside tests; extra keys are ignored | unchanged wire format. Three behaviour changes are visible: `job_cancel` matches the exact id (a cancel of `x` no longer removes `0001_a_x.job`); an attachment named `*.part` or `*.tmp` is stored with `_` appended, which is safe because both upload paths (`server._upload`, `NodeClient.put_file`; one loop, `NodeClient.put_files`, since 2026-11-11) send chunks under the names returned by `msg_begin`; an unconfigured node returns `not_configured` instead of closing (the old hub shows `{"error": "not_configured"}`) | nothing breaks |
| old | old | unchanged | unchanged | unchanged |

The forced command path `~/.local/bin/rb-node serve-remote` does not change, so `authorized_keys` lines written before keep working after `node-install.sh --update`.

### 6.6 `scripts/node-install.sh`

The single node entry point. The shell script does little itself: it checks prerequisites, copies code, writes the wrapper, and calls `python3 -m rb_node.install <subcommand>` (with `PYTHONPATH` set to the checkout) for everything that edits a file or derives a value, so that logic is tested in Python.

| Flag | Alias | Effect |
|---|---|---|
| `--research-root DIR` | `--trm-root` | Sets `trm_root` (absolute, `~` expanded). Also moves `queue_dir`, `write_roots` and `withheld_source` when they still hold the default derived from the old root. Without it: keep the value in `node.json`; with no `node.json`, ask once on a terminal, else stop with "give --research-root". |
| `--hub-key 'ssh-ed25519 AAAA... comment'` | | Bridge public key given inline. |
| `--hub-pubkey FILE` | | Bridge public key from a file (first two fields used). |
| `--harness-key '...'` | | Harness public key inline. |
| `--harness-pubkey FILE` | | Harness public key from a file. |
| `--hub-from ADDR` | `--hub-subnet` | Value for `from="..."`: one or more addresses or CIDR ranges, comma-separated, each validated with `ipaddress.ip_network(strict=False)`. |
| `--withheld-file FILE` | | Validates that the file loads with no `source_error`, has at least one pattern, and every pattern compiles; refuses a file that fails validation. Copies it to `~/.research-bridge/withheld-patterns.json` (mode 600) and sets `withheld_source` to that path. When every existing pattern file (the destination, and the file `withheld_source` currently names) is byte-identical to FILE and `withheld_source` already names the destination, nothing changes and nothing is asked, so a rerun with the same file needs no answer. When an existing pattern file differs: a terminal is required (otherwise the step refuses, exit 1, nothing changed); the counts are shown (current N patterns, new M; "fewer patterns: masking is narrowed" when M < N; never pattern text); `Replace? [y/N]`; on `y` the existing destination is backed up to `withheld-patterns.json.bak.<stamp>` (mode 600) before the copy. Reason: without this, a session with a shell on the node could narrow masking (hard rule 3) to one harmless pattern plus the five fallback patterns by rerunning the script. |
| `--apply-authorized-keys` | | Shows the planned change to `~/.ssh/authorized_keys` (lines added, line numbers replaced), asks `Apply? [y/N]` only when stdin and stdout are a terminal, backs up to `authorized_keys.bak.<stamp>`, then writes through a temporary file and rename (mode 600, `~/.ssh` mode 700). The first line holding the same key blob is replaced, not duplicated; any further line with that blob is reported for removal by hand (as doctor `ak_duplicate`). The same public key for bridge and harness is refused (exit 2), because one of the two forced commands would be lost and hard rule 9 requires a separate harness key. Without a terminal, or without `y`, the lines are printed only. |
| `--update` | | `git pull --ff-only` in the checkout first; when the branch has no upstream, prints a message and continues with the current checkout. When the pull moves `HEAD`, the script runs the pulled `scripts/node-install.sh` afresh (`exec sh`) with the same options except `--update`, because `sh` reads a script while it runs and a pull can replace that file (`docs/postmortems/2026-11-10-first-live-run.md` PM-03); the rest of the run is the new script's. With `--dry-run` it does not re-run. |
| `--dry-run` | | Prints every action, writes nothing. |
| `-h`, `--help` | | Usage. A flag given without its value prints usage and exits 2. |

Order of work: prerequisites (`python3` 3.8 or later, `git`; notes for missing `pdftotext` and `claude`) → refusal when `~/.local/share/research-bridge` holds hub data (`host.json` or `ledger.jsonl`), so a node install cannot land in a hub's data directory → research root decided and checked to be a directory → keys and `--hub-from` validated (`rb_node.install authorized-keys --check`), exit 2 before anything is written (§13 row 11) → `--update` → code copy into `~/.local/share/research-bridge/releases/<stamp>/rb_node`, then an atomic symlink swap of `~/.local/share/research-bridge/rb_node` (`ln -s` to a temporary name, then `mv -T`), keeping the two newest releases and the one in use (`releases/legacy` is never pruned) → wrapper `~/.local/bin/rb-node` with the absolute python path found at install time → `node.json` (`config init` if missing, root and derived paths, `claude_bin` only when the current value is not an executable file, withheld file) → mailbox directories `in`, `out`, `state`, `state/acked` (mode 700) → install record (`rb-node install-record <checkout>`) → `authorized_keys` → host key fingerprints (`ssh-keygen -lf` on each `/etc/ssh/ssh_host_*_key.pub`, labelled "compare with the fingerprint that rb setup --node NAME shows on the hub") → `rb-node doctor`.

On the first run over an existing plain `rb_node` directory, the directory is moved into `releases/legacy` before the symlink is created; there is one moment without code on that run only.

### 6.7 Node defect fixes (contract §1.4)

| Defect | Today | Fix |
|---|---|---|
| Cancel matches the wrong job | `glob("*_%s.job" % job_id)` matches `0001_a_x.job` for `x` (`rb_node/jobs.py:180,189`) | Regular expressions `^\d+_<re.escape(id)>\.job$` (pending) and `^\d+_<re.escape(id)>\.job(\..*)?$` (processing) |
| `.part` name collision loses an attachment | `Mailbox.sanitize` accepts `foo.part`, which is the part file of `foo` | `sanitize` appends `_` to a name ending in `.part` or `.tmp` (case-insensitive) |
| `approve-key set` accepts piped input | `getpass` falls back to stdin (`rb_node/cli.py:103`) | Refuse unless stdin and stdout are a terminal (`rb_node.cli._interactive`, replaceable in tests); `clear` asks `y/N` |
| Queued job calls bare `rb-node` | `#!/bin/bash\nexec rb-node run-job ...` (`rb_node/jobs.py:150-156`: argv at 150-151, body at 156) | Absolute launcher from `spawn.launcher_argv()`; the `python -m rb_node.cli` fallback writes `PYTHONPATH=<quoted package parent> exec <python> -m rb_node.cli run-job ...` (assignment before `exec`) |
| Responder output discarded | `stdout`/`stderr` to `DEVNULL` (`rb_node/spawn.py:131-133`, `88-89`) | A diagnostic log `mailbox/state/respond-<msg_id>.log`, mode 600. The `claude -p --output-format json` stdout is not kept as it is: its `result` field is the model's final text, derived from the message body and from files the responder read in the research tree, possibly withheld runs. After the run, the log receives only the JSON fields `is_error`, `subtype`, `num_turns` and `duration_ms` (or `stdout was not JSON (N bytes)`), plus stderr passed through `Withheld.mask_text` and cut to the last 64 KiB. The `respond` process started by `trigger` appends its own stderr (a Python traceback, if any; `respond` never prints a message body) to the same file. The audit record and event carry only the reason, never log text. Retention: at the start of each responder run, `respond-*.log` files older than 14 days are deleted. |
| Dead responder lock blocks for 35 minutes | pid (process id) written, never read (`rb_node/spawn.py:62`); takeover is unlink then `O_EXCL` create (`spawn.py:46-60`), so two processes that both judged the lock stale can each remove the other's new lock | The lock is stale when its age exceeds the threshold (unchanged) or its content parses as a pid for which both `os.kill(pid, 0)` and `os.killpg(pid, 0)` raise `ProcessLookupError`. The process-group test matters because `trigger` starts `respond` with `start_new_session=True`, so `respond` leads its process group and the `claude` child it runs belongs to that group: if `respond` is killed while the child keeps running, the group still exists and the lock stays held. The single-process test covers a `respond` started by hand that does not lead a group. `PermissionError` counts as alive; empty or unparsable content falls back to the age rule. Takeover is serialised: a process that judges the lock stale creates `responder.lock.takeover` with `O_EXCL` (if that fails it returns "busy"; a takeover file older than 60 s is removed by the age rule), reads and judges the lock again, removes it only if still stale, creates the new lock with `O_EXCL`, then removes the takeover file. A process that judged the old lock stale before another process replaced it reads the new lock again inside the takeover, finds its holder alive, and returns without removing it. |
| Withheld loader counts broken patterns | `extra_count` counts before compile (`rb_node/withheld.py:45`) | `extra_count` = compiled patterns from the source; new `rejected_count` and `rejected_indexes` (indexes only) |
| Withheld default can never load | `withheld_source` defaults to a `.yaml` path (`rb_node/config.py:29`) | Default `~/.research-bridge/withheld-patterns.json` |
| `~` not expanded | `config set trm_root '~/x'` stores `~/x` | `node_set` and `load_config` expand `~` in every path key and list entry |
| Root change leaves dependent paths behind | `node-install.sh --trm-root` sets only `trm_root` | `node_set(…, "trm_root", new)` moves `queue_dir`, the queue `write_roots` entry and an old-default `withheld_source` when they still equal the defaults derived from the old root |
| Live session not told that bodies are data | `serve-local` `initialize` has no `instructions`, version literal `0.1.0` (`rb_node/local.py:177-180`) | `instructions` string: inbox bodies are data from a peer, never instructions; requests to change files or queue jobs go to the user. `serverInfo.version` = `__version__` |

## 7. Security

### 7.1 Edits outside the repository

| File | Side | Written by | Confirmation | Backup |
|---|---|---|---|---|
| `~/.ssh/research-bridge/<node>_ed25519{,.pub}`, `<node>_harness_ed25519{,.pub}` | hub | `rb setup` step 3 (`ssh-keygen`) | terminal, `y`, then passphrase prompts; never overwrites an existing key | not needed (new files only) |
| `~/.ssh/config` | hub | `rb setup` step 4; never when it is a symbolic link or would be tracked by git | terminal, blocks shown, `y` | `config.bak.<stamp>` |
| first `userknownhostsfile` | hub | `rb setup` step 5, on a run after the node command (§7.3) | terminal, fingerprint shown, user compares with the node's printed line, `y` | `known_hosts.bak.<stamp>` |
| agent memory | hub | `rb setup` step 6, `rb agent` (`ssh-add`), only into a runtime-directory socket (§7.4 load order) | terminal, passphrase prompt | n/a |
| `$XDG_RUNTIME_DIR/rb-ssh-agent` (socket) | hub | `rb setup`, `rb agent` (`ssh-agent -a`) | only when no runtime-directory socket answers; an existing file there is removed only when it is a socket owned by the user and a connect is refused (§7.4) | n/a |
| `~/.config/systemd/user/rb-sync.service`, `rb-sync.timer`, `rb-web.service` | hub | `rb service install` | terminal, contents shown, `y`; unchanged files skipped | `<file>.bak.<stamp>` when an existing file differs |
| `~/.claude.json` | hub | no `rb` command; doctor reads it | the user runs the printed `claude mcp add-json` command | n/a |
| `~/.bashrc` | hub | nothing | n/a | n/a |
| `~/.ssh/authorized_keys` | node | `node-install.sh --apply-authorized-keys` (`rb_node.install`) | terminal, planned change shown, `y` | `authorized_keys.bak.<stamp>` |
| `~/.research-bridge/withheld-patterns.json` and `withheld_source` in `node.json` | node | `node-install.sh --withheld-file` (`rb_node.install withheld`); `rb-node config set withheld_source` | first copy: none; replacing a differing file: terminal, counts shown, `y`. `config set` of a guarded key (`withheld_source` and, added later, `approval_path`, `read_roots`, `write_roots`; `GUARDED_KEYS` in `rb_node/cli.py`): terminal required (`withheld_source` is a My call, §12; §13 row 18); `config init --force` over a `node.json` that holds a non-default value for any of the four: terminal required (§13 rows 12 and 18) | `withheld-patterns.json.bak.<stamp>` |
| `~/.local/share/research-bridge/`, `~/.local/bin/rb-node`, other `~/.research-bridge/*` | node | `node-install.sh` | none (the program's own install and data directories, as today) | previous release kept |
| `<research root>/.mcp.json` | node | `rb-node link --apply` | explicit flag; only if absent | n/a |

A session never runs the confirming commands for the user: `rb setup`, `rb agent`, `rb service install` (without `--print`), `rb-node approve-key` and the `authorized_keys` step require stdin and stdout to be a terminal, as `rb approve` does. A Claude session's Bash tool has no terminal, so these commands refuse or fall back to printing. `--yes-print-only`, `--print` and `--dry-run` write nothing.

### 7.2 Why no command writes `~/.claude.json`

- Claude Code rewrites `~/.claude.json` while it runs. A read-modify-write from another process can lose either side's change (`scripts/hub-agent.sh --persist` did exactly this kind of write).
- The file holds the user's other MCP servers and per-project settings; a fault in our writer damages unrelated configuration.
- AGENTS.md lists `~/.claude.json` under "ask the user before".
- After agent discovery (§7.4), the only reason to edit the MCP entry after registration, `SSH_AUTH_SOCK`, disappears. Registration itself uses `claude mcp add-json`, the Claude CLI's own command, run by the user. `rb doctor` only reads the file.

### 7.3 Host key comparison

1. `rb setup` step 5 resolves `hostname`, `port`, `hostkeyalias` and `hashknownhosts` from `ssh -G rb-<node>`. If `ssh-keygen -F` already finds an entry, the step is skipped. A changed key is not handled here: the next connection fails with `host_key_changed`, and the user decides on the node console. If the node's host key was replaced on purpose, the user removes the old entry with `ssh-keygen -R '[HOST]:PORT' -f <known_hosts file>` (plain `HOST` for port 22) and reruns `rb setup --node NAME`.
2. On a run in which step 3 generated a key, the step stops here and prints that the host key is checked on a rerun after the node command (§6.2 step 5). The node command prints the fingerprints that the comparison needs, so asking before it has run would leave the user nothing to compare with.
3. Otherwise it runs `ssh-keyscan -p PORT -t ed25519 HOST` once (with `-H` when `hashknownhosts` is `yes`), falling back to `-t ecdsa` and then `-t rsa` when the node offers no ed25519 key. As built, the scanned lines are kept in memory; they are written to a temporary file (`mkstemp`, mode 600, removed at once) only for `ssh-keygen -lf`. A scan that cannot be fingerprinted is never appended (§13 row 6).
4. It prints the SHA-256 fingerprint and key type of the scan (`ssh-keygen -lf <tempfile>`) and asks the user to compare it with the line of the same type that `node-install.sh` printed at its end (or with `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` run on the node console). The prompt says: "If you have not run the node command yet, answer n and run rb setup --node NAME again after it."
5. Only on `y` it appends the same scanned lines to the known-hosts file. When the alias sets `HostKeyAlias`, the host field of each line is replaced by that alias (the key itself is unchanged); when it also hashes `known_hosts`, setup cannot name the entry and prints the lines for the user to add by hand (§13 row 6). There is no second scan, and `StrictHostKeyChecking accept-new` is never used. On `n` nothing is written, and setup prints: "If the fingerprints differ, do not connect. Check the node's key on its console (`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`) and find the cause before running rb setup again." Because nothing is appended before the comparison, a mismatch never leaves an entry behind.
6. Only one key type is stored. OpenSSH prefers host key algorithms already present in `known_hosts` for that host, so later connections offer the stored type.
7. OpenSSH's `UpdateHostKeys` is on by default (`ssh -G` prints `updatehostkeys true` on this hub). After a successful login to a host whose key is already trusted, ssh itself may add the node's other host key types, which the server proves with the trusted connection. The anti-goal "a host key the user was not shown" applies to keys added by `rb` commands; these later additions rest on the key the user compared.

### 7.4 Agent discovery

There are two orders: one for connecting and one for loading keys.

**Connect order** (`NodeClient`, doctor `agent` and `key_loaded`). `sshenv.agent_socket(alias)` returns the first candidate that answers (`ssh-add -l` exits 0 or 1), preferring one whose listing contains the fingerprint of the alias's key. Candidates, in order:

1. `$SSH_AUTH_SOCK`, when set. This socket comes from the caller's own environment, so it is accepted wherever it lives (often `/tmp/ssh-XXXX/agent.N`), but only after the checks below. It is used to connect only; no key is ever added to it unless it also lies directly in the runtime directory.
2. `$XDG_RUNTIME_DIR/gcr/ssh`, `$XDG_RUNTIME_DIR/openssh_agent`, `$XDG_RUNTIME_DIR/rb-ssh-agent`. These are guessed names, so they are looked for only under the runtime directory. When `XDG_RUNTIME_DIR` is unset (a systemd user unit has it set; some shells do not), `/run/user/<uid>` is used.

**Load order** (`rb setup` step 6, `rb agent`; `sshenv.load_socket()`). Only sockets in the runtime directory: `gcr/ssh`, `openssh_agent`, `rb-ssh-agent`, and an inherited `$SSH_AUTH_SOCK` only when its parent directory is the runtime directory itself. The first that answers is used; when none answers, `rb-ssh-agent` is started. The order follows `scripts/hub-agent.sh`, which put the runtime-directory sockets first on purpose. Reason: on a Linux hub the user usually works in an SSH login shell. If the laptop forwards its agent, `$SSH_AUTH_SOCK` is the laptop's agent, and adding the hub's bridge and harness keys to it copies the keys to another machine (AGENTS.md lists moving SSH keys under "ask the user before"). If the shell has its own per-login agent, the keys sit in a socket that the `rb-sync` unit and an MCP server started from another shell cannot find, and that socket disappears at logout; unattended sync then fails with `agent_empty` or `no_agent` while `rb doctor` in the same shell reports the key as loaded. Doctor check `agent_location` reports this case.

My call (user to check), approved by the coordinator on 2026-11-10 as ruling R1: contract §1.1 and §1.2 step 6 describe a single order with `$SSH_AUTH_SOCK` first for both purposes. This design keeps that order for connecting and uses the runtime-directory order for loading, which is the safer reading; R1 supersedes those contract sections.

Checks before a socket is used, for every candidate:
- `lstat`: a socket, not a symbolic link, owned by the current uid.
- Its parent directory is owned by the current uid and has no group or other write bit.
- For guessed names, the runtime directory itself is owned by the current uid with mode 700.

Why guessed names are restricted to the runtime directory: `rb setup` and `rb agent` add decrypted private keys to the socket they find. A socket in a world-writable directory such as `/tmp` can be created by another local user under a plausible name; adding a key to it would hand that user the private key. The runtime directory is created by the login manager for this uid with mode 700, so no other user can place a socket there. The inherited `$SSH_AUTH_SOCK` passes the same ownership checks, which rejects a socket owned by someone else (for example after `sudo -E`).

`NodeClient` runs discovery only when the caller gave neither `ssh_argv` nor `env`, and passes the chosen socket to the ssh child as `SSH_AUTH_SOCK`. The result is cached per alias for 30 seconds in the process and dropped at once when a call fails with `no_agent`, `agent_empty`, `key_not_loaded` or `node_refused_key`. A running MCP server therefore picks up an agent started or reloaded later, within 30 seconds or at the next failure, without a restart.

Starting an agent (`rb setup` step 6, `rb agent`): only when no socket of the load order answers. If `$XDG_RUNTIME_DIR/rb-ssh-agent` exists, it is removed only when it is a socket owned by the user and a connect to it raises `ConnectionRefusedError` (no process is listening). This replaces `hub-agent.sh`'s unconditional `rm -f`, which could unlink a live agent's socket after a transient probe failure. The agent started this way is not supervised; `rb doctor` reports when it is gone. With linger off, the runtime directory and the socket are removed at the last logout.

### 7.5 Information in messages and `hello`

- Error messages name the alias only; ssh's stderr, which carries `user@host` and addresses, is matched but never copied (G4).
- `hello.state` holds booleans, counts and the python version. The hostname was already in protocol 1.
- An unconfigured node answers `hello` only and touches no path.
- The responder log `mailbox/state/respond-<msg_id>.log` (§6.7) holds no model output text (`result` is dropped) and masked stderr. It lies outside every read root (`mailbox/state` is not in `read_roots`), so no op serves it over the bridge; it is read only on the node console. Logs older than 14 days are deleted.
- Doctor output on the node prints `authorized_keys` line numbers and option names, never key blobs or comments. Pattern problems are reported by index, never by text.

### 7.6 Threat model

In scope: a Claude session with a shell on the hub or node trying to complete a confirming command (blocked by the terminal check); a fake agent socket in a shared directory (§7.4); host key substitution at first contact (out-of-band fingerprint comparison, §7.3); an old `authorized_keys` line for the same key with weaker options staying in force (`ak_duplicate`, same-key replacement); a broken pattern file weakening hard rule 3 without notice (`withheld_rejected`, doctor `fail`); a session on the node replacing the pattern file with a narrower one (terminal, counts and `y` before replacing, backup, §6.6).

Out of scope: another process of the same user on the hub (it can use the agent anyway, which unattended sync requires; issue 25 point 4); root on either machine; a node that lies in `hello.state` (the state is informational and authorizes nothing); host key pinning in code (issue 25); a pseudo-terminal created by a session to defeat the terminal check (the check makes completing these commands harder for a session but does not prevent it, as for `rb approve`).

## 8. Data and ledger

- No ledger change.
- Hub: `host.json` unchanged in shape. New files written only after confirmation, listed in §7.1.
- Node: `node.json` gains no key; the default of `withheld_source` changes; `~` is expanded on write and on load. New file `mailbox/state/respond-<msg_id>.log` (mode 600). `install.json` unchanged in shape. Install layout gains `~/.local/share/research-bridge/releases/` with `rb_node` as a symlink.
- Wire: `hello` gains `protocol`, `ops`, `state`; new error code `not_configured`.
- `deploy/authorized_keys.example` shows the two lines that `node-install.sh --apply-authorized-keys` writes (`from="<HUB_ADDR>"`, comments `research-bridge-hub` and `research-bridge-harness`), with placeholders only; `deploy/node.json.example` gets the new `withheld_source` default and keeps placeholders.

## 9. Scope of this phase

1. Node implementer (brief `brief-node.md`): protocol 2 `hello`, unconfigured dispatcher, `rb-node doctor`, `rb-node link`, `rb_node.install`, `node-install.sh`, config fixes, defect fixes, deletion of `scripts/trm-link.sh`, `deploy/*`, node tests.
2. Hub implementer (brief `brief-hub-setup.md`): `sshenv`, error classification, keepalive, discovery, `normalize_hello`, `rb setup`, `rb agent`, `rb doctor`, `rb service`, the missing-`host.json` helper, deletion of `scripts/hub-connect.sh` and `scripts/hub-agent.sh`, hub tests, `tests/conftest.py`.
3. Both run in separate worktrees from this branch and are merged here; the full suite must pass after the merge (`rtk proxy uv run --extra host pytest -q`).
4. User, later: run `rb setup` on the hub, the printed command on node1 (needs a go-ahead for any node1 command), then `rb setup --node node1` again on the hub for the host key comparison; `rb-node approve-key set` on node1; `rb service install`.

## 10. Verification

Updated 2026-11-10 after the build: every named test was found in `tests/` and its file run with `rtk proxy uv run --extra host pytest -q tests/<file>` on the hub (Python 3.12.11); every file passed (test_setup 62, test_client_errors 28, test_sshenv 25, test_host_client 10, test_doctor 65, test_node_doctor 32, test_node_hello 11, test_remote 27, test_jobs 41, test_mailbox 15, test_spawn 24, test_withheld 21, test_configure 13, test_node_link 8, test_local 8, test_service 15, test_node_install 42, test_host_tools 64, test_sync 34, test_web 26). Full suite afterwards: 760 passed. Live checks need the user and node1 and were not run: this review has no node contact. The node test files were run under Python 3.12 only in this pass.

| Goal / anti-goal | Check | Kind | Status |
|---|---|---|---|
| G1 | Step table in §16 (24 → 17); recount against the README rewritten in the documentation part of this review (contract §1.5) | manual | not verified: the recount against the rewritten README (commit fb5ccc2) was not done in this pass |
| G2 | Read-through of the rewritten README (contract §1.5), checking that each step in §16 is covered without a manual section. Not a sandboxed run: ssh does not take its home from `HOME` (§5). | manual | not verified: the read-through was not done in this pass |
| G3 | `tests/test_setup.py::test_setup_second_run_changes_nothing` | unit test | passes (2026-11-10, hub, Python 3.12) |
| G4 | `tests/test_client_errors.py`: one test per code (`::test_publickey_no_socket_is_no_agent`, `::test_publickey_agent_empty`, `::test_publickey_key_not_loaded`, `::test_publickey_key_loaded_is_node_refused`, `::test_host_key_changed`, `::test_host_key_unknown`, `::test_resolve_failure_for_alias_is_unknown_alias`, `::test_resolve_failure_for_hostname_is_unreachable`, `::test_timeouts`, `::test_other_exit_is_closed`), `::test_message_never_contains_stderr_text` | unit test | passes (2026-11-10, hub, Python 3.12) |
| G4, real stderr | stderr templates checked against the OpenSSH 9.6 binary's strings on this hub (`Host key verification failed.`, `No %s host key is known for %.200s and you have requested strict checking.`, `REMOTE HOST IDENTIFICATION HAS CHANGED`, `%s: Could not resolve hostname %.100s: %s`, `ssh: connect to host %s port %s: %s`, `%s@%s: Permission denied (%s).`, `Timeout, server %s not responding.`, `Connection timed out during banner exchange`); the text of `Connection refused`, `No route to host` and `Connection timed out` comes from the C library and was not checked | manual | partly checked (design phase, 2026-11-10); not repeated after the build |
| G5 | `tests/test_client_errors.py::test_client_passes_discovered_socket_to_child`, `tests/test_sshenv.py::test_agent_socket_cache_dropped_after_agent_failure`; live: start the agent after the MCP server, call `queue_status` | unit test, live check | unit tests pass (2026-11-10, hub, Python 3.12); live check not verified: no node contact in this review |
| G6 | `tests/test_host_client.py::test_default_argv` (keepalive options); live: drop the network during a call | unit test, live check | unit test passes (2026-11-10, hub, Python 3.12); live check not verified: no node contact in this review |
| G7 | `tests/test_doctor.py` (all), `::test_exit_code_one_only_on_fail` | unit test | passes (2026-11-10, hub, Python 3.12) |
| G8 | `tests/test_node_doctor.py` (all) | unit test | passes (2026-11-10, hub, Python 3.12) |
| G9 new hub, old node | `tests/test_doctor.py::test_online_old_node_reports_unknown_not_fail`, `::test_online_against_old_node_stand_in` (the old-node stand-in `tests/oldnode.py`, served by a local subprocess, integration item 2), `tests/test_client_errors.py::test_normalize_hello_old_node` (canned three-key result), `tests/test_sync.py::test_old_node_stand_in_answers_like_the_old_node`, `::test_sync_pass_against_old_node_records_protocol_1`, `::test_mcp_nodes_after_old_node_pass`; live: the new hub against the node code installed on node1 | unit test, live check | unit tests pass (2026-11-10, hub, Python 3.12); live check not verified: no node contact in this review |
| G9 old hub, new node | `tests/test_node_hello.py::test_hello_keeps_protocol1_keys`, `tests/test_remote.py::test_attachment_named_part_not_lost` (upload under returned names), `tests/test_host_client.py::test_put_file_commit_visible_on_node` after merge | unit test | passes (2026-11-10, hub, Python 3.12) |
| G10 | `tests/test_jobs.py::test_cancel_matches_exact_job_id`, `::test_job_script_uses_absolute_launcher`, `::test_approve_key_set_requires_terminal`; `tests/test_mailbox.py::test_sanitize_part_and_tmp_suffix`; `tests/test_spawn.py::test_lock_with_dead_pid_is_stale`, `::test_lock_dead_leader_live_group_not_stale`, `::test_concurrent_takeover_one_holder`, `::test_responder_output_logged_mode_600`, `::test_responder_log_drops_result_text`; `tests/test_withheld.py::test_rejected_patterns_counted`; `tests/test_configure.py::test_default_withheld_source_is_json`, `::test_tilde_expanded_in_path_keys`, `::test_set_research_root_moves_dependent_defaults`; `tests/test_node_link.py::test_serve_local_initialize_has_instructions_and_version` | unit test | passes (2026-11-10, hub, Python 3.12); the node files were not rerun under Python 3.8 in this pass |
| Ruling R6, unit text and MCP entry | `tests/test_service.py::test_units_use_absolute_rb_path_and_no_ssh_auth_sock` (only `RB_HOST_CONFIG`: no `RB_HOST_ROOT` text in either service), `::test_units_rb_host_root_only_when_set`, `::test_unit_text_matches_sync_design` (both cases against the text of sync design §6.10); `tests/test_setup.py::test_mcp_command_carries_rb_host_variables` | unit test | passes (2026-11-10, hub, Python 3.12) |
| Ruling R9, missing `host.json` | `tests/test_sync.py::test_missing_host_json_one_line_error`, `tests/test_web.py::test_cli_web_serve_without_host_json` (exact line), `tests/test_doctor.py::test_missing_host_json_one_line_error_for_every_command`, `::test_invalid_host_json_one_line_error` (one line with the reason, §13 row 3) | unit test | passes (2026-11-10, hub, Python 3.12) |
| Anti-goal: `~/.claude.json` | `tests/test_setup.py::test_no_claude_json_write` | unit test | passes (2026-11-10, hub, Python 3.12) |
| Anti-goal: edits without confirmation | `tests/test_setup.py::test_ssh_block_shown_and_written_only_on_yes`, `::test_host_key_no_append_on_no`, `::test_print_only_writes_nothing`; `tests/test_service.py::test_install_writes_after_yes_with_backup`; `tests/test_node_install.py::test_apply_requires_terminal_and_yes` | unit test | passes (2026-11-10, hub, Python 3.12) |
| Anti-goal: sessions complete confirming commands | `tests/test_setup.py::test_setup_requires_terminal`, `::test_rb_agent_requires_terminal`; `tests/test_service.py::test_requires_terminal_unless_print`; `tests/test_jobs.py::test_approve_key_set_requires_terminal` | unit test | passes (2026-11-10, hub, Python 3.12) |
| Anti-goal: host key not shown | `tests/test_setup.py::test_host_key_appends_exact_scanned_bytes_on_yes`, `::test_host_key_deferred_on_first_run_then_compared`, `::test_host_key_backup_kept`, `::test_host_key_unfingerprintable_scan_is_not_appended` | unit test | passes (2026-11-10, hub, Python 3.12) |
| Anti-goal: key to foreign socket | `tests/test_sshenv.py::test_socket_owned_by_other_uid_skipped`, `::test_candidates_only_under_runtime_dir`, `::test_runtime_dir_rejects_group_writable`, `::test_inherited_sock_checked_like_candidates`, `::test_inherited_sock_outside_runtime_dir_never_loaded`; `tests/test_setup.py::test_forwarded_agent_gets_no_key`; `tests/test_doctor.py::test_offline_key_only_in_inherited_agent_warns` | unit test | passes (2026-11-10, hub, Python 3.12) |
| Anti-goal: paths in `hello` | `tests/test_node_hello.py::test_hello_state_has_no_paths`, `::test_unconfigured_creates_no_directories` | unit test | passes (2026-11-10, hub, Python 3.12) |
| Anti-goal: ten MCP tools | `tests/test_host_tools.py::test_exact_tool_set` | unit test | passes (2026-11-10, hub, Python 3.12) |
| No test reaches real ssh, agent or network | `tests/test_sshenv.py::test_no_test_reaches_real_runner`, `tests/test_client_errors.py::test_default_ssh_spawn_blocked_in_tests` (guards in `tests/conftest.py` on `sshenv.run`, `sshenv.run_interactive` and `client._popen`; `HOME` and `configure.claude_json_path` under `tmp_path`, `tests/test_sshenv.py::test_claude_json_path_isolated`); node: `tests/test_node_install.py` stub `PATH`, `tests/test_configure.py::test_default_config_paths_follow_home` | unit test | passes (2026-11-10, hub, Python 3.12) |
| Live link | `rb setup` on the hub, printed command on node1, `rb setup --node node1` again (host key), its doctor report all `ok` | live check | not verified: needs the user and node1; no node contact in this review |

## 11. Decided by the user

- 2026-11-05: the hub is the Linux server.
- The runtime environment is managed by uv.
- Goals stated for the 2026-11-10 review: material gathered on the hub; session conversations visible on a hub-served page; SSH transport with automatic update after the first link; experiment handling after autoresearch practice; the project not fixed to trm; flexible MCP synchronisation; scripts simplified so the README suffices.

## 12. My calls (user to check)

Coordinator rulings after the design audit (kept in the gitignored review working directory, not in this repository; the text of each is in §12), approved by the coordinator on 2026-11-10, not by the user. Earlier text in this document that left these points open for the coordinator now refers to them:
- R1. Two agent socket orders (§7.4): loading keys (`rb setup` step 6, `rb agent`) uses only runtime-directory sockets and starts `rb-ssh-agent` there when none answers; connecting (`NodeClient`) may also use `$SSH_AUTH_SOCK`. Contract §1.1 and §1.2 step 6 are superseded.
- R2. Host key comparison is deferred (§6.2 step 5, §7.3): a run that generated keys does not scan; the user reruns `rb setup --node NAME` after the node command printed the fingerprint. The step-count goal is "at most 17" (G1).
- R3. One sync pass runs `hello`, poll and `git_status` on one connection, then the due board sources (sync-and-page design §6.2); the sync implementer may edit `rb_host/store.py`, `rb_host/board.py` and `scripts/demo_dashboard.py`.
- R4. Sync code reads error codes with `getattr(exc, "code", None) or "transport"`; the test for a missing attribute uses a local stub exception class without `code`, not `TransportError` (§6.4 is unchanged).
- R5. The hub reads the node's git state from the key `tree` and falls back to `trm`; it does not accept a key named `research`.
- R6. Unit text is defined only in sync-and-page design §6.10: `Environment=RB_HOST_CONFIG=<absolute path of host.json>` always; `Environment=RB_HOST_ROOT=...` only when the installing shell has it set, otherwise the line is absent (not commented). The MCP registration printed by `rb setup` (step 8) carries the same `RB_HOST_*` variables; a service test covers the `RB_HOST_CONFIG`-only case (§10).
- R7. `rb web serve --bind` accepts only loopback addresses; any other value is refused with a message that names `ssh -N -L PORT:127.0.0.1:PORT <hub>` (sync-and-page design §7).
- R8. The board source errors `gpu_status_unavailable` and `no_gpus` are recorded in the sync status file's `board` map and do not make a sync pass fail (sync-and-page design §6.2).
- R9. When `host.json` is missing or invalid, `rb sync` and `rb web serve` print exactly one line, `error: no usable host.json at <path>; run: rb setup --node NAME --host HOST --user USER`, and exit 1. The coordinator applies the same helper to `rb share` and `rb board` at integration. As built (commit 5ec5f74): one helper, `configure.host_cfg` / `configure.host_json_error`, serves every `rb` command; the line is exactly this for a missing file and carries the reason in parentheses for an unreadable or invalid one (§13 row 3); `rb board show` still works without `host.json`.
- R13. Accepted as written in this design: the extra `hello.state` key `withheld_source_set` (§6.5); an old node's `withheld_extra` is reported but never better than `warn` (§6.3 `node_withheld`); `rb-node config set withheld_source` requires a terminal (§7.1); the responder log is filtered and logs older than 14 days are deleted (§6.7); the hub `withheld_hub` check fails on a pattern file with zero patterns (§6.3); `rb setup --research-root` (§6.2); `rb setup --node NAME` alone on a rerun (§6.2); the releases-directory symlink swap in `node-install.sh` (§6.6).

Coordinator decisions in force (contract §3), none approved by the user (note 2026-11-11: the user confirmed all six on 2026-11-10, `docs/HANDOFF.md` "Decided by the user on 2026-11-10"; the list is kept as written):
- The hub stores outgoing message bodies under `outbox/` (sync design, not this one).
- The ten MCP tools stay; flexibility comes from added result fields.
- The hub page has no approval form; approval stays `rb approve`.
- Unattended sync runs as systemd user units, installed only by `rb service install`.
- Windows instructions shrink to an appendix; Windows code paths stay.
- `trm` naming in config keys and on the wire is not renamed now.

Calls made in this design:
- Contract §1.1 to §1.4 as the scope (the contract itself is the coordinator's, not the user's).
- `rb setup` asks `y/N` before generating keys, although the contract lists only edits of existing files for confirmation; AGENTS.md asks for care around key generation.
- `rb setup` gains `--research-root DIR`, used only in the printed node command. Without it the node command is not paste-ready for a first install.
- `--yes-print-only` means: show everything, ask nothing, write nothing, no network traffic (no host key scan, no name lookup for `--hub-from`, offline doctor only), no terminal needed.
- Step 4 compares six options with the values given to `rb setup`; the doctor's `ssh_options` check compares only the two fixed ones (it has no expected values for the other four; `alias` and `key_file` cover them). The keepalive options are not compared, because `default_argv` passes them.
- `--yes-print-only` keeps the name the contract gives it, although the mode confirms nothing.
- The hub `agent` check is `fail` only when some bridge key needs a passphrase.
- A later `rb setup --node NAME` without `--host`/`--user` takes the values from `ssh -G`.
- A block that exists with other values, or is overridden by an earlier `Host *`, is reported, never rewritten.
- Host key: one scan, ed25519 first, one key type stored; hashed when `hashknownhosts yes`.
- Host key step deferred on a run that generated a key: the comparison happens on a rerun of `rb setup --node NAME` after the node command, because only the node command prints the fingerprint to compare with (audit finding B2; ruling R2). The contract's step order is kept; the cost is one extra user step (A5 in §16, which replaces the separate `rb doctor` step).
- Discovery for connecting accepts an inherited `$SSH_AUTH_SOCK` anywhere but applies the same ownership checks; guessed names only in the runtime directory; `/run/user/<uid>` when `XDG_RUNTIME_DIR` is unset.
- Keys are loaded only into runtime-directory sockets (§7.4 load order), never into an inherited `$SSH_AUTH_SOCK` outside it. This departs from contract §1.1 and §1.2 step 6, which name one order with `$SSH_AUTH_SOCK` first; ruling R1 supersedes those sections (audit finding B1).
- Discovery cache: 30 seconds per alias, dropped on agent-class failures.
- Rule 9 also covers a key file without a passphrase and an uncomputable fingerprint (reported as `node_refused_key`, with a hint naming both possibilities).
- `ssh` missing and malformed responses map to `closed` (the contract fixes ten codes).
- `str(TransportError)` carries the hint, so MCP tool results (`{"error": str(exc)}`) show the next command without a server change.
- Unconfigured node: `serve-remote` answers `hello` with `configured: false` and every other op with `not_configured`.
- `hello.state` gains `withheld_source_set` beyond the contract's list, so the hub can tell "no file configured" from "file failed to load".
- `withheld_extra` keeps its name and now counts compiled patterns.
- Doctor levels per check as in §6.3 (for example: harness items are `warn`; node `claude_bin` is `warn`; old-node unknowns are `warn`; an old node's `node_withheld` is always `warn`, whatever `withheld_extra` says; a missing hub pattern file is `fail`, as `rb config check` treats it today; a pattern file with no pattern is `fail` on both sides).
- `rb config check` and `rb-node config check` print only non-`ok` lines, as today; doctors print all.
- `sync_status` check reads the sync file defined in sync-and-page design §6.3, is skipped when absent, and uses that design's staleness rule (§6.8) instead of a rule of its own. Done at integration (commit ceb27f9): the hub doctor reads the file through `threads.read_status` / `threads.summary` (ruling R10); the earlier defensive reader of its own is gone.
- Node install: symlink swap with two releases kept; one gap on the first migration from a plain directory.
- `node-install.sh` logic lives in a new `rb_node/install.py`.
- `--apply-authorized-keys` asks `y` on a terminal and only prints otherwise (today it appends without asking).
- `--withheld-file` refuses a file that does not load cleanly or has no pattern; replacing a differing pattern file needs a terminal and `y`, with a backup (audit finding I5).
- My call (user to check): `rb-node config set withheld_source` requires a terminal, so a session cannot point the node at a narrower pattern file through that command either. Today it has no terminal check (`rb_node/cli.py:69-72`). `node-install.sh` therefore sets `withheld_source` inside `rb_node.install withheld`, not through `config set`. The safer option is in force (accepted by the coordinator, R13); the user may prefer to leave `config set` unchanged.
- Responder log kept to the last 64 KiB, without the model's `result` text, stderr masked, deleted after 14 days (the 14 days is my choice; audit finding I10).
- The `cli.py` helper for a missing or invalid `host.json` is named `_host_cfg()`; the hub-setup implementer applies it to `pending`, `approve`, `reject`, `harness`, `git-status` and its own commands. `sync` and `web` print the one-line error of ruling R9 inside `rb_host/sync.py` and `rb_host/web.py` (sync-and-page brief §3.7, §3.8). `share` and `board` keep their current messages in the implementer branches; the coordinator applies the same helper to them at integration (R9), so contract §1.2's "every command" is met after integration. As built after integration (commit 5ec5f74): `_host_cfg()` delegates to `configure.host_cfg`, and `rb sync`, `rb web serve`, `rb share`, `rb board`, `rb agent` and `rb service install` all print `configure.host_json_error`'s line.
- Other deviations from current behaviour, for the user to confirm: `rb-node config check` no longer reports an empty or missing `harness_root` (today `rb_node/configure.py:135-138`; the harness channel is optional, and `hello.state.harness_root_set` still tells the hub); the node `job_template` check gains a `fail` level when the list has no `{config}` (today every problem is one level; since PR 46 any of `{config}`, `{config_dir}`, `{config_stem}` satisfies it, §13 row 14); `config_keys` ignores keys starting with `_`.
- `tests/conftest.py` holds the hub-setup implementer's isolation fixture for external commands. The sync-and-page brief also allows a `conftest.py`; if both appear, the coordinator concatenates them at merge (the fixture is self-contained).
- The unit text written by `rb service install`, including which `Environment=` lines each service gets, is defined only in the sync-and-page design §6.10; this design and the hub brief refer to it and do not restate it.

## 13. Decision log (while building)

Rulings made by the implementers and the integrator where the code differs from the text above. None is approved by the user.

| # | Ruling | Cost if wrong | Where recorded |
|---|---|---|---|
| 1 | The bridge key is chosen by the generated key file names (`<node>_ed25519`, `<node>_harness_ed25519`; with `--keydir`, `rb setup` uses `<keydir>/<name>` directly), never by position in the `identityfile` list, and never falls back to OpenSSH's default list, a `Host *` value or a personal key. No match gives `no bridge IdentityFile configured for <alias>` (doctor `key_file`, `rb agent`). The text said "first `identityfile`" (§6.1, §6.2 step 4, §6.3), which let a `Host *` key read first be loaded into the agent or reported as the bridge key. | A user whose hand-written block names a bridge key with another file name is told no bridge key is configured and must rename the key or rerun `rb setup`. | integration item 6; commit d874b0d; `tests/test_sshenv.py::test_pick_identity_only_bridge_key_names_or_keydir`, `tests/test_doctor.py::test_offline_key_file_no_bridge_identity`, `tests/test_setup.py::test_host_star_identityfile_does_not_hide_bridge_keys`, `::test_differences_show_the_picked_identity` |
| 2 | Closed in commit 252345c (after this row was written): error classification (rules 6 to 9), discovery's socket preference and the doctor's `key_loaded` check pass `sshenv.key_names(node)`, so a custom alias finds its key (§6.4; `tests/test_sshenv.py::test_agent_socket_with_custom_alias_uses_node_key_names`). The next column is the cost the gap had while it was open. | With a custom alias, a key missing from the agent is reported as `node_refused_key` and sends the user to the node instead of `rb agent`; with several agents answering, `NodeClient` may pick one without the key, and doctor `key_loaded` may report the key as not loaded although another agent holds it. | §6.4; `rb_host/client.py` `classify`, `rb_host/sshenv.py` `agent_socket`; reported by the 2026-11-10 design finalizer |
| 3 | One helper for every `rb` command (`configure.host_cfg`, `configure.host_json_error`). The R9 line is exact for a missing `host.json`; an unreadable or invalid file adds the reason in parentheses (`(not valid JSON: <parse error>); fix or move it, then run: rb setup ...`). `rb board show` keeps working without `host.json` (laptop sources only). | A script that matches the exact R9 text for an invalid file does not match; the parse error text is shown on the terminal (it names the file position, not its content). | integration item 4; commit 5ec5f74; `tests/test_doctor.py::test_missing_host_json_one_line_error_for_every_command`, `::test_invalid_host_json_one_line_error`, `::test_board_show_works_without_host_json` |
| 4 | `rb setup` checks its arguments before step 1 (node name, characters in `--host`/`--user`, port range, `host.json` key types, bridge and harness keys resolving to one file) and exits 2 (wrong types: 1) with one line; a failed step 1 or 2 stops the run (§6.2). The text said every failed step lets setup continue. | A host or user value with whitespace or `#` that OpenSSH would accept through another syntax is refused; such a value would otherwise be written unquoted into `~/.ssh/config`. | integration item 8; commits d2de29f, a2ef122; `tests/test_setup.py::test_setup_host_json_wrong_types_one_line`, `::test_setup_host_json_invalid_stops` |
| 5 | MCP entry comparison: when `rb` runs from a git worktree and the registered entry differs only in `--directory`, setup step 8 counts it as registered and the doctor gives a `warn` (`from_worktree`) instead of `differs`; an entry whose arguments or `RB_HOST_*` variables differ is `differs` (§6.2 step 8, §6.3 `mcp_entry`). | A worktree run does not notice an entry that points at a stale main checkout with the same arguments; the main checkout's own run still compares the path. | integration item 9; commit fafe6e6; `tests/test_doctor.py::test_mcp_entry_from_worktree_is_only_a_warning`, `tests/test_setup.py::test_old_mcp_entry_without_rb_host_env_is_printed_again` |
| 6 | Host key step: the scan goes to the `hostname`/`port` that `ssh -G` reports for a defined alias; the scanned lines stay in memory and are fingerprinted through a temporary file that is removed at once; a scan that cannot be fingerprinted is not appended; with `HostKeyAlias` the host field is rewritten to that alias before the append; with `HostKeyAlias` and hashed `known_hosts` the lines are printed for the user to add (§6.2 step 5, §7.3 steps 3 to 5). The text said the bytes of a temporary file are appended unchanged. | With `HostKeyAlias`, the appended line is not byte-identical to the scan (only the host field differs; the key the user compared is the same). A user with a hashed `known_hosts` and `HostKeyAlias` adds the line by hand. | integration item 10; commits d2de29f, ef49060; `tests/test_setup.py::test_host_key_scan_uses_what_ssh_reports`, `::test_host_key_unfingerprintable_scan_is_not_appended`, `::test_host_key_appends_exact_scanned_bytes_on_yes` |
| 7 | `normalize_hello` raises `TransportError` (code `closed`) for a result that is not a JSON object and sets a non-integer `withheld_extra` to `None`; `rb doctor` and `rb sync` both read `hello` through it (§6.1). | A malformed `hello` shows as `closed` with the node-doctor hint instead of `internal`. | ruling R10; commits d3f8de5, ceb27f9; `tests/test_client_errors.py::test_normalize_hello_bad_values` |
| 8 | Doctor `sync_status` reads the status file through `threads.read_status` / `threads.summary` (900 s rule) and reports a pass left at `stage: "running"` with a `last_attempt_at` older than 900 s as "never finished" (§6.3). | A pass that legitimately runs longer than 900 s would be reported as unfinished; the unit's `TimeoutStartSec=240` makes that impossible under the timer. | integration item 3; commit ceb27f9; `tests/test_doctor.py::test_offline_sync_status_unfinished_pass`, `::test_offline_sync_staleness_is_900_seconds` |
| 9 | Output format: node doctor lines are `[<level>] <id>: <message>`; `rb doctor` ends with `summary: N ok, N warn, N fail`; `rb-node doctor` ends with the closing line of the check commands (`ok`, `N to fix`, `all ok, M warning(s)` or `N to fix, M warning(s)`; §6.3). The text gave one format for both sides. | A script that parses doctor output must handle two formats. | commits d4f54cc, ebaf71b |
| 10 | Node checks: `ak_duplicate` names three cases (line without the forced command; the harness line, hard rule 9; a second `serve-remote` line); `config_keys` also reports known keys with a value of the wrong type (dropped, not used); hub `host_json` reports wrong key types and skips the remaining checks (§6.3). | None beyond wording; a wrong-typed key is ignored as before, now reported. | integration items 8, 15; commits 09af851, bef535b, a2ef122; `tests/test_node_doctor.py::test_authorized_keys_two_serve_remote_lines_same_key`, `tests/test_doctor.py::test_offline_wrong_types_report_not_raise` |
| 11 | `node-install.sh` refuses to install when `~/.local/share/research-bridge` holds hub data (`host.json` or `ledger.jsonl`), requires the research root to be an existing directory, validates the keys and `--hub-from` before any write (exit 2), and keeps the release in use besides the two newest (§6.6). | A machine used as both hub and node under one account cannot install the node there (the two share that directory); the user installs under another account. | commits 684c948, 09af851; `tests/test_node_install.py::test_script_refuses_hub_data_directory`, `::test_script_bad_hub_from_refused_before_any_write` |
| 12 | `rb-node config init --force` without a terminal is refused when the existing `node.json` holds a value other than the default for a guarded key (`withheld_source`, `approval_path`, `read_roots`, `write_roots`; row 18), for the same reason as the terminal check on `config set` of those keys (§7.1). Corrected 2026-11-11: the text named `withheld_source` only. | A scripted re-initialisation over a custom pattern source or custom roots needs a terminal. | commit 09af851; `tests/test_node_install.py::test_config_init_force_keeps_custom_withheld_source_without_terminal` |
| 13 | `rb config check` has no checks of its own: it is the offline part of `rb doctor` restricted to problems (`doctor.main(None, offline_only=True, only_problems=True)`), so the two can never disagree (§6.1). Its old list (`configure.check`) is no longer what the command prints. | A check that only made sense in the old `config check` (and is not a doctor check) is no longer reported; the doctor's offline list is the single list. | commit d4f54cc ("classified config check"); `tests/test_doctor.py` |
| 14 | Corrected 2026-11-11. The node `job_template` check, the hub `node_job_template` check and `hello.state.job_template_set` accept any one of `{config}`, `{config_dir}`, `{config_stem}` (PR 46). The text named `{config}` only (§6.3 node table, §6.5). The same placeholders are replaced as substrings of an argument by `rb_node/jobs.py`, and a template with `{config_stem}` accepts `.yaml` configs only. | A reader who follows the old text adds `{config}` to a template that loads its config by name, or reads a `fail` where the code gives `ok`. | `rb_node/doctor.py` `CONFIG_PLACEHOLDERS`; `tests/test_node_doctor.py::test_job_template_empty_warn_missing_placeholder_fail`, `tests/test_node_hello.py::test_hello_job_template_set_needs_config_placeholder`, `tests/test_configure.py::test_node_check_template_placeholder`, `tests/test_jobs.py::test_template_dir_and_stem_placeholders` |
| 15 | Corrected 2026-11-11. The node table has a row `allowed_gpus` (`warn` when the list is empty or malformed; the node refuses `job_submit` with `no_allowed_gpus`), and `hello.state` has the key `allowed_gpus_set` (PR 47). The hub row `node_allowed_gpus` already existed; its text cited PR 46 and now cites PR 47. | A node with no `allowed_gpus` refuses every job, and the node-side doctor table did not list the check that says so. | `rb_node/doctor.py` (`config_checks`, `state`); `tests/test_node_doctor.py::test_allowed_gpus_empty_warns_and_list_is_ok`, `tests/test_node_hello.py::test_hello_allowed_gpus_set` |
| 16 | Corrected 2026-11-11. The hub check `data_root` fails when the data root has any group or other permission bit, with the next command `chmod 700 <path>`. The text tested only that the directory exists. | A reader trusts a data root of mode 755 because the table lists no mode check, although the doctor reports it as a `fail`. | `rb_host/doctor.py` (`data_root`); `tests/test_doctor.py::test_data_root_open_to_other_accounts_fails`; `docs/manual/hub-setup.md` |
| 17 | Corrected 2026-11-11. `scripts/node-install.sh --update` runs the pulled script afresh when the pull moves `HEAD` (§6.6). The text described the pull only. | A reader who changes the script expects the old file to finish the run, which `sh` does not do after a pull replaced the file; the node's install record then stayed at 0.1.0 while 0.2.0 was installed (first live run, PM-03). | commit 4ac2284; `scripts/node-install.sh`; `tests/test_node_install.py::test_script_update_runs_the_pulled_script` |
| 18 | Corrected 2026-11-11. `rb-node config set` needs a terminal for four keys (`GUARDED_KEYS`: `withheld_source`, `approval_path`, `read_roots`, `write_roots`), and `config init --force` without a terminal is refused when any of the four differs from its default (§7.1, row 12). The text named `withheld_source` only. | A reader treats `approval_path`, `read_roots` and `write_roots` as settable without a terminal and adds another control for them, or believes `allowed_gpus` and `job_template` are guarded, which they are not (`tests/test_configure.py::test_allowed_gpus_is_not_a_guarded_key`). | commit 47d4e43; `rb_node/cli.py`; `tests/test_configure.py::test_guarded_keys_need_a_terminal`, `tests/test_node_install.py::test_config_set_withheld_source_requires_terminal`, `::test_config_init_force_keeps_custom_withheld_source_without_terminal` (withheld source only for `init --force`; the other three keys follow the same loop in `rb_node/cli.py`) |
| 19 | Corrected 2026-11-11 (branch of the node fixes of that day, not yet merged when written). The node check `approval_path` uses the rule `hello` and `job_submit` use (`approval.root_holding_path`): the path must lie outside every read, write and mailbox root, with symbolic links resolved. The text named read and write roots only, and the check had its own loop, so a path under the mailbox root was `ok` in the doctor and refused at submit (audit item D7). | A reader puts the verifier under the mailbox root, where the hub writes attachments, and the doctor does not warn. | `rb_node/doctor.py` (`_approval_checks`), `rb_node/approval.py` (`root_holding_path`); `tests/test_node_doctor.py::test_approval_path_check_uses_the_submit_rule`, `tests/test_jobs.py::test_approval_path_inside_mailbox_is_refused` |
| 20 | Corrected 2026-11-11 (same branch). New node check `max_file`: `fail` when `max_file` in `node.json` is above 52428800 (hard rule 5); the loaded value is capped at 52428800, and `rb-node config set max_file` refuses a larger value (audit item D8). | A node owner sets a larger cap that has no effect on uploads and believes larger files pass. | `rb_node/doctor.py` (`config_checks`), `rb_node/configure.py` (`node_set`); `tests/test_configure.py::test_max_file_is_capped_at_the_protocol_limit` |
| 21 | Corrected 2026-11-11 (same branch). §5: `spawn._launcher`, the old name of `spawn.launcher_argv`, is no longer kept as an alias; callers use `spawn.launcher_argv`. | Code or a test that calls `spawn._launcher` fails. | `rb_node/spawn.py`; `tests/test_spawn.py::test_launcher_argv_is_what_callers_use` |

## 14. Left to the builder

- Exact wording of messages beyond the substrings pinned by tests.
- Column widths and colour of doctor output (no colour when stdout is not a terminal).
- Whether `rb doctor` gains `--json`.
- The precise `rb-node link` warning text about issue 41.

## 15. Open questions

- Should `node-install.sh` run `rb-node approve-key set` itself when no verifier exists and a terminal is present? Default: no; doctor prints it as the next command (one step remains).
- Should `rb-node approve-key set` over an existing verifier ask for the old passphrase first? Default: no in this branch.
- Should the hub doctor probe `approve_params` on an old node to learn whether a verifier exists? It would be accurate but is a second op; contract §1.2 says `hello` only. Default: no.
- Should `rb agent` also offer to start a supervised `ssh-agent` user unit? Default: no; the gcr socket or the started agent is used, and doctor reports when it is gone.
- Who moves `rb_host/harness.py` onto agent discovery, and when? Default: a follow-up change after this branch; until then `rb agent` prints the `export` line (§3).

## 16. User steps before and after

Before: survey `user-steps.md` §2, 16 hub steps and 8 node steps = 24, 3 hand transfers (public keys, withheld file, hub subnet), 7 documents.

After, same columns:

TTY (teletype) below means an interactive terminal.

| # | Step | Command | Input asked | TTY | Outside-repo edit | README alone |
|---|---|---|---|---|---|---|
| A1 | Install | `uv sync --extra host` | none | no | `.venv` in repo | yes |
| A2 | Link the node (hub part) | `rb setup --node node1 --host <NODE_HOST> --port <NODE_PORT> --user <NODE_USER> [--research-root DIR]` | `y` to generate keys, key passphrase twice per key, `y` for the ssh config blocks, passphrase at `ssh-add` (host key deferred, §7.3) | yes | `~/.ssh/research-bridge/`, `~/.ssh/config`, both after `y` | yes |
| A3 | Hub withheld file | copy the session-calendar pattern file to `<data_root>/withheld_patterns.json` (or the path `withheld_patterns_file` names) | file | no | data root | yes |
| A4 | MCP entry | paste the printed `claude mcp add-json ...` (1), then restart the Claude session once (2): two steps | none | no | `~/.claude.json` by the Claude CLI (does not ask) | yes |
| B1 | Code on the node | `git clone <REPO_URL>` | none | no | clone location | yes |
| B2 | Node withheld file | copy the same pattern file to `~/withheld-patterns.json` on the node with the user's own login, for example from the hub `scp -P <NODE_PORT> <pattern file> <NODE_USER>@<NODE_HOST>:withheld-patterns.json`; never through the alias `rb-node1`, whose key runs only the forced command | file | no | node home | yes |
| B3 | Link the node (node part) | paste the command printed by A2 | `--research-root` if not given, `y` for `authorized_keys` | yes | `authorized_keys` after `y`; `node.json`, `~/.local/bin/rb-node` and install directories without asking | yes |
| A5 | Host key and check | `rb setup --node node1` (rerun) | fingerprint comparison with the lines B3 printed, `y` | yes | `known_hosts` after `y` | yes |
| B4 | Approval passphrase | `rb-node approve-key set` | passphrase twice | yes | `~/.research-bridge/approve.json` | yes |
| B5 | Job command | `rb-node config set job_template '[...]'` (needed for jobs only) | project value | no | `node.json` | yes |
| B6 | Claude login on the node | `claude` (login) | login | yes | `~/.claude` | yes |
| B7 | Live session (optional) | `rb-node link --apply` | none | no | `<research root>/.mcp.json` | yes |
| A6 | Unattended sync and page | `rb service install` (1), then paste the printed `systemctl --user ...` line (2): two steps | `y` | yes | `~/.config/systemd/user/rb-*` after `y` | yes |
| A7 | First approval | `rb approve <job_id>` | `y/N`, approval passphrase | yes | none | yes |
| A8 | Per boot | `rb agent` | key passphrase | yes | none | yes |

Total: 17 steps (rows A1–A8 and B1–B7, with A4 and A6 counted as two steps each because each includes a pasted command), counting the per-boot step once as the survey did. The rerun A5 also runs the doctor, so no separate `rb doctor` step is needed. Hand transfers from hub to node: the pasted node command (carries both public keys and the hub address) and the withheld file; the host key fingerprint is compared by eye (as survey step H6). Files outside the repository edited by hand: none. Edited by a command that does not ask: `~/.claude.json` (the Claude CLI command the user pastes), `node.json` and `~/.local/bin/rb-node` (`node-install.sh`), 3 against 6 before. `~/.ssh/config`, `known_hosts`, `authorized_keys` and the unit files are written by commands after a shown change and `y`. Facts typed once: node name, host, port, user (A2), research root (A2 or B3).
