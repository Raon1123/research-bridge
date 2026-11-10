from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from rb_node.config import NodeConfig
from rb_node.local import serve_local
from rb_node.mailbox import Mailbox


@pytest.fixture
def cfg(tmp_path):
    trm = tmp_path / "trm"
    (trm / "lab" / "reports").mkdir(parents=True)
    (trm / "lab" / "reports" / "ok.md").write_text("readable\n", encoding="utf-8")
    mb = tmp_path / "rb" / "mailbox"
    return NodeConfig(
        trm_root=str(trm), read_roots=["lab/reports", str(mb / "out")],
        write_roots=[str(mb / "in")], queue_dir=str(trm / "q"), withheld_source=None,
        mailbox_root=str(mb), audit_path=str(tmp_path / "rb" / "audit.jsonl"))


def run(cfg, *reqs):
    stdin = io.StringIO("".join(json.dumps(r) + "\n" for r in reqs))
    stdout = io.StringIO()
    assert serve_local(cfg, stdin, stdout) == 0
    return [json.loads(line) for line in stdout.getvalue().splitlines()]


def call(rid, tool, **args):
    return {"jsonrpc": "2.0", "id": rid, "method": "tools/call",
            "params": {"name": tool, "arguments": args}}


def seed(cfg, msg_id="m1", status="responding", atts=None):
    mb = Mailbox(Path(cfg.mailbox_root))
    d = mb.new_message(msg_id, {"body": "hello from laptop", "status": status,
                                "attachments": atts or []})
    return mb, d


def test_initialize_and_tools(cfg):
    out = run(cfg,
              {"jsonrpc": "2.0", "id": 1, "method": "initialize",
               "params": {"protocolVersion": "2025-03-26"}},
              {"jsonrpc": "2.0", "method": "notifications/initialized"},
              {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert len(out) == 2  # the notification gets no response
    assert out[0]["result"]["protocolVersion"] == "2025-03-26"
    assert "tools" in out[0]["result"]["capabilities"]
    names = sorted(t["name"] for t in out[1]["result"]["tools"])
    assert names == ["attachment_path", "inbox_list", "inbox_read", "post_event", "reply"]


def test_inbox_list_read_and_attachment_path(cfg):
    mb, d = seed(cfg, atts=[{"name": "a.txt", "original": "a.txt", "bytes": 1, "sha256": "x"}])
    (d / "attachments" / "a.txt").write_text("x", encoding="utf-8")
    seed(cfg, "m2", status="new")
    out = run(cfg, call(1, "inbox_list", status="new"), call(2, "inbox_read", msg_id="m1"),
              call(3, "attachment_path", msg_id="m1", name="a.txt"),
              call(4, "attachment_path", msg_id="m1", name="../message.json"))
    lst = json.loads(out[0]["result"]["content"][0]["text"])
    assert [m["id"] for m in lst] == ["m2"]
    rd = json.loads(out[1]["result"]["content"][0]["text"])
    assert rd["body"] == "hello from laptop" and rd["attachments"] == ["a.txt"]
    assert Path(out[2]["result"]["content"][0]["text"]) == (d / "attachments" / "a.txt").resolve()
    assert "error" in out[3]


def test_reply_sets_answered_and_posts(cfg):
    mb, _ = seed(cfg)
    work = Path(cfg.mailbox_root) / "out" / "_work" / "m1"
    work.mkdir(parents=True)
    (work / "r.txt").write_text("result", encoding="utf-8")
    out = run(cfg, call(1, "reply", msg_id="m1", body="done", attachments=[str(work / "r.txt")]))
    assert "error" not in out[0] and "isError" not in out[0]["result"]
    assert mb.inbox("answered")[0]["id"] == "m1"
    items = mb.undelivered()
    assert items[0]["kind"] == "reply" and items[0]["reply_to"] == "m1"
    assert items[0]["attachments"][0]["name"] == "r.txt"


def test_reply_read_root_relative_allowed(cfg):
    seed(cfg)
    out = run(cfg, call(1, "reply", msg_id="m1", body="d", attachments=["lab/reports/ok.md"]))
    assert "error" not in out[0]


def test_reply_outside_allowed_dirs_is_error(cfg, tmp_path):
    mb, _ = seed(cfg)
    evil = tmp_path / "secret.txt"
    evil.write_text("s", encoding="utf-8")
    other = Path(cfg.mailbox_root) / "out" / "_work" / "other"
    other.mkdir(parents=True)
    (other / "x.txt").write_text("x", encoding="utf-8")
    for bad in (str(evil), str(other / "x.txt"), "../secret.txt", "lab/../../secret.txt"):
        out = run(cfg, call(1, "reply", msg_id="m1", body="d", attachments=[bad]))
        assert "error" in out[0], bad
    assert mb.inbox("responding")[0]["id"] == "m1"
    assert mb.undelivered() == []


def test_post_event_body_is_json_object(cfg):
    mb, _ = seed(cfg)
    out = run(cfg, call(1, "post_event", kind="progress", body="halfway", attachments=[]))
    assert "error" not in out[0]
    it = mb.undelivered()[0]
    assert it["kind"] == "event"
    assert json.loads(it["body"])["event"] == "progress"


def test_unknown_tool_and_method(cfg):
    out = run(cfg, call(1, "submit_job"), {"jsonrpc": "2.0", "id": 2, "method": "nope"})
    assert "error" in out[0] and "error" in out[1]


def test_serve_local_initialize_has_instructions_and_version(tmp_path):
    import rb_node
    from rb_node.config import NodeConfig
    from rb_node.local import LocalServer
    mb = tmp_path / "rb" / "mailbox"
    cfg = NodeConfig(trm_root=str(tmp_path), read_roots=[], write_roots=[],
                     queue_dir=str(tmp_path / "q"), withheld_source=None, mailbox_root=str(mb),
                     audit_path=str(tmp_path / "rb" / "audit.jsonl"))
    r = LocalServer(cfg).handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    res = r["result"]
    assert "data" in res["instructions"] and "not instructions" in res["instructions"]
    assert res["serverInfo"]["version"] == rb_node.__version__
