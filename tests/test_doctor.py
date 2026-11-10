from __future__ import annotations

import json
from pathlib import Path

import pytest

import hubfake
import rb_node
from rb_host import cli, client, configure, doctor, service, sshenv
from rb_host.client import RemoteError, TransportError


@pytest.fixture
def hub(monkeypatch, tmp_path):
    return hubfake.install(monkeypatch, tmp_path)


def _complete(hub, monkeypatch, tmp_path):
    """A hub on which every offline check is ok."""
    hubfake.linked(hub)
    key = hub.ssh_dir / "research-bridge" / "node1_ed25519"
    hkey = hub.ssh_dir / "research-bridge" / "node1_harness_ed25519"
    hub.add_agent("rb-ssh-agent", [hub.pub_fp(key), hub.pub_fp(hkey)])
    local = tmp_path / "local.json"
    local.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(configure, "local_path", lambda: local)
    uv = tmp_path / "uv"
    uv.write_text("", encoding="utf-8")
    cj = configure.claude_json_path()
    cj.write_text(json.dumps({"mcpServers": {"research-bridge": _entry(uv)}}), encoding="utf-8")
    d = hub.home / ".config" / "systemd" / "user"
    d.mkdir(parents=True)
    for n in service.UNIT_NAMES:
        (d / n).write_text("OnUnitInactiveSec=300\n", encoding="utf-8")
    hub.linger_value = "yes"
    hub.systemctl.update({("is-enabled", "rb-sync.timer"): (0, "enabled", ""),
                          ("is-active", "rb-sync.timer"): (0, "active", ""),
                          ("is-active", "rb-web.service"): (0, "active", "")})
    return hub


def by_id(results):
    out = {}
    for r in results:
        out.setdefault(r.id, []).append(r)
    return out


def test_offline_missing_host_json_is_fail_with_setup_hint(hub):
    res = doctor.offline()
    r = by_id(res)["host_json"][0]
    assert r.level == "fail" and r.next.startswith("rb setup")


def test_offline_all_ok(hub, monkeypatch, tmp_path):
    _complete(hub, monkeypatch, tmp_path)
    res = doctor.offline()
    assert [r for r in res if r.level != "ok"] == []
    ids = [r.id for r in res]
    assert ids[:4] == ["host_json", "host_json_git", "data_root", "nodes"]
    assert "linger" in ids and "agent_location" in ids and "sync_status" not in ids


def test_offline_alias_unknown_fail(hub, monkeypatch, tmp_path):
    _complete(hub, monkeypatch, tmp_path)
    hub.write_config("")
    r = by_id(doctor.offline())["alias"][0]
    assert r.level == "fail" and "ssh has no Host block for rb-node1" in r.message and r.node == "node1"


def test_offline_ssh_g_failure_message(hub, monkeypatch, tmp_path):
    _complete(hub, monkeypatch, tmp_path)
    hub.ssh_g_fail = True
    r = by_id(doctor.offline())["alias"][0]
    assert r.level == "fail" and r.message == "ssh -G failed for rb-node1"


def test_offline_harness_alias_missing_warn(hub, monkeypatch, tmp_path):
    _complete(hub, monkeypatch, tmp_path)
    text = hub.config_path.read_text(encoding="utf-8").replace("Host rb-node1-harness", "Host other")
    hub.write_config(text)
    res = doctor.offline()
    assert by_id(res)["alias_harness"][0].level == "warn"
    assert doctor.exit_code(res) == 0


def test_offline_key_not_loaded_fail(hub, monkeypatch, tmp_path):
    _complete(hub, monkeypatch, tmp_path)
    hkey = hub.ssh_dir / "research-bridge" / "node1_harness_ed25519"
    for s in hub.agents:
        hub.agents[s] = [hub.pub_fp(hkey)]
    r = by_id(doctor.offline())["key_loaded"][0]
    assert r.level == "fail" and r.next == "rb agent --node node1"
    assert by_id(doctor.offline())["key_loaded_harness"][0].level == "ok"


def test_offline_no_agent_with_unencrypted_key_is_warn(hub, monkeypatch, tmp_path):
    _complete(hub, monkeypatch, tmp_path)
    hub.agents.clear()
    hub.unencrypted.update(str(hub.ssh_dir / "research-bridge" / n)
                           for n in ("node1_ed25519", "node1_harness_ed25519"))
    res = by_id(doctor.offline())
    assert res["agent"][0].level == "warn"
    assert res["key_loaded"][0].level == "ok"


def test_offline_no_agent_with_encrypted_key_is_fail(hub, monkeypatch, tmp_path):
    _complete(hub, monkeypatch, tmp_path)
    hub.agents.clear()
    r = by_id(doctor.offline())["agent"][0]
    assert r.level == "fail" and r.next == "rb agent"


def test_offline_key_only_in_inherited_agent_warns(hub, monkeypatch, tmp_path):
    _complete(hub, monkeypatch, tmp_path)
    key = hub.ssh_dir / "research-bridge" / "node1_ed25519"
    hub.agents.clear()
    hub.add_agent("agent.1", [hub.pub_fp(key)], runtime=False)
    res = by_id(doctor.offline())
    assert res["key_loaded"][0].level == "ok"
    loc = res["agent_location"][0]
    assert loc.level == "warn" and "unattended sync and other shells cannot use it" in loc.message
    assert loc.next == "rb agent --node node1"


def test_offline_known_host_missing_fail(hub, monkeypatch, tmp_path):
    _complete(hub, monkeypatch, tmp_path)
    (hub.ssh_dir / "known_hosts").write_text("", encoding="utf-8")
    assert by_id(doctor.offline())["known_host"][0].level == "fail"


def test_offline_key_file_problems(hub, monkeypatch, tmp_path):
    _complete(hub, monkeypatch, tmp_path)
    key = hub.ssh_dir / "research-bridge" / "node1_ed25519"
    key.chmod(0o640)
    r = by_id(doctor.offline())["key_file"][0]
    assert r.level == "fail" and "mode" in r.message and r.next == "chmod 600 %s" % key
    key.chmod(0o600)
    Path(str(key) + ".pub").unlink()
    assert "public key missing" in by_id(doctor.offline())["key_file"][0].message
    key.unlink()
    assert "key file missing" in by_id(doctor.offline())["key_file"][0].message


def test_offline_withheld_missing_or_empty_fail(hub, monkeypatch, tmp_path, capsys):
    _complete(hub, monkeypatch, tmp_path)
    wp = tmp_path / "data" / "withheld_patterns.json"
    wp.unlink()
    r = by_id(doctor.offline())["withheld_hub"][0]
    assert r.level == "fail" and "does not exist" in r.message
    assert cli.main(["config", "check"]) == 1
    assert "withheld_patterns_file does not exist" in capsys.readouterr().out
    wp.write_text("{}", encoding="utf-8")
    r = by_id(doctor.offline())["withheld_hub"][0]
    assert r.level == "fail" and "has no pattern" in r.message
    wp.write_text('{"patterns": ["ok_[0-9]", "(unclosed"]}', encoding="utf-8")
    r = by_id(doctor.offline())["withheld_hub"][0]
    assert r.level == "fail" and "1 pattern(s) do not compile (indexes 1)" in r.message
    wp.write_text("{", encoding="utf-8")
    assert "not valid JSON" in by_id(doctor.offline())["withheld_hub"][0].message


def test_offline_local_json_missing_is_warn(hub, monkeypatch, tmp_path):
    _complete(hub, monkeypatch, tmp_path)
    monkeypatch.setattr(configure, "local_path", lambda: tmp_path / "nope.json")
    assert by_id(doctor.offline())["local_json"][0].level == "warn"


def _entry(uv):
    e = dict(configure.mcp_entry()["research-bridge"])
    e["command"] = str(uv)
    return e


def test_offline_mcp_entry_project_scope_found(hub, monkeypatch, tmp_path):
    _complete(hub, monkeypatch, tmp_path)
    uv = tmp_path / "uv"
    configure.claude_json_path().write_text(json.dumps({"projects": {str(configure.REPO): {
        "mcpServers": {"research-bridge": _entry(uv)}}}}), encoding="utf-8")
    assert by_id(doctor.offline())["mcp_entry"][0].level == "ok"


def test_offline_mcp_entry_problems(hub, monkeypatch, tmp_path):
    _complete(hub, monkeypatch, tmp_path)
    cj = configure.claude_json_path()
    cj.write_text("{}", encoding="utf-8")
    r = by_id(doctor.offline())["mcp_entry"][0]
    assert r.level == "warn" and r.message == "MCP server not registered"
    assert r.next.startswith("claude mcp add-json --scope user research-bridge")
    cj.write_text(json.dumps({"mcpServers": {"research-bridge": dict(
        _entry(tmp_path / "uv"), command="/nonexistent/uv")}}), encoding="utf-8")
    assert by_id(doctor.offline())["mcp_entry"][0].message == "MCP entry points at a missing path"
    wt = tmp_path / "a" / ".claude" / "worktrees" / "w"
    wt.mkdir(parents=True)
    cj.write_text(json.dumps({"mcpServers": {"research-bridge": {
        "command": str(tmp_path / "uv"), "args": ["run", "--directory", str(wt)]}}}), encoding="utf-8")
    assert by_id(doctor.offline())["mcp_entry"][0].message == "MCP entry points at a worktree"
    old = _entry(tmp_path / "uv")
    del old["env"]["RB_HOST_CONFIG"]
    cj.write_text(json.dumps({"mcpServers": {"research-bridge": old}}), encoding="utf-8")
    r = by_id(doctor.offline())["mcp_entry"][0]
    assert r.level == "warn" and "differs" in r.message and r.next.startswith("claude mcp add-json")


def test_offline_services_not_installed_warn(hub, monkeypatch, tmp_path):
    _complete(hub, monkeypatch, tmp_path)
    for n in service.UNIT_NAMES:
        (hub.home / ".config" / "systemd" / "user" / n).unlink()
    hub.systemctl.clear()
    res = by_id(doctor.offline())
    assert res["service_sync"][0].level == "warn" and res["service_web"][0].level == "warn"
    assert "linger" not in res


def test_offline_linger_off_warns(hub, monkeypatch, tmp_path):
    _complete(hub, monkeypatch, tmp_path)
    hub.linger_value = "no"
    r = by_id(doctor.offline())["linger"][0]
    assert r.level == "warn" and r.next == "loginctl enable-linger hubuser"


def test_offline_sync_status_stale_warns(hub, monkeypatch, tmp_path):
    _complete(hub, monkeypatch, tmp_path)
    sdir = tmp_path / "data" / "sync"
    sdir.mkdir()
    (sdir / "node1.json").write_text(json.dumps(
        {"ok": False, "last_ok_at": "2020-01-01T00:00:00Z", "error": "agent_empty"}), encoding="utf-8")
    r = by_id(doctor.offline())["sync_status"][0]
    assert r.level == "warn" and "agent_empty" in r.message and r.next == "rb sync --node node1"
    (sdir / "node1.json").write_text("{", encoding="utf-8")
    assert by_id(doctor.offline())["sync_status"][0].level == "warn"


def test_offline_sync_status_unfinished_pass(hub, monkeypatch, tmp_path):
    import time
    _complete(hub, monkeypatch, tmp_path)
    sdir = tmp_path / "data" / "sync"
    sdir.mkdir()
    fresh = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 60))
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 7200))
    body = {"ok": False, "stage": "running", "error": "incomplete", "last_ok_at": fresh}
    (sdir / "node1.json").write_text(json.dumps(dict(body, last_attempt_at=fresh)), encoding="utf-8")
    assert by_id(doctor.offline())["sync_status"][0].level == "ok"  # a pass in progress
    (sdir / "node1.json").write_text(json.dumps(dict(body, last_attempt_at=old)), encoding="utf-8")
    r = by_id(doctor.offline())["sync_status"][0]
    assert r.level == "warn" and "never finished" in r.message


def test_mcp_entry_from_worktree_is_only_a_warning(hub, monkeypatch, tmp_path):
    _complete(hub, monkeypatch, tmp_path)
    main_co = tmp_path / "main"
    main_co.mkdir()
    wt = tmp_path / "main" / ".claude" / "worktrees" / "w"
    wt.mkdir(parents=True)
    monkeypatch.setattr(configure, "REPO", main_co)
    entry = _entry(tmp_path / "uv")
    configure.claude_json_path().write_text(
        json.dumps({"mcpServers": {"research-bridge": entry}}), encoding="utf-8")
    assert by_id(doctor.offline())["mcp_entry"][0].level == "ok"
    monkeypatch.setattr(configure, "REPO", wt)
    r = by_id(doctor.offline())["mcp_entry"][0]
    assert r.level == "warn" and "runs from a git worktree" in r.message
    assert configure.mcp_registered(wt) == (True, "from_worktree")
    # another difference besides the checkout path is still a difference
    entry["env"] = dict(entry["env"], RB_HOST_CONFIG="/elsewhere/host.json")
    configure.claude_json_path().write_text(
        json.dumps({"mcpServers": {"research-bridge": entry}}), encoding="utf-8")
    assert configure.mcp_registered(wt) == (True, "differs")
    # outside a worktree a different checkout path is a difference
    monkeypatch.setattr(configure, "REPO", tmp_path / "other")
    (tmp_path / "other").mkdir()
    entry["env"] = _entry(tmp_path / "uv")["env"]
    configure.claude_json_path().write_text(
        json.dumps({"mcpServers": {"research-bridge": entry}}), encoding="utf-8")
    assert configure.mcp_registered(tmp_path / "other") == (True, "differs")


def test_offline_key_file_no_bridge_identity(hub, monkeypatch, tmp_path):
    _complete(hub, monkeypatch, tmp_path)
    d = hub.ssh_dir / "research-bridge"
    personal = hub.ssh_dir / "id_ed25519"
    hub.make_key(personal, "personal")
    txt = hub.config_path.read_text(encoding="utf-8").replace(str(d / "node1_ed25519"), str(personal))
    hub.write_config(txt)
    r = by_id(doctor.offline())["key_file"][0]
    assert r.level == "fail" and "no bridge IdentityFile configured for rb-node1" in r.message
    assert r.next == "rb setup --node node1"


def test_offline_no_user_bus_is_manager_not_available(hub, monkeypatch, tmp_path):
    _complete(hub, monkeypatch, tmp_path)
    bus = (1, "", "Failed to connect to bus: No medium found")
    hub.systemctl.update({("is-active", "rb-sync.timer"): bus, ("is-active", "rb-web.service"): bus})
    res = by_id(doctor.offline())
    assert "user manager not available" in res["service_sync"][0].message


def test_offline_sync_staleness_is_900_seconds(hub, monkeypatch, tmp_path):
    import time
    _complete(hub, monkeypatch, tmp_path)
    for n in service.UNIT_NAMES:
        (hub.home / ".config" / "systemd" / "user" / n).write_text("OnUnitInactiveSec=60\n", encoding="utf-8")
    sdir = tmp_path / "data" / "sync"
    sdir.mkdir()
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 400))
    (sdir / "node1.json").write_text(json.dumps({"ok": True, "last_ok_at": stamp}), encoding="utf-8")
    assert by_id(doctor.offline())["sync_status"][0].level == "ok"


@pytest.mark.parametrize("body", [{"nodes": None}, {"nodes": ["node1"]}, {"data_root": 5},
                                  {"nodes": {"node1": "x"}}, {"withheld_patterns_file": []}])
def test_offline_wrong_types_report_not_raise(hub, tmp_path, body):
    hp = tmp_path / "data" / "host.json"
    hp.parent.mkdir(parents=True, exist_ok=True)
    hp.write_text(json.dumps(body), encoding="utf-8")
    res = doctor.offline()
    assert any(r.level == "fail" for r in res)
    assert configure.check()  # rb config check does not raise either
    assert doctor.main(None, offline_only=False) == 1


def test_online_missing_alias_in_entry_is_a_fail_not_a_traceback(hub, tmp_path, monkeypatch):
    hp = tmp_path / "data" / "host.json"
    hp.parent.mkdir(parents=True, exist_ok=True)
    hp.write_text(json.dumps({"nodes": {"node1": {"harness_alias": "rb-node1-harness"}}}), encoding="utf-8")
    assert doctor.main("node1", offline_only=False) == 1


from test_host_client import node  # noqa: E402,F401  (local subprocess node fixture)
from oldnode import SERVE_OLD  # noqa: E402


def test_online_against_old_node_stand_in(monkeypatch, tmp_path, node):
    """tests/oldnode.py answers hello without a protocol key: the doctor must read it as protocol 1."""
    monkeypatch.setattr(doctor, "_connect",
                        lambda cfg, n: client.NodeClient("x", ssh_argv=SERVE_OLD, env=node["env"]))
    res = doctor.online(_cfg(tmp_path), "node1")
    by = {r.id: r for r in res}
    assert by["reachable"].level == "ok" and "protocol 1" in by["reachable"].message
    for k in ("node_approval", "node_job_template", "node_responder", "node_queue"):
        assert by[k].level == "warn" and "unknown" in by[k].message


# ---------------------------------------------------------------- online

class FakeClient:
    def __init__(self, result=None, exc=None):
        self.result, self.exc = result, exc

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def hello(self):
        if self.exc:
            raise self.exc
        return self.result


def _cfg(tmp_path):
    from rb_host.config import HostConfig
    return HostConfig(nodes={"node1": {"alias": "rb-node1", "harness_alias": "rb-node1-harness"}},
                      data_root=str(tmp_path / "data"))


def _online(monkeypatch, tmp_path, result=None, exc=None):
    monkeypatch.setattr(doctor, "_connect", lambda cfg, node: FakeClient(result, exc))
    return doctor.online(_cfg(tmp_path), "node1")


def _p2(**state):
    st = {"configured": True, "approval_verifier": True, "job_template_set": True,
          "withheld_source_set": True, "withheld_loaded": 12, "withheld_rejected": 0,
          "harness_root_set": False, "claude_bin_found": True, "queue_dir_exists": True,
          "python": "3.8.20"}
    st.update(state)
    return {"node": "n", "version": rb_node.__version__, "withheld_extra": 12, "protocol": 2,
            "ops": ["hello"], "state": st}


OLD = {"node": "n", "version": "0.1.0", "withheld_extra": 5}


def test_online_protocol2_all_ok(monkeypatch, tmp_path):
    res = _online(monkeypatch, tmp_path, _p2())
    assert [r.level for r in res] == ["ok"] * 7
    assert [r.id for r in res] == ["reachable", "node_version", "node_withheld", "node_approval",
                                   "node_job_template", "node_responder", "node_queue"]


def test_online_old_node_reports_unknown_not_fail(monkeypatch, tmp_path):
    res = by_id(_online(monkeypatch, tmp_path, OLD))
    assert res["node_version"][0].level == "warn"
    for k in ("node_approval", "node_job_template", "node_responder", "node_queue"):
        assert res[k][0].level == "warn" and "unknown (node code predates protocol 2)" in res[k][0].message
    w = res["node_withheld"][0]
    assert w.level == "warn" and "counted before compiling" in w.message
    assert all(r[0].level != "fail" for r in res.values())


def test_online_old_node_zero_withheld_warn(monkeypatch, tmp_path):
    res = by_id(_online(monkeypatch, tmp_path, dict(OLD, withheld_extra=0)))
    assert res["node_withheld"][0].level == "warn"
    assert "0 extra patterns" in res["node_withheld"][0].message


def test_old_node_hints_name_update(monkeypatch, tmp_path):
    res = _online(monkeypatch, tmp_path, dict(OLD, withheld_extra=0))
    named = [r for r in res if "rb-node doctor" in r.next]
    assert named
    assert all("scripts/node-install.sh --update" in r.next for r in named)


def test_online_new_node_zero_patterns_fail(monkeypatch, tmp_path):
    res = by_id(_online(monkeypatch, tmp_path, _p2(withheld_loaded=0, withheld_rejected=0)))
    assert res["node_withheld"][0].level == "fail"


def test_online_new_node_withheld_rejected_fail(monkeypatch, tmp_path):
    res = by_id(_online(monkeypatch, tmp_path, _p2(withheld_rejected=1)))
    assert res["node_withheld"][0].level == "fail" and "1 node pattern(s)" in res["node_withheld"][0].message


def test_online_new_node_without_source_warns(monkeypatch, tmp_path):
    res = by_id(_online(monkeypatch, tmp_path, _p2(withheld_source_set=False)))
    assert res["node_withheld"][0].level == "warn"


def test_online_protocol2_approval_missing_is_fail(monkeypatch, tmp_path):
    res = by_id(_online(monkeypatch, tmp_path, _p2(approval_verifier=False, job_template_set=False)))
    assert res["node_approval"][0].level == "fail"
    assert res["node_job_template"][0].level == "warn"


def test_online_not_configured_node(monkeypatch, tmp_path):
    hello = {"node": "n", "version": "0.2.0", "withheld_extra": 0, "protocol": 2, "ops": ["hello"],
             "state": {"configured": False}}
    for kw in ({"result": hello}, {"exc": RemoteError("not_configured")}):
        res = _online(monkeypatch, tmp_path, **kw)
        assert [r.id for r in res] == ["reachable"]
        assert res[0].level == "fail" and res[0].message == "node reachable but not configured"
        assert "rb-node doctor" in res[0].next


def test_online_state_missing_keys_unknown(monkeypatch, tmp_path):
    hello = {"node": "n", "version": rb_node.__version__, "withheld_extra": 0, "protocol": 2,
             "ops": ["hello"], "state": {"configured": True}}
    res = by_id(_online(monkeypatch, tmp_path, hello))
    for k in ("node_approval", "node_job_template", "node_responder", "node_queue"):
        assert res[k][0].level == "warn" and "unknown" in res[k][0].message


def test_online_transport_error_shows_code_and_hint(monkeypatch, tmp_path):
    exc = TransportError("rb-node1 refused the key", "node_refused_key", "on the node: check it")
    res = _online(monkeypatch, tmp_path, exc=exc)
    assert [r.id for r in res] == ["reachable"]
    assert res[0].level == "fail" and res[0].message == "node_refused_key: rb-node1 refused the key"
    assert res[0].next == "on the node: check it"


def test_exit_code_one_only_on_fail():
    warn = doctor.Result("a", "warn", "m", "n", "")
    ok = doctor.Result("b", "ok", "m", "", "")
    assert doctor.exit_code([warn, ok]) == 0
    assert doctor.exit_code([warn, doctor.Result("c", "fail", "m", "n", "")]) == 1


def test_render_only_problems():
    res = [doctor.Result("a", "ok", "fine", "", ""), doctor.Result("b", "warn", "odd", "do x", "node1")]
    full = doctor.render(res, only_problems=False)
    assert "ok a  fine" in full and "warn b  odd" in full and "      next: do x" in full
    short = doctor.render(res, only_problems=True)
    assert "ok a" not in short and "warn b  odd" in short and short.rstrip().endswith("1 item(s) to fix")
    assert doctor.render(res[:1], only_problems=True).strip() == "ok"


def test_config_check_runs_offline_part(hub, monkeypatch, tmp_path, capsys):
    seen = []
    monkeypatch.setattr(doctor, "main", lambda node, offline_only, only_problems=False:
                        seen.append((node, offline_only, only_problems)) or 0)
    assert cli.main(["config", "check"]) == 0
    assert seen == [(None, True, True)]
    monkeypatch.undo()
    hub = hubfake.install(monkeypatch, tmp_path)
    _complete(hub, monkeypatch, tmp_path)
    capsys.readouterr()
    assert cli.main(["config", "check"]) == 0
    out = capsys.readouterr().out
    assert "ok " not in out and out.strip() == "ok"


def test_main_offline_only_never_connects(hub, monkeypatch, tmp_path, capsys):
    _complete(hub, monkeypatch, tmp_path)
    monkeypatch.setattr(doctor, "_connect", lambda *a: (_ for _ in ()).throw(AssertionError("connected")))
    assert doctor.main(None, offline_only=True) == 0
    monkeypatch.setattr(doctor, "_connect", lambda cfg, node: FakeClient(_p2()))
    assert doctor.main(None, offline_only=False) == 0
    assert "node_approval" in capsys.readouterr().out


@pytest.mark.parametrize("argv", [["pending"], ["approve", "j"], ["reject", "j"],
                                  ["harness", "pull", "--node", "n"], ["git-status"], ["agent"],
                                  ["service", "install"], ["share", "build"], ["share", "serve"],
                                  ["board", "refresh"], ["sync"], ["web", "serve"]])
def test_missing_host_json_one_line_error_for_every_command(argv, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    monkeypatch.setenv("RB_HOST_CONFIG", "/nonexistent-dir/host.json")
    assert cli.main(argv) == 1
    out = capsys.readouterr().out
    assert out.startswith("error: no usable host.json at /nonexistent-dir/host.json")
    assert len(out.strip().splitlines()) == 1 and "Traceback" not in out


@pytest.mark.parametrize("argv", [["pending"], ["share", "build"], ["share", "serve"], ["board", "refresh"],
                                  ["board", "show"], ["sync"], ["web", "serve"]])
def test_invalid_host_json_one_line_error(argv, monkeypatch, capsys, tmp_path):
    p = tmp_path / "host.json"
    p.write_text("{", encoding="utf-8")
    monkeypatch.setenv("RB_HOST_CONFIG", str(p))
    assert cli.main(argv) == 1
    out = capsys.readouterr().out
    assert "not valid JSON" in out and len(out.strip().splitlines()) == 1


def test_board_show_works_without_host_json(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("RB_HOST_CONFIG", str(tmp_path / "none" / "host.json"))
    monkeypatch.setenv("RB_HOST_ROOT", str(tmp_path / "root"))
    assert cli.main(["board", "show"]) == 0
    assert "error" not in capsys.readouterr().out
