"""scripts/demo_dashboard.py: the demo serves the 8765 pages and the new hub page from one
throwaway local node (no SSH, no real host.json)."""
from __future__ import annotations

import http.client
import importlib.util
import os
import threading
import urllib.parse
from pathlib import Path

import pytest

from rb_host import jobs, threads

REPO = Path(__file__).resolve().parents[1]


def _load_demo():
    spec = importlib.util.spec_from_file_location("demo_dashboard", REPO / "scripts" / "demo_dashboard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _get(port, path, host, cookie=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    try:
        c.request("GET", path, headers=dict({"Host": host}, **({"Cookie": cookie} if cookie else {})))
        r = c.getresponse()
        return r.status, r.read().decode("utf-8")
    finally:
        c.close()


def _enter(address):
    """Open the printed address as a browser does: take the cookie from the 303 reply."""
    u = urllib.parse.urlsplit(address)
    c = http.client.HTTPConnection(u.hostname, u.port, timeout=20)
    try:
        c.request("GET", u.path + "?" + u.query, headers={"Host": "%s:%d" % (u.hostname, u.port)})
        r = c.getresponse()
        r.read()
        assert r.status == 303 and r.getheader("Location") == "/"
        return r.getheader("Set-Cookie").split(";", 1)[0]
    finally:
        c.close()


def test_host_and_origin_mapping():
    demo = _load_demo()
    assert demo.map_host("127.0.0.1:5555", 5555) == "127.0.0.1:8765"
    assert demo.map_host("LOCALHOST:5555", 5555) == "127.0.0.1:8765"
    assert demo.map_host("evil.example", 5555) == "evil.example"
    assert demo.map_host("127.0.0.1:5556", 5555) == "127.0.0.1:5556"
    assert demo.map_host(None, 5555) is None
    assert demo.map_origin("http://127.0.0.1:5555", 5555) == "http://127.0.0.1:8765"
    assert demo.map_origin("http://localhost:5555", 5555) == "http://127.0.0.1:8765"
    assert demo.map_origin(None, 5555) is None
    assert demo.map_origin("http://evil.example", 5555) == "http://evil.example"


def test_demo_pages_200_and_seeded_thread(tmp_path, monkeypatch):
    monkeypatch.setenv("RB_HOST_CONFIG", str(tmp_path / "missing-host.json"))
    monkeypatch.setenv("RB_HOST_ROOT", str(tmp_path / "root"))
    monkeypatch.setattr(jobs, "connect", jobs.connect)
    monkeypatch.chdir(os.getcwd())
    demo = _load_demo()
    srv, web_srv = demo.start(tmp_path / "demo", 0, 0)
    for s in (srv, web_srv):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        port, wport = srv.server_address[1], web_srv.server_address[1]
        host, whost = "127.0.0.1:%d" % port, "127.0.0.1:%d" % wport
        for path in ("/board", "/rb/pending"):
            code, body = _get(port, path, host)
            assert code == 200, (path, body[:200])
        assert "sweep-lr.yaml" in _get(port, "/rb/pending", host)[1]
        assert _get(port, "/board", "evil.example")[0] == 403

        cfg = jobs.load_cfg()
        full = [t for t in threads.load(cfg)["threads"]
                if sum(1 for r in t["records"] if r.get("msg_kind") != "event") == 3]
        assert len(full) == 1
        recs = [r for r in full[0]["records"] if r.get("msg_kind") != "event"]
        m1 = next(r["id"] for r in recs if r["direction"] == "out" and not r.get("reply_to"))
        assert _get(wport, "/threads", whost)[0] == 401  # the page needs the key
        address = demo.hub_page_address(web_srv)
        cookie = _enter(address)
        code, listing = _get(wport, "/threads", whost, cookie)
        assert code == 200 and ('/thread/%s"' % full[0]["id"]) in listing
        code, page = _get(wport, "/thread/%s" % m1, whost, cookie)
        assert code == 200
        for r in recs:
            assert r["id"] in page
        assert _get(wport, "/", whost, cookie)[0] == 200
    finally:
        srv.shutdown()
        web_srv.shutdown()
        srv.server_close()
        web_srv.server_close()


def test_script_prints_flushed_lines_and_removes_its_temp_dir_on_sigterm(tmp_path):
    import signal
    import subprocess
    import sys
    env = dict(os.environ, RB_HOST_CONFIG=str(tmp_path / "none.json"),
               RB_HOST_ROOT=str(tmp_path / "root"), TMPDIR=str(tmp_path))
    p = subprocess.Popen([sys.executable, str(REPO / "scripts" / "demo_dashboard.py"),
                          "--port", "0", "--web-port", "0"], stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, env=env, universal_newlines=True)
    try:
        lines = [p.stdout.readline() for _ in range(3)]  # blocks until flushed
        assert lines[0].startswith("demo data: ") and "hub page" in lines[2]
        address = lines[2].split("hub page: ", 1)[1].split(" ", 1)[0]
        assert "/enter?key=" in address
        cookie = _enter(address)
        u = urllib.parse.urlsplit(address)
        code, body = _get(u.port, "/threads", "127.0.0.1:%d" % u.port, cookie)
        assert code == 200
        demo_dir = Path(lines[0].split(": ", 1)[1].strip())
        assert demo_dir.is_dir()
        p.send_signal(signal.SIGTERM)
        assert p.wait(timeout=30) == 0
        assert not demo_dir.exists()
    finally:
        if p.poll() is None:
            p.kill()
        p.stdout.close()


def test_hub_page_not_served_without_proc_net_tcp(tmp_path, monkeypatch):
    from rb_host import web
    monkeypatch.setenv("RB_HOST_CONFIG", str(tmp_path / "missing-host.json"))
    monkeypatch.setenv("RB_HOST_ROOT", str(tmp_path / "root"))
    monkeypatch.chdir(os.getcwd())
    demo = _load_demo()
    srv, web_srv = demo.start(tmp_path / "demo", 0, 0)
    try:
        ok, line = demo.hub_page_line(web_srv)
        assert ok and "/enter?key=" in line
        monkeypatch.setattr(web, "proc_tcp_readable", lambda: False)
        ok, line = demo.hub_page_line(web_srv)
        assert not ok and line.startswith("hub page: not available")
        assert "the hub page needs /proc/net/tcp to check who connects (Linux only)" in line
    finally:
        srv.server_close()
        web_srv.server_close()
