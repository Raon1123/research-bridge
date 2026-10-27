from __future__ import annotations

from rb_host.ledger import Ledger


def test_append_dedupes(tmp_path):
    lg = Ledger(tmp_path / "l" / "ledger.jsonl")
    rec = {"kind": "message", "id": "m1", "body": "hi"}
    assert lg.append(rec) is True
    assert lg.append(dict(rec)) is False
    assert lg.append({"kind": "job", "id": "m1"}) is True  # different kind, same id
    assert len((tmp_path / "l" / "ledger.jsonl").read_text().splitlines()) == 2


def test_update_last_line_wins(tmp_path):
    lg = Ledger(tmp_path / "ledger.jsonl")
    lg.append({"kind": "job", "id": "j1", "status": "pending_approval"})
    lg.append({"kind": "job", "id": "j2", "status": "pending_approval"})
    assert [r["id"] for r in lg.pending_jobs()] == ["j1", "j2"]
    lg.update("j1", status="approved")
    assert lg.get("j1")["status"] == "approved"
    assert [r["id"] for r in lg.pending_jobs()] == ["j2"]
    assert len((tmp_path / "ledger.jsonl").read_text().splitlines()) == 3


def test_thread_and_torn_line(tmp_path):
    p = tmp_path / "ledger.jsonl"
    lg = Ledger(p)
    lg.append({"kind": "message", "id": "m1"})
    lg.append({"kind": "reply", "id": "r1", "reply_to": "m1"})
    lg.append({"kind": "message", "id": "m2"})
    with open(p, "ab") as fh:
        fh.write(b'{"kind": "message", "id": "m3"')  # crash mid-write
    assert {r["id"] for r in lg.thread("m1")} == {"m1", "r1"}
    assert lg.get("m3") is None
