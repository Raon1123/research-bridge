"""scripts/demo_dashboard.py: the demo serves the 8765 pages and the new hub page from one
throwaway local node (no SSH, no real host.json)."""
from __future__ import annotations

import http.client
import importlib.util
import os
import threading
from pathlib import Path

import pytest

from rb_host import jobs, threads

REPO = Path(__file__).resolve().parents[1]


def _load_demo():
    spec = importlib.util.spec_from_file_location("demo_dashboard", REPO / "scripts" / "demo_dashboard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _get(port, path, host):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    try:
        c.request("GET", path, headers={"Host": host})
        r = c.getresponse()
        return r.status, r.read().decode("utf-8")
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
        code, listing = _get(wport, "/threads", whost)
        assert code == 200 and ('/thread/%s"' % full[0]["id"]) in listing
        code, page = _get(wport, "/thread/%s" % m1, whost)
        assert code == 200
        for r in recs:
            assert r["id"] in page
        assert _get(wport, "/", whost)[0] == 200
    finally:
        srv.shutdown()
        web_srv.shutdown()
        srv.server_close()
        web_srv.server_close()
