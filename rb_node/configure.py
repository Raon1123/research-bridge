"""Write and check config files from the command line, without leaking them into git.

Shared by `rb config` (laptop) and `rb-node config` (node console). Standard library only.
A config file holds real host names, paths and user names, so every write first asks git
whether the target would be tracked: inside a work tree and not ignored -> refused.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, Dict, List, Optional


class ConfigError(Exception):
    pass


def git_exposure(path: Path) -> Optional[str]:
    """None if git would not track `path`; else the reason it would.

    No git on PATH or no work tree around the file -> None (nothing can commit it)."""
    path = Path(path).absolute()
    d = path.parent
    while not d.exists():
        d = d.parent
    try:
        top = subprocess.run(["git", "-C", str(d), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if top.returncode != 0:
        return None
    root = top.stdout.strip()
    ls = subprocess.run(["git", "-C", root, "ls-files", "--error-unmatch", str(path)],
                        capture_output=True, text=True, timeout=20)
    if ls.returncode == 0:
        return "%s is tracked by git in %s" % (path, root)
    ign = subprocess.run(["git", "-C", root, "check-ignore", "-q", str(path)],
                         capture_output=True, text=True, timeout=20)
    if ign.returncode != 0:
        return "%s is inside the git work tree %s and not ignored (add it to .gitignore)" % (
            path, root)
    return None


def write_json(path: Path, data: Dict[str, Any], mode: int = 0o600) -> None:
    """Atomic write with mode 600 after the git check."""
    path = Path(path)
    reason = git_exposure(path)
    if reason:
        raise ConfigError("refusing to write: " + reason)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.chmod(tmp, mode)
        os.replace(tmp, str(path))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ConfigError("%s is not valid JSON (%s)" % (path, exc))
    if not isinstance(data, dict):
        raise ConfigError("%s must hold a JSON object" % path)
    return data


def parse_value(raw: str) -> Any:
    """A JSON literal (list, number, true/false, quoted string) if it parses, else the raw text."""
    try:
        return json.loads(raw)
    except ValueError:
        return raw


# ---------------------------------------------------------------------------
# node.json (rb-node config)
# ---------------------------------------------------------------------------
def _node_types() -> Dict[str, type]:
    from .config import NodeConfig
    return {f.name: type(getattr(NodeConfig(), f.name)) for f in fields(NodeConfig)}


def node_defaults() -> Dict[str, Any]:
    from .config import NodeConfig
    return asdict(NodeConfig())


def node_set(data: Dict[str, Any], key: str, value: Any) -> Dict[str, Any]:
    types = _node_types()
    if key not in types:
        raise ConfigError("unknown key %r; keys: %s" % (key, ", ".join(sorted(types))))
    want = types[key]
    if key == "withheld_source" and value in (None, ""):
        value = None
    elif key == "allowed_gpus":
        if not (isinstance(value, list) and len(set(value)) == len(value) and all(
                isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in value)):
            raise ConfigError("allowed_gpus needs a JSON list of distinct GPU indices, e.g. '[4, 5]'")
    elif want is list:
        if not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
            raise ConfigError("%s needs a JSON list of strings, e.g. '[\"a\", \"b\"]'" % key)
    elif want is int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ConfigError("%s needs a positive integer" % key)
        from .protocol import MAX_FILE
        if key == "max_file" and value > MAX_FILE:
            raise ConfigError("max_file can be at most %d (50 MB, AGENTS.md hard rule 5)" % MAX_FILE)
    elif not isinstance(value, str):
        value = str(value)
    from .config import NodeConfig, PATH_KEYS, PATH_LIST_KEYS, default_dependents
    if key in PATH_KEYS and isinstance(value, str) and value.startswith("~"):
        value = os.path.expanduser(value)
    if key in PATH_LIST_KEYS and isinstance(value, list):
        value = [os.path.expanduser(v) if v.startswith("~") else v for v in value]
    out = dict(data)
    out[key] = value
    if key == "trm_root" and isinstance(value, str):
        old = data.get("trm_root")
        old = old if isinstance(old, str) else NodeConfig().trm_root
        if old != value:
            od, nd = default_dependents(old), default_dependents(value)
            if out.get("queue_dir", od["queue_dir"]) == od["queue_dir"]:
                out["queue_dir"] = nd["queue_dir"]
            wr = out.get("write_roots", [NodeConfig().write_roots[0], od["queue_jobs"]])
            if isinstance(wr, list):
                out["write_roots"] = [nd["queue_jobs"] if e == od["queue_jobs"] else e for e in wr]
            if out.get("withheld_source") == od["old_withheld"]:
                out["withheld_source"] = NodeConfig().withheld_source
    return out


def node_check(data: Dict[str, Any]) -> List[str]:
    """Problems that block a feature, one line each. Empty list = ready."""
    from . import doctor
    return [c.message for c in doctor.config_checks(data) if c.level != "ok"]
