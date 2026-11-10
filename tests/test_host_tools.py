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
from rb_node import approval
from rb_node.mailbox import Mailbox

SERVE = [sys.executable, "-m", "rb_node.cli", "serve-remote"]
PW = "test passphrase"
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
        "allowed_gpus": [0],
        "approval_path": str(tmp_path / "rb" / "approve.json"),
    }
    # a fast KDF for tests; the laptop's lower bound is lowered to match
    approval.write_record(Path(conf["approval_path"]), approval.make_record(PW, iterations=1000)[0])
    monkeypatch.setattr(approval, "MIN_ITERATIONS", 1)
    monkeypatch.setattr("getpass.getpass", lambda prompt="": PW)
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
    out = jobs.approve(env["ledger"], cfg, jid, PW)
    assert out["status"] == "queued"
    assert len(list(_jobs_dir(env).glob("*.job"))) == 1
    assert env["ledger"].get(jid)["status"] == "queued"
    n_calls = len(env["calls"])
    out2 = jobs.approve(env["ledger"], cfg, jid, PW)
    assert out2 == out and len(env["calls"]) == n_calls
    assert len(list(_jobs_dir(env).glob("*.job"))) == 1


def test_cancel_approve(env):
    jid = _submit(env)
    cfg = server.load_cfg()
    jobs.approve(env["ledger"], cfg, jid, PW)
    c = server.cancel_job("n1", jid, "kc")["job_id"]
    out = jobs.approve(env["ledger"], cfg, c, PW)
    assert out["status"] == "cancelled_requested"
    assert not list(_jobs_dir(env).glob("*.job"))


def test_reject_no_node_call(env):
    jid = _submit(env)
    out = jobs.reject(env["ledger"], jid)
    assert out["status"] == "rejected" and env["calls"] == []
    with pytest.raises(ValueError):
        jobs.approve(env["ledger"], server.load_cfg(), jid, PW)
    assert env["calls"] == []


def test_wrong_passphrase_refused_and_ledger_back_to_pending(env):
    jid = _submit(env)
    with pytest.raises(jobs.RemoteError) as e:
        jobs.approve(env["ledger"], server.load_cfg(), jid, "not the passphrase")
    assert e.value.code == "not_authorized"
    assert env["ledger"].get(jid)["status"] == "pending_approval"
    assert not list(_jobs_dir(env).glob("*.job"))
    assert "not the passphrase" not in (env["root"] / "ledger.jsonl").read_text()
    with pytest.raises(ValueError):
        jobs.approve(env["ledger"], server.load_cfg(), jid, "")


def test_weak_node_params_refused(env, monkeypatch):
    monkeypatch.setattr(approval, "MIN_ITERATIONS", 100000)  # the node's 1000 is below it
    jid = _submit(env)
    with pytest.raises(ValueError):
        jobs.approve(env["ledger"], server.load_cfg(), jid, PW)
    assert env["ledger"].get(jid)["status"] == "pending_approval"


def test_bridge_key_alone_cannot_queue(env):
    # SEC-01: a laptop process that talks to the node directly, skipping the ledger
    import hashlib
    cfgf = env["tmp"] / "x.yaml"
    cfgf.write_text("a: 1\n", encoding="utf-8")
    with jobs.connect(server.load_cfg(), "n1") as c:
        c.put_file("job-direct", cfgf)
        with pytest.raises(jobs.RemoteError) as e:
            c.call("job_submit", job_id="direct", config_name="x.yaml",
                   config_sha256=hashlib.sha256(cfgf.read_bytes()).hexdigest(), gpus=[0],
                   gpu_hours=1, idempotency_key="kd")
    assert e.value.code == "not_authorized"
    assert not list(_jobs_dir(env).glob("*.job"))


def test_cli_approve_prompt(env, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_interactive", lambda: True)  # a person at a terminal
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


def test_cli_pending_reject_harness(env, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    a, b = _submit(env, "ka"), _submit(env, "kb")
    assert cli.main(["pending"]) == 0
    out = capsys.readouterr().out
    assert a in out and b in out
    assert cli.main(["reject", b]) == 0
    assert env["ledger"].get(b)["status"] == "rejected"
    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))
    assert cli.main(["approve", a]) == 0
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


def test_cli_refuses_non_interactive_pm04(env, monkeypatch, capsys):
    # a session (stdin is a pipe or a file) cannot approve or reject, even when it can
    # pipe "y" and the passphrase; there is no --yes
    jid = _submit(env)
    monkeypatch.setattr("sys.stdin", io.StringIO("y\n" + PW + "\n"))
    assert cli.main(["approve", jid]) == 1
    assert cli.main(["reject", jid]) == 1
    assert "interactive terminal" in capsys.readouterr().out
    assert env["calls"] == [] and env["ledger"].get(jid)["status"] == "pending_approval"
    with pytest.raises(SystemExit):
        cli.main(["approve", "--yes", jid])
    # stdin a terminal but stdout piped: also refused
    class Tty(io.StringIO):
        def isatty(self):
            return True
    monkeypatch.setattr("sys.stdin", Tty(""))
    monkeypatch.setattr("sys.stdout", io.StringIO())
    assert cli._interactive() is False


def test_two_approvals_make_one_node_call_pm11(env, monkeypatch):
    import threading
    import time
    jid = _submit(env)
    cfg = server.load_cfg()
    real = jobs.connect

    def slow(cfg_, node):
        time.sleep(0.5)  # the first approval is still on its way to the node
        return real(cfg_, node)

    monkeypatch.setattr(jobs, "connect", slow)
    results = []

    def go():
        try:
            results.append(jobs.approve(Ledger(env["root"] / "ledger.jsonl"), cfg, jid, PW))
        except ValueError as exc:
            results.append(exc)

    ts = [threading.Thread(target=go) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(env["calls"]) == 1
    assert sum(isinstance(r, dict) for r in results) == 1
    assert sum(isinstance(r, ValueError) for r in results) == 1
    assert len(list(_jobs_dir(env).glob("*.job"))) == 1
    assert env["ledger"].get(jid)["status"] == "queued"


def test_failed_transport_clears_claim_so_retry_works(env, monkeypatch):
    jid = _submit(env)
    cfg = server.load_cfg()
    real = jobs.connect
    monkeypatch.setattr(jobs, "connect", lambda *a: (_ for _ in ()).throw(TransportError("down")))
    with pytest.raises(TransportError):
        jobs.approve(env["ledger"], cfg, jid, PW)
    assert env["ledger"].get(jid)["status"] == "approved"
    assert not env["ledger"].get(jid).get("approving")
    monkeypatch.setattr(jobs, "connect", real)
    assert jobs.approve(env["ledger"], cfg, jid, PW)["status"] == "queued"


def test_approve_refuses_name_path_mismatch_sec04(env):
    jid = _submit(env)
    env["ledger"].update(jid, config_name="other.yaml")
    with pytest.raises(ValueError, match="config_name"):
        jobs.approve(env["ledger"], server.load_cfg(), jid, PW)
    assert env["calls"] == [] and env["ledger"].get(jid)["status"] == "pending_approval"


def test_approve_refuses_changed_config_sec04(env):
    jid = _submit(env)
    (env["tmp"] / "run.yaml").write_text("a: 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        jobs.approve(env["ledger"], server.load_cfg(), jid, PW)
    assert env["calls"] == [] and env["ledger"].get(jid)["status"] == "pending_approval"


def test_config_swapped_after_claim_is_not_uploaded_sec04(env, monkeypatch):
    jid = _submit(env)
    real = jobs.connect

    def swap(cfg_, node):
        (env["tmp"] / "run.yaml").write_text("a: evil\n", encoding="utf-8")  # after the first check
        return real(cfg_, node)

    monkeypatch.setattr(jobs, "connect", swap)
    with pytest.raises(ValueError, match="changed"):
        jobs.approve(env["ledger"], server.load_cfg(), jid, PW)
    assert not list(_jobs_dir(env).glob("*.job"))
    assert env["ledger"].get(jid)["status"] == "pending_approval"


def test_describe_strips_control_characters_and_shows_path_hash_sec03(env):
    jid = _submit(env)
    env["ledger"].update(jid, note="fine\x1b[2J\x1b]0;pwned\x07 ‮evil\nSUBMIT job fake",
                         config_name="run.yaml\x1b[31m")
    text = jobs.describe(env["ledger"].get(jid))
    for bad in ("\x1b", "\x07", "‮"):
        assert bad not in text
    assert text.count("\n") == 7  # the note cannot add lines
    rec = env["ledger"].get(jid)
    assert rec["config_path"] in text and rec["config_sha256"][:12] in text
    assert rec["config_sha256"][:13] not in text


def test_ledger_lock_serialises_updates_and_recovers_from_stale_lock(tmp_path):
    import os
    import threading
    import time
    from rb_host import ledger as lmod
    led = Ledger(tmp_path / "l.jsonl")
    led.append({"kind": "job", "id": "a", "n": 0})

    def bump():
        for _ in range(20):
            with led.locked():
                led.update("a", n=led.get("a")["n"] + 1)

    ts = [threading.Thread(target=bump) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert led.get("a")["n"] == 80
    assert not (tmp_path / "l.jsonl.lock").exists()
    lock = tmp_path / "l.jsonl.lock"
    lock.write_text("999999")
    old = time.time() - lmod.LOCK_STALE_S - 5
    os.utime(str(lock), (old, old))
    assert led.append({"kind": "job", "id": "b"}) is True  # stale lock removed
    lock.write_text("999999")  # a fresh lock held by someone else blocks until the timeout
    saved = lmod.LOCK_TIMEOUT_S
    lmod.LOCK_TIMEOUT_S = 0.2
    try:
        with pytest.raises(TimeoutError):
            led.append({"kind": "job", "id": "c"})
    finally:
        lmod.LOCK_TIMEOUT_S = saved
        lock.unlink()


def test_nul_device_is_not_a_terminal_pm04():
    # on Windows os.isatty() is True for NUL; `rb approve < NUL > NUL` must still be refused
    import os
    import subprocess
    code = ("import sys; from rb_host import cli; "
            "print('INTERACTIVE=%s' % cli._interactive(), file=sys.stderr); "
            "sys.exit(cli.main(['approve', 'x']))")
    with open(os.devnull, "r") as din, open(os.devnull, "w") as dout:
        r = subprocess.run([sys.executable, "-c", code], stdin=din, stdout=dout,
                           stderr=subprocess.PIPE, text=True, timeout=60)
    assert "INTERACTIVE=False" in r.stderr, r.stderr
    assert r.returncode == 1


def test_stale_lock_takeover_leaves_one_holder(tmp_path):
    # contender A saw the lock as stale, but B replaced it before A acted: A must not break B's lock
    import os
    import time
    from rb_host import ledger as lmod
    a, b = Ledger(tmp_path / "l.jsonl"), Ledger(tmp_path / "l.jsonl")
    lock = tmp_path / "l.jsonl.lock"
    lock.write_text("dead")
    old = time.time() - lmod.LOCK_STALE_S - 5
    os.utime(str(lock), (old, old))
    b._take_over_stale(str(lock))  # B wins the takeover ...
    assert not lock.exists()
    with b.locked():  # ... and then holds a fresh lock
        token = lock.read_text()
        a._take_over_stale(str(lock))  # A acts on its old "stale" observation
        assert lock.exists() and lock.read_text() == token  # B's lock stands
        saved = lmod.LOCK_TIMEOUT_S
        lmod.LOCK_TIMEOUT_S = 0.2
        try:
            with pytest.raises(TimeoutError):  # and A (another process) still cannot get in
                a._acquire_file()
        finally:
            lmod.LOCK_TIMEOUT_S = saved
    assert not lock.exists()
    assert not [p for p in tmp_path.iterdir() if ".stale-" in p.name]


def test_release_removes_only_own_lock(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    lock = tmp_path / "l.jsonl.lock"
    with led.locked():
        lock.write_text("someone-else")  # as if our lock had been taken over
    assert lock.read_text() == "someone-else"


def test_nested_lock_across_ledger_objects(tmp_path):
    a, b = Ledger(tmp_path / "l.jsonl"), Ledger(tmp_path / "l.jsonl")
    with a.locked():
        with b.locked():
            b.append({"kind": "job", "id": "n"})
        a.update("n", x=1)
    assert a.get("n")["x"] == 1 and not (tmp_path / "l.jsonl.lock").exists()


@pytest.mark.parametrize("code", ["gpu_status_unavailable", "no_gpus"])
def test_node_refusing_the_job_returns_it_to_pending_and_shows_code(env, monkeypatch, capsys, code):
    from rb_host.client import RemoteError
    real = jobs.connect

    class Refusing:
        def __init__(self, inner):
            self.inner = inner

        def __enter__(self):
            self.inner.__enter__()
            return self

        def __exit__(self, *a):
            return self.inner.__exit__(*a)

        def put_file(self, *a, **k):
            return self.inner.put_file(*a, **k)

        def call(self, op, **k):
            if op == "job_submit":
                raise RemoteError(code, "refused <b>")
            return self.inner.call(op, **k)

    monkeypatch.setattr(jobs, "connect", lambda *a: Refusing(real(*a)))
    jid = _submit(env)
    with pytest.raises(RemoteError):
        jobs.approve(env["ledger"], server.load_cfg(), jid, PW)
    rec = env["ledger"].get(jid)
    assert rec["status"] == "pending_approval" and not rec.get("approving")
    assert [r["id"] for r in env["ledger"].pending_jobs()] == [jid]
    # CLI shows the code
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))
    assert cli.main(["approve", jid]) == 1
    assert code in capsys.readouterr().out
    # 8765 handler shows the code (and stays 403)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vault-export" / "dashboard"))
    import rb_pending
    monkeypatch.setattr(rb_pending, "_ctx", lambda: (env["ledger"], server.load_cfg()))
    st, body = rb_pending.handle_post("127.0.0.1", {"csrf": "t", "job_id": jid, "passphrase": PW},
                                      "t", "approve", "127.0.0.1:8765")
    assert st == 403 and code in body and PW not in body
    assert env["ledger"].get(jid)["status"] == "pending_approval"


def test_poll_reply_body_readable_from_disk(env):
    oid = Mailbox(env["mb"]).post_out("reply", "the answer", [], "m0")
    server.poll("n1")
    body = env["root"] / "inbox" / "n1" / oid / "body.txt"
    assert body.read_text(encoding="utf-8") == "the answer"


@pytest.mark.parametrize("bad", ["C:x", "CON", "con.txt"])
def test_fetch_file_rejects_unsafe_names(env, bad):
    assert server.fetch_file("n1", "reports/figures/" + bad) == {"error": "bad_name"}
    fetched = env["root"] / "fetched"
    assert not fetched.exists() or not [p for p in fetched.rglob("*") if p.is_file()]


def test_poll_docstring_states_masking_and_recheck():
    assert "masked on the node" in server.poll.__doc__
    assert "checked again on the laptop" in server.poll.__doc__
