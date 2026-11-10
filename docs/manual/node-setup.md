# Node setup

A node runs `rb_node` (standard library only, Python 3.8 or later) and is reached from the hub over SSH (Secure Shell) with forced commands: the SSH key lets the hub run one fixed program and nothing else. The first node is `node1`. `scripts/node-install.sh` is the single entry point on the node: it installs the code, writes the wrapper and `node.json`, and prints or applies the two `authorized_keys` lines. Every command in this manual runs on the node console, by the user; a session needs the user's go-ahead for each command on the node (`AGENTS.md`). For the hub side see [hub-setup.md](hub-setup.md); the Windows-hub notes for the node are in Appendix A.

Placeholders: `node1` (node name), `<NODE_HOST>`, `<NODE_PORT>`, `<NODE_USER>` (the node's address, SSH port and login name), `<HUB_ADDR>` (the hub's address as the node sees it), `<HUB_SUBNET>` (the hub's network range). Abbreviations: MCP = Model Context Protocol; GPU = graphics processing unit.

## 1. Requirements

- Linux, `python3` 3.8 or later on `PATH`, and `git`. `node-install.sh` stops without them.
- `pdftotext` (package `poppler-utils`) to scan pdf files; without it pdf files are denied (`deny_unscannable`). The installer only notes its absence.
- The Claude Code CLI, if the node should answer messages with a server Claude session (§6). Non-interactive SSH often lacks it on `PATH`; the installer sets `claude_bin` to the first `claude` it finds on `PATH` when the current value is not an executable file, and `rb-node doctor` check `claude_bin` tells you if that is not enough.
- The research tree whose documents are shared (the "research root", `trm_root` in `node.json`; on `node1` the project described in [../projects/trm.md](../projects/trm.md)) and its job queue directory with `jobs/`, `processing/`, `done/`, `failed/`.
- A checkout of this repository on the node: `git clone <REPO_URL>` there, or a copy of the hub's checkout that includes `.git` (copy from the hub to the node; the node never opens a connection to the hub).
- The node must not be the hub: the installer refuses to run where `~/.local/share/research-bridge` holds `host.json` or `ledger.jsonl`.

## 2. Install: `scripts/node-install.sh`

Run on the node console, in the checkout. The hub prints the exact command for your node at the end of `rb setup` (hub manual §4); the shape is:

    scripts/node-install.sh \
      --research-root /home/<NODE_USER>/project/trm \
      --hub-key 'ssh-ed25519 AAAA... research-bridge-hub' \
      --harness-key 'ssh-ed25519 AAAA... research-bridge-harness' \
      --hub-from <HUB_ADDR> --withheld-file ~/withheld-patterns.json --apply-authorized-keys

Copy the hub's withheld pattern file to the node first (from the hub: `scp`; format and rules in §4.3). All flags are in §11.2. Run it with `--dry-run` first to see every action without writing anything.

What it does, in order (the script and `python3 -m rb_node.install` do all of it; nothing else is needed):

1. **Checks** python 3.8 or later, git, and that this is not a hub; when `--hub-key` and `--hub-from` are given, validates the public keys (type, base64, and that the bridge and harness keys differ) and `--hub-from` (addresses or CIDR ranges, comma-separated) before writing anything. Without `--research-root`, an existing `node.json` keeps its value; with no `node.json` it asks once on a terminal and otherwise stops with `give --research-root DIR`.
2. **`--update` only:** `git pull --ff-only` in the checkout (never a push); if the branch has no upstream it installs the current checkout.
3. **Code:** copies `rb_node/` into `~/.local/share/research-bridge/releases/<stamp>/` and swaps the symlink `~/.local/share/research-bridge/rb_node` to it atomically. It keeps the two newest releases and the one in use. The first run over a plain `rb_node` directory (code installed by the earlier by-hand copy) moves that directory to `releases/legacy/` and leaves a moment without code on that one run.
4. **Wrapper:** writes `~/.local/bin/rb-node` (mode 755) with the absolute path of the `python3` found now (§3).
5. **`node.json`:** `rb-node config init` if missing, then `rb-node config set trm_root <root>` (which also moves `queue_dir` and the queue entry of `write_roots` if they still have their defaults), then `claude_bin` as above.
6. **Withheld file** (`--withheld-file`): validates it, copies it to `~/.research-bridge/withheld-patterns.json` and sets `withheld_source` (§4.3).
7. **Mailbox:** creates `~/.research-bridge/mailbox/{in,out,state,state/acked}` with mode 700, then writes the install record `~/.research-bridge/install.json` (version, commit, dirty-file count of the checkout).
8. **`authorized_keys`:** prints the two lines it would install and the planned change (add, replace the line of the same key, or unchanged; it never removes a line). With `--apply-authorized-keys` on a terminal it saves `authorized_keys.bak.<stamp>`, asks `Apply? [y/N]` and writes the file with mode 600. Without a terminal, or if the file is a symbolic link, it only prints; apply the lines by hand (§5). Without `--hub-key` and `--hub-from` it says what to give.
9. **Host key fingerprints:** prints the node's SSH host key fingerprints, to compare with what `rb setup --node node1` shows on the hub.
10. **`rb-node doctor`** (§7.2), then the reminder `Next (you, on this console): rb-node approve-key set`.

Then, on the node console: `rb-node approve-key set` (§4.2). On the hub, rerun `rb setup --node node1` and compare the fingerprint.

## 3. Wrapper and release directories

`~/.local/bin/rb-node`, mode 755, written by the installer:

```sh
#!/bin/sh
PYTHONPATH="$HOME/.local/share/research-bridge" exec /usr/bin/python3 -m rb_node.cli "$@"
```

The python path is the absolute one found at install time (here `/usr/bin/python3` as an example), so the wrapper does not depend on the `PATH` an SSH forced command has. `rb-node doctor` check `wrapper` warns if that python is missing or older than 3.8. Layout:

| Path | Content |
|---|---|
| `~/.local/share/research-bridge/rb_node` | Symlink to the active release. |
| `~/.local/share/research-bridge/releases/<stamp>/rb_node` | Copies of the code; `legacy` is the pre-installer copy. |
| `~/.local/bin/rb-node` | The wrapper. |
| `~/.research-bridge/` (mode 700) | `node.json`, `install.json`, `approve.json`, `withheld-patterns.json`, `audit.jsonl`, `mailbox/`. Not in git. |

## 4. `node.json` and its related files

`~/.research-bridge/node.json`, mode 600; `RB_NODE_CONFIG` overrides the path (tests use it). Paths come only from this file; the hub cannot supply paths (`AGENTS.md` hard rule 4). A leading `~` in a path value is expanded when the file is read. Unknown keys are ignored (`rb-node doctor` warns about them, except keys starting with `_`).

Edit it on the node console only, with `rb-node config` (no bridge operation reaches it):

    rb-node config path                  # print the path
    rb-node config init [--force]        # write the defaults (mode 600)
    rb-node config show                  # print it
    rb-node config set KEY VALUE         # one key; lists and numbers as JSON, e.g. '["a", "b"]'
    rb-node config check                 # non-ok doctor lines for the config only; ends with "ok", "N to fix", "all ok, M warning(s)" or "N to fix, M warning(s)"

`init` refuses to overwrite an existing file without `--force`, and `--force` outside a terminal refuses if it would reset a customised `withheld_source`. `set withheld_source` needs a terminal (a session cannot weaken the masking), and `set` accepts only known keys of the right type. `config check` exits 1 only when a check is `fail`; its `--help` text says "exit 1 if anything" (§12.1).

### 4.1 Keys

| Key | Type | Default | Meaning |
|---|---|---|---|
| `trm_root` | path | `~/project/trm` | Root of the research tree (the "research root"). Relative `read_roots` and `experiments_dir`, `hypotheses_path` are joined to it. |
| `read_roots` | list of paths | `lab/registry/`, `lab/experiments/`, `lab/reports/`, `reports/figures/`, `~/.research-bridge/mailbox/out/` | Directories the hub may read through `read_doc` and `fetch_file`. Check them against the real tree (the tree was restructured on 2026-10-15; issue 9 is open). |
| `write_roots` | list of paths | `~/.research-bridge/mailbox/in/`, `<trm_root>/scripts/queue/jobs` | The only places the node writes for the hub: the mailbox inbox and the queue `jobs/` directory. |
| `queue_dir` | path | `<trm_root>/scripts/queue` | Queue root (`jobs/`, `processing/`, `done/`, `failed/`). |
| `withheld_source` | path or `null` | `~/.research-bridge/withheld-patterns.json` | Withheld pattern file (§4.3). `null` or `""` means none: only the five fallback patterns apply. The file does not exist after `config init`, and the doctor fails until you install one. |
| `claude_bin` | path | `~/.local/bin/claude` | Absolute path of the Claude CLI for the responder. |
| `job_template` | list of strings | `[]` | argv with a config placeholder (`{config}`, `{config_dir}` or `{config_stem}`, §4.1.1), for example `["uv", "run", "pretrain.py", "--config", "{config}"]`. Empty means `job_submit` is refused (`no_job_template`). Set by the node's owner. |
| `allowed_gpus` | list of integers | `[]` | GPU indices a bridge job may use: the node owner's GPUs, for example `[4, 5, 6, 7]`. Empty means `job_submit` is refused (`no_allowed_gpus`) and `run-job` starts nothing. A GPU outside the list, or more than one GPU, is refused with `invalid`. Set by the node's owner. |
| `max_file` | positive integer | 52428800 (50 MB) | Attachment cap in bytes. |
| `mailbox_root` | path | `~/.research-bridge/mailbox` | Mailbox (`in/`, `out/`, `state/`). |
| `audit_path` | path | `~/.research-bridge/audit.jsonl` | Audit log (no message bodies). |
| `approval_path` | path | `~/.research-bridge/approve.json` | Job approval verifier (§4.2). Keep it outside every read and write root. |
| `experiments_dir` | path under `trm_root` | `lab/experiments` | Where `read_doc` finds `EXP-nnn`: a file `EXP-nnn.md` or exactly one `EXP-nnn_*.md`. Must lie inside a read root, else `read_doc` by id is denied. |
| `hypotheses_path` | path under `trm_root` | `lab/registry/HYPOTHESES.md` | File whose section for `H-nnn` `read_doc` returns. Must lie inside a read root. |
| `harness_root` | path | `""` | The node's `~/.claude` for the harness channel. Empty means harness push and pull are refused (`no_harness_root`). |

Setting `trm_root` also updates `queue_dir`, the queue entry of `write_roots` and an old default `withheld_source` if they still have the values derived from the previous root.

### 4.1.1 `job_template` placeholders

The config is stored as `rbjob-<job_id><ext>` under the mailbox state directory. `{config}` is the stored config's path, `{config_dir}` its directory and `{config_stem}` its name without the extension. The last two are for a loader that finds the config by name, such as Hydra (`--config-dir {config_dir} --config-name {config_stem}`). With such a template:

- only `.yaml` configs are accepted (Hydra does not find `.yml` or `.json` by name);
- the submitted file is the whole primary config, so it must list the tree's base config in `defaults` (for example `defaults: [cfg_pretrain, _self_]`) to inherit it;
- the node stores the submitted file as `rbjob-<job_id>.yaml` and passes that name, not the submitted one. The tree's own config directory is searched first, so a file stored under a name the tree also uses would be ignored without an error.

### 4.2 Approval passphrase (user runs, on the node console)

    rb-node approve-key set      # asks for a passphrase (at least 12 characters) twice

This writes the verifier (salt, iteration count, sha256 of the derived key; mode 600) to `approval_path`. The passphrase itself is stored nowhere. Run it in a terminal on the node, not through the bridge: the bridge key's forced command cannot reach it. `rb-node approve-key clear` (asks `y/N`) removes the verifier, after which no job can be queued or cancelled. Until it is set, every approval fails with `not_authorized`. After five wrong keys the node waits 30 s before the next try, doubling up to 1 h (`approval_wait`); a right key resets the count.

### 4.3 Withheld pattern file

The node always applies five built-in fallback patterns (`AGENTS.md` hard rule 3). The file adds more.

- **Where it must be:** the path in `withheld_source`, by default `~/.research-bridge/withheld-patterns.json` (hyphen in the name; the hub's copy is `withheld_patterns.json` with an underscore). It must be readable by the account that SSH forced commands run as.
- **How to install it:** `scripts/node-install.sh --withheld-file FILE`. It checks that the file is valid JSON, has at least one pattern and that every pattern compiles; if not, nothing is copied. It then copies it (mode 600, a backup of an older copy first) and sets `withheld_source`. Replacing a different file asks `Replace? [y/N]` on a terminal and tells you the old and new pattern counts, and warns if the new file has fewer. Without a terminal it refuses. `rb-node config set withheld_source PATH` is the by-hand form and also needs a terminal.
- **Format:** JSON, one of: a list of regular-expression strings; `{"patterns": [...]}`; `{"families": [{"patterns": [...]}, ...]}`. YAML is not parsed (no PyYAML dependency); `exp_id_patterns` keys are ignored on purpose. An invented example: `{"patterns": ["secretproject_[0-9]+"]}`.
- **Effect:** text documents have lines that match blanked; pdf, tex and images that match are denied; unknown extensions are denied; poll bodies are masked and attachments with matching names are dropped.
- **How to see that it loaded:** `rb-node doctor` check `withheld` says how many patterns loaded; on the hub `rb doctor` check `node_withheld` and the `withheld_extra` field of `nodes` say the same (`0` means the node loaded no file).

## 5. `~/.ssh/authorized_keys`

`node-install.sh` writes these two lines (`--apply-authorized-keys`). The program path is `<bindir>/rb-node` with `<bindir>` the installer's `~/.local/bin`, as an absolute path:

```
restrict,from="<HUB_ADDR>",command="/home/<NODE_USER>/.local/bin/rb-node serve-remote" ssh-ed25519 <PUBKEY> research-bridge-hub
restrict,from="<HUB_ADDR>",command="/home/<NODE_USER>/.local/bin/rb-node harness-receive" ssh-ed25519 <PUBKEY> research-bridge-harness
```

`<PUBKEY>` is the base64 field of the matching hub `.pub` file. `--hub-from` takes one or more addresses or CIDR ranges, comma-separated, and is written into `from="..."` normalized (use `<HUB_SUBNET>` if the hub's address can change).

- `restrict` turns off pty, port, agent and X11 forwarding.
- `command=` ignores whatever command the client asks for. The message key can only run `serve-remote`; the harness key only `harness-receive`, which accepts `harness-push`, `harness-send` or nothing and exits 1 on anything else.
- `from=` limits the source address; if a router translates addresses between hub and node, use the address the node sees.
- Other keys in the file are not affected. A shared, unrestricted key keeps its shell; the "no unauthorized read or write" rule holds fully only after such keys are removed or restricted (pending decision in `docs/HANDOFF.md`).

<details>
<summary>By hand: editing authorized_keys without the installer</summary>

Append the two lines above, with the real address and the matching `.pub` field, to `~/.ssh/authorized_keys` (mode 600; `~/.ssh` mode 700). The two keys must differ, and neither key may appear on any other line of the file (`rb-node doctor` check `ak_duplicate`). Check the lines with `rb-node doctor` (§7.2) afterwards. Print the node's host key fingerprints with `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`.

</details>

## 6. Server Claude session (the responder)

When a message is committed, `serve-remote` starts `rb-node respond <msg_id>` as a detached process. It runs `claude -p` in `trm_root` with `serve-local` as its only MCP server and these limits: one session at a time (lock file, stale after timeout + 300 s), wall timeout 1800 s, `--max-turns 40`, tools = `serve-local` + Read/Grep/Glob; Bash, Write, Edit, WebFetch and WebSearch are disallowed. The session writes only through the `reply` tool. A failure posts a `responder_failed` event to the outbox.

The `serve-local` tools are `inbox_list`, `inbox_read`, `attachment_path`, `reply`, `post_event`. A server session cannot submit jobs.

Each run appends facts to `~/.research-bridge/mailbox/state/respond-<msg_id>.log` (mode 600; JSON status fields and a masked tail of stderr, at most 64 KB); logs older than 14 days are deleted. If a message waits more than 10 minutes with no running responder, or stays in `responding` beyond the lock's stale time, `rb-node doctor` check `stuck_messages` names it and the command to read its log or rerun it (`rb-node respond <msg_id>`).

## 7. Checks

### 7.1 Security checks from the hub (provisioning step B2)

Run after hub manual §4 to §6. The results go in `docs/provisioning.md` §Results with placeholders.

| Command on the hub | Expected |
|---|---|
| `ssh rb-node1` (send nothing) | No shell prompt. |
| `ssh rb-node1 cat /etc/passwd` | No passwd contents. |
| `ssh rb-node1-harness <anything except harness-push / harness-send>` | Exit 1. |
| `read_doc("node1", "../../.ssh/authorized_keys")` from a Claude session | `denied` |
| `send_message("node1", "test", [<small pdf>])`, then `poll` | Reply stored under `<data root>/inbox/node1/<msg_id>/` with `provenance.json` |
| `submit_job` with `gpu_hours=0.01`, then `rb approve` | `job_finished` event with status `done` or `budget_exceeded` |

Send and read checks are meaningful only after the node loaded a withheld pattern file (§4.3).

### 7.2 `rb-node doctor` (on the node console)

    rb-node doctor

Read-only: it creates no directory and writes no audit record. Output is `[ok|warn|fail] <id>: <message>`, and under each non-ok line `      next: <command>`; it ends with `ok`, `N to fix`, `all ok, M warning(s)` or `N to fix, M warning(s)` (failures and warnings counted apart). Exit 1 only if some check is `fail`. It never prints key material or pattern text.

| id | Level if not ok | What a failure means | Next |
|---|---|---|---|
| `config` | fail | `node.json` is missing, not valid JSON or not an object; nothing else is checked. | `rb-node config init` or rerun `scripts/node-install.sh` |
| `config_keys` | warn | An unknown key or a value of the wrong type is ignored. | `rb-node config show` |
| `research_root` | fail | `trm_root` is not a directory. | `rb-node config set trm_root DIR` |
| `read_roots` | warn | A read root does not exist. | `mkdir -p DIR` or `rb-node config set read_roots '[...]'` |
| `doc_paths` | warn | `experiments_dir` or `hypotheses_path` is outside every read root, so `read_doc` by id is denied. | `rb-node config set KEY PATH` |
| `queue_dir` | warn | `queue_dir/jobs` is missing or not writable: jobs would go where no runner watches. | `mkdir -p DIR/jobs` or set `queue_dir` |
| `withheld` | fail if the file is missing, unreadable, not valid JSON, empty, or has patterns that do not compile; warn if `withheld_source` is unset | Only the five fallback patterns apply (or the file is broken). | `scripts/node-install.sh --withheld-file FILE` or `rb-node config set withheld_source PATH` |
| `approval` | fail | The verifier is missing or unreadable: every `job_submit` and `job_cancel` is refused. | `rb-node approve-key set` |
| `approval_path` | fail | `approval_path` is inside a read or write root, where the hub could reach it. | `rb-node config set approval_path ~/.research-bridge/approve.json` |
| `job_template` | warn if empty, fail if it has none of `{config}`, `{config_dir}`, `{config_stem}` | Jobs are refused (`no_job_template`) or cannot receive their config file. | `rb-node config set job_template '[...,"{config}"]'` |
| `allowed_gpus` | warn if empty | `allowed_gpus` is empty or malformed: every `job_submit` is refused (`no_allowed_gpus`). | `rb-node config set allowed_gpus '[4, 5, 6, 7]'` (your own GPU indices) |
| `claude_bin` | warn | The responder cannot start; messages wait for a live session. | `rb-node config set claude_bin PATH` |
| `pdftotext` | warn | pdf files are denied. | install `poppler-utils` |
| `ak_bridge` | fail | `authorized_keys` has no `serve-remote` line, or it lacks `restrict` or `from=`, or its command path is not an absolute existing executable. The hub will be refused (`node_refused_key`). | `scripts/node-install.sh --hub-key '...' --hub-from ADDR --apply-authorized-keys` |
| `ak_harness` | warn | Same for the `harness-receive` line; only the harness channel is affected. | same with `--harness-key` |
| `ak_duplicate` | fail | The bridge key also appears on another line, without the forced command or as the harness key (`AGENTS.md` hard rule 9). | remove that line from `~/.ssh/authorized_keys` |
| `mailbox` | warn | `mailbox/{in,out,state}` is missing or does not have mode 700. | rerun `scripts/node-install.sh` |
| `responder_lock` | warn | A responder lock is left by a process that no longer runs, or is older than timeout + 300 s. | `rm ~/.research-bridge/mailbox/state/responder.lock` |
| `stuck_messages` | warn | A message waits unanswered or is stuck in `responding` (§6). | `rb-node respond <msg_id>` or read the log |
| `install` | warn | No install record, or its version differs from the running code. | rerun `scripts/node-install.sh` |
| `wrapper` | warn | The wrapper is missing, uses the `PATH` python, or its python is missing or older than 3.8. | rerun `scripts/node-install.sh` |

The hub's `rb doctor` runs a short online version over SSH (hub manual §10.2) from the `hello` state (§12).

## 8. Budget enforcement

An approved job's queue file wraps the template command in `rb-node run-job --gpus ... --gpu-hours ...`. The wrapper stops the job at wall time `gpu_hours / len(gpus)` (status `budget_exceeded`). Cancel requests are polled every 10 s. `job_submit` pins the research tree's `HEAD` in `state/git/<job_id>.json`; `run-job` records `git_submit` and `git_start` in the job record, and the `job_finished` event carries `git_head`.

Which GPU the job gets: the node's queue runner has one worker per GPU and exports that GPU as `CUDA_VISIBLE_DEVICES`. A job queued through the bridge asks for one GPU from `allowed_gpus`, and the wrapper runs it on the GPU of the worker that claimed it, which can differ from the index in the request (the job record and the `job_finished` event then carry `gpus_used`). The wrapper starts nothing on a GPU outside `allowed_gpus`: the job ends as `failed` with reason `gpu_not_allowed` and exit code 126. Run from the console without a worker, the wrapper sets `CUDA_VISIBLE_DEVICES` to the `--gpus` value.

## 9. Updating and removing

**Update:** in the checkout on the node, `scripts/node-install.sh --update` (pulls with `--ff-only`, copies a new release, swaps the symlink, rewrites the install record, runs the doctor). `node.json`, the mailbox and the approval verifier are kept. Needs the user's go-ahead for the session case. The hub shows the difference as `node_version` in `rb doctor`.

**State on 2026-11-10:** the registered node still runs `rb_node` 0.1.0, the code before this branch. That code has no `doctor`, no `link`, and answers `hello` without a protocol field; the hub treats it as protocol 1 and reports its checks as `unknown`. The first run of `scripts/node-install.sh` from a checkout of this branch updates it (§2, step 3 describes the one-time move of the old directory).

**Remove:** delete the two `authorized_keys` lines, then `~/.local/bin/rb-node`, `~/.local/share/research-bridge/` and, once its contents are no longer needed, `~/.research-bridge/`.

## 10. Git tracking and the live research session

- **Git state, read only, without file names or commit subjects:** `rb-node git-status` (node console), the `git_status` bridge operation, and `rb git-status --node node1` (hub) report branch, HEAD, dirty-file count, ahead/behind and the origin URL (credentials removed) for `trm_root` and for the installed code. Every `rb sync` pass reads it.
- **Live session in the research tree:** `rb-node link [DIR] [--apply]` registers `rb-node serve-local` as a project MCP server, so a Claude session started in `DIR` (default `trm_root`) can read hub messages and call `reply` and `post_event`. Without `--apply` it prints the `.mcp.json` it would write:

      {"mcpServers": {"rb-node": {"type": "stdio", "command": "/home/<NODE_USER>/.local/bin/rb-node", "args": ["serve-local"]}}}

  (plus `"env": {"RB_NODE_CONFIG": ...}` if that variable is set). With `--apply` it creates `DIR/.mcp.json`; if the file exists it changes nothing and prints the `claude mcp add --scope project rb-node -- <rb-node> serve-local` command to run instead. It needs `~/.local/bin/rb-node` (run the installer first). Claude Code may ask you to approve a project MCP server the first time. It prints this warning, and it is current: the spawned responder (§6) and a live session are not arbitrated, so both can answer the same message (GitHub issue 41). If you use a live session, consider whether the responder should be off (`claude_bin` pointing at no executable makes `rb-node doctor` warn and the responder not start).

## 11. Reference: commands

### 11.1 `rb-node` subcommands

| Subcommand | Who runs it | Does |
|---|---|---|
| `serve-remote` | the hub's bridge key (forced command) | Serves hub requests on stdin and stdout. Without a valid `node.json` it stays alive and answers `hello` with `state.configured: false`. |
| `harness-receive` | the hub's harness key (forced command) | Routes on `SSH_ORIGINAL_COMMAND`: `harness-send` pulls, empty or `harness-push` stages into staging directories only; anything else exits 1. No apply command exists. |
| `serve-local` | the server Claude session or a live session | MCP server with `inbox_list`, `inbox_read`, `attachment_path`, `reply`, `post_event`. |
| `respond MSG_ID` | `serve-remote`, or the user | Runs one server Claude session for one message (§6). |
| `run-job --gpus G[,G...] --gpu-hours H --job-id ID -- ARGV...` | the queue | Budget wrapper (§8). |
| `approve-key set` / `approve-key clear` | the user, terminal | §4.2. |
| `config path\|init [--force]\|show\|set KEY VALUE\|check` | the user | §4. |
| `git-status` | the user | Prints the git state of `trm_root` and the install record as JSON. |
| `install-record CHECKOUT` | `node-install.sh` | Writes `~/.research-bridge/install.json`. |
| `doctor` | the user | §7.2. |
| `link [DIR] [--apply]` | the user | §10. |

### 11.2 `scripts/node-install.sh` flags

| Flag | Meaning |
|---|---|
| `--research-root DIR` (alias `--trm-root`) | The research tree on this node; sets `trm_root` and the paths derived from it. Must be an existing directory. |
| `--hub-key 'KEY'` | The hub's bridge public key, inline (`type blob [comment]`). |
| `--hub-pubkey FILE` | The same, from a file. |
| `--harness-key 'KEY'`, `--harness-pubkey FILE` | The hub's harness public key. Optional; without it only the bridge line is handled. |
| `--hub-from ADDR` (alias `--hub-subnet`) | Value for `from="..."`: addresses or CIDR ranges, comma-separated. Needed with `--hub-key` for the lines to be printed. |
| `--withheld-file FILE` | §4.3. |
| `--apply-authorized-keys` | Show the change to `~/.ssh/authorized_keys` and apply it after `y/N` on a terminal. |
| `--update` | `git pull --ff-only` in this checkout first. |
| `--dry-run` | Print every action, write nothing. |
| `-h`, `--help` | Usage. |

An unknown flag prints the usage and exits 2.

## 12. The hello operation (protocol 2) and the other operations

The hub sends `hello` first. A node of protocol 2 (`rb_node` 0.2.0 and later) answers with `node`, `version`, `withheld_extra` (patterns loaded from the file, besides the fallback), `protocol` (the number 2), `ops` (the sorted list of operations it serves) and `state`, a map of booleans and counts without any path or pattern text; a node of the older code omits `protocol` and `state`, and the hub treats it as protocol 1. A node whose `node.json` is missing or invalid still answers `hello` with `state.configured` false and `ops` `["hello"]`, and answers every other operation with `not_configured`.

`state` keys: `configured`, `approval_verifier`, `job_template_set`, `allowed_gpus_set`, `withheld_source_set`, `withheld_loaded`, `withheld_rejected` (patterns that do not compile), `harness_root_set`, `claude_bin_found`, `queue_dir_exists`, `python`. The other operations: `msg_begin`, `put_chunk`, `msg_commit`, `poll`, `ack`, `get_file`, `read_doc`, `queue_status`, `gpu_status`, `job_submit`, `job_cancel`, `approve_params`, `git_status`.

### 12.1 Differences between the documents and the code

Recorded here so a reader is not surprised:

- `rb-node config check --help` and `rb config check --help` say "exit 1 if anything"; the code exits 1 only when a check is `fail`, not on `warn`.
- The git operation sends its tree under the key `trm`; the hub accepts `tree` first and falls back to `trm`.
- The package version in `pyproject.toml` is 0.1.0; the version the node reports is `rb_node.__version__`, 0.2.0.

### 12.2 Removed scripts

`scripts/hub-connect.sh`, `scripts/hub-agent.sh` and `scripts/trm-link.sh` no longer exist. Their work is done by `rb setup`, `rb agent` (hub manual §4) and `rb-node link` (§10).

## Appendix A. Windows hub notes (not maintained since 2026-11-05)

Last checked on 2026-11-05 with the laptop as hub; not kept in step with the code.

- Copy the code with LF line endings. On a Windows hub, check out with `core.autocrlf=input` or convert first; CRLF breaks the wrapper script. The installer today runs from a checkout on the node, so this matters only if the checkout is made on Windows and copied.
- The hub-side checks of §7.1 name the laptop paths in the old manual: replies were stored under `D:/raw/research-bridge/inbox/node1/<msg_id>/`.
- `from=` in `authorized_keys` was the laptop's subnet (`research-bridge-laptop` in the old comment). The installer now writes the comment `research-bridge-hub` and the hub's address.
- The by-hand install of the first node was: `ssh node1 "mkdir -p ~/.local/share/research-bridge ~/.local/bin ~/.research-bridge && chmod 700 ~/.research-bridge"` then `scp -r rb_node node1:~/.local/share/research-bridge/` (with `node1` the ordinary login alias, not the restricted `rb-node1`) and the three-line wrapper of §3 with `python3` instead of an absolute path. `scripts/node-install.sh` replaces it.
