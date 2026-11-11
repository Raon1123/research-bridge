from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import rb_node.spawn as spawn
from rb_node.config import NodeConfig
from rb_node.mailbox import Mailbox

REPO = str(Path(__file__).resolve().parent.parent)

FAKE = """
import os, sys, time
mode = os.environ.get("FAKE_MODE", "answer")
if mode == "custom":
    sys.stdout.write(os.environ.get("FAKE_STDOUT", ""))
    sys.stderr.write(os.environ.get("FAKE_STDERR", ""))
    sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
if mode == "exit1":
    sys.exit(1)
if mode == "sleep":
    time.sleep(8)
    sys.exit(0)
if mode == "grandchild":
    import subprocess
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(4)"])
    sys.exit(0)
if mode == "noop":
    sys.exit(0)
from rb_node.config import load_config
from rb_node.local import LocalServer
srv = LocalServer(load_config())
for rec in srv.mb.inbox("responding"):
    srv.call_tool("reply", {"msg_id": rec["id"], "body": "ok", "attachments": []})
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    trm = tmp_path / "trm"
    trm.mkdir()
    mb = tmp_path / "rb" / "mailbox"
    cfg = NodeConfig(trm_root=str(trm), read_roots=["lab"], write_roots=[str(mb / "in")],
                     queue_dir=str(trm / "q"), withheld_source=None, mailbox_root=str(mb),
                     audit_path=str(tmp_path / "rb" / "audit.jsonl"))
    script = tmp_path / "fake_claude.py"
    script.write_text(FAKE, encoding="utf-8")
    if os.name == "nt":
        claude = tmp_path / "fake_claude.cmd"
        claude.write_text('@"%s" "%s" %%*\r\n' % (sys.executable, script), encoding="utf-8")
    else:
        claude = tmp_path / "fake_claude.sh"
        claude.write_text('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, script))
        claude.chmod(0o755)
    cfg.claude_bin = str(claude)
    cfgfile = tmp_path / "node.json"
    cfgfile.write_text(json.dumps(cfg.__dict__), encoding="utf-8")
    monkeypatch.setenv("RB_NODE_CONFIG", str(cfgfile))
    monkeypatch.setenv("PYTHONPATH", REPO)
    return cfg


def mkmsg(cfg, mid, status="new"):
    return Mailbox(Path(cfg.mailbox_root)).new_message(mid, {"body": "b", "status": status})


def status(cfg, mid):
    return {r["id"]: r["status"] for r in Mailbox(Path(cfg.mailbox_root)).inbox()}[mid]


def events(cfg):
    return [i for i in Mailbox(Path(cfg.mailbox_root)).undelivered() if i["kind"] == "event"]


def test_nonzero_exit_fails_and_posts_event(env, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "exit1")
    mkmsg(env, "m1")
    assert spawn.respond(env, "m1") == 0
    assert status(env, "m1") == "failed"
    ev = events(env)
    assert len(ev) == 1 and ev[0]["reply_to"] == "m1"
    body = json.loads(ev[0]["body"])
    assert body["event"] == "responder_failed" and body["msg_id"] == "m1"
    assert "1" in body["reason"]


def test_timeout_fails(env, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "sleep")
    monkeypatch.setattr(spawn, "RESPONDER_TIMEOUT", 1)
    mkmsg(env, "m1")
    t = time.time()
    spawn.respond(env, "m1")
    assert time.time() - t < 7
    assert status(env, "m1") == "failed"
    assert json.loads(events(env)[0]["body"])["reason"] == "timeout"


def test_grandchild_holding_output_does_not_hold_the_lock(env, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "grandchild")
    monkeypatch.setattr(spawn, "RESPONDER_TIMEOUT", 3)
    mkmsg(env, "m1")
    t = time.time()
    spawn.respond(env, "m1")
    assert time.time() - t < 2.5
    assert json.loads(events(env)[0]["body"])["reason"] == "no reply"


def test_exit_zero_without_reply_fails(env, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "noop")
    mkmsg(env, "m1")
    spawn.respond(env, "m1")
    assert status(env, "m1") == "failed"
    assert len(events(env)) == 1


def test_answer_then_loops_over_remaining_new(env, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "answer")
    mkmsg(env, "m1")
    mkmsg(env, "m2")
    mkmsg(env, "job-x")  # job uploads are never answered by the responder
    spawn.respond(env, "m1")
    assert status(env, "m1") == "answered" and status(env, "m2") == "answered"
    assert status(env, "job-x") == "new"
    assert events(env) == []
    assert not (Path(env.mailbox_root) / "state" / "responder.lock").exists()


def test_trigger_skips_when_lock_held(env, monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: calls.append((a, k)))
    mkmsg(env, "m1")
    spawn.trigger(env, "m1")
    assert len(calls) == 1
    assert calls[0][0][0][-2:] == ["respond", "m1"]
    assert calls[0][1]["stdin"] == subprocess.DEVNULL
    lock = spawn._acquire(Path(env.mailbox_root) / "state")
    assert lock is not None
    spawn.trigger(env, "m1")
    assert len(calls) == 1 and status(env, "m1") == "new"
    spawn._release(lock)
    spawn.trigger(env, "m1")
    assert len(calls) == 2


def test_stale_lock_is_taken_over(env):
    state = Path(env.mailbox_root) / "state"
    state.mkdir(parents=True)
    lock = state / "responder.lock"
    lock.write_text("1", encoding="utf-8")
    old = time.time() - spawn._lock_stale() - 10
    os.utime(str(lock), (old, old))
    assert spawn._acquire(state) is not None


def test_respond_when_lock_held_leaves_new(env):
    mkmsg(env, "m1")
    lock = spawn._acquire(Path(env.mailbox_root) / "state")
    assert spawn.respond(env, "m1") == 0
    assert status(env, "m1") == "new"
    spawn._release(lock)


def test_lock_stale_threshold_tracks_responder_timeout(env, monkeypatch):
    monkeypatch.setattr(spawn, "RESPONDER_TIMEOUT", 1)
    assert spawn._lock_stale() > spawn.RESPONDER_TIMEOUT
    state = Path(env.mailbox_root) / "state"
    state.mkdir(parents=True)
    lock = state / "responder.lock"
    lock.write_text("1", encoding="utf-8")
    t = time.time() - (spawn.RESPONDER_TIMEOUT + 10)
    os.utime(str(lock), (t, t))
    assert spawn._acquire(state) is None  # still held: a run may be alive
    t = time.time() - (spawn._lock_stale() + 10)
    os.utime(str(lock), (t, t))
    assert spawn._acquire(state) is not None


def _capture_argv(env, monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"] = list(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(spawn.subprocess, "run", fake_run)
    mkmsg(env, "m1")
    spawn.respond(env, "m1")
    return seen["argv"]


def test_argv_confines_responder_tools(env, monkeypatch):  # PM-02
    argv = _capture_argv(env, monkeypatch)
    assert argv[argv.index("--tools") + 1] == "Read,Grep,Glob"
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert "--strict-mcp-config" in argv
    assert argv[argv.index("--allowedTools") + 1] == "mcp__rb__*,Read,Grep,Glob"
    dis = argv[argv.index("--disallowedTools") + 1].split(",")
    assert set(dis) == {"Bash", "Write", "Edit", "WebFetch", "WebSearch"}
    assert argv[argv.index("--max-turns") + 1] == "40"


def test_prompt_names_no_nonexistent_work_dir(env, monkeypatch):  # PM-14
    argv = _capture_argv(env, monkeypatch)
    prompt = argv[argv.index("-p") + 1]
    assert "_work" not in prompt and "work directory" not in prompt
    assert "reply" in prompt and "inbox_read" in prompt


def _dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def _write_lock(state, content, age=0):
    state.mkdir(parents=True, exist_ok=True)
    lock = state / "responder.lock"
    lock.write_text(str(content), encoding="utf-8")
    if age:
        t = time.time() - age
        os.utime(str(lock), (t, t))
    return lock


def test_lock_with_dead_pid_is_stale(env, monkeypatch):
    state = Path(env.mailbox_root) / "state"
    _write_lock(state, _dead_pid())
    assert spawn._lock_holder_dead(state / "responder.lock") is True
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: calls.append((a, k)))
    mkmsg(env, "m1")
    spawn.trigger(env, "m1")
    assert len(calls) == 1
    lock = spawn._acquire(state)
    assert lock is not None
    assert lock.read_text(encoding="utf-8") == str(os.getpid())
    assert not (state / "responder.lock.takeover").exists()


def test_lock_dead_leader_live_group_not_stale(env):
    state = Path(env.mailbox_root) / "state"
    code = ("import subprocess, sys\n"
            "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
            "print(g.pid, flush=True)\n")
    leader = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE,
                              start_new_session=True)
    grandchild = int(leader.stdout.readline())
    leader.wait()
    try:
        _write_lock(state, leader.pid)
        lock = state / "responder.lock"
        assert spawn._lock_holder_dead(lock) is False
        assert spawn._acquire(state) is None
    finally:
        os.kill(grandchild, 9)
    deadline = time.time() + 5
    while time.time() < deadline and spawn._lock_holder_dead(lock) is False:
        time.sleep(0.05)
    assert spawn._lock_holder_dead(lock) is True
    assert spawn._acquire(state) is not None


def test_lock_with_live_foreign_pid_respects_age(env):
    state = Path(env.mailbox_root) / "state"
    _write_lock(state, "1")
    assert spawn._lock_holder_dead(state / "responder.lock") is False
    assert spawn._acquire(state) is None


def test_lock_unparsable_content_uses_age_only(env):
    state = Path(env.mailbox_root) / "state"
    _write_lock(state, "not a pid")
    assert spawn._lock_holder_dead(state / "responder.lock") is False
    assert spawn._acquire(state) is None


def _contender(state, q, release):
    import rb_node.spawn as sp
    got = sp._acquire(Path(state))
    q.put((os.getpid(), str(got) if got else None))
    release.wait(20)


def test_concurrent_takeover_one_holder(env):
    import multiprocessing
    ctx = multiprocessing.get_context("fork")
    state = Path(env.mailbox_root) / "state"
    _write_lock(state, _dead_pid(), age=100)
    q, release = ctx.Queue(), ctx.Event()
    procs = [ctx.Process(target=_contender, args=(str(state), q, release)) for _ in range(2)]
    for p in procs:
        p.start()
    try:
        results = [q.get(timeout=20) for _ in procs]
    finally:
        release.set()
        for p in procs:
            p.join(20)
    winners = [(pid, path) for pid, path in results if path]
    assert len(winners) == 1
    lock = state / "responder.lock"
    assert lock.read_text(encoding="utf-8") == str(winners[0][0])
    assert not (state / "responder.lock.takeover").exists()


def test_takeover_serialised_when_stale_judgement_is_slow(env, monkeypatch):
    import threading
    state = Path(env.mailbox_root) / "state"
    _write_lock(state, _dead_pid(), age=100)
    real = spawn._is_stale

    def slow(path):
        verdict = real(path)  # both contenders judge the dead lock stale before either replaces it
        time.sleep(0.3)
        return verdict

    monkeypatch.setattr(spawn, "_is_stale", slow)
    results = []
    barrier = threading.Barrier(2)

    def go():
        barrier.wait()
        results.append(spawn._acquire(state))

    ts = [threading.Thread(target=go) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(20)
    assert len([r for r in results if r]) == 1


def test_old_takeover_file_is_replaced(env):
    state = Path(env.mailbox_root) / "state"
    _write_lock(state, _dead_pid(), age=100)
    tk = state / "responder.lock.takeover"
    tk.write_text("", encoding="utf-8")
    t = time.time() - 120
    os.utime(str(tk), (t, t))
    assert spawn._acquire(state) is not None
    assert not tk.exists()
    # a fresh takeover file blocks
    spawn._release(state / "responder.lock")
    _write_lock(state, _dead_pid(), age=100)
    tk.write_text("", encoding="utf-8")
    assert spawn._acquire(state) is None


def _log(env, mid):
    return Path(env.mailbox_root) / "state" / ("respond-%s.log" % mid)


def test_responder_output_logged_mode_600(env, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "custom")
    monkeypatch.setenv("FAKE_STDOUT", json.dumps({"is_error": True, "subtype": "error_max_turns",
                                                  "num_turns": 40, "duration_ms": 5}))
    monkeypatch.setenv("FAKE_STDERR", "boom: something failed\n")
    monkeypatch.setenv("FAKE_EXIT", "1")
    mkmsg(env, "m1")
    spawn.respond(env, "m1")
    log = _log(env, "m1")
    assert log.is_file() and (log.stat().st_mode & 0o777) == 0o600
    text = log.read_text(encoding="utf-8")
    assert "is_error" in text and "boom: something failed" in text
    body = events(env)[0]["body"]
    assert "boom" not in body and "is_error" not in body


def test_responder_log_drops_result_text(env, monkeypatch):
    from rb_node.withheld import FALLBACK_PATTERNS
    a, b = FALLBACK_PATTERNS[1], FALLBACK_PATTERNS[2]  # plain-text fallback patterns
    monkeypatch.setenv("FAKE_MODE", "custom")
    monkeypatch.setenv("FAKE_STDOUT", json.dumps({"result": "answer about %s run" % a,
                                                  "is_error": False, "num_turns": 2}))
    monkeypatch.setenv("FAKE_STDERR", "line one\nleaked %s here\nlast line\n" % b)
    monkeypatch.setenv("FAKE_EXIT", "1")
    mkmsg(env, "m1")
    spawn.respond(env, "m1")
    text = _log(env, "m1").read_text(encoding="utf-8")
    assert "num_turns" in text and "line one" in text and "last line" in text
    assert "answer about" not in text and a not in text and b not in text


def test_responder_log_non_json_stdout(env, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "custom")
    monkeypatch.setenv("FAKE_STDOUT", "plain words that must not be kept")
    monkeypatch.setenv("FAKE_EXIT", "1")
    mkmsg(env, "m1")
    spawn.respond(env, "m1")
    text = _log(env, "m1").read_text(encoding="utf-8")
    assert "stdout was not JSON (33 bytes)" in text and "plain words" not in text


def test_old_responder_logs_deleted(env, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "answer")
    state = Path(env.mailbox_root) / "state"
    state.mkdir(parents=True, exist_ok=True)
    old, new = state / "respond-old.log", state / "respond-new.log"
    old.write_text("x", encoding="utf-8")
    new.write_text("x", encoding="utf-8")
    t = time.time() - 15 * 86400
    os.utime(str(old), (t, t))
    mkmsg(env, "m1")
    spawn.respond(env, "m1")
    assert not old.exists() and new.exists()


def test_trigger_logs_child_output_to_respond_log(env, monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: calls.append((a, k)))
    mkmsg(env, "m1")
    spawn.trigger(env, "m1")
    k = calls[0][1]
    assert k["stdout"] is k["stderr"] or k["stdout"].name == k["stderr"].name
    assert Path(k["stdout"].name if hasattr(k["stdout"], "name") else "").name == "respond-m1.log"
    assert (_log(env, "m1").stat().st_mode & 0o777) == 0o600


def test_launcher_argv_is_what_callers_use(env, monkeypatch):
    monkeypatch.setattr(spawn, "launcher_argv", lambda: ["/abs/rb-node"])
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: calls.append(a))
    mkmsg(env, "m1")
    spawn.trigger(env, "m1")
    assert calls[0][0][:2] == ["/abs/rb-node", "respond"]
    import json as _j
    conf = _j.loads(Path(spawn._mcp_config(str(env.trm_root))).read_text(encoding="utf-8"))
    assert conf["mcpServers"]["rb"]["command"] == "/abs/rb-node"


def test_release_keeps_a_lock_another_process_took_over(tmp_path):
    lock = tmp_path / "responder.lock"
    lock.write_text("1", encoding="utf-8")  # not this process's pid
    spawn._release(lock)
    assert lock.exists()
    lock.write_text(str(os.getpid()), encoding="utf-8")
    spawn._release(lock)
    assert not lock.exists()


def test_discard_old_keeps_a_fresh_takeover_file(tmp_path):
    tk = tmp_path / "responder.lock.takeover"
    tk.write_text("", encoding="utf-8")
    assert spawn._discard_old(tk) is False and tk.exists()
    old = time.time() - spawn.TAKEOVER_STALE - 5
    os.utime(str(tk), (old, old))
    assert spawn._discard_old(tk) is True and not tk.exists()
    assert not list(tmp_path.glob("*.discard.*"))
