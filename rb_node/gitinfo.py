"""Read-only git state for the research tree and the installed code (stdlib only).

Reports only: branch, commit sha, dirty-file COUNT, upstream ahead/behind, and the origin URL with
credentials removed. Never file names, commit subjects or diffs, so no withheld text can ride along.
No network access: ahead/behind uses the last fetched upstream.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

TIMEOUT = 20
_SHA = re.compile(r"^[0-9a-f]{40}$")


def _git(root: Path, *args: str) -> Optional[str]:
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    try:
        r = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(root)] + list(args),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=TIMEOUT, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", "replace").strip()


def _clean_url(url: str) -> str:
    """Drop user:password@ from an http(s)/ssh URL."""
    return re.sub(r"^([a-z+]+://)[^/@]*@", r"\1", url)


def repo_state(root: Path) -> Dict[str, Any]:
    """{"available": False} outside a work tree; otherwise the fields listed in the module doc."""
    root = Path(root)
    if not root.is_dir() or _git(root, "rev-parse", "--is-inside-work-tree") != "true":
        return {"available": False}
    head = _git(root, "rev-parse", "HEAD") or ""
    out = {"available": True,
           "head": head if _SHA.match(head) else None,
           "branch": _git(root, "symbolic-ref", "--short", "-q", "HEAD") or None}  # None = detached
    porcelain = _git(root, "status", "--porcelain")
    out["dirty_files"] = None if porcelain is None else len([x for x in porcelain.splitlines() if x])
    up = _git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    out["upstream"] = up or None
    if up:
        counts = (_git(root, "rev-list", "--left-right", "--count", "HEAD...@{upstream}") or "").split()
        if len(counts) == 2 and all(c.isdigit() for c in counts):
            out["ahead"], out["behind"] = int(counts[0]), int(counts[1])
    url = _git(root, "config", "--get", "remote.origin.url")
    out["origin"] = _clean_url(url) if url else None
    return out


def mask_state(state: Dict[str, Any], withheld: Any) -> Dict[str, Any]:
    """Blank string fields that match a withheld pattern (a branch name can carry a series name)."""
    out = dict(state)
    for k in ("branch", "upstream", "origin"):
        v = out.get(k)
        if isinstance(v, str) and withheld.name_hit(v):
            out[k] = "[withheld]"
    return out


def install_path(rb_home: Path) -> Path:
    return Path(rb_home) / "install.json"


def read_install(rb_home: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(install_path(rb_home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_install(rb_home: Path, source_repo: Path, version: str) -> Dict[str, Any]:
    """Record which commit of the research-bridge checkout was installed (node-install.sh calls this)."""
    rec = {"installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "version": version,
           "source": repo_state(source_repo)}
    path = install_path(rb_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    os.chmod(str(tmp), 0o600)
    os.replace(str(tmp), str(path))
    return rec
