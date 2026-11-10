"""rb web serve: the read-only hub page (design 2026-11-10 §6.6, §7).
The server runs on an ephemeral loopback port; requests are raw sockets so targets are sent exactly."""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from rb_host import cli, jobs, threads, web, webaccess
from rb_host.client import NodeClient
from rb_host.config import HostConfig
from rb_host.ledger import Ledger

REPO = Path(__file__).resolve().parents[1]
ROUTES = ["/", "/threads", "/thread/msgid-7f3a", "/jobs", "/nodes", "/healthz"]
NOW = "2026-11-10T00:00:00Z"
Q_BODY = "question first line\nsecond line"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("RB_HOST_CONFIG", str(tmp_path / "host.json"))
    monkeypatch.setenv("RB_HOST_ROOT", str(tmp_path / "root"))

    def refuse(cfg, node):
        raise AssertionError("jobs.connect used")
    monkeypatch.setattr(jobs, "connect", refuse)


def _stamp(offset_s=0):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - offset_s))


def put(cfg, rec, text, prov=None):
    sub = "inbox" if rec["direction"] == "in" else "outbox"
    d = Path(cfg.data_root) / sub / rec["node"] / rec["id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "body.txt").write_text(text, encoding="utf-8")
    if prov is not None:
        (d / "provenance.json").write_text(json.dumps(prov), encoding="utf-8")


@pytest.fixture
def cfg(tmp_path):
    root = tmp_path / "data"
    (root / "host.json").parent.mkdir(parents=True, exist_ok=True)
    (root / "host.json").write_text('{"marker": "HOSTJSON-MARKER"}', encoding="utf-8")
    wp = tmp_path / "withheld.json"
    wp.write_text(json.dumps({"patterns": ["unrelatedfam_"]}), encoding="utf-8")
    c = HostConfig(nodes={"n1": {"alias": "x"}}, data_root=str(root),
                   withheld_patterns_file=str(wp))
    led = Ledger(root / "ledger.jsonl")
    m1 = {"kind": "message", "id": "msgid-7f3a", "direction": "out", "node": "n1",
          "reply_to": None, "from_session": "sess-a", "attachments": ["a.txt"],
          "body_chars": len(Q_BODY), "status": "sent", "created": "2026-11-10T00:00:01Z"}
    r1 = {"kind": "message", "id": "%020d-abcd1234" % (1_762_732_800 * 10 ** 9),
          "direction": "in", "node": "n1", "msg_kind": "reply", "reply_to": "msgid-7f3a",
          "files": [], "quarantined": 0, "status": "received",
          "created": "2026-11-10T00:00:02Z", "delivered": False}
    m2 = {"kind": "message", "id": "follow-1", "direction": "out", "node": "n1",
          "reply_to": r1["id"], "from_session": "", "attachments": [], "body_chars": 3,
          "status": "sent", "created": "2026-11-10T00:00:03Z"}
    for r in (m1, r1, m2):
        led.append(r)
    put(c, m1, Q_BODY, prov={"node": "n1", "msg_id": m1["id"], "attachments": [
        {"index": 0, "name": "a.txt", "bytes": 5, "sha256": "ab" * 32}]})
    put(c, r1, "the answer", prov={"files": [
        {"index": 0, "name": "REAL-QUARANTINED-NAME.bin", "status": "quarantined",
         "reason": "deny_name"}]})
    put(c, m2, "ok")
    led.append({"kind": "job", "op": "submit", "id": "job-pend", "node": "n1",
                "config_name": "sweep.yaml", "config_path": "/x/sweep.yaml", "gpus": [0, 1],
                "gpu_hours": 4, "note": "note-one", "status": "pending_approval",
                "created": "2026-11-10T00:00:04Z"})
    led.append({"kind": "job", "op": "submit", "id": "job-queued", "node": "n1",
                "config_name": "other.yaml", "gpus": [0], "gpu_hours": 1,
                "status": "queued", "created": "2026-11-10T00:00:05Z"})
    ev = {"kind": "message", "id": "ev-1", "direction": "in", "node": "n1",
          "msg_kind": "event", "status": "received", "created": "2026-11-10T00:00:06Z",
          "delivered": True}
    led.append(ev)
    put(c, ev, json.dumps({"event": "job_finished", "job_id": "job-queued",
                           "status": "done", "git_head": "0123456789abcdef0123"}))
    sd = Path(root) / "sync"
    sd.mkdir()
    (sd / "n1.json").write_text(json.dumps({
        "schema": 1, "node": "n1", "last_attempt_at": _stamp(5), "last_ok_at": _stamp(5),
        "ok": True, "error": None, "stage": None, "new_items": 1, "rejected": 0,
        "board": {"queue": "ok", "gpu": "ok", "state": "no_path", "events": "no_path",
                  "kanban": "no_path"},
        "node_version": "9.9", "protocol": 2, "withheld_extra": 3, "node_seen_at": _stamp(5),
        "tree_head": "f" * 40, "tree_dirty": 2, "git_error": None, "duration_s": 1.5}),
        encoding="utf-8")
    bd = Path(root) / "board"
    bd.mkdir()
    (bd / "n1_queue.json").write_text(json.dumps({
        "source": "n1:queue", "fetched_at": _stamp(5), "attempted_at": _stamp(5), "ok": True,
        "error": None, "cadence_s": 600, "items": [{"state": "queued", "count": 2}]}),
        encoding="utf-8")
    return c


@pytest.fixture
def srv(cfg):
    s = web.make_server(cfg, "127.0.0.1", 0)
    t = threading.Thread(target=s.serve_forever, daemon=True)
    t.start()
    # sign in with a real key, as a browser does; req() then sends the cookie
    token, _secs = webaccess.redeem(cfg, webaccess.issue_key(cfg, 10, 12))
    s.cookie = "%s=%s" % (web.cookie_name(s.server_address[1]), token)
    s.token = token
    try:
        yield s
    finally:
        s.shutdown()
        s.server_close()
        t.join(5)


def req(srv, target, method="GET", host="default", extra="", cookie="auto"):
    port = srv.server_address[1]
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        msg = "%s %s HTTP/1.1\r\n" % (method, target)
        if host == "default":
            host = "127.0.0.1:%d" % port
        if host is not None:
            msg += "Host: %s\r\n" % host
        if cookie == "auto":
            cookie = getattr(srv, "cookie", None)
        if cookie:
            msg += "Cookie: %s\r\n" % cookie
        msg += extra + "Connection: close\r\n\r\n"
        s.sendall(msg.encode("latin-1"))
        data = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    headers = {}
    for ln in lines[1:]:
        k, _, v = ln.partition(":")
        headers[k.strip().lower()] = v.strip()
    return int(lines[0].split()[1]), headers, body.decode("utf-8")


def snapshot(*roots):
    out = {}
    for r in roots:
        for p in sorted(Path(r).rglob("*")):
            if p.is_file():
                st = p.stat()
                out[str(p)] = (st.st_size, st.st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
    return out


# -- addressing -------------------------------------------------------------------------
def test_route_of_and_allowed_hosts():
    assert web.route_of("/") == ("index", None)
    assert web.route_of("/?x=1") == ("index", None)
    assert web.route_of("/threads") == ("threads", None)
    assert web.route_of("/thread/abc.D-1_x?q=1") == ("thread", "abc.D-1_x")
    assert web.route_of("/jobs") == ("jobs", None)
    assert web.route_of("/nodes") == ("nodes", None)
    assert web.route_of("/healthz") == ("healthz", None)
    for bad in ("/thread/", "/thread/%2e%2e", "/thread/a/b", "//x", "/x", "", "http://h/",
                "/thread/" + "a" * 129, "/jobs/", "/threads\n"):
        assert web.route_of(bad) == ("other", None), bad
    assert web.allowed_hosts(8767) == frozenset(
        ["127.0.0.1:8767", "localhost:8767", "[::1]:8767"])


def test_wrong_host_refused(srv):
    port = srv.server_address[1]
    for host in ("evil.example:%d" % port, "127.0.0.1", "127.0.0.1:1",
                 "localhost:%d" % (port + 1), "", None):
        for route in ROUTES:
            code, _h, body = req(srv, route, host=host)
            assert (code, body) == (403, "forbidden"), (host, route)


def test_loopback_host_names_accepted(srv):
    port = srv.server_address[1]
    for host in ("localhost:%d" % port, "LOCALHOST:%d" % port, "[::1]:%d" % port,
                 "127.0.0.1:%d" % port):
        assert req(srv, "/healthz", host=host, cookie=None)[0] == 200


def test_only_get_and_head(srv):
    for method in ("POST", "PUT", "DELETE", "PATCH", "OPTIONS"):
        code, headers, _b = req(srv, "/", method=method)
        assert code == 405 and headers["allow"] == "GET, HEAD", method
    code, headers, body = req(srv, "/", method="HEAD")
    assert code == 200 and body == "" and int(headers["content-length"]) > 0


def test_path_traversal_is_404(srv):
    targets = ["/thread/../host.json", "/thread/%2e%2e%2fhost.json",
               "/thread/..%2F..%2Fledger.jsonl", "//etc/passwd", "/thread/" + "a" * 200,
               "/thread/unknownid", "/static/x"]
    for t in targets:
        code, _h, body = req(srv, t)
        assert code == 404, t
        assert "HOSTJSON-MARKER" not in body and "msgid-7f3a" not in body, t


# -- content ----------------------------------------------------------------------------
def test_all_routes_render(srv):
    for route in ROUTES[:-1]:
        code, headers, body = req(srv, route)
        assert code == 200 and headers["content-type"].startswith("text/html"), route
    code, headers, body = req(srv, "/healthz")
    data = json.loads(body)
    assert code == 200 and data == {"ok": True}
    assert headers["content-type"].startswith("application/json")
    _c, _h, index = req(srv, "/")
    assert 'http-equiv="refresh" content="30"' in index
    _c, _h, thread = req(srv, "/thread/msgid-7f3a")
    assert 'http-equiv="refresh" content="60"' in thread
    # the whole component is shown from any of its ids
    assert "the answer" in thread and "follow-1" in thread and Q_BODY.split("\n")[0] in thread
    other = "/thread/follow-1"
    assert "the answer" in req(srv, other)[2]
    # state words, undelivered marker, node line
    assert "not yet returned by poll" in thread
    assert "n1" in index and "9.9" in index and "f" * 12 in index and "f" * 13 not in index
    # job_finished event beside its job
    _c, _h, jobs_page = req(srv, "/jobs")
    assert "job-queued" in jobs_page and "0123456789ab" in jobs_page
    assert "0123456789abc" not in jobs_page
    # board table and "no path configured"
    _c, _h, nodes_page = req(srv, "/nodes")
    assert "no path configured" in nodes_page and "queued" in nodes_page


def test_unknown_source_without_path_shows_no_path(srv):
    _c, _h, nodes_page = req(srv, "/nodes")
    assert nodes_page.count("no path configured") == 3  # state, events, kanban


def test_pending_job_shows_command_and_no_form(srv):
    for route in ("/", "/jobs"):
        _c, _h, body = req(srv, route)
        assert "rb approve job-pend" in body and "rb reject job-pend" in body, route
        assert "note-one" in body and "sweep.yaml" in body
    for route in ROUTES:
        assert "<form" not in req(srv, route)[2], route


def test_body_and_fields_escaped_and_cleaned(cfg, srv):
    led = Ledger(Path(cfg.data_root) / "ledger.jsonl")
    rec = {"kind": "message", "id": "xss-1", "direction": "out", "node": "n1",
           "reply_to": None, "from_session": "x‮<b>", "attachments": [],
           "status": "sent", "created": "2026-11-10T00:00:07Z"}
    led.append(rec)
    put(cfg, rec, "<script>alert(1)</script>\nsee https://example.org/x")
    code, headers, body = req(srv, "/thread/xss-1")
    assert code == 200
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body and "<script" not in body
    assert "x&lt;b&gt;" in body and "‮" not in body
    assert "https://example.org/x" in body and 'href="https' not in body
    assert body.count("<nav>") == 1 and '<a href="/nodes">' in body
    for route in ROUTES:
        assert "‮" not in req(srv, route)[2]
    assert "<script" not in "".join(req(srv, r)[2] for r in ROUTES)


def test_body_remasked_at_render(cfg, srv):
    led = Ledger(Path(cfg.data_root) / "ledger.jsonl")
    rec = {"kind": "message", "id": "late-1", "direction": "out", "node": "n1",
           "reply_to": None, "from_session": "", "attachments": [], "status": "sent",
           "created": "2026-11-10T00:00:08Z"}
    led.append(rec)
    put(cfg, rec, "secretfam_root line\nvisible tail")
    assert "secretfam_root" in req(srv, "/thread/late-1")[2]  # not yet withheld
    Path(cfg.withheld_patterns_file).write_text(json.dumps({"patterns": ["secretfam_"]}),
                                                encoding="utf-8")
    for route in ("/thread/late-1", "/threads", "/"):
        body = req(srv, route)[2]
        assert "secretfam_" not in body, route
    assert "visible tail" in req(srv, "/thread/late-1")[2]


def test_withheld_banner_when_pattern_file_missing(cfg, srv):
    assert "pattern file" not in req(srv, "/")[2].lower()
    os.unlink(cfg.withheld_patterns_file)
    for route in ("/", "/threads", "/thread/msgid-7f3a", "/jobs", "/nodes"):
        assert "withheld pattern file" in req(srv, route)[2].lower(), route


@pytest.mark.parametrize("text", ['[]', '{}', '{"patterns": ["("]}'])
def test_withheld_banner_when_file_gives_no_usable_pattern(cfg, srv, text):
    Path(cfg.withheld_patterns_file).write_text(text, encoding="utf-8")
    assert "no usable pattern" in req(srv, "/")[2].lower()


def test_withheld_banner_when_some_patterns_do_not_compile(cfg, srv):
    Path(cfg.withheld_patterns_file).write_text('{"patterns": ["(", "usable_extra_"]}',
                                                encoding="utf-8")
    body = req(srv, "/")[2].lower()
    assert "1 pattern(s) in the withheld pattern file do not compile and are ignored" in body
    assert "no usable pattern" not in body and "only the five" not in body


def test_withheld_banner_when_node_has_no_extra_patterns(cfg, srv):
    p = Path(cfg.data_root) / "sync" / "n1.json"
    st = json.loads(p.read_text(encoding="utf-8"))
    st["withheld_extra"] = 0
    p.write_text(json.dumps(st), encoding="utf-8")
    assert "withheld_extra" in req(srv, "/")[2]


def test_quarantined_names_never_shown(srv):
    body = req(srv, "/thread/msgid-7f3a")[2]
    assert "REAL-QUARANTINED-NAME" not in body
    assert "deny_name" in body and "quarantined" in body.lower()
    assert "a.txt" in body and "ab" * 6 in body and "ab" * 7 not in body


def test_withheld_attachment_name_hidden_at_render(cfg, srv):
    Path(cfg.withheld_patterns_file).write_text(json.dumps({"patterns": ["secretfam_"]}),
                                                encoding="utf-8")
    rec = {"kind": "message", "id": "att-1", "direction": "out", "node": "n1", "reply_to": None,
           "from_session": "secretfam_sess", "attachments": ["secretfam_a.txt"],
           "status": "sent", "created": "2026-11-10T00:00:09Z"}
    Ledger(Path(cfg.data_root) / "ledger.jsonl").append(rec)
    put(cfg, rec, "b", prov={"attachments": [{"index": 0, "name": "secretfam_a.txt", "bytes": 1,
                                              "sha256": "00" * 32}]})
    body = req(srv, "/thread/att-1")[2]
    assert "secretfam_" not in body and "(withheld)" in body


def test_ids_that_do_not_fit_the_route_are_not_linked(cfg, srv):
    rec = {"kind": "message", "id": "has space", "direction": "out", "node": "n1",
           "reply_to": None, "from_session": "", "attachments": [], "status": "sent",
           "created": "2026-11-10T00:00:10Z"}
    Ledger(Path(cfg.data_root) / "ledger.jsonl").append(rec)
    put(cfg, rec, "spaced")
    body = req(srv, "/threads")[2]
    assert "has space" in body and 'href="/thread/has space' not in body
    assert req(srv, "/thread/has%20space")[0] == 404


FIXED_ROUTES = {"/", "/threads", "/jobs", "/nodes"}
THREAD_HREF = r"/thread/[A-Za-z0-9][A-Za-z0-9._-]{0,127}"


def test_security_headers(srv):
    for route in ROUTES:
        code, headers, body = req(srv, route)
        assert code == 200
        assert headers["content-security-policy"] == web.CSP
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["cache-control"] == "no-store"
        assert headers["referrer-policy"] == "no-referrer"
        assert "<script" not in body and "src=" not in body
        hrefs = re.findall(r'href="([^"]*)"', body)
        for href in hrefs:
            assert href in FIXED_ROUTES or re.fullmatch(THREAD_HREF, href), (route, href)
        assert body.lower().count("href=") == len(hrefs), route  # no single-quoted or bare href
        if route != "/healthz":
            assert [h for h in hrefs if h in FIXED_ROUTES][:4] == ["/", "/threads", "/jobs", "/nodes"]
            assert body.count("<nav>") == 1


def test_page_opens_no_connection(srv, monkeypatch):
    from rb_host import board  # noqa: F401  (imported lazily by /nodes; load it before patching)

    def boom(*a, **k):
        raise AssertionError("the page opened a connection")
    monkeypatch.setattr(jobs, "connect", boom)
    monkeypatch.setattr(NodeClient, "__enter__", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    for route in ROUTES:
        assert req(srv, route)[0] == 200, route


def test_page_writes_no_file(cfg, srv, tmp_path):
    before = snapshot(tmp_path)
    for route in ROUTES:
        assert req(srv, route)[0] == 200
    assert snapshot(tmp_path) == before


def test_no_http_client_or_mcp_import():
    for mod in ("web.py", "threads.py"):
        src = (REPO / "rb_host" / mod).read_text(encoding="utf-8")
        for bad in ("urllib.request", "http.client", "requests", "socket.create_connection"):
            assert bad not in src, (mod, bad)
    out = subprocess.run([sys.executable, "-c",
                          "import rb_host.web, sys; print('mcp' in sys.modules)"],
                         cwd=str(REPO), capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "False", out.stderr


def test_access_log_has_route_names_only(srv, capsys):
    capsys.readouterr()
    assert req(srv, "/thread/msgid-7f3a?q=MARK")[0] == 200
    assert req(srv, "/nope")[0] == 404
    assert req(srv, "/", host="evil.example")[0] == 403
    err = capsys.readouterr().err.splitlines()
    assert "GET thread 200" in err and "GET other 404" in err and "GET index 403" in err
    joined = "\n".join(err)
    assert "msgid-7f3a" not in joined and "MARK" not in joined and "127.0.0.1" not in joined


# -- bind and cli ------------------------------------------------------------------------
def test_wildcard_bind_refused(cfg):
    for bind in ("0.0.0.0", "::", "", "::1"):
        with pytest.raises(ValueError):
            web.make_server(cfg, bind, 0)


def test_non_loopback_bind_refused(cfg, monkeypatch, capsys):
    with pytest.raises(ValueError) as ei:
        web.make_server(cfg, "192.0.2.10", 0)
    assert "ssh -N -L" in str(ei.value)
    assert web.allowed_hosts(8767) == frozenset(["127.0.0.1:8767", "localhost:8767", "[::1]:8767"])

    def boom(*a, **k):
        raise AssertionError("a server was started")
    monkeypatch.setattr(web, "make_server", boom)
    monkeypatch.setattr(web, "serve", boom)
    assert cli.main(["web", "serve", "--bind", "192.0.2.10", "--port", "8767"]) == 1
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1 and lines[0].startswith("error:")
    assert "ssh -N -L 8767:127.0.0.1:8767" in lines[0]


def test_cli_web_serve_without_host_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("RB_HOST_CONFIG", str(tmp_path / "missing" / "host.json"))
    monkeypatch.setenv("RB_HOST_ROOT", str(tmp_path / "emptyroot"))

    def boom(*a, **k):
        raise AssertionError("a server was started")
    monkeypatch.setattr(web, "make_server", boom)
    monkeypatch.setattr(web, "serve", boom)
    assert cli.main(["web", "serve"]) == 1
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines == ["error: no usable host.json at %s; run: rb setup --node NAME --host HOST "
                     "--user USER" % (tmp_path / "missing" / "host.json")]


def test_cli_web_serve_starts_server_with_defaults(cfg, tmp_path, monkeypatch):
    host = tmp_path / "ok-host.json"
    host.write_text(json.dumps({"nodes": {"n1": {"alias": "x"}}, "data_root": cfg.data_root}),
                    encoding="utf-8")
    monkeypatch.setenv("RB_HOST_CONFIG", str(host))
    seen = {}
    monkeypatch.setattr(web, "serve", lambda c, bind, port: seen.update(bind=bind, port=port))
    assert cli.main(["web", "serve"]) == 0
    assert seen == {"bind": "127.0.0.1", "port": web.DEFAULT_PORT}


def test_nodes_table_cleans_and_masks_node_values(cfg, srv):
    sp = Path(cfg.data_root) / "sync" / "n1.json"
    st = json.loads(sp.read_text(encoding="utf-8"))
    st["node_version"] = "9\u202e.9"
    st["tree_head"] = "abc"
    sp.write_text(json.dumps(st), encoding="utf-8")
    body = req(srv, "/")[2]
    assert "\u202e" not in body and "9.9" in body


def test_removed_path_shows_no_path_even_with_cache(cfg, srv):
    bd = Path(cfg.data_root) / "board"
    (bd / "n1_state.json").write_text(json.dumps({
        "source": "n1:state", "fetched_at": _stamp(5), "attempted_at": _stamp(5), "ok": True,
        "error": None, "cadence_s": 600, "items": [{"phase": "OLD-CACHED-PHASE"}]}),
        encoding="utf-8")
    page = req(srv, "/nodes")[2]
    assert page.count("no path configured") == 3
    assert "OLD-CACHED-PHASE" not in page


# -- access control ------------------------------------------------------------------------
NEED = 'access key required: run "rb web key" in a hub terminal and open the address it prints'


def test_every_protected_route_needs_a_session(srv):
    for route in ROUTES[:-1] + ["/thread/unknown-id", "/thread/follow-1"]:
        for method in ("GET", "HEAD"):
            code, headers, body = req(srv, route, method=method, cookie=None)
            assert code == 401, (route, method)
            assert headers["content-type"] == "text/plain; charset=utf-8"
            assert body == (NEED if method == "GET" else ""), route
        assert req(srv, route)[0] in (200, 404)
    assert req(srv, "/thread/unknown-id")[0] == 404  # with a session the id lookup shows
    assert req(srv, "/healthz", cookie=None)[0] == 200
    assert req(srv, "/nope", cookie=None)[0] == 404  # routes that do not exist stay 404
    assert req(srv, "/", host="evil.example", cookie=None)[0] == 403  # Host check is first
    assert req(srv, "/", method="POST", cookie=None)[0] == 405


def test_bad_cookies_are_ignored(srv):
    port = srv.server_address[1]
    good = srv.token
    for c in ("rb_web_%d=%s" % (port + 1, good), "other=%s" % good, "rb_web_%d=" % port,
              "rb_web_%d=short" % port, "rb_web_%d=%s" % (port, "A" * 43), "\x01\x02;;==",
              "rb_web_%d=%s=" % (port, good + "!")):
        assert req(srv, "/", cookie=c)[0] == 401, c
    assert req(srv, "/", cookie="x=1; rb_web_%d=%s" % (port, good))[0] == 200


def test_enter_sets_cookie_and_redirects(cfg, srv):
    key = webaccess.issue_key(cfg, 10, 2)
    code, h, body = req(srv, "/enter?key=" + key, cookie=None)
    assert code == 303 and h["location"] == "/" and body == ""
    port = srv.server_address[1]
    m = re.fullmatch(r"rb_web_%d=([A-Za-z0-9_-]{20,128}); HttpOnly; SameSite=Strict; Path=/; "
                     r"Max-Age=7200" % port, h["set-cookie"])
    assert m, h["set-cookie"]
    assert "secure" not in h["set-cookie"].lower()
    assert h["cache-control"] == "no-store" and h["x-content-type-options"] == "nosniff"
    assert h["referrer-policy"] == "no-referrer"
    assert req(srv, "/", cookie="rb_web_%d=%s" % (port, m.group(1)), host=None)[0] == 403
    assert req(srv, "/", cookie="rb_web_%d=%s" % (port, m.group(1)))[0] == 200
    # single use
    code, _h, body = req(srv, "/enter?key=" + key, cookie=None)
    assert (code, body) == (401, NEED)


def test_enter_failures_and_head(cfg, srv):
    key = webaccess.issue_key(cfg, 10, 12)
    for target in ("/enter", "/enter?", "/enter?key=", "/enter?key=short", "/enter?other=" + key,
                   "/enter?key=%s&key=%s" % (key, key), "/enter?key=" + key + "!",
                   "/enter?key=" + "A" * 43):
        code, _h, body = req(srv, target, cookie=None)
        assert (code, body) == (401, NEED), target
    # HEAD never redeems; the key still works afterwards
    assert req(srv, "/enter?key=" + key, method="HEAD", cookie=None)[0] == 401
    assert req(srv, "/enter?key=" + key, cookie=None)[0] == 303
    assert req(srv, "/enter?key=x", host="evil.example", cookie=None)[0] == 403


def test_expired_session_is_refused(cfg, srv, monkeypatch):
    assert req(srv, "/")[0] == 200
    real = time.time
    monkeypatch.setattr(webaccess, "_now", lambda: real() + 13 * 3600)
    assert req(srv, "/")[0] == 401


def test_log_never_has_key_token_or_cookie(cfg, srv, capfd):
    key = webaccess.issue_key(cfg, 10, 12)
    capfd.readouterr()
    code, h, _b = req(srv, "/enter?key=" + key, cookie=None)
    token = re.search(r"=([^;]+);", h["set-cookie"]).group(1)
    assert code == 303 and req(srv, "/", cookie="%s=%s" % (web.cookie_name(
        srv.server_address[1]), token))[0] == 200
    assert req(srv, "/enter?key=" + key, cookie=None)[0] == 401
    err = capfd.readouterr().err
    assert "GET enter 303" in err and "GET index 200" in err
    for secret in (key, token, srv.token):
        assert secret not in err


def test_require_key_false_is_not_reachable_from_cli():
    src = (REPO / "rb_host" / "cli.py").read_text(encoding="utf-8")
    assert "require_key" not in src
    assert "require_key" not in (REPO / "rb_host" / "web.py").read_text(
        encoding="utf-8").split("def cli_main")[1]


def test_require_key_false_serves_without_session(cfg):
    s = web.make_server(cfg, "127.0.0.1", 0, require_key=False)
    t = threading.Thread(target=s.serve_forever, daemon=True)
    t.start()
    try:
        assert req(s, "/")[0] == 200
    finally:
        s.shutdown()
        s.server_close()
        t.join(5)


# -- rb web key ------------------------------------------------------------------------------
@pytest.fixture
def hostjson(cfg, tmp_path, monkeypatch):
    host = tmp_path / "ok-host.json"
    host.write_text(json.dumps({"nodes": {"n1": {"alias": "x"}}, "data_root": cfg.data_root}),
                    encoding="utf-8")
    monkeypatch.setenv("RB_HOST_CONFIG", str(host))
    return host


def test_cli_web_key_output(cfg, hostjson, capsys):
    assert cli.main(["web", "key"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 3
    m = re.fullmatch(r"http://127\.0\.0\.1:8767/enter\?key=([A-Za-z0-9_-]{43})", lines[0])
    assert m
    assert "works once" in lines[1] and "10 minutes" in lines[1]
    assert "12 hours" in lines[2]
    assert webaccess.counts(cfg) == (1, 0)
    assert webaccess.redeem(cfg, m.group(1)) is not None
    assert cli.main(["web", "key", "--port", "9000", "--minutes", "60",
                     "--session-hours", "168"]) == 0
    out = capsys.readouterr().out
    assert ":9000/enter?key=" in out and "60 minutes" in out and "168 hours" in out


@pytest.mark.parametrize("flags", [["--minutes", "0"], ["--minutes", "61"],
                                   ["--session-hours", "0"], ["--session-hours", "169"],
                                   ["--port", "0"], ["--port", "70000"]])
def test_cli_web_key_range_errors(cfg, hostjson, capsys, flags):
    assert cli.main(["web", "key"] + flags) == 1
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1 and lines[0].startswith("error:")
    assert webaccess.counts(cfg) == (0, 0)


def test_cli_web_key_revoke_and_status(cfg, hostjson, capsys):
    webaccess.issue_key(cfg, 10, 12)
    webaccess.issue_key(cfg, 10, 12)
    webaccess.redeem(cfg, webaccess.issue_key(cfg, 10, 12))
    assert cli.main(["web", "key", "--status"]) == 0
    assert capsys.readouterr().out.strip() == "2 pending key(s), 1 live session(s)"
    assert cli.main(["web", "key", "--revoke"]) == 0
    assert capsys.readouterr().out.strip() == "revoked 2 pending key(s) and 1 session(s)"
    assert webaccess.counts(cfg) == (0, 0)


def test_cli_web_key_without_host_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("RB_HOST_CONFIG", str(tmp_path / "missing" / "host.json"))
    monkeypatch.setenv("RB_HOST_ROOT", str(tmp_path / "emptyroot"))
    for argv in (["web", "key"], ["web", "key", "--status"], ["web", "key", "--revoke"]):
        assert cli.main(argv) == 1
        lines = capsys.readouterr().out.strip().splitlines()
        assert len(lines) == 1 and lines[0].startswith("error: no usable host.json")


def test_mcp_tools_unchanged_by_web_key():
    src = (REPO / "rb_host" / "server.py").read_text(encoding="utf-8")
    assert "webaccess" not in src


# -- audit fixes -----------------------------------------------------------------------------
def _tree(cfg):
    root = Path(cfg.data_root)
    return sorted((str(p.relative_to(root)), p.stat().st_ino, p.stat().st_mtime_ns,
                   p.read_bytes() if p.is_file() else b"") for p in root.rglob("*"))


def test_failed_enter_changes_nothing(cfg, srv):
    before = _tree(cfg)
    for target in ("/enter?key=" + "A" * 43, "/enter?key=short", "/enter"):
        assert req(srv, target, cookie=None)[0] == 401
    assert _tree(cfg) == before


def test_failed_enter_creates_no_web_directory(cfg):
    s = web.make_server(cfg, "127.0.0.1", 0)
    t = threading.Thread(target=s.serve_forever, daemon=True)
    t.start()
    try:
        before = _tree(cfg)
        assert req(s, "/enter?key=" + "A" * 43, cookie=None)[0] == 401
        assert _tree(cfg) == before and not (Path(cfg.data_root) / "web").exists()
    finally:
        s.shutdown()
        s.server_close()
        t.join(5)


def test_cookie_header_parsing(srv):
    port = srv.server_address[1]
    name, good = web.cookie_name(port), srv.token
    ok = [
        'a={"j":1}; %s=%s' % (name, good), 'a=x y; %s=%s' % (name, good),
        'a="unbalanced; %s=%s' % (name, good), '%s=junk; %s=%s' % (name, name, good),
        '%s=%s; %s=junk' % (name, good, name), '%s = %s' % (name, good),
    ]
    for c in ok:
        assert req(srv, "/", cookie=c)[0] == 200, c
    # two Cookie header lines
    assert req(srv, "/", cookie="a=1", extra="Cookie: %s=%s\r\n" % (name, good))[0] == 200
    assert req(srv, "/", cookie="%s=junk" % name,
               extra="Cookie: %s=%s\r\n" % (name, good))[0] == 200
    # at most eight candidates are tried
    many = "; ".join(["%s=junk" % name] * 8 + ["%s=%s" % (name, good)])
    assert req(srv, "/", cookie=many)[0] == 401
    assert req(srv, "/", cookie="%s=junk; x=%s" % (name, good))[0] == 401


@pytest.mark.parametrize("hdr", ["Sec-Purpose: prefetch", "Purpose: preview",
                                 "Sec-Purpose: prefetch;anonymous-client-ip",
                                 "Sec-Purpose: PREFETCH"])
def test_prefetch_does_not_redeem(cfg, srv, hdr):
    key = webaccess.issue_key(cfg, 10, 12)
    assert req(srv, "/enter?key=" + key, cookie=None, extra=hdr + "\r\n")[0] == 401
    assert req(srv, "/enter?key=" + key, cookie=None)[0] == 303


TCP_TEXT = """  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 0100007F:1F4F 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000        0 11 1 0 100 0
   1: 0100007F:C350 0100007F:1F4F 01 00000000:00000000 00:00000000 00000000  1000        0 22 1 0 100 0
   2: 0100007F:1F4F 0100007F:C350 01 00000000:00000000 00:00000000 00000000  1000        0 23 1 0 100 0
   3: 0100007F:C351 0100007F:1F4F 01 00000000:00000000 00:00000000 00000000  1001        0 24 1 0 100 0
   4: garbage
   5: 0100007F:C352 0100007F:1F4F 01 00000000:00000000 00:00000000 00000000  notanumber        0 25
"""


def test_socket_owner_lookup():
    srv_addr = ("127.0.0.1", 8015)
    assert web.socket_owner(TCP_TEXT, ("127.0.0.1", 50000), srv_addr) == 1000
    assert web.socket_owner(TCP_TEXT, ("127.0.0.1", 50001), srv_addr) == 1001
    assert web.socket_owner(TCP_TEXT, ("127.0.0.1", 50002), srv_addr) is None  # unparsable uid
    assert web.socket_owner(TCP_TEXT, ("127.0.0.1", 50003), srv_addr) is None  # no row
    assert web.socket_owner(TCP_TEXT, ("127.0.0.1", 50000), ("127.0.0.1", 8016)) is None
    assert web.socket_owner(TCP_TEXT.splitlines()[0] + "\n", ("127.0.0.1", 50000), srv_addr) is None
    assert web.socket_owner("", ("127.0.0.1", 50000), srv_addr) is None
    assert web.socket_owner("junk\nmore junk\n", ("127.0.0.1", 50000), srv_addr) is None
    assert web.socket_owner(TCP_TEXT, ("::1", 50000), srv_addr) is None
    assert web.socket_owner(TCP_TEXT, None, srv_addr) is None


def test_real_lookup_accepts_own_connection(srv):
    assert srv.peer_check is True
    assert req(srv, "/healthz", cookie=None)[0] == 200


def test_connection_of_another_account_is_dropped(srv, monkeypatch, capfd):
    calls = []
    monkeypatch.setattr(web._Handler, "_serve", lambda self, head: calls.append(1))
    monkeypatch.setattr(web, "socket_owner", lambda *a: os.getuid() + 1)
    capfd.readouterr()
    port = srv.server_address[1]
    with socket.create_connection(("127.0.0.1", port), timeout=5) as c:
        c.sendall(("GET /healthz HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nConnection: close\r\n\r\n"
                   % port).encode())
        data = b""
        try:
            while True:
                chunk = c.recv(4096)
                if not chunk:
                    break
                data += chunk
        except ConnectionResetError:
            pass
    assert data == b"" and calls == []
    err = capfd.readouterr().err
    assert err.splitlines() == [
        "refused: 1 connection(s) not owned by this account or over the limit"]


@pytest.mark.parametrize("bad", [lambda *a: None, lambda *a: 1 / 0])
def test_lookup_failure_refuses(srv, monkeypatch, bad):
    monkeypatch.setattr(web, "socket_owner", bad)
    port = srv.server_address[1]
    with socket.create_connection(("127.0.0.1", port), timeout=5) as c:
        c.sendall(b"GET /healthz HTTP/1.1\r\nHost: x\r\n\r\n")
        try:
            assert c.recv(4096) == b""
        except ConnectionResetError:
            pass


def test_unreadable_proc_tcp_refuses_everything(srv, monkeypatch):
    monkeypatch.setattr(web, "PROC_TCP", "/nonexistent/tcp")
    port = srv.server_address[1]
    with socket.create_connection(("127.0.0.1", port), timeout=5) as c:
        c.sendall(b"GET /healthz HTTP/1.1\r\nHost: x\r\n\r\n")
        try:
            assert c.recv(4096) == b""
        except ConnectionResetError:
            pass


def test_serve_needs_proc_net_tcp(cfg, hostjson, monkeypatch, capsys):
    monkeypatch.setattr(web, "PROC_TCP", "/nonexistent/tcp")

    def boom(*a, **k):
        raise AssertionError("a server was started")
    monkeypatch.setattr(web, "serve", boom)
    assert cli.main(["web", "serve"]) == 1
    assert capsys.readouterr().out.strip().splitlines() == [
        "error: the hub page needs /proc/net/tcp to check who connects (Linux only)"]


def test_cli_web_key_missing_data_root_and_corrupt_file(cfg, tmp_path, monkeypatch, capsys):
    host = tmp_path / "gone-host.json"
    host.write_text(json.dumps({"nodes": {"n1": {"alias": "x"}},
                                "data_root": str(tmp_path / "nothere")}), encoding="utf-8")
    monkeypatch.setenv("RB_HOST_CONFIG", str(host))
    assert cli.main(["web", "key"]) == 1
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1 and "does not exist" in lines[0]
    assert cli.main(["web", "key", "--revoke"]) == 1
    assert not (tmp_path / "nothere").exists()
    # a corrupt existing file: the key command aborts, --revoke repairs
    host.write_text(json.dumps({"nodes": {"n1": {"alias": "x"}}, "data_root": cfg.data_root}),
                    encoding="utf-8")
    acc = Path(cfg.data_root) / "web" / "access.json"
    acc.parent.mkdir()
    acc.write_text("{broken", encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["web", "key"]) == 1
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1 and "rb web key --revoke" in lines[0]
    assert acc.read_text(encoding="utf-8") == "{broken"
    assert cli.main(["web", "key", "--revoke"]) == 0
    assert cli.main(["web", "key"]) == 0


def test_without_fcntl_other_commands_still_work(tmp_path):
    code = (
        "import sys\nsys.modules['fcntl'] = None\n"
        "from rb_host import cli, web, webaccess\n"
        "from rb_host.config import HostConfig\n"
        "cfg = HostConfig(nodes={}, data_root=sys.argv[1])\n"
        "assert webaccess.redeem(cfg, 'A' * 43) is None\n"
        "try:\n    webaccess.issue_key(cfg, 10, 12)\nexcept OSError as e:\n    print('issue-failed')\n"
        "print(cli.main(['config', 'path']))\n")
    (tmp_path / "d").mkdir()
    env = dict(os.environ, RB_HOST_CONFIG=str(tmp_path / "h.json"),
               RB_HOST_ROOT=str(tmp_path / "root"))
    out = subprocess.run([sys.executable, "-c", code, str(tmp_path / "d")], cwd=str(REPO),
                         capture_output=True, text=True, timeout=60, env=env)
    assert out.returncode == 0, out.stderr
    assert "issue-failed" in out.stdout and out.stdout.strip().endswith("0")


# -- accept loop, limits, prefetch body, strict status ------------------------------------------
def _connect(srv, send=True):
    port = srv.server_address[1]
    c = socket.create_connection(("127.0.0.1", port), timeout=10)
    if send:
        c.sendall(("GET /healthz HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nConnection: close\r\n\r\n"
                   % port).encode())
    return c


def _drain(c):
    data = b""
    try:
        while True:
            chunk = c.recv(4096)
            if not chunk:
                break
            data += chunk
    except ConnectionResetError:
        pass
    return data


def test_queue_and_limit_constants():
    assert web.MAX_CONNECTIONS == 32 and web.QUEUE_SIZE == 128
    assert web._Server.request_queue_size == 128


def test_refused_client_gets_no_bytes_and_no_handler(srv, monkeypatch):
    calls = []
    monkeypatch.setattr(web._Handler, "_serve", lambda self, head: calls.append(1))
    monkeypatch.setattr(web, "socket_owner", lambda *a: os.getuid() + 1)
    c = _connect(srv)  # the request is sent; it must not be read or answered
    assert _drain(c) == b"" and calls == []
    c.close()


def test_slow_check_does_not_stall_the_accept_loop(srv, monkeypatch):
    gate = threading.Event()
    foreign = socket.socket()
    foreign.bind(("127.0.0.1", 0))
    fport = foreign.getsockname()[1]
    seen = threading.Event()
    me = os.getuid()

    def lookup(text, client, server):
        if client[1] == fport:
            seen.set()
            gate.wait(20)
        return me
    monkeypatch.setattr(web, "socket_owner", lookup)
    try:
        foreign.connect(("127.0.0.1", srv.server_address[1]))
        assert seen.wait(10)  # the slow check is running in its own thread
        assert req(srv, "/healthz", cookie=None)[0] == 200  # and an owned connection is served
    finally:
        gate.set()
        foreign.close()


def test_connection_cap_closes_without_lookup(srv, monkeypatch):
    gate = threading.Event()
    calls = []
    me = os.getuid()

    def lookup(*a):
        calls.append(1)
        gate.wait(30)
        return me
    monkeypatch.setattr(web, "socket_owner", lookup)
    held = []
    try:
        for _ in range(web.MAX_CONNECTIONS):
            held.append(_connect(srv, send=False))
        deadline = time.time() + 10
        while len(calls) < web.MAX_CONNECTIONS and time.time() < deadline:
            time.sleep(0.01)
        assert len(calls) == web.MAX_CONNECTIONS
        extra = _connect(srv)
        assert _drain(extra) == b"" and len(calls) == web.MAX_CONNECTIONS
        extra.close()
    finally:
        gate.set()
        for c in held:
            c.close()
    deadline = time.time() + 10
    while time.time() < deadline:  # slots are released again
        try:
            if req(srv, "/healthz", cookie=None)[0] == 200:
                break
        except OSError:
            pass
    assert req(srv, "/healthz", cookie=None)[0] == 200


def test_refusal_log_is_rate_limited(srv, monkeypatch, capfd):
    now = [1000.0]
    monkeypatch.setattr(web, "_clock", lambda: now[0])
    monkeypatch.setattr(web, "socket_owner", lambda *a: os.getuid() + 1)
    capfd.readouterr()
    for _ in range(5):
        c = _connect(srv)
        _drain(c)
        c.close()
    now[0] += 11
    c = _connect(srv)
    _drain(c)
    c.close()
    lines = capfd.readouterr().err.splitlines()
    tail = " connection(s) not owned by this account or over the limit"
    assert lines == ["refused: 1" + tail, "refused: 5" + tail]


def test_prefetch_401_has_a_complete_body(cfg, srv):
    key = webaccess.issue_key(cfg, 10, 12)
    port = srv.server_address[1]
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(("GET /enter?key=%s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nSec-Purpose: prefetch\r\n"
                   "Connection: close\r\n\r\n" % (key, port)).encode())
        data = _drain(s)
    head, _, body = data.partition(b"\r\n\r\n")
    length = int(re.search(rb"Content-Length: (\d+)", head, re.I).group(1))
    assert len(body) == length and body.decode() == NEED
    code, _h, hbody = req(srv, "/enter?key=" + key, method="HEAD", cookie=None,
                          extra="Sec-Purpose: prefetch\r\n")
    assert code == 401 and hbody == ""


def test_status_reports_corrupt_file_like_issuing(cfg, hostjson, capsys):
    acc = Path(cfg.data_root) / "web" / "access.json"
    acc.parent.mkdir()
    for content in ("{broken", "[]", '{"keys": 5}', '{"keys": [{"sha256": "x"}]}',
                    '{"sessions": {}}'):
        acc.write_text(content, encoding="utf-8")
        assert cli.main(["web", "key", "--status"]) == 1
        status_line = capsys.readouterr().out.strip().splitlines()
        assert len(status_line) == 1 and "rb web key --revoke" in status_line[0], content
        assert cli.main(["web", "key"]) == 1  # issuing aborts the same way
        issue_line = capsys.readouterr().out.strip().splitlines()
        assert issue_line == status_line, content
        assert acc.read_text(encoding="utf-8") == content  # nothing rewritten
        assert webaccess.counts(cfg) == (0, 0)  # the page's reader stays tolerant
    acc.unlink()
    assert cli.main(["web", "key", "--status"]) == 0
    assert capsys.readouterr().out.strip() == "0 pending key(s), 0 live session(s)"


def test_slot_is_returned_when_the_connection_thread_cannot_start(cfg, monkeypatch):
    import socketserver
    srv = web.make_server(cfg, port=0)
    try:
        def boom(self, request, client_address):
            raise RuntimeError("can't start new thread")
        monkeypatch.setattr(socketserver.ThreadingMixIn, "process_request", boom)
        a, b = socket.socketpair()
        try:
            for _ in range(web.MAX_CONNECTIONS + 3):  # more often than there are slots
                assert srv.verify_request(a, ("127.0.0.1", 1)) is True
                with pytest.raises(RuntimeError):
                    srv.process_request(a, ("127.0.0.1", 1))
        finally:
            a.close()
            b.close()
    finally:
        srv.server_close()
