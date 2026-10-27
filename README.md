# research-bridge

Laptop-to-node bridge for Claude sessions: an MCP server (`rb-host-mcp`) and an approval CLI (`rb`).
The node side (`rb-node`) is stdlib-only and is reached over SSH.

## Install (laptop)

    pip install -e .[host]

Host config is JSON at `D:/raw/research-bridge/host.json` (override with `RB_HOST_CONFIG`):

    {"nodes": {"node1": {"alias": "node1"}}}

## Register the MCP server

Add to user-scope `~/.claude.json` under `mcpServers`:

    "research-bridge": {"type": "stdio", "command": "rb-host-mcp", "args": []}

Tools: `nodes`, `send_message`, `poll`, `thread`, `read_doc`, `fetch_file`, `queue_status`,
`gpu_status`, `submit_job`, `cancel_job`. `submit_job` and `cancel_job` only write a
`pending_approval` record to the ledger; nothing reaches the node until you approve.

## rb CLI

    rb pending                 # list jobs waiting for approval
    rb approve <job_id>        # show the job, ask y/N, then upload config and submit/cancel
    rb approve --yes <job_id>  # skip the prompt (explicit opt-in)
    rb reject <job_id>         # mark rejected; no node call
    rb harness push|pull|diff  # not implemented yet (exit 2)

Approving the same job twice is a no-op.
