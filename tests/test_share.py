"""Status snapshot of the hub page route /status (share.snapshot; designs
docs/design/2026-11-06-shared-status-page.md §10 and docs/design/2026-11-11-hub-status-page.md §10).

Fixtures are copies under tmp_path with placeholder labels only. The session-calendar and
run-view shapes are ASSUMED (see the 2026-11-06 design §8). Tests of the removed share.build,
the tiers and rb share serve are archived in docs/99_Archive/shared-status-page/.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from rb_host import cli, config, share
from rb_host.ledger import Ledger

REPO = Path(__file__).resolve().parents[1]
TODAY = datetime.datetime.now(datetime.timezone.utc).date()

TITLE = "TITLE-free-text-zq"
EXTRA = "extra_field_zq"
METRIC = "metric_value_zq"
T_ARG = "03:17:41Z"  # unusual time of day


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
                  "runs": str(runs), "labels": ["ARG"]}}), encoding="utf-8")
    monkeypatch.setenv("RB_HOST_CONFIG", str(host))
    return {"tmp": tmp_path, "root": root, "host": host,
            "cfg": config.load_host_config(host), "sessions": sess}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _snap(env, **kw) -> dict:
    kw.setdefault("today", TODAY)
    return share.snapshot(env["cfg"], **kw)


def _src(snap: dict) -> dict:
    return {s["id"]: s for s in snap["sources"]}


def test_all_sections_present(env):
    snap = _snap(env)
    assert snap["schema_version"] == share.SCHEMA_VERSION == 2
    for k in ("built_at", "period", "sources", "sessions", "experiments", "activity", "dropped"):
        assert k in snap
    assert set(snap["period"]) == {"from", "to"}
    assert snap["period"]["to"] == TODAY.isoformat()
    assert set(snap["sessions"]) == {"per_day", "totals", "active_now", "nodes"}
    assert {"sessions", "routines", "active_h"} <= set(snap["sessions"]["totals"])
    exp = snap["experiments"]
    assert set(exp) == {"queue", "gpu", "runs_per_day", "tracks"}
    assert set(exp["queue"]) == {"queued", "running", "done", "failed", "other", "pending_approvals"}
    assert {"in_use", "total", "gpu_hours_period"} <= set(exp["gpu"])
    assert set(_src(snap)) == {"calendar:sessions", "calendar:status", "runs", "n1:queue",
                               "n1:gpu", "n1:events", "rb:ledger",
                               "withheld:patterns"}
    # sessions: ARG laptop 1.5 h + a record without end (0 h); ZZZ -> 'gpu-box' is not a lane: other
    day = _days_ago(1).isoformat()
    row = [r for r in snap["sessions"]["per_day"]
           if r["date"] == day and r["lane"] == "laptop" and r["project"] == "ARG"]
    assert len(row) == 1 and row[0]["count"] == 2 and row[0]["active_h"] == 1.5
    assert any(r["lane"] == "other" and r["project"] == "other"
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
    blob = json.dumps(_snap(env))
    for needle in (TITLE, EXTRA, METRIC, "metrics", "secretcfg", "gpu-a", "gpu-box"):
        assert needle not in blob, needle


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
    # missing and unparseable inputs are tolerated
    (env["root"] / "board" / "n1_gpu.json").unlink()
    env["sessions"].write_text("{not json", encoding="utf-8")
    snap = _snap(env)
    s = _src(snap)
    assert s["n1:gpu"]["ok"] is False and s["calendar:sessions"]["ok"] is False
    assert s["calendar:sessions"]["error"] == "unparseable"


def test_withheld_label_dropped(env):
    snap = _snap(env)
    assert snap["dropped"] >= 2
    assert "pp_ltf_" not in json.dumps(snap)
    assert all(t["track"] != "pp_ltf_y" for t in snap["experiments"]["tracks"])


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
    # without share.labels the labels are shown: test_snapshot_label_rule_without_allowlist


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
    snap = share.snapshot(config.load_host_config(env["host"]), today=TODAY)
    assert not any("bad" in k for k in _src(snap))
    assert snap["dropped"] >= 1


def test_withheld_source_error_reported(env):
    env["tmp"].joinpath("withheld.json").write_text("{not json", encoding="utf-8")
    src = _src(_snap(env))["withheld:patterns"]
    assert src["ok"] is False and src["error"]


def test_tracks_order_independent(env):
    old, new = _iso(_days_ago(2), "00:00:00Z"), _iso(_days_ago(0), "00:00:00Z")
    evs = [{"track": "ARG", "stage": "S5", "ts": new}, {"track": "ARG", "stage": "S1", "ts": old}]
    wh = share.Withheld.load(Path(env["cfg"].withheld_patterns_file))
    for order in (evs, evs[::-1]):
        t, _ = share.reduce_tracks(order, wh, {"ARG"})
        assert t[0]["stage"] == "S5"


def test_queue_states_of_the_node_are_counted():
    # G5 (design 2026-11-11 §8): the node reports jobs, processing, done, failed
    q = share.reduce_queue([{"state": "jobs", "count": 3}, {"state": "processing", "count": 1},
                            {"state": "done", "count": 5}, {"state": "failed", "count": 2},
                            {"state": "Queued", "count": 1}, {"state": "paused", "count": 4},
                            {"state": "jobs", "count": -1}, {"state": "jobs", "count": True},
                            {"state": 3, "count": 1}, "x"])
    assert q == {"queued": 4, "running": 1, "done": 5, "failed": 2, "other": 4}


def _tree(root: Path) -> dict:
    out = {}
    for p in sorted(root.rglob("*")):
        st = p.lstat()
        out[str(p)] = (p.is_dir(), st.st_size, st.st_mtime_ns,
                       None if p.is_dir() else _sha(p))
    return out


def _with_share(env, **share_conf):
    raw = json.loads(env["host"].read_text(encoding="utf-8"))
    for k, v in share_conf.items():
        if v is None:
            raw["share"].pop(k, None)
        else:
            raw["share"][k] = v
    env["host"].write_text(json.dumps(raw), encoding="utf-8")
    return config.load_host_config(env["host"])


def _ssnap(cfg, **kw):
    kw.setdefault("today", TODAY)
    return share.snapshot(cfg, **kw)


def _put_in(root: Path, rec: dict, text: str) -> None:
    d = root / "inbox" / rec["node"] / rec["id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "body.txt").write_text(text, encoding="utf-8")


def test_snapshot_writes_nothing(env):
    # G4: no file under the temporary tree (data root and every source) is created or changed
    before = _tree(env["tmp"])
    snap = _ssnap(env["cfg"])
    assert snap["schema_version"] == share.SCHEMA_VERSION == 2
    assert _tree(env["tmp"]) == before
    assert not (env["root"] / "share").exists()


def test_snapshot_sections(env):
    snap = _ssnap(env["cfg"])
    assert "tier" not in snap and "waiting" not in snap
    assert set(snap) == {"schema_version", "built_at", "period", "sources", "sessions",
                         "experiments", "activity", "dropped"}
    assert set(snap["experiments"]["queue"]) == {"queued", "running", "done", "failed", "other",
                                                 "pending_approvals"}
    assert snap["sessions"]["totals"]["cost_usd"] == 12.5
    assert snap["experiments"]["queue"]["pending_approvals"] == 1
    assert snap["experiments"]["gpu"]["gpu_hours_period"] == 3
    blob = json.dumps(snap)
    for needle in ("secretcfg", "config_name", "j1", TITLE, EXTRA, METRIC):
        assert needle not in blob, needle


def test_snapshot_counts_node_queue_states(env):
    _board_file(env["root"], "queue", [{"state": "jobs", "count": 3},
                                       {"state": "processing", "count": 1},
                                       {"state": "done", "count": 7}, {"state": "failed", "count": 2},
                                       {"state": "held", "count": 4}])
    q = _ssnap(env["cfg"])["experiments"]["queue"]
    assert (q["queued"], q["running"], q["done"], q["failed"], q["other"]) == (3, 1, 7, 2, 4)


def test_snapshot_lane_rule(env):
    d1 = _days_ago(1)
    lanes = ["laptop", "hub", "server", "n1", "gpu-box", 5]
    _write(env["sessions"], {"sessions": [
        {"start": _iso(d1, "01:00:00Z"), "end": _iso(d1, "02:00:00Z"), "lane": ln,
         "project": "ARG"} for ln in lanes]})
    got = sorted(r["lane"] for r in _ssnap(env["cfg"])["sessions"]["per_day"])
    assert got == sorted(["laptop", "hub", "server", "n1", "other"])
    rows = {r["lane"]: r["count"] for r in _ssnap(env["cfg"])["sessions"]["per_day"]}
    assert rows["other"] == 2


def test_snapshot_label_rule_without_allowlist(env):
    cfg = _with_share(env, labels=None)
    d1 = _days_ago(1)
    long = "L" * 80
    _write(env["sessions"], {"sessions": [
        {"start": _iso(d1, "01:00:00Z"), "lane": "hub", "project": p}
        for p in ("ARG", "x‮<b>\x1b[1m", long, 7, "unrelated", "pp_ltf_z", "\x1b")]})
    snap = _ssnap(cfg)
    rows = {r["project"]: r["count"] for r in snap["sessions"]["per_day"]}
    assert rows == {"ARG": 1, "x<b>[1m": 1, "L" * 60: 1, "unrelated": 1, "other": 2}
    assert snap["dropped"] >= 1 and "pp_ltf_" not in json.dumps(snap)
    # with an allowlist, a label outside it is other
    cfg = _with_share(env, labels=["ARG"])
    projects = {r["project"] for r in _ssnap(cfg)["sessions"]["per_day"]}
    assert projects == {"ARG", "other"}


def test_snapshot_activity_rows(env):
    root = env["root"]
    led = Ledger(root / "ledger.jsonl")
    d0, d1, d2, d9 = (_iso(_days_ago(n), "06:00:00Z") for n in (0, 1, 2, 9))
    led.append({"kind": "job", "op": "submit", "id": "j2", "node": "n1", "gpu_hours": 1,
                "status": "queued", "created": d2, "approved_at": d1})
    led.append({"kind": "job", "op": "cancel", "id": "j3", "node": "n1", "target_job_id": "j2",
                "status": "queued", "created": d1, "approved_at": d1})
    led.append({"kind": "job", "op": "submit", "id": "j4", "node": "n1", "gpu_hours": 1,
                "status": "rejected", "created": d0, "rejected_at": d0})
    led.append({"kind": "job", "op": "submit", "id": "j-old", "node": "n1", "status": "queued",
                "created": d9, "approved_at": d9})
    led.append({"kind": "message", "id": "m-out", "direction": "out", "node": "n1",
                "status": "sent", "created": d0})
    led.append({"kind": "message", "id": "m-in", "direction": "in", "node": "n1",
                "msg_kind": "reply", "status": "received", "created": d0})
    events = [("ev-done", d1, {"event": "job_finished", "job_id": "j2", "status": "done"}),
              ("ev-fail", d1, {"event": "job_finished", "job_id": "j2", "status": "FAILED"}),
              ("ev-crash", d0, {"event": "job_finished", "job_id": "jx", "status": "crashed"}),
              ("ev-masked", d0, {"event": "job_finished", "job_id": "j2", "status": "failed",
                                 "reason": "pp_ltf_q"}),
              ("ev-other", d0, {"event": "responder_failed", "status": "failed"}),
              ("ev-old", d9, {"event": "job_finished", "job_id": "j2", "status": "failed"})]
    for eid, when, body in events:
        rec = {"kind": "message", "id": eid, "direction": "in", "node": "n1",
               "msg_kind": "event", "status": "received", "created": when}
        led.append(rec)
        _put_in(root, rec, json.dumps(body))
    snap = _ssnap(env["cfg"])
    rows = snap["activity"]
    assert [r["date"] for r in rows] == [_days_ago(n).isoformat() for n in range(8)]
    by = {r["date"]: r for r in rows}
    t0, t1, t2 = (by[_days_ago(n).isoformat()] for n in (0, 1, 2))
    assert (t2["submits"], t2["cancels"], t2["approved"]) == (1, 0, 0)
    assert (t1["submits"], t1["cancels"], t1["approved"]) == (1, 1, 2)  # j1 is from fixture
    assert (t0["submits"], t0["approved"]) == (1, 0)  # a refused approval has no approved_at
    assert (t1["finished"], t1["failed"]) == (2, 1)
    # ev-masked: its body line is blanked by the withheld mask, so it counts as finished only
    assert (t0["finished"], t0["failed"]) == (2, 1)
    assert (t0["sent"], t0["received"]) == (1, 1)
    assert sum(r["sent"] + r["received"] for r in rows) == 2  # events are not messages
    assert "pp_ltf_" not in json.dumps(snap)


def test_snapshot_never_raises_for_broken_sources(env):
    root = env["root"]
    (root / "board" / "n1_gpu.json").unlink()
    (root / "board" / "n1_queue.json").write_text("{not json", encoding="utf-8")
    (root / "board" / "n1_events.json").write_text("[1, 2]", encoding="utf-8")
    env["sessions"].write_text("{not json", encoding="utf-8")
    with open(str(root / "ledger.jsonl"), "ab") as fh:
        fh.write(b"\xff\xfe not utf8\n")  # the ledger cannot be decoded
    cfg = _with_share(env, runs=str(env["tmp"] / "nope.json"), calendar_status=5)
    snap = _ssnap(cfg)
    src = _src(snap)
    assert src["n1:gpu"]["error"] == "never_fetched"
    assert src["n1:queue"]["error"] == "unparseable"
    assert src["n1:events"]["error"] == "unparseable"
    assert src["calendar:sessions"]["error"] == "unparseable"
    assert src["runs"]["error"] == "missing"
    assert src["calendar:status"]["error"] == "not_configured"
    assert src["rb:ledger"]["ok"] is False and src["rb:ledger"]["error"] == "unreadable"
    assert snap["activity"] == []
    for s in snap["sources"]:
        assert s["error"] is None or share.ERROR_CODE.match(s["error"]), s


def test_snapshot_error_codes_are_filtered(env):
    _board_file(env["root"], "gpu", [], ok=False, error="unrelated<b>")
    _board_file(env["root"], "events", [], ok=False, error="pp_ltf_err")
    snap = _ssnap(env["cfg"])
    src = _src(snap)
    assert src["n1:gpu"]["error"] == "bad_error_code"
    assert src["n1:events"]["error"] == "withheld"
    assert "pp_ltf_" not in json.dumps(snap) and "<b>" not in json.dumps(snap)
    env["tmp"].joinpath("withheld.json").write_text("{not json", encoding="utf-8")
    assert _src(_ssnap(env["cfg"]))["withheld:patterns"]["error"] == "unparseable"


def test_snapshot_days(env):
    snap = _ssnap(env["cfg"], days=3)
    assert snap["period"] == {"from": _days_ago(3).isoformat(), "to": TODAY.isoformat()}
    assert len(snap["activity"]) == 4
    with pytest.raises(ValueError):
        share.snapshot(env["cfg"], days=-1)


def test_share_is_no_longer_a_command(capsys):
    # G6 (design 2026-11-11): rb share build|serve and share_serve.py are archived
    for argv in (["share", "build"], ["share", "serve"]):
        with pytest.raises(SystemExit) as exc:
            cli.main(argv)
        assert exc.value.code == 2
    assert "invalid choice: 'share'" in capsys.readouterr().err
    assert not (REPO / "rb_host" / "share_serve.py").exists()
    assert not hasattr(share, "build") and not hasattr(share, "share_dir")


# -- sessions collected from the nodes (docs/design/2026-11-11-node-sessions.md §8) ----------
SA, SB, SC, SD = ("0a1b2c3d-0000-4000-8000-%012d" % i for i in range(1, 5))


def _now_minus(seconds: int) -> str:
    t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=seconds)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _node_store(root: Path, sessions: dict, node="n1", **kw) -> Path:
    rec = {"schema": 1, "node": node, "fetched_at": _now_minus(60), "attempted_at": _now_minus(60),
           "ok": True, "error": None, "tree": "trm", "outside": 0, "unparsed": 0, "files": 1,
           "truncated": False, "skipped": 0, "sessions": sessions}
    rec.update(kw)
    return _write(root / "sessions" / ("%s.json" % node), rec)


def _sync_field(root: Path, value, node="n1") -> None:
    _write(root / "sync" / ("%s.json" % node), {"schema": 1, "node": node, "ok": True,
                                                  "board": {}, "sessions": value})


def _node_info(snap: dict, node="n1") -> dict:
    return {n["node"]: n for n in snap["sessions"]["nodes"]}[node]


def test_node_sessions_rows_from_the_store(env):
    d1, d2 = _days_ago(1).isoformat(), _days_ago(2).isoformat()
    _node_store(env["root"], {
        SA: {"label": "ARG", "start": _iso(_days_ago(2), "10:00:00Z"),
             "end": _iso(_days_ago(1), "11:00:00Z"), "days": {d1: 3600, d2: 1800}},
        SB: {"label": "ARG", "start": _iso(_days_ago(1), "09:00:00Z"),
             "end": _iso(_days_ago(1), "09:00:00Z"), "days": {}},
        SC: {"label": "lab/not-on-the-allowlist", "start": _iso(_days_ago(1), "08:00:00Z"),
             "end": _iso(_days_ago(1), "08:30:00Z"), "days": {d1: 900}},
        SD: {"label": "ARG", "start": _now_minus(3000), "end": _now_minus(400),
             "days": {_now_minus(400)[:10]: 0}},
    }, outside=3, unparsed=2, truncated=True, skipped=1)
    snap = _snap(env)
    rows = {(r["date"], r["lane"], r["project"]): r for r in snap["sessions"]["per_day"]}
    assert rows[(d1, "n1", "ARG")]["count"] == 2 and rows[(d1, "n1", "ARG")]["active_h"] == 1.0
    assert rows[(d2, "n1", "ARG")]["count"] == 1 and rows[(d2, "n1", "ARG")]["active_h"] == 0.5
    assert rows[(d1, "n1", "other")]["count"] == 1 and rows[(d1, "n1", "other")]["active_h"] == 0.25
    assert rows[(_now_minus(3000)[:10], "n1", "ARG")]["count"] >= 1  # counted on its start day
    assert (d1, "laptop", "ARG") in rows  # the file source is still there
    info = _node_info(snap)
    assert info["state"] == "ok" and info["active_now"] == 1 and info["sessions"] == 4
    assert (info["outside"], info["unparsed"], info["truncated"], info["skipped"]) == (3, 2, True, 1)
    assert snap["sessions"]["active_now"] == 1
    src = _src(snap)["n1:sessions"]
    assert src["ok"] is True and src["error"] is None and src["fetched_at"]
    assert snap["sessions"]["totals"]["sessions"] == sum(  # totals stay the file source's
        r["count"] for r in snap["sessions"]["per_day"] if r["lane"] != "n1")


def test_node_sessions_four_states(env):
    states = {}
    for field in ("unsupported", "not_configured", "io_error"):
        _sync_field(env["root"], field)
        snap = _snap(env)
        info = _node_info(snap)
        states[field] = (info["state"], info["error"])
        assert info["fetched_at"] is None and snap["sessions"]["active_now"] == 0
        assert _src(snap)["n1:sessions"]["ok"] is False
    _node_store(env["root"], {})
    info = _node_info(_snap(env))
    states["ok"] = (info["state"], info["error"])
    assert states == {"unsupported": ("unsupported", "unsupported"),
                      "not_configured": ("not_configured", "not_configured"),
                      "io_error": ("error", "io_error"), "ok": ("ok", None)}
    assert info["sessions"] == 0


def test_store_state_wins_over_the_status_field(env):
    _sync_field(env["root"], "ok")
    _node_store(env["root"], {SA: {"label": "ARG", "start": _now_minus(100),
                                   "end": _now_minus(50), "days": {}}},
                ok=False, error="not_configured")
    snap = _snap(env)
    info = _node_info(snap)
    assert info["state"] == "not_configured"
    assert any(r["lane"] == "n1" for r in snap["sessions"]["per_day"])  # history still shown


def test_node_never_asked_has_no_sessions_row(env):
    snap = _snap(env)
    assert snap["sessions"]["nodes"] == [] and "n1:sessions" not in _src(snap)
    _sync_field(env["root"], None)
    assert _snap(env)["sessions"]["nodes"] == []


def test_node_store_codes_and_labels_are_checked(env):
    wp = Path(env["cfg"].withheld_patterns_file)
    wp.write_text(json.dumps({"patterns": ["unrelatedfam_"]}), encoding="utf-8")
    for code, shown in (("Bad Code!", "bad_error_code"), ("e2e_fail", "bad_error_code"),
                        ("unrelatedfam_x", "withheld"), (7, "unavailable")):
        _node_store(env["root"], {}, ok=False, error=code)
        assert _node_info(_snap(env))["error"] == shown, code
    _node_store(env["root"], {
        SA: {"label": "unrelatedfam_run", "start": _now_minus(100), "end": _now_minus(50),
             "days": {}},
        SB: {"label": "<b>ARG</b>", "start": _now_minus(100), "end": _now_minus(50), "days": {}}})
    c = config.load_host_config(env["host"])
    c.share.pop("labels")
    snap = share.snapshot(c, today=TODAY)
    blob = json.dumps(snap)
    assert "unrelatedfam_" not in blob and snap["dropped"] >= 1
    assert "<b>ARG</b>" in blob  # cleaned text is kept; the page escapes it


@pytest.mark.parametrize("content", [b"{not json", b"[]", b'{"sessions": []}', b"\xff\xfe",
                                     json.dumps({"sessions": {SA: "x", SB: {"days": "x"},
                                                              SC: {"start": 5}},
                                                 "ok": True, "fetched_at": 9}).encode()])
def test_bad_node_store_never_raises(env, content):
    p = env["root"] / "sessions" / "n1.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    snap = _snap(env)
    info = _node_info(snap)
    assert info["state"] in ("ok", "error")
    assert not any(r["lane"] == "n1" for r in snap["sessions"]["per_day"])


def test_unreadable_node_store(env):
    p = _node_store(env["root"], {})
    p.chmod(0)
    try:
        if os.access(str(p), os.R_OK):
            pytest.skip("running as a user who can read mode 000 files")
        info = _node_info(_snap(env))
        assert (info["state"], info["error"]) == ("error", "unreadable")
    finally:
        p.chmod(0o600)


def test_snapshot_writes_nothing_with_a_node_store(env):
    _node_store(env["root"], {SA: {"label": "ARG", "start": _now_minus(100),
                                   "end": _now_minus(50), "days": {}}})
    _sync_field(env["root"], "ok")
    before = _tree(env["tmp"])
    _ssnap(env["cfg"])
    assert _tree(env["tmp"]) == before
