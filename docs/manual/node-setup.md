# Node setup

A node runs `rb_node` (standard library only, Python 3.8 or later) and is reached from the hub over SSH with forced commands. The first node is node1 (Linux, Python 3.12). Every command in this manual runs on the node and needs the user's go-ahead (`AGENTS.md`). For the hub side see [hub-setup.md](hub-setup.md).

## 1. Requirements

- Python 3.8 or later as `python3`.
- `pdftotext` (poppler) for scanning pdf files; without it pdf files are denied (`deny_unscannable`).
- The Claude Code CLI, if the node should answer messages with a server Claude session. Non-interactive SSH often lacks it on `PATH`; put its absolute path in `claude_bin` (§4).
- The research working tree whose documents are shared (on node1 the `trm` tree, `trm_root`), and its job queue directory with `jobs/`, `processing/`, `done/`, `failed/`.

## 2. Copy the code

Copy with LF line endings. On a Windows hub, check out with `core.autocrlf=input` or convert first; CRLF breaks the wrapper script.

    ssh <node> "mkdir -p ~/.local/share/research-bridge ~/.local/bin ~/.research-bridge && chmod 700 ~/.research-bridge"
    scp -r rb_node <node>:~/.local/share/research-bridge/

Here `<node>` is the node's ordinary login alias (on node1, the existing `node1` alias), not the restricted `rb-<node>` alias, which cannot run commands.

## 3. Wrapper

`~/.local/bin/rb-node`, mode 755:

```sh
#!/bin/sh
PYTHONPATH="$HOME/.local/share/research-bridge" exec python3 -m rb_node.cli "$@"
```

Subcommands: `serve-remote` (hub requests on stdin), `serve-local` (MCP for the server Claude session), `respond <msg_id>` (run one server session), `run-job --gpus G --gpu-hours H --job-id ID -- <argv>` (budget wrapper), `harness-receive` (harness forced command).

## 4. `~/.research-bridge/node.json`

Start from `deploy/node.json.example`. Paths come only from this file; the hub cannot supply paths (`AGENTS.md` hard rule 4). Mode 600.

| Key | Meaning |
|---|---|
| `trm_root` | Root of the research working tree. Relative read roots are joined to it. |
| `read_roots` | Directories the hub may read through `read_doc` / `fetch_file`. List current paths; the example still has names from before the server's 2026-10-15 restructuring. |
| `write_roots` | Only the mailbox inbox and the queue `jobs/` directory. |
| `queue_dir` | Queue root (`jobs/`, `processing/`, `done/`, `failed/`). |
| `withheld_source` | File with withheld patterns: a JSON list, `{"patterns": [...]}` or `{"families": [{"patterns": [...]}]}`. YAML is not parsed (no PyYAML); with a YAML file only the fallback patterns apply. |
| `claude_bin` | Absolute path of the Claude CLI. |
| `job_template` | argv list with a `{config}` placeholder, for example `["uv", "run", "pretrain.py", "--config", "{config}"]`. Empty means `submit_job` is refused with `no_job_template`. The node's owner sets it. |
| `max_file` | Attachment cap in bytes (default 50 MB). |
| `mailbox_root`, `audit_path` | Under `~/.research-bridge/`. |
| `harness_root` | The node's `~/.claude`. Empty means harness push and pull are refused (`no_harness_root`). |
| `approval_path` | Job approval verifier, default `~/.research-bridge/approve.json`. Keep it outside `read_roots` and `write_roots`. Missing means `job_submit` and `job_cancel` are refused (`not_authorized`). |

`RB_NODE_CONFIG` overrides the path (tests use it).

Withheld handling is always on: the fallback patterns listed in `AGENTS.md` hard rule 3 apply even if `withheld_source` is missing. Text documents have hit lines blanked; pdf, tex and images that match are denied; unknown extensions are denied.

### Approval passphrase (user runs, on the node console)

    rb-node approve-key set      # asks for a passphrase (at least 12 characters) twice

This writes the verifier (salt, iteration count, sha256 of the derived key; mode 600) to `approval_path`. The passphrase itself is not stored anywhere. Run it in a terminal on the node, not through the bridge: the bridge key's forced command cannot reach it. `rb-node approve-key clear` removes the verifier, after which no job can be queued or cancelled. Until it is set, every approval fails with `not_authorized`. After five wrong keys the node waits 30 s before the next try, doubling up to 1 h; a right key resets the count.

## 5. `~/.ssh/authorized_keys` (user runs)

Append two lines based on `deploy/authorized_keys.example`, replacing `<HUB_SUBNET>` with the hub's subnet and `<PUBKEY>` with the base64 field of the matching `.pub` file:

```
restrict,from="<HUB_SUBNET>",command="<NODE_HOME>/.local/bin/rb-node serve-remote" ssh-ed25519 <PUBKEY> research-bridge-hub
restrict,from="<HUB_SUBNET>",command="<NODE_HOME>/.local/bin/rb-node harness-receive" ssh-ed25519 <PUBKEY> research-bridge-harness
```

- `restrict` turns off pty, port, agent and X11 forwarding.
- `command=` ignores whatever command the client asks for. The message key can only run `serve-remote`; the harness key only `harness-receive`, which accepts `harness-push`, `harness-send` or nothing and exits 1 on anything else.
- `from=` limits the source address. Use a subnet if the hub's address changes (DHCP).
- Other keys in the file are not affected. A shared, unrestricted key keeps its shell; the "no unauthorized read or write" rule holds fully only after such keys are removed or restricted (pending decision in `docs/HANDOFF.md`).

## 6. Server Claude session (optional)

When a message is committed, `serve-remote` starts `rb-node respond <msg_id>` as a detached process. It runs `claude -p` in `trm_root` with `serve-local` as its only MCP server and these limits: one session at a time (lock file, stale after timeout + 300 s), wall timeout 1800 s, `--max-turns 40`, tools = `serve-local` + Read/Grep/Glob. The session writes only through the `reply` tool. A failure posts a `responder_failed` event to the outbox.

The `serve-local` tools are `inbox_list`, `inbox_read`, `attachment_path`, `reply`, `post_event`. A server session cannot submit jobs.

## 7. Checks (run from the hub after hub manual §4–§6)

| Command on the hub | Expected |
|---|---|
| `ssh rb-<node>` (send nothing) | No shell prompt. |
| `ssh rb-<node> cat /etc/passwd` | No passwd contents. |
| `ssh rb-<node>-harness <anything except harness-push / harness-send>` | Exit 1. |
| `read_doc("<node>", "../../.ssh/authorized_keys")` from a Claude session | `denied` |
| `send_message("<node>", "test", [<small pdf>])`, then `poll` | Reply stored under `D:/raw/research-bridge/inbox/<node>/<msg_id>/` with `provenance.json` |
| `submit_job` with `gpu_hours=0.01`, then `rb approve` | `job_finished` event with status `done` or `budget_exceeded` |

Record the results (with placeholders) in `docs/provisioning.md` §Results.

## 8. Budget enforcement

An approved job's queue file wraps the template command in `rb-node run-job --gpus ... --gpu-hours ...`. The wrapper sets `CUDA_VISIBLE_DEVICES` to exactly those GPUs and stops the job at wall time `gpu_hours / len(gpus)` (status `budget_exceeded`). Cancel requests are polled every 10 s. The node's own queue runner still assigns workers to GPUs; the wrapper narrows what the job sees.

## 9. Upgrading and removing

Upgrade: copy the new `rb_node/` over the old one (same LF rule) with the user's go-ahead; `node.json` and the mailbox are kept. Remove: delete the two `authorized_keys` lines, then `~/.local/bin/rb-node`, `~/.local/share/research-bridge/` and, once its contents are no longer needed, `~/.research-bridge/`.
