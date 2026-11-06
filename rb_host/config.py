"""Host configuration (JSON) read from <data root>/host.json.

Data root: RB_HOST_ROOT if set; otherwise D:/raw/research-bridge on Windows and
~/.local/share/research-bridge elsewhere. RB_HOST_CONFIG overrides the host.json path only.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

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
    share: Dict[str, Any] = field(default_factory=dict)  # rb share: calendar_sessions|calendar_status|runs paths, labels list

    def alias(self, node: str) -> str:
        entry = self.nodes.get(node)
        if not isinstance(entry, dict) or not isinstance(entry.get("alias"), str):
            raise ValueError("unknown node: %s" % node)
        return entry["alias"]


def load_host_config(path: Optional[Path] = None) -> HostConfig:
    p = Path(path) if path is not None else Path(default_root()) / "host.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("host config must be a JSON object: %s" % p)
    kw = {k: data[k] for k in ("nodes", "data_root", "withheld_patterns_file", "board", "share") if k in data}
    if "withheld_patterns_file" not in kw and "data_root" in kw and default_withheld() != WINDOWS_WITHHELD:
        kw["withheld_patterns_file"] = (Path(kw["data_root"]) / "withheld_patterns.json").as_posix()
    return HostConfig(**kw)
