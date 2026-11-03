"""Host configuration (JSON) read from D:/raw/research-bridge/host.json."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_ROOT = "D:/raw/research-bridge"
DEFAULT_WITHHELD = "D:/raw/session-calendar/server/withheld_patterns.json"


@dataclass
class HostConfig:
    nodes: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    data_root: str = DEFAULT_ROOT
    withheld_patterns_file: str = DEFAULT_WITHHELD
    board: Dict[str, str] = field(default_factory=dict)  # laptop source paths for rb board

    def alias(self, node: str) -> str:
        entry = self.nodes.get(node)
        if not isinstance(entry, dict) or not isinstance(entry.get("alias"), str):
            raise ValueError("unknown node: %s" % node)
        return entry["alias"]


def load_host_config(path: Optional[Path] = None) -> HostConfig:
    p = Path(path) if path is not None else Path(DEFAULT_ROOT) / "host.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("host config must be a JSON object: %s" % p)
    kw = {k: data[k] for k in ("nodes", "data_root", "withheld_patterns_file", "board") if k in data}
    return HostConfig(**kw)
