"""rb web serve: the read-only hub page (docs/design/2026-11-10-sync-and-hub-page.md, section 6.6 and 7).

Shows stored conversations, job records, pending approvals and the sync state. A request reads
files (the ledger through `threads.load`, stored bodies, the sync status file, the board cache)
and writes nothing (except `/enter`, which consumes an access key in `web/access.json`), opens no node connection and starts no process. Every route except /healthz needs a session
cookie obtained with a one-time key (`rb_host.webaccess`). Stdlib HTTP server on
loopback; GET and HEAD only; no script, no form, no external resource. This module imports
neither `mcp` nor `rb_host.server` nor `rb_host.board` at module level (`board` is loaded on the
first /nodes request).
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.parse
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from rb_node.withheld import Withheld

from . import configure, jobs, threads, webaccess

DEFAULT_PORT = 8767
ROUTE = re.compile(r"^/(?:|threads|jobs|nodes|healthz|enter|thread/([A-Za-z0-9][A-Za-z0-9._-]{0,127}))$")
CSP = ("default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; form-action 'none'; "
       "base-uri 'none'; frame-ancestors 'none'")
LOOPBACK_BINDS = ("127.0.0.1",)
MAX_THREAD_ROWS = 500
INDEX_THREADS = 10
STYLE = ("body{font-family:system-ui,sans-serif;margin:16px;max-width:1200px}"
         "table{border-collapse:collapse;margin:4px 0 16px}td,th{border:1px solid #bbb;"
         "padding:3px 8px;text-align:left;vertical-align:top}"
         "pre{white-space:pre-wrap;word-break:break-word;background:#f4f4f4;padding:6px}"
         "code{background:#eee;padding:0 3px}.err{color:#b00020}.stale{color:#a15c00}"
         ".banner{background:#fff3cd;padding:4px 8px;margin:4px 0}"
         ".rec{border-top:1px solid #bbb;margin-top:12px}")
_NAMES = {"": "index", "threads": "threads", "jobs": "jobs", "nodes": "nodes",
          "healthz": "healthz", "enter": "enter"}
NEED_KEY = 'access key required: run "rb web key" in a hub terminal and open the address it prints'


# -- addressing ---------------------------------------------------------------------------
def allowed_hosts(port: int) -> frozenset:
    """The only Host header values served (lowercase)."""
    return frozenset(["127.0.0.1:%d" % port, "localhost:%d" % port, "[::1]:%d" % port])


def route_of(raw_target: str) -> Tuple[str, Optional[str]]:
    """Match the raw request target before any percent-decoding; the query part is ignored."""
    path = raw_target.split("?", 1)[0]
    m = ROUTE.fullmatch(path)
    if m is None:
        return ("other", None)
    if m.group(1) is not None:
        return ("thread", m.group(1))
    return (_NAMES[path.lstrip("/")], None)


# -- html helpers --------------------------------------------------------------------------
class Raw(str):
    """Markup that is already escaped."""


def _e(v: Any) -> str:
    return html.escape(str(v), quote=True)


def _cell(c: Any) -> str:
    return str(c) if isinstance(c, Raw) else _e(c)


def _table(head: List[str], rows: List[List[Any]], empty: str = "(none)") -> str:
    if not rows:
        return "<p>%s</p>" % _e(empty)
    th = "".join("<th>%s</th>" % _e(h) for h in head)
    body = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % _cell(c) for c in r) for r in rows)
    return "<table><tr>%s</tr>%s</table>" % (th, body)


def _t(wh: Withheld, v: Any, limit: int = 300) -> str:
    """Free text from a record: cleaned, and replaced when it matches a withheld pattern."""
    s = jobs.clean(v, 100000)
    return "(withheld)" if wh.name_hit(s) else s[:limit]


def _link(wh: Withheld, mid: Any) -> Raw:
    """A link to /thread/<id> only for ids the route accepts; the label is masked."""
    s = str(mid)
    label = _t(wh, s, 128)
    if label != "(withheld)" and route_of("/thread/" + s)[0] == "thread":
        return Raw('<a href="/thread/%s">%s</a>' % (_e(s), _e(label)))
    return Raw(_e(label))


def _age(seconds: Optional[float]) -> str:
    if seconds is None:
        return "unknown age"
    s = int(seconds)
    if s < 120:
        return "%d s ago" % s
    if s < 7200:
        return "%d min ago" % (s // 60)
    if s < 172800:
        return "%d h ago" % (s // 3600)
    return "%d d ago" % (s // 86400)


NAV = ('<nav><a href="/">overview</a> | <a href="/threads">threads</a> | '
       '<a href="/jobs">jobs</a> | <a href="/nodes">nodes</a></nav>')


def _page(title: str, body: str, refresh: int) -> bytes:
    return ('<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="refresh" content="%d"><title>%s</title><style>%s</style></head>'
            "<body>\n<h1>%s</h1>\n%s\n<p>Read only: this page changes nothing.</p>\n"
            "%s</body></html>\n" % (refresh, _e(title), STYLE, _e(title), NAV, body)).encode("utf-8")


def _banners(cfg: Any, wh: Withheld) -> str:
    out = []
    if wh.source_error:
        out.append("Withheld pattern file is %s: only the five built-in patterns are applied "
                   "to what this page shows." % wh.source_error)
    elif wh.extra_count == 0:
        out.append("Withheld pattern file gives no usable pattern (%d rejected): only the five "
                   "built-in patterns are applied to what this page shows."
                   % wh.rejected_count)
    elif wh.rejected_count:
        out.append("%d pattern(s) in the withheld pattern file do not compile and are ignored."
                   % wh.rejected_count)
    for n in sorted(cfg.nodes):
        st = threads.read_status(cfg, n)
        extra = st.get("withheld_extra") if st else None
        if isinstance(extra, int) and not isinstance(extra, bool) and extra == 0:
            out.append("Node %s reports withheld_extra 0: it loaded no pattern file and applies "
                       "only the five built-in patterns." % _t(wh, n, 60))
    return "".join('<p class="banner">%s</p>\n' % _e(b) for b in out)


# -- sections ------------------------------------------------------------------------------
def _nodes_table(cfg: Any, wh: Withheld) -> str:
    rows = []
    for n in sorted(cfg.nodes):
        s = threads.summary(cfg, n)
        st = threads.read_status(cfg, n) or {}
        if not s["synced"]:
            state = Raw("never synced")
            last_ok = ""
        else:
            state = "ok" if s["ok"] else "%s at %s" % (s["error"], s["stage"])
            last_ok = Raw("%s (%s)%s" % (_e(s["last_ok_at"]), _e(_age(s["age_s"])),
                                         ' <span class="stale">stale</span>' if s["stale"] else ""))
        head = st.get("tree_head")
        tree = (str(head)[:12] + ("" if st.get("tree_dirty") is None
                                  else " dirty %s" % st.get("tree_dirty"))) if head else ""
        rows.append([_t(wh, n, 60), state, last_ok, s["last_attempt_at"] or "",
                     _t(wh, s["node_version"], 40), _t(wh, s["protocol"], 20),
                     _t(wh, s["withheld_extra"], 20), _t(wh, tree, 40), s["undelivered"]])
    return _table(["node", "sync", "last success", "last attempt", "node version", "protocol",
                   "withheld_extra", "tree", "undelivered"], rows, "(no nodes configured)")


def _gpus(rec: dict) -> str:
    g = rec.get("gpus")
    return ",".join(str(x) for x in g) if isinstance(g, list) else ""


def _job_cells(wh: Withheld, j: dict, commands: bool) -> List[Any]:
    what = ("cancel of %s" % j.get("target_job_id") if j.get("op") == "cancel"
            else j.get("config_name"))
    jid = _t(wh, j.get("id"), 80)
    row = [jid, j.get("op"), _t(wh, j.get("node"), 60), _t(wh, what), _gpus(j),
           _t(wh, j.get("gpu_hours"), 40), _t(wh, j.get("note")), j.get("created") or "",
           j.get("approved_at") or j.get("rejected_at") or ""]
    if commands:
        row.append(Raw("<code>rb approve %s</code><br><code>rb reject %s</code>"
                       % (_e(jid), _e(jid))) if j.get("status") == "pending_approval" else "")
    return row


JOB_HEAD = ["job", "operation", "node", "config or target", "gpus", "gpu_hours", "note",
            "created", "approved/rejected"]


def _pending_section(data: dict, wh: Withheld) -> str:
    pend = [j for j in data["jobs"] if j.get("status") == "pending_approval"]
    return _table(JOB_HEAD + ["commands (type them in a hub terminal)"],
                  [_job_cells(wh, j, True) for j in pend], "(no pending approvals)")


def _preview(cfg: Any, wh: Withheld, rec: dict) -> str:
    body = threads.read_body(cfg, rec, wh)
    if body["missing"]:
        return "(body not stored)"
    return body["text"].split("\n", 1)[0][:100]


def _threads_table(cfg: Any, wh: Withheld, tlist: List[dict]) -> str:
    rows = []
    for t in tlist:
        rows.append([_link(wh, t["id"]), _t(wh, t["node"], 60), _preview(cfg, wh, t["records"][0]),
                     len(t["records"]), t["last_at"], t["state"], t["undelivered"]])
    return _table(["thread", "node", "first line", "records", "last activity", "state",
                   "undelivered"], rows, "(no conversations stored)")


def _index(cfg: Any, wh: Withheld) -> bytes:
    data = threads.load(cfg)
    body = (_banners(cfg, wh) + "<h2>Nodes</h2>\n" + _nodes_table(cfg, wh)
            + "<h2>Pending approvals</h2>\n" + _pending_section(data, wh)
            + "<h2>Latest conversations</h2>\n"
            + _threads_table(cfg, wh, data["threads"][:INDEX_THREADS]))
    return _page("Research bridge", body, 30)


def _threads_page(cfg: Any, wh: Withheld) -> bytes:
    data = threads.load(cfg)
    shown = data["threads"][:MAX_THREAD_ROWS]
    more = len(data["threads"]) - len(shown)
    body = _banners(cfg, wh) + _threads_table(cfg, wh, shown)
    if more > 0:
        body += "<p>%d more not shown.</p>\n" % more
    return _page("Conversations", body, 30)


def _event_facts(cfg: Any, wh: Withheld, ev: dict) -> Tuple[str, str, str]:
    text = threads.read_body(cfg, ev, wh, limit=4000)["text"]
    try:
        info = json.loads(text)
    except ValueError:
        info = {}
    info = info if isinstance(info, dict) else {}
    return (threads.node_time(ev), _t(wh, info.get("status"), 40),
            _t(wh, info.get("git_head"), 100)[:12])


def _jobs_page(cfg: Any, wh: Withheld) -> bytes:
    data = threads.load(cfg)
    order = ["pending_approval", "approved", "queued", "cancelled_requested", "rejected"]
    groups = {}  # type: Dict[str, List[dict]]
    for j in data["jobs"]:
        key = j.get("status") if j.get("status") in order else "other"
        groups.setdefault(str(key), []).append(j)
    parts = [_banners(cfg, wh)]
    for key in order + ["other"]:
        js = groups.get(key)
        if not js:
            continue
        rows = []
        for j in sorted(js, key=lambda r: str(r.get("created")), reverse=True):
            fin = Raw("<br>".join(_e("%s %s %s" % _event_facts(cfg, wh, ev))
                                  for ev in j["events"]))
            rows.append(_job_cells(wh, j, True) + [fin])
        parts.append("<h2>%s (%d)</h2>\n%s" % (_e(key), len(js), _table(
            JOB_HEAD + ["commands (type them in a hub terminal)", "job_finished events"], rows)))
    if not data["jobs"]:
        parts.append("<p>(no job records)</p>\n")
    if data["orphan_events"]:
        rows = []
        for ev in data["orphan_events"]:
            when, status, head = _event_facts(cfg, wh, ev)
            rows.append([when, _t(wh, ev.get("node"), 60), status, head])
        parts.append("<h2>Events whose job is not in the ledger</h2>\n"
                     + _table(["time", "node", "status", "git_head"], rows))
    return _page("Jobs", "".join(parts), 60)


def _items_table(wh: Withheld, items: Any) -> str:
    rows = [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []
    if not rows:
        return "<p>(no items)</p>"
    cols = []  # type: List[str]
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    return _table([_t(wh, c, 40) for c in cols],
                  [[_t(wh, r.get(c), 120) for c in cols] for r in rows])


def _status_dump(wh: Withheld, st: dict) -> str:
    rows = []
    for k in sorted(st):
        v = st[k]
        if isinstance(v, dict):
            v = ", ".join("%s=%s" % (a, b) for a, b in sorted(v.items()))
        rows.append([_t(wh, k, 40), _t(wh, v, 400)])
    return _table(["field", "value"], rows, "(no status file: rb sync has not run)")


def _nodes_page(cfg: Any, wh: Withheld) -> bytes:
    parts = [_banners(cfg, wh)]
    try:
        from . import board  # loads rb_host.server (and so mcp) on the first request only
        loaded = board.load(cfg)
        by_id = {s.get("source"): s for s in loaded.get("sources", []) if isinstance(s, dict)}
        names = board.NODE_SOURCES
    except Exception:
        by_id, names = {}, ()
        parts.append('<p class="err">board cache unavailable</p>\n')
    for n in sorted(cfg.nodes):
        st = threads.read_status(cfg, n) or {}
        parts.append("<h2>%s</h2>\n%s" % (_e(_t(wh, n, 60)), _status_dump(wh, st)))
        bmap = st.get("board") if isinstance(st.get("board"), dict) else {}
        for name in names:
            src = by_id.get("%s:%s" % (n, name))
            if src is None:
                continue
            title = "%s:%s" % (_t(wh, n, 60), name)
            if bmap.get(name) == "no_path":
                parts.append("<h3>%s</h3>\n<p>no path configured</p>\n" % _e(title))
                continue
            state = ("ok" if src.get("ok") else "error: %s" % _t(wh, src.get("error"), 60))
            stale = ' <span class="stale">stale</span>' if src.get("stale") else ""
            parts.append("<h3>%s</h3>\n<p>%s; fetched %s%s</p>\n%s\n" % (
                _e(title), _e(state), _e(src.get("fetched_at")), stale,
                _items_table(wh, src.get("items"))))
    return _page("Nodes", "".join(parts), 60)


def _attachment_section(cfg: Any, wh: Withheld, rec: dict) -> str:
    att = threads.attachments(cfg, rec, wh)
    rows = [[f["name"], f["bytes"], str(f["sha256"])[:12], f["status"]] for f in att["files"]]
    if not rows:  # no provenance file: names from the ledger record, still masked
        names = rec.get("files") if rec.get("direction") == "in" else rec.get("attachments")
        rows = [[_t(wh, nm, 200), "", "", ""] for nm in names] if isinstance(names, list) else []
    out = _table(["attachment", "bytes", "sha256 (12)", "status"], rows, "(no attachments)")
    nq = max(len(att["quarantined"]), int(rec.get("quarantined") or 0)
             if isinstance(rec.get("quarantined"), int) else 0)
    if nq:
        reasons = ", ".join(q["reason"] for q in att["quarantined"])
        out += "<p>quarantined files: %d%s</p>" % (nq, _e(" (%s)" % reasons) if reasons else "")
    return out


def _thread_page(cfg: Any, wh: Withheld, anyid: str) -> Tuple[int, str, bytes]:
    data = threads.load(cfg)
    tid = data["by_msg"].get(anyid)
    t = next((x for x in data["threads"] if x["id"] == tid), None)
    if t is None:
        return 404, "text/plain; charset=utf-8", b"not found"
    in_thread = {r["id"] for r in t["records"]}
    parts = [_banners(cfg, wh),
             "<p>thread %s · node %s · state <b>%s</b> · %d records</p>\n" % (
                 _e(_t(wh, t["id"], 128)), _e(_t(wh, t["node"], 60)), _e(t["state"]),
                 len(t["records"]))]
    for r in t["records"]:
        inbound = r.get("direction") == "in"
        kind = r.get("msg_kind") or "message"
        facts = [("time", threads.node_time(r)),
                 ("direction", "node to hub" if inbound else "hub to node"), ("kind", kind),
                 ("from_session", _t(wh, r.get("from_session"), 120)),
                 ("status", _t(wh, r.get("status"), 40))]
        if inbound and r.get("delivered") is False:
            facts.append(("poll", "not yet returned by poll"))
        rt = r.get("reply_to")
        if isinstance(rt, str) and rt:
            facts.append(("reply_to", _link(wh, rt) if rt in in_thread else
                          _t(wh, rt, 128) + (" (unknown)" if r["id"] in t["reply_to_unknown"]
                                             else "")))
        body = threads.read_body(cfg, r, wh)
        if body["missing"]:
            shown = "<p>%s</p>" % ("body file missing" if inbound else "body not stored")
        else:
            shown = "<pre>%s</pre>" % _e(body["text"])
        parts.append('<div class="rec"><h3>%s</h3>\n%s\n%s\n%s</div>\n' % (
            _e(_t(wh, r.get("id"), 128)),
            _table(["field", "value"], [[k, v] for k, v in facts]),
            _attachment_section(cfg, wh, r), shown))
    return 200, "text/html; charset=utf-8", _page("Thread", "".join(parts), 60)


def _healthz() -> bytes:
    """Liveness only: this route needs no session, so it carries no data of the hub."""
    return json.dumps({"ok": True}).encode("utf-8")


def render(cfg: Any, route: str, arg: Optional[str]) -> Tuple[int, str, bytes]:
    """(status, content type, body) for one route. Reads files only."""
    html_type = "text/html; charset=utf-8"
    if route == "healthz":
        return 200, "application/json; charset=utf-8", _healthz()
    wh = Withheld.load(Path(cfg.withheld_patterns_file))
    if route == "index":
        return 200, html_type, _index(cfg, wh)
    if route == "threads":
        return 200, html_type, _threads_page(cfg, wh)
    if route == "jobs":
        return 200, html_type, _jobs_page(cfg, wh)
    if route == "nodes":
        return 200, html_type, _nodes_page(cfg, wh)
    if route == "thread" and arg is not None:
        return _thread_page(cfg, wh, arg)
    return 404, "text/plain; charset=utf-8", b"not found"


# -- server ----------------------------------------------------------------------------------
class _Handler(BaseHTTPRequestHandler):
    server_version = "rb-web"
    sys_version = ""
    timeout = 10  # an idle connection must not hold a handler thread forever

    def _raw(self) -> str:
        parts = str(getattr(self, "requestline", "")).split()
        return parts[1] if len(parts) == 3 else ""

    def _plain(self, code: int, text: str, head: bool = False) -> None:
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _session_ok(self) -> bool:
        try:
            jar = SimpleCookie()
            jar.load(self.headers.get("Cookie") or "")
            morsel = jar.get(cookie_name(self.server.server_address[1]))  # type: ignore[attr-defined]
            token = morsel.value if morsel is not None else None
        except Exception:
            return False
        return webaccess.session_ok(self.server.cfg, token)  # type: ignore[attr-defined]

    def _enter(self, raw: str, head: bool) -> None:
        """GET /enter?key=...: exchange a one-time key for a session cookie. HEAD never does."""
        keys = []  # type: List[str]
        if not head and "?" in raw:
            keys = [v for k, v in urllib.parse.parse_qsl(raw.split("?", 1)[1].split("#")[0],
                                                          keep_blank_values=True) if k == "key"]
        got = webaccess.redeem(self.server.cfg, keys[0]) if len(keys) == 1 else None  # type: ignore[attr-defined]
        if got is None:
            return self._plain(401, NEED_KEY, head)
        token, seconds = got
        self.send_response(303)
        self.send_header("Location", "/")
        self.send_header("Set-Cookie", "%s=%s; HttpOnly; SameSite=Strict; Path=/; Max-Age=%d"
                         % (cookie_name(self.server.server_address[1]), token, seconds))  # type: ignore[attr-defined]
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()

    def _serve(self, head: bool) -> None:
        host = (self.headers.get("Host") or "").lower()
        if host not in self.server.allowed:  # type: ignore[attr-defined]
            return self._plain(403, "forbidden", head)
        raw = self._raw()
        route, arg = route_of(raw)
        if route == "other" or self.path.split("?", 1)[0] != raw.split("?", 1)[0]:
            return self._plain(404, "not found", head)
        if route == "enter":
            return self._enter(raw, head)
        if route != "healthz" and self.server.require_key and not self._session_ok():  # type: ignore[attr-defined]
            return self._plain(401, NEED_KEY, head)
        try:
            status, ctype, data = render(self.server.cfg, route, arg)  # type: ignore[attr-defined]
        except Exception:
            return self._plain(500, "error", head)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if not head:
            self.wfile.write(data)

    def do_GET(self) -> None:
        self._serve(False)

    def do_HEAD(self) -> None:
        self._serve(True)

    def _no_method(self) -> None:
        body = b"method not allowed"
        self.send_response(405)
        self.send_header("Allow", "GET, HEAD")
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        self.close_connection = True

    def send_error(self, code: int, message: Optional[str] = None,
                   explain: Optional[str] = None) -> None:
        if code == 501:
            return self._no_method()
        self.close_connection = True
        self._plain(code, "error", getattr(self, "command", None) == "HEAD")

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _no_method

    def log_request(self, code: Any = "-", size: Any = "-") -> None:
        # method, route name and status only: no path, id, query, address or header
        sys.stderr.write("%s %s %s\n" % (getattr(self, "command", None) or "-",
                                         route_of(self._raw())[0], code))

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        sys.stderr.write("request error: %s\n" % sys.exc_info()[0].__name__)


def check_bind(bind: str, port: int) -> None:
    if bind not in LOOPBACK_BINDS:
        raise ValueError("--bind accepts only 127.0.0.1; from another machine use: "
                         "ssh -N -L %d:127.0.0.1:%d <hub>" % (port, port))
    if not 0 <= port <= 65535:
        raise ValueError("--port must be between 0 and 65535")


def cookie_name(port: int) -> str:
    """Cookies are not separated by port, so the port is part of the name."""
    return "rb_web_%d" % port


def make_server(cfg: Any, bind: str = "127.0.0.1", port: int = DEFAULT_PORT,
                require_key: bool = True) -> ThreadingHTTPServer:
    """Build (do not start) the page server. Only a loopback bind is accepted.

    `require_key=False` serves every route without a session. It exists only for tests that are
    about rendering; no command-line flag or config key reaches it."""
    check_bind(bind, port)
    srv = _Server((bind, port), _Handler)
    srv.cfg = cfg  # type: ignore[attr-defined]
    srv.require_key = require_key  # type: ignore[attr-defined]
    srv.allowed = allowed_hosts(srv.server_address[1])  # type: ignore[attr-defined]
    return srv


def serve(cfg: Any, bind: str, port: int) -> None:
    srv = make_server(cfg, bind, port)
    sys.stderr.write("serving the read-only hub page on http://127.0.0.1:%d/\n"
                     % srv.server_address[1])
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


def key_main(args: argparse.Namespace) -> int:
    """rb web key: issue a one-time access key, or revoke everything, or show counts."""
    if args.revoke or args.status:
        cfg = configure.host_cfg()
        if cfg is None:
            return 1
        if args.revoke:
            k, n = webaccess.revoke_all(cfg)
            print("revoked %d pending key(s) and %d session(s)" % (k, n))
        else:
            k, n = webaccess.counts(cfg)
            print("%d pending key(s), %d live session(s)" % (k, n))
        return 0
    lo, hi = webaccess.KEY_MINUTES
    if not lo <= args.minutes <= hi:
        print("error: --minutes must be between %d and %d" % (lo, hi))
        return 1
    lo, hi = webaccess.SESSION_HOURS
    if not lo <= args.session_hours <= hi:
        print("error: --session-hours must be between %d and %d" % (lo, hi))
        return 1
    if not 1 <= args.port <= 65535:
        print("error: --port must be between 1 and 65535")
        return 1
    cfg = configure.host_cfg()
    if cfg is None:
        return 1
    try:
        key = webaccess.issue_key(cfg, args.minutes, args.session_hours)
    except OSError as exc:
        print("error: cannot write the access file (%s)" % (exc.strerror or type(exc).__name__))
        return 1
    expires = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + args.minutes * 60))
    print("http://127.0.0.1:%d/enter?key=%s" % (args.port, key))
    print("the key works once and expires at %s (%d minutes)" % (expires, args.minutes))
    print("the browser session then lasts %d hours" % args.session_hours)
    return 0


def cli_main(args: argparse.Namespace) -> int:
    if args.action == "key":
        return key_main(args)
    try:
        check_bind(args.bind, args.port)
    except ValueError as exc:
        print("error: %s" % exc)
        return 1
    cfg = configure.host_cfg()
    if cfg is None:
        return 1
    try:
        serve(cfg, args.bind, args.port)
    except OSError as exc:
        print("error: cannot listen on %s:%d (%s)" % (args.bind, args.port,
                                                      exc.strerror or type(exc).__name__))
        return 1
    return 0
