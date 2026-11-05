# research-bridge

Laptop-to-node bridge for Claude sessions. A Claude session on the laptop can message a Claude session on an experiment server, read its experiment documents with withheld content masked, and request GPU jobs that you approve yourself. The laptop side is an MCP server (`rb-host-mcp`) and a CLI (`rb`). The node side (`rb-node`) is stdlib-only Python and is reached over SSH.

![research-bridge concept](docs/images/concept.svg)

- Only the laptop opens connections; the node answers.
- A Claude session can request a job but cannot approve it. You approve it with `rb approve` or the dashboard and type a passphrase, and the node checks it.
- Withheld material is filtered on the node and checked again on the laptop.

## Getting started

**1. Install (laptop).**

    uv sync --extra host

**2. Try the demo.** No node or SSH is needed: it starts a throwaway local node with made-up jobs and fake GPUs.

    uv run --extra host python scripts/demo_dashboard.py   # then open http://127.0.0.1:8799/board
                                                     # approval passphrase: demo passphrase

| Unified board (`/board`) | Pending approval (`/rb/pending`) |
|---|---|
| ![Unified board](docs/images/board.png) | ![Pending approval](docs/images/rb-pending.png) |

**3. Connect a real node.** Follow the manuals in this order: [hub setup](docs/manual/hub-setup.md) §1–§3, [node setup](docs/manual/node-setup.md) §1–§6, hub setup §4–§6, then node setup §7 (checks). The commands that write the config files, with the venv active on the laptop and `rb-node` installed on the node:

    rb config init && rb config add-node node1        # laptop: host.json
    rb-node config init && rb-node approve-key set    # node console: node.json, approval passphrase
    rb config mcp                                      # prints the ~/.claude.json entry to add
    rb config check                                    # exit 0 = ready

**4. Use it.** From a Claude session, call the MCP tools (`send_message`, `poll`, `read_doc`, `submit_job`, ...). Approve jobs in a terminal:

    rb pending
    rb approve <job_id>

## Documentation

| Topic | Where |
|---|---|
| Design, concept figure, config files, all commands, harness channel | [design spec](docs/superpowers/specs/2026-10-27-research-bridge-design.md) (§13 for current commands) |
| Step-by-step setup (keys, SSH aliases, `authorized_keys`) | [docs/manual/](docs/manual/README.md) (English and 국문) |
| Later designs (node-side approval, unified board) | [docs/design/](docs/design/README.md) |
| Live 8765 dashboard | [docs/session-dashboard.md](docs/session-dashboard.md) |
| Contributing, what must never be published | [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) |

Real host names, ports, user names and IPs never go into tracked files; use placeholders (`node1`, `<NODE_HOST>`, ...) and keep real values in the gitignored `private/` directory.
