"""Shared status page (design docs/design/2026-11-06-shared-status-page.md §10).

Fixtures are copies under tmp_path with placeholder labels only. The session-calendar and
run-view shapes are ASSUMED (see the implementation plan, Global Constraints A).
"""
from __future__ import annotations

import datetime
import hashlib
import http.client
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from rb_host import cli, config, share, share_serve
from rb_host.ledger import Ledger

REPO = Path(__file__).resolve().parents[1]
TODAY = datetime.datetime.now(datetime.timezone.utc).date()

TITLE = "TITLE-free-text-zq"
EXTRA = "extra_field_zq"
METRIC = "metric_value_zq"
T_ARG = "03:17:41Z"  # unusual time of day: must never reach the audit file


def _iso(day: datetime.date, hms: str) -> str:
    return "%sT%s" % (day.isoformat(), hms)


def _days_ago(n: int) -> datetime.date:
    return TODAY - datetime.timedelta(days=n)


def _write(p: Path, obj) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def _board_file(root: Path, source: str, items, *, ok=True, error=None, fetched=None, cadence=3600):
    now = datetime.datetime.now(datetime.timezone.utc)
    fetched = fetched or now.strftime("%Y-%m-%dT%H:%M:%SZ")
    _write(root / "board" / ("n1_%s.json" % source),
           {"source": "n1:%s" % source, "fetched_at": fetched, "ok": ok, "error": error,
            "cadence_s": cadence, "items": items})


def _sessions():
    d1, d2 = _days_ago(1), _days_ago(2)
    return {"sessions": [
        {"start": _iso(d1, T_ARG), "end": _iso(d1, "04:47:41Z"), "machine": "laptop",
         "project": "ARG", "kind": "session", "title": TITLE, EXTRA: 1},
        {"start": _iso(d2, "10:00:00Z"), "end": _iso(d2, "10:30:00Z"), "lane": "gpu-box",
         "project": "ZZZ", "kind": "session", "title": TITLE},
        {"start": _iso(d2, "11:00:00Z"), "end": _iso(d2, "11:05:00Z"), "machine": "laptop",
         "project": "ARG", "kind": "routine", "title": TITLE},
        {"start": _iso(d1, "11:00:00Z"), "end": _iso(d1, "12:00:00Z"), "machine": "laptop",
         "project": "pp_ltf_x", "kind": "session", "title": TITLE},
        {"start": _iso(d1, "13:00:00Z"), "machine": "laptop", "project": "ARG"},  # no end
        {"machine": "laptop", "project": "ARG"},  # no start: skipped, never raises
    ]}


def _runs():
    d1 = _days_ago(1)
    return {"runs": [
        {"run_id": "r1", "project": "ARG", "started": _iso(d1, "01:00:00Z"),
         "ended": _iso(d1, "02:00:00Z"), "status": "done", "metrics": {"m": METRIC}, EXTRA: "x"},
        {"run_id": "r2", "project": "ARG", "started": _iso(d1, "03:00:00Z"),
         "ended": _iso(d1, "03:10:00Z"), "status": "failed", "metrics": {"m": METRIC}},
        {"run_id": "r3", "project": "ZZZ", "started": _iso(d1, "04:00:00Z"), "ended": None,
         "status": "running", "metrics": {}},
    ]}


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "data"
    cal = tmp_path / "cal"
    sess = _write(cal / "sessions.json", _sessions())
    stat = _write(cal / "status.json", {"generated": "2026-11-06T00:00:00Z", "cost_usd": 12.5})
    runs = _write(tmp_path / "runs" / "runs.json", _runs())
    wp = _write(tmp_path / "withheld.json", {"patterns": []})
    port = _write(tmp_path / "board-fixture" / "portfolio.json", {
        "columns": ["ready"], "papers": [{"paper_id": "p0", "short": "P0", "column": "ready",
                                          "tasks": []}]})
    live = _write(tmp_path / "board-fixture" / "live.json", {
        "meta": {"refreshed": "2026-11-03 11:02"}, "items": [],
        "ranking": {"tiers": []}})
    # n1:queue is stale (old fetched_at, short cadence); n1:gpu fresh; n1:events fresh
    _board_file(root, "queue", [{"state": "queued", "count": 2}, {"state": "running", "count": 1},
                                {"state": "done", "count": 5}, {"state": "failed", "count": 1}],
                fetched="2020-01-01T00:00:00Z", cadence=60)
    _board_file(root, "gpu", [
        {"index": 0, "name": "gpu-a", "memory_used": 10, "memory_total": 80, "utilization": 50},
        {"index": 1, "name": "gpu-a", "memory_used": 0, "memory_total": 80, "utilization": 0}])
    _board_file(root, "events", [
        {"ts": _iso(_days_ago(0), "00:00:00Z"), "stage": "S5", "kind": "monitor", "track": "ARG",
         "id": "e1"},
        {"ts": _iso(_days_ago(1), "00:00:00Z"), "stage": "S6", "kind": "monitor",
         "track": "pp_ltf_y", "id": "e2"},
        {"ts": _iso(_days_ago(2), "00:00:00Z"), "stage": "S3", "kind": "monitor", "track": "ZZZ",
         "id": "e3"}])
    Ledger(root / "ledger.jsonl").append(
        {"kind": "job", "op": "submit", "id": "j1", "node": "n1", "config_name": "secretcfg.yaml",
         "gpus": [0], "gpu_hours": 3, "status": "pending_approval",
         "created": _iso(_days_ago(1), "05:00:00Z")})
    host = tmp_path / "host.json"
    host.write_text(json.dumps({
        "nodes": {"n1": {"alias": "x"}}, "data_root": str(root),
        "withheld_patterns_file": str(wp),
        "share": {"calendar_sessions": str(sess), "calendar_status": str(stat),
                  "runs": str(runs), "labels": ["ARG"]},
        "board": {"portfolio": str(port), "priorities": str(live)}}), encoding="utf-8")
    monkeypatch.setenv("RB_HOST_CONFIG", str(host))
    inputs = [sess, stat, runs, wp, port, live, root / "ledger.jsonl"] + sorted((root / "board").glob("*.json"))
    return {"tmp": tmp_path, "root": root, "host": host, "inputs": inputs,
            "cfg": config.load_host_config(host), "sessions": sess}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _build(env, **kw):
    kw.setdefault("today", TODAY)
    return share.build(env["cfg"], **kw)


def _snap(env, **kw) -> dict:
    return _build(env, **kw)["snapshot"]


def _src(snap: dict) -> dict:
    return {s["id"]: s for s in snap["sources"]}


def _all_strings(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield str(k)
            yield from _all_strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from _all_strings(v)
    elif o is not None:
        yield str(o)


def test_all_sections_present(env):
    snap = _snap(env)
    assert snap["schema_version"] == share.SCHEMA_VERSION == 1
    assert snap["tier"] == "shared"
    for k in ("built_at", "period", "sources", "sessions", "experiments", "dropped"):
        assert k in snap
    assert set(snap["period"]) == {"from", "to"}
    assert snap["period"]["to"] == TODAY.isoformat()
    assert set(snap["sessions"]) == {"per_day", "totals"}
    assert {"sessions", "routines", "active_h"} <= set(snap["sessions"]["totals"])
    exp = snap["experiments"]
    assert set(exp) == {"queue", "gpu", "runs_per_day", "tracks"}
    assert set(exp["queue"]) == {"queued", "running", "done", "failed", "pending_approvals"}
    assert {"in_use", "total", "gpu_hours_period"} <= set(exp["gpu"])
    assert set(_src(snap)) == {"calendar:sessions", "calendar:status", "runs", "n1:queue",
                               "n1:gpu", "n1:events", "rb:ledger",
                               "withheld:patterns"}
    # sessions: ARG laptop 1.5 h + a record without end (0 h); ZZZ -> 'gpu-box' maps to server
    day = _days_ago(1).isoformat()
    row = [r for r in snap["sessions"]["per_day"]
           if r["date"] == day and r["lane"] == "laptop" and r["project"] == "ARG"]
    assert len(row) == 1 and row[0]["count"] == 2 and row[0]["active_h"] == 1.5
    assert any(r["lane"] == "server" and r["project"] == "other"
               for r in snap["sessions"]["per_day"])
    assert snap["sessions"]["totals"]["routines"] == 1
    runs = {(r["date"], r["project"]): r for r in snap["experiments"]["runs_per_day"]}
    assert runs[(day, "ARG")]["started"] == 2
    assert runs[(day, "ARG")]["finished"] == 1 and runs[(day, "ARG")]["failed"] == 1
    assert snap["experiments"]["gpu"]["in_use"] == 1 and snap["experiments"]["gpu"]["total"] == 2
    tracks = snap["experiments"]["tracks"]
    assert tracks
    for t in tracks:
        assert set(t) == {"track", "stage", "last_event_age_s"}
    arg = [t for t in tracks if t["track"] == "ARG"]
    assert len(arg) == 1 and arg[0]["stage"] == "S5" and arg[0]["last_event_age_s"] >= 0


def test_unknown_source_field_not_copied(env):
    res = _build(env)
    blob = json.dumps(res["snapshot"])
    html = share_serve.render_html(res["snapshot"])
    on_disk = "".join(Path(p).read_text(encoding="utf-8") for p in res["paths"])
    for needle in (TITLE, EXTRA, METRIC, "metrics", "secretcfg", "gpu-a", "gpu-box"):
        assert needle not in blob, needle
        assert needle not in on_disk, needle
    for needle in (TITLE, EXTRA, METRIC, "secretcfg", "gpu-a", "gpu-box"):
        assert needle not in html, needle


def _get(srv, method, path):
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
    try:
        c.request(method, path)
        r = c.getresponse()
        return r.status, dict((k.lower(), v) for k, v in r.getheaders()), r.read()
    finally:
        c.close()


class _Running:
    def __init__(self, root: Path) -> None:
        self.srv = share_serve.make_server(root, "127.0.0.1", 0)
        self.t = threading.Thread(target=self.srv.serve_forever, args=(0.01,), daemon=True)

    def __enter__(self):
        self.t.start()
        return self.srv

    def __exit__(self, *a):
        self.srv.shutdown()
        self.srv.server_close()
        self.t.join(5)


def test_serve_only_two_files(env):
    res = _build(env)
    root = share.share_dir(env["cfg"])
    outside = env["tmp"] / "outside.txt"
    outside.write_text("outside-secret", encoding="utf-8")
    os.symlink(str(outside), str(root / "link.txt"))
    html = (root / "index.html").read_bytes()
    snap = (root / "snapshot.json").read_bytes()
    with _Running(root) as srv:
        for path, body in (("/", html), ("/index.html", html), ("/snapshot.json", snap)):
            st, hd, got = _get(srv, "GET", path)
            assert st == 200 and got == body, path
            assert hd["cache-control"] == "no-store"
            assert hd["x-content-type-options"] == "nosniff"
            assert "default-src 'none'" in hd["content-security-policy"]
        st, _, got = _get(srv, "HEAD", "/snapshot.json")
        assert st == 200 and got == b""
        for path in ("/../snapshot.json", "/md?x=1", "/%2e%2e/snapshot.json",
                     "/snapshot.json?x", "/snapshot.json#f", "/owner/snapshot.json",
                     "/owner/", "/audit.jsonl", "/link.txt", "//snapshot.json", "/share/",
                     "/index.html/", "/nope"):
            st, _, got = _get(srv, "GET", path)
            assert st == 404, path
            assert b"outside-secret" not in got
        st, _, _ = _get(srv, "POST", "/")
        assert st == 405
    assert res["paths"] and {p.name for p in res["paths"]} == set(share.SHARED_FILES)
    # a served file that is itself a symlink is refused
    root2 = env["tmp"] / "root2"
    root2.mkdir()
    (root2 / "index.html").write_bytes(html)
    os.symlink(str(root / "snapshot.json"), str(root2 / "snapshot.json"))
    with _Running(root2) as srv:
        assert _get(srv, "GET", "/index.html")[0] == 200
        assert _get(srv, "GET", "/snapshot.json")[0] == 404


def test_stale_and_failed_sources_marked(env):
    s = _src(_snap(env))
    assert s["n1:queue"]["stale"] is True
    assert s["n1:gpu"]["stale"] is False
    assert s["rb:ledger"]["stale"] is False
    # events denied
    _board_file(env["root"], "events", [], ok=False, error="denied")
    snap = _snap(env)
    s = _src(snap)
    assert s["n1:events"]["ok"] is False and s["n1:events"]["error"] == "denied"
    assert snap["experiments"]["tracks"] == []
    html = share_serve.render_html(snap)
    assert "unavailable (denied)" in html
    # missing and unparseable inputs are tolerated
    (env["root"] / "board" / "n1_gpu.json").unlink()
    env["sessions"].write_text("{not json", encoding="utf-8")
    snap = _snap(env)
    s = _src(snap)
    assert s["n1:gpu"]["ok"] is False and s["calendar:sessions"]["ok"] is False
    assert s["calendar:sessions"]["error"] == "unparseable"


def test_sources_unchanged(env):
    before = {p: _sha(p) for p in env["inputs"]}
    _build(env)
    _build(env, tier="owner")
    assert {p: _sha(p) for p in env["inputs"]} == before
    assert set(env["inputs"]) == {p for p in env["inputs"] if p.exists()}


def test_shared_tier_has_no_waiting_list_or_pending_details(env):
    snap = _snap(env)
    assert "waiting" not in snap
    assert "cost_usd" not in snap["sessions"]["totals"]
    assert snap["experiments"]["queue"]["pending_approvals"] == 1
    blob = json.dumps(snap)
    for needle in ("waiting", "cost_usd", "secretcfg", "config_name", "gpu_hours\": 3", "j1"):
        assert needle not in blob, needle
    assert "12.5" not in blob
    shared = share.share_dir(env["cfg"])
    owner = share.owner_dir(env["cfg"])
    assert (shared / "snapshot.json").exists() and not (owner / "snapshot.json").exists()

    res = _build(env, tier="owner")
    osnap = res["snapshot"]
    assert osnap["tier"] == "owner"
    assert "waiting" in osnap and isinstance(osnap["waiting"], list)
    assert osnap["waiting"]
    assert osnap["sessions"]["totals"]["cost_usd"] == 12.5
    assert all(Path(p).parent == owner for p in res["paths"])
    assert json.loads((owner / "snapshot.json").read_text(encoding="utf-8"))["tier"] == "owner"
    # the shared file written earlier is not overwritten by the owner build
    assert json.loads((shared / "snapshot.json").read_text(encoding="utf-8"))["tier"] == "shared"
    with pytest.raises(ValueError):
        share_serve.make_server(owner, "127.0.0.1", 0)
    with pytest.raises(ValueError):
        share_serve.serve(owner, "127.0.0.1", 0)


def test_withheld_label_dropped(env, capsys):
    res = _build(env)
    snap = res["snapshot"]
    assert res["dropped"] >= 2 and snap["dropped"] == res["dropped"]
    blob = json.dumps(snap) + share_serve.render_html(snap)
    assert "pp_ltf_" not in blob
    assert all(t["track"] != "pp_ltf_y" for t in snap["experiments"]["tracks"])
    capsys.readouterr()
    rc = cli.main(["share", "build"])
    cap = capsys.readouterr()
    assert rc == 1
    assert "pp_ltf" not in cap.out + cap.err
    assert any(ch.isdigit() for ch in cap.err)


def test_cli_build_variants(env, capsys):
    # no withheld hit: remove the two offending records, exit 0, paths printed, days honoured
    d1 = _days_ago(1)
    _write(env["sessions"], {"sessions": [
        {"start": _iso(d1, T_ARG), "end": _iso(d1, "04:00:00Z"), "machine": "laptop",
         "project": "ARG"}]})
    ev = env["root"] / "board" / "n1_events.json"
    data = json.loads(ev.read_text(encoding="utf-8"))
    data["items"] = [i for i in data["items"] if i["track"] != "pp_ltf_y"]
    ev.write_text(json.dumps(data), encoding="utf-8")
    assert cli.main(["share", "build", "--days", "3"]) == 0
    out = capsys.readouterr().out
    assert "snapshot.json" in out and "dropped 0" in out
    snap = json.loads((share.share_dir(env["cfg"]) / "snapshot.json").read_text(encoding="utf-8"))
    frm = datetime.date.fromisoformat(snap["period"]["from"])
    to = datetime.date.fromisoformat(snap["period"]["to"])
    assert 2 <= (to - frm).days <= 3
    assert cli.main(["share", "build", "--tier", "owner"]) == 0
    assert (share.owner_dir(env["cfg"]) / "snapshot.json").exists()


def test_audit_has_no_payload(env):
    res = _build(env)
    audit = share.share_dir(env["cfg"]) / "audit.jsonl"
    text = audit.read_text(encoding="utf-8")
    lines = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    assert len(lines) == 1
    assert {"ts", "tier", "sources", "items", "dropped", "sha256"} <= set(lines[0])
    assert lines[0]["tier"] == "shared" and lines[0]["dropped"] == res["dropped"]
    assert lines[0]["sha256"] == _sha(res["paths"][1] if res["paths"][1].name == "snapshot.json"
                                      else res["paths"][0])
    for needle in ("ARG", "ZZZ", "pp_ltf", TITLE, T_ARG, "S5"):
        assert needle not in text, needle
    _build(env)
    assert len(audit.read_text(encoding="utf-8").splitlines()) == 2


def test_no_network_client_imported():
    code = ("import sys, rb_host.share; "
            "bad = [m for m in ('urllib.request','http.client','rb_host.server','rb_host.client',"
            "'rb_host.jobs','rb_host.board','mcp','socket') if m in sys.modules]; "
            "print(','.join(bad)); sys.exit(1 if bad else 0)")
    env = dict(os.environ, PYTHONPATH=str(REPO))
    r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                       cwd=str(REPO), timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


def test_labels_not_on_allowlist_become_other(env):
    snap = _snap(env)
    projects = {r["project"] for r in snap["sessions"]["per_day"]}
    projects |= {r["project"] for r in snap["experiments"]["runs_per_day"]}
    projects |= {t["track"] for t in snap["experiments"]["tracks"]}
    assert "ARG" in projects and "other" in projects and "ZZZ" not in projects
    assert "ZZZ" not in json.dumps(snap)
    # no labels configured: every label becomes 'other'
    raw = json.loads(env["host"].read_text(encoding="utf-8"))
    del raw["share"]["labels"]
    env["host"].write_text(json.dumps(raw), encoding="utf-8")
    cfg = config.load_host_config(env["host"])
    snap = share.build(cfg, today=TODAY)["snapshot"]
    assert "ARG" not in json.dumps(snap)


def test_html_has_no_script_or_external_url(env):
    for tier in ("shared", "owner"):
        snap = _snap(env, tier=tier)
        html = share_serve.render_html(snap)
        low = html.lower()
        assert low.lstrip().startswith("<!doctype html")
        for bad in ("<script", "http://", "https://", "src=", "href=", "//"):
            assert bad not in low.replace("<!doctype html>", ""), bad
    # every value is escaped
    snap = _snap(env)
    snap["sources"][0]["id"] = "<b>x</b>"
    out = share_serve.render_html(snap)
    assert "<b>x</b>" not in out and "&lt;b&gt;x&lt;/b&gt;" in out


def test_snapshot_written_atomically(env, monkeypatch):
    res = _build(env)
    root = share.share_dir(env["cfg"])
    assert not list(root.rglob("*.part"))
    index = root / "index.html"
    before = index.read_bytes()
    snap_before = (root / "snapshot.json").read_bytes()

    def boom(snapshot):
        raise RuntimeError("render failed")

    monkeypatch.setattr(share_serve, "render_html", boom)
    if hasattr(share, "render_html"):
        monkeypatch.setattr(share, "render_html", boom)
    with pytest.raises(Exception):
        _build(env)
    assert index.read_bytes() == before
    assert (root / "snapshot.json").read_bytes() == snap_before
    assert not list(root.rglob("*.part"))
    assert res["paths"]


def test_bad_records_do_not_raise(env):
    d1 = _days_ago(1)
    st = _iso(d1, "01:00:00Z")
    _write(env["tmp"] / "cal" / "sessions.json", {"sessions": [
        "str", 5, None, {"start": 5}, {"start": ["x"], "project": 3},
        {"start": "0001-01-01T00:00:00+01:00"}, {"start": "9999-12-31T23:59:59-01:00"},
        {"start": st, "end": _iso(d1, "00:00:00Z"), "project": "ARG"},   # negative duration
        {"start": st, "end": _iso(_days_ago(0), "23:00:00Z"), "project": "ARG"},  # > 24 h
        {"start": st, "end": "9999-12-31T23:59:59-01:00", "project": "ARG"}]})
    _write(env["tmp"] / "runs" / "runs.json", {"runs": [
        1, {"started": "0001-01-01T00:00:00+01:00", "ended": "9999-12-31T23:59:59-01:00"},
        {"status": 7, "started": st}, {"status": "failed", "started": st, "project": "ARG"}]})
    _write(env["root"] / "board" / "n1_events.json", {
        "fetched_at": "0001-01-01T00:00:00+01:00", "ok": True, "cadence_s": True,
        "items": [{"track": "ARG", "stage": "S5", "ts": "9999-12-31T23:59:59-01:00"}, 3]})
    with open(str(env["root"] / "ledger.jsonl"), "ab") as fh:
        fh.write(b'\xff\xfe not utf8\n')
    snap = _snap(env)
    sess = [r for r in snap["sessions"]["per_day"] if r["date"] == d1.isoformat()]
    assert all(0 <= r["active_h"] <= 24 * r["count"] for r in sess)
    assert sum(r["active_h"] for r in sess) == 0
    runs = {(r["date"], r["project"]): r for r in snap["experiments"]["runs_per_day"]}
    assert runs[(d1.isoformat(), "ARG")]["failed"] == 1  # failed, no `ended`
    assert snap["experiments"]["tracks"] == []
    src = _src(snap)
    assert src["rb:ledger"]["ok"] is False and src["rb:ledger"]["error"] == "unreadable"
    assert src["n1:events"]["fetched_at"] is None


def test_node_cache_strings_are_checked(env):
    _write(env["root"] / "board" / "n1_queue.json", {
        "fetched_at": "free text from the node", "ok": False,
        "error": "Something went wrong on the node", "cadence_s": 60, "items": []})
    snap = _snap(env)
    q = _src(snap)["n1:queue"]
    assert q["fetched_at"] is None and q["error"] == "bad_error_code"
    assert "free text" not in json.dumps(snap) and "Something" not in json.dumps(snap)


def test_bad_node_name_skipped(env):
    raw = json.loads(env["host"].read_text(encoding="utf-8"))
    raw["nodes"]["bad name/../x"] = {"alias": "y"}
    env["host"].write_text(json.dumps(raw), encoding="utf-8")
    res = share.build(config.load_host_config(env["host"]), today=TODAY)
    assert not any("bad" in k for k in _src(res["snapshot"]))
    assert res["dropped"] >= 1


def test_withheld_source_error_reported(env):
    env["tmp"].joinpath("withheld.json").write_text("{not json", encoding="utf-8")
    src = _src(_snap(env))["withheld:patterns"]
    assert src["ok"] is False and src["error"]


def test_idle_connection_does_not_block(env):
    _build(env)
    import socket
    with _Running(share.share_dir(env["cfg"])) as srv:
        idle = socket.create_connection(("127.0.0.1", srv.server_address[1]))
        try:
            st, _, _ = _get(srv, "GET", "/")
            assert st == 200
        finally:
            idle.close()


def test_tracks_order_independent(env):
    old, new = _iso(_days_ago(2), "00:00:00Z"), _iso(_days_ago(0), "00:00:00Z")
    evs = [{"track": "ARG", "stage": "S5", "ts": new}, {"track": "ARG", "stage": "S1", "ts": old}]
    wh = share.Withheld.load(Path(env["cfg"].withheld_patterns_file))
    for order in (evs, evs[::-1]):
        t, _ = share.reduce_tracks(order, wh, {"ARG"})
        assert t[0]["stage"] == "S5"


def test_cli_negative_days_rejected(env, capsys):
    assert cli.main(["share", "build", "--days", "-1"]) == 1
    assert "--days must be >= 0" in capsys.readouterr().out


def test_put_has_plain_405_with_headers(env):
    _build(env)
    with _Running(share.share_dir(env["cfg"])) as srv:
        for method in ("PUT", "FOO"):
            st, h, body = _get(srv, method, "/")
            assert st == 405 and h["cache-control"] == "no-store"
            assert h["x-content-type-options"] == "nosniff"
            assert h["content-type"].startswith("text/plain") and b"<" not in body
