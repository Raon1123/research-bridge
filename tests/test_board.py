"""Unified board (design docs/design/2026-11-02-unified-board.md §10). Local subprocess node only."""
from __future__ import annotations

import hashlib
import json
import socket
import sys
from pathlib import Path

import pytest

from rb_host import board, cli, jobs
from rb_host.client import NodeClient
from rb_host.ledger import Ledger

SERVE = [sys.executable, "-m", "rb_node.cli", "serve-remote"]
REPO = Path(__file__).resolve().parents[1]

STATE_MD = "---\nphase: S5\ntrack: ARG\nupdated: 2026-11-02\nnote: H108N rerun\n---\n# State\nbody text\n"
EVENTS = [
    {"ts": "2026-11-02T09:00:00Z", "stage": "S5", "kind": "monitor", "track": "ARG",
     "msg": "free text is dropped"},
    {"ts": "2026-11-02T09:30:00Z", "stage": "S6", "kind": "analysis", "track": "pp_seedext_7"},
]
KANBAN = {"cards": [{"column": "doing", "title": "a"}, {"column": "doing", "title": "b"},
                    {"column": "todo", "title": "c"}]}


@pytest.fixture
def env(tmp_path, monkeypatch):
    trm = tmp_path / "trm"
    for d in ("lab/state", "lab/monitor", "scripts/queue/jobs", "scripts/queue/done"):
        (trm / d).mkdir(parents=True)
    (trm / "lab/state/STATE.md").write_text(STATE_MD, encoding="utf-8")
    # JSON lines under a .json name: the node masks line by line, so a hit drops one record.
    # A real events.jsonl is denied by the node (.jsonl is not a scannable text type).
    (trm / "lab/monitor/events.json").write_text(
        "\n".join(json.dumps(e) for e in EVENTS) + "\n", encoding="utf-8")
    (trm / "lab/monitor/events.jsonl").write_text(json.dumps(EVENTS[0]) + "\n", encoding="utf-8")
    (trm / "lab/monitor/kanban.json").write_text(json.dumps(KANBAN), encoding="utf-8")
    (trm / "scripts/queue/jobs/0002_b.job").write_text("x", encoding="utf-8")
    (trm / "scripts/queue/done/0001_a.job").write_text("x", encoding="utf-8")
    mb = tmp_path / "rb" / "mailbox"
    conf = {"trm_root": str(trm), "read_roots": ["lab/state", "lab/monitor", str(mb / "out")],
            "write_roots": [str(mb / "in")], "queue_dir": str(trm / "scripts" / "queue"),
            "withheld_source": None, "claude_bin": str(tmp_path / "no-such-claude"),
            "mailbox_root": str(mb), "audit_path": str(tmp_path / "rb" / "audit.jsonl")}
    nodecfg = tmp_path / "node.json"
    nodecfg.write_text(json.dumps(conf), encoding="utf-8")
    wp = tmp_path / "withheld.json"
    wp.write_text(json.dumps({"patterns": []}), encoding="utf-8")
    portfolio = tmp_path / "portfolio.json"
    portfolio.write_bytes(json.dumps({
        "columns": ["ready", "gated"],
        "papers": [{"paper_id": "p0", "short": "P0", "column": "ready",
                    "tasks": [{"task_id": "p0-T1", "title": "decide x", "status": "todo",
                               "user_action": True},
                              {"task_id": "p0-T2", "title": "done", "status": "done",
                               "user_action": True}]},
                   {"paper_id": "p1", "short": "P1", "column": "gated", "tasks": []}]},
        indent=2).replace("\n", "\r\n").encode("utf-8"))
    live = tmp_path / "live.json"
    live.write_text(json.dumps({
        "meta": {"refreshed": "2026-11-03 11:02"},
        "items": [{"key": "K1", "title": "approve thing", "actor": "user", "status": "open"},
                  {"key": "K2", "title": "server item", "actor": "server", "status": "open"}],
        "ranking": {"tiers": [{"tier": "now", "keys": ["K1", "K2"]},
                              {"tier": "later", "keys": []}]}}), encoding="utf-8")
    root = tmp_path / "data"
    host = tmp_path / "host.json"
    host.write_text(json.dumps({
        "nodes": {"n1": {"alias": "x", "board": {"state": "lab/state/STATE.md",
                                                  "events": "lab/monitor/events.json",
                                                  "kanban": "lab/monitor/kanban.json"}}},
        "data_root": str(root), "withheld_patterns_file": str(wp),
        "board": {"portfolio": str(portfolio), "priorities": str(live)}}), encoding="utf-8")
    monkeypatch.setenv("RB_HOST_CONFIG", str(host))
    nenv = {"RB_NODE_CONFIG": str(nodecfg), "PYTHONPATH": str(REPO)}
    calls = []

    def connect(cfg, node):
        calls.append(node)
        return NodeClient("x", ssh_argv=SERVE, env=nenv)

    monkeypatch.setattr(jobs, "connect", connect)
    led = Ledger(root / "ledger.jsonl")
    led.append({"kind": "job", "op": "submit", "id": "j1", "node": "n1", "config_name": "c.yaml",
                "gpus": [0], "gpu_hours": 1, "status": "pending_approval", "created": "t"})
    led.append({"kind": "job", "op": "submit", "id": "j0", "node": "n1", "status": "queued",
                "created": "t"})
    led.append({"kind": "message", "id": "m-in", "direction": "in", "node": "n1",
                "msg_kind": "reply", "status": "received", "created": "t"})
    led.append({"kind": "message", "id": "m-ev", "direction": "in", "node": "n1",
                "msg_kind": "event", "status": "received", "created": "t"})
    return {"tmp": tmp_path, "root": root, "calls": calls, "portfolio": portfolio, "live": live,
            "ledger": led, "cfg": jobs.load_cfg()}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _by_id(b: dict) -> dict:
    return {s["source"]: s for s in b["sources"]}


def test_all_sources_rendered(env):
    board.refresh(env["cfg"])
    b = board.load(env["cfg"])
    ids = set(_by_id(b))
    assert ids == {"rb:ledger", "n1:queue", "n1:gpu", "n1:state", "n1:events", "n1:kanban",
                   "vault:portfolio", "vault:priorities"}
    s = _by_id(b)
    assert s["n1:state"]["ok"] and s["n1:state"]["items"][0]["phase"] == "S5"
    assert {"state": "jobs", "count": 1} in s["n1:queue"]["items"]
    assert {"column": "doing", "count": 2} in s["n1:kanban"]["items"]
    assert {"column": "ready", "count": 1} in s["vault:portfolio"]["items"]
    text = board.render_text(b)
    for sid in ids:
        assert sid in text


def test_waiting_on_user_first(env):
    board.refresh(env["cfg"])
    b = board.load(env["cfg"])
    waits = b["waiting"]
    refs = [w["ref"] for w in waits]
    assert refs[0] == "j1"  # pending approval first
    assert "m-in" in refs and "m-ev" not in refs  # events need no answer
    assert "p0" in refs and "p1" not in refs  # one line per paper with open user tasks
    assert [w["what"] for w in waits if w["ref"] == "p0"] == ["P0: 1 open user tasks on /portfolio"]
    assert "K1" in refs and "K2" not in refs
    # an outgoing message that answers m-in clears it
    env["ledger"].append({"kind": "message", "id": "m-out", "direction": "out", "node": "n1",
                          "reply_to": "m-in", "status": "sent", "created": "t"})
    assert "m-in" not in [w["ref"] for w in board.load(env["cfg"])["waiting"]]
    assert board.render_text(b).index("Waiting on you") < board.render_text(b).index("rb:ledger")


def test_waiting_text_from_ledger_is_cleaned_sec03(env):
    # D4: ledger text is written by a hub session; the board strips control and bidi characters
    env["ledger"].append({"kind": "job", "op": "sub\x1b[2Jmit", "id": "j‮9", "node": "n\x071",
                          "config_name": "evil‮\x1b[31m.yaml", "gpus": [0],
                          "gpu_hours": "1\x1b]0;x\x07", "status": "pending_approval",
                          "created": "t"})
    env["ledger"].append({"kind": "job", "op": "cancel", "id": "j8", "node": "n1",
                          "target_job_id": "t‮\x1bx", "status": "pending_approval",
                          "created": "t"})
    env["ledger"].append({"kind": "message", "id": "m‮2", "direction": "in",
                          "node": "n\x1b1", "msg_kind": "rep‮ly", "status": "received",
                          "created": "t"})
    b = board.load(env["cfg"])
    shown = json.dumps(b["waiting"], ensure_ascii=False) + board.render_text(b)
    for bad in ("\x1b", "\x07", "‮"):
        assert bad not in shown
    whats = [w["what"] for w in b["waiting"]]
    assert "approve sub[2Jmit job on n1 (evil[31m.yaml, 1]0;x GPU-h) at /rb/pending" in whats
    assert "approve cancel job on n1 (tx,  GPU-h) at /rb/pending" in whats
    assert "unanswered reply from n1" in whats
    assert {"j9", "m2"} <= {w["ref"] for w in b["waiting"]}


def test_node_sources_use_bridge_only(env, monkeypatch):
    real = socket.socket

    def guarded(*a, **k):
        raise AssertionError("board opened a socket")

    monkeypatch.setattr(socket, "socket", guarded)
    try:
        board.refresh(env["cfg"])
    finally:
        monkeypatch.setattr(socket, "socket", real)
    assert env["calls"] and set(env["calls"]) == {"n1"}
    # load never connects
    env["calls"].clear()
    board.load(env["cfg"])
    assert env["calls"] == []


def test_failed_source_shows_error(env):
    cfg = env["cfg"]
    cfg.nodes["n1"]["board"]["state"] = "lab/state/MISSING.md"
    board.refresh(cfg)
    s = _by_id(board.load(cfg))
    assert s["n1:state"]["ok"] is False and s["n1:state"]["error"] == "not_found"
    assert s["n1:state"]["items"] == []
    # a source never fetched is reported, not shown as current
    (env["root"] / "board" / "n1_gpu.json").unlink()
    s = _by_id(board.load(cfg))
    assert s["n1:gpu"]["ok"] is False and s["n1:gpu"]["error"] == "never_fetched"


def test_events_jsonl_denied_by_node(env):
    cfg = env["cfg"]
    cfg.nodes["n1"]["board"]["events"] = "lab/monitor/events.jsonl"
    board.refresh(cfg)
    s = _by_id(board.load(cfg))
    assert s["n1:events"]["ok"] is False and s["n1:events"]["items"] == []


def test_unconfigured_node_source_is_reported(env):
    cfg = env["cfg"]
    del cfg.nodes["n1"]["board"]["kanban"]
    board.refresh(cfg)
    s = _by_id(board.load(cfg))
    assert s["n1:kanban"]["error"] == "no_path" and env["calls"].count("n1") == 4


def test_stale_source(env):
    board.refresh(env["cfg"])
    p = env["root"] / "board" / "n1_queue.json"
    rec = json.loads(p.read_text(encoding="utf-8"))
    rec["fetched_at"] = "2000-01-01T00:00:00Z"
    p.write_text(json.dumps(rec), encoding="utf-8")
    s = _by_id(board.load(env["cfg"]))
    assert s["n1:queue"]["stale"] is True and s["n1:gpu"]["stale"] is False


def test_sources_unchanged(env):
    files = [env["portfolio"], env["live"], env["root"] / "ledger.jsonl"]
    before = [_sha(f) for f in files]
    board.refresh(env["cfg"])
    board.load(env["cfg"])
    board.render_text(board.load(env["cfg"]))
    assert [_sha(f) for f in files] == before


def test_withheld_event_dropped(env):
    board.refresh(env["cfg"])
    s = _by_id(board.load(env["cfg"]))
    ev = s["n1:events"]["items"]
    assert ev == [{"ts": "2026-11-02T09:00:00Z", "stage": "S5", "kind": "monitor", "track": "ARG"}]
    st = s["n1:state"]["items"][0]
    assert "note" not in st  # STATE.md line hit by a fallback pattern: blanked on node and hub
    for f in env["root"].rglob("*"):  # the whole data root, fetched/ included
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8")
        assert "pp_seedext" not in text and "H108N" not in text and "free text" not in text


def test_laptop_recheck_drops_what_node_let_through():
    wh = board._withheld_from(["secretfam_"])
    items = board.reduce_events(json.dumps([{"ts": "1", "stage": "S1", "kind": "k",
                                             "track": "secretfam_x"},
                                            {"ts": "2", "stage": "S2"}]), wh)
    assert items == [{"ts": "2", "stage": "S2"}]
    st = board.reduce_state("---\na: ok\nb: secretfam_1\n---\n", wh)
    assert st == [{"a": "ok"}]


def test_events_jsonl_parsed():
    wh = board._withheld_from([])
    text = '{"ts": "1", "stage": "S1"}\nnot json\n{"ts": "2", "id": "e2"}\n'
    assert board.reduce_events(text, wh) == [{"ts": "2", "id": "e2"}, {"ts": "1", "stage": "S1"}]


def test_audit_has_no_payload(env):
    board.refresh(env["cfg"])
    lines = (env["root"] / "board" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5
    for line in lines:
        rec = json.loads(line)
        assert set(rec) == {"ts", "source", "bytes", "sha256", "result"}


def test_cli_refresh_and_show(env, capsys):
    assert cli.main(["board", "refresh"]) == 0
    out = capsys.readouterr().out
    assert "n1:state ok" in out
    assert cli.main(["board", "show"]) == 0
    out = capsys.readouterr().out
    assert "Waiting on you" in out and "j1" in out
    assert cli.main(["board", "show", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["waiting"][0]["ref"] == "j1"


def test_cli_refresh_one_source(env, capsys):
    assert cli.main(["board", "refresh", "--source", "gpu"]) == 0
    assert env["calls"] == ["n1"]
    assert not (env["root"] / "board" / "n1_queue.json").exists()


def test_no_host_config_load_is_empty(tmp_path, monkeypatch):
    from rb_host.config import HostConfig
    b = board.load(HostConfig(data_root=str(tmp_path), board={
        "portfolio": str(tmp_path / "none.json"), "priorities": str(tmp_path / "none.json")}))
    s = _by_id(b)
    assert s["vault:portfolio"]["ok"] is False and s["vault:portfolio"]["error"] == "missing"
    assert s["rb:ledger"]["ok"] is True


def test_failed_source_keeps_previous_items(env):
    cfg = env["cfg"]
    board.refresh(cfg, "n1", ["state"])
    before = json.loads((env["root"] / "board" / "n1_state.json").read_text(encoding="utf-8"))
    assert before["ok"] and before["items"] and before["attempted_at"] == before["fetched_at"]
    cfg.nodes["n1"]["board"]["state"] = "lab/state/MISSING.md"
    board.refresh(cfg, "n1", ["state"])
    after = json.loads((env["root"] / "board" / "n1_state.json").read_text(encoding="utf-8"))
    assert after["items"] == before["items"] and after["ok"] is False
    assert after["error"] == "not_found"
    assert after["fetched_at"] == before["fetched_at"] and after["attempted_at"]


def test_failed_source_without_previous_has_null_fetched_at(env):
    cfg = env["cfg"]
    cfg.nodes["n1"]["board"]["state"] = "lab/state/MISSING.md"
    board.refresh(cfg, "n1", ["state"])
    rec = json.loads((env["root"] / "board" / "n1_state.json").read_text(encoding="utf-8"))
    assert rec["fetched_at"] is None and rec["items"] == [] and rec["attempted_at"]


def test_vault_defaults_omitted_on_linux(tmp_path):
    import os
    from rb_host.config import HostConfig
    if os.name == "nt":
        pytest.skip("Windows keeps the vault defaults")
    b = board.load(HostConfig(data_root=str(tmp_path)))
    ids = {s["source"] for s in b["sources"]}
    assert "vault:portfolio" not in ids and "vault:priorities" not in ids
    assert "rb:ledger" in ids
