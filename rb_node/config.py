"""Node configuration (JSON). Roots come from here only, never from the host."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_RB = "~/.research-bridge"


def _home(p: str) -> str:
    return os.path.expanduser(p)


def default_trm() -> str:
    return _home("~/project/trm")


PATH_KEYS = ("trm_root", "queue_dir", "withheld_source", "claude_bin", "mailbox_root",
             "audit_path", "approval_path", "harness_root")
PATH_LIST_KEYS = ("read_roots", "write_roots")


def _rb(sub: str) -> str:
    return _home(DEFAULT_RB + sub)


@dataclass
class NodeConfig:
    # Path defaults are computed when the object is built, so HOME at that moment decides them.
    trm_root: str = field(default_factory=default_trm)
    read_roots: List[str] = field(default_factory=lambda: [
        "lab/registry/", "lab/experiments/", "lab/reports/", "reports/figures/",
        _rb("/mailbox/out/")])
    write_roots: List[str] = field(default_factory=lambda: [
        _rb("/mailbox/in/"), default_trm() + "/scripts/queue/jobs"])
    queue_dir: str = field(default_factory=lambda: default_trm() + "/scripts/queue")
    withheld_source: Optional[str] = field(
        default_factory=lambda: _rb("/withheld-patterns.json"))
    claude_bin: str = field(default_factory=lambda: _home("~/.local/bin/claude"))
    job_template: List[str] = field(default_factory=list)  # argv with {config}, {config_dir} or {config_stem}
    # GPU indices a bridge job may run on (the node owner's GPUs). Empty -> job_submit refused
    # (no_allowed_gpus) and run-job launches nothing. Set from the node console only.
    allowed_gpus: List[int] = field(default_factory=list)
    max_file: int = 50 * 1024 * 1024
    mailbox_root: str = field(default_factory=lambda: _rb("/mailbox"))
    audit_path: str = field(default_factory=lambda: _rb("/audit.jsonl"))
    # job approval verifier, set only from the node console (rb-node approve-key set); keep it
    # outside read_roots and write_roots. Missing -> job_submit / job_cancel refused.
    approval_path: str = field(default_factory=lambda: _rb("/approve.json"))
    # Where read_doc looks up EXP-nnn and H-nnn by id (relative to trm_root; must lie in read_roots).
    experiments_dir: str = "lab/experiments"
    hypotheses_path: str = "lab/registry/HYPOTHESES.md"
    harness_root: str = ""  # node's ~/.claude; empty -> harness push/pull refused (no_harness_root)


def default_dependents(root: str) -> Dict[str, Any]:
    """Defaults that follow the research tree root."""
    return {"queue_dir": root + "/scripts/queue",
            "queue_jobs": root + "/scripts/queue/jobs",
            "old_withheld": root + "/lab/11_governance/11_lab-root/WITHHELD_RUNS.yaml"}


def expand_paths(data: dict) -> dict:
    """Expand a leading ~ in every path key and every path-list entry."""
    out = dict(data)
    for k in PATH_KEYS:
        v = out.get(k)
        if isinstance(v, str) and v.startswith("~"):
            out[k] = os.path.expanduser(v)
    for k in PATH_LIST_KEYS:
        v = out.get(k)
        if isinstance(v, list):
            out[k] = [os.path.expanduser(e) if isinstance(e, str) and e.startswith("~") else e
                      for e in v]
    return out


def _type_ok(name: str, value: Any, default: Any) -> bool:
    if name == "withheld_source":
        return value is None or isinstance(value, str)
    if name == "allowed_gpus":
        return isinstance(value, list) and all(
            isinstance(e, int) and not isinstance(e, bool) and e >= 0 for e in value)
    if isinstance(default, list):
        return isinstance(value, list) and all(isinstance(e, str) for e in value)
    if isinstance(default, int):
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, str)


def coerce(data: dict) -> Tuple[Dict[str, Any], List[str]]:
    """(known keys whose value has the right type, names of known keys with the wrong type).

    The one type rule for node.json: load_config drops the wrong-typed values (the key keeps its
    default) and rb-node doctor names them. Unknown keys are left out of both."""
    default = NodeConfig()
    kept = {}  # type: Dict[str, Any]
    wrong = []  # type: List[str]
    for f in fields(NodeConfig):
        if f.name not in data:
            continue
        if _type_ok(f.name, data[f.name], getattr(default, f.name)):
            kept[f.name] = data[f.name]
        else:
            wrong.append(f.name)
    return kept, wrong


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
    kept, _wrong = coerce(data)
    return NodeConfig(**expand_paths(kept))
