"""Host configuration (JSON) read from <data root>/host.json.

Data root: RB_HOST_ROOT if set; otherwise D:/raw/research-bridge on Windows and
~/.local/share/research-bridge elsewhere. RB_HOST_CONFIG overrides the host.json path only.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

WINDOWS_ROOT = "D:/raw/research-bridge"
WINDOWS_WITHHELD = "D:/raw/session-calendar/server/withheld_patterns.json"


def default_root() -> str:
    """Hub data directory. A Windows drive path on Linux would be a relative path under the
    current directory, so each platform has its own default."""
    env = os.environ.get("RB_HOST_ROOT")
    if env:
        return env
    if os.name == "nt":
        return WINDOWS_ROOT
    return (Path.home() / ".local" / "share" / "research-bridge").as_posix()


def host_json_path() -> Path:
    """host.json: RB_HOST_CONFIG when set (and not empty), else <data root>/host.json. The one
    place of this rule; `jobs.load_cfg`, `configure.host_path` and `rb sync` use it."""
    p = os.environ.get("RB_HOST_CONFIG")
    return Path(p) if p else Path(default_root()) / "host.json"


def default_withheld() -> str:
    """Withheld-pattern JSON. On Windows it is the session-calendar export in the vault;
    elsewhere a copy the user places in the data root."""
    if os.name == "nt" and not os.environ.get("RB_HOST_ROOT"):
        return WINDOWS_WITHHELD
    return (Path(default_root()) / "withheld_patterns.json").as_posix()


@dataclass
class HostConfig:
    nodes: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    data_root: str = field(default_factory=default_root)
    withheld_patterns_file: str = field(default_factory=default_withheld)
    board: Dict[str, str] = field(default_factory=dict)  # laptop source paths for rb board
    share: Dict[str, Any] = field(default_factory=dict)  # /status of the hub page: calendar_sessions|calendar_status|runs paths, labels list

    def alias(self, node: str) -> str:
        entry = self.nodes.get(node)
        if not isinstance(entry, dict) or not isinstance(entry.get("alias"), str):
            raise ValueError("unknown node: %s" % node)
        return entry["alias"]


class WrongTypes(ValueError):
    """host.json parsed, but a key has the wrong type."""


def wrong_types(data: Any) -> List[str]:
    """Problems with the types of the keys of a parsed host.json (empty when all are fine)."""
    if not isinstance(data, dict):
        return ["the top level must be an object"]
    bad = []  # type: List[str]
    nodes = data.get("nodes")
    if "nodes" in data and (not isinstance(nodes, dict)  # null is a wrong type, not "absent"
                            or not all(isinstance(v, dict) for v in nodes.values())):
        bad.append("nodes must be an object whose values are objects")
    for key in ("data_root", "withheld_patterns_file"):
        if key in data and not isinstance(data[key], str):
            bad.append("%s must be a string" % key)
    for key in ("board", "share"):
        if key in data and not isinstance(data[key], dict):
            bad.append("%s must be an object" % key)
    return bad


def load_host_config(path: Optional[Path] = None) -> HostConfig:
    p = Path(path) if path is not None else Path(default_root()) / "host.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("host config must be a JSON object: %s" % p)
    bad = wrong_types(data)
    if bad:
        raise WrongTypes("wrong types: " + "; ".join(bad))
    kw = {k: data[k] for k in ("nodes", "data_root", "withheld_patterns_file", "board", "share") if k in data}
    if "withheld_patterns_file" not in kw and "data_root" in kw and default_withheld() != WINDOWS_WITHHELD:
        kw["withheld_patterns_file"] = (Path(kw["data_root"]) / "withheld_patterns.json").as_posix()
    return HostConfig(**kw)
