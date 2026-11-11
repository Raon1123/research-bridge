> Came from: Appendix A of `docs/manual/hub-setup.md`; moved here on 2026-11-11.
> Not maintained (not kept in step with the code since 2026-11-05). The current text is `docs/manual/hub-setup.md`.

## Appendix A. Windows or laptop hub (not maintained since 2026-11-05)

This appendix keeps the instructions of the first hub, the Windows laptop. They were last checked on 2026-11-05 and are not kept in step with the code. `rb setup`, `rb agent`, `rb doctor`, `rb service` and the timer were written for Linux and were not tried on Windows. Paths are examples.

- **Requirements:** Python 3.14 (tests ran there), the OpenSSH client and the "OpenSSH Authentication Agent" service set to start automatically, the repository at `D:/raw/Codes/research-bridge` (the 8765 dashboard imports `rb_host` from `RB_REPO` in `vault-export/dashboard/rb_pending.py`).
- **Data directory:** `D:/raw/research-bridge/` is the default on Windows when `RB_HOST_ROOT` is not set; keep it outside the vault and any cloud-synced folder. The default withheld pattern file is the session-calendar export `D:/raw/session-calendar/server/withheld_patterns.json`.
- **Keys:** `ssh-keygen -t ed25519 -f C:/keys/research-bridge/node1_ed25519 -C research-bridge-hub` and the same for the harness key; `ssh-add` both; the passphrase is entered once per logon. Use the `C:/keys/...` paths as `IdentityFile` in the blocks of §4.5. `from=` on the node is the laptop's subnet.
- **MCP entry** in `~/.claude.json` under `mcpServers`: `"research-bridge": {"type": "stdio", "command": "uv", "args": ["run", "--directory", "D:/raw/Codes/research-bridge", "--extra", "host", "python", "-m", "rb_host.server"]}`.
- **Approval** in PowerShell or Windows Terminal (redirected input and Git Bash's mintty are refused), or on `http://127.0.0.1:8765/rb/pending` (loopback only, per-process CSRF token, passphrase field). Install the dashboard route from `vault-export/` (see `vault-export/README.md`) and restart the 8765 dashboard; both need the user's go-ahead.
- **Checks:** `curl -s -o NUL -w "%{http_code}" http://127.0.0.1:8765/rb/pending` should print 200 and the same URL on the laptop's LAN address 403.
- **Tests:** `tests/test_rb_pending.py` and `tests/test_bridge_edges.py` use the repository's `vault-export/` copies; the vault is not needed.
