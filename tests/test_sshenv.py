from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from rb_host import configure, sshenv


def _sock(path: Path, listen: bool = True) -> socket.socket:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)  # independent of the umask
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(str(path))
    if listen:
        s.listen(1)
    return s


@pytest.fixture
def socks():
    made = []

    def make(path, listen=True):
        s = _sock(path, listen)
        made.append(s)
        return s

    yield make
    for s in made:
        s.close()


def test_runtime_dir_rejects_group_writable(tmp_path, socks):
    run = tmp_path / "run"
    socks(run / "gcr" / "ssh")
    assert [p.name for p in sshenv.candidate_sockets()] == ["ssh"]
    run.chmod(0o770)
    assert sshenv.runtime_dir() is None
    assert sshenv.candidate_sockets() == []


def test_candidates_only_under_runtime_dir(tmp_path, socks):
    socks(tmp_path / "run" / "gcr" / "ssh")
    socks(tmp_path / "other" / "agent")
    assert sshenv.candidate_sockets() == [tmp_path / "run" / "gcr" / "ssh"]


def test_socket_owned_by_other_uid_skipped(tmp_path, socks, monkeypatch):
    a = tmp_path / "run" / "gcr" / "ssh"
    b = tmp_path / "run" / "openssh_agent"
    socks(a)
    socks(b)
    real = os.lstat

    def fake(p, *args, **kw):
        st = real(p, *args, **kw)
        if str(p) == str(a):
            return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink,
                                   st.st_uid + 1, st.st_gid, st.st_size, 0, 0, 0))
        return st

    monkeypatch.setattr(os, "lstat", fake)
    assert sshenv.candidate_sockets() == [b]


def test_symlink_socket_skipped(tmp_path, socks):
    real = tmp_path / "run" / "real"
    socks(real)
    (tmp_path / "run" / "openssh_agent").symlink_to(real)
    assert sshenv.candidate_sockets() == []


def test_inherited_sock_checked_like_candidates(tmp_path, socks, monkeypatch):
    f = tmp_path / "plain"
    f.write_text("x")
    monkeypatch.setenv("SSH_AUTH_SOCK", str(f))
    assert sshenv.candidate_sockets() == []
    wide = tmp_path / "wide"
    socks(wide / "agent")
    wide.chmod(0o777)
    monkeypatch.setenv("SSH_AUTH_SOCK", str(wide / "agent"))
    assert sshenv.candidate_sockets() == []
    ok = tmp_path / "fwd"
    socks(ok / "agent")
    ok.chmod(0o700)
    socks(tmp_path / "run" / "gcr" / "ssh")
    monkeypatch.setenv("SSH_AUTH_SOCK", str(ok / "agent"))
    assert sshenv.candidate_sockets()[0] == ok / "agent"


def test_inherited_sock_outside_runtime_dir_never_loaded(tmp_path, socks, monkeypatch):
    other = tmp_path / "other"
    socks(other / "agent")
    other.chmod(0o700)
    monkeypatch.setenv("SSH_AUTH_SOCK", str(other / "agent"))
    monkeypatch.setattr(sshenv, "run", lambda argv, env=None, timeout=10.0, input=None: (2, "", ""))
    assert other / "agent" not in sshenv.load_sockets()
    assert sshenv.load_socket() is None
    inside = tmp_path / "run" / "ssh-agent.socket"
    socks(inside)
    monkeypatch.setenv("SSH_AUTH_SOCK", str(inside))
    assert inside in sshenv.load_sockets()


def _fake_run(table):
    calls = []

    def run(argv, env=None, timeout=10.0, input=None):
        calls.append((list(argv), dict(env or {})))
        return table(argv, env or {})

    run.calls = calls
    return run


def test_agent_socket_prefers_socket_holding_alias_key(tmp_path, socks, monkeypatch):
    a = tmp_path / "run" / "gcr" / "ssh"
    b = tmp_path / "run" / "openssh_agent"
    socks(a)
    socks(b)
    monkeypatch.setattr(sshenv, "user_home", lambda: tmp_path / "home")

    def table(argv, env):
        if argv[:2] == ["ssh", "-G"]:
            return 0, "hostname h\nidentityfile ~/.ssh/k\n", ""
        if argv[0] == "ssh-keygen":
            return 0, "256 SHA256:WANT comment (ED25519)\n", ""
        if argv[0] == "ssh-add":
            if env.get("SSH_AUTH_SOCK") == str(b):
                return 0, "256 SHA256:WANT c (ED25519)\n", ""
            return 0, "256 SHA256:OTHER c (ED25519)\n", ""
        return 127, "", ""

    monkeypatch.setattr(sshenv, "run", _fake_run(table))
    assert sshenv.agent_socket("rb-node1") == b


def test_agent_socket_none_when_nothing_answers(tmp_path, socks, monkeypatch):
    socks(tmp_path / "run" / "gcr" / "ssh")
    monkeypatch.setattr(sshenv, "run", _fake_run(lambda a, e: (2, "", "")))
    assert sshenv.agent_socket() is None


def test_agent_socket_cache_dropped_after_agent_failure(tmp_path, socks, monkeypatch):
    a = tmp_path / "run" / "gcr" / "ssh"
    b = tmp_path / "run" / "openssh_agent"
    socks(a)
    socks(b)
    state = {"dead": set()}

    def table(argv, env):
        if argv[0] == "ssh-add":
            return (2, "", "") if env.get("SSH_AUTH_SOCK") in state["dead"] else (1, "", "")
        return 127, "", ""

    run = _fake_run(table)
    monkeypatch.setattr(sshenv, "run", run)
    assert sshenv.agent_socket() == a
    state["dead"].add(str(a))
    n = len(run.calls)
    assert sshenv.agent_socket() == a
    assert len(run.calls) == n
    sshenv.forget(None)
    assert sshenv.agent_socket() == b


def test_agent_socket_cache_is_per_alias(tmp_path, socks, monkeypatch):
    socks(tmp_path / "run" / "gcr" / "ssh")
    run = _fake_run(lambda a, e: (1, "", ""))
    monkeypatch.setattr(sshenv, "run", run)
    sshenv.agent_socket("one")
    n = len(run.calls)
    sshenv.agent_socket("one")
    assert len(run.calls) == n
    sshenv.forget("one")
    sshenv.agent_socket("one")
    assert len(run.calls) > n


def test_ssh_config_parses_ssh_G(monkeypatch):
    out = ("user u\nHostname example.invalid\nidentityfile ~/.ssh/a\nidentityfile ~/.ssh/b\nport 22\n")
    monkeypatch.setattr(sshenv, "run", lambda argv, **k: (0, out, ""))
    cfg = sshenv.ssh_config("rb-node1")
    assert cfg["identityfile"] == ["~/.ssh/a", "~/.ssh/b"]
    assert cfg["hostname"] == ["example.invalid"] and cfg["port"] == ["22"]


def test_ssh_config_splits_userknownhostsfile(tmp_path, monkeypatch):
    out = "userknownhostsfile ~/.ssh/known_hosts ~/.ssh/known_hosts2\n"
    monkeypatch.setattr(sshenv, "run", lambda argv, **k: (0, out, ""))
    monkeypatch.setattr(sshenv, "user_home", lambda: tmp_path / "h")
    cfg = sshenv.ssh_config("a")
    assert cfg["userknownhostsfile"] == ["~/.ssh/known_hosts", "~/.ssh/known_hosts2"]
    assert sshenv.known_hosts_files(cfg) == [tmp_path / "h/.ssh/known_hosts",
                                             tmp_path / "h/.ssh/known_hosts2"]
    cfg2 = {"userknownhostsfile": ["relative/kh", "%h_kh", "/abs/kh", "%d/.ssh/kh", "100%%"]}
    assert sshenv.known_hosts_files(cfg2) == [Path("/abs/kh"), tmp_path / "h/.ssh/kh"]


def test_alias_unknown_when_hostname_equals_alias(monkeypatch):
    monkeypatch.setattr(sshenv, "run", lambda argv, **k: (0, "hostname rb-node1\n", ""))
    assert sshenv.alias_defined("rb-node1") is False
    monkeypatch.setattr(sshenv, "run", lambda argv, **k: (0, "hostname <NODE_HOST>\n", ""))
    assert sshenv.alias_defined("rb-node1") is True


def test_identity_file_expands_tilde(tmp_path, monkeypatch):
    monkeypatch.setattr(sshenv, "user_home", lambda: tmp_path)
    monkeypatch.setattr(
        sshenv, "run",
        lambda argv, **k: (0, "identityfile ~/.ssh/research-bridge/node1_ed25519\n", ""))
    assert sshenv.identity_file("rb-node1") == tmp_path / ".ssh/research-bridge/node1_ed25519"


def test_known_host_uses_bracket_form_for_port(monkeypatch, tmp_path):
    monkeypatch.setattr(sshenv, "user_home", lambda: tmp_path)
    seen = []

    def run(argv, **k):
        seen.append(argv)
        name = argv[2]
        return (0 if name == "[<NODE_HOST>]:2222" else 1), "", ""

    monkeypatch.setattr(sshenv, "run", run)
    cfg = {"hostname": ["<NODE_HOST>"], "port": ["2222"], "userknownhostsfile": ["~/.ssh/known_hosts"]}
    assert sshenv.known_host(cfg) is True
    assert seen[0][-1] == str(tmp_path / ".ssh/known_hosts")
    seen.clear()
    cfg22 = dict(cfg, port=["22"])
    assert sshenv.known_host(cfg22) is False
    assert seen[0][2] == "<NODE_HOST>"


def test_route_source_parses_ip_route_get(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: [(socket.AF_INET, 1, 6, "", ("192.0.2.9", 0))])
    seen = []

    def run(argv, **k):
        seen.append(argv)
        return 0, "192.0.2.9 via 192.0.2.1 dev eth0 src 192.0.2.50 uid 1000\n    cache\n", ""

    monkeypatch.setattr(sshenv, "run", run)
    assert sshenv.route_source("<NODE_HOST>") == "192.0.2.50"
    assert seen[0] == ["ip", "-o", "route", "get", "192.0.2.9"]


def test_dead_socket_detected_by_refused_connect(tmp_path, socks):
    dead = tmp_path / "dead"
    s = socks(dead, listen=False)
    s.close()
    assert sshenv.socket_refuses(dead) is True
    live = tmp_path / "live"
    socks(live)
    assert sshenv.socket_refuses(live) is False


def test_start_agent_removes_only_dead_owned_socket(tmp_path, socks, monkeypatch):
    target = tmp_path / "run" / "rb-ssh-agent"
    s = socks(target, listen=False)
    s.close()
    calls = []
    monkeypatch.setattr(sshenv, "run", lambda argv, **k: (calls.append(argv) or (0, "", "")))
    assert sshenv.start_agent() == target
    assert not target.exists()
    assert calls == [["ssh-agent", "-a", str(target)]]
    calls.clear()
    socks(target)
    with pytest.raises(RuntimeError):
        sshenv.start_agent()
    assert target.exists() and calls == []


def test_start_agent_without_runtime_dir(tmp_path, monkeypatch):
    (tmp_path / "run").chmod(0o770)
    with pytest.raises(RuntimeError):
        sshenv.start_agent()


def test_no_test_reaches_real_runner():
    with pytest.raises(AssertionError):
        sshenv.run(["true"])


def test_claude_json_path_isolated(tmp_path):
    assert tmp_path in configure.claude_json_path().parents
    assert tmp_path in Path.home().parents


def test_sshenv_does_not_import_mcp():
    code = "import sys, rb_host.sshenv; sys.exit(1 if 'mcp' in sys.modules else 0)"
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0
