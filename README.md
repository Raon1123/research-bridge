# research-bridge

Laptop-to-node bridge for Claude sessions: an MCP server (`rb-host-mcp`) and an approval CLI (`rb`).
The node side (`rb-node`) is stdlib-only and is reached over SSH.

## What it looks like

Screenshots from `scripts/demo_dashboard.py`. They show the two pages the 8765 dashboard serves, using made-up data: a throwaway local node, two jobs and fake GPUs. No real node, ledger or vault file is involved.

**Unified board** (`/board`). This page only shows data. The "waiting on you" list comes first, then one table per source:

- `rb:ledger`: the laptop ledger, read live;
- `<node>:queue|gpu|state|events|kanban`: the node, from the cache that `rb board refresh` writes;
- `vault:portfolio|priorities`: the vault files, read live.

![Unified board](docs/images/board.png)

**Pending approval** (`/rb/pending`). Each Approve button needs the approval passphrase, and the node itself checks it. A wrong passphrase gets "approval refused by the node" and the job stays pending. In the screenshot, the first demo job was approved with the right passphrase: it now shows as `queued` in the ledger and as a `jobs` entry in the node queue on the board above. Reject needs no passphrase and makes no node call.

![Pending approval](docs/images/rb-pending.png)

Run the demo yourself. It needs the unified board (`rb_host/board.py`) and node-side approval (`rb_node/approval.py`):

    python scripts/demo_dashboard.py            # then open http://127.0.0.1:8799/board
                                                 # approval passphrase: demo passphrase

## Install (laptop)

    pip install -e .[host]

Host config is JSON at `D:/raw/research-bridge/host.json` (override with `RB_HOST_CONFIG`):

    {"nodes": {"node1": {"alias": "node1"}}}

## Private values (not in git)

Server addresses, ports, node names, user names and laptop IPs are replaced in tracked files by
placeholders (`node1`, `<NODE_HOST>`, `<NODE_PORT>`, `<NODE_USER>`, `<LAPTOP_USER>`,
`<LAPTOP_ETH_SUBNET>` ...). Real values live in the gitignored `private/` directory:
`private/placeholders.md` (placeholder -> real value) and `private/local.json` (copy of
`local.example.json`; `laptop_home` and `node_home` feed the harness path mapping, overridable
with `RB_LAPTOP_HOME` / `RB_NODE_HOME`). Do not commit real values; put them in `private/`.

## Register the MCP server

Add to user-scope `~/.claude.json` under `mcpServers`:

    "research-bridge": {"type": "stdio", "command": "rb-host-mcp", "args": []}

Tools: `nodes`, `send_message`, `poll`, `thread`, `read_doc`, `fetch_file`, `queue_status`,
`gpu_status`, `submit_job`, `cancel_job`. `submit_job` and `cancel_job` only write a
`pending_approval` record to the ledger; nothing reaches the node until you approve.

## rb CLI

    rb pending                 # list jobs waiting for approval
    rb approve <job_id>        # show the job, ask y/N and the approval passphrase, then upload config and submit/cancel
    rb approve --yes <job_id>  # skip the y/N question; the passphrase is always asked
    rb reject <job_id>         # mark rejected; no node call
    rb harness push --node N [--dry-run]   # laptop harness -> node harness-staging/<stamp>/
    rb harness pull --node N               # node harness -> D:/raw/research-bridge/harness-staging/<stamp>/
    rb harness diff <stamp>                # unified diff of a pulled stamp against ~/.claude

Approving the same job twice is a no-op.

## Harness channel (manual)

Separate SSH key and alias (`rb-<node>-harness`, or `harness_alias` in the host node entry) whose
forced command is `rb-node harness-receive`. It routes on `SSH_ORIGINAL_COMMAND`: `harness-send`
(node tars its allowlisted subset), empty or `harness-push` (stage a received tar). Set
`harness_root` (the node's `~/.claude`) in `node.json`; without it push and pull are refused
(`no_harness_root`). Allowlist: `CLAUDE.md`, `settings.json`, `rtk-reference.md`, `commands/`,
`agents/`, `hooks/`, `workflows/`. Tars are checked member by member (no absolute paths, `..`,
links or devices) before anything is written. `settings.json` and other `.json` files with a
populated credential-like key block the transfer.

There is no apply command. After reading `rb harness diff <stamp>`, copy by hand, for example:

    cp -r D:/raw/research-bridge/harness-staging/<stamp>/agents/. ~/.claude/agents/

(On the node, staged pushes sit in `~/.research-bridge/harness-staging/<stamp>/`; copy them into
`~/.claude` the same way.)
