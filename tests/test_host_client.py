from __future__ import annotations

import hashlib
import json
import os
import sys
import textwrap
from pathlib import Path

import pytest

from rb_host.client import AgentLockedError, NodeClient, RemoteError, TransportError
from rb_host.config import HostConfig
from rb_host.store import store_incoming
from rb_node.protocol import CHUNK

SERVE = [sys.executable, "-m", "rb_node.cli", "serve-remote"]


@pytest.fixture
def node(tmp_path):
    trm = tmp_path / "trm"
    for d in ("lab/experiments", "lab/registry", "lab/reports", "reports/figures",
              "scripts/queue/jobs"):
        (trm / d).mkdir(parents=True)
    mb = tmp_path / "rb" / "mailbox"
    conf = {
        "trm_root": str(trm),
        "read_roots": ["lab/registry", "lab/experiments", "lab/reports", "reports/figures",
                       str(mb / "out")],
        "write_roots": [str(mb / "in"), str(trm / "scripts" / "queue" / "jobs")],
        "queue_dir": str(trm / "scripts" / "queue"),
        "withheld_source": None,
        "claude_bin": str(tmp_path / "no-such-claude"),
        "mailbox_root": str(mb),
        "audit_path": str(tmp_path / "rb" / "audit.jsonl"),
    }
    cfgp = tmp_path / "node.json"
    cfgp.write_text(json.dumps(conf), encoding="utf-8")
    env = {"RB_NODE_CONFIG": str(cfgp), "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    return {"trm": trm, "mb": mb, "env": env, "cfgp": cfgp, "tmp": tmp_path}


def test_call_and_remote_error(node):
    with NodeClient("x", ssh_argv=SERVE, env=node["env"]) as c:
        assert "version" in c.call("hello")
        with pytest.raises(RemoteError) as ei:
            c.call("no_such_op")
        assert ei.value.code == "unknown_op"


def test_put_file_commit_visible_on_node(node, tmp_path):
    src = tmp_path / "my file 한글.txt"
    data = os.urandom(CHUNK + 123)
    src.write_bytes(data)
    with NodeClient("x", ssh_argv=SERVE, env=node["env"]) as c:
        stored = c.put_file("job-abc", src)
        again = c.put_file("job-abc", src)  # retry with the same msg_id is safe
    assert again == stored
    f = node["mb"] / "in" / "job-abc" / "attachments" / stored
    assert f.is_file() and f.read_bytes() == data
    assert not list(f.parent.glob("*.part"))
    assert "/" not in stored and "\\" not in stored


def test_get_file_roundtrip(node, tmp_path):
    data = os.urandom(CHUNK * 2 + 5)
    (node["trm"] / "reports" / "figures" / "big.png").write_bytes(data)
    dest = tmp_path / "dl" / "big.png"
    with NodeClient("x", ssh_argv=SERVE, env=node["env"]) as c:
        sha = c.get_file("doc", "reports/figures/big.png", dest)
    assert sha == hashlib.sha256(data).hexdigest()
    assert dest.read_bytes() == data
    assert not dest.with_suffix(".png.part").exists()


def _killer(tmp_path):
    """ssh stand-in: serves the node in-process, then dies after the first get_file reply."""
    script = tmp_path / "killer.py"
    script.write_text(textwrap.dedent("""
        import os, sys
        from rb_node.config import load_config
        from rb_node.protocol import encode, read_message
        from rb_node.remote import Node
        node = Node(load_config())
        while True:
            msg = read_message(sys.stdin.buffer)
            if msg is None:
                break
            sys.stdout.buffer.write(encode(node.handle(msg)))
            sys.stdout.buffer.flush()
            if msg.get("op") == "get_file":
                os._exit(7)
    """), encoding="utf-8")
    return [sys.executable, str(script)]


def test_get_file_killed_mid_transfer(node, tmp_path):
    (node["trm"] / "reports" / "figures" / "big.png").write_bytes(os.urandom(CHUNK * 2 + 5))
    dest = tmp_path / "dl" / "big.png"
    with NodeClient("x", ssh_argv=_killer(tmp_path), env=node["env"]) as c:
        with pytest.raises(TransportError):
            c.get_file("doc", "reports/figures/big.png", dest)
    assert not dest.exists()
    assert [p.name for p in dest.parent.iterdir() if not p.name.endswith(".part")] == []
    # retry over a healthy connection succeeds and promotes only after verification
    with NodeClient("x", ssh_argv=SERVE, env=node["env"]) as c:
        c.get_file("doc", "reports/figures/big.png", dest)
    assert dest.is_file()


def test_agent_locked(tmp_path):
    script = tmp_path / "fakessh.py"
    script.write_text(
        "import sys\nsys.stderr.write('x@h: Permission denied (publickey).\\n')\nsys.exit(255)\n",
        encoding="utf-8")
    with NodeClient("x", ssh_argv=[sys.executable, str(script)]) as c:
        with pytest.raises(AgentLockedError):
            c.call("hello")
    assert issubclass(AgentLockedError, TransportError)


def test_other_exit_is_transport_error(tmp_path):
    script = tmp_path / "fakessh2.py"
    script.write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
    with NodeClient("x", ssh_argv=[sys.executable, str(script)]) as c:
        with pytest.raises(TransportError) as ei:
            c.call("hello")
    assert not isinstance(ei.value, AgentLockedError)


def test_default_argv():
    from rb_host.client import default_argv
    assert default_argv("rb-node1") == ["ssh", "-o", "BatchMode=yes", "-o",
                                         "ConnectTimeout=15", "rb-node1"]


def test_unknown_alias():
    cfg = HostConfig(nodes={"node1": {"alias": "rb-node1"}})
    assert cfg.alias("node1") == "rb-node1"
    with pytest.raises(ValueError):
        cfg.alias("nope")


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
        return hashlib.sha256(self.files[name]).hexdigest()


def _hcfg(tmp_path):
    return HostConfig(nodes={"node1": {"alias": "a"}}, data_root=str(tmp_path / "data"),
                      withheld_patterns_file=str(tmp_path / "none.json"))


def test_store_incoming_quarantines_withheld(tmp_path):
    cfg = _hcfg(tmp_path)
    item = {"id": "m1", "kind": "reply", "reply_to": "q", "body": "ok line\nsee pp_ltf_x here\nend",
            "attachments": [{"name": "pp_ltf_fig.png", "original": "pp_ltf_fig.png"},
                            {"name": "good.txt", "original": "good.txt"},
                            {"name": "leak.md", "original": "leak.md"}]}
    cl = FakeClient({"pp_ltf_fig.png": b"png", "good.txt": b"fine",
                     "leak.md": b"line\nH108N number\n"})
    out = store_incoming(cfg, "node1", item, cl)
    data = tmp_path / "data"
    assert (data / "quarantine" / "node1" / "m1" / "pp_ltf_fig.png").is_file()
    assert (data / "quarantine" / "node1" / "m1" / "leak.md").is_file()
    assert (data / "inbox" / "node1" / "m1" / "good.txt").is_file()
    assert not (data / "inbox" / "node1" / "m1" / "pp_ltf_fig.png").exists()
    assert not (data / "inbox" / "node1" / "m1" / "leak.md").exists()
    assert not (data / "quarantine" / "node1" / "m1" / ".stage").exists()
    assert "pp_ltf_x" not in out["body"] and "ok line" in out["body"]
    prov_text = (data / "inbox" / "node1" / "m1" / "provenance.json").read_text(encoding="utf-8")
    prov = json.loads(prov_text)
    assert prov["node"] == "node1" and prov["msg_id"] == "m1" and prov["received_at"]
    assert "pp_ltf" not in prov_text and "H108N" not in prov_text
    ok = [f for f in prov["files"] if f["status"] == "ok"]
    assert ok[0]["sha256"] == hashlib.sha256(b"fine").hexdigest() and ok[0]["bytes"] == 4
    assert sum(1 for f in prov["files"] if f["status"] == "quarantined") == 2
    assert out["quarantined"] == 2


def test_store_incoming_node_denied(tmp_path):
    cfg = _hcfg(tmp_path)

    class Denier:
        def get_file(self, kind, ref, dest):
            raise RemoteError("denied", "denied")
    item = {"id": "m2", "body": "", "attachments": [{"name": "pp_ltf_a.png"}]}
    out = store_incoming(cfg, "node1", item, Denier())
    assert out["quarantined"] == 1
    assert not list((tmp_path / "data" / "inbox" / "node1" / "m2").glob("*.png"))
