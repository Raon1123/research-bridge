"""`rb service`: systemd user units for unattended sync and the hub page.

The unit text is fixed by docs/design/2026-11-10-sync-and-hub-page.md section 6.10. rb writes the
files after a y and prints, never runs, the systemctl and loginctl commands.
"""
from __future__ import annotations

import difflib
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, Optional

from . import configure, sshenv

UNIT_NAMES = ("rb-sync.service", "rb-sync.timer", "rb-web.service")


def unit_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base and os.path.isabs(base) else sshenv.user_home() / ".config"
    return root / "systemd" / "user"


def rb_path() -> Path:
    return Path(sys.executable).with_name("rb")


def installed_interval() -> Optional[int]:
    """OnUnitInactiveSec of the installed rb-sync.timer, or None."""
    try:
        text = (unit_dir() / "rb-sync.timer").read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"^OnUnitInactiveSec=(\d+)\s*$", text, re.M)
    return int(m.group(1)) if m else None


def units(rb: Path, host_json: Path, interval: int, port: int,
          rb_host_root: Optional[str]) -> Dict[str, str]:
    env = ["Environment=RB_HOST_CONFIG=%s" % host_json]
    if rb_host_root:
        env.append("Environment=RB_HOST_ROOT=%s" % rb_host_root)
    env_text = "\n".join(env)
    sync = """[Unit]
Description=research-bridge hub sync, one pass per start (pull only; never approves a job)
ConditionPathExists=%(hj)s

[Service]
Type=oneshot
%(env)s
ExecStart=%(rb)s sync
TimeoutStartSec=240
NoNewPrivileges=yes
""" % {"hj": host_json, "env": env_text, "rb": rb}
    timer = """[Unit]
Description=Start rb-sync.service every %(i)d seconds

[Timer]
OnActiveSec=60
OnUnitInactiveSec=%(i)d
RandomizedDelaySec=20
AccuracySec=10s

[Install]
WantedBy=timers.target
""" % {"i": interval}
    web = """[Unit]
Description=research-bridge hub page (read-only, loopback)
ConditionPathExists=%(hj)s

[Service]
Type=simple
%(env)s
ExecStart=%(rb)s web serve --port %(port)d --bind 127.0.0.1
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes

[Install]
WantedBy=default.target
""" % {"hj": host_json, "env": env_text, "rb": rb, "port": port}
    return {"rb-sync.service": sync, "rb-sync.timer": timer, "rb-web.service": web}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, str(path))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def install(interval: int = 300, port: int = 8767, print_only: bool = False) -> int:
    from . import setup

    hj = configure.host_path()
    if not hj.is_file():
        print(configure.host_json_error(FileNotFoundError()))
        return 1
    if interval < 30 or not 1 <= port <= 65535:
        print("error: --interval must be at least 30 and --port between 1 and 65535")
        return 1
    rb = rb_path()
    hj = hj.absolute()
    for p in (rb, hj):
        if re.search(r"[\s%]", str(p)):
            print("error: %s contains a space or a percent sign; systemd unit lines cannot hold it" % p)
            return 1
    if "/.claude/worktrees/" in rb.as_posix():
        print("warning: %s lies in a git worktree, which is deleted later; run rb service install "
              "from the main checkout's environment" % rb)
    texts = units(rb, hj, interval, port, os.environ.get("RB_HOST_ROOT") or None)
    d = unit_dir()
    for name in UNIT_NAMES:
        path = d / name
        new = texts[name]
        old = None
        if path.is_file():
            old = path.read_text(encoding="utf-8", errors="replace")
            if old == new:
                print("%s: unchanged" % path)
                continue
        print("--- %s ---" % path)
        print(new, end="")
        if old is not None:
            print("--- changes against the installed file ---")
            sys.stdout.writelines(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                                       "installed", "new"))
        if print_only:
            continue
        if not setup.ask("%s %s? [y/N] " % ("Replace" if old is not None else "Write", path)):
            print("%s: not written" % path)
            continue
        if old is not None:
            bak = path.with_name("%s.bak.%s" % (name, time.strftime("%Y%m%d%H%M%S")))
            shutil.copy2(str(path), str(bak))
            print("backup: %s" % bak)
        _write(path, new)
        print("%s: written" % path)
    print("Then run these yourself (rb does not run them):")
    print("  systemctl --user daemon-reload && systemctl --user enable --now "
          "rb-sync.timer rb-web.service")
    user = sshenv.user_name()
    if sshenv.linger(user) is not True:
        print("  loginctl enable-linger %s   # user units stop at logout otherwise; may need an "
              "administrator" % user)
    print("After each reboot, load the keys: rb agent")
    return 0


def status() -> int:
    for name in UNIT_NAMES:
        _, enabled = sshenv.systemctl_user("is-enabled", name)
        _, active = sshenv.systemctl_user("is-active", name)
        print("%-18s enabled=%s active=%s" % (name, enabled or "unknown", active or "unknown"))
    rc, out = sshenv.systemctl_user("show", "rb-sync.service", "-p", "Result,ExecMainExitTimestamp")
    if rc == 0 and out:
        for line in out.splitlines():
            print("rb-sync.service    %s" % line)
    state = sshenv.linger(sshenv.user_name())
    print("linger: %s" % ("yes" if state else "no" if state is False else "unknown"))
    return 0
