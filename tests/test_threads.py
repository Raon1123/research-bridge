"""Stored conversations: thread building, body and attachment readers (design 2026-11-10 §6.7).
No node, no network; ledger and body files are written by hand."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from rb_host import jobs, threads
from rb_host.config import HostConfig
from rb_host.ledger import Ledger
from rb_node.withheld import Withheld


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("RB_HOST_CONFIG", str(tmp_path / "host.json"))
    monkeypatch.setenv("RB_HOST_ROOT", str(tmp_path / "root"))

    def refuse(cfg, node):
        raise AssertionError("jobs.connect used")
    monkeypatch.setattr(jobs, "connect", refuse)


@pytest.fixture
def cfg(tmp_path):
    return HostConfig(nodes={"n1": {"alias": "x"}}, data_root=str(tmp_path / "data"),
                      withheld_patterns_file=str(tmp_path / "withheld.json"))


def add(cfg, rid, direction="out", created="2026-11-10T00:00:00Z", **kw):
    rec = {"kind": "message", "id": rid, "direction": direction, "node": "n1",
           "status": "received" if direction == "in" else "sent", "created": created}
    rec.update(kw)
    assert Ledger(Path(cfg.data_root) / "ledger.jsonl").append(rec)
    return rec


def put_body(cfg, rec, text, prov=None):
    sub = "inbox" if rec["direction"] == "in" else "outbox"
    d = Path(cfg.data_root) / sub / rec["node"] / rec["id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "body.txt").write_text(text, encoding="utf-8")
    if prov is not None:
        (d / "provenance.json").write_text(json.dumps(prov), encoding="utf-8")
    return d


def wh_none():
    return Withheld([])


def test_three_level_thread(cfg):
    add(cfg, "m1", "out", "2026-11-10T00:00:01Z")
    add(cfg, "r1", "in", "2026-11-10T00:00:02Z", reply_to="m1", msg_kind="reply", delivered=True)
    add(cfg, "m2", "out", "2026-11-10T00:00:03Z", reply_to="r1")
    got = threads.load(cfg)
    assert len(got["threads"]) == 1
    t = got["threads"][0]
    assert [r["id"] for r in t["records"]] == ["m1", "r1", "m2"]
    assert t["id"] == "m1"
    assert got["by_msg"] == {"m1": "m1", "r1": "m1", "m2": "m1"}
    assert len(Ledger(Path(cfg.data_root) / "ledger.jsonl").thread("m1")) == 2


def test_dangling_reply_to_is_root(cfg):
    add(cfg, "x1", "in", reply_to="ghost", msg_kind="reply", delivered=True)
    add(cfg, "y1", "out")
    got = threads.load(cfg)
    by_id = {t["id"]: t for t in got["threads"]}
    assert set(by_id) == {"x1", "y1"}
    assert by_id["x1"]["reply_to_unknown"] == ["x1"]
    assert by_id["y1"]["reply_to_unknown"] == []


def test_events_without_reply_to_unthreaded(cfg):
    add(cfg, "e1", "in", msg_kind="event", delivered=True)
    got = threads.load(cfg)
    assert got["threads"] == []
    assert [r["id"] for r in got["events_by_node"]["n1"]] == ["e1"]


def test_job_finished_links_to_job(cfg):
    Ledger(Path(cfg.data_root) / "ledger.jsonl").append(
        {"kind": "job", "id": "j1", "op": "submit", "node": "n1", "status": "queued",
         "created": "2026-11-10T00:00:00Z"})
    e1 = add(cfg, "e1", "in", msg_kind="event", delivered=True)
    put_body(cfg, e1, json.dumps({"event": "job_finished", "job_id": "j1", "status": "done"}))
    e2 = add(cfg, "e2", "in", msg_kind="event", delivered=True)
    put_body(cfg, e2, json.dumps({"event": "job_finished", "job_id": "nope", "status": "done"}))
    e3 = add(cfg, "e3", "in", msg_kind="event", delivered=True)
    put_body(cfg, e3, "")  # blanked by the withheld check
    got = threads.load(cfg)
    assert [j["id"] for j in got["jobs"]] == ["j1"]
    assert [r["id"] for r in got["jobs"][0]["events"]] == ["e1"]
    assert [r["id"] for r in got["orphan_events"]] == ["e2"]
    assert [r["id"] for r in got["events_by_node"]["n1"]] == ["e3"]
    assert got["threads"] == []


def test_responder_failed_joins_thread(cfg):
    add(cfg, "m1", "out", "2026-11-10T00:00:01Z")
    ev = add(cfg, "e1", "in", "2026-11-10T00:00:05Z", msg_kind="event", reply_to="m1",
             delivered=True)
    put_body(cfg, ev, json.dumps({"event": "responder_failed"}))
    got = threads.load(cfg)
    assert len(got["threads"]) == 1
    assert [r["id"] for r in got["threads"][0]["records"]] == ["m1", "e1"]
    assert got["events_by_node"] == {}


def test_node_time_from_id_prefix(cfg):
    ns = 1_762_646_400 * 10 ** 9  # 2025-11-09T00:00:00Z
    rid = "%020d-abcd1234" % ns
    rec = {"id": rid, "direction": "in", "created": "2026-11-10T00:00:00Z"}
    assert threads.node_time(rec) == "2025-11-09T00:00:00Z"
    assert threads.node_time(dict(rec, direction="out")) == "2026-11-10T00:00:00Z"
    assert threads.node_time({"id": "plain", "direction": "in", "created": "c"}) == "c"
    assert threads.node_time({"id": "plain"}) == ""
    # ordering inside a thread uses the node time, not the later `created`
    add(cfg, "m1", "out", "2026-11-10T00:00:00Z")
    add(cfg, rid, "in", "2026-11-10T09:00:00Z", reply_to="m1", msg_kind="reply", delivered=True)
    ids = [r["id"] for r in threads.load(cfg)["threads"][0]["records"]]
    assert ids == [rid, "m1"]
    assert threads.load(cfg)["threads"][0]["id"] == rid


def test_states(cfg):
    add(cfg, "a1", "out", "2026-11-10T00:00:01Z", status="pending_send")
    add(cfg, "b1", "out", "2026-11-10T00:00:01Z")
    add(cfg, "b2", "in", "2026-11-10T00:00:02Z", reply_to="b1", msg_kind="reply", delivered=False)
    add(cfg, "c1", "in", "2026-11-10T00:00:01Z", msg_kind="reply", delivered=True)
    add(cfg, "c2", "out", "2026-11-10T00:00:02Z", reply_to="c1")
    got = {t["id"]: t for t in threads.load(cfg)["threads"]}
    assert got["a1"]["state"] == "delivery pending"
    assert got["b1"]["state"] == "open"
    assert got["b1"]["undelivered"] == 1
    assert got["c1"]["state"] == "answered"
    assert got["c1"]["last_at"] == "2026-11-10T00:00:02Z"


def test_cache_invalidated_on_ledger_change(cfg):
    add(cfg, "m1", "out")
    first = threads.load(cfg)
    assert threads.load(cfg) is first
    assert first["ledger_mtime_ns"] is not None
    add(cfg, "m2", "out")
    second = threads.load(cfg)
    assert {t["id"] for t in second["threads"]} == {"m1", "m2"}


def test_load_without_ledger(cfg):
    got = threads.load(cfg)
    assert got["threads"] == [] and got["jobs"] == [] and got["ledger_mtime_ns"] is None


def test_missing_body_placeholder(cfg):
    rec = add(cfg, "m1", "out")
    out = threads.read_body(cfg, rec, wh_none())
    assert out == {"text": "", "missing": True, "truncated": False}


def test_read_body_remasks_and_truncates(cfg):
    rec = add(cfg, "r1", "in", msg_kind="reply", delivered=True)
    put_body(cfg, rec, "keep\nsecretfam_x\n" + "z" * 25000)
    out = threads.read_body(cfg, rec, Withheld(["secretfam_"]))
    assert out["missing"] is False and out["truncated"] is True
    assert out["text"].startswith("keep\n\n") and "secretfam_" not in out["text"]
    assert out["text"].endswith("\n[truncated]")
    short = threads.read_body(cfg, rec, Withheld(["secretfam_"]), limit=5)
    assert short["text"] == "keep\n\n[truncated]"


def test_body_symlink_leaving_the_directory_is_not_read(cfg, tmp_path):
    rec = add(cfg, "m1", "out")
    d = put_body(cfg, rec, "x")
    outside = tmp_path / "outside.txt"
    outside.write_text("OUTSIDE", encoding="utf-8")
    (d / "body.txt").unlink()
    (d / "body.txt").symlink_to(outside)
    assert threads.body_path(cfg, rec) is None
    assert threads.read_body(cfg, rec, wh_none())["missing"] is True


def test_attachments_from_provenance_and_masked_names(cfg):
    rec = add(cfg, "r1", "in", msg_kind="reply", delivered=True)
    put_body(cfg, rec, "b", prov={"files": [
        {"index": 0, "name": "plot.png", "status": "ok", "bytes": 12, "sha256": "ab" * 32},
        {"index": 1, "name": "secretfam_a.txt", "status": "ok", "bytes": 3, "sha256": "cd" * 32},
        {"index": 2, "status": "quarantined", "reason": "deny_name", "bytes": 9}]})
    got = threads.attachments(cfg, rec, Withheld(["secretfam_"]))
    assert [f["name"] for f in got["files"]] == ["plot.png", "(withheld)"]
    assert got["files"][0] == {"name": "plot.png", "bytes": 12, "sha256": "ab" * 32,
                               "status": "ok"}
    assert got["quarantined"] == [{"reason": "deny_name"}]


def test_attachments_outgoing_and_missing(cfg):
    rec = add(cfg, "m1", "out")
    assert threads.attachments(cfg, rec, wh_none()) == {"files": [], "quarantined": []}
    put_body(cfg, rec, "b", prov={"attachments": [
        {"index": 0, "name": "a.txt", "bytes": 1, "sha256": "ef" * 32}]})
    got = threads.attachments(cfg, rec, wh_none())
    assert [f["name"] for f in got["files"]] == ["a.txt"]


def test_quarantined_names_never_in_model(cfg):
    rec = add(cfg, "r1", "in", msg_kind="reply", delivered=True)
    put_body(cfg, rec, "b", prov={"files": [
        {"index": 0, "name": "REALNAME.txt", "status": "quarantined", "reason": "bad_name"}]})
    got = threads.attachments(cfg, rec, wh_none())
    assert got["files"] == []
    assert "REALNAME" not in json.dumps(got)
    assert got["quarantined"] == [{"reason": "bad_name"}]


_AUDIT = {"on": False, "opened": []}


def _hook(event, args):
    if _AUDIT["on"] and event == "open":
        _AUDIT["opened"].append(str(args[0]))


sys.addaudithook(_hook)


def test_unsafe_record_id_never_read(cfg):
    evil = {"kind": "message", "id": "../../host", "direction": "in", "node": "n1",
            "msg_kind": "reply", "created": "2026-11-10T00:00:00Z", "delivered": True}
    Ledger(Path(cfg.data_root) / "ledger.jsonl").append(evil)
    trap = Path(cfg.data_root) / "host"
    trap.mkdir(parents=True)
    (trap / "body.txt").write_text("TRAP", encoding="utf-8")
    (trap / "provenance.json").write_text("{}", encoding="utf-8")
    assert threads.stored_dir(cfg, evil) is None
    _AUDIT["opened"].clear()
    _AUDIT["on"] = True
    try:
        assert threads.body_path(cfg, evil) is None
        assert threads.read_body(cfg, evil, wh_none())["missing"] is True
        assert threads.attachments(cfg, evil, wh_none())["files"] == []
        threads.load(cfg)
    finally:
        _AUDIT["on"] = False
    assert not [p for p in _AUDIT["opened"] if str(trap) in p]


def test_unknown_node_has_no_stored_dir(cfg):
    assert threads.stored_dir(cfg, {"id": "m1", "node": "zz", "direction": "out"}) is None


def test_clean_block_keeps_newlines_removes_bidi():
    assert threads.clean_block("a‮b\nc\x07", 100) == "ab\nc"
    assert threads.clean_block("a\tb\r\nc", 100) == "a\tb\nc"
    assert threads.clean_block("abcdef", 3) == "abc\n[truncated]"
