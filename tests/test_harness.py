from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from rb_host import cli, harness as hh
from rb_node import harness as nh

REPO = Path(__file__).resolve().parents[1]
RECV = [sys.executable, "-m", "rb_node.cli", "harness-receive"]


def _tar(members):
    """members: list of (name, bytes | ("symlink"|"hardlink", target))."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, val in members:
            ti = tarfile.TarInfo(name)
            if isinstance(val, tuple):
                ti.type = tarfile.SYMTYPE if val[0] == "symlink" else tarfile.LNKTYPE
                ti.linkname = val[1]
                tf.addfile(ti)
            else:
                ti.size = len(val)
                tf.addfile(ti, io.BytesIO(val))
    return buf.getvalue()


def _names(data):
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        return sorted(tf.getnames())


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "laptop" / ".claude"
    (home / "agents").mkdir(parents=True)
    (home / "hooks" / "__pycache__").mkdir(parents=True)
    (home / "agents" / "a.md").write_text("see D:/raw/papers/x here\n", encoding="utf-8")
    (home / "hooks" / "h.py").write_text("print(1)\n", encoding="utf-8")
    (home / "hooks" / "h.pyc").write_bytes(b"\0")
    (home / "hooks" / "__pycache__" / "h.cpython.pyc").write_bytes(b"\0")
    (home / "hooks" / "old.bak").write_text("x", encoding="utf-8")
    (home / "CLAUDE.md").write_text("# rules\n", encoding="utf-8")
    (home / "settings.json").write_text('{"model": "m"}', encoding="utf-8")
    (home / ".credentials.json").write_text('{"token": "SECRETVALUE"}', encoding="utf-8")
    (home / "projects").mkdir()
    (home / "projects" / "s.jsonl").write_text("session", encoding="utf-8")

    nroot = tmp_path / "node" / ".claude"
    (nroot / "agents").mkdir(parents=True)
    (nroot / "agents" / "a.md").write_text("server version\n", encoding="utf-8")
    (nroot / "agents" / "only-server.md").write_text("s\n", encoding="utf-8")
    (nroot / "settings.json").write_text('{"model": "n"}', encoding="utf-8")
    (nroot / ".credentials.json").write_text('{"token": "SECRETVALUE"}', encoding="utf-8")
    (nroot / "projects").mkdir()
    (nroot / "projects" / "s.jsonl").write_text("session", encoding="utf-8")

    rb = tmp_path / "node" / "rb"
    conf = {"harness_root": str(nroot), "mailbox_root": str(rb / "mailbox"),
            "audit_path": str(rb / "audit.jsonl")}
    nodecfg = tmp_path / "node.json"
    nodecfg.write_text(json.dumps(conf), encoding="utf-8")
    data_root = tmp_path / "data"
    host = tmp_path / "host.json"
    host.write_text(json.dumps({"nodes": {"node1": {"alias": "rb-node1"}},
                                "data_root": str(data_root)}), encoding="utf-8")
    monkeypatch.setenv("RB_HOST_CONFIG", str(host))
    monkeypatch.setenv("RB_NODE_CONFIG", str(nodecfg))
    return {"home": home, "nroot": nroot, "rb": rb, "data": data_root, "tmp": tmp_path,
            "nodecfg": nodecfg, "audit": rb / "audit.jsonl"}


@pytest.fixture
def fake(env, monkeypatch):
    """Route cli through a local fake node (ssh replaced by a subprocess of rb_node.cli)."""
    seen = {}

    def argv(cfg, node, command):
        seen["alias"] = hh.harness_alias(cfg, node)
        seen["command"] = command
        return RECV, {"SSH_ORIGINAL_COMMAND": command, "PYTHONPATH": str(REPO),
                      "RB_NODE_CONFIG": os.environ["RB_NODE_CONFIG"]}

    monkeypatch.setattr(hh, "transport", argv)
    monkeypatch.setattr(hh, "claude_home", lambda: env["home"])
    env["seen"] = seen
    return env


def _recv(env, command, stdin=b"", nodecfg=None):
    e = dict(os.environ)
    e.update({"SSH_ORIGINAL_COMMAND": command, "PYTHONPATH": str(REPO),
              "RB_NODE_CONFIG": str(nodecfg or env["nodecfg"])})
    return subprocess.run(RECV, input=stdin, env=e, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _staging(env):
    d = env["rb"] / "harness-staging"
    return sorted(p for p in d.iterdir()) if d.is_dir() else []


# -- allowlist / portablize -------------------------------------------------
def test_collect_allowlist_only(env):
    entries = hh.collect(env["home"])
    names = sorted(n for n, _ in entries)
    assert names == ["CLAUDE.md", "agents/a.md", "hooks/h.py", "settings.json"]
    assert nh.HARNESS_FILES == ["CLAUDE.md", "settings.json", "rtk-reference.md"]
    assert nh.HARNESS_DIRS == ["commands", "agents", "hooks", "workflows"]


def test_collect_portablizes_markdown(env):
    d = dict(hh.collect(env["home"]))
    text = d["agents/a.md"].decode()
    assert "see <RAW_ROOT>/papers/x here" in text and "D:/raw/papers" not in text
    assert "## Path resolution" in text and hh.NODE_HOME + "/raw" in text
    assert d["hooks/h.py"] == (env["home"] / "hooks" / "h.py").read_bytes()  # code untouched


def test_credentials_in_json_refuse(env):
    (env["home"] / "settings.json").write_text('{"env": {"api_key": "zzz"}}', encoding="utf-8")
    with pytest.raises(hh.HarnessError) as ei:
        hh.collect(env["home"])
    assert "zzz" not in str(ei.value)


# -- tar safety ---------------------------------------------------------------
@pytest.mark.parametrize("members", [
    [("agents/ok.md", b"x"), ("../evil", b"x")],
    [("agents/ok.md", b"x"), ("agents/../../evil", b"x")],
    [("agents/ok.md", b"x"), ("agents/link", ("symlink", "/etc/passwd"))],
    [("agents/ok.md", b"x"), ("agents/hard", ("hardlink", "agents/ok.md"))],
    [("agents/ok.md", b"x"), ("/abs/evil", b"x")],
    [("agents/ok.md", b"x"), ("projects/s.jsonl", b"x")],       # not allowlisted
    [("agents/ok.md", b"x"), ("agents\\evil.md", b"x")],
])
def test_receive_rejects_unsafe_tar_writes_nothing(env, members):
    r = _recv(env, "harness-push", _tar(members))
    assert r.returncode == 1
    assert _staging(env) == []
    assert not (env["tmp"] / "evil").exists() and not (env["rb"] / "evil").exists()


def test_receive_rejects_device(env):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        ti = tarfile.TarInfo("agents/dev")
        ti.type = tarfile.CHRTYPE
        tf.addfile(ti)
    r = _recv(env, "harness-push", buf.getvalue())
    assert r.returncode == 1 and _staging(env) == []


def test_safe_extract_function_nothing_written(tmp_path):
    with pytest.raises(nh.HarnessError):
        nh.stage_tar(_tar([("agents/a.md", b"1"), ("../evil", b"2")]), tmp_path / "st", "S1")
    assert not (tmp_path / "st").exists()


# -- forced-command routing ---------------------------------------------------
def test_receive_unknown_command_exit_1(env):
    r = _recv(env, "rm -rf /")
    assert r.returncode == 1 and r.stdout == b""
    assert _staging(env) == []


def test_receive_empty_and_push_stage(env):
    good = _tar([("agents/n.md", b"hello")])
    for cmd in ("", "harness-push"):
        r = _recv(env, cmd, good)
        assert r.returncode == 0, r.stderr
    st = _staging(env)
    assert len(st) == 2 and all((p / "agents" / "n.md").read_bytes() == b"hello" for p in st)


def test_receive_send_returns_allowlisted_tar(env):
    r = _recv(env, "harness-send")
    assert r.returncode == 0, r.stderr
    assert _names(r.stdout) == ["agents/a.md", "agents/only-server.md", "settings.json"]


def test_no_harness_root_refused(env):
    cfg = env["tmp"] / "empty.json"
    cfg.write_text(json.dumps({"mailbox_root": str(env["rb"] / "mailbox"),
                               "audit_path": str(env["audit"])}), encoding="utf-8")
    for cmd, data in (("harness-send", b""), ("harness-push", _tar([("agents/a.md", b"x")]))):
        r = _recv(env, cmd, data, nodecfg=cfg)
        assert r.returncode == 1 and b"no_harness_root" in r.stderr
    assert _staging(env) == []


def test_node_credential_in_settings_refuses_send(env):
    (env["nroot"] / "settings.json").write_text('{"token": "SECRETVALUE"}', encoding="utf-8")
    r = _recv(env, "harness-send")
    assert r.returncode == 1 and b"SECRETVALUE" not in r.stderr + r.stdout


def test_send_skips_symlinks(env):
    link = env["nroot"] / "agents" / "ln.md"
    try:
        link.symlink_to(env["nroot"] / "projects" / "s.jsonl")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    r = _recv(env, "harness-send")
    assert "agents/ln.md" not in _names(r.stdout)


# -- host: push -----------------------------------------------------------------
def test_push_dry_run_lists_sends_nothing(env, monkeypatch, capsys):
    monkeypatch.setattr(hh, "claude_home", lambda: env["home"])

    def boom(*a, **k):
        raise AssertionError("transport used")
    monkeypatch.setattr(hh, "transport", boom)
    assert cli.main(["harness", "push", "--node", "node1", "--dry-run"]) == 0
    out = capsys.readouterr().out
    for n in ("CLAUDE.md", "agents/a.md", "hooks/h.py", "settings.json"):
        assert n in out
    assert "h.pyc" not in out and "credentials" not in out
    assert _staging(env) == []


def test_push_lands_in_node_staging(fake, capsys):
    assert cli.main(["harness", "push", "--node", "node1"]) == 0
    assert fake["seen"] == {"alias": "rb-node1-harness", "command": "harness-push"}
    st = _staging(fake)
    assert len(st) == 1
    assert "see <RAW_ROOT>/papers/x here" in (st[0] / "agents" / "a.md").read_text()
    assert not (st[0] / ".credentials.json").exists()
    # live node harness untouched
    assert (fake["nroot"] / "agents" / "a.md").read_text() == "server version\n"


def test_push_node_without_harness_root_fails(fake, tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "n2.json"
    cfg.write_text(json.dumps({"audit_path": str(fake["audit"])}), encoding="utf-8")
    monkeypatch.setenv("RB_NODE_CONFIG", str(cfg))
    assert cli.main(["harness", "push", "--node", "node1"]) == 1
    assert "no_harness_root" in capsys.readouterr().out


def test_unknown_node(env, monkeypatch, capsys):
    monkeypatch.setattr(hh, "claude_home", lambda: env["home"])
    assert cli.main(["harness", "push", "--node", "nope", "--dry-run"]) == 1


# -- host: pull / diff ------------------------------------------------------------
def test_pull_stages_allowlisted_subset(fake, capsys):
    assert cli.main(["harness", "pull", "--node", "node1"]) == 0
    assert fake["seen"]["command"] == "harness-send"
    dirs = sorted((fake["data"] / "harness-staging").iterdir())
    assert len(dirs) == 1
    got = sorted(p.relative_to(dirs[0]).as_posix() for p in dirs[0].rglob("*") if p.is_file())
    assert got == ["agents/a.md", "agents/only-server.md", "settings.json"]


def test_pull_rejects_malicious_tar(env, monkeypatch):
    class R:
        pass
    monkeypatch.setattr(hh, "claude_home", lambda: env["home"])
    evil = _tar([("agents/a.md", b"1"), ("../evil", b"2")])
    monkeypatch.setattr(hh, "_run", lambda argv, e, data: evil)
    monkeypatch.setattr(hh, "transport", lambda c, n, cmd: (["x"], {}))
    assert cli.main(["harness", "pull", "--node", "node1"]) == 1
    assert not (env["data"] / "harness-staging").exists() or \
        not list((env["data"] / "harness-staging").iterdir())
    assert not (env["data"] / "evil").exists()


def test_diff_against_live(fake, capsys):
    assert cli.main(["harness", "pull", "--node", "node1"]) == 0
    stamp = next((fake["data"] / "harness-staging").iterdir()).name
    capsys.readouterr()
    assert cli.main(["harness", "diff", stamp]) == 0
    out = capsys.readouterr().out
    assert "--- live/agents/a.md" in out and "+++ staged/agents/a.md" in out
    assert "-see D:/raw/papers/x here" in out and "+server version" in out
    assert "only-server.md" in out  # new file shown against /dev/null


def test_pull_stores_claude_md_untrusted_and_diff_maps_back(fake, capsys):
    # SEC-02: staging is under the laptop data root, where a session could load CLAUDE.md
    (fake["nroot"] / "CLAUDE.md").write_text("# server rules\n", encoding="utf-8")
    assert cli.main(["harness", "pull", "--node", "node1"]) == 0
    st = next((fake["data"] / "harness-staging").iterdir())
    assert not (st / "CLAUDE.md").exists()
    assert (st / "CLAUDE.md.untrusted").read_text() == "# server rules\n"
    capsys.readouterr()
    assert cli.main(["harness", "diff", st.name]) == 0
    out = capsys.readouterr().out
    assert "--- live/CLAUDE.md" in out and "+++ staged/CLAUDE.md" in out
    assert "-# rules" in out and "+# server rules" in out


def test_diff_bad_stamp_and_missing(fake, capsys):
    assert cli.main(["harness", "diff", "../x"]) == 1
    assert cli.main(["harness", "diff", "20260101T000000Z"]) == 1


def test_no_apply_command(env):
    with pytest.raises(SystemExit):
        cli.main(["harness", "apply", "20260101T000000Z"])
    assert not hasattr(hh, "apply")


def test_audit_has_no_content_or_names(fake):
    cli.main(["harness", "push", "--node", "node1"])
    cli.main(["harness", "pull", "--node", "node1"])
    text = fake["audit"].read_text(encoding="utf-8")
    assert "harness" in text
    for s in ("a.md", "server version", "SECRETVALUE", "RAW_ROOT"):
        assert s not in text
