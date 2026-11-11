from __future__ import annotations

import atexit
import os
import shutil
import tempfile

import pytest

# --- session-wide isolation -------------------------------------------------------------
# Set when this file is imported, before any test module runs. The per-test fixture below
# narrows these values further, but a test that undoes its monkeypatches (monkeypatch.undo())
# falls back to what is set here, never to the real account. On 2026-11-10 one such undo made
# every run of the suite overwrite the real ~/.claude.json (docs/postmortems/).
_SESSION_DIR = tempfile.mkdtemp(prefix="rb-tests-")
atexit.register(shutil.rmtree, _SESSION_DIR, True)
for _name, _sub in (("HOME", "home"), ("XDG_RUNTIME_DIR", "run")):
    os.makedirs(os.path.join(_SESSION_DIR, _sub), mode=0o700)
    os.environ[_name] = os.path.join(_SESSION_DIR, _sub)
for _name in ("SSH_AUTH_SOCK", "RB_HOST_ROOT", "RB_HOST_CONFIG", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
    os.environ.pop(_name, None)

# --- per-test isolation: HOME, runtime directory, external commands ---


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
    monkeypatch.setattr(configure, "claude_json_path", lambda: home / ".claude.json")

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
