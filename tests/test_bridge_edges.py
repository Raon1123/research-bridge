"""Session-browser bridge edges (this repo's vault-export copy; the user applies it to the vault).
Fixture ledger only."""
from __future__ import annotations

import json
import sys
from pathlib import Path

VAULT = Path(__file__).resolve().parents[1] / "vault-export" / "session-calendar"
sys.path.insert(0, str(VAULT))
import bridge_edges  # noqa: E402

SID = "aaaaaaaa-1111-2222-3333-444444444444"


def _ledger(tmp_path):
    p = tmp_path / "ledger.jsonl"
    recs = [
        {"kind": "message", "id": "m1", "direction": "out", "node": "node1",
         "reply_to": None, "from_session": SID, "attachments": ["a.txt", "b.pdf"],
         "attachment_bytes": 300, "body": "SECRET-BODY", "body_chars": 11,
         "status": "pending_send", "created": "2026-10-27T01:00:00Z"},
        {"kind": "message", "id": "m1", "direction": "out", "node": "node1",
         "reply_to": None, "from_session": SID, "attachments": ["a.txt", "b.pdf"],
         "attachment_bytes": 300, "body": "SECRET-BODY", "body_chars": 11,
         "status": "sent", "created": "2026-10-27T01:00:00Z"},
        {"kind": "message", "id": "r1", "direction": "in", "node": "node1",
         "msg_kind": "reply", "reply_to": "m1", "files": ["x.csv"],
         "quarantined": 0, "body": "SECRET-REPLY", "status": "received",
         "created": "2026-10-27T01:05:00Z"},
        {"kind": "job", "id": "j1", "op": "submit", "node": "node1",
         "status": "pending_approval", "created": "2026-10-27T01:06:00Z"},
    ]
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    return p


def _keys(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from _keys(v)
    elif isinstance(o, list):
        for v in o:
            yield from _keys(v)


def test_two_edges_no_body(tmp_path):
    edges = bridge_edges.build_edges(_ledger(tmp_path))
    assert len(edges) == 2  # job without a session is not attributed
    assert all(e["kind"] == "bridge" for e in edges)
    assert "body" not in set(_keys(edges))
    assert "SECRET" not in json.dumps(edges)
    out = next(e for e in edges if e["msg_id"] == "m1")
    assert out["sid"] == SID and out["peer"] == "node1:responder"
    assert out["attachments"] == 2 and out["bytes"] == 300
    assert out["from"] == "main" and out["to"] == "ext:node1:responder"
    rep = next(e for e in edges if e["msg_id"] == "r1")
    assert rep["sid"] == SID and rep["from"] == "ext:node1:responder" and rep["to"] == "main"
    assert rep["attachments"] == 1 and rep["t"] > out["t"]


def test_merge_skips_missing_cache_and_never_creates(tmp_path):
    edges = bridge_edges.build_edges(_ledger(tmp_path))
    cache = tmp_path / "agents"
    cache.mkdir()
    res = bridge_edges.merge(edges, cache)
    assert res == {"merged": 0, "skipped": 2}
    assert list(cache.iterdir()) == []


def test_merge_existing_cache_idempotent(tmp_path):
    edges = bridge_edges.build_edges(_ledger(tmp_path))
    cache = tmp_path / "agents"
    cache.mkdir()
    base = {"sid": SID, "lanes": [{"id": "main", "kind": "main"}], "events": [
        {"kind": "send", "from": "main", "to": "x", "t": 1.0}], "counts": {"send": 1}}
    (cache / (SID + ".json")).write_text(json.dumps(base), encoding="utf-8")
    for _ in range(2):
        assert bridge_edges.merge(edges, cache) == {"merged": 2, "skipped": 0}
    g = json.loads((cache / (SID + ".json")).read_text(encoding="utf-8"))
    assert sum(1 for e in g["events"] if e["kind"] == "bridge") == 2
    assert g["counts"]["bridge"] == 2 and g["counts"]["send"] == 1
    assert [l["id"] for l in g["lanes"]].count("ext:node1:responder") == 1
    assert "body" not in set(_keys(g))


def test_missing_ledger_gives_no_edges(tmp_path):
    assert bridge_edges.build_edges(tmp_path / "nope.jsonl") == []


def test_merge_skips_unsafe_session_ids(tmp_path):
    # SEC-07: a ledger-supplied session id must never become a path
    cache = tmp_path / "agents"
    cache.mkdir()
    (tmp_path / "x.json").write_text("{}", encoding="utf-8")
    edge = {"kind": "bridge", "from": "main", "to": "ext:n:r", "t": 1.0, "msg_id": "m"}
    bad = ["../x", "..\\x", "x" * 36, SID.upper(), SID + "\n", SID[:-1], ""]
    edges = [dict(edge, sid=b) for b in bad]
    assert bridge_edges.merge(edges, cache) == {"merged": 0, "skipped": len(bad)}
    assert (tmp_path / "x.json").read_text(encoding="utf-8") == "{}"
    assert list(cache.iterdir()) == []
