"""rb sync: one reliable pass per node and the status file (design 2026-11-10 §6.2, §6.3).
Local subprocess node only; jobs.connect is never the real one."""
from __future__ import annotations

import io
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from rb_host import board, cli, jobs, server, sync
from rb_host.client import NodeClient, RemoteError, TransportError
from rb_host.ledger import Ledger
from rb_node.mailbox import Mailbox

SERVE = [sys.executable, "-m", "rb_node.cli", "serve-remote"]
REPO = Path(__file__).resolve().parents[1]
STATE_MD = "---\nphase: S5\ntrack: ARG\nupdated: 2026-11-02\n---\n# State\n"
KEYS = {"schema", "node", "last_attempt_at", "last_ok_at", "ok", "error", "stage", "new_items",
        "rejected", "board", "node_version", "protocol", "withheld_extra", "node_seen_at",
        "tree_head", "tree_dirty", "git_error", "duration_s"}
ALIAS = "ssh-alias-marker"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """No test here reads the developer's host.json or opens an SSH connection."""
    monkeypatch.setenv("RB_HOST_CONFIG", str(tmp_path / "host.json"))
    monkeypatch.setenv("RB_HOST_ROOT", str(tmp_path / "root"))

    def refuse(cfg, node):
        raise AssertionError("jobs.connect used without the local node")
    monkeypatch.setattr(jobs, "connect", refuse)


class Rec:
    """Client proxy: records (connection, op) and lets a test replace one op."""

    def __init__(self, inner, n, env):
        self.inner, self.n, self.env = inner, n, env

    def __enter__(self):
        self.inner.__enter__()
        return self

    def __exit__(self, *a):
        return self.inner.__exit__(*a)

    def call(self, op, **kw):
        self.env["log"].append((self.n, op))
        hook = self.env["hooks"].get(op)
        if hook is not None:
            return hook(lambda: self.inner.call(op, **kw))
        return self.inner.call(op, **kw)

    def get_file(self, kind, ref, dest):
        self.env["log"].append((self.n, "get_file"))
        return self.inner.get_file(kind, ref, dest)


def _fake_smi(d, code=0):
    d.mkdir(parents=True, exist_ok=True)
    p = d / "nvidia-smi"
    p.write_text("#!/bin/sh\necho '0, Fake, 1, 2, 3'\necho '1, Fake, 4, 5, 6'\n" if code == 0
                 else "#!/bin/sh\nexit 1\n", encoding="ascii")
    p.chmod(0o755)


@pytest.fixture
def env(tmp_path, monkeypatch):
    trm = tmp_path / "trm"
    for d in ("lab/state", "lab/monitor", "scripts/queue/jobs"):
        (trm / d).mkdir(parents=True)
    (trm / "lab/state/STATE.md").write_text(STATE_MD, encoding="utf-8")
    (trm / "lab/monitor/events.json").write_text(
        json.dumps({"ts": "2026-11-02T09:00:00Z", "stage": "S5", "kind": "m", "track": "A"}) + "\n",
        encoding="utf-8")
    (trm / "lab/monitor/kanban.json").write_text(json.dumps({"cards": []}), encoding="utf-8")
    mb = tmp_path / "rb" / "mailbox"
    conf = {"trm_root": str(trm), "read_roots": ["lab/state", "lab/monitor", str(mb / "out")],
            "write_roots": [str(mb / "in")], "queue_dir": str(trm / "scripts" / "queue"),
            "withheld_source": None, "claude_bin": str(tmp_path / "no-such-claude"),
            "mailbox_root": str(mb), "audit_path": str(tmp_path / "rb" / "audit.jsonl")}
    nodecfg = tmp_path / "node.json"
    nodecfg.write_text(json.dumps(conf), encoding="utf-8")
    wp = tmp_path / "withheld.json"
    wp.write_text(json.dumps({"patterns": []}), encoding="utf-8")
    root = tmp_path / "data"
    _fake_smi(tmp_path / "bin")
    nenv = {"RB_NODE_CONFIG": str(nodecfg), "PYTHONPATH": str(REPO),
            "PATH": str(tmp_path / "bin") + os.pathsep + os.environ.get("PATH", "")}
    e = {"tmp": tmp_path, "root": root, "mb": mb, "nenv": nenv, "log": [], "hooks": {},
         "conns": 0, "wp": wp, "host": tmp_path / "host.json", "nodecfg": nodecfg}

    def write_host(paths=None, extra_nodes=()):
        node = {"alias": ALIAS}
        if paths:
            node["board"] = paths
        nodes = {"n1": node}
        for n in extra_nodes:
            nodes[n] = {"alias": "other-alias"}
        e["host"].write_text(json.dumps({"nodes": nodes, "data_root": str(root),
                                         "withheld_patterns_file": str(wp)}), encoding="utf-8")
        return jobs.load_cfg()

    def connect(cfg, node):
        e["conns"] += 1
        return Rec(NodeClient(ALIAS, ssh_argv=SERVE, env=nenv), e["conns"], e)

    e["write_host"] = write_host
    e["cfg"] = write_host()
    monkeypatch.setattr(jobs, "connect", connect)
    e["connect"] = connect
    return e


def _status(env, node="n1"):
    return json.loads((env["root"] / "sync" / ("%s.json" % node)).read_text(encoding="utf-8"))


def _reply(env, body="answer"):
    return Mailbox(env["mb"]).post_out("reply", body, [], "m0")


def _clock(monkeypatch):
    t = {"n": 0}

    def fake_now():
        t["n"] += 10
        return "2026-11-10T00:%02d:%02dZ" % (t["n"] // 60 % 60, t["n"] % 60)
    monkeypatch.setattr(jobs, "now", fake_now)


# -- pass order, status file --------------------------------------------------------------
def test_pass_order_on_one_connection(env):
    cfg = env["write_host"](
        {"state": "lab/state/STATE.md", "events": "lab/monitor/events.json",
         "kanban": "lab/monitor/kanban.json"})
    board.refresh(cfg, "n1", ["state", "events", "kanban"])
    _reply(env)
    env["log"].clear()
    env["conns"] = 0
    st = sync.run_pass(cfg, "n1")
    assert st["ok"] is True, st
    first = [op for n, op in env["log"] if n == 1]
    assert first == ["hello", "poll", "ack", "git_status"]
    assert env["conns"] == 3
    assert sorted(op for n, op in env["log"] if n > 1) == ["gpu_status", "queue_status"]


def test_status_file_fields_and_atomic_write(env):
    _reply(env)
    st = sync.run_pass(env["cfg"], "n1")
    got = _status(env)
    assert set(got) == KEYS and got == st
    assert got["ok"] is True and got["new_items"] == 1 and got["error"] is None
    assert got["stage"] is None and got["schema"] == 1 and got["node"] == "n1"
    assert got["board"]["queue"] == "ok" and got["board"]["state"] == "no_path"
    d = env["root"] / "sync"
    assert [p.name for p in d.iterdir()] == ["n1.json"]
    assert stat.S_IMODE((d / "n1.json").stat().st_mode) == 0o600


def test_status_file_has_no_body_or_text(env, capsys):
    _reply(env, "MARKER-REPLY-91c2")
    assert sync.run(None, 0) == 0
    out = capsys.readouterr()
    text = (env["root"] / "sync" / "n1.json").read_text(encoding="utf-8")
    for blob in (text, out.out):
        assert "MARKER-REPLY-91c2" not in blob and ALIAS not in blob
    assert len(out.out.strip().splitlines()) == 1
    line = json.loads(out.out)
    assert line["node"] == "n1" and line["ok"] is True and "tree_head" in line


def test_cli_sync_prints_one_line_without_text(env, capsys):
    _reply(env, "MARKER-REPLY-5d1e")
    assert cli.main(["sync", "--node", "n1"]) == 0
    out = capsys.readouterr()
    assert len(out.out.strip().splitlines()) == 1
    assert json.loads(out.out)["new_items"] == 1
    for blob in (out.out, out.err):
        assert "MARKER-REPLY-5d1e" not in blob and ALIAS not in blob


def test_sync_stores_with_delivered_false(env):
    oid = _reply(env)
    sync.run_pass(env["cfg"], "n1")
    rec = Ledger(env["root"] / "ledger.jsonl").get(oid)
    assert rec["delivered"] is False and "delivered_at" not in rec
    assert (env["mb"] / "state" / "acked" / oid).exists()


# -- failures -----------------------------------------------------------------------------
def test_poll_error_fails_pass(env, capsys):
    def boom(real):
        raise RemoteError("internal")
    env["hooks"]["poll"] = boom
    assert sync.run(None, 0) == 1
    st = _status(env)
    assert st["ok"] is False and st["error"] == "internal" and st["stage"] == "poll"
    assert not (env["root"] / "board").exists()  # board not refreshed
    assert ("n1" in capsys.readouterr().out)


def test_board_failure_fails_pass_except_no_path(env):
    cfg = env["write_host"]({"state": "lab/state/MISSING.md"})
    st = sync.run_pass(cfg, "n1")
    assert st["ok"] is False and st["stage"] == "board" and st["error"] == "not_found"
    assert st["board"]["state"] == "not_found"
    cfg = env["write_host"]()
    assert sync.run_pass(cfg, "n1")["ok"] is True


def test_transport_error_without_code_attribute(env, monkeypatch):
    class NoCode(Exception):
        pass

    class Stub(TransportError):  # no `code` under either TransportError definition
        def __init__(self, msg):
            Exception.__init__(self, msg)
    monkeypatch.delattr(TransportError, "code", raising=False)

    def bad(cfg, node):
        env["conns"] += 1
        raise Stub("connection to ssh-alias-marker closed (exit 255)")
    monkeypatch.setattr(jobs, "connect", bad)
    st = sync.run_pass(env["cfg"], "n1")
    assert st["error"] == "transport" and st["stage"] == "connect"
    assert "ssh-alias-marker" not in (env["root"] / "sync" / "n1.json").read_text()
    assert env["conns"] == 1
    assert sync.error_code(NoCode()) == "internal"
    assert sync.error_code(NoCode("x")) != "transport"


def test_transport_error_code_attribute_used(env, monkeypatch):
    exc = TransportError("text")
    exc.code = "agent_empty"

    def bad(cfg, node):
        raise exc
    monkeypatch.setattr(jobs, "connect", bad)
    st = sync.run_pass(env["cfg"], "n1")
    assert st["error"] == "agent_empty" and st["stage"] == "connect"


def test_old_node_hello_and_git_status_give_nulls(env):
    env["hooks"]["hello"] = lambda real: {k: v for k, v in real().items()
                                           if k in ("node", "version", "withheld_extra")}

    def nogit(real):
        raise RemoteError("unknown_op")
    env["hooks"]["git_status"] = nogit
    st = sync.run_pass(env["cfg"], "n1")
    assert st["ok"] is True, st
    assert st["protocol"] == 1 and st["tree_head"] is None and st["git_error"] == "unknown_op"
    assert st["node_version"]


def test_git_status_tree_key_and_trm_fallback(env):
    env["hooks"]["git_status"] = lambda real: {"tree": {"head": "abc123", "dirty_files": 2}}
    st = sync.run_pass(env["cfg"], "n1")
    assert st["tree_head"] == "abc123" and st["tree_dirty"] == 2 and st["git_error"] is None
    env["hooks"]["git_status"] = lambda real: {"trm": {"head": "def456", "dirty_files": 0}}
    st = sync.run_pass(env["cfg"], "n1")
    assert st["tree_head"] == "def456" and st["tree_dirty"] == 0
    env["hooks"]["git_status"] = lambda real: {"research": {"head": "zzz", "dirty_files": 9}}
    assert sync.run_pass(env["cfg"], "n1")["tree_head"] is None


def test_failed_pass_keeps_last_ok_at(env, monkeypatch):
    _clock(monkeypatch)
    first = sync.run_pass(env["cfg"], "n1")
    assert first["ok"] and first["last_ok_at"]

    def bad(cfg, node):
        raise TransportError("down")
    monkeypatch.setattr(jobs, "connect", bad)
    second = sync.run_pass(env["cfg"], "n1")
    assert second["ok"] is False and second["last_ok_at"] == first["last_ok_at"]
    assert second["last_attempt_at"] > first["last_attempt_at"]
    for k in ("node_version", "protocol", "withheld_extra", "node_seen_at", "tree_head", "board"):
        assert second[k] == first[k], k


def test_board_exception_is_board_failure(env, monkeypatch):
    def boom(cfg, node, sources=None):
        raise FileNotFoundError("x.part")
    monkeypatch.setattr(board, "refresh", boom)
    st = sync.run_pass(env["cfg"], "n1")
    assert st["ok"] is False and st["stage"] == "board" and st["error"] == "os_error"


def test_due_sources(env):
    cfg = env["write_host"]({"state": "lab/state/STATE.md", "events": "lab/monitor/events.json",
                             "kanban": "lab/monitor/kanban.json"})
    board.refresh(cfg, "n1")
    assert sync.due_sources(cfg, "n1") == []
    p = env["root"] / "board" / "n1_state.json"
    rec = json.loads(p.read_text(encoding="utf-8"))
    p.write_text(json.dumps(dict(rec, fetched_at="2020-01-01T00:00:00Z")), encoding="utf-8")
    assert sync.due_sources(cfg, "n1") == ["state"]
    p.write_text(json.dumps(rec), encoding="utf-8")
    q = env["root"] / "board" / "n1_queue.json"
    q.write_text(json.dumps(dict(json.loads(q.read_text(encoding="utf-8")), ok=False)),
                 encoding="utf-8")
    assert sync.due_sources(cfg, "n1") == ["queue"]
    (env["root"] / "board" / "n1_gpu.json").unlink()
    assert sync.due_sources(cfg, "n1") == ["queue", "gpu"]
    (env["root"] / "board" / "n1_events.json").write_text("{not json", encoding="utf-8")
    assert sync.due_sources(cfg, "n1") == ["queue", "gpu", "events"]


def test_due_sources_without_paths(env):
    cfg = env["cfg"]
    assert sync.due_sources(cfg, "n1") == ["queue", "gpu"]
    st = sync.run_pass(cfg, "n1")
    assert st["ok"] is True
    assert {k: st["board"][k] for k in ("state", "events", "kanban")} == {
        "state": "no_path", "events": "no_path", "kanban": "no_path"}
    assert st["board"]["queue"] == "ok" and st["board"]["gpu"] == "ok"
    names = {p.name for p in (env["root"] / "board").iterdir()}
    assert names == {"n1_queue.json", "n1_gpu.json", "audit.jsonl"}
    audit = (env["root"] / "board" / "audit.jsonl").read_text(encoding="utf-8")
    assert "state" not in audit and "kanban" not in audit
    st2 = sync.run_pass(cfg, "n1")  # caches fresh now
    assert st2["board"]["queue"] == "skipped" and st2["board"]["state"] == "no_path"


def test_missing_host_json_one_line_error(tmp_path, capsys):
    assert cli.main(["sync"]) == 1
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1 and out[0].startswith("error: no usable host.json at ")
    assert "Traceback" not in out[0]


def test_watch_survives_failed_pass(env, monkeypatch, capsys):
    def bad(cfg, node):
        raise TransportError("down")
    monkeypatch.setattr(jobs, "connect", bad)
    rc = sync.run(None, 30, sleep=lambda s: None, max_passes=2)
    assert rc == 1
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 2 and all(json.loads(x)["ok"] is False for x in lines)


def test_watch_minimum(monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("must not be called")
    monkeypatch.setattr(jobs, "load_cfg", boom)
    monkeypatch.setattr(jobs, "connect", boom)
    assert cli.main(["sync", "--watch", "5"]) == 1
    assert "at least 30" in capsys.readouterr().out


def test_provisional_status_written_first(env, monkeypatch):
    seen = {}

    def reader(cfg, node):
        seen["file"] = _status(env)
        raise TransportError("down")
    monkeypatch.setattr(jobs, "connect", reader)
    final = sync.run_pass(env["cfg"], "n1")
    assert seen["file"]["stage"] == "running" and seen["file"]["error"] == "incomplete"
    assert seen["file"]["ok"] is False
    assert seen["file"]["last_attempt_at"] == final["last_attempt_at"]
    assert _status(env)["stage"] == "connect"


def test_gpu_unavailable_is_recorded_without_failing_pass(env):
    """Coordinator ruling R8: gpu_status_unavailable is recorded, it does not fail the pass."""
    _fake_smi(env["tmp"] / "bin", code=1)
    st = sync.run_pass(env["cfg"], "n1")
    assert st["board"]["gpu"] == "gpu_status_unavailable" and st["ok"] is True


def test_non_code_board_error_becomes_source_error(env, monkeypatch):
    monkeypatch.setattr(server, "queue_status",
                        lambda node: {"error": "connection to x closed"})
    st = sync.run_pass(env["cfg"], "n1")
    assert st["board"]["queue"] == "source_error"
    assert st["ok"] is False and st["stage"] == "board" and st["error"] == "source_error"
    assert "connection to x" not in (env["root"] / "sync" / "n1.json").read_text()


def test_board_code_and_error_code_units():
    assert sync.board_code("not_found") == "not_found"
    assert sync.board_code("nvidia-smi failed") == "gpu_status_unavailable"
    assert sync.board_code("nvidia-smi not found") == "gpu_status_unavailable"
    assert sync.board_code("Some text here") == "source_error"
    assert sync.error_code(TimeoutError("x")) == "ledger_locked"
    assert sync.error_code(OSError("x")) == "os_error"
    assert sync.error_code(ValueError("x")) == "internal"
    assert sync.error_code(RemoteError("denied")) == "denied"
    assert sync.error_code(RemoteError("x" * 50)) == "invalid_code"


def test_invalid_node_code_replaced(env):
    text = "Bad Code: private text"

    def bad_git(real):
        raise RemoteError(text)
    env["hooks"]["git_status"] = bad_git
    st = sync.run_pass(env["cfg"], "n1")
    assert st["git_error"] == "invalid_code" and st["ok"] is True
    env["hooks"].clear()

    def bad_poll(real):
        raise RemoteError("x" * 50)
    env["hooks"]["poll"] = bad_poll
    st = sync.run_pass(env["cfg"], "n1")
    assert st["error"] == "invalid_code" and st["stage"] == "poll"
    blob = (env["root"] / "sync" / "n1.json").read_text()
    assert text not in blob and "x" * 50 not in blob


def test_unexpected_exception_is_internal(env, capsys):
    env["write_host"](extra_nodes=("n2",))
    env["hooks"]["hello"] = lambda real: ["not", "a", "dict"]
    assert sync.run(None, 0) == 1
    cap = capsys.readouterr()
    assert [json.loads(x)["node"] for x in cap.out.strip().splitlines()] == ["n1", "n2"]
    st = _status(env)
    assert st["error"] == "internal" and st["stage"] == "hello"
    assert "AttributeError" in cap.err
    assert _status(env, "n2")["stage"] == "hello"  # the next node was still processed


def test_stage_sweep_runs_before_connect(env, monkeypatch):
    called = []
    from rb_host import store
    monkeypatch.setattr(store, "sweep_stage_dirs", lambda cfg, node: called.append(node) or 0)
    sync.run_pass(env["cfg"], "n1")
    assert called == ["n1"]


def test_run_host_json_nodes_not_a_mapping(env, capsys):
    env["host"].write_text(json.dumps({"nodes": ["n1"], "data_root": str(env["root"])}),
                           encoding="utf-8")
    assert sync.run(None, 0) == 1  # a failed pass is reported, not a traceback
    assert '"ok": false' in capsys.readouterr().out


def test_run_host_json_unreadable(env, capsys):
    env["host"].unlink()
    env["host"].mkdir()  # exists but cannot be read as a file
    assert sync.run(None, 0) == 1
    assert capsys.readouterr().out.startswith("error:")


def test_run_no_nodes_configured_fails(env, capsys):
    env["host"].write_text(json.dumps({"nodes": {}, "data_root": str(env["root"])}),
                           encoding="utf-8")
    assert sync.run(None, 0) == 1
    out = capsys.readouterr().out
    assert out.startswith("error:") and "no nodes" in out


def test_run_pass_survives_bad_status_read(env, monkeypatch):
    def boom(cfg, node):
        raise AttributeError("x")
    monkeypatch.setattr(sync, "read_status", boom)
    st = sync.run_pass(env["cfg"], "n1")  # must not raise
    assert isinstance(st, dict)


# -- old node (protocol 1) stand-in -------------------------------------------------------
def _use_old_node(env, monkeypatch):
    from oldnode import SERVE_OLD

    def connect(cfg, node):
        env["conns"] += 1
        return Rec(NodeClient(ALIAS, ssh_argv=SERVE_OLD, env=env["nenv"]), env["conns"], env)
    monkeypatch.setattr(jobs, "connect", connect)


def test_old_node_stand_in_answers_like_the_old_node(env):
    from oldnode import SERVE_OLD
    with NodeClient(ALIAS, ssh_argv=SERVE_OLD, env=env["nenv"]) as c:
        assert set(c.call("hello")) == {"node", "version", "withheld_extra"}
        with pytest.raises(RemoteError) as ei:
            c.call("no_such_op")
        assert ei.value.code == "unknown_op"


def test_sync_pass_against_old_node_records_protocol_1(env, monkeypatch):
    _use_old_node(env, monkeypatch)
    _reply(env)
    st = sync.run_pass(env["cfg"], "n1")
    assert st["ok"] is True, st
    got = _status(env)
    assert got["protocol"] == 1 and got["new_items"] == 1 and got["node_version"] == "0.1.0"


def test_mcp_nodes_after_old_node_pass(env, monkeypatch):
    _use_old_node(env, monkeypatch)
    sync.run_pass(env["cfg"], "n1")
    res = server.nodes()
    assert res["nodes"] == ["n1"]
    s = res["status"]["n1"]
    assert s["synced"] is True and s["ok"] is True and s["protocol"] == 1
