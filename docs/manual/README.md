# Setup manuals

These two manuals are the reference behind the repository `README.md`. The README takes you from a clone to a working link and daily use; the manuals describe what each command does, reads, writes and asks, list every command, flag and configuration key of their side, and say what each doctor check means.

Two roles take part in research-bridge. Each has its own manual.

| Role | Runs | Today | Manual |
|---|---|---|---|
| **Hub** | `rb_host`: the MCP (Model Context Protocol) server for Claude sessions (`rb-host-mcp`), the `rb` command, the ledger and stored messages, unattended sync, the read-only hub page | this Linux server, since 2026-11-05 | [hub-setup.md](hub-setup.md) · [국문](hub-setup.ko.md) |
| **Node** | `rb_node`: the SSH forced-command endpoint (`rb-node serve-remote`), the mailbox, budgeted jobs, the per-message server Claude session (`serve-local` MCP), the harness staging channel | `node1` (experiment server) | [node-setup.md](node-setup.md) · [국문](node-setup.ko.md) |

The hub is the centre: it holds the only ledger, it is the only side that opens connections (hub to node, never node to hub), and it is where the user approves jobs. One hub serves any number of nodes; each node gets its own keys, SSH aliases and entry in the hub's `host.json`. The laptop is not the hub: the vault and its 8765 dashboard exist only on the laptop, and the hub page is reached from the laptop through an SSH local forward (hub manual §14).

```
Claude session ──stdio MCP── hub (rb-host-mcp, rb CLI, ledger, rb sync timer, hub page 127.0.0.1:8767)
                                  │ ssh, alias rb-<node>         (message key, forced command)
                                  │ ssh, alias rb-<node>-harness (harness key, forced command)
                                  ▼
                              node (rb-node serve-remote / harness-receive)
                                  │ starts on each message
                                  ▼
                              server Claude session ──stdio MCP── rb-node serve-local
```

## Order of setup for a new node

Two scripted commands do the work that used to be spread over both manuals: `rb setup` on the hub and `scripts/node-install.sh` on the node. Each prints the command that the other side needs.

| Step | Where | Command or action | Manual |
|---|---|---|---|
| 1 | hub | `uv sync --extra host --python '>=3.10'` and the tests | hub §1, §2 |
| 2 | hub terminal | `rb setup --node node1 --host <NODE_HOST> --port <NODE_PORT> --user <NODE_USER>` | hub §4 |
| 3 | node console | The printed `scripts/node-install.sh ...` command, then `rb-node approve-key set` | node §2, §4.2 |
| 4 | hub terminal | `rb setup --node node1` again (host key comparison) | hub §4.2 |
| 5 | hub terminal | The printed `claude mcp add-json ...`; start a new Claude session | hub §6 |
| 6 | hub | `rb doctor` | hub §10 |
| 7 | hub terminal | `rb service install`, then the printed `systemctl` commands | hub §13, §14 |
| 8 | hub | The security checks and one job | node §7.1 |

Daily use: `rb agent` after each reboot, `rb pending` / `rb approve`, the hub page, `rb doctor` when something fails.

## Section numbers

Other documents cite manual sections by number, so the numbers are stable: hub §12 is the Linux hub, node §5 the `authorized_keys` lines, node §7 the checks. New material is added at the end, before the appendix. Windows and laptop-hub instructions are in Appendix A of each manual and are not maintained since 2026-11-05.

## Conventions in these manuals

- Placeholders stand for private values: `node1` (node name), `<NODE_HOST>`, `<NODE_PORT>`, `<NODE_USER>` (the node's address, SSH port and login name), `<HUB_ADDR>` (the hub's address as the node sees it), `<HUB_SUBNET>` (the hub's network range), `<HUB_HOST>` (the name you use to log in to the hub from the laptop, for the SSH forward to the hub page), `<NODE_HOME>` (the node user's home directory), `<HUB_HOME>` (the home directory, on the hub, whose paths appear in the harness files; `local.example.json`), `<LAPTOP_LAN_IP>` (the laptop's own address, used only in `docs/session-dashboard.md` for the 8765 dashboard) and `<SHARED_KEY>` (the old shared key of the node). This is the one list; other documents refer to it. Real values are kept in the gitignored `private/placeholders.md` and never committed (`docs/CONTRIBUTING.md` §3).
- "Hub terminal" and "node console" mean a terminal a person has open on that machine. Commands that ask `y/N` or a passphrase refuse to run without a terminal, so a Claude session cannot run them; `AGENTS.md` requires the user to run, or to approve, every command on the node.
- The runtime is uv only. `rb ...` in the hub manual means `uv run --extra host rb ...` in the main checkout. People type plain commands; sessions prefix shell commands with `rtk`.
- The English files are the reference. The `.ko.md` files are translations; if they differ, the English file wins. Update both in the same change.
