# Setup manuals

Two roles take part in research-bridge. Each has its own manual.

| Role | Runs | Today | Manual |
|---|---|---|---|
| **Hub** | `rb_host`: the MCP server for Claude sessions (`rb-host-mcp`), the `rb` CLI, the ledger and inbox, and the approval page on the 8765 dashboard | the laptop | [hub-setup.md](hub-setup.md) · [국문](hub-setup.ko.md) |
| **Node** | `rb_node`: the SSH forced-command endpoint (`rb-node serve-remote`), the mailbox, budgeted jobs, the per-message server Claude session (`serve-local` MCP), the harness staging channel | node1 (experiment server) | [node-setup.md](node-setup.md) · [국문](node-setup.ko.md) |

The hub is the centre: it holds the only ledger, it is the only side that opens connections (hub to node, never node to hub), and it is where the user approves jobs. One hub serves any number of nodes; each node gets its own keys, SSH aliases and entry in the hub's `host.json`.

```
Claude session ──stdio MCP── hub (rb-host-mcp, rb CLI, ledger, 8765 /rb/pending)
                                  │ ssh, alias rb-<node>         (message key, forced command)
                                  │ ssh, alias rb-<node>-harness (harness key, forced command)
                                  ▼
                              node (rb-node serve-remote / harness-receive)
                                  │ starts on each message
                                  ▼
                              server Claude session ──stdio MCP── rb-node serve-local
```

Order of setup for a new node: hub manual §1–§3 once, then node manual §1–§6, then hub manual §4–§6 for that node, then the checks in node manual §7.

## Conventions in these manuals

- Placeholders stand for private values: `<NODE_HOST>`, `<NODE_PORT>`, `<NODE_USER>`, `<NODE_HOME>`, `<HUB_SUBNET>`, `<HUB_LAN_IP>`. Real values are kept in the gitignored `private/placeholders.md` and never committed (`docs/CONTRIBUTING.md` §3).
- "User runs" marks steps that create keys, edit SSH configuration, or run commands on a node. `AGENTS.md` requires the user to run these or to approve each command.
- The English files are the reference. The `.ko.md` files are translations; if they differ, the English file wins. Update both in the same change.
