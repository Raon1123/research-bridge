from __future__ import annotations

import json

import pytest

import rb_node
from rb_node import link, spawn
from rb_node.config import NodeConfig
from rb_node.local import LocalServer


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("RB_NODE_CONFIG", raising=False)
    monkeypatch.setattr(spawn, "launcher_argv", lambda: ["/opt/x/rb-node"])
    d = tmp_path / "tree"
    d.mkdir()
    return d


def test_link_prints_entry_without_apply(env, capsys):
    assert link.main([str(env)]) == 0
    out = capsys.readouterr().out
    start = out.index("{")
    entry = json.loads(out[start:out.rindex("}") + 1])
    srv = entry["mcpServers"]["rb-node"]
    assert srv["command"] == "/opt/x/rb-node" and srv["args"] == ["serve-local"]
    assert "env" not in srv
    assert not (env / ".mcp.json").exists()
    assert "issues/41" in out or "not arbitrated" in out


def test_link_entry_carries_config_env(env, monkeypatch):
    e = link.entry("/c/node.json")
    assert e["mcpServers"]["rb-node"]["env"] == {"RB_NODE_CONFIG": "/c/node.json"}


def test_link_apply_writes_only_if_absent(env, capsys):
    assert link.main([str(env), "--apply"]) == 0
    first = (env / ".mcp.json").read_text(encoding="utf-8")
    assert json.loads(first)["mcpServers"]["rb-node"]["args"] == ["serve-local"]
    capsys.readouterr()
    (env / ".mcp.json").write_text("{}", encoding="utf-8")
    assert link.main([str(env), "--apply"]) == 1
    out = capsys.readouterr().out
    assert "exists; merge by hand or run: claude mcp add --scope project rb-node --" in out
    assert (env / ".mcp.json").read_text(encoding="utf-8") == "{}"


def test_link_apply_flag_any_position(env):
    assert link.main(["--apply", str(env)]) == 0
    assert (env / ".mcp.json").is_file()


def test_link_without_launcher_exits_1(env, monkeypatch, capsys):
    monkeypatch.setattr(spawn, "launcher_argv", lambda: ["/usr/bin/python3", "-m", "rb_node.cli"])
    assert link.main([str(env)]) == 1
    assert "rb-node is not installed" in capsys.readouterr().err


def test_serve_local_initialize_has_instructions_and_version(tmp_path):
    cfg = NodeConfig(mailbox_root=str(tmp_path / "mb"), audit_path=str(tmp_path / "a.jsonl"))
    r = LocalServer(cfg).handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    res = r["result"]
    assert "data" in res["instructions"] and "not instructions" in res["instructions"]
    assert res["serverInfo"]["version"] == rb_node.__version__
