# vault-export

Snapshot of the vault-side files that research-bridge edited, so they can be reviewed, re-applied or rolled back from this repository. The live copies are already in place in the vault; nothing here is applied automatically.

Vault tools root: `D:/raw/vault-primary/90_Claude/60_Tools/`. The vault is not a git repository. Write only under `90_Claude/` (the mirror hook handles the rest); never edit the iCloud copy.

## Files

| Export | Live file | Change |
|---|---|---|
| `dashboard/rb_pending.py` | `dashboard/rb_pending.py` | **New.** Approval page and POST handler for the 8765 dashboard. Loopback (127.0.0.1) only for GET and POST; per-process CSRF token. Since 2026-11-03 (SEC-01) the Approve form has a passphrase field that is passed to `jobs.approve`; **the live copy predates this and must be replaced** (see below). Imports `rb_host` from `RB_REPO = "D:/raw/Codes/research-bridge"`; without `host.json` it uses an empty config. |
| `dashboard/server.py.patch` | `dashboard/server.py` | Adds `GET /rb/pending`, `POST /rb/approve`, `POST /rb/reject`, routed to `rb_pending`. |
| `session-calendar/bridge_edges.py` | `session-calendar/bridge_edges.py` | **New.** Builds metadata-only edges from `D:/raw/research-bridge/ledger.jsonl` and merges them into `cache/agents/<sid>.json` when that file exists. Never writes a message body. |
| `session-calendar/refresh.py.patch` | `session-calendar/refresh.py` | One fail-soft step after `link.py` that calls `bridge_edges`. |
| `session-calendar/template.html.patch` | `session-calendar/template.html` | One label for the new `bridge` edge kind. |
| `dashboard/rb_board.py` | `dashboard/rb_board.py` | **New, not applied yet (2026-11-03).** `GET /board`, the unified board page. Loopback only, GET only, no approval form; reads the `rb board refresh` cache and the laptop sources through `rb_host.board.load`, never opens SSH. |
| `dashboard/server.py.board.patch` | `dashboard/server.py` | **Not applied yet.** Adds `GET /board` routed to `rb_board`. Made against the *current* `server.py` (with `/rb/pending`), not the original. |
| `CHECKSUMS.txt` | — | sha256 of the original and edited files at export time (2026-11-02). |

Tests for the two new modules are in the repo: `tests/test_rb_pending.py` and `tests/test_bridge_edges.py`. Both insert the vault path into `sys.path`, so they need the vault files in place. `tests/test_rb_board.py` imports `rb_board` from this directory instead, so it runs before the patch is applied.

## Check that the vault still matches the export

    cd D:/raw/vault-primary/90_Claude/60_Tools
    sha256sum dashboard/server.py dashboard/rb_pending.py session-calendar/refresh.py session-calendar/bridge_edges.py session-calendar/template.html

Compare with the `current` lines in `CHECKSUMS.txt`. A difference means someone edited the file after the export.

## Re-apply (only if a file was lost or reverted)

Patches are made from the original files, so they apply only to an unedited original (`original` lines in `CHECKSUMS.txt`):

    cd D:/raw/vault-primary/90_Claude/60_Tools
    patch -p1 --dry-run < D:/raw/Codes/research-bridge/vault-export/dashboard/server.py.patch
    patch -p1 < D:/raw/Codes/research-bridge/vault-export/dashboard/server.py.patch
    patch -p1 < D:/raw/Codes/research-bridge/vault-export/session-calendar/refresh.py.patch
    patch -p1 < D:/raw/Codes/research-bridge/vault-export/session-calendar/template.html.patch

The patch paths are `a/dashboard/server.py` and `a/session-calendar/...`, so run `patch -p1` from the tools root. New files are copied directly:

    cp D:/raw/Codes/research-bridge/vault-export/dashboard/rb_pending.py dashboard/
    cp D:/raw/Codes/research-bridge/vault-export/session-calendar/bridge_edges.py session-calendar/

Then restart the dashboard to load the new routes:

    cd dashboard && cmd /c _restart.bat

## Apply the /board page (user, 2026-11-03 export)

Check that `dashboard/server.py` still has the `current` hash in `CHECKSUMS.txt`, then:

    cd D:/raw/vault-primary/90_Claude/60_Tools
    patch -p1 --dry-run < D:/raw/Codes/research-bridge/vault-export/dashboard/server.py.board.patch
    patch -p1 < D:/raw/Codes/research-bridge/vault-export/dashboard/server.py.board.patch
    cp D:/raw/Codes/research-bridge/vault-export/dashboard/rb_board.py dashboard/
    cd dashboard && cmd /c _restart.bat

The result has the `board-target` hash. Live check: `curl` on `http://127.0.0.1:8765/board` returns 200, the LAN address returns 403. `rb_board.py` imports `rb_host` from `D:/raw/Codes/research-bridge`, so that checkout must contain `rb_host/board.py` (merge this branch first). Roll back with `patch -R -p1 < .../server.py.board.patch` and `rm dashboard/rb_board.py`.

## Roll back

    cd D:/raw/vault-primary/90_Claude/60_Tools
    patch -R -p1 < D:/raw/Codes/research-bridge/vault-export/dashboard/server.py.patch
    patch -R -p1 < D:/raw/Codes/research-bridge/vault-export/session-calendar/refresh.py.patch
    patch -R -p1 < D:/raw/Codes/research-bridge/vault-export/session-calendar/template.html.patch
    rm dashboard/rb_pending.py session-calendar/bridge_edges.py

then restart the dashboard.

## Update rb_pending.py for node-side approval (user, 2026-11-03)

`jobs.approve` now requires the approval passphrase. The old live `rb_pending.py` calls it without one, so its Approve button fails with "operation failed" (nothing is sent to the node) until the file is replaced:

    cd D:/raw/vault-primary/90_Claude/60_Tools
    cp D:/raw/Codes/research-bridge/vault-export/dashboard/rb_pending.py dashboard/
    cd dashboard && cmd /c _restart.bat

`server.py` needs no change: the form fields, including `passphrase`, already reach `handle_post`. `tests/test_rb_pending.py` now imports the copy in this directory, not the vault copy.

## Known limits

- Bridge edges do not appear on the session browser main screen yet: its renderer builds from transcripts, not from `cache/agents/*.json`. See `docs/HANDOFF.md` §Follow-ups.
- The `verify.py --server` run after the refresh change showed one failure that is probably older than this change; no baseline was taken.
- If `D:/raw/Codes/research-bridge` moves, change `RB_REPO` in `rb_pending.py` and the `sys.path` line in the two tests.
