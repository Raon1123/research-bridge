"""8765 /board page: the research-bridge unified board (docs/design/2026-11-02-unified-board.md).

GET only, loopback only. Renders the board cache written by `rb board refresh` plus the laptop
sources; a page load never opens an SSH connection and never writes a file. Approval stays on
/rb/pending.
"""
from __future__ import annotations

import html
import sys

RB_REPO = "D:/raw/Codes/research-bridge"
try:  # an importable rb_host (installed, or on the path in tests) wins over the fixed location
    import rb_host  # noqa: F401
except ImportError:
    if RB_REPO not in sys.path:
        sys.path.insert(0, RB_REPO)

from rb_host import board, jobs  # noqa: E402
from rb_host.config import HostConfig  # noqa: E402

STYLE = ("body{font-family:system-ui,sans-serif;margin:16px;max-width:1100px}"
         "table{border-collapse:collapse;margin:4px 0 16px}td,th{border:1px solid #bbb;"
         "padding:3px 8px;text-align:left}.err{color:#b00020}.stale{color:#a15c00}"
         ".src{display:inline-block;vertical-align:top;margin-right:16px}")


def _cfg() -> HostConfig:
    try:
        return jobs.load_cfg()
    except FileNotFoundError:  # no host.json yet: defaults (empty ledger, no nodes)
        return HostConfig()


def _e(v) -> str:
    return html.escape(str(v), quote=True)


def _items_table(items) -> str:
    if not items:
        return "<p>(no items)</p>"
    keys = []
    for it in items:
        keys += [k for k in it if k not in keys]
    head = "".join("<th>%s</th>" % _e(k) for k in keys)
    rows = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % _e(it.get(k, "")) for k in keys)
                   for it in items[:50])
    return "<table><tr>%s</tr>%s</table>" % (head, rows)


def render_board(b: dict) -> str:
    waits = "".join("<tr><td>%s</td><td>%s</td><td>%s</td></tr>"
                    % (_e(w["source"]), _e(w["ref"]), _e(w["what"])) for w in b["waiting"])
    waits = waits or '<tr><td colspan="3">Nothing is waiting on you.</td></tr>'
    parts = []
    for s in b["sources"]:
        if s["ok"]:
            state = "ok"
        else:
            state = '<span class="err">error: %s</span>' % _e(s["error"])
        stale = ' <span class="stale">stale</span>' if s.get("stale") else ""
        parts.append('<div class="src"><h3>%s</h3><p>%s · fetched %s%s</p>%s</div>'
                     % (_e(s["source"]), state, _e(s.get("fetched_at")), stale,
                        _items_table(s.get("items", []))))
    return ('<!doctype html><html><head><meta charset="utf-8"><title>Research board</title>'
            "<style>%s</style></head><body><h1>Research board</h1>"
            "<p>Generated %s. Refresh node sources with <code>rb board refresh</code>. "
            'Approve jobs on <a href="/rb/pending">/rb/pending</a>.</p>'
            "<h2>Waiting on you (%d)</h2><table><tr><th>source</th><th>ref</th><th>what</th></tr>"
            "%s</table><h2>Sources</h2>%s</body></html>"
            % (STYLE, _e(b["generated"]), len(b["waiting"]), waits, "".join(parts)))


def handle_get(client_ip, host=None):
    if client_ip != "127.0.0.1" or not jobs.host_allowed(host):
        return 403, "forbidden"
    try:
        return 200, render_board(board.load(_cfg()))
    except Exception:
        return 500, "research-bridge board unavailable"
