from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import rb_node
from rb_node import approval, cli, doctor
from rb_node.config import NodeConfig

BLOB = "AAAAC3NzaC1lZDI1NTE5AAAAIDistinctiveBlobForTestsOnly0123456789abcdef"
BLOB2 = "AAAAC3NzaC1lZDI1NTE5AAAAIOtherDistinctiveBlobForTests0123456789abcd"


def by_id(checks):
    return {c.id: c for c in checks}


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setattr(doctor, "_which", lambda name: None)
    return h


def make_full(home, tmp_path, monkeypatch):
    """A complete, healthy node under tmp. Returns (node.json path, data dict)."""
    rb = home / ".research-bridge"
    trm = tmp_path / "trm"
    for sub in ("lab/registry", "lab/experiments", "lab/reports", "reports/figures",
                "scripts/queue/jobs"):
        (trm / sub).mkdir(parents=True)
    mb = rb / "mailbox"
    for sub in ("in", "out", "state"):
        (mb / sub).mkdir(parents=True)
        os.chmod(str(mb / sub), 0o700)
    patterns = rb / "withheld-patterns.json"
    patterns.write_text(json.dumps({"patterns": ["zzq_[a-z]+"]}), encoding="utf-8")
    rec, _key = approval.make_record("a passphrase long enough", iterations=1000)
    approval.write_record(rb / "approve.json", rec)
    claude = tmp_path / "claude"
    claude.write_text("#!/bin/sh\n", encoding="utf-8")
    claude.chmod(0o755)
    bindir = home / ".local" / "bin"
    bindir.mkdir(parents=True)
    wrapper = bindir / "rb-node"
    wrapper.write_text('#!/bin/sh\nPYTHONPATH="$HOME/x" exec %s -m rb_node.cli "$@"\n'
                       % sys.executable, encoding="utf-8")
    wrapper.chmod(0o755)
    ssh = home / ".ssh"
    ssh.mkdir()
    (ssh / "authorized_keys").write_text(
        '# comment\n'
        'restrict,from="192.0.2.10",command="%s/rb-node serve-remote" ssh-ed25519 %s research-bridge-hub\n'
        'restrict,from="192.0.2.10",command="%s/rb-node harness-receive" ssh-ed25519 %s research-bridge-harness\n'
        % (bindir, BLOB, bindir, BLOB2), encoding="utf-8")
    (rb / "install.json").write_text(json.dumps({"version": rb_node.__version__}), encoding="utf-8")
    data = {"trm_root": str(trm), "queue_dir": str(trm / "scripts/queue"),
            "write_roots": [str(mb / "in") + "/", str(trm / "scripts/queue/jobs")],
            "withheld_source": str(patterns), "claude_bin": str(claude),
            "job_template": ["uv", "run", "train.py", "--config", "{config}"],
            "allowed_gpus": [4, 5]}
    full = {**NodeConfig(trm_root=str(trm)).__dict__, **data}
    path = rb / "node.json"
    path.write_text(json.dumps(full), encoding="utf-8")
    monkeypatch.setenv("RB_NODE_CONFIG", str(path))
    monkeypatch.setattr(doctor, "_which", lambda name: "/usr/bin/" + name)
    return path, full


def write_cfg(home, **kw):
    path = home / ".research-bridge" / "node.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = {**NodeConfig().__dict__, **kw}
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path, cfg


def test_doctor_fresh_install_lists_fixes(home, monkeypatch):
    path, _ = write_cfg(home)
    monkeypatch.setenv("RB_NODE_CONFIG", str(path))
    checks = by_id(doctor.run())
    assert checks["approval"].level == "fail"
    assert checks["job_template"].level == "warn"
    assert checks["pdftotext"].level == "warn"
    assert checks["ak_bridge"].level == "fail"
    for c in checks.values():
        if c.level != "ok":
            assert c.fix, c.id


def test_doctor_ok_when_complete(home, tmp_path, monkeypatch):
    make_full(home, tmp_path, monkeypatch)
    checks = doctor.run()
    assert [c for c in checks if c.level != "ok"] == []
    assert doctor.exit_code(checks) == 0
    ids = {c.id for c in checks}
    assert {"config", "approval", "ak_bridge", "mailbox", "wrapper", "install"} <= ids


def test_doctor_missing_config_is_single_fail(home, monkeypatch):
    monkeypatch.setenv("RB_NODE_CONFIG", str(home / "none.json"))
    checks = doctor.run()
    assert [(c.id, c.level) for c in checks] == [("config", "fail")]
    assert "no node.json at" in checks[0].message


def test_withheld_missing_file_fail(home):
    _, cfg = write_cfg(home, withheld_source=str(home / "nope.json"))
    assert by_id(doctor.config_checks(cfg))["withheld"].level == "fail"


def test_withheld_unparseable_fail(home):
    f = home / "p.json"
    f.write_text("a: b\n", encoding="utf-8")
    _, cfg = write_cfg(home, withheld_source=str(f))
    assert by_id(doctor.config_checks(cfg))["withheld"].level == "fail"


def test_config_keys_ignores_underscore_notes(home):
    _, cfg = write_cfg(home, _withheld_source_note="x", nope=1)
    c = by_id(doctor.config_checks(cfg))["config_keys"]
    assert c.level == "warn" and "'nope'" in c.message and "_withheld" not in c.message


def test_withheld_unset_warn(home):
    _, cfg = write_cfg(home, withheld_source=None)
    c = by_id(doctor.config_checks(cfg))["withheld"]
    assert c.level == "warn" and "five fallback patterns" in c.message


def test_withheld_zero_patterns_fail(home):
    f = home / "p.json"
    f.write_text("{}", encoding="utf-8")
    _, cfg = write_cfg(home, withheld_source=str(f))
    c = by_id(doctor.config_checks(cfg))["withheld"]
    assert c.level == "fail" and "has no pattern" in c.message


def test_withheld_rejected_fail(home):
    f = home / "p.json"
    f.write_text(json.dumps({"patterns": ["good_[a-z]+", "bad(["]}), encoding="utf-8")
    _, cfg = write_cfg(home, withheld_source=str(f))
    c = by_id(doctor.config_checks(cfg))["withheld"]
    assert c.level == "fail" and "pattern(s) do not compile" in c.message
    assert "bad([" not in c.message and "good_" not in c.message and "1" in c.message


def test_approval_malformed_fail(home):
    rb = home / ".research-bridge"
    rb.mkdir()
    (rb / "approve.json").write_text("{}", encoding="utf-8")
    _, cfg = write_cfg(home)
    c = by_id(doctor.config_checks(cfg))["approval"]
    assert c.level == "fail"
    (rb / "approve.json").unlink()
    c = by_id(doctor.config_checks(cfg))["approval"]
    assert c.level == "fail" and "approval verifier missing" in c.message


def test_job_template_empty_warn_missing_placeholder_fail(home):
    _, cfg = write_cfg(home, job_template=[])
    c = by_id(doctor.config_checks(cfg))["job_template"]
    assert c.level == "warn" and "job_template is empty" in c.message
    _, cfg = write_cfg(home, job_template=["python", "train.py"])
    c = by_id(doctor.config_checks(cfg))["job_template"]
    assert c.level == "fail" and "{config}" in c.message
    for ph in ("{config_dir}", "{config_stem}"):  # a loader that finds the config by name
        _, cfg = write_cfg(home, job_template=["python", "train.py", "--config-name", ph])
        assert by_id(doctor.config_checks(cfg))["job_template"].level == "ok"


def test_allowed_gpus_empty_warns_and_list_is_ok(home):
    _, cfg = write_cfg(home, allowed_gpus=[])
    c = by_id(doctor.config_checks(cfg))["allowed_gpus"]
    assert c.level == "warn" and "no_allowed_gpus" in c.message and "allowed_gpus" in c.fix
    _, cfg = write_cfg(home, allowed_gpus=[4, 5])
    assert by_id(doctor.config_checks(cfg))["allowed_gpus"].level == "ok"
    _, cfg = write_cfg(home, allowed_gpus=[4, "5"])  # wrong type: named, and treated as empty
    checks = by_id(doctor.config_checks(cfg))
    assert checks["allowed_gpus"].level == "warn"
    assert "allowed_gpus" in checks["config_keys"].message


def ak_cfg(home, text):
    ssh = home / ".ssh"
    ssh.mkdir(exist_ok=True)
    (ssh / "authorized_keys").write_text(text, encoding="utf-8")
    return NodeConfig(mailbox_root=str(home / "mb"))


@pytest.mark.parametrize("opts,cmd,word", [
    ('from="192.0.2.1"', "%s/rb-node serve-remote", "lacks restrict"),
    ("restrict", "%s/rb-node serve-remote", "lacks from="),
    ('restrict,from="192.0.2.1"', "rb-node serve-remote", "not absolute"),
])
def test_authorized_keys_lines_checked(home, opts, cmd, word):
    bindir = home / ".local" / "bin"
    bindir.mkdir(parents=True)
    (bindir / "rb-node").write_text("#!/bin/sh\n", encoding="utf-8")
    (bindir / "rb-node").chmod(0o755)
    line = '%s,command="%s" ssh-ed25519 %s c\n' % (opts, cmd % bindir if "%s" in cmd else cmd, BLOB)
    c = by_id(doctor.system_checks(ak_cfg(home, "# x\n" + line)))["ak_bridge"]
    assert c.level == "fail" and word in c.message and "line 2" in c.message


def test_authorized_keys_absent_is_fail_not_exception(home):
    cfg = NodeConfig(mailbox_root=str(home / "mb"))
    c = by_id(doctor.system_checks(cfg))["ak_bridge"]
    assert c.level == "fail" and "no serve-remote line" in c.message


def test_authorized_keys_options_with_comma_in_quotes(home):
    parsed = doctor.parse_authorized_keys(
        'restrict,from="192.0.2.1,198.51.100.0/24",command="/x/rb-node serve-remote" '
        'ssh-ed25519 %s cmt\n' % BLOB)
    assert len(parsed) == 1
    p = parsed[0]
    assert p["lineno"] == 1 and p["keytype"] == "ssh-ed25519" and p["blob"] == BLOB
    assert p["options"]["from"] == "192.0.2.1,198.51.100.0/24"
    assert p["options"]["command"] == "/x/rb-node serve-remote" and "restrict" in p["options"]
    assert doctor.parse_authorized_keys("# c\n\nssh-rsa %s\n" % BLOB)[0]["options"] == {}


def test_authorized_keys_duplicate_unrestricted_key_fail(home):
    bindir = home / ".local" / "bin"
    bindir.mkdir(parents=True)
    (bindir / "rb-node").write_text("#!/bin/sh\n", encoding="utf-8")
    (bindir / "rb-node").chmod(0o755)
    text = ('restrict,from="192.0.2.1",command="%s/rb-node serve-remote" ssh-ed25519 %s a\n'
            '# note\nssh-ed25519 %s plain\n' % (bindir, BLOB, BLOB))
    checks = by_id(doctor.system_checks(ak_cfg(home, text)))
    assert checks["ak_bridge"].level == "ok"
    assert checks["ak_duplicate"].level == "fail" and "line 3" in checks["ak_duplicate"].message


def test_authorized_keys_two_serve_remote_lines_same_key(home):
    bindir = home / ".local" / "bin"
    bindir.mkdir(parents=True)
    (bindir / "rb-node").write_text("#!/bin/sh\n", encoding="utf-8")
    (bindir / "rb-node").chmod(0o755)
    line = 'restrict,from="192.0.2.1",command="%s/rb-node serve-remote" ssh-ed25519 %s a\n' % (bindir, BLOB)
    c = by_id(doctor.system_checks(ak_cfg(home, line + "# n\n" + line)))["ak_duplicate"]
    assert c.level == "fail" and "line 3 also holds this key" in c.message
    assert "remove it by hand" in c.message and "without the forced command" not in c.message


def test_authorized_keys_output_has_no_key_material(home):
    text = ('from="192.0.2.1",command="/nope/rb-node serve-remote" ssh-ed25519 %s secretcomment\n'
            'ssh-ed25519 %s secretcomment\n' % (BLOB, BLOB))
    out = doctor.render(doctor.system_checks(ak_cfg(home, text)), only_problems=False)
    assert BLOB not in out and "secretcomment" not in out


def test_stale_lock_dead_pid_warn(home, tmp_path):
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    mb = tmp_path / "mb"
    (mb / "state").mkdir(parents=True)
    (mb / "state" / "responder.lock").write_text(str(p.pid), encoding="utf-8")
    c = by_id(doctor.system_checks(NodeConfig(mailbox_root=str(mb))))["responder_lock"]
    assert c.level == "warn" and "stale responder lock" in c.message and c.fix


def test_live_lock_is_ok(home, tmp_path):
    mb = tmp_path / "mb"
    (mb / "state").mkdir(parents=True)
    (mb / "state" / "responder.lock").write_text(str(os.getpid()), encoding="utf-8")
    c = by_id(doctor.system_checks(NodeConfig(mailbox_root=str(mb))))["responder_lock"]
    assert c.level == "ok"


def put_message(mb, mid, status, age_s):
    d = mb / "in" / mid
    d.mkdir(parents=True)
    ts = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(time.time() - age_s))
    (d / "message.json").write_text(json.dumps({"id": mid, "status": status, "received": ts}),
                                    encoding="utf-8")


def test_stuck_new_message_warn(home, tmp_path):
    mb = tmp_path / "mb"
    put_message(mb, "m1", "new", 20 * 60)
    put_message(mb, "m2", "new", 5)
    c = by_id(doctor.system_checks(NodeConfig(mailbox_root=str(mb))))["stuck_messages"]
    assert c.level == "warn" and "rb-node respond m1" in c.fix and "1 message(s)" in c.message


def test_recent_new_message_ok(home, tmp_path):
    mb = tmp_path / "mb"
    put_message(mb, "m2", "new", 5)
    put_message(mb, "job-x", "new", 99999)
    c = by_id(doctor.system_checks(NodeConfig(mailbox_root=str(mb))))["stuck_messages"]
    assert c.level == "ok"


def test_install_version_mismatch_warn(home, tmp_path):
    rb = tmp_path / "rb"
    rb.mkdir()
    (rb / "install.json").write_text(json.dumps({"version": "0.1.0"}), encoding="utf-8")
    c = by_id(doctor.system_checks(NodeConfig(mailbox_root=str(rb / "mailbox"))))["install"]
    assert c.level == "warn" and "0.1.0" in c.message
    (rb / "install.json").unlink()
    c = by_id(doctor.system_checks(NodeConfig(mailbox_root=str(rb / "mailbox"))))["install"]
    assert c.level == "warn" and "no install record" in c.message


def test_wrapper_python_from_path_and_missing(home):
    cfg = NodeConfig(mailbox_root=str(home / "mb"))
    assert by_id(doctor.system_checks(cfg))["wrapper"].level == "warn"
    bindir = home / ".local" / "bin"
    bindir.mkdir(parents=True)
    w = bindir / "rb-node"
    w.write_text('#!/bin/sh\nexec python3 -m rb_node.cli "$@"\n', encoding="utf-8")
    c = by_id(doctor.system_checks(cfg))["wrapper"]
    assert c.level == "warn" and "python from PATH" in c.message
    w.write_text('#!/bin/sh\nexec /nonexistent/python -m rb_node.cli "$@"\n', encoding="utf-8")
    c = by_id(doctor.system_checks(cfg))["wrapper"]
    assert c.level == "warn" and "python missing" in c.message


def test_pdftotext_missing_warn(home):
    c = by_id(doctor.system_checks(NodeConfig(mailbox_root=str(home / "mb"))))["pdftotext"]
    assert c.level == "warn"


def test_mailbox_missing_and_mode(home, tmp_path):
    mb = tmp_path / "mb"
    cfg = NodeConfig(mailbox_root=str(mb))
    assert by_id(doctor.system_checks(cfg))["mailbox"].level == "warn"
    assert not mb.exists()  # read only
    for s in ("in", "out", "state"):
        (mb / s).mkdir(parents=True)
        os.chmod(str(mb / s), 0o755)
    assert by_id(doctor.system_checks(cfg))["mailbox"].level == "warn"


def test_doctor_creates_nothing(home, tmp_path, monkeypatch):
    path, _ = write_cfg(home, mailbox_root=str(tmp_path / "mb"))
    monkeypatch.setenv("RB_NODE_CONFIG", str(path))
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    doctor.run()
    assert sorted(str(p) for p in tmp_path.rglob("*")) == before


def test_render_formats():
    checks = [doctor.Check("a", "ok", "fine", ""), doctor.Check("b", "warn", "odd", "do x"),
              doctor.Check("c", "fail", "bad", "do y")]
    full = doctor.render(checks, only_problems=False)
    assert "fine" in full and "      next: do x" in full and "1 to fix, 1 warning(s)" in full
    short = doctor.render(checks, only_problems=True)
    assert "fine" not in short and "odd" in short and short.rstrip().endswith("1 to fix, 1 warning(s)")
    assert doctor.render(checks[:1], only_problems=True).strip() == "ok"
    assert doctor.render(checks[:2], only_problems=True).rstrip().endswith("all ok, 1 warning(s)")
    assert doctor.render(checks[2:], only_problems=True).rstrip().endswith("1 to fix")
    assert doctor.exit_code(checks) == 1 and doctor.exit_code(checks[:2]) == 0


def test_config_check_prints_only_problems_exit1_on_fail(home, tmp_path, monkeypatch, capsys):
    path, full = make_full(home, tmp_path, monkeypatch)
    full["job_template"] = []
    path.write_text(json.dumps(full), encoding="utf-8")
    assert cli.main(["config", "check"]) == 0
    out = capsys.readouterr().out
    assert "ok " not in out and "job_template" in out
    (home / ".research-bridge" / "approve.json").unlink()
    assert cli.main(["config", "check"]) == 1
    assert "approval verifier missing" in capsys.readouterr().out


def test_doctor_cli_prints_all_lines(home, tmp_path, monkeypatch, capsys):
    make_full(home, tmp_path, monkeypatch)
    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "[ok]" in out and BLOB not in out


def test_authorized_keys_same_blob_on_harness_line_fail(home):
    bindir = home / ".local" / "bin"
    bindir.mkdir(parents=True)
    (bindir / "rb-node").write_text("#!/bin/sh\n", encoding="utf-8")
    (bindir / "rb-node").chmod(0o755)
    text = ('restrict,from="192.0.2.1",command="%s/rb-node serve-remote" ssh-ed25519 %s a\n'
            'restrict,from="192.0.2.1",command="%s/rb-node harness-receive" ssh-ed25519 %s b\n'
            % (bindir, BLOB, bindir, BLOB))
    checks = by_id(doctor.system_checks(ak_cfg(home, text)))
    assert checks["ak_duplicate"].level == "fail"
    assert "line 2" in checks["ak_duplicate"].message
    assert "hard rule 9" in checks["ak_duplicate"].message


@pytest.mark.parametrize("sub", ["doctor", "link", "config", "approve-key", "git-status"])
def test_subcommand_help_is_its_own(sub, capsys):
    from rb_node import cli
    assert cli.main([sub, "--help"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("usage: rb-node %s" % sub)
