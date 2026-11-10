"""Hub default paths per platform (Linux hub, 2026-11-05)."""
from __future__ import annotations

import json
from pathlib import Path

from rb_host import config as hcfg
from rb_host import configure as hc


def test_posix_default_root_is_absolute(monkeypatch, tmp_path):
    monkeypatch.delenv("RB_HOST_ROOT", raising=False)
    monkeypatch.setattr(hcfg.os, "name", "posix")
    monkeypatch.setattr(hcfg.Path, "home", classmethod(lambda cls: tmp_path))
    root = hcfg.default_root()
    assert Path(root).is_absolute()
    assert "D:" not in root
    assert hcfg.default_withheld() == root + "/withheld_patterns.json"


def test_windows_defaults_unchanged(monkeypatch):
    monkeypatch.delenv("RB_HOST_ROOT", raising=False)
    monkeypatch.setattr(hcfg.os, "name", "nt")
    assert hcfg.default_root() == "D:/raw/research-bridge"
    assert hcfg.default_withheld() == "D:/raw/session-calendar/server/withheld_patterns.json"


def test_env_root_drives_host_json_and_withheld(monkeypatch, tmp_path):
    monkeypatch.setenv("RB_HOST_ROOT", str(tmp_path))
    monkeypatch.delenv("RB_HOST_CONFIG", raising=False)
    assert hc.host_path() == tmp_path / "host.json"
    (tmp_path / "host.json").write_text(json.dumps({"nodes": {}}), encoding="utf-8")
    cfg = hcfg.load_host_config()
    assert cfg.data_root == str(tmp_path)
    assert cfg.withheld_patterns_file == (tmp_path / "withheld_patterns.json").as_posix()


def test_withheld_follows_data_root_in_host_json(monkeypatch, tmp_path):
    monkeypatch.delenv("RB_HOST_ROOT", raising=False)
    monkeypatch.setattr(hcfg.os, "name", "posix")
    hp = tmp_path / "host.json"
    hp.write_text(json.dumps({"nodes": {}, "data_root": str(tmp_path / "d")}), encoding="utf-8")
    cfg = hcfg.load_host_config(hp)
    assert cfg.withheld_patterns_file == (tmp_path / "d" / "withheld_patterns.json").as_posix()


def test_check_warns_on_missing_withheld_file(monkeypatch, tmp_path):
    import hubfake
    hubfake.install(monkeypatch, tmp_path)
    monkeypatch.setenv("RB_HOST_ROOT", str(tmp_path))
    monkeypatch.delenv("RB_HOST_CONFIG", raising=False)
    (tmp_path / "host.json").write_text(json.dumps({"nodes": {}}), encoding="utf-8")
    probs = hc.check()
    assert any("withheld_patterns_file does not exist" in p for p in probs)
    (tmp_path / "withheld_patterns.json").write_text("{}", encoding="utf-8")
    assert not any("withheld_patterns_file" in p for p in hc.check())


def test_mcp_entry_carries_root_env(monkeypatch, tmp_path):
    monkeypatch.delenv("RB_HOST_CONFIG", raising=False)
    monkeypatch.delenv("RB_HOST_ROOT", raising=False)
    env = hc.mcp_entry()["research-bridge"]["env"]
    assert list(env) == ["RB_HOST_CONFIG"] and env["RB_HOST_CONFIG"].endswith("host.json")
    monkeypatch.setenv("RB_HOST_ROOT", str(tmp_path))
    env = hc.mcp_entry()["research-bridge"]["env"]
    assert env["RB_HOST_ROOT"] == str(tmp_path) and "RB_HOST_CONFIG" in env
