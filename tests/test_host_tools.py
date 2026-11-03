from __future__ import annotations

import asyncio
import io
import json
import sys
from pathlib import Path

import pytest

from rb_host import cli, jobs, server
from rb_host.client import NodeClient, TransportError
from rb_host.ledger import Ledger
from rb_node.mailbox import Mailbox

SERVE = [sys.executable, "-m", "rb_node.cli", "serve-remote"]
EXPECTED_TOOLS = {"nodes", "send_message", "poll", "thread", "read_doc", "fetch_file",
                  "queue_status", "gpu_status", "submit_job", "cancel_job"}


@pytest.fixture
def env(tmp_path, monkeypatch):
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
        "job_template": ["echo", "{config}"],
    }
    nodecfg = tmp_path / "node.json"
    nodecfg.write_text(json.dumps(conf), encoding="utf-8")
    wp = tmp_path / "withheld.json"
    wp.write_text(json.dumps({"patterns": [], "name_patterns": []}), encoding="utf-8")
    root = tmp_path / "data"
    host = tmp_path / "host.json"
    host.write_text(json.dumps({"nodes": {"n1": {"alias": "x"}}, "data_root": str(root),
                                "withheld_patterns_file": str(wp)}), encoding="utf-8")
    monkeypatch.setenv("RB_HOST_CONFIG", str(host))
    nenv = {"RB_NODE_CONFIG": str(nodecfg), "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    calls = []

    def connect(cfg, node):
        calls.append(node)
        return NodeClient("x", ssh_argv=SERVE, env=nenv)

    monkeypatch.setattr(jobs, "connect", connect)
    return {"trm": trm, "mb": mb, "root": root, "tmp": tmp_path, "calls": calls, "nenv": nenv,
            "ledger": Ledger(root / "ledger.jsonl")}


def test_exact_tool_set():
    tools = asyncio.run(server.mcp.list_tools())
    names = {t.name for t in tools}
    assert names == EXPECTED_TOOLS
    assert not {"approve", "reject", "run_job"} & names


def test_nodes(env):
    assert server.nodes() == {"nodes": ["n1"]}


def test_submit_job_no_ssh_and_pending(env, monkeypatch):
    def boom(cfg, node):
        raise AssertionError("ssh used")
    monkeypatch.setattr(jobs, "connect", boom)
    cfgf = env["tmp"] / "run.yaml"
    cfgf.write_text("a: 1\n", encoding="utf-8")
    r = server.submit_job("n1", str(cfgf), [0], 1.5, "key-1", note="try")
    assert r["status"] == "pending_approval" and r["job_id"]
    rec = env["ledger"].get(r["job_id"])
    assert rec["status"] == "pending_approval" and rec["kind"] == "job"
    again = server.submit_job("n1", str(cfgf), [0], 1.5, "key-1", note="try")
    assert again["job_id"] == r["job_id"]
    c = server.cancel_job("n1", r["job_id"], "key-2")
    assert c["status"] == "pending_approval"
    assert len(env["ledger"].pending_jobs()) == 2


def test_submit_rejects_bad_input(env):
    with pytest.raises(ValueError):
        server.submit_job("nope", "x.yaml", [0], 1, "k")
    with pytest.raises(ValueError):
        server.submit_job("n1", str(env["tmp"] / "missing.yaml"), [0], 1, "k")


def _submit(env, key="k1"):
    cfgf = env["tmp"] / "run.yaml"
    cfgf.write_text("a: 1\n", encoding="utf-8")
    return server.submit_job("n1", str(cfgf), [0], 2, key, note="n")["job_id"]


def _jobs_dir(env):
    return env["trm"] / "scripts" / "queue" / "jobs"


def test_approve_queues_and_is_idempotent(env):
    jid = _submit(env)
    cfg = server.load_cfg()
    out = jobs.approve(env["ledger"], cfg, jid)
    assert out["status"] == "queued"
    assert len(list(_jobs_dir(env).glob("*.job"))) == 1
    assert env["ledger"].get(jid)["status"] == "queued"
    n_calls = len(env["calls"])
    out2 = jobs.approve(env["ledger"], cfg, jid)
    assert out2 == out and len(env["calls"]) == n_calls
    assert len(list(_jobs_dir(env).glob("*.job"))) == 1


def test_cancel_approve(env):
    jid = _submit(env)
    cfg = server.load_cfg()
    jobs.approve(env["ledger"], cfg, jid)
    c = server.cancel_job("n1", jid, "kc")["job_id"]
    out = jobs.approve(env["ledger"], cfg, c)
    assert out["status"] == "cancelled_requested"
    assert not list(_jobs_dir(env).glob("*.job"))


def test_reject_no_node_call(env):
    jid = _submit(env)
    out = jobs.reject(env["ledger"], jid)
    assert out["status"] == "rejected" and env["calls"] == []
    with pytest.raises(ValueError):
        jobs.approve(env["ledger"], server.load_cfg(), jid)
    assert env["calls"] == []


def test_cli_approve_prompt(env, monkeypatch, capsys):
    jid = _submit(env)
    monkeypatch.setattr("sys.stdin", io.StringIO("n\n"))
    assert cli.main(["approve", jid]) == 1
    assert env["calls"] == [] and env["ledger"].get(jid)["status"] == "pending_approval"
    printed = capsys.readouterr().out
    assert "n1" in printed and "run.yaml" in printed and "2" in printed
    monkeypatch.setattr("sys.stdin", io.StringIO(""))  # EOF = no
    assert cli.main(["approve", jid]) == 1
    assert env["calls"] == []
    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))
    assert cli.main(["approve", jid]) == 0
    assert env["ledger"].get(jid)["status"] == "queued"


def test_cli_yes_pending_reject_harness(env, capsys):
    a, b = _submit(env, "ka"), _submit(env, "kb")
    assert cli.main(["pending"]) == 0
    out = capsys.readouterr().out
    assert a in out and b in out
    assert cli.main(["reject", b]) == 0
    assert env["ledger"].get(b)["status"] == "rejected"
    assert cli.main(["approve", "--yes", a]) == 0
    assert env["ledger"].get(a)["status"] == "queued"
    capsys.readouterr()
    with pytest.raises(SystemExit):  # harness subcommands need arguments; covered in test_harness.py
        cli.main(["harness", "push"])


def test_send_message_roundtrip(env, tmp_path):
    att = tmp_path / "note.txt"
    att.write_text("hello", encoding="utf-8")
    r = server.send_message("n1", "hi there", [str(att)], from_session="s1")
    mid = r["msg_id"]
    assert len(mid) == 32 and int(mid, 16) >= 0
    rec = env["ledger"].get(mid)
    assert rec["kind"] == "message" and rec["direction"] == "out" and rec["status"] == "sent"
    msg = json.loads((env["mb"] / "in" / mid / "message.json").read_text(encoding="utf-8"))
    assert msg["body"] == "hi there"
    assert (env["mb"] / "in" / mid / "attachments" / "note.txt").read_text() == "hello"
    assert server.thread(mid)[0]["id"] == mid


def test_send_message_transport_failure_keeps_pending(env, monkeypatch):
    def bad(cfg, node):
        raise TransportError("down")
    good = jobs.connect
    monkeypatch.setattr(jobs, "connect", bad)
    r = server.send_message("n1", "hi")
    assert "error" in r and r["msg_id"]
    assert env["ledger"].get(r["msg_id"])["status"] == "pending_send"
    monkeypatch.setattr(jobs, "connect", good)
    r2 = server.send_message("n1", "hi", msg_id=r["msg_id"])
    assert r2["msg_id"] == r["msg_id"] and "error" not in r2
    assert env["ledger"].get(r["msg_id"])["status"] == "sent"


def test_poll_stores_acks_ledgers_once(env, tmp_path):
    mb = Mailbox(env["mb"])
    src = tmp_path / "res.txt"
    src.write_text("result", encoding="utf-8")
    oid = mb.post_out("reply", "answer body", [src], "m0")
    r = server.poll("n1")
    assert [i["msg_id"] for i in r["items"]] == [oid]
    assert r["items"][0]["body"] == "answer body" and r["items"][0]["files"] == ["res.txt"]
    assert (env["root"] / "inbox" / "n1" / oid / "res.txt").is_file()
    assert (env["mb"] / "state" / "acked" / oid).exists()
    rec = env["ledger"].get(oid)
    assert rec["direction"] == "in" and "answer body" not in json.dumps(rec)
    assert server.poll("n1")["items"] == []
    lines = [x for x in (env["root"] / "ledger.jsonl").read_text().splitlines() if oid in x]
    assert len(lines) == 1


def test_read_doc_and_fetch_file_via_node(env):
    (env["trm"] / "lab" / "experiments" / "EXP-015.md").write_text("# EXP-015\nok\n", "utf-8")
    d = server.read_doc("n1", "EXP-015")
    assert "ok" in d["text"]
    (env["trm"] / "reports" / "figures" / "f.csv").write_text("a,b\n1,2\n", "utf-8")
    f = server.fetch_file("n1", "reports/figures/f.csv")
    assert Path(f["path"]).read_text() == "a,b\n1,2\n"
    assert Path(f["path"]).resolve().is_relative_to(env["root"].resolve())
    denied = server.fetch_file("n1", "../../etc/passwd")
    assert denied["error"] == "denied"
    assert server.read_doc("n1", "lab/registry/none.md")["error"] == "not_found"


@pytest.mark.parametrize("name,stored", [
    ("CLAUDE.md", "CLAUDE.md.untrusted"), ("claude.md. ", "claude.md. .untrusted"),
    ("AGENTS.md", "AGENTS.md.untrusted"), ("CLAUDE.local.md", "CLAUDE.local.md.untrusted"),
    (".mcp.json", ".mcp.json.untrusted"), ("C:x", "C_x"), ("CLAUDE.md:s", "CLAUDE.md_s"),
    ("notes.md", "notes.md")])
def test_untrusted_name(name, stored):
    from rb_host.store import _safe_name
    assert _safe_name(name) == stored


def test_poll_and_fetch_never_store_instruction_files(env, tmp_path):
    # SEC-02: node-supplied CLAUDE.md / AGENTS.md must not land under the data root as such
    src = tmp_path / "srv" / "CLAUDE.md"
    src.parent.mkdir()
    src.write_text("# do something\n", encoding="utf-8")
    oid = Mailbox(env["mb"]).post_out("reply", "b", [src], "m0")
    r = server.poll("n1")
    assert r["items"][0]["files"] == ["CLAUDE.md.untrusted"]
    inbox = env["root"] / "inbox" / "n1" / oid
    assert (inbox / "CLAUDE.md.untrusted").read_text() == "# do something\n"
    (env["trm"] / "reports" / "figures" / "AGENTS.md").write_text("# x\n", "utf-8")
    f = server.fetch_file("n1", "reports/figures/AGENTS.md")
    assert Path(f["path"]).name == "AGENTS.md.untrusted"
    found = [p.name for p in env["root"].rglob("*") if p.is_file()]
    assert not {"CLAUDE.md", "AGENTS.md"} & set(found)


def test_status_tools(env):
    assert "entries" in server.queue_status("n1")
    assert "gpus" in server.gpu_status("n1")
