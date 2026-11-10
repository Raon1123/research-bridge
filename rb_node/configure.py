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
    elif not isinstance(value, str):
        value = str(value)
    out = dict(data)
    out[key] = value
    return out


def node_check(data: Dict[str, Any]) -> List[str]:
    """Problems that block a feature, one line each. Empty list = ready."""
    from .config import NodeConfig
    probs: List[str] = []
    known = {f.name for f in fields(NodeConfig)}
    for k in data:
        if k not in known:
            probs.append("unknown key %r is ignored" % k)
    cfg = NodeConfig(**{k: v for k, v in data.items() if k in known})
    tpl = cfg.job_template
    if not tpl:
        probs.append("job_template is empty: job_submit is refused (no_job_template)")
    elif not any(k in a for a in tpl for k in ("{config}", "{config_dir}", "{config_stem}")):
        probs.append("job_template has no {config}, {config_dir} or {config_stem} placeholder")
    if not cfg.allowed_gpus:
        probs.append("allowed_gpus is empty: job_submit is refused (no_allowed_gpus)")
    if not cfg.harness_root:
        probs.append("harness_root is empty: harness push/pull are refused (no_harness_root)")
    elif not Path(cfg.harness_root).is_dir():
        probs.append("harness_root does not exist: %s" % cfg.harness_root)
    if not Path(cfg.trm_root).is_dir():
        probs.append("trm_root does not exist: %s" % cfg.trm_root)
    for r in cfg.read_roots:
        p = Path(r) if os.path.isabs(r) else Path(cfg.trm_root) / r
        if not p.is_dir():
            probs.append("read root does not exist: %s" % p)
    if not cfg.withheld_source:
        probs.append("withheld_source unset: only the fallback patterns apply")
    elif not cfg.withheld_source.endswith(".json"):
        probs.append("withheld_source is not JSON: only the fallback patterns apply")
    elif not Path(cfg.withheld_source).is_file():
        probs.append("withheld_source not found: %s" % cfg.withheld_source)
    if not Path(cfg.claude_bin).is_file():
        probs.append("claude_bin not found: %s" % cfg.claude_bin)
    ap = Path(cfg.approval_path).absolute()
    roots = [Path(r) if os.path.isabs(r) else Path(cfg.trm_root) / r
             for r in list(cfg.read_roots) + list(cfg.write_roots)]
    for r in roots:
        try:
            ap.relative_to(r.absolute())
            probs.append("approval_path is inside a read/write root: %s" % r)
        except ValueError:
            pass
    if not ap.is_file():
        probs.append("approval verifier missing: run `rb-node approve-key set` on the console")
    return probs
