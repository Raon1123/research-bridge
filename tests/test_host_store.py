"""Laptop storage of node-supplied data: names, bodies, size cap (PM-06, PM-09, PM-10)."""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

from rb_host.client import NodeClient, RemoteError
from rb_host.config import HostConfig
from rb_host.store import store_incoming


class FakeClient:
    def __init__(self, files):
        self.files = files
        self.calls = []

    def get_file(self, kind, ref, dest):
        self.calls.append(ref)
        name = ref.split("/", 1)[1]
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.files[name])
        return "x"


def _hcfg(tmp_path):
    return HostConfig(nodes={"node1": {"alias": "a"}}, data_root=str(tmp_path / "data"),
                      withheld_patterns_file=str(tmp_path / "none.json"))


def _files(root):
    return sorted(p.name for p in root.rglob("*") if p.is_file())


# -- PM-06 --------------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["C:x", "a:b", "CON", "con.txt", "NUL", "COM1", "lpt9.log",
                                 "aux.tar.gz", "a*b", "x\x01y", "trail. "])
def test_store_incoming_rejects_unsafe_names(tmp_path, bad):
    cfg = _hcfg(tmp_path)
    item = {"id": "m6", "body": "", "attachments": [{"name": bad}, {"name": "good.txt"}]}
    cl = FakeClient({bad: b"evil", "good.txt": b"fine"})
    out = store_incoming(cfg, "node1", item, cl)
    data = tmp_path / "data"
    assert out["quarantined"] == 1 and out["files"] == ["good.txt"]
    assert cl.calls == ["m6/good.txt"]  # the bad name is never fetched
    prov = json.loads((data / "inbox" / "node1" / "m6" / "provenance.json").read_text("utf-8"))
    bad_entries = [f for f in prov["files"] if f["status"] == "quarantined"]
    assert [f["reason"] for f in bad_entries] == ["bad_name"] and "name" not in bad_entries[0]
    assert _files(data) == ["body.txt", "good.txt", "provenance.json"]


@pytest.mark.parametrize("bad", ["C:x", "CON", "a/b", "..", ".hidden", "x y.", "", "m:1"])
def test_store_incoming_rejects_unsafe_message_id(tmp_path, bad):
    cfg = _hcfg(tmp_path)
    with pytest.raises(ValueError):
        store_incoming(cfg, "node1", {"id": bad, "body": "b"}, FakeClient({}))
    assert not (tmp_path / "data").exists() or _files(tmp_path / "data") == []


def test_store_incoming_keeps_sec02(tmp_path):
    cfg = _hcfg(tmp_path)
    item = {"id": "m7", "body": "", "attachments": [{"name": "CLAUDE.md"}, {"name": ".mcp.json"}]}
    out = store_incoming(cfg, "node1", item, FakeClient({"CLAUDE.md": b"x", ".mcp.json": b"{}"}))
    assert sorted(out["files"]) == [".mcp.json.untrusted", "CLAUDE.md.untrusted"]


# -- PM-09 --------------------------------------------------------------------------------
def test_store_incoming_writes_masked_body(tmp_path):
    cfg = _hcfg(tmp_path)
    item = {"id": "m9", "body": "ok line\nsee pp_ltf_x here\nend", "attachments": []}
    out = store_incoming(cfg, "node1", item, FakeClient({}))
    text = (tmp_path / "data" / "inbox" / "node1" / "m9" / "body.txt").read_text(encoding="utf-8")
    assert text == out["body"] and "pp_ltf_x" not in text and "ok line" in text


# -- PM-10 --------------------------------------------------------------------------------
def _endless(tmp_path):
    """ssh stand-in whose get_file replies never carry eof."""
    script = tmp_path / "endless.py"
    script.write_text(textwrap.dedent("""
        import base64, sys
        from rb_node.protocol import encode, read_message
        while True:
            msg = read_message(sys.stdin.buffer)
            if msg is None:
                break
            res = {"data_b64": base64.b64encode(b"x" * 1024).decode(), "eof": False}
            sys.stdout.buffer.write(encode({"id": msg["id"], "ok": True, "result": res}))
            sys.stdout.buffer.flush()
    """), encoding="utf-8")
    return [sys.executable, str(script)]


def test_get_file_stops_at_size_cap(tmp_path, monkeypatch):
    import rb_host.client as rc
    monkeypatch.setattr(rc, "MAX_FILE", 10 * 1024)
    dest = tmp_path / "dl" / "big.bin"
    env = {"PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    with NodeClient("x", ssh_argv=_endless(tmp_path), env=env) as c:
        with pytest.raises(RemoteError) as ei:
            c.get_file("doc", "big.bin", dest)
    assert ei.value.code == "too_large"
    assert not dest.exists()
    assert list(dest.parent.iterdir()) == []  # the .part file is deleted


def test_store_incoming_quarantines_oversize(tmp_path):
    class Big:
        def get_file(self, kind, ref, dest):
            raise RemoteError("too_large", "x")
    item = {"id": "m10", "body": "", "attachments": [{"name": "huge.bin"}]}
    out = store_incoming(_hcfg(tmp_path), "node1", item, Big())
    assert out["quarantined"] == 1


# -- fix round 1 --------------------------------------------------------------------------
def test_attachment_cannot_overwrite_body_or_provenance(tmp_path):
    item = {"id": "m1", "body": "real body",
            "attachments": [{"name": "body.txt"}, {"name": "provenance.json"},
                            {"name": "same.txt"}, {"name": "SAME.txt"}]}
    cl = FakeClient({"body.txt": b"evil", "provenance.json": b"evil", "same.txt": b"one",
                     "SAME.txt": b"two"})
    out = store_incoming(_hcfg(tmp_path), "node1", item, cl)
    inbox = tmp_path / "data" / "inbox" / "node1" / "m1"
    assert (inbox / "body.txt").read_text(encoding="utf-8") == "real body"
    assert json.loads((inbox / "provenance.json").read_text("utf-8"))["msg_id"] == "m1"
    assert len(out["files"]) == 4 and len(set(n.lower() for n in out["files"])) == 4
    assert sorted((inbox / n).read_bytes() for n in out["files"]) == [
        b"evil", b"evil", b"one", b"two"]


@pytest.mark.parametrize("bad", ["m\n", "m1\n"])
def test_msg_id_fullmatch(tmp_path, bad):
    with pytest.raises(ValueError):
        store_incoming(_hcfg(tmp_path), "node1", {"id": bad, "body": ""}, FakeClient({}))


@pytest.mark.parametrize("bad", ["CONIN$", "conout$", "COM¹", "lpt².txt", "COM³"])
def test_more_reserved_names(bad):
    from rb_host.store import valid_remote_name
    assert not valid_remote_name(bad)


def test_empty_non_eof_chunks_do_not_spin(tmp_path):
    script = tmp_path / "empty.py"
    script.write_text(textwrap.dedent("""
        import sys
        from rb_node.protocol import encode, read_message
        while True:
            msg = read_message(sys.stdin.buffer)
            if msg is None:
                break
            res = {"data_b64": "", "eof": False}
            sys.stdout.buffer.write(encode({"id": msg["id"], "ok": True, "result": res}))
            sys.stdout.buffer.flush()
    """), encoding="utf-8")
    env = {"PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    dest = tmp_path / "dl" / "x.bin"
    with NodeClient("x", ssh_argv=[sys.executable, str(script)], env=env) as c:
        with pytest.raises(RemoteError) as ei:
            c.get_file("doc", "x.bin", dest)
    assert ei.value.code == "stalled"
    assert list(dest.parent.iterdir()) == []


def test_index_rename_cannot_collide(tmp_path):
    names = ["2-a.txt", "a.txt", "a.txt"]
    item = {"id": "m2", "body": "", "attachments": [{"name": n} for n in names]}
    cl = FakeClient({"2-a.txt": b"first", "a.txt": b"dup"})
    out = store_incoming(_hcfg(tmp_path), "node1", item, cl)
    inbox = tmp_path / "data" / "inbox" / "node1" / "m2"
    assert len(set(n.lower() for n in out["files"])) == 3
    assert (inbox / "2-a.txt").read_bytes() == b"first"
    assert sorted((inbox / n).read_bytes() for n in out["files"]) == [b"dup", b"dup", b"first"]


def test_poll_survives_oserror_item(tmp_path, monkeypatch):
    from rb_host import server
    from rb_host import store as st
    from rb_host.ledger import Ledger
    cfg = _hcfg(tmp_path)

    class C:
        acked = []

        def call(self, op, **kw):
            if op == "poll":
                return {"items": [{"id": "bad", "body": ""}, {"id": "good", "body": "b"}]}
            self.acked += kw["ids"]
            return {}
    real = st.store_incoming

    def flaky(cfg_, node, it, c):
        if it["id"] == "bad":
            raise OSError("name too long")
        return real(cfg_, node, it, c)
    monkeypatch.setattr(server, "store_incoming", flaky)
    monkeypatch.setattr(server, "ledger_for", lambda c: Ledger(tmp_path / "l.jsonl"))
    c = C()
    monkeypatch.setattr(server, "_run", lambda node, fn: fn(c))
    r = server._poll_node(cfg, "node1")
    assert [i["msg_id"] for i in r["items"]] == ["good"] and r["rejected"] == 1
    assert c.acked == ["good"]


# -- sync-and-page: stage directories and outbox -------------------------------------------
def _wh_file(tmp_path, patterns):
    p = tmp_path / "wh.json"
    p.write_text(json.dumps({"patterns": patterns, "name_patterns": patterns}), encoding="utf-8")
    return p


def _wcfg(tmp_path, patterns=("secretfam_",)):
    return HostConfig(nodes={"n1": {"alias": "a"}}, data_root=str(tmp_path / "data"),
                      withheld_patterns_file=str(_wh_file(tmp_path, list(patterns))))


def test_stage_dir_unique_per_process(tmp_path, monkeypatch):
    import os
    cfg = _hcfg(tmp_path)
    parents = []

    class C(FakeClient):
        def get_file(self, kind, ref, dest):
            parents.append(Path(dest).parent.name)
            return super().get_file(kind, ref, dest)
    for pid in (111, 222):
        monkeypatch.setattr(os, "getpid", lambda pid=pid: pid)
        store_incoming(cfg, "node1", {"id": "m%d" % pid, "body": "", "attachments": [{"name": "a.txt"}]},
                       C({"a.txt": b"x"}))
    assert parents[0].startswith(".stage-111-") and parents[1].startswith(".stage-222-")
    assert parents[0] != parents[1]
    quar = tmp_path / "data" / "quarantine"
    assert not list(quar.rglob(".stage*"))
    assert not list(quar.glob("node1/*"))  # empty quarantine/<node>/<id> removed


@pytest.mark.parametrize("bad", ["../x", "a/b", "CON", ""])
def test_store_outgoing_rejects_unsafe_id(tmp_path, bad):
    from rb_host.store import store_outgoing
    cfg = _wcfg(tmp_path)
    with pytest.raises(ValueError):
        store_outgoing(cfg, "n1", bad, "b", [])
    assert not (tmp_path / "data" / "outbox").exists() or _files(tmp_path / "data") == []
    assert not (tmp_path / "x").exists()


def test_store_outgoing_masks_and_records(tmp_path):
    import hashlib
    from rb_host.store import store_outgoing
    cfg = _wcfg(tmp_path)
    att = tmp_path / "a.txt"
    att.write_bytes(b"hello")
    out = store_outgoing(cfg, "n1", "m1", "ok\nsecretfam_1\nend", [att])
    d = tmp_path / "data" / "outbox" / "n1" / "m1"
    assert (d / "body.txt").read_text(encoding="utf-8") == "ok\n\nend"
    prov = json.loads((d / "provenance.json").read_text(encoding="utf-8"))
    assert prov["body_withheld_lines"] == 1 and out["body_withheld_lines"] == 1
    assert prov["attachments"] == [{"index": 0, "name": "a.txt", "bytes": 5,
                                    "sha256": hashlib.sha256(b"hello").hexdigest()}]
    assert prov["node"] == "n1" and prov["msg_id"] == "m1" and prov["body_chars"] == 18
    assert out["dir"] == str(d)
    assert not (d / "a.txt").exists()  # attachments are not copied
    assert not list(d.glob("*.tmp")) and not list(d.glob("*.part"))


def test_store_outgoing_retry_same_body_ok_different_body_refused(tmp_path):
    from rb_host.store import store_outgoing
    cfg = _wcfg(tmp_path)
    store_outgoing(cfg, "n1", "m1", "one", [])
    d = tmp_path / "data" / "outbox" / "n1" / "m1"
    first = (d / "provenance.json").read_text(encoding="utf-8")
    store_outgoing(cfg, "n1", "m1", "one", [])
    assert (d / "provenance.json").read_text(encoding="utf-8") == first
    with pytest.raises(ValueError, match="different body"):
        store_outgoing(cfg, "n1", "m1", "two", [])
    assert (d / "body.txt").read_text(encoding="utf-8") == "one"


def test_store_outgoing_masks_attachment_name(tmp_path):
    import hashlib
    from rb_host.store import store_outgoing
    cfg = _wcfg(tmp_path)
    att = tmp_path / "secretfam_a.txt"
    att.write_bytes(b"zz")
    store_outgoing(cfg, "n1", "m1", "b", [att])
    prov = json.loads((tmp_path / "data" / "outbox" / "n1" / "m1" / "provenance.json")
                      .read_text(encoding="utf-8"))
    assert prov["attachments"][0]["name"] == "(withheld)"
    assert prov["attachments"][0]["sha256"] == hashlib.sha256(b"zz").hexdigest()


def test_store_outgoing_unknown_node(tmp_path):
    from rb_host.store import store_outgoing
    with pytest.raises(ValueError, match="unknown node"):
        store_outgoing(_wcfg(tmp_path), "zz", "m1", "b", [])


def test_sweep_removes_old_stage_dirs_only(tmp_path):
    import os
    import time
    from rb_host.store import sweep_stage_dirs
    cfg = _wcfg(tmp_path)
    base = tmp_path / "data" / "quarantine" / "n1"
    old = base / "old1" / ".stage-1-aaaa"
    fresh = base / "new1" / ".stage-2-bbbb"
    old.mkdir(parents=True)
    fresh.mkdir(parents=True)
    t = time.time() - 7200
    os.utime(str(old), (t, t))
    assert sweep_stage_dirs(cfg, "n1") == 1
    assert not old.exists() and not old.parent.exists()
    assert fresh.exists()
    assert sweep_stage_dirs(cfg, "n1", now_s=time.time() + 7200) == 1
    assert sweep_stage_dirs(cfg, "n1") == 0
