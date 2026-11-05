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
