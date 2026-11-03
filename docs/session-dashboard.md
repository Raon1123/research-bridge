# The 8765 session dashboard

The session dashboard is the vault's HTTP server on the laptop, port 8765. It serves the session calendar, the agent-sequence (session browser) view, the priorities board, and the research-bridge pages. research-bridge does not own it: the server lives in the vault, and this repository only ships patches for it in `vault-export/dashboard/`.

## Where it runs

| Item | Value |
|---|---|
| Base URL (laptop) | `http://127.0.0.1:8765` |
| Base URL (LAN) | `http://<HUB_LAN_IP>:8765` (the server binds `0.0.0.0:8765`) |
| Server code | `D:/raw/vault-primary/90_Claude/60_Tools/dashboard/server.py` (vault; read its `README.md` there) |
| Started by | Windows startup shortcut `DashboardServer.lnk` → `start_dashboard.vbs` → `server.py --port 8765 --host 0.0.0.0` |
| Restart | `_restart.bat` in the same directory. **Only the user restarts it** (`AGENTS.md` "Ask the user before"). |
| Logs | `dashboard_server.log`, `dashboard_server_err.log` in the same directory |
| research-bridge modules it imports | `dashboard/rb_pending.py` (and, once applied, `dashboard/rb_board.py`); both import `rb_host` from `D:/raw/Codes/research-bridge` |

If `127.0.0.1:8765` does not answer but the LAN address does, check whether VS Code's port forwarding has taken 8765 (seen 2026-10-03; vault `session-calendar/README.md`).

## Routes to use

| Route | What | research-bridge? | Status 2026-11-03 |
|---|---|---|---|
| `/session-calendar` | Session calendar (302 to `90_Claude/00_Index/session-calendar.html`) | shows ledger messages through the session-calendar adapter | 302 |
| `/agents` | Agent-sequence view, `?sid=<prefix>` opens one session (302 to `agent-sequence.html`) | cross-machine dialogue appears here | 302 |
| `/priorities` | Priorities board (302 to `priorities.html`) | — | 302 |
| `/team-dashboard` | Team dashboard | — | 200 |
| `/rb/pending` | Pending job approvals, loopback only | yes (`vault-export/dashboard/rb_pending.py`) | 200 |
| `/rb/approve` | POST from the `/rb/pending` form; needs the approval passphrase | yes | — |
| `/board` | Unified board, loopback only | yes (`vault-export/dashboard/rb_board.py`) | 404: patch not applied yet (`vault-export/README.md`) |

The status column was checked with `curl` on the loopback address. Re-check before relying on it:

    for p in /session-calendar /agents /rb/pending /board; do curl -s -o NUL -w "$p %{http_code}\n" http://127.0.0.1:8765$p; done

## Rules for sessions

- Reading pages with `GET` is fine. Do not `POST` to `/rb/approve` or `/todo/toggle`: approval is the user's step (hard rule 1, PM-04 in `docs/postmortems/2026-11-03-whole-branch-review.md`).
- Do not edit vault `dashboard/` files directly. Change the copy in `vault-export/dashboard/`, test it with `tests/test_rb_pending.py` / `tests/test_rb_board.py`, and hand the user the apply and restart steps.
- Do not write the LAN address into this repository; it is public. Use `<HUB_LAN_IP>`.
