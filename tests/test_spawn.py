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
if mode == "exit1":
    sys.exit(1)
if mode == "sleep":
    time.sleep(8)
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
