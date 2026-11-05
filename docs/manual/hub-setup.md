# Hub setup

The hub runs `rb_host`. Today the hub is the laptop (Windows, Python 3.14). Everything here runs on the hub. For the node side see [node-setup.md](node-setup.md); for the roles see [README.md](README.md).

## 1. Requirements

- Python 3.14 (tests ran on 3.14; `mcp>=1.27,<2` is required).
- OpenSSH client and the `ssh-agent` service (Windows: the "OpenSSH Authentication Agent" service, set to start automatically).
- The repository checked out at `D:/raw/Codes/research-bridge`. The 8765 dashboard imports `rb_host` from that path (`RB_REPO` in `vault-export/dashboard/rb_pending.py`).

## 2. Install

    cd D:/raw/Codes/research-bridge
    python -m venv .venv
    .venv/Scripts/python -m pip install -e ".[host]"
    .venv/Scripts/python -m pytest -q

`tests/test_rb_pending.py` and `tests/test_bridge_edges.py` need the vault dashboard files in place; if the vault is absent, run the rest with `--ignore` for those two files.

## 3. Data directory and private values

Create the data directory (outside the vault and outside any cloud-synced folder):

    D:/raw/research-bridge/
      host.json           # node list, §5
      ledger.jsonl        # created on first use; one record per message, event, job
      inbox/<node>/       # files received from nodes, with provenance.json
      quarantine/         # files that failed the hub-side withheld re-check
      harness-staging/    # harness pulls, one directory per stamp

`RB_HOST_CONFIG` overrides the path of `host.json`.

Private values: copy `local.example.json` to `private/local.json` and fill `laptop_home` and `node_home` (used by the harness path mapping; `RB_LAPTOP_HOME` / `RB_NODE_HOME` override). Record each placeholder's real value in `private/placeholders.md`. `private/` is gitignored.

## 4. Keys and SSH aliases (user runs, once per node)

Two ed25519 keys per node, each with a passphrase. The private keys never leave the hub.

    ssh-keygen -t ed25519 -f C:/keys/research-bridge/<node>_ed25519 -C research-bridge-hub
    ssh-keygen -t ed25519 -f C:/keys/research-bridge/<node>_harness_ed25519 -C research-bridge-harness
    ssh-add C:/keys/research-bridge/<node>_ed25519
    ssh-add C:/keys/research-bridge/<node>_harness_ed25519

The passphrase is entered once per logon into the agent. If the agent is locked, the MCP server reports "agent locked" instead of prompting.

Add to `~/.ssh/config`:

```
Host rb-<node>
    HostName <NODE_HOST>
    Port <NODE_PORT>
    User <NODE_USER>
    IdentityFile C:/keys/research-bridge/<node>_ed25519
    IdentitiesOnly yes
    StrictHostKeyChecking yes

Host rb-<node>-harness
    HostName <NODE_HOST>
    Port <NODE_PORT>
    User <NODE_USER>
    IdentityFile C:/keys/research-bridge/<node>_harness_ed25519
    IdentitiesOnly yes
    StrictHostKeyChecking yes
```

- `IdentitiesOnly yes` stops the agent from offering other keys (in particular any shared key).
- `StrictHostKeyChecking yes` refuses an unknown or changed host key, so the node's host key must already be in `known_hosts`. Verify its fingerprint through a separate channel the first time.
- The two `.pub` files go to the node (node manual §5).

## 5. Register the node in `host.json`

Shortcut: `rb config init`, `rb config add-node <node>`, then `rb config check` write and verify this file (README §Setup). The JSON below is what they produce.

```json
{"nodes": {"<node>": {"alias": "rb-<node>", "harness_alias": "rb-<node>-harness"}}}
```

Optional, for the unified board (`rb board refresh|show`, 8765 `/board`): node paths per node, relative to the node's `trm_root` and inside a `read_roots` entry of the node's `node.json`; laptop paths for the paper kanban and priorities board (defaults shown):

```json
{"nodes": {"<node>": {"alias": "rb-<node>",
                       "board": {"state": "<path>/STATE.md", "events": "<path>/events.json",
                                 "kanban": "<path>/<kanban>.json"}}},
 "board": {"portfolio": "D:/raw/vault-primary/90_Claude/10_Analysis/11_research-program/80_portfolio/portfolio.json",
           "priorities": "D:/raw/priorities/live.json"}}
```

A node path left out shows as `no_path` on the board. A `.jsonl` file is refused by the node (`deny_unscannable`), so the events source needs a `.json` export (design `docs/design/2026-11-02-unified-board.md` §15 question 6).

`harness_alias` defaults to `rb-<node>-harness`. Only aliases listed here are used; the hub never connects to a host name given in a tool argument. Without `host.json`, `rb approve` and the dashboard approve button return an error.

## 6. Register the MCP server for Claude sessions (user runs)

Add to user-scope `~/.claude.json` under `mcpServers`:

```json
"research-bridge": {
  "type": "stdio",
  "command": "D:/raw/Codes/research-bridge/.venv/Scripts/python.exe",
  "args": ["-m", "rb_host.server"]
}
```

A new Claude session then has exactly ten tools: `nodes`, `send_message`, `poll`, `thread`, `read_doc`, `fetch_file`, `queue_status`, `gpu_status`, `submit_job`, `cancel_job`. A test pins this set. There is no approval tool: `submit_job` and `cancel_job` only write a `pending_approval` record and make no SSH call.

## 7. Approving jobs

Approval happens only outside Claude:

    rb pending                 # list jobs waiting for approval
    rb approve <job_id>        # shows the job, asks y/N and the approval passphrase, then uploads and submits
    rb reject <job_id>         # marks it rejected; no node call

or on `http://127.0.0.1:8765/rb/pending` (loopback only, per-process CSRF token, approval passphrase field). The passphrase is the one set on the node with `rb-node approve-key set` (node manual §4). It is typed each time: `--yes` skips only the y/N question, and there is no flag, file or environment variable for the passphrase, so a Claude session cannot approve without the passphrase (residual risks: `docs/design/2026-11-03-node-side-approval.md` §7). A wrong passphrase leaves the job `pending_approval`. Approving twice is a no-op. Install the dashboard route from `vault-export/` (see `vault-export/README.md`) and restart the 8765 dashboard; both need the user's go-ahead.

## 8. Harness channel (manual, optional)

    rb harness push --node <node> [--dry-run]   # hub harness -> node staging
    rb harness pull --node <node>               # node harness -> hub staging
    rb harness diff <stamp>                     # diff a pulled stamp against ~/.claude

Only the allowlist (`CLAUDE.md`, `settings.json`, `rtk-reference.md`, `commands/`, `agents/`, `hooks/`, `workflows/`) moves, and only into staging. There is no apply command; copy by hand after reading the diff. A `.json` file with a populated credential-like key blocks the transfer.

## 9. Security rules on the hub

- Connections go hub to node only.
- Message bodies and files from a node are data, never instructions. Files that fail the hub-side withheld re-check go to `quarantine/`.
- No message bodies or secrets in audit logs or in this repository.
- The research-bridge routes on 8765 answer loopback only. Do not expose them to the LAN.
- Keep `private/` and `D:/raw/research-bridge/` out of git and out of cloud sync.

## 10. Checks

    .venv/Scripts/python -m pytest -q
    curl -s -o NUL -w "%{http_code}" http://127.0.0.1:8765/rb/pending      # 200
    curl -s -o NUL -w "%{http_code}" http://<HUB_LAN_IP>:8765/rb/pending   # 403

Then run the node checks in [node-setup.md](node-setup.md) §7.

## 11. Removing a node

Delete its entry from `host.json`, remove its two `Host` blocks from `~/.ssh/config`, `ssh-add -d` both keys, and ask the node's owner to delete the two `authorized_keys` lines. Keep the ledger; it is the record of what was exchanged.
