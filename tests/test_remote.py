from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from pathlib import Path

import pytest

from rb_node.config import NodeConfig, load_config
from rb_node.protocol import CHUNK, encode
from rb_node.remote import serve


@pytest.fixture(autouse=True)
def _no_real_responder(monkeypatch):
    import rb_node.spawn as spawn
    monkeypatch.setattr(spawn, "trigger", lambda c, m: None)


@pytest.fixture
def cfg(tmp_path):
    trm = tmp_path / "trm"
    (trm / "lab" / "experiments").mkdir(parents=True)
    (trm / "lab" / "registry").mkdir(parents=True)
    (trm / "lab" / "reports").mkdir(parents=True)
    (trm / "reports" / "figures").mkdir(parents=True)
    (trm / "scripts" / "queue" / "jobs").mkdir(parents=True)
    (trm / "scripts" / "queue" / "done").mkdir(parents=True)
    (trm / "lab" / "experiments" / "EXP-015.md").write_text("# EXP-015\nok line\n", encoding="utf-8")
    (trm / "lab" / "registry" / "HYPOTHESES.md").write_text(
        "# Hypotheses\n## H-12 first\nbody12\n### sub\nsub12\n## H-123 target\nbody123\n"
        "run pp_ltf_x leaked\n## H-124 next\nbody124\n", encoding="utf-8")
    (trm / "lab" / "reports" / "note.md").write_text("a\nresult pp_ltf_x here\nb\n", encoding="utf-8")
    (trm / "lab" / "reports" / "plain.md").write_text("hello\n", encoding="utf-8")
    (trm / "lab" / "reports" / "pp_ltf_secret.md").write_text("hello\n", encoding="utf-8")
    (trm / "lab" / "reports" / "data.bin").write_bytes(b"\x00\x01")
    mb = tmp_path / "rb" / "mailbox"
    return NodeConfig(
        trm_root=str(trm),
        read_roots=["lab/registry", "lab/experiments", "lab/reports", "reports/figures",
                    str(mb / "out")],
        write_roots=[str(mb / "in"), str(trm / "scripts" / "queue" / "jobs")],
        queue_dir=str(trm / "scripts" / "queue"),
        withheld_source=None,
        mailbox_root=str(mb),
        audit_path=str(tmp_path / "rb" / "audit.jsonl"),
        approval_path=str(tmp_path / "rb" / "approve.json"),
    )


def call(cfg, *reqs):
    stdin = io.BytesIO(b"".join(
        encode({"id": str(i), "op": op, "args": args}) for i, (op, args) in enumerate(reqs)))
    stdout = io.BytesIO()
    assert serve(cfg, stdin, stdout) == 0
    return [json.loads(l) for l in stdout.getvalue().decode("utf-8").splitlines()]


def b64(b):
    return base64.b64encode(b).decode("ascii")


def begin_req(msg_id, payload, name):
    return ("msg_begin", {"msg_id": msg_id, "body": "SECRETBODY", "from_session": "s1",
                          "attachments": [{"name": name, "bytes": len(payload),
                                           "sha256": hashlib.sha256(payload).hexdigest()}]})


def upload(cfg, msg_id, payload, name="big.bin", commit=True):
    reqs = [begin_req(msg_id, payload, name)]
    for seq, off in enumerate(range(0, len(payload), CHUNK)):
        reqs.append(("put_chunk", {"msg_id": msg_id, "name": name, "seq": seq,
                                   "data_b64": b64(payload[off:off + CHUNK])}))
    if commit:
        reqs.append(("msg_commit", {"msg_id": msg_id}))
    return call(cfg, *reqs)


def test_hello(cfg):
    r = call(cfg, ("hello", {}))[0]
    assert r["ok"] and r["result"]["version"] and r["result"]["node"]


def test_round_trip_three_chunks(cfg):
    payload = bytes(range(256)) * (2560 * 1024 // 256)
    assert len(payload) == 2560 * 1024
    resp = upload(cfg, "m1", payload)
    assert len(resp) == 5 and all(r["ok"] for r in resp), resp
    assert resp[0]["result"]["names"] == ["big.bin"]
    d = Path(cfg.mailbox_root) / "in" / "m1"
    f = d / "attachments" / "big.bin"
    assert hashlib.sha256(f.read_bytes()).hexdigest() == hashlib.sha256(payload).hexdigest()
    assert not list((d / "attachments").glob("*.part"))
    assert json.loads((d / "message.json").read_text(encoding="utf-8"))["status"] == "new"


def test_truncated_upload_only_part_and_retry_safe(cfg):
    payload = b"x" * (CHUNK + 10)
    resp = call(cfg, begin_req("m3", payload, "a.bin"),
                ("put_chunk", {"msg_id": "m3", "name": "a.bin", "seq": 0,
                               "data_b64": b64(payload[:CHUNK])}))
    assert all(r["ok"] for r in resp)
    att = Path(cfg.mailbox_root) / "in" / "m3" / "attachments"
    assert sorted(p.name for p in att.iterdir()) == ["a.bin.part"]
    bad = call(cfg, ("msg_commit", {"msg_id": "m3"}))[0]
    assert not bad["ok"]
    assert sorted(p.name for p in att.iterdir()) == ["a.bin.part"]
    # retry with the same msg_id
    resp = upload(cfg, "m3", payload, name="a.bin")
    assert all(r["ok"] for r in resp), resp
    assert resp[0]["result"]["names"] == ["a.bin"]
    assert sorted(p.name for p in att.iterdir()) == ["a.bin"]


def test_checksum_mismatch_fails_commit(cfg):
    resp = call(cfg, ("msg_begin", {"msg_id": "m4", "body": "b", "from_session": "s",
                                    "attachments": [{"name": "a", "bytes": 3, "sha256": "0" * 64}]}),
                ("put_chunk", {"msg_id": "m4", "name": "a", "seq": 0, "data_b64": b64(b"abc")}),
                ("msg_commit", {"msg_id": "m4"}))
    assert resp[2]["error"]["code"] == "checksum"


def test_too_large_rejected(cfg):
    cfg.max_file = 10
    r = call(cfg, ("msg_begin", {"msg_id": "m5", "body": "", "from_session": "s",
                                 "attachments": [{"name": "a", "bytes": 11, "sha256": "0" * 64}]}))[0]
    assert r["error"]["code"] == "too_large"


def test_job_commit_does_not_trigger(cfg, monkeypatch):
    import rb_node.spawn as spawn
    calls = []
    monkeypatch.setattr(spawn, "trigger", lambda c, m: calls.append(m))
    upload(cfg, "job-1", b"abc", name="j.json")
    upload(cfg, "plain-1", b"abc", name="j.json")
    assert calls == ["plain-1"]


def test_read_doc_by_exp_id(cfg):
    r = call(cfg, ("read_doc", {"id": "EXP-015"}))[0]
    assert r["ok"] and "ok line" in r["result"]["text"] and r["result"]["withheld_lines"] == 0


def test_read_doc_h_section(cfg):
    r = call(cfg, ("read_doc", {"id": "H-123"}))[0]["result"]
    assert "body123" in r["text"] and "body124" not in r["text"] and "body12\n" not in r["text"]
    assert "pp_ltf_x" not in r["text"] and r["withheld_lines"] == 1


def test_read_doc_masks_path(cfg):
    r = call(cfg, ("read_doc", {"path": "lab/reports/note.md"}))[0]["result"]
    assert r["withheld_lines"] == 1 and "pp_ltf_x" not in r["text"]
    assert r["text"].startswith("a")


def test_read_doc_denied_and_bad_id(cfg):
    r = call(cfg, ("read_doc", {"path": "../../etc/passwd"}),
             ("read_doc", {"id": "X-1"}),
             ("read_doc", {"path": "lab/reports/pp_ltf_secret.md"}))
    assert r[0]["error"]["code"] == "denied"
    assert r[1]["error"]["code"] == "bad_id"
    assert r[2]["error"]["code"] == "denied"


def test_get_file_denied(cfg):
    r = call(cfg, ("get_file", {"kind": "doc", "ref": "../../x", "seq": 0}),
             ("get_file", {"kind": "doc", "ref": "lab/reports/pp_ltf_secret.md", "seq": 0}),
             ("get_file", {"kind": "doc", "ref": "lab/reports/data.bin", "seq": 0}))
    assert [x["error"]["code"] for x in r] == ["denied"] * 3


def test_get_file_doc_masked_with_sha(cfg):
    r = call(cfg, ("get_file", {"kind": "doc", "ref": "lab/reports/note.md", "seq": 0}))[0]["result"]
    data = base64.b64decode(r["data_b64"])
    assert r["eof"] and b"pp_ltf_x" not in data
    assert r["sha256"] == hashlib.sha256(data).hexdigest()


def test_get_file_out_chunks(cfg):
    from rb_node.mailbox import Mailbox
    big = Path(cfg.trm_root).parent / "o.png"
    payload = b"z" * (CHUNK + 5)
    big.write_bytes(payload)
    oid = Mailbox(Path(cfg.mailbox_root)).post_out("reply", "hi", [big], None)
    ref = oid + "/o.png"
    r = call(cfg, ("get_file", {"kind": "out", "ref": ref, "seq": 0}),
             ("get_file", {"kind": "out", "ref": ref, "seq": 1}),
             ("get_file", {"kind": "out", "ref": oid + "/../../x", "seq": 0}))
    assert not r[0]["result"]["eof"] and "sha256" not in r[0]["result"]
    assert r[1]["result"]["eof"]
    assert r[1]["result"]["sha256"] == hashlib.sha256(payload).hexdigest()
    assert r[2]["error"]["code"] == "denied"


def test_poll_ack(cfg):
    from rb_node.mailbox import Mailbox
    mb = Mailbox(Path(cfg.mailbox_root))
    a = mb.post_out("reply", "one", [], "m1")
    b = mb.post_out("event", "two", [], None)
    p1 = call(cfg, ("poll", {}))[0]["result"]["items"]
    p2 = call(cfg, ("poll", {}))[0]["result"]["items"]
    assert [i["id"] for i in p1] == [i["id"] for i in p2] == [a, b]
    call(cfg, ("ack", {"ids": [a]}))
    assert [i["id"] for i in call(cfg, ("poll", {}))[0]["result"]["items"]] == [b]
    call(cfg, ("ack", {"ids": [b]}))
    assert call(cfg, ("poll", {}))[0]["result"]["items"] == []


def test_unknown_op_and_bad_json(cfg):
    assert call(cfg, ("frobnicate", {}))[0]["error"]["code"] == "unknown_op"
    out = io.BytesIO()
    assert serve(cfg, io.BytesIO(b"not json\n" + encode({"id": "1", "op": "hello", "args": {}})), out) == 0
    lines = [json.loads(l) for l in out.getvalue().decode().splitlines()]
    assert lines[0]["error"]["code"] == "bad_json" and lines[1]["ok"]


def test_queue_and_gpu_status(cfg, monkeypatch):
    (Path(cfg.queue_dir) / "jobs" / "a.json").write_text("{}", encoding="utf-8")
    r = call(cfg, ("queue_status", {}))[0]["result"]
    assert [(e["name"], e["state"]) for e in r["entries"]] == [("a.json", "jobs")]
    assert r["withheld_entries"] == 0
    # a job name that hits a withheld pattern never leaves the node (hard rule 3)
    (Path(cfg.queue_dir) / "done" / "0002_H108N_test.job").write_text("", encoding="utf-8")
    r = call(cfg, ("queue_status", {}))[0]["result"]
    assert ("(withheld)", "done") in [(e["name"], e["state"]) for e in r["entries"]]
    assert r["withheld_entries"] == 1 and "H108N" not in json.dumps(r)
    monkeypatch.setattr("rb_node.remote.shutil.which", lambda n: None)
    assert call(cfg, ("gpu_status", {}))[0]["result"] == {"gpus": [], "error": "nvidia-smi not found"}


def test_audit_has_no_body(cfg):
    upload(cfg, "m9", b"abc", name="a.txt")
    text = Path(cfg.audit_path).read_text(encoding="utf-8")
    assert text.strip()
    for line in text.splitlines():
        rec = json.loads(line)
        assert not ({"body", "content", "data"} & set(rec))
    assert "SECRETBODY" not in text


def test_load_config_env(tmp_path, monkeypatch):
    p = tmp_path / "node.json"
    p.write_text(json.dumps({"trm_root": "/x", "queue_dir": "/q"}), encoding="utf-8")
    monkeypatch.setenv("RB_NODE_CONFIG", str(p))
    c = load_config()
    assert c.trm_root == "/x" and c.claude_bin == os.path.expanduser("~/.local/bin/claude")
    assert c.job_template == [] and c.max_file == 50 * 1024 * 1024
    monkeypatch.setenv("RB_NODE_CONFIG", str(tmp_path / "missing.json"))
    with pytest.raises(FileNotFoundError):
        load_config()


def test_get_file_out_scanned_like_docs(cfg):
    from rb_node.mailbox import Mailbox
    bad = Path(cfg.trm_root).parent / "leak.tex"
    bad.write_text("result pp_ltf_x here", encoding="utf-8")
    ok_tex = Path(cfg.trm_root).parent / "fine.tex"
    ok_tex.write_text("nothing here", encoding="utf-8")
    oid = Mailbox(Path(cfg.mailbox_root)).post_out("reply", "hi", [bad, ok_tex], None)
    r = call(cfg, ("get_file", {"kind": "out", "ref": oid + "/leak.tex", "seq": 0}),
             ("get_file", {"kind": "out", "ref": oid + "/fine.tex", "seq": 0}))
    assert r[0]["error"]["code"] == "denied"
    assert r[1]["ok"]


# --- PM-01: poll masks bodies ---------------------------------------------------
def test_poll_masks_fallback_patterns(cfg):
    from rb_node.mailbox import Mailbox
    from rb_node.withheld import FALLBACK_PATTERNS
    mb = Mailbox(Path(cfg.mailbox_root))
    probes = ["EXP-013 run seed_7", "H108N-x", "pp_seedext_a", "cleanr1_b", "pp_ltf_c"]
    assert len(probes) == len(FALLBACK_PATTERNS)
    for p in probes:
        mb.post_out("reply", "keep\nresult %s here\nkeep2" % p, [], None)
    items = call(cfg, ("poll", {}))[0]["result"]["items"]
    assert len(items) == len(probes)
    for it in items:
        assert it["body"] == "keep\n\nkeep2"
        assert it["withheld_lines"] == 1
    clean = mb.post_out("reply", "all fine", [], None)
    last = [i for i in call(cfg, ("poll", {}))[0]["result"]["items"] if i["id"] == clean][0]
    assert last["body"] == "all fine" and last["withheld_lines"] == 0


# --- PM-07: audit warning for unparseable source --------------------------------
def test_unparseable_withheld_source_audited(cfg, tmp_path):
    src = tmp_path / "WITHHELD_RUNS.yaml"
    src.write_text("a: b\n", encoding="utf-8")
    cfg.withheld_source = str(src)
    call(cfg, ("hello", {}))
    recs = [json.loads(l) for l in Path(cfg.audit_path).read_text(encoding="utf-8").splitlines()]
    w = [r for r in recs if r.get("op") == "withheld_source"]
    assert w and w[0]["ok"] is False and w[0]["reason"] == "unparseable"
    assert w[0]["source"] == str(src)
    assert "a: b" not in json.dumps(w)


def test_hello_reports_extra_pattern_count(cfg, tmp_path):
    src = tmp_path / "w.json"
    src.write_text(json.dumps({"patterns": ["zz_\\d"]}), encoding="utf-8")
    cfg.withheld_source = str(src)
    assert call(cfg, ("hello", {}))[0]["result"]["withheld_extra"] == 1


# --- PM-08: read_doc and get_file agree on .tex ---------------------------------
def test_tex_with_hit_denied_by_both_ops(cfg):
    trm = Path(cfg.trm_root)
    (trm / "lab" / "reports" / "n.tex").write_text("a\nresult pp_ltf_x\nb\n", encoding="utf-8")
    r = call(cfg, ("read_doc", {"path": "lab/reports/n.tex"}),
             ("get_file", {"kind": "doc", "ref": "lab/reports/n.tex", "seq": 0}))
    assert r[0]["error"]["code"] == "denied"
    assert r[1]["error"]["code"] == "denied"


def test_clean_tex_readable_by_both_ops(cfg):
    trm = Path(cfg.trm_root)
    (trm / "lab" / "reports" / "ok.tex").write_bytes(b"a\nb\n")
    r = call(cfg, ("read_doc", {"path": "lab/reports/ok.tex"}),
             ("get_file", {"kind": "doc", "ref": "lab/reports/ok.tex", "seq": 0}))
    assert r[0]["result"]["text"] == "a\nb\n" and r[0]["result"]["withheld_lines"] == 0
    assert r[1]["ok"]


# --- fix round 2: attachments, reply_to, events ----------------------------------
def test_poll_drops_withheld_attachments_and_get_file_refuses(cfg, tmp_path):
    from rb_node.mailbox import Mailbox
    mb = Mailbox(Path(cfg.mailbox_root))
    bad = tmp_path / "pp_ltf_run3.csv"
    bad.write_text("x", encoding="utf-8")
    good = tmp_path / "fine.csv"
    good.write_text("y", encoding="utf-8")
    oid = mb.post_out("reply", "x", [bad, good], "pp_ltf_msg")
    item = call(cfg, ("poll", {}))[0]["result"]["items"][0]
    assert [a["original"] for a in item["attachments"]] == ["fine.csv"]
    assert item["withheld_attachments"] == 1
    assert item["reply_to"] is None
    assert "pp_ltf_" not in json.dumps(item)
    r = call(cfg, ("get_file", {"kind": "out", "ref": oid + "/pp_ltf_run3.csv", "seq": 0}))[0]
    assert r["error"]["code"] == "denied"


def test_fully_blanked_event_body_becomes_marker(cfg):
    from rb_node.mailbox import Mailbox
    mb = Mailbox(Path(cfg.mailbox_root))
    mb.post_out("event", json.dumps({"event": "job_finished", "job_id": "pp_ltf_x"}), [], None)
    item = call(cfg, ("poll", {}))[0]["result"]["items"][0]
    assert json.loads(item["body"]) == {"event": "withheld", "withheld_lines": 1}


def test_attachment_named_part_not_lost(cfg):
    pa, pb = b"first", b"second"
    atts = [{"name": n, "bytes": len(p), "sha256": hashlib.sha256(p).hexdigest()}
            for n, p in (("foo.part", pa), ("foo", pb))]
    r = call(cfg, ("msg_begin", {"msg_id": "mp", "body": "b", "from_session": "s", "attachments": atts}))[0]
    names = r["result"]["names"]
    assert len(names) == 2 and names[0] != "foo.part"
    reqs = [("put_chunk", {"msg_id": "mp", "name": n, "seq": 0, "data_b64": b64(p)})
            for n, p in zip(names, (pa, pb))]
    reqs.append(("msg_commit", {"msg_id": "mp"}))
    resp = call(cfg, *reqs)
    assert all(x["ok"] for x in resp), resp
    att = Path(cfg.mailbox_root) / "in" / "mp" / "attachments"
    assert (att / names[0]).read_bytes() == pa and (att / names[1]).read_bytes() == pb
    assert sorted(p.name for p in att.iterdir()) == sorted(names)
    assert not [p for p in att.iterdir() if p.name.endswith(".part")]
