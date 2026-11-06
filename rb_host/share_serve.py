"""Shared status page: static HTML renderer and a two-file HTTP server (docs/design/2026-11-06-shared-status-page.md).

`render_html` turns a snapshot dict into one self-contained HTML document (no script, no external
URL). `make_server` / `serve` publish exactly `index.html` and `snapshot.json` from one directory,
GET and HEAD only. Neither opens an outgoing connection.
"""
from __future__ import annotations

import html
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

DEFAULT_PORT = 8766
# Raw request path -> published file. Anything else is 404 before any unquoting.
ALLOWED_PATHS = ("/", "/index.html", "/snapshot.json")
CONTENT_TYPES = {"index.html": "text/html; charset=utf-8",
                 "snapshot.json": "application/json; charset=utf-8"}
CSP = "default-src 'none'; style-src 'unsafe-inline'"
STYLE = ("body{font-family:system-ui,sans-serif;margin:16px;max-width:1100px}"
         "table{border-collapse:collapse;margin:4px 0 16px}td,th{border:1px solid #bbb;"
         "padding:3px 8px;text-align:left}.err{color:#b00020}.stale{color:#a15c00}"
         ".owner{background:#fff3cd;padding:4px 8px}")


# -- renderer ---------------------------------------------------------------------------
def _e(v: Any) -> str:
    return html.escape(str(v), quote=True)


def _unavailable(why: Any = "missing") -> str:
    return '<p class="err">unavailable (%s)</p>' % _e(why)


def _rows(v: Any) -> List[dict]:
    return [r for r in v if isinstance(r, dict)] if isinstance(v, list) else []


def _table(head: List[str], rows: List[List[Any]]) -> str:
    if not rows:
        return "<p>(no items)</p>"
    th = "".join("<th>%s</th>" % _e(h) for h in head)
    body = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % _e(c) for c in r) for r in rows)
    return "<table><tr>%s</tr>%s</table>" % (th, body)


def _section(title: str, body: Callable[[], str]) -> str:
    try:
        inner = body()
    except Exception:  # a malformed section must not take the page down
        inner = _unavailable("malformed")
    return "<h2>%s</h2>\n%s\n" % (_e(title), inner)


def _sources(snap: dict) -> str:
    srcs = _rows(snap.get("sources"))
    if not srcs:
        return _unavailable()
    rows = []
    for s in srcs:
        ok = s.get("ok")
        status = "ok" if ok else "error: %s" % s.get("error", "unknown")
        rows.append([s.get("id", ""), s.get("fetched_at") or "", status,
                     "stale" if s.get("stale") else ""])
    return _table(["id", "fetched_at", "status", "stale"], rows)


def _sessions_day(snap: dict) -> str:
    ses = snap.get("sessions")
    if not isinstance(ses, dict) or "per_day" not in ses:
        return _unavailable()
    return _table(["date", "lane", "project", "count", "active_h"],
                  [[r.get("date", ""), r.get("lane", ""), r.get("project", ""),
                    r.get("count", ""), r.get("active_h", "")] for r in _rows(ses["per_day"])])


def _totals(snap: dict) -> str:
    ses = snap.get("sessions")
    t = ses.get("totals") if isinstance(ses, dict) else None
    if not isinstance(t, dict):
        return _unavailable()
    rows = [[k, t[k]] for k in ("sessions", "routines", "active_h") if k in t]
    if snap.get("tier") == "owner" and "cost_usd" in t:
        rows.append(["cost_usd", "unavailable" if t["cost_usd"] is None else t["cost_usd"]])
    return _table(["total", "value"], rows)


def _exp(snap: dict, key: str) -> Any:
    ex = snap.get("experiments")
    return ex.get(key) if isinstance(ex, dict) else None


def _queue(snap: dict) -> str:
    q = _exp(snap, "queue")
    if not isinstance(q, dict):
        return _unavailable()
    return _table(["state", "count"], [[k, v] for k, v in q.items()])


def _gpu(snap: dict) -> str:
    g = _exp(snap, "gpu")
    if not isinstance(g, dict):
        return _unavailable()
    return _table(["field", "value"], [[k, v] for k, v in g.items()])


def _runs(snap: dict) -> str:
    r = _exp(snap, "runs_per_day")
    if not isinstance(r, list):
        return _unavailable()
    return _table(["date", "project", "started", "finished", "failed"],
                  [[x.get("date", ""), x.get("project", ""), x.get("started", ""),
                    x.get("finished", ""), x.get("failed", "")] for x in _rows(r)])


def _tracks(snap: dict) -> str:
    for s in _rows(snap.get("sources")):
        if str(s.get("id", "")).endswith(":events") and s.get("ok") is False:
            return '<p class="err">stage data: unavailable (%s)</p>' % _e(s.get("error", "unknown"))
    t = _exp(snap, "tracks")
    if not isinstance(t, list):
        return _unavailable()
    return _table(["track", "stage", "last_event_age_s"],
                  [[x.get("track", ""), x.get("stage", ""), x.get("last_event_age_s", "")]
                   for x in _rows(t)])


def _waiting(snap: dict) -> str:
    w = snap.get("waiting")
    if not isinstance(w, list):
        return _unavailable()
    if not w:
        return "<p>(no items)</p>"
    return _table(["source", "ref", "what"],
                  [[x.get("source", ""), x.get("ref", ""), x.get("what", "")] for x in _rows(w)])


def render_html(snapshot: dict) -> str:
    """One complete HTML document for a snapshot. Never raises on a missing section or key."""
    snap = snapshot if isinstance(snapshot, dict) else {}
    per = snap.get("period") if isinstance(snap.get("period"), dict) else {}
    owner = snap.get("tier") == "owner"
    parts = ["<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
             "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
             "<meta http-equiv=\"refresh\" content=\"300\">"
             "<title>research status</title><style>%s</style></head><body>\n" % STYLE,
             "<!-- research-bridge share page; schema_version %s -->\n" % _e(snap.get("schema_version", "unknown")),
             "<h1>Research status</h1>\n"]
    if owner:
        parts.append('<p class="owner">owner view (loopback only)</p>\n')
    parts.append("<p>period: %s to %s<br>built at: %s (stale flags as of build time)</p>\n" % (
        _e(per.get("from", "unavailable")), _e(per.get("to", "unavailable")),
        _e(snap.get("built_at", "unavailable"))))
    parts.append(_section("Sources", lambda: _sources(snap)))
    parts.append(_section("Sessions per day", lambda: _sessions_day(snap)))
    parts.append(_section("Totals", lambda: _totals(snap)))
    parts.append(_section("Queue", lambda: _queue(snap)))
    parts.append(_section("GPU", lambda: _gpu(snap)))
    parts.append(_section("Runs per day", lambda: _runs(snap)))
    parts.append(_section("Tracks", lambda: _tracks(snap)))
    if owner and "waiting" in snap:
        parts.append(_section("Waiting", lambda: _waiting(snap)))
    if snap.get("dropped"):
        parts.append("<p>dropped items: %s</p>\n" % _e(snap.get("dropped")))
    parts.append("</body></html>\n")
    return "".join(parts)


# -- server -----------------------------------------------------------------------------
def _check_tier(root: Path) -> None:
    p = Path(root) / "snapshot.json"
    if not p.is_file():
        return
    try:
        tier = json.loads(p.read_text(encoding="utf-8")).get("tier")
    except (ValueError, OSError, AttributeError):
        tier = None
    if tier != "shared":
        raise ValueError("snapshot tier is not shared")


class _Handler(BaseHTTPRequestHandler):
    root = Path(".")  # type: Path
    server_version = "rb-share"
    sys_version = ""
    timeout = 10  # an idle connection must not hold a handler thread forever

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

    def _serve(self, head: bool) -> None:
        parts = self.requestline.split()
        raw = parts[1] if len(parts) > 1 else ""
        if raw not in ALLOWED_PATHS or self.path not in ALLOWED_PATHS:
            return self._plain(404, "not found", head)
        name = "snapshot.json" if self.path == "/snapshot.json" else "index.html"
        target = Path(self.root) / name
        if os.path.islink(str(target)) or not target.is_file():
            return self._plain(404, "not found", head)
        try:
            data = target.read_bytes()
        except OSError:
            return self._plain(404, "not found", head)
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES[name])
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", CSP)
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
        # Never the default HTML error body: unknown methods get our 405, the rest plain text.
        if code == 501:
            return self._no_method()
        self.close_connection = True
        self._plain(code, "error", self.command == "HEAD")

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _no_method

    def log_request(self, code: Any = "-", size: Any = "-") -> None:
        # method, path (query stripped), status only; no body.
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        if path not in ALLOWED_PATHS:
            path = "<other>"
        sys.stderr.write("%s %s %s\n" % (self.command, path, code))

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass  # request lines come from log_request; parse errors carry no useful data


class _Server(ThreadingHTTPServer):
    def handle_error(self, request: Any, client_address: Any) -> None:
        sys.stderr.write("request error: %s\n" % sys.exc_info()[0].__name__)


def make_server(root: Path, bind: str, port: int) -> ThreadingHTTPServer:
    """Build (do not start) the server for `root`. Refuses a snapshot whose tier is not shared."""
    _check_tier(root)
    handler = type("ShareHandler", (_Handler,), {"root": Path(root)})
    srv = _Server((bind, port), handler)
    srv.daemon_threads = True
    return srv


def serve(root: Path, bind: str = "127.0.0.1", port: int = DEFAULT_PORT) -> None:
    srv = make_server(root, bind, port)
    where = "loopback only" if bind in ("127.0.0.1", "localhost") else "LAN"
    sys.stderr.write("serving %s on %s:%s (index.html, snapshot.json only) (%s)\n"
                     % (root, bind, srv.server_address[1], where))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
