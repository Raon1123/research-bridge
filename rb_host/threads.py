"""Hub-side views of stored conversations and of the sync status file.

No network and no writes. This module imports none of `mcp`, `rb_host.server`, `rb_host.board`
or `rb_host.sync`, so that the hub page can use it without loading the MCP server.
"""
from __future__ import annotations

import calendar
import json
import time
from pathlib import Path
from typing import Any, Optional

from .store import _within, valid_msg_id

STALE_AFTER_S = 900  # three default timer intervals


def stored_dir(cfg: Any, rec: dict) -> Optional[Path]:
    """inbox/<node>/<id> (inbound) or outbox/<node>/<id>; None unless the record names a
    configured node and a safe id and the directory exists."""
    node, mid = rec.get("node"), rec.get("id")
    if not isinstance(node, str) or node not in cfg.nodes:
        return None
    if not isinstance(mid, str) or not valid_msg_id(mid):
        return None
    sub = "inbox" if rec.get("direction") == "in" else "outbox"
    root = Path(cfg.data_root) / sub / node
    d = root / mid
    if not _within(d, root) or not d.is_dir():
        return None
    return d


def body_path(cfg: Any, rec: dict) -> Optional[Path]:
    d = stored_dir(cfg, rec)
    if d is None:
        return None
    p = d / "body.txt"
    return p if p.is_file() else None


def status_path(cfg: Any, node: str) -> Path:
    cfg.alias(node)
    return Path(cfg.data_root) / "sync" / ("%s.json" % node)


def read_status(cfg: Any, node: str) -> Optional[dict]:
    """The sync status file as a dict; None when it is missing or unparseable. Never raises."""
    try:
        data = json.loads(status_path(cfg, node).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _age_s(ts: Any) -> Optional[float]:
    try:
        return max(0.0, time.time() - calendar.timegm(time.strptime(str(ts), "%Y-%m-%dT%H:%M:%SZ")))
    except ValueError:
        return None


def _undelivered(cfg: Any, node: str) -> int:
    from .jobs import ledger_for
    return sum(1 for r in ledger_for(cfg)._latest().values()
               if r.get("kind") == "message" and r.get("direction") == "in"
               and r.get("node") == node and r.get("delivered") is False)


def summary(cfg: Any, node: str) -> dict:
    """The `nodes` tool's view of one node (design 6.8). `stale` depends on `last_ok_at` only."""
    st = read_status(cfg, node)
    keys = ("ok", "error", "stage", "last_attempt_at", "last_ok_at", "node_seen_at",
            "node_version", "protocol", "withheld_extra")
    out = {"synced": st is not None}  # type: dict
    for k in keys:
        out[k] = st.get(k) if st else None
    age = _age_s(out["last_ok_at"]) if st else None
    out["age_s"] = None if age is None else round(age)
    out["stale"] = age is None or age > STALE_AFTER_S
    out["undelivered"] = _undelivered(cfg, node)
    return out
