from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from rb_host import client, sshenv
from rb_host.client import (AGENT_CODES, CODES, NODE_DOCTOR, AgentLockedError, NodeClient,
                            TransportError, classify, normalize_hello)

ALIAS = "rb-node1"
KEY = Path("/k/node1_ed25519")
SECRET = "alice@203.0.113.9 /home/alice"


def fake_local(monkeypatch, key=KEY, unencrypted=False, rc=2, fps=(), fp="SHA256:WANT"):
    calls = []
    monkeypatch.setattr(sshenv, "identity_file", lambda a: key)
    monkeypatch.setattr(sshenv, "key_unencrypted", lambda k: unencrypted)

    def agent_rc(sock):
        calls.append("agent_rc")
        return rc

    monkeypatch.setattr(sshenv, "agent_rc", agent_rc)
    monkeypatch.setattr(sshenv, "agent_fingerprints", lambda s: list(fps))
    monkeypatch.setattr(sshenv, "fingerprint", lambda p: fp)
    return calls


def cl(stderr, code=255, sock=None):
    return classify(code, stderr + "\n" + SECRET, ALIAS, "node1", sock)


def test_publickey_no_socket_is_no_agent(monkeypatch):
    fake_local(monkeypatch)
    e = cl("u@h: Permission denied (publickey).")
    assert e.code == "no_agent" and isinstance(e, AgentLockedError) and e.hint == "rb agent"


def test_publickey_agent_unreachable_is_no_agent(monkeypatch):
    fake_local(monkeypatch, rc=2)
    assert cl("u@h: Permission denied (publickey).", sock=Path("/s")).code == "no_agent"


def test_publickey_agent_empty(monkeypatch):
    fake_local(monkeypatch, rc=1)
    assert cl("u@h: Permission denied (publickey).", sock=Path("/s")).code == "agent_empty"


def test_publickey_key_not_loaded(monkeypatch):
    fake_local(monkeypatch, rc=0, fps=["SHA256:OTHER"])
    e = cl("u@h: Permission denied (publickey).", sock=Path("/s"))
    assert e.code == "key_not_loaded" and e.hint == "rb agent --node node1"


def test_publickey_key_loaded_is_node_refused(monkeypatch):
    fake_local(monkeypatch, rc=0, fps=["SHA256:WANT"])
    e = cl("u@h: Permission denied (publickey).", sock=Path("/s"))
    assert e.code == "node_refused_key" and not isinstance(e, AgentLockedError)
    assert "rb-node doctor" in e.hint and "scripts/node-install.sh --update" in e.hint
    assert "--hub-from" in e.hint


def test_publickey_unencrypted_key_is_node_refused(monkeypatch):
    calls = fake_local(monkeypatch, unencrypted=True)
    assert cl("u@h: Permission denied (publickey).").code == "node_refused_key"
    assert calls == []


def test_publickey_fingerprint_unknown_is_node_refused(monkeypatch):
    fake_local(monkeypatch, rc=0, fps=["SHA256:OTHER"], fp=None)
    assert cl("u@h: Permission denied (publickey).", sock=Path("/s")).code == "node_refused_key"


def test_host_key_changed(monkeypatch):
    fake_local(monkeypatch)
    e = cl("@@@ WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED! @@@\nHost key verification failed.")
    assert e.code == "host_key_changed"


def test_host_key_unknown(monkeypatch):
    fake_local(monkeypatch)
    e = cl("No ED25519 host key is known for [<NODE_HOST>]:2222 and you have requested strict "
           "checking.\nHost key verification failed.")
    assert e.code == "host_key_unknown" and e.hint == "rb setup --node node1"


def test_resolve_failure_for_alias_is_unknown_alias(monkeypatch):
    fake_local(monkeypatch)
    e = cl("ssh: Could not resolve hostname RB-node1: Name or service not known")
    assert e.code == "unknown_alias"


def test_resolve_failure_for_hostname_is_unreachable(monkeypatch):
    fake_local(monkeypatch)
    assert cl("ssh: Could not resolve hostname other.invalid: Name or service not known"
              ).code == "unreachable"


def test_connection_refused_is_unreachable(monkeypatch):
    fake_local(monkeypatch)
    assert cl("ssh: connect to host <NODE_HOST> port 2222: Connection refused").code == "unreachable"


@pytest.mark.parametrize("line", ["Timeout, server <NODE_HOST> not responding.",
                                  "Connection timed out during banner exchange",
                                  "ssh: connect to host h port 22: Connection timed out"])
def test_timeouts(monkeypatch, line):
    fake_local(monkeypatch)
    assert cl(line).code == "timeout"


def test_other_exit_is_closed(monkeypatch):
    fake_local(monkeypatch)
    e = classify(1, "rb-node: node config not found: x", ALIAS, "node1", None)
    assert e.code == "closed" and str(e).startswith("connection to rb-node1 closed (exit 1)")
    assert e.message == "connection to rb-node1 closed (exit 1)" and e.hint == NODE_DOCTOR
    assert "rb-node doctor" in e.hint and "scripts/node-install.sh --update" in e.hint


def test_message_never_contains_stderr_text(monkeypatch):
    stderrs = ["u@h: Permission denied (publickey).", "REMOTE HOST IDENTIFICATION HAS CHANGED",
               "Host key verification failed.", "Could not resolve hostname rb-node1:",
               "Could not resolve hostname zz:", "Connection refused", "Timeout, server x not responding.",
               "something else"]
    for rc in (0, 1, 2):
        fake_local(monkeypatch, rc=rc, fps=["SHA256:WANT"])
        for s in stderrs:
            for sock in (None, Path("/s")):
                e = cl(s, sock=sock)
                assert "alice" not in str(e) and "203.0.113.9" not in str(e)
                assert "/home/alice" not in str(e)
                assert e.code in CODES


def test_agent_locked_subclass_for_agent_codes():
    assert issubclass(AgentLockedError, TransportError)
    assert AGENT_CODES == ("no_agent", "agent_empty", "key_not_loaded")
    assert len(CODES) == 10


def test_transport_error_str():
    assert str(TransportError("m")) == "m" and TransportError("m").code == "closed"
    e = TransportError("m", "timeout", "h")
    assert str(e) == "m (next: h)" and e.message == "m" and e.hint == "h"


def test_client_passes_discovered_socket_to_child(monkeypatch, tmp_path):
    script = tmp_path / "ssh.py"
    script.write_text("import os, sys\nsys.stderr.write(os.environ['SSH_AUTH_SOCK'] + '\\n')\n"
                      "sys.stderr.flush()\nsys.exit(3)\n")
    sock = tmp_path / "agent.sock"
    monkeypatch.setattr(sshenv, "agent_socket", lambda alias=None: sock)
    monkeypatch.setattr(client, "default_argv", lambda alias: [sys.executable, str(script)])
    with NodeClient("x") as c:
        assert c.agent_sock == sock
        with pytest.raises(TransportError):
            c.call("hello")
        assert str(sock) in b"".join(c._err).decode()


def test_explicit_env_or_argv_skips_discovery(monkeypatch):
    def boom(alias=None):
        raise AssertionError("discovery ran")

    monkeypatch.setattr(sshenv, "agent_socket", boom)
    with NodeClient("x", ssh_argv=[sys.executable, "-c", "pass"]):
        pass
    monkeypatch.setattr(client, "default_argv", lambda alias: [sys.executable, "-c", "pass"])
    with NodeClient("x", env={"A": "b"}):
        pass


def test_normalize_hello_old_node():
    h = normalize_hello({"node": "n", "version": "0.1.0", "withheld_extra": 0})
    assert h == {"node": "n", "version": "0.1.0", "protocol": 1, "ops": None, "state": None,
                 "withheld_extra": 0}


def test_normalize_hello_protocol2():
    raw = {"node": "n", "version": "0.2.0", "withheld_extra": 12, "protocol": 2,
           "ops": ["hello", "poll"], "state": {"configured": True, "python": "3.8.20"}}
    assert normalize_hello(raw) == raw


def test_normalize_hello_bad_values():
    h = normalize_hello({"protocol": "2", "ops": "x", "state": [], "withheld_extra": True})
    assert h["protocol"] == 1 and h["ops"] is None and h["state"] is None
    assert h["withheld_extra"] is None
    with pytest.raises(TransportError) as ei:
        normalize_hello(["x"])
    assert str(ei.value).startswith("bad response")


def test_failure_forgets_cached_socket(monkeypatch, tmp_path):
    fake_local(monkeypatch)
    forgot = []
    monkeypatch.setattr(sshenv, "forget", lambda alias=None: forgot.append(alias))
    script = tmp_path / "ssh.py"
    script.write_text("import sys\nsys.stderr.write('u@h: Permission denied (publickey).\\n')\n"
                      "sys.exit(255)\n")
    with NodeClient("rb-node1", ssh_argv=[sys.executable, str(script)]) as c:
        with pytest.raises(AgentLockedError) as ei:
            c.call("hello")
    assert ei.value.code == "no_agent" and forgot == ["rb-node1"]


def test_bad_response_is_closed_with_node_doctor(tmp_path):
    script = tmp_path / "ssh.py"
    script.write_text("import sys\nsys.stdout.write('garbage not a frame\\n')\nsys.stdout.flush()\n"
                      "import time; time.sleep(1)\n")
    with NodeClient("rb-node1", ssh_argv=[sys.executable, str(script)]) as c:
        with pytest.raises(TransportError) as ei:
            c.call("hello")
    assert ei.value.code == "closed" and ei.value.message == "bad response from rb-node1"
    assert ei.value.hint == NODE_DOCTOR


def test_cannot_start_ssh(monkeypatch):
    def popen(argv, env):
        raise FileNotFoundError("x")

    monkeypatch.setattr(client, "_popen", popen)
    with pytest.raises(TransportError) as ei:
        NodeClient("rb-node1", ssh_argv=["ssh"]).__enter__()
    assert ei.value.code == "closed" and ei.value.hint == "install openssh-client"
    assert "FileNotFoundError" in ei.value.message


def test_default_ssh_spawn_blocked_in_tests(monkeypatch):
    monkeypatch.setattr(sshenv, "agent_socket", lambda alias=None: None)
    with pytest.raises(AssertionError):
        NodeClient("rb-node1").__enter__()
