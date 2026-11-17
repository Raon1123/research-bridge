"""rb sync: one reliable pass per node and the status file (design 2026-11-10 §6.2, §6.3).
Local subprocess node only; jobs.connect is never the real one."""
from __future__ import annotations

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
        "rejected", "rejected_ids", "board", "node_version", "protocol", "withheld_extra", "node_seen_at",
        "hub_withheld_extra", "hub_withheld_rejected", "tree_head", "tree_dirty", "git_error", "duration_s",
        "sessions"}
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

    def put_files(self, *a, **kw):  # the upload's ops go through call() above
        return NodeClient.put_files(self, *a, **kw)


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
    assert first == ["hello", "poll", "ack", "git_status", "sessions"]  # sessions last
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
            self.message, self.hint = msg, ""  # str() works; only `code` is missing
    assert str(Stub("m")) == "m" and not hasattr(Stub("m"), "code")
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
    def boom(real):
        raise AttributeError("boom")
    env["hooks"]["hello"] = boom
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


@pytest.mark.parametrize("nodes", [["n1"], None])
def test_run_host_json_nodes_not_a_mapping(env, capsys, nodes):
    env["host"].write_text(json.dumps({"nodes": nodes, "data_root": str(env["root"])}),
                           encoding="utf-8")
    assert sync.run(None, 0) == 1  # a failed pass is reported, not a traceback
    assert "wrong types" in capsys.readouterr().out


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


# -- counts survive a failure; rejected ids are named ---------------------------------------
def test_failure_after_storing_keeps_the_counts(env):
    _reply(env, "one")
    _reply(env, "two")

    def bad_ack(real):
        raise RemoteError("io_error")
    env["hooks"]["ack"] = bad_ack
    st = sync.run_pass(env["cfg"], "n1")
    assert st["ok"] is False and st["stage"] == "poll" and st["error"] == "io_error"
    assert st["new_items"] == 2 and _status(env)["new_items"] == 2


def test_clashing_inbound_id_is_named_in_status_and_line(env, capsys):
    from rb_host import server as srv
    mid = srv.send_message("n1", "question")["msg_id"]
    env["hooks"]["poll"] = lambda real: {"items": [
        {"id": mid, "kind": "reply", "body": "spoof", "reply_to": None, "attachments": []}]}
    st = sync.run_pass(env["cfg"], "n1")
    assert st["ok"] is True and st["rejected"] == 1 and st["rejected_ids"] == [mid]
    assert _status(env)["rejected_ids"] == [mid]
    assert sync.run(None, 0) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["rejected_ids"] == [mid]


def test_status_records_hub_pattern_file_state(env):
    env["wp"].write_text(json.dumps({"patterns": ["usable_one_", "(", "usable_two_"]}), encoding="utf-8")
    st = sync.run_pass(env["cfg"], "n1")
    assert st["hub_withheld_extra"] == 2 and st["hub_withheld_rejected"] == 1
    saved = json.loads(sync.status_path(env["cfg"], "n1").read_text(encoding="utf-8"))
    assert saved["hub_withheld_extra"] == 2 and saved["hub_withheld_rejected"] == 1
    env["wp"].unlink()  # missing file: no usable extra pattern, nothing rejected
    st = sync.run_pass(env["cfg"], "n1")
    assert st["hub_withheld_extra"] == 0 and st["hub_withheld_rejected"] == 0


# -- sessions (docs/design/2026-11-11-node-sessions.md §8, §9 step 3) ---------------------------
SID_A = "0a1b2c3d-0000-4000-8000-00000000000a"
SID_B = "0a1b2c3d-0000-4000-8000-00000000000b"


def _store(env, node="n1"):
    p = env["root"] / "sessions" / ("%s.json" % node)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _answer(sessions, **kw):
    a = {"days": 8, "now": "2026-11-11T09:00:00Z", "tree": "trm", "sessions": sessions,
         "outside": 1, "unparsed": 0, "files": 3, "truncated": False}
    a.update(kw)
    return a


def _sess(sid, start="2026-11-10T10:00:00Z", end="2026-11-10T11:00:00Z", days=None,
          label="lab/experiments"):
    return {"id": sid, "label": label, "start": start, "end": end,
            "days": {"2026-11-10": 600} if days is None else days}


def test_sessions_unsupported_when_hello_does_not_list_it(env):
    env["hooks"]["hello"] = lambda real: dict(real(), ops=[o for o in real()["ops"]
                                                          if o != "sessions"])
    st = sync.run_pass(env["cfg"], "n1")
    assert st["ok"] is True and st["sessions"] == "unsupported" and st["error"] is None
    assert "sessions" not in [op for _n, op in env["log"]]
    env["hooks"]["hello"] = lambda real: {k: v for k, v in real().items() if k != "ops"}
    st = sync.run_pass(env["cfg"], "n1")
    assert st["ok"] is True and st["sessions"] == "unsupported"
    assert "sessions" not in [op for _n, op in env["log"]] and _store(env) is None


def test_sessions_not_configured_on_the_node(env):
    st = sync.run_pass(env["cfg"], "n1")  # the local node has no sessions_dir
    assert st["ok"] is True and st["sessions"] == "not_configured"
    assert _status(env)["sessions"] == "not_configured" and _store(env) is None


def test_sessions_from_a_configured_node_are_stored(env):
    import time as _t
    sdir = env["tmp"] / "projects"
    rec = sdir / "proj" / (SID_A + ".jsonl")
    rec.parent.mkdir(parents=True)
    now = _t.time()
    lines = [{"timestamp": _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime(now - d)),
              "cwd": str(env["tmp"] / "trm" / "lab"), "message": {"content": "MARKER-T-4"}}
             for d in (120, 60)]
    rec.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    conf = json.loads(env["nodecfg"].read_text(encoding="utf-8"))
    conf["sessions_dir"] = str(sdir)
    env["nodecfg"].write_text(json.dumps(conf), encoding="utf-8")
    st = sync.run_pass(env["cfg"], "n1")
    assert st["ok"] is True and st["sessions"] == "ok"
    store = _store(env)
    assert store["ok"] is True and store["error"] is None and store["node"] == "n1"
    assert store["fetched_at"] == store["attempted_at"] and store["schema"] == 1
    assert set(store["sessions"]) == {SID_A} and store["sessions"][SID_A]["label"] == "lab"
    assert store["sessions"][SID_A]["days"] and store["skipped"] == 0
    assert "MARKER-T-4" not in json.dumps(store) and "MARKER-T-4" not in json.dumps(_status(env))
    d = env["root"] / "sessions"
    assert [p.name for p in d.iterdir()] == ["n1.json"]
    assert stat.S_IMODE((d / "n1.json").stat().st_mode) == 0o600


def test_sessions_merge_by_id(env, monkeypatch):
    _clock(monkeypatch)
    env["hooks"]["sessions"] = lambda real: _answer([
        _sess(SID_A, days={"2026-11-09": 300, "2026-11-10": 600}), _sess(SID_B)])
    assert sync.run_pass(env["cfg"], "n1")["sessions"] == "ok"
    first = _store(env)
    env["hooks"]["sessions"] = lambda real: _answer([
        _sess(SID_A, start="2026-11-10T10:30:00Z", end="2026-11-11T08:00:00Z",
              days={"2026-11-10": 500, "2026-11-11": 900}, label="lab/new")],
        outside=4, truncated=True)
    assert sync.run_pass(env["cfg"], "n1")["sessions"] == "ok"
    s = _store(env)
    a = s["sessions"][SID_A]
    assert a == {"label": "lab/new", "start": "2026-11-10T10:00:00Z",
                 "end": "2026-11-11T08:00:00Z",
                 "days": {"2026-11-09": 300, "2026-11-10": 600, "2026-11-11": 900}}
    assert s["sessions"][SID_B] == first["sessions"][SID_B]  # not in the answer: kept
    assert s["outside"] == 4 and s["truncated"] is True and s["fetched_at"] > first["fetched_at"]


def test_malformed_sessions_answer_is_checked_entry_by_entry(env):
    env["wp"].write_text(json.dumps({"patterns": ["unrelatedfam_"]}), encoding="utf-8")
    good = _sess(SID_A)
    bad = [_sess("../x"), _sess(SID_B.upper()), _sess(SID_B, start="yesterday"),
           _sess(SID_B, start="2026-11-11T00:00:00Z", end="2026-11-10T00:00:00Z"),
           _sess(SID_B, days={"2026-11-10": -5}), _sess(SID_B, days={"2026-11-10": True}),
           _sess(SID_B, days={"2026-11-10": 90000}), _sess(SID_B, days={"x": 5}),
           _sess(SID_B, days=[]),
           _sess(SID_B, label="lab\x1b[1m"), _sess(SID_B, label="unrelatedfam_run"),
           _sess(SID_B, label="x" * 121), _sess(SID_B, label=""), _sess(SID_B, label=5),
           "not an object", dict(good, id=7)]
    # a label with HTML-special characters is a legal directory name: kept as it is (the page
    # escapes it), not dropped
    html = _sess(SID_B, label="R&D/<b>lab's</b>")
    env["hooks"]["sessions"] = lambda real: _answer([good, html] + bad, outside="many",
                                                    tree="x\x1b[1m", truncated="yes")
    st = sync.run_pass(env["cfg"], "n1")
    assert st["ok"] is True and st["sessions"] == "ok"
    s = _store(env)
    assert set(s["sessions"]) == {SID_A, SID_B} and s["skipped"] == len(bad)
    assert s["sessions"][SID_B]["label"] == "R&D/<b>lab's</b>"
    assert s["outside"] == 0 and s["tree"] is None and s["truncated"] is False
    blob = json.dumps(s)
    for raw in ("unrelatedfam_", "\\u001b"):
        assert raw not in blob, raw


def test_sessions_file_counts_are_stored(env):
    env["hooks"]["sessions"] = lambda real: _answer([], ignored=2, deeper=3, shallower=1)
    assert sync.run_pass(env["cfg"], "n1")["sessions"] == "ok"
    s = _store(env)
    assert (s["ignored"], s["deeper"], s["shallower"]) == (2, 3, 1)
    env["hooks"]["sessions"] = lambda real: _answer([])  # a node without the fields
    sync.run_pass(env["cfg"], "n1")
    s = _store(env)
    assert (s["ignored"], s["deeper"], s["shallower"]) == (0, 0, 0)
    for bad in ("2", True, -1, 1.5, None, [3]):
        env["hooks"]["sessions"] = lambda real: _answer([], ignored=bad, deeper=bad,
                                                        shallower=bad)
        sync.run_pass(env["cfg"], "n1")
        s = _store(env)
        assert (s["ignored"], s["deeper"], s["shallower"]) == (0, 0, 0), bad


@pytest.mark.parametrize("answer", [None, [], "text", {"sessions": "x"}, {"days": 8}])
def test_sessions_answer_of_the_wrong_shape(env, answer):
    env["hooks"]["sessions"] = lambda real: answer
    st = sync.run_pass(env["cfg"], "n1")
    assert st["ok"] is True and st["sessions"] == "bad_answer" and _store(env) is None


def test_sessions_failure_keeps_the_store(env, monkeypatch):
    from rb_host import sessions as hub_sessions
    _clock(monkeypatch)
    env["hooks"]["sessions"] = lambda real: _answer([_sess(SID_A)])
    sync.run_pass(env["cfg"], "n1")
    good = _store(env)

    def boom(real):
        raise RemoteError("io_error")
    env["hooks"]["sessions"] = boom
    st = sync.run_pass(env["cfg"], "n1")
    assert st["ok"] is True and st["sessions"] == "io_error" and st["error"] is None
    s = _store(env)
    assert s["sessions"] == good["sessions"] and s["fetched_at"] == good["fetched_at"]
    assert s["ok"] is False and s["error"] == "io_error" and s["attempted_at"] > good["attempted_at"]

    def crash(real):
        raise RuntimeError("SESSIONS-SECRET-TEXT")
    env["hooks"]["sessions"] = crash
    st = sync.run_pass(env["cfg"], "n1")
    assert st["ok"] is True and st["sessions"] == "internal"
    assert "SESSIONS-SECRET-TEXT" not in json.dumps(_store(env))
    env["hooks"]["sessions"] = lambda real: _answer([_sess(SID_B)])
    with monkeypatch.context() as m:
        def disk(*a, **k):
            raise OSError("disk full")
        m.setattr(hub_sessions, "write_store", disk)
        st = sync.run_pass(env["cfg"], "n1")
    assert st["ok"] is True and st["sessions"] == "os_error"
    assert set(_store(env)["sessions"]) == {SID_A}
    boom_code = RemoteError("Bad Code!")  # a code outside the code pattern is not kept as is
    env["hooks"]["sessions"] = lambda real: (_ for _ in ()).throw(boom_code)
    assert sync.run_pass(env["cfg"], "n1")["sessions"] == "invalid_code"


def test_sessions_state_follows_the_node_after_an_ok_fetch(env):
    # a store that said ok must not keep saying ok once the node stops answering
    env["hooks"]["sessions"] = lambda real: _answer([_sess(SID_A)])
    sync.run_pass(env["cfg"], "n1")
    del env["hooks"]["sessions"]  # the local node answers not_configured
    st = sync.run_pass(env["cfg"], "n1")
    assert st["sessions"] == "not_configured"
    s = _store(env)
    assert s["ok"] is False and s["error"] == "not_configured" and SID_A in s["sessions"]
    env["hooks"]["hello"] = lambda real: dict(real(), ops=["hello", "poll"])
    sync.run_pass(env["cfg"], "n1")
    assert _store(env)["error"] == "unsupported"


def test_sessions_field_carried_forward_when_the_pass_fails_early(env, monkeypatch):
    env["hooks"]["sessions"] = lambda real: _answer([])
    assert sync.run_pass(env["cfg"], "n1")["sessions"] == "ok"

    def bad(cfg, node):
        raise TransportError("down")
    monkeypatch.setattr(jobs, "connect", bad)
    st = sync.run_pass(env["cfg"], "n1")
    assert st["ok"] is False and st["sessions"] == "ok"


def test_sessions_in_the_printed_line(env, capsys):
    assert sync.run(None, 0) == 0
    assert json.loads(capsys.readouterr().out)["sessions"] == "not_configured"
