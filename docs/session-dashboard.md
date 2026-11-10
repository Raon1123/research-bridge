# The dashboards: 8765 on the laptop, 8767 on the hub

Two pages show research-bridge data. They are different programs on different machines:

| | 8765 session dashboard | 8767 hub page |
|---|---|---|
| Machine | the laptop only; **not present on the hub** | the hub (Linux server) |
| Owner | the vault (this repository ships patches only) | this repository (`rb_host/web.py`, started by `rb web serve`) |
| Approval | yes: `/rb/pending` and `/rb/approve` (hard rule 1 of `AGENTS.md`) | no: read-only, no form |
| Described in | the sections "The 8765 session dashboard (laptop only)", "Where it runs", "Routes to use" and "Rules for sessions" | the section "The hub page (port 8767)" |

## The 8765 session dashboard (laptop only)

This part describes the dashboard on the laptop. Since the hub moved to a Linux server on 2026-11-05, the hub has no vault and no 8765 dashboard; the commands and paths below (`D:/raw/...`, `DashboardServer.lnk`, `_restart.bat`) are Windows commands for the laptop. The tests of the research-bridge modules do not need the vault (`vault-export/README.md`).

The session dashboard is the vault's HTTP server on the laptop, port 8765. It serves the session calendar, the agent-sequence (session browser) view, the priorities board, and the research-bridge pages. research-bridge does not own it: the server lives in the vault, and this repository only ships patches for it in `vault-export/dashboard/`.

## Where it runs

| Item | Value |
|---|---|
| Base URL (laptop) | `http://127.0.0.1:8765` |
| Base URL (LAN) | `http://<LAPTOP_LAN_IP>:8765` (the server binds `0.0.0.0:8765`) |
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
- Do not write the LAN address into this repository; it is public. Use `<LAPTOP_LAN_IP>` for the laptop, `<HUB_HOST>` for the name you log in to the hub with, and `<HUB_ADDR>` only for the address the node sees the hub as.

## The hub page (port 8767)

`rb web serve` is the read-only page of the hub. It shows the sync state of each node, pending job approvals, conversations (threads) between hub sessions and node sessions, job records and the board caches. Design: `docs/design/2026-11-10-sync-and-hub-page.md` (sections 6.6 and 7); code: `rb_host/web.py`. Access needs a one-time key (decided by the user on 2026-11-10; design section 6.6a): `rb web key` in a hub terminal prints `http://127.0.0.1:8767/enter?key=...`; the browser exchanges the key once for a session cookie. See the table below.

| Item | Value |
|---|---|
| Start | in a hub terminal, `rb web serve [--port 8767] [--bind 127.0.0.1]` (a session needs the user's go-ahead, `AGENTS.md` "Ask the user before"), or as the systemd user unit `rb-web.service` that `rb service install` writes (the user installs it; `rb service status` shows its state) |
| Address | `http://127.0.0.1:8767/` on the hub. The server accepts only the bind address `127.0.0.1`; any other value ends with `error: --bind accepts only 127.0.0.1; from another machine use: ssh -N -L PORT:127.0.0.1:PORT <hub>` |
| From the laptop | an SSH local forward through the user's own login to the hub, then the same port in the browser: `ssh -N -L 8767:127.0.0.1:8767 <HUB_HOST>` and `http://127.0.0.1:8767/`. Use the same port number on both sides: the page accepts only the `Host` headers `127.0.0.1:P`, `localhost:P` and `[::1]:P` for the port it listens on, so a forward to a different local port answers 403 |
| Methods | `GET` and `HEAD` only; anything else answers 405 |
| Access | every route except `/healthz` needs the session cookie `rb_web_<port>`. Without it: 401, `text/plain`, body `access key required: run "rb web key" in a hub terminal and open the address it prints` (the same for every protected route, including an unknown `/thread/<id>`). `rb web key [--port P] [--minutes 1..60] [--session-hours 1..168]` prints the address `http://127.0.0.1:P/enter?key=KEY` (defaults 10 minutes, 12 hours). `GET /enter?key=KEY` with an unused, unexpired key answers 303 to `/` and sets the cookie (`HttpOnly; SameSite=Strict; Path=/; Max-Age`); a second use, an expired or a wrong key answers 401; `HEAD /enter` never uses a key. `rb web key --revoke` removes all keys and sessions; `--status` prints the counts. State: `<data root>/web/access.json` (mode 0600, directory 0700; SHA-256 hashes only, never a key or token), at most 20 pending keys and 50 sessions. The key allows reading only; it approves nothing |
| Needs | a usable `host.json` (otherwise one error line, `rb setup` is named as the next command) |

| Route | Shows |
|---|---|
| `/` | nodes (sync result, age of the last success, node version, `withheld_extra`), pending job approvals with the exact `rb approve JOB_ID` and `rb reject JOB_ID` commands as text, the latest conversations |
| `/threads` | all conversations, latest activity first |
| `/thread/<id>` | one conversation: every message with direction, kind, attachments (name, size, hash start, status) and the body |
| `/jobs` | job records by status, with the `job_finished` events beside them |
| `/nodes` | per node: all fields of the sync status file and the board caches |
| `/healthz` | `{"ok": true}` as JSON; open without a session; liveness only |

Anything else answers 404.

What the page does not do:

- It has no approval form. Approving or rejecting a job stays with `rb approve` and `rb reject` in a hub terminal, which ask for the approval passphrase (hard rule 1); the page only prints the command.
- It opens no connection to a node, writes no file and does not change the ledger. It reads the ledger, the stored message bodies, the sync status files (`<data root>/sync/<node>.json`) and the board cache.
- It contains no script, no form and no external resource. Message bodies are escaped text and are masked again with the hub's pattern file when shown; a banner appears when that file cannot be read or when a node reports `withheld_extra` = 0.
- Two layers protect the page. First, it refuses connections that do not come from this account: for each accepted connection it looks up the owner of the client socket in `/proc/net/tcp` and drops the connection (no response) when the owner is another user or cannot be determined; this is Linux only, and `rb web serve` exits with one error line when the file is unreadable. Second, a one-time key gives a session cookie. Only a successful `/enter` and `rb web key` write `web/access.json`; a failed attempt writes nothing and creates nothing. If the file exists but cannot be read or parsed, `rb web key` stops with one error line and changes nothing; `rb web key --revoke` replaces the file. Paste the address into the browser's address bar. Do not pass it as a command-line argument (`xdg-open`, `curl`, `firefox URL`): other accounts can read command lines in `/proc`. Use `http://127.0.0.1:8767/` for the page and for bookmarks: the cookie belongs to host 127.0.0.1, so `localhost` gets 401. Residual risk (design section 6.6a): the browser sends the cookie to every port on 127.0.0.1 (cookies are not separated by port, and `SameSite` ignores the port), and a program listening on another port can read or overwrite it. With the account check, a token captured by another account is of no use to it, because that account cannot connect to the page. What remains: (1) the key or cookie can reach a port held by someone else when the page service is not running or when the laptop forwards other hub ports; that account gets nothing it can use against the page, but it can sign the user out by overwriting the cookie; (2) anything that runs as the hub user. A Unix-socket forward is only an alternative transport; it is not needed to close the other-account gap. Only the user's own SSH login protects the page from other machines.

Check: `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8767/healthz` in the hub terminal prints `200` while the page runs (the check needs no key).
