from __future__ import annotations

import json
import os
import shlex
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

import hubfake
from rb_host import cli, configure, doctor, setup, sshenv

HOST = ["--host", "<NODE_HOST>", "--port", "2222", "--user", "<NODE_USER>"]
ARGS = ["setup", "--node", "node1"] + HOST
KEYS = "research-bridge"
SCAN = b"[<NODE_HOST>]:2222 ssh-ed25519 AAAAscanned\n"


@pytest.fixture
def hub(monkeypatch, tmp_path):
    h = hubfake.install(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    h.doctor_calls = []
    monkeypatch.setattr(doctor, "main", lambda node, offline_only, only_problems=False:
                        h.doctor_calls.append((node, offline_only)) or 0)
    h.scan = SCAN
    return h


def _keys(hub, loaded=True):
    d = hub.ssh_dir / KEYS
    hub.make_key(d / "node1_ed25519", "research-bridge-hub")
    hub.make_key(d / "node1_harness_ed25519", "research-bridge-harness")
    if loaded:
        hub.add_agent("rb-ssh-agent", [hub.pub_fp(d / "node1_ed25519"), hub.pub_fp(d / "node1_harness_ed25519")])
    return d


def _snapshot(*roots):
    out = {}
    for root in roots:
        for p in sorted(Path(root).rglob("*")):
            st = p.lstat()
            out[str(p)] = (st.st_mtime_ns, st.st_size)
    return out


def _git_init(d):
    d.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(d), "init", "-q"], check=True, capture_output=True)


def test_setup_requires_terminal(hub, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "_interactive", lambda: False)
    assert cli.main(ARGS) == 1
    assert "terminal" in capsys.readouterr().out
    assert hub.calls == [] and not (tmp_path / "data").exists()


def test_setup_fresh_runs_steps_in_order(hub, capsys, tmp_path):
    assert cli.main(ARGS) == 0
    out = capsys.readouterr().out
    marks = [out.index("step %d/9" % i) for i in range(1, 10)]
    assert marks == sorted(marks)
    data = json.loads((tmp_path / "data" / "host.json").read_text(encoding="utf-8"))
    assert data["nodes"]["node1"]["alias"] == "rb-node1"
    assert [c[0] for c in hub.names("interactive")] == ["ssh-keygen", "ssh-keygen", "ssh-add", "ssh-add"]
    assert len(hub.asks) == 2 and "Generate" in hub.asks[0] and "Append to" in hub.asks[1]
    cfg = hub.config_path.read_text(encoding="utf-8")
    assert "Host rb-node1\n" in cfg and "Host rb-node1-harness\n" in cfg
    assert stat.S_IMODE(hub.config_path.stat().st_mode) == 0o600
    assert hub.keyscan_calls == [] and not (hub.ssh_dir / "known_hosts").exists()
    assert "rb setup --node node1" in out
    assert "scripts/node-install.sh" in out and "claude mcp add-json" in out
    assert hub.started == ["rb-ssh-agent"]
    assert hub.doctor_calls == [("node1", False)]


def test_host_key_deferred_on_first_run_then_compared(hub, capsys):
    assert cli.main(ARGS) == 0
    assert hub.keyscan_calls == [] and not any("fingerprint" in a for a in hub.asks)
    hub.asks.clear()
    capsys.readouterr()
    assert cli.main(ARGS) == 0
    assert len(hub.keyscan_calls) == 1 and len(hub.asks) == 1
    assert "answer n" in hub.asks[0]
    assert (hub.ssh_dir / "known_hosts").read_bytes().endswith(SCAN)
    assert "SHA256:" in capsys.readouterr().out


def test_setup_second_run_changes_nothing(hub, tmp_path):
    assert cli.main(ARGS) == 0
    hub.write_known_hosts(SCAN)
    before = _snapshot(tmp_path / "home", tmp_path / "data")
    hub.asks.clear()
    hub.calls.clear()
    assert cli.main(ARGS) == 0
    assert hub.asks == [] and hub.names("interactive") == []
    assert _snapshot(tmp_path / "home", tmp_path / "data") == before


def test_host_key_backup_kept(hub, tmp_path):
    hubfake.linked(hub, port=2222)
    other = b"other.example ssh-ed25519 AAAAother\n"
    hub.write_known_hosts(other)
    hub.add_agent("rb-ssh-agent", [hub.pub_fp(hub.ssh_dir / KEYS / "node1_ed25519"),
                                   hub.pub_fp(hub.ssh_dir / KEYS / "node1_harness_ed25519")])
    assert cli.main(ARGS) == 0
    baks = list(hub.ssh_dir.glob("known_hosts.bak.*"))
    assert len(baks) == 1 and baks[0].read_bytes() == other
    assert (hub.ssh_dir / "known_hosts").read_bytes() == other + SCAN


def test_setup_host_json_invalid_stops(hub, capsys, tmp_path):
    hp = tmp_path / "data" / "host.json"
    hp.parent.mkdir()
    hp.write_text("{", encoding="utf-8")
    assert cli.main(ARGS) == 1
    out = capsys.readouterr().out
    assert "not valid JSON" in out and hp.read_text(encoding="utf-8") == "{"
    assert hub.names("interactive") == [] and hub.asks == []


def test_ssh_block_shown_and_written_only_on_yes(hub, capsys):
    _keys(hub)
    hub.answer = lambda p: str(hub.config_path) not in p
    assert cli.main(ARGS) == 0
    out = capsys.readouterr().out
    assert "Host rb-node1\n" in out and "Host rb-node1-harness\n" in out
    assert not hub.config_path.exists()
    hub.answer = True
    assert cli.main(ARGS) == 0
    assert "Host rb-node1\n" in hub.config_path.read_text(encoding="utf-8")
    assert stat.S_IMODE(hub.config_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(hub.ssh_dir.stat().st_mode) == 0o700


def test_ssh_block_existing_with_different_values_reported_not_rewritten(hub, capsys):
    d = _keys(hub)
    text = hubfake.NODE_BLOCKS.format(port=22, key=d / "node1_ed25519", hkey=d / "node1_harness_ed25519")
    hub.write_config(text)
    assert cli.main(ARGS) == 0
    out = capsys.readouterr().out
    assert "rb-node1: port is 22, expected 2222" in out
    assert hub.config_path.read_text(encoding="utf-8") == text
    assert not any(str(hub.config_path) in a for a in hub.asks)


def test_ssh_block_overridden_by_earlier_host_star_warns(hub, capsys):
    _keys(hub)
    hub.write_config("Host *\n    StrictHostKeyChecking ask\n")
    assert cli.main(ARGS) == 0
    out = capsys.readouterr().out
    assert "stricthostkeychecking" in out and "overridden" in out


def test_ssh_config_backup_kept(hub):
    _keys(hub)
    old = "Host other\n    HostName x.example\n"
    hub.write_config(old)
    assert cli.main(ARGS) == 0
    baks = list(hub.ssh_dir.glob("config.bak.*"))
    assert len(baks) == 1 and baks[0].read_text(encoding="utf-8") == old
    assert hub.config_path.read_text(encoding="utf-8").startswith(old)


def test_symlinked_ssh_config_not_written(hub, capsys, tmp_path):
    _keys(hub)
    target = tmp_path / "dotfiles" / "ssh_config"
    target.parent.mkdir()
    target.write_text("Host other\n    HostName x.example\n", encoding="utf-8")
    hub.ssh_dir.mkdir(exist_ok=True)
    hub.config_path.symlink_to(target)
    assert cli.main(ARGS) == 0
    out = capsys.readouterr().out
    assert hub.config_path.is_symlink() and os.readlink(str(hub.config_path)) == str(target)
    assert target.read_text(encoding="utf-8") == "Host other\n    HostName x.example\n"
    assert not any(str(hub.config_path) in a for a in hub.asks)
    assert "Host rb-node1\n" in out and "symbolic link" in out


def test_ssh_config_in_git_repo_not_written(hub, capsys):
    _keys(hub)
    _git_init(hub.home)
    assert cli.main(ARGS) == 0
    out = capsys.readouterr().out
    assert not hub.config_path.exists()
    assert "git" in out and "Host rb-node1\n" in out
    assert not any(str(hub.config_path) in a for a in hub.asks)


def test_keydir_in_git_repo_refused(hub, capsys, tmp_path):
    repo = tmp_path / "repo"
    _git_init(repo)
    assert cli.main(ARGS + ["--keydir", str(repo / "keys")]) == 1
    out = capsys.readouterr().out
    assert "git" in out and "failed" in out
    assert [c for c in hub.names("interactive") if c[0] == "ssh-keygen"] == []
    assert not (repo / "keys").exists()


def _ready_for_hostkey(hub, known=b"other.example ssh-ed25519 AAAAother\n"):
    hubfake.linked(hub, port=2222)
    hub.write_known_hosts(known)
    d = hub.ssh_dir / KEYS
    hub.add_agent("rb-ssh-agent", [hub.pub_fp(d / "node1_ed25519"), hub.pub_fp(d / "node1_harness_ed25519")])
    return known


def test_host_key_appends_exact_scanned_bytes_on_yes(hub):
    known = _ready_for_hostkey(hub)
    hub.scan = b"[<NODE_HOST>]:2222 ssh-ed25519 AAAAexact\n[<NODE_HOST>]:2222 ssh-rsa AAAAmore"
    assert cli.main(ARGS) == 0
    assert (hub.ssh_dir / "known_hosts").read_bytes() == known + hub.scan
    assert len(hub.keyscan_calls) == 1


def test_host_key_no_append_on_no(hub):
    known = _ready_for_hostkey(hub)
    hub.answer = False
    assert cli.main(ARGS) == 0
    assert (hub.ssh_dir / "known_hosts").read_bytes() == known
    assert list(hub.ssh_dir.glob("known_hosts.bak.*")) == []


def test_host_key_appends_to_expanded_path(hub, tmp_path):
    known = _ready_for_hostkey(hub)
    assert cli.main(ARGS) == 0
    assert (hub.ssh_dir / "known_hosts").read_bytes() == known + SCAN
    for root in (tmp_path, Path.cwd()):
        assert not [p for p in root.rglob("~*")] if root == tmp_path else \
            not [p for p in root.iterdir() if p.name.startswith("~")]


def test_host_key_hashed_when_hashknownhosts_yes(hub):
    _ready_for_hostkey(hub)
    hub.write_config("HashKnownHosts yes\n\n" + hub.config_path.read_text(encoding="utf-8"))
    assert cli.main(ARGS) == 0
    assert hub.keyscan_calls == [("<NODE_HOST>", 2222, True)]


def test_host_key_unreachable_continues(hub, capsys):
    _ready_for_hostkey(hub)
    hub.scan = b""
    assert cli.main(ARGS) == 0
    assert "could not read the host key" in capsys.readouterr().out


def test_agent_started_only_when_no_socket_answers(hub):
    d = _keys(hub)
    assert cli.main(ARGS) == 0
    assert hub.started == []
    hub.agents.clear()
    assert cli.main(ARGS) == 0
    assert hub.started == ["rb-ssh-agent"]
    assert [c[0] for c in hub.names("interactive")].count("ssh-add") == 2


@pytest.mark.parametrize("argv", [ARGS, ["agent"]])
def test_forwarded_agent_gets_no_key(hub, argv):
    hubfake.linked(hub, port=2222)
    fwd = hub.add_agent("agent.1", [], runtime=False)
    assert cli.main(argv) == 0
    assert hub.started == ["rb-ssh-agent"]
    adds = [c for c in hub.calls if c[0] == "interactive" and c[1][0] == "ssh-add"]
    assert len(adds) == 2
    assert all(c[2]["SSH_AUTH_SOCK"] == str(hub.run_dir / "rb-ssh-agent") for c in adds)
    assert all(c[2]["SSH_AUTH_SOCK"] != fwd for c in adds)


def test_keys_added_only_when_not_loaded(hub):
    d = _keys(hub, loaded=False)
    hub.add_agent("rb-ssh-agent", [hub.pub_fp(d / "node1_ed25519")])
    assert cli.main(ARGS) == 0
    adds = [c[1] for c in hub.calls if c[0] == "interactive" and c[1][0] == "ssh-add"]
    assert adds == [["ssh-add", str(d / "node1_harness_ed25519")]]


def test_node_command_contains_both_keys_and_hub_from(hub, capsys):
    d = _keys(hub)
    assert cli.main(ARGS) == 0
    out = capsys.readouterr().out
    for n in ("node1_ed25519", "node1_harness_ed25519"):
        assert Path(str(d / n) + ".pub").read_text(encoding="utf-8").strip() in out
    assert "--hub-from 192.0.2.50" in out and "--apply-authorized-keys" in out
    assert hub.route_calls == ["<NODE_HOST>"]


def test_hub_from_override(hub, capsys):
    _keys(hub)
    assert cli.main(ARGS + ["--hub-from", "198.51.100.7"]) == 0
    assert "--hub-from 198.51.100.7" in capsys.readouterr().out
    assert hub.route_calls == []


def test_node_command_research_root_and_withheld(hub, capsys, tmp_path):
    _keys(hub)
    wp = tmp_path / "data" / "withheld_patterns.json"
    wp.parent.mkdir()
    wp.write_text('{"patterns": ["zz_[0-9]"]}', encoding="utf-8")
    assert cli.main(ARGS + ["--research-root", "/srv/tree"]) == 0
    out = capsys.readouterr().out
    assert "--research-root /srv/tree" in out and "--withheld-file" in out and str(wp) in out
    wp.unlink()
    assert cli.main(ARGS) == 0
    out = capsys.readouterr().out
    assert "--research-root" not in out and "--withheld-file" not in out
    assert "does not exist" in out and str(wp) in out


def test_mcp_command_uses_absolute_uv_and_no_ssh_auth_sock(hub, monkeypatch, capsys):
    _keys(hub)
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: "/opt/uv/bin/uv" if name == "uv" else None)
    assert cli.main(ARGS) == 0
    line = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip().startswith("claude mcp add-json")][0]
    parts = shlex.split(line)
    assert parts[:6] == ["claude", "mcp", "add-json", "--scope", "user", "research-bridge"]
    entry = json.loads(parts[6])
    assert entry["command"] == "/opt/uv/bin/uv" and "SSH_AUTH_SOCK" not in line


def test_mcp_command_carries_rb_host_variables(hub, monkeypatch, capsys, tmp_path):
    _keys(hub)
    monkeypatch.setenv("RB_HOST_CONFIG", str(tmp_path / "data" / "host.json"))
    assert cli.main(ARGS) == 0
    line = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip().startswith("claude mcp add-json")][0]
    env = json.loads(shlex.split(line)[6])["env"]
    assert env["RB_HOST_ROOT"] == str(tmp_path / "data") and env["RB_HOST_CONFIG"].endswith("host.json")


def test_mcp_command_warns_for_worktree_checkout(hub, monkeypatch, capsys, tmp_path):
    _keys(hub)
    wt = tmp_path / "a" / ".claude" / "worktrees" / "w"
    wt.mkdir(parents=True)
    monkeypatch.setattr(configure, "REPO", wt)
    assert cli.main(ARGS) == 0
    assert "worktree" in capsys.readouterr().out


def test_print_only_writes_nothing(hub, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "_interactive", lambda: False)
    assert cli.main(ARGS + ["--yes-print-only"]) == 0
    out = capsys.readouterr().out
    assert list((tmp_path / "home").rglob("*")) == [] and not (tmp_path / "data").exists()
    assert hub.asks == [] and hub.names("interactive") == []
    assert hub.keyscan_calls == [] and hub.route_calls == []
    assert hub.doctor_calls == [("node1", True)]
    assert "ssh-keyscan" in out and "--hub-from <HUB_ADDR>" in out


def test_upgrade_from_old_scripts_reports_nothing_to_change(hub, capsys, tmp_path):
    hubfake.linked(hub, port=2222)
    d = hub.ssh_dir / KEYS
    hub.add_agent("rb-ssh-agent", [hub.pub_fp(d / "node1_ed25519"), hub.pub_fp(d / "node1_harness_ed25519")])
    uv = tmp_path / "uv"
    uv.write_text("", encoding="utf-8")
    entry = dict(configure.mcp_entry()["research-bridge"], command=str(uv))
    entry["env"] = dict(entry["env"], SSH_AUTH_SOCK="/run/user/1000/rb-ssh-agent")
    configure.claude_json_path().write_text(json.dumps({"mcpServers": {"research-bridge": entry}}),
                                            encoding="utf-8")
    before = _snapshot(tmp_path / "home", tmp_path / "data")
    assert cli.main(ARGS) == 0
    out = capsys.readouterr().out
    assert hub.asks == [] and hub.names("interactive") == []
    assert _snapshot(tmp_path / "home", tmp_path / "data") == before
    assert ", expected " not in out and "SSH_AUTH_SOCK" in out and "no longer needed" in out
    assert "claude mcp add-json" not in out


def test_old_mcp_entry_without_rb_host_env_is_printed_again(hub, capsys, tmp_path):
    hubfake.linked(hub, port=2222)
    d = hub.ssh_dir / KEYS
    hub.add_agent("rb-ssh-agent", [hub.pub_fp(d / "node1_ed25519"), hub.pub_fp(d / "node1_harness_ed25519")])
    uv = tmp_path / "uv"
    uv.write_text("", encoding="utf-8")
    configure.claude_json_path().write_text(json.dumps({"mcpServers": {"research-bridge": {
        "command": str(uv), "args": ["run", "--directory", str(configure.REPO)]}}}), encoding="utf-8")
    assert cli.main(ARGS) == 0
    out = capsys.readouterr().out
    assert "differs" in out and "claude mcp add-json" in out and "RB_HOST_CONFIG" in out


def test_rb_agent_prints_export_line(hub, capsys, tmp_path):
    hubfake.linked(hub, port=2222)
    d = hub.ssh_dir / KEYS
    sock = hub.add_agent("rb-ssh-agent", [hub.pub_fp(d / "node1_ed25519"), hub.pub_fp(d / "node1_harness_ed25519")])
    before = _snapshot(tmp_path / "home", tmp_path / "data")
    assert cli.main(["agent"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[-1].endswith("export SSH_AUTH_SOCK=%s" % sock)
    assert lines[-2] == "agent: %s" % sock
    assert _snapshot(tmp_path / "home", tmp_path / "data") == before


def test_rerun_with_node_only_reads_values_from_ssh_G(hub, capsys):
    hubfake.linked(hub, port=2222)
    d = hub.ssh_dir / KEYS
    hub.add_agent("rb-ssh-agent", [hub.pub_fp(d / "node1_ed25519"), hub.pub_fp(d / "node1_harness_ed25519")])
    assert cli.main(["setup", "--node", "node1"]) == 0
    assert hub.route_calls == ["<NODE_HOST>"]
    assert ", expected " not in capsys.readouterr().out


def test_rerun_without_values_and_no_alias_exits_2(hub, capsys):
    assert cli.main(["setup", "--node", "node1"]) == 2
    assert "give --host and --user on the first run" in capsys.readouterr().out


def test_rb_agent_loads_missing_keys_any_keydir(hub, tmp_path):
    custom = tmp_path / "custom"
    hubfake.linked(hub, port=2222, keydir=custom)
    hub.add_agent("rb-ssh-agent", [])
    assert cli.main(["agent"]) == 0
    adds = [c[1][1] for c in hub.calls if c[0] == "interactive" and c[1][0] == "ssh-add"]
    assert adds == [str(custom / "node1_ed25519"), str(custom / "node1_harness_ed25519")]


def test_rb_agent_missing_key_exits_1(hub, capsys):
    hubfake.linked(hub, port=2222)
    (hub.ssh_dir / KEYS / "node1_ed25519").unlink()
    hub.add_agent("rb-ssh-agent", [])
    assert cli.main(["agent"]) == 1
    assert "key file missing" in capsys.readouterr().out


def test_rb_agent_requires_terminal(hub, monkeypatch, capsys):
    hubfake.linked(hub, port=2222)
    monkeypatch.setattr(cli, "_interactive", lambda: False)
    hub.calls.clear()
    assert cli.main(["agent"]) == 1
    assert "terminal" in capsys.readouterr().out and hub.calls == []


def test_no_claude_json_write(hub, tmp_path):
    cj = configure.claude_json_path()
    cj.write_bytes(b'{"mcpServers": {}}\n')
    st = cj.stat()
    assert cli.main(ARGS) == 0
    assert cj.read_bytes() == b'{"mcpServers": {}}\n' and cj.stat().st_mtime_ns == st.st_mtime_ns
    assert [p.name for p in cj.parent.iterdir() if p.name.startswith(".claude.json.")] == []
    assert not (tmp_path / "home" / ".bashrc").exists()


def test_host_star_identityfile_does_not_hide_bridge_keys(hub, capsys):
    hub.write_config("Host *\n    IdentityFile ~/.ssh/id_ed25519\n")
    assert cli.main(ARGS) == 0
    out = capsys.readouterr().out
    d = hub.ssh_dir / KEYS
    adds = [c[1] for c in hub.calls if c[0] == "interactive" and c[1][0] == "ssh-add"]
    assert [Path(c[-1]) for c in adds] == [d / "node1_ed25519", d / "node1_harness_ed25519"]
    assert "id_ed25519" not in out.replace("node1_ed25519", "").replace("node1_harness_ed25519", "")
    # second run: key choice is stable, nothing changes
    assert sshenv.identity_file("rb-node1") == d / "node1_ed25519"
    assert sshenv.identity_file("rb-node1-harness") == d / "node1_harness_ed25519"


def test_doctor_key_file_uses_bridge_key_under_host_star(hub, monkeypatch, tmp_path):
    hubfake.linked(hub, port=2222)
    hub.write_config("Host *\n    IdentityFile ~/.ssh/id_ed25519\n\n"
                     + hub.config_path.read_text(encoding="utf-8"))
    res = {r.id: r for r in doctor.offline() if r.node in ("", "node1")}
    assert res["key_file"].level == "ok", res["key_file"]


@pytest.mark.parametrize("extra", [["--node", "x *"], ["--user", "u\n    ProxyCommand touch /tmp/pwn"],
                                   ["--host", "h #x"], ["--host", "h h"], ["--port", "70000"]])
def test_setup_rejects_bad_values(hub, capsys, extra):
    argv = list(ARGS)
    for flag, val in zip(extra[::2], extra[1::2]):
        i = argv.index(flag)
        argv[i + 1] = val
    assert cli.main(argv) == 2
    assert hub.names("interactive") == [] and hub.asks == [] and not hub.config_path.exists()


def test_rerun_explicit_port_wins_over_ssh_G(hub, capsys):
    hubfake.linked(hub, port=2222)
    assert cli.main(["setup", "--node", "node1", "--port", "2200"]) == 0
    assert "port is 2222, expected 2200" in capsys.readouterr().out


def test_node_command_quotes_pub_lines_and_hub_from(hub, capsys):
    _keys(hub, loaded=False)
    pub = hub.ssh_dir / KEYS / "node1_ed25519.pub"
    pub.write_text("ssh-ed25519 AAAAx it's me\n", encoding="utf-8")
    assert cli.main(ARGS + ["--hub-from", "my hub"]) == 0
    out = capsys.readouterr().out
    assert "--hub-key 'ssh-ed25519 AAAAx it'\"'\"'s me'" in out and "--hub-from 'my hub'" in out


def test_host_key_unfingerprintable_scan_is_not_appended(hub, capsys, monkeypatch):
    hubfake.linked(hub, port=2222)
    hub.write_known_hosts(b"")
    monkeypatch.setattr(sshenv, "scan_fingerprints", lambda data: [])
    assert cli.main(ARGS) == 0
    assert "could not be fingerprinted" in capsys.readouterr().out
    assert hub.asks == [] or not any("fingerprint" in q for q in hub.asks)
    assert (hub.ssh_dir / "known_hosts").read_bytes() == b""


def test_host_key_with_hostkeyalias_names_the_alias(hub, capsys):
    hubfake.linked(hub, port=2222)
    hub.write_config(hub.config_path.read_text(encoding="utf-8").replace(
        "Host rb-node1\n", "Host rb-node1\n    HostKeyAlias nodeone\n"))
    hub.write_known_hosts(b"")
    assert cli.main(ARGS) == 0
    assert (hub.ssh_dir / "known_hosts").read_bytes() == b"nodeone ssh-ed25519 AAAAscanned\n"


def test_unwritable_known_hosts_target_is_reported_not_raised(hub, capsys):
    hubfake.linked(hub, port=2222)
    hub.write_config("Host rb-node1\n    UserKnownHostsFile /dev/null\n\n"
                     + hub.config_path.read_text(encoding="utf-8"))
    hub.write_known_hosts(b"")
    assert cli.main(ARGS) == 0
    assert "not a regular file" in capsys.readouterr().out


def test_ssh_config_write_failure_is_reported_not_raised(hub, capsys, monkeypatch):
    _keys(hub)
    monkeypatch.setattr(setup, "_atomic_write", lambda *a, **k: (_ for _ in ()).throw(PermissionError("denied")))
    assert cli.main(ARGS) == 1
    assert "could not write" in capsys.readouterr().out


def test_rb_agent_missing_harness_key_exits_1(hub, capsys):
    hubfake.linked(hub, port=2222)
    (hub.ssh_dir / KEYS / "node1_harness_ed25519").unlink()
    hub.add_agent("rb-ssh-agent", [])
    assert cli.main(["agent"]) == 1


def test_same_key_for_both_aliases_is_refused(hub, capsys):
    hubfake.linked(hub, port=2222)
    txt = hub.config_path.read_text(encoding="utf-8").replace("node1_harness_ed25519", "node1_ed25519")
    hub.write_config(txt)
    assert cli.main(ARGS) == 2
    assert "same file" in capsys.readouterr().out


def test_rb_agent_never_loads_a_personal_key(hub, capsys):
    hubfake.linked(hub, port=2222)
    d = hub.ssh_dir / KEYS
    personal = hub.ssh_dir / "id_ed25519"
    hub.make_key(personal, "personal")
    txt = hub.config_path.read_text(encoding="utf-8")
    txt = txt.replace(str(d / "node1_ed25519"), str(personal)).replace(
        str(d / "node1_harness_ed25519"), str(personal))
    hub.write_config(txt)
    hub.add_agent("rb-ssh-agent", [])
    assert cli.main(["agent"]) == 1
    out = capsys.readouterr().out
    assert "no bridge IdentityFile configured for rb-node1" in out
    assert "rb setup --node node1" in out
    assert not [c for c in hub.calls if c[0] == "interactive" and c[1][0] == "ssh-add"]


def test_differences_show_the_picked_identity(hub):
    from rb_host import setup
    key = hub.ssh_dir / KEYS / "node1_ed25519"
    cfg = {"identityfile": ["~/.ssh/id_ed25519", str(key)], "hostname": ["h"], "port": ["22"],
           "user": ["u"], "identitiesonly": ["yes"], "stricthostkeychecking": ["true"]}
    args = type("A", (), {"host": "h", "port": 22, "user": "u"})()
    assert setup._differences("rb-node1", cfg, args, key) == []
    other = key.parent / "other_ed25519"
    cfg["identityfile"] = [str(other)]
    got = setup._differences("rb-node1", cfg, args, key)
    assert got == ["rb-node1: identityfile is unset, expected %s" % key]
    cfg["identityfile"] = ["~/.ssh/id_ed25519", str(key)]
    cfg["identityfile"][1] = str(key.parent / "x" / "node1_ed25519")
    got = setup._differences("rb-node1", cfg, args, key)
    assert str(key.parent / "x" / "node1_ed25519") in got[0] and "id_ed25519," not in got[0]


@pytest.mark.parametrize("body", [{"nodes": ["node1"]}, {"nodes": "x"}, {"nodes": 5},
                                  {"nodes": {}, "data_root": 5}, {"data_root": ["a"]},
                                  {"nodes": {"node1": "x"}}])
def test_setup_host_json_wrong_types_one_line(hub, capsys, tmp_path, body):
    hp = tmp_path / "data" / "host.json"
    hp.parent.mkdir()
    hp.write_text(json.dumps(body), encoding="utf-8")
    code = cli.main(ARGS)
    out = capsys.readouterr().out
    assert code == 1, out
    assert "Traceback" not in out and "not valid JSON" not in out
    assert "wrong types" in out and "rb setup" in out
    assert len([ln for ln in out.splitlines() if ln.startswith("error:")]) == 1
    assert hub.names("interactive") == [] and hub.asks == []


def test_host_key_scan_uses_what_ssh_reports(hub, capsys):
    _ready_for_hostkey(hub)
    args = ["setup", "--node", "node1", "--host", "<NODE_HOST>", "--port", "2300", "--user",
            "<NODE_USER>"]
    cli.main(args)
    assert hub.keyscan_calls and hub.keyscan_calls[-1][:2] == ("<NODE_HOST>", 2222)
    assert "scanning what ssh uses" in capsys.readouterr().out
