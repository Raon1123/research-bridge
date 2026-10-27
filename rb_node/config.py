"""Node configuration (JSON). Roots come from here only, never from the host."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import List, Optional

DEFAULT_TRM = "/home/<NODE_USER>/project/trm"
DEFAULT_RB = "~/.research-bridge"


def _home(p: str) -> str:
    return os.path.expanduser(p)


@dataclass
class NodeConfig:
    trm_root: str = DEFAULT_TRM
    read_roots: List[str] = field(default_factory=lambda: [
        "lab/registry/", "lab/experiments/", "lab/reports/", "reports/figures/",
        _home(DEFAULT_RB + "/mailbox/out/")])
    write_roots: List[str] = field(default_factory=lambda: [
        _home(DEFAULT_RB + "/mailbox/in/"), DEFAULT_TRM + "/scripts/queue/jobs"])
    queue_dir: str = DEFAULT_TRM + "/scripts/queue"
    withheld_source: Optional[str] = DEFAULT_TRM + "/lab/11_governance/11_lab-root/WITHHELD_RUNS.yaml"
    claude_bin: str = "/home/<NODE_USER>/.local/bin/claude"
    job_template: List[str] = field(default_factory=list)  # argv with {config} placeholder
    max_file: int = 50 * 1024 * 1024
    mailbox_root: str = _home(DEFAULT_RB + "/mailbox")
    audit_path: str = _home(DEFAULT_RB + "/audit.jsonl")
    harness_root: str = ""  # node's ~/.claude; empty -> harness push/pull refused (no_harness_root)
    harness_root: str = ""  # node's ~/.claude; empty -> harness push/pull refused (no_harness_root)


def config_path() -> Path:
    env = os.environ.get("RB_NODE_CONFIG")
    return Path(env) if env else Path(_home(DEFAULT_RB + "/node.json"))


def load_config(path: Optional[Path] = None) -> NodeConfig:
    p = Path(path) if path is not None else config_path()
    if not p.is_file():
        raise FileNotFoundError("node config not found: %s" % p)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError("node config is not valid JSON: %s (%s)" % (p, exc))
    if not isinstance(data, dict):
        raise ValueError("node config must be a JSON object: %s" % p)
    known = {f.name for f in fields(NodeConfig)}
    return NodeConfig(**{k: v for k, v in data.items() if k in known})
