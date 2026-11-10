from __future__ import annotations

import re
import stat
from pathlib import Path

import pytest

import hubfake
from rb_host import cli, configure, service, setup, sshenv

DESIGN = Path(__file__).resolve().parents[1] / "docs" / "design" / "2026-11-10-sync-and-hub-page.md"
RB = Path("/opt/rb/.venv/bin/rb")
HJ = Path("/srv/d/host.json")


@pytest.fixture
def hub(monkeypatch, tmp_path):
    h = hubfake.install(monkeypatch, tmp_path)
    monkeypatch.setattr(service, "rb_path", lambda: RB)
    return h


def template(name):
    """The indented block that follows the heading `name` in design section 6.10."""
    lines = DESIGN.read_text(encoding="utf-8").splitlines()
    i = lines.index("`%s`" % name)
    out = []
    for ln in lines[i + 2:]:
        if ln.startswith("    "):
            out.append(ln[4:])
        elif ln.strip() == "" and out:
            out.append("")
        else:
            break
    return "\n".join(out).rstrip("\n") + "\n"


def test_units_use_absolute_rb_path_and_no_ssh_auth_sock():
    u = service.units(RB, HJ, 300, 8767, None)
    assert set(u) == set(service.UNIT_NAMES)
    assert "ExecStart=/opt/rb/.venv/bin/rb sync" in u["rb-sync.service"]
    assert "ConditionPathExists=/srv/d/host.json" in u["rb-sync.service"]
    assert "OnActiveSec=60" in u["rb-sync.timer"] and "OnUnitInactiveSec=300" in u["rb-sync.timer"]
    assert "--port 8767 --bind 127.0.0.1" in u["rb-web.service"]
    for text in u.values():
        assert "SSH_AUTH_SOCK" not in text and "uv run" not in text
        assert "EnvironmentFile" not in text and "ExecStartPre" not in text
    for n in ("rb-sync.service", "rb-web.service"):
        assert "Environment=RB_HOST_CONFIG=/srv/d/host.json" in u[n]
        assert "RB_HOST_ROOT" not in u[n]


def test_units_rb_host_root_only_when_set():
    u = service.units(RB, HJ, 300, 8767, "/srv/d")
    for n in ("rb-sync.service", "rb-web.service"):
        assert "Environment=RB_HOST_CONFIG=/srv/d/host.json" in u[n]
        assert "Environment=RB_HOST_ROOT=/srv/d" in u[n].splitlines()
    assert "Environment" not in u["rb-sync.timer"]


@pytest.mark.parametrize("root", [None, "/srv/d"])
def test_unit_text_matches_sync_design(root):
    u = service.units(RB, HJ, 120, 9000, root)
    for name in service.UNIT_NAMES:
        want = template(name)
        want = (want.replace("{host_json}", str(HJ)).replace("{rb}", str(RB))
                .replace("{interval}", "120").replace("{port}", "9000"))
        want = want.replace("{rb_host_root_line}\n", "Environment=RB_HOST_ROOT=%s\n" % root if root else "")
        assert u[name].splitlines() == want.splitlines(), name


def _host_json(hub):
    hp = hub.tmp / "data" / "host.json"
    hp.parent.mkdir(exist_ok=True)
    hp.write_text("{}", encoding="utf-8")
    return hp


def test_install_writes_after_yes_with_backup(hub, monkeypatch, tmp_path):
    _host_json(hub)
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    d = hub.home / ".config" / "systemd" / "user"
    d.mkdir(parents=True)
    (d / "rb-sync.timer").write_text("old timer\n", encoding="utf-8")
    assert cli.main(["service", "install"]) == 0
    for n in service.UNIT_NAMES:
        assert stat.S_IMODE((d / n).stat().st_mode) == 0o644
    baks = list(d.glob("rb-sync.timer.bak.*"))
    assert len(baks) == 1 and baks[0].read_text(encoding="utf-8") == "old timer\n"
    assert len(hub.asks) == 3


def test_install_declined_writes_nothing(hub, monkeypatch):
    _host_json(hub)
    hub.answer = False
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    assert cli.main(["service", "install"]) == 0
    assert not (hub.home / ".config").exists()


def test_install_unchanged_files_not_asked(hub, monkeypatch, capsys):
    _host_json(hub)
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    assert cli.main(["service", "install"]) == 0
    hub.asks.clear()
    assert cli.main(["service", "install"]) == 0
    assert hub.asks == [] and "unchanged" in capsys.readouterr().out


def test_install_print_writes_nothing(hub, monkeypatch, capsys):
    _host_json(hub)
    monkeypatch.setattr(cli, "_interactive", lambda: False)
    assert cli.main(["service", "install", "--print"]) == 0
    assert not (hub.home / ".config").exists() and hub.asks == []
    assert "ExecStart=/opt/rb/.venv/bin/rb sync" in capsys.readouterr().out


def test_install_prints_systemctl_not_runs(hub, monkeypatch, capsys):
    _host_json(hub)
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    seen = []
    monkeypatch.setattr(sshenv, "systemctl_user", lambda *a: seen.append(a) or (0, ""))
    assert cli.main(["service", "install"]) == 0
    assert seen == []
    out = capsys.readouterr().out
    assert ("systemctl --user daemon-reload && systemctl --user enable --now "
            "rb-sync.timer rb-web.service") in out
    assert "loginctl enable-linger hubuser" in out
    hub.linger_value = "yes"
    assert cli.main(["service", "install"]) == 0
    assert "enable-linger" not in capsys.readouterr().out


def test_install_warns_for_worktree_rb(hub, monkeypatch, capsys):
    _host_json(hub)
    monkeypatch.setattr(service, "rb_path", lambda: Path("/x/.claude/worktrees/w/.venv/bin/rb"))
    assert cli.main(["service", "install", "--print"]) == 0
    assert "worktree" in capsys.readouterr().out


def test_install_rb_host_root_copied_from_shell(hub, monkeypatch, capsys):
    _host_json(hub)
    assert cli.main(["service", "install", "--print"]) == 0
    assert "Environment=RB_HOST_ROOT=%s" % (hub.tmp / "data") in capsys.readouterr().out
    monkeypatch.delenv("RB_HOST_ROOT")
    monkeypatch.setenv("RB_HOST_CONFIG", str(hub.tmp / "data" / "host.json"))
    assert cli.main(["service", "install", "--print"]) == 0
    assert "RB_HOST_ROOT" not in capsys.readouterr().out


def test_install_refuses_without_host_json(hub, capsys):
    assert service.install(print_only=True) == 1
    assert capsys.readouterr().out.startswith("error: no host.json at")


def test_status_reads_systemctl(hub, capsys):
    hub.systemctl.update({("is-enabled", "rb-sync.timer"): (0, "enabled", ""),
                          ("is-active", "rb-sync.timer"): (0, "active", ""),
                          ("is-active", "rb-web.service"): (3, "inactive", ""),
                          ("show", "rb-sync.service", "-p", "Result,ExecMainExitTimestamp"):
                              (0, "Result=success\nExecMainExitTimestamp=Tue", "")})
    assert service.status() == 0
    out = capsys.readouterr().out
    assert "rb-sync.timer" in out and "enabled=enabled active=active" in out
    assert "rb-web.service" in out and "active=inactive" in out
    assert "Result=success" in out and "linger: no" in out


def test_requires_terminal_unless_print(hub, monkeypatch, capsys):
    _host_json(hub)
    monkeypatch.setattr(cli, "_interactive", lambda: False)
    assert cli.main(["service", "install"]) == 1
    assert "terminal" in capsys.readouterr().out
    assert not (hub.home / ".config").exists()
    assert cli.main(["service", "install", "--print"]) == 0
    assert not (hub.home / ".config").exists()


def test_install_refuses_rb_host_root_with_space_and_absolutizes(hub, monkeypatch, capsys, tmp_path):
    _host_json(hub)
    monkeypatch.setenv("RB_HOST_CONFIG", str(hub.tmp / "data" / "host.json"))
    monkeypatch.setenv("RB_HOST_ROOT", str(tmp_path / "rb data"))
    assert cli.main(["service", "install", "--print"]) == 1
    assert "space or a percent" in capsys.readouterr().out
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RB_HOST_ROOT", "rel")
    assert cli.main(["service", "install", "--print"]) == 0
    assert "Environment=RB_HOST_ROOT=%s" % (tmp_path / "rel") in capsys.readouterr().out
