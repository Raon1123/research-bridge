from __future__ import annotations

import pytest

# --- hub-setup: external command isolation ---


@pytest.fixture(autouse=True)
def _isolate_external(monkeypatch, tmp_path):
    from rb_host import client, configure, sshenv

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    run_dir.chmod(0o700)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(run_dir))
    monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)
    monkeypatch.setenv("HOME", str(home))
    # configure.claude_json_path is added by the configure change; tolerate its absence.
    monkeypatch.setattr(configure, "claude_json_path", lambda: home / ".claude.json", raising=False)

    def forbidden(*a, **k):
        raise AssertionError("external command in a test: %r" % (a,))

    monkeypatch.setattr(sshenv, "run", forbidden)
    monkeypatch.setattr(sshenv, "run_interactive", forbidden)
    monkeypatch.setattr(sshenv, "user_home", forbidden)

    orig_popen = client._popen

    def guarded(argv, env):
        if argv and argv[0] == "ssh":
            raise AssertionError("real ssh started in a test: %r" % (argv,))
        return orig_popen(argv, env)

    monkeypatch.setattr(client, "_popen", guarded)
    sshenv.forget()
    yield
    sshenv.forget()
