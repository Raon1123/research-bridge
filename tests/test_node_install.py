from __future__ import annotations

import base64
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from rb_node import cli, install
from rb_node.config import NodeConfig
from rb_node.withheld import FALLBACK_PATTERNS

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "node-install.sh"


def pub(i: int) -> str:
    raw = b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + bytes([i]) * 32
    return "ssh-ed25519 " + base64.b64encode(raw).decode() + " test@example"


def blob(i: int) -> str:
    return pub(i).split()[1]


K1, K2, K3 = pub(1), pub(2), pub(3)


def new_lines(bindir="/home/<NODE_USER>/.local/bin", frm="192.0.2.10"):
    return install.ak_lines(install.read_pubkey(inline=K1), install.read_pubkey(inline=K2), frm,
                            Path(bindir))


def test_ak_lines_shape():
    a, b = new_lines()
    assert a == ('restrict,from="192.0.2.10",command="/home/<NODE_USER>/.local/bin/rb-node '
                 'serve-remote" ssh-ed25519 %s research-bridge-hub' % blob(1))
    assert b.endswith("research-bridge-harness") and "harness-receive" in b


def test_read_pubkey_validation(tmp_path):
    assert install.read_pubkey(inline=K1) == ("ssh-ed25519", blob(1))
    f = tmp_path / "k.pub"
    f.write_text("# c\n" + K2 + "\n", encoding="utf-8")
    assert install.read_pubkey(path=str(f)) == ("ssh-ed25519", blob(2))
    for bad in ("", "ssh-ed25519", "notakey AAAA", "ssh-ed25519 not base64!!", "rm -rf / x"):
        with pytest.raises(ValueError):
            install.read_pubkey(inline=bad)


def test_authorized_keys_replaces_same_key_line():
    old = ('from="198.51.100.0/24",command="/old/rb-node serve-remote" ssh-ed25519 %s\n' % blob(1))
    existing = "# comment\n" + old + "ssh-ed25519 %s other\n" % blob(9)
    text, changes = install.plan_authorized_keys(existing, new_lines())
    lines = text.splitlines()
    assert lines[0] == "# comment" and lines[1] == new_lines()[0]
    assert lines[2] == "ssh-ed25519 %s other" % blob(9)
    assert lines[3] == new_lines()[1]  # harness appended
    assert any("replace line 2" in c for c in changes)
    assert text.endswith("\n")


def test_authorized_keys_appends_new():
    text, changes = install.plan_authorized_keys("", new_lines())
    assert text.splitlines() == new_lines()
    assert [c.split()[0] for c in changes] == ["add", "add"]


def test_authorized_keys_blob_on_two_existing_lines():
    existing = ("ssh-ed25519 %s a\n# x\nssh-ed25519 %s b\nssh-ed25519 %s c\n"
                % (blob(1), blob(9), blob(1)))
    text, changes = install.plan_authorized_keys(existing, new_lines())
    lines = text.splitlines()
    assert lines[0] == new_lines()[0] and lines[3] == "ssh-ed25519 %s c" % blob(1)
    assert any("line 4 also holds this key" in c for c in changes)


def test_authorized_keys_idempotent():
    first, _ = install.plan_authorized_keys("# keep\n", new_lines())
    second, changes = install.plan_authorized_keys(first, new_lines())
    assert second == first
    assert [c.split()[0] for c in changes] == ["unchanged", "unchanged"]


def test_plan_never_removes_and_rejects_shared_blob():
    a, _b = new_lines()
    with pytest.raises(ValueError):
        install.plan_authorized_keys("", [a, a.replace("rb-node serve-remote", "rb-node x")])
    existing = "no trailing newline"
    text, _ = install.plan_authorized_keys(existing, new_lines())
    assert text.splitlines()[0] == existing


def test_hub_from_validated():
    assert install.validate_from("192.0.2.10") == "192.0.2.10"
    assert install.validate_from("192.0.2.0/24,198.51.100.7") == "192.0.2.0/24,198.51.100.7"
    assert install.validate_from("2001:db8::/32") == "2001:db8::/32"
    assert install.validate_from("192.0.2.5/24") == "192.0.2.0/24"
    for bad in ("not-an-address", "", "192.0.2.1,", 'x"y'):
        with pytest.raises(ValueError):
            install.validate_from(bad)


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.delenv("RB_NODE_CONFIG", raising=False)
    return h


def test_same_key_for_bridge_and_harness_refused(home, tmp_path, capsys):
    rc = install.main(["authorized-keys", "--hub-key", K1, "--harness-key", K1,
                       "--hub-from", "192.0.2.10", "--bindir", str(tmp_path)])
    assert rc == 2
    assert "hard rule 9" in capsys.readouterr().err
    assert not (home / ".ssh").exists()


def test_authorized_keys_main_prints_and_applies(home, tmp_path, monkeypatch, capsys):
    argv = ["authorized-keys", "--hub-key", K1, "--harness-key", K2, "--hub-from", "192.0.2.10",
            "--bindir", str(tmp_path / "bin"), "--apply"]
    monkeypatch.setattr(install, "_interactive", lambda: False)
    assert install.main(argv) == 0
    out = capsys.readouterr().out
    assert "serve-remote" in out and "harness-receive" in out
    assert not (home / ".ssh" / "authorized_keys").exists()
    monkeypatch.setattr(install, "_interactive", lambda: True)
    monkeypatch.setattr(install, "_ask", lambda prompt: True)
    assert install.main(argv) == 0
    text = (home / ".ssh" / "authorized_keys").read_text(encoding="utf-8")
    assert text.count("\n") == 2
    assert install.main(argv[:-1] + ["--dry-run"]) == 0  # dry run changes nothing


def test_apply_requires_terminal_and_yes(tmp_path, monkeypatch):
    path = tmp_path / ".ssh" / "authorized_keys"
    text, changes = install.plan_authorized_keys("", new_lines())
    monkeypatch.setattr(install, "_interactive", lambda: False)
    monkeypatch.setattr(install, "_ask", lambda p: True)
    assert install.apply_authorized_keys(path, text, changes) is False and not path.exists()
    monkeypatch.setattr(install, "_interactive", lambda: True)
    monkeypatch.setattr(install, "_ask", lambda p: False)
    assert install.apply_authorized_keys(path, text, changes) is False and not path.exists()
    monkeypatch.setattr(install, "_ask", lambda p: True)
    assert install.apply_authorized_keys(path, text, changes) is True
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert path.read_text(encoding="utf-8") == text


def test_backup_written_before_change(tmp_path, monkeypatch):
    path = tmp_path / ".ssh" / "authorized_keys"
    path.parent.mkdir()
    path.write_bytes(b"# old bytes\n")
    text, changes = install.plan_authorized_keys(path.read_text(encoding="utf-8"), new_lines())
    monkeypatch.setattr(install, "_interactive", lambda: True)
    monkeypatch.setattr(install, "_ask", lambda p: True)
    assert install.apply_authorized_keys(path, text, changes)
    baks = list(path.parent.glob("authorized_keys.bak.*"))
    assert len(baks) == 1 and baks[0].read_bytes() == b"# old bytes\n"
    assert stat.S_IMODE(baks[0].stat().st_mode) == 0o600


# -- withheld file -----------------------------------------------------------------------------
def pattern_file(path: Path, patterns) -> Path:
    path.write_text(json.dumps({"patterns": patterns}), encoding="utf-8")
    return path


def node_json(home: Path) -> Path:
    p = home / ".research-bridge" / "node.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"trm_root": "/x"}), encoding="utf-8")
    return p


def dest_of(home: Path) -> Path:
    return home / ".research-bridge" / "withheld-patterns.json"


def test_withheld_file_copied_and_validated(home, tmp_path, capsys):
    cfgp = node_json(home)
    dest = dest_of(home)
    good = pattern_file(tmp_path / "good.json", ["zzq_[a-z]+", "yyq_[0-9]+"])
    assert install.install_withheld(good, dest, cfgp) == 0
    assert dest.read_bytes() == good.read_bytes() and stat.S_IMODE(dest.stat().st_mode) == 0o600
    assert json.loads(cfgp.read_text(encoding="utf-8"))["withheld_source"] == str(dest)
    out = capsys.readouterr().out
    assert "zzq_" not in out and "2" in out
    dest.unlink()
    bad = pattern_file(tmp_path / "bad.json", ["ok_[a-z]+", "bad(["])
    zero = pattern_file(tmp_path / "zero.json", [])
    assert install.install_withheld(bad, dest, cfgp) == 1 and not dest.exists()
    assert install.install_withheld(zero, dest, cfgp) == 1 and not dest.exists()
    assert install.install_withheld(tmp_path / "missing.json", dest, cfgp) == 1
    err = capsys.readouterr().err
    assert "bad([" not in err
    # a file holding only the fallback patterns has no extra pattern
    only = pattern_file(tmp_path / "fb.json", list(FALLBACK_PATTERNS))
    assert install.install_withheld(only, dest, cfgp) == 1


def test_withheld_same_file_rerun_no_prompt(home, tmp_path, monkeypatch):
    cfgp = node_json(home)
    dest = dest_of(home)
    f = pattern_file(tmp_path / "f.json", ["zzq_[a-z]+"])
    assert install.install_withheld(f, dest, cfgp) == 0
    before = dest.read_bytes()

    def boom(*a):
        raise AssertionError("must not ask")
    monkeypatch.setattr(install, "_ask", boom)
    monkeypatch.setattr(install, "_interactive", lambda: False)
    assert install.install_withheld(f, dest, cfgp) == 0
    assert dest.read_bytes() == before
    assert not list(dest.parent.glob("withheld-patterns.json.bak.*"))


def test_withheld_replace_needs_terminal_yes_and_backup(home, tmp_path, monkeypatch, capsys):
    cfgp = node_json(home)
    dest = dest_of(home)
    old = pattern_file(tmp_path / "old.json", ["aaq_1", "bbq_2", "ccq_3"])
    assert install.install_withheld(old, dest, cfgp) == 0
    old_bytes = dest.read_bytes()
    new = pattern_file(tmp_path / "new.json", ["ddq_4"])
    monkeypatch.setattr(install, "_interactive", lambda: False)
    assert install.install_withheld(new, dest, cfgp) == 1 and dest.read_bytes() == old_bytes
    monkeypatch.setattr(install, "_interactive", lambda: True)
    monkeypatch.setattr(install, "_ask", lambda p: False)
    capsys.readouterr()
    assert install.install_withheld(new, dest, cfgp) == 1 and dest.read_bytes() == old_bytes
    monkeypatch.setattr(install, "_ask", lambda p: True)
    assert install.install_withheld(new, dest, cfgp) == 0
    out = capsys.readouterr().out
    assert "fewer patterns" in out and "3 patterns" in out and "1 patterns" in out
    assert dest.read_bytes() == new.read_bytes()
    baks = list(dest.parent.glob("withheld-patterns.json.bak.*"))
    assert len(baks) == 1 and baks[0].read_bytes() == old_bytes


def test_withheld_differing_configured_file_needs_prompt(home, tmp_path, monkeypatch):
    cfgp = node_json(home)
    other = pattern_file(tmp_path / "other.json", ["ooq_1", "ppq_2"])
    cfgp.write_text(json.dumps({"withheld_source": str(other)}), encoding="utf-8")
    new = pattern_file(tmp_path / "new.json", ["ddq_4"])
    monkeypatch.setattr(install, "_interactive", lambda: False)
    assert install.install_withheld(new, dest_of(home), cfgp) == 1
    assert not dest_of(home).exists()


def test_withheld_dry_run_writes_nothing(home, tmp_path):
    cfgp = node_json(home)
    f = pattern_file(tmp_path / "f.json", ["zzq_[a-z]+"])
    assert install.install_withheld(f, dest_of(home), cfgp, dry_run=True) == 0
    assert not dest_of(home).exists()
    assert "withheld_source" not in json.loads(cfgp.read_text(encoding="utf-8"))


def test_config_set_withheld_source_requires_terminal(home, monkeypatch):
    cfgp = node_json(home)
    monkeypatch.setenv("RB_NODE_CONFIG", str(cfgp))
    before = cfgp.read_bytes()
    monkeypatch.setattr(cli, "_interactive", lambda: False)
    assert cli.main(["config", "set", "withheld_source", "/x.json"]) == 1
    assert cfgp.read_bytes() == before
    assert cli.main(["config", "set", "max_file", "1024"]) == 0  # other keys unchanged
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    assert cli.main(["config", "set", "withheld_source", "/x.json"]) == 0


def test_make_mailbox_modes(tmp_path):
    cfg = NodeConfig(mailbox_root=str(tmp_path / "rb" / "mailbox"))
    install.make_mailbox(cfg)
    for sub in ("in", "out", "state", "state/acked"):
        d = tmp_path / "rb" / "mailbox" / sub
        assert d.is_dir() and stat.S_IMODE(d.stat().st_mode) == 0o700


def test_host_fingerprints(tmp_path, monkeypatch):
    for n in ("a", "b"):
        (tmp_path / ("ssh_host_%s_key.pub" % n)).write_text("x", encoding="utf-8")
    monkeypatch.setenv("RB_NODE_HOSTKEY_GLOB", str(tmp_path / "ssh_host_*_key.pub"))
    monkeypatch.setattr(install, "_run", lambda argv, input=None: (0, "256 SHA256:ZZ x (ED25519)\n", ""))
    assert install.host_fingerprints() == ["256 SHA256:ZZ x (ED25519)"] * 2
    monkeypatch.setattr(install, "_run", lambda argv, input=None: (1, "", "no"))
    assert install.host_fingerprints() == []


# -- the script --------------------------------------------------------------------------------
@pytest.fixture
def sh_env(tmp_path):
    stub = tmp_path / "stub"
    stub.mkdir()
    kg = stub / "ssh-keygen"
    kg.write_text("#!/bin/sh\necho '256 SHA256:TESTFINGERPRINT x (ED25519)'\n", encoding="utf-8")
    kg.chmod(0o755)
    hk = tmp_path / "hostkeys"
    hk.mkdir()
    (hk / "ssh_host_ed25519_key.pub").write_text("x", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    tree = tmp_path / "tree"
    tree.mkdir()
    env = {"HOME": str(home),
           "PATH": "%s:%s:/usr/bin:/bin" % (stub, os.path.dirname(sys.executable)),
           "RB_NODE_HOSTKEY_GLOB": str(hk / "ssh_host_*_key.pub"),
           "PYTHONDONTWRITEBYTECODE": "1"}
    return env, home, tree, stub


def sh(env, *args):
    return subprocess.run(["sh", str(SCRIPT)] + list(args), env=env, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
                          universal_newlines=True)


def test_script_syntax():
    for shell in ("sh", "dash"):
        r = subprocess.run([shell, "-n", str(SCRIPT)], stderr=subprocess.PIPE,
                           universal_newlines=True)
        assert r.returncode == 0, r.stderr


def test_script_help_and_missing_flag_value_usage(sh_env):
    env, home, tree, _ = sh_env
    r = sh(env, "--help")
    assert r.returncode == 0 and "usage:" in r.stdout
    r = sh(env, "--research-root")
    assert r.returncode == 2 and "usage:" in r.stderr
    r = sh(env, "--no-such-flag")
    assert r.returncode == 2
    assert not (home / ".local").exists()


def test_script_dry_run_writes_nothing(sh_env):
    env, home, tree, _ = sh_env
    r = sh(env, "--dry-run", "--research-root", str(tree), "--hub-key", K1, "--harness-key", K2,
           "--hub-from", "192.0.2.10", "--apply-authorized-keys")
    assert r.returncode == 0, r.stderr
    assert "[dry-run]" in r.stdout
    assert not (home / ".local").exists() and not (home / ".research-bridge").exists()
    assert not (home / ".ssh").exists()


def test_script_needs_research_root_without_terminal(sh_env):
    env, home, tree, _ = sh_env
    r = sh(env)
    assert r.returncode == 2 and "--research-root" in r.stderr
    assert not (home / ".local").exists()


def full_args(tree, *extra):
    return ["--research-root", str(tree), "--hub-key", K1, "--harness-key", K2,
            "--hub-from", "192.0.2.10", "--apply-authorized-keys"] + list(extra)


def test_script_install_tmp_home(sh_env):
    env, home, tree, _ = sh_env
    r = sh(env, *full_args(tree))
    assert r.returncode == 0, r.stdout + r.stderr
    wrapper = home / ".local" / "bin" / "rb-node"
    text = wrapper.read_text(encoding="utf-8")
    assert os.access(str(wrapper), os.X_OK)
    py = text.split("exec ")[1].split()[0]
    assert os.path.isabs(py) and os.path.exists(py)
    share = home / ".local" / "share" / "research-bridge"
    link = share / "rb_node"
    assert link.is_symlink() and "releases" in os.readlink(str(link))
    assert (link / "doctor.py").is_file()
    mb = home / ".research-bridge" / "mailbox"
    for sub in ("in", "out", "state"):
        assert (mb / sub).is_dir()
    data = json.loads((home / ".research-bridge" / "node.json").read_text(encoding="utf-8"))
    assert data["trm_root"] == str(tree) and data["queue_dir"] == str(tree) + "/scripts/queue"
    assert not (home / ".ssh" / "authorized_keys").exists()
    assert "serve-remote" in r.stdout and "harness-receive" in r.stdout
    assert "TESTFINGERPRINT" in r.stdout
    assert (home / ".research-bridge" / "install.json").is_file()
    # the wrapper really runs the installed code
    out = subprocess.run([str(wrapper), "config", "path"], env=env, stdout=subprocess.PIPE,
                         universal_newlines=True)
    assert out.returncode == 0 and "node.json" in out.stdout


def test_script_rerun_keeps_claude_bin(sh_env, tmp_path):
    env, home, tree, _ = sh_env
    assert sh(env, "--research-root", str(tree)).returncode == 0
    fake = tmp_path / "myclaude"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    fake.chmod(0o755)
    wrapper = home / ".local" / "bin" / "rb-node"
    assert subprocess.run([str(wrapper), "config", "set", "claude_bin", str(fake)],
                          env=env).returncode == 0
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "claude").write_text("#!/bin/sh\n", encoding="utf-8")
    (other / "claude").chmod(0o755)
    env2 = dict(env, PATH=env["PATH"] + ":" + str(other))
    assert sh(env2, "--research-root", str(tree)).returncode == 0
    data = json.loads((home / ".research-bridge" / "node.json").read_text(encoding="utf-8"))
    assert data["claude_bin"] == str(fake)


def test_script_sets_claude_bin_when_missing(sh_env, tmp_path):
    env, home, tree, _ = sh_env
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "claude").write_text("#!/bin/sh\n", encoding="utf-8")
    (other / "claude").chmod(0o755)
    env2 = dict(env, PATH=env["PATH"] + ":" + str(other))
    assert sh(env2, "--research-root", str(tree)).returncode == 0
    data = json.loads((home / ".research-bridge" / "node.json").read_text(encoding="utf-8"))
    assert data["claude_bin"] == str(other / "claude")


def test_script_update_swap_is_symlink(sh_env):
    env, home, tree, _ = sh_env
    share = home / ".local" / "share" / "research-bridge"
    targets = []
    for _ in range(4):
        assert sh(env, "--research-root", str(tree)).returncode == 0
        targets.append(os.readlink(str(share / "rb_node")))
        time.sleep(1.1)  # release names carry second-resolution stamps; pruning orders by mtime
    assert len(set(targets)) == 4
    kept = sorted(d.name for d in (share / "releases").iterdir() if d.is_dir() and d.name != "legacy")
    assert len(kept) == 2 and targets[-1].split("/")[1] in kept


def test_script_legacy_directory_moved(sh_env):
    env, home, tree, _ = sh_env
    share = home / ".local" / "share" / "research-bridge"
    (share / "rb_node").mkdir(parents=True)
    (share / "rb_node" / "old.py").write_text("x", encoding="utf-8")
    assert sh(env, "--research-root", str(tree)).returncode == 0
    assert (share / "rb_node").is_symlink()
    assert (share / "releases" / "legacy" / "rb_node" / "old.py").is_file()


def _alias_run(tmp_path, name, args):
    stub = tmp_path / ("stub-" + name)
    stub.mkdir()
    kg = stub / "ssh-keygen"
    kg.write_text("#!/bin/sh\necho '256 SHA256:TESTFINGERPRINT x (ED25519)'\n", encoding="utf-8")
    kg.chmod(0o755)
    hk = tmp_path / ("hk-" + name)
    hk.mkdir()
    (hk / "ssh_host_ed25519_key.pub").write_text("x", encoding="utf-8")
    home = tmp_path / ("home-" + name)
    home.mkdir()
    env = {"HOME": str(home), "PATH": "%s:%s:/usr/bin:/bin" % (stub, os.path.dirname(sys.executable)),
           "RB_NODE_HOSTKEY_GLOB": str(hk / "ssh_host_*_key.pub"), "PYTHONDONTWRITEBYTECODE": "1"}
    r = sh(env, *args)
    lines = [ln for ln in r.stdout.splitlines() if "serve-remote" in ln]
    cfg = json.loads((home / ".research-bridge" / "node.json").read_text(encoding="utf-8"))
    return r, [ln.replace(str(home), "HOME") for ln in lines], \
        {k: str(v).replace(str(home), "HOME") for k, v in cfg.items()}


def test_script_flag_aliases(sh_env, tmp_path):
    env, home, tree, _ = sh_env
    r1, lines1, cfg1 = _alias_run(tmp_path, "old", ["--trm-root", str(tree), "--hub-key", K1,
                                                    "--hub-from", "192.0.2.10"])
    r2, lines2, cfg2 = _alias_run(tmp_path, "new", ["--research-root", str(tree), "--hub-key", K1,
                                                    "--hub-from", "192.0.2.10"])
    assert r1.returncode == 0 and r2.returncode == 0, r1.stderr + r2.stderr
    assert lines1 and lines1 == lines2 and cfg1 == cfg2
    r3, lines3, _ = _alias_run(tmp_path, "subnet", ["--research-root", str(tree), "--hub-key", K1,
                                                    "--hub-subnet", "192.0.2.10"])
    assert r3.returncode == 0 and lines3 == lines2


def test_script_same_key_refused(sh_env):
    env, home, tree, _ = sh_env
    r = sh(env, "--research-root", str(tree), "--hub-key", K1, "--harness-key", K1,
           "--hub-from", "192.0.2.10")
    assert r.returncode == 2 and "hard rule 9" in r.stderr
    assert not (home / ".local").exists() and not (home / ".research-bridge").exists()


def test_script_bad_hub_from_refused_before_any_write(sh_env):
    env, home, tree, _ = sh_env
    r = sh(env, "--research-root", str(tree), "--hub-key", K1, "--hub-from", "not an address")
    assert r.returncode == 2
    assert not (home / ".local").exists() and not (home / ".research-bridge").exists()


def test_script_refuses_hub_data_directory(sh_env):
    env, home, tree, _ = sh_env
    share = home / ".local" / "share" / "research-bridge"
    share.mkdir(parents=True)
    (share / "host.json").write_text("{}", encoding="utf-8")
    r = sh(env, "--research-root", str(tree))
    assert r.returncode == 1 and "hub" in r.stderr
    assert not (share / "releases").exists()


def test_script_refuses_python_path_with_space(sh_env, tmp_path):
    env, home, tree, _ = sh_env
    spaced = tmp_path / "a b"
    spaced.mkdir()
    (spaced / "python3").symlink_to(sys.executable)
    env2 = dict(env, PATH="%s:%s" % (spaced, env["PATH"]))
    r = sh(env2, "--research-root", str(tree))
    assert r.returncode == 1 and "python3 path" in r.stderr


def test_script_withheld_file(sh_env, tmp_path):
    env, home, tree, _ = sh_env
    f = pattern_file(tmp_path / "w.json", ["zzq_[a-z]+"])
    assert sh(env, "--research-root", str(tree), "--withheld-file", str(f)).returncode == 0
    data = json.loads((home / ".research-bridge" / "node.json").read_text(encoding="utf-8"))
    dest = home / ".research-bridge" / "withheld-patterns.json"
    assert data["withheld_source"] == str(dest) and dest.read_bytes() == f.read_bytes()
    bad = pattern_file(tmp_path / "bad.json", ["bad(["])
    r = sh(env, "--research-root", str(tree), "--withheld-file", str(bad))
    assert r.returncode == 1
    assert dest.read_bytes() == f.read_bytes()


def test_script_update_without_upstream(sh_env, tmp_path):
    env, home, tree, _ = sh_env
    repo = tmp_path / "co"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "node-install.sh").write_text(SCRIPT.read_text(encoding="utf-8"),
                                                       encoding="utf-8")
    os.symlink(str(REPO / "rb_node"), str(repo / "rb_node"))
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=dict(env, HOME=str(home)))
    r = subprocess.run(["sh", str(repo / "scripts" / "node-install.sh"), "--update",
                        "--research-root", str(tree)], env=env, stdin=subprocess.DEVNULL,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "no upstream for this branch; installing the current checkout" in r.stdout


def test_deploy_examples_and_trm_link_removed():
    assert not (REPO / "scripts" / "trm-link.sh").exists()
    ak = (REPO / "deploy" / "authorized_keys.example").read_text(encoding="utf-8")
    assert 'from="<HUB_ADDR>"' in ak and "research-bridge-hub" in ak
    assert "/home/<NODE_USER>/.local/bin/rb-node harness-receive" in ak
    assert "--apply-authorized-keys" in ak
    ex = json.loads((REPO / "deploy" / "node.json.example").read_text(encoding="utf-8"))
    assert ex["withheld_source"] == "/home/<NODE_USER>/.research-bridge/withheld-patterns.json"
    for d in ("rb_node", "scripts", "deploy"):
        for p in (REPO / d).rglob("*"):
            if p.is_file() and p.suffix in (".py", ".sh", ".example"):
                assert "trm-link" not in p.read_text(encoding="utf-8", errors="replace"), p


def test_authorized_keys_non_utf8_file_kept_byte_for_byte(home, tmp_path, monkeypatch):
    ssh = home / ".ssh"
    ssh.mkdir()
    (ssh / "authorized_keys").write_bytes(b"# stray \xff byte\n")
    argv = ["authorized-keys", "--hub-key", K1, "--hub-from", "192.0.2.10",
            "--bindir", str(tmp_path / "bin")]
    assert install.main(argv) == 0
    monkeypatch.setattr(install, "_interactive", lambda: True)
    monkeypatch.setattr(install, "_ask", lambda prompt: True)
    assert install.main(argv + ["--apply"]) == 0
    data = (ssh / "authorized_keys").read_bytes()
    assert data.startswith(b"# stray \xff byte\n") and b"serve-remote" in data


def test_authorized_keys_symlink_not_replaced(tmp_path, monkeypatch, capsys):
    real = tmp_path / "managed"
    real.write_text("# x\n", encoding="utf-8")
    path = tmp_path / "authorized_keys"
    path.symlink_to(real)
    text, changes = install.plan_authorized_keys("# x\n", new_lines())
    monkeypatch.setattr(install, "_interactive", lambda: True)
    monkeypatch.setattr(install, "_ask", lambda p: True)
    assert install.apply_authorized_keys(path, text, changes) is False
    assert path.is_symlink() and real.read_text(encoding="utf-8") == "# x\n"


def test_write_private_ignores_leftover_tmp_symlink(tmp_path):
    victim = tmp_path / "victim"
    victim.write_text("keep", encoding="utf-8")
    (tmp_path / "f.tmp").symlink_to(victim)
    install._write_private(tmp_path / "f", b"new")
    assert victim.read_text(encoding="utf-8") == "keep"
    assert (tmp_path / "f").read_bytes() == b"new"


def test_config_init_force_keeps_custom_withheld_source_without_terminal(home, monkeypatch):
    cfgp = node_json(home)
    monkeypatch.setenv("RB_NODE_CONFIG", str(cfgp))
    data = json.loads(cfgp.read_text(encoding="utf-8"))
    data["withheld_source"] = "/custom.json"
    cfgp.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(cli, "_interactive", lambda: False)
    assert cli.main(["config", "init", "--force"]) == 1
    assert json.loads(cfgp.read_text(encoding="utf-8"))["withheld_source"] == "/custom.json"
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    assert cli.main(["config", "init", "--force"]) == 0


def test_withheld_custom_source_missing_needs_terminal(home, tmp_path, monkeypatch):
    cfgp = node_json(home)
    data = json.loads(cfgp.read_text(encoding="utf-8"))
    data["withheld_source"] = str(tmp_path / "gone.json")
    cfgp.write_text(json.dumps(data), encoding="utf-8")
    src = pattern_file(tmp_path / "new.json", ["harmless"])
    monkeypatch.setattr(install, "_interactive", lambda: False)
    assert install.install_withheld(src, dest_of(home), cfgp) == 1
    assert json.loads(cfgp.read_text(encoding="utf-8"))["withheld_source"] == data["withheld_source"]
