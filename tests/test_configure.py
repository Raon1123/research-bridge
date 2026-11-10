from __future__ import annotations

import json
import subprocess

import pytest

from rb_host import cli as host_cli
from rb_host import configure as hc
from rb_node import cli as node_cli
from rb_node import configure as nc


def _git(d, *a):
    subprocess.run(["git", "-C", str(d)] + list(a), check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    _git(d, "init", "-q")
    (d / ".gitignore").write_text("host.json\n", encoding="utf-8")
    return d


def test_git_exposure(repo, tmp_path):
    assert nc.git_exposure(tmp_path / "outside.json") is None
    assert nc.git_exposure(repo / "host.json") is None
    assert "not ignored" in nc.git_exposure(repo / "node.json")
    (repo / "t.json").write_text("{}", encoding="utf-8")
    _git(repo, "add", "-f", "t.json")
    assert "tracked" in nc.git_exposure(repo / "t.json")


def test_write_refuses_trackable_path(repo):
    with pytest.raises(nc.ConfigError):
        nc.write_json(repo / "node.json", {"a": 1})
    assert not (repo / "node.json").exists()
    nc.write_json(repo / "host.json", {"a": 1})
    assert json.loads((repo / "host.json").read_text(encoding="utf-8")) == {"a": 1}


def test_repo_gitignore_covers_real_configs():
    for name in ("host.json", "node.json", "private/local.json", "deploy/node.json"):
        assert nc.git_exposure(hc.REPO / name) is None, name
    assert nc.git_exposure(hc.REPO / "local.example.json") is not None


def test_host_config_flow(tmp_path, monkeypatch, capsys):
    hp = tmp_path / "data" / "host.json"
    monkeypatch.setenv("RB_HOST_CONFIG", str(hp))
    assert host_cli.main(["config", "init"]) == 0
    assert host_cli.main(["config", "init"]) == 1  # exists, no --force
    assert host_cli.main(["config", "add-node", "node1"]) == 0
    assert host_cli.main(["config", "add-node", "bad name"]) == 1
    assert host_cli.main(["config", "set", "nodes.node1.board.state", "lab/STATE.md"]) == 0
    assert host_cli.main(["config", "set", "board.priorities", "D:/p.json"]) == 0
    assert host_cli.main(["config", "set", "nodes.node1.ssh_host", "x"]) == 1
    data = json.loads(hp.read_text(encoding="utf-8"))
    assert data["nodes"]["node1"] == {"alias": "rb-node1", "harness_alias": "rb-node1-harness",
                                      "board": {"state": "lab/STATE.md"}}
    assert data["board"] == {"priorities": "D:/p.json"}
    from rb_host.jobs import load_cfg
    assert load_cfg().alias("node1") == "rb-node1"
    assert host_cli.main(["config", "remove-node", "node1"]) == 0
    assert json.loads(hp.read_text(encoding="utf-8"))["nodes"] == {}


def test_host_check_reports(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("RB_HOST_CONFIG", str(tmp_path / "host.json"))
    monkeypatch.setattr(hc.Path, "home", lambda: tmp_path)
    assert host_cli.main(["config", "check"]) == 1
    assert "rb config init" in capsys.readouterr().out
    hc.init()
    hc.add_node("node1")
    assert host_cli.main(["config", "check"]) == 1
    out = capsys.readouterr().out
    assert "'rb-node1' is not a Host" in out and "MCP server not registered" in out


def test_mcp_entry_runs_through_uv():
    e = hc.mcp_entry()["research-bridge"]
    assert e["command"] == "uv" and e["args"][:2] == ["run", "--directory"]
    assert e["args"][-3:] == ["python", "-m", "rb_host.server"] and "--extra" in e["args"]


def test_node_config_flow(tmp_path, monkeypatch, capsys):
    p = tmp_path / "node.json"
    monkeypatch.setenv("RB_NODE_CONFIG", str(p))
    assert node_cli.main(["config", "show"]) == 1
    assert node_cli.main(["config", "init"]) == 0
    assert node_cli.main(["config", "init"]) == 1
    tpl = '["uv", "run", "train.py", "--config", "{config}"]'
    assert node_cli.main(["config", "set", "job_template", tpl]) == 0
    assert node_cli.main(["config", "set", "job_template", "not a list"]) == 1
    assert node_cli.main(["config", "set", "max_file", "1024"]) == 0
    assert node_cli.main(["config", "set", "harness_root", str(tmp_path)]) == 0
    # a provisioned node has a real ~/.research-bridge/approve.json
    assert node_cli.main(["config", "set", "approval_path", str(tmp_path / "none.json")]) == 0
    assert node_cli.main(["config", "set", "nope", "1"]) == 1
    from rb_node.config import load_config
    cfg = load_config()
    assert cfg.job_template[-1] == "{config}" and cfg.max_file == 1024
    capsys.readouterr()
    assert node_cli.main(["config", "check"]) == 1
    out = capsys.readouterr().out
    assert "job_template" not in out and "harness_root" not in out
    assert "approval verifier missing" in out


def test_node_check_template_placeholder():
    probs = nc.node_check({"job_template": ["python", "train.py"]})
    assert any("{config}" in p for p in probs)


def test_set_research_root_moves_dependent_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    data = nc.node_defaults()
    out = nc.node_set(data, "trm_root", "/srv/tree")
    assert out["trm_root"] == "/srv/tree"
    assert out["queue_dir"] == "/srv/tree/scripts/queue"
    assert "/srv/tree/scripts/queue/jobs" in out["write_roots"]
    assert data["write_roots"][0] in out["write_roots"]  # mailbox entry unchanged
    assert out["withheld_source"] == data["withheld_source"]  # already the new default
    # user-changed queue_dir is left alone
    data2 = dict(nc.node_defaults(), queue_dir="/custom/q")
    out2 = nc.node_set(data2, "trm_root", "/srv/tree")
    assert out2["queue_dir"] == "/custom/q"
    # same value: no cascade
    data3 = dict(nc.node_defaults(), queue_dir="/custom/q")
    assert nc.node_set(data3, "trm_root", data3["trm_root"]) == data3


def test_set_research_root_moves_old_withheld_default(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    from rb_node.config import default_dependents
    data = nc.node_defaults()
    data["withheld_source"] = default_dependents(data["trm_root"])["old_withheld"]
    out = nc.node_set(data, "trm_root", "/srv/tree")
    assert out["withheld_source"].endswith("/.research-bridge/withheld-patterns.json")


def test_tilde_expanded_in_path_keys(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    p = tmp_path / "node.json"
    monkeypatch.setenv("RB_NODE_CONFIG", str(p))
    assert node_cli.main(["config", "init"]) == 0
    assert node_cli.main(["config", "set", "trm_root", "~/x"]) == 0
    assert node_cli.main(["config", "set", "read_roots", '["~/a", "lab/b"]']) == 0
    from rb_node.config import load_config
    import json as _json
    stored = _json.loads(p.read_text(encoding="utf-8"))
    assert stored["trm_root"] == str(home / "x")
    assert stored["read_roots"] == [str(home / "a"), "lab/b"]
    stored["queue_dir"] = "~/q"
    p.write_text(_json.dumps(stored), encoding="utf-8")
    assert load_config().queue_dir == str(home / "q")


def test_default_withheld_source_is_json(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    from rb_node.config import NodeConfig
    assert NodeConfig().withheld_source.endswith("/.research-bridge/withheld-patterns.json")


def test_default_config_paths_follow_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    from rb_node.config import NodeConfig, PATH_KEYS, PATH_LIST_KEYS
    cfg = NodeConfig()
    for k in PATH_KEYS:
        v = getattr(cfg, k)
        if v and v.startswith("/"):
            assert v.startswith(str(home)), k
    for k in PATH_LIST_KEYS:
        for v in getattr(cfg, k):
            if v.startswith("/"):
                assert v.startswith(str(home)), (k, v)
