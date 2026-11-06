"""`rb config`: write and check the laptop's config files from the command line.

Files: host.json (<data root>/host.json, or RB_HOST_CONFIG; data root in rb_host.config) and private/local.json in the
checkout (gitignored). Every write is refused if git would track the target
(rb_node.configure.git_exposure). ~/.ssh/config and ~/.claude.json are only read, never
written: `rb config mcp` prints the entry for the user to add.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

from rb_node.configure import ConfigError, git_exposure, read_json, write_json

from .config import default_root, default_withheld

REPO = Path(__file__).resolve().parent.parent
NODE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
TOP_KEYS = ("data_root", "withheld_patterns_file")
BOARD_KEYS = ("portfolio", "priorities")
SHARE_KEYS = ("calendar_sessions", "calendar_status", "runs")
NODE_KEYS = ("alias", "harness_alias")
NODE_BOARD_KEYS = ("state", "events", "kanban")


def host_path() -> Path:
    p = os.environ.get("RB_HOST_CONFIG")
    return Path(p) if p else Path(default_root()) / "host.json"


def local_path() -> Path:
    return REPO / "private" / "local.json"


def _load(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise ConfigError("no %s; run `rb config init` first" % path)
    return read_json(path)


def init(data_root: str = "", force: bool = False) -> Path:
    path = host_path()
    if path.exists() and not force:
        raise ConfigError("%s exists; use --force to overwrite" % path)
    data: Dict[str, Any] = {"nodes": {}}
    if data_root:
        data["data_root"] = data_root
    write_json(path, data)
    return path


def add_node(name: str, alias: str = "", harness_alias: str = "", force: bool = False) -> Dict:
    if not NODE_NAME.match(name):
        raise ConfigError("node name must be letters, digits, '-' or '_' (max 32)")
    path = host_path()
    data = _load(path)
    nodes = data.setdefault("nodes", {})
    if name in nodes and not force:
        raise ConfigError("node %s exists; use --force to replace it" % name)
    entry = {"alias": alias or "rb-" + name, "harness_alias": harness_alias or "rb-%s-harness" % name}
    nodes[name] = entry
    write_json(path, data)
    return entry


def remove_node(name: str) -> None:
    path = host_path()
    data = _load(path)
    if name not in data.get("nodes", {}):
        raise ConfigError("unknown node: %s" % name)
    del data["nodes"][name]
    write_json(path, data)


def set_key(key: str, value: str) -> None:
    """Dotted keys: data_root, withheld_patterns_file, board.<portfolio|priorities>,
    share.<calendar_sessions|calendar_status|runs>, nodes.<name>.<alias|harness_alias>, nodes.<name>.board.<state|events|kanban>."""
    path = host_path()
    data = _load(path)
    parts = key.split(".")
    if len(parts) == 1 and key in TOP_KEYS:
        data[key] = value
    elif len(parts) == 2 and parts[0] == "board" and parts[1] in BOARD_KEYS:
        data.setdefault("board", {})[parts[1]] = value
    elif len(parts) == 2 and parts[0] == "share" and parts[1] in SHARE_KEYS:
        data.setdefault("share", {})[parts[1]] = value
    elif len(parts) >= 3 and parts[0] == "nodes":
        node = data.get("nodes", {}).get(parts[1])
        if node is None:
            raise ConfigError("unknown node %s; add it with `rb config add-node`" % parts[1])
        if len(parts) == 3 and parts[2] in NODE_KEYS:
            node[parts[2]] = value
        elif len(parts) == 4 and parts[2] == "board" and parts[3] in NODE_BOARD_KEYS:
            node.setdefault("board", {})[parts[3]] = value
        else:
            raise ConfigError("unknown key %s" % key)
    else:
        raise ConfigError("unknown key %s; see `rb config set --help`" % key)
    write_json(path, data)


def set_local(laptop_home: str = "", node_home: str = "") -> Path:
    path = local_path()
    data = read_json(path) if path.is_file() else {}
    if laptop_home:
        data["laptop_home"] = laptop_home.replace("\\", "/")
    if node_home:
        data["node_home"] = node_home
    write_json(path, data)
    return path


def mcp_entry() -> Dict[str, Any]:
    root = Path(__file__).resolve().parents[1].as_posix()
    entry: Dict[str, Any] = {"type": "stdio", "command": "uv",
                             "args": ["run", "--directory", root, "--extra", "host",
                                      "python", "-m", "rb_host.server"]}
    env = {k: os.environ[k] for k in ("RB_HOST_ROOT", "RB_HOST_CONFIG") if os.environ.get(k)}
    if env:
        entry["env"] = env
    return {"research-bridge": entry}


def _ssh_hosts() -> List[str]:
    p = Path.home() / ".ssh" / "config"
    if not p.is_file():
        return []
    hosts: List[str] = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"\s*Host\s+(.+)", line, re.I)
        if m:
            hosts.extend(m.group(1).split())
    return hosts


def check() -> List[str]:
    """Problems, one line each; empty = ready. Reads ~/.ssh/config and ~/.claude.json only."""
    probs: List[str] = []
    hp = host_path()
    for p in (hp, local_path()):
        if p.exists():
            reason = git_exposure(p)
            if reason:
                probs.append("LEAK RISK: " + reason)
    if not hp.is_file():
        return probs + ["no %s: run `rb config init`" % hp]
    try:
        data = read_json(hp)
    except ConfigError as exc:
        return probs + [str(exc)]
    nodes = data.get("nodes") or {}
    if not nodes:
        probs.append("no node in host.json: run `rb config add-node <name>`")
    hosts = _ssh_hosts()
    for name, entry in nodes.items():
        for k in NODE_KEYS:
            a = (entry or {}).get(k) or ("rb-%s-harness" % name if k == "harness_alias" else "")
            if not a:
                probs.append("node %s has no %s" % (name, k))
            elif a not in hosts:
                probs.append("node %s: %s %r is not a Host in ~/.ssh/config" % (name, k, a))
    root = Path(data.get("data_root") or default_root())
    if not root.is_dir():
        probs.append("data_root does not exist: %s" % root)
    wp = Path(data.get("withheld_patterns_file") or default_withheld())
    if not wp.is_file():
        probs.append("withheld_patterns_file does not exist: %s (the hub re-check falls back to "
                     "the five built-in patterns only)" % wp)
    if not local_path().is_file():
        probs.append("no private/local.json: run `rb config local --laptop-home ... "
                     "--node-home ...` (harness path mapping falls back to guesses)")
    cj = Path.home() / ".claude.json"
    try:
        servers = json.loads(cj.read_text(encoding="utf-8")).get("mcpServers") or {}
    except (OSError, ValueError, AttributeError):
        servers = {}
    if "research-bridge" not in servers:
        probs.append("MCP server not registered in ~/.claude.json: add the entry from `rb config mcp`")
    return probs
