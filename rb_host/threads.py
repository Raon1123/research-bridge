"""Hub-side views of stored conversations and of the sync status file.

No network and no writes. This module imports none of `mcp`, `rb_host.server`, `rb_host.board`
or `rb_host.sync`, so that the hub page can use it without loading the MCP server.
"""
from __future__ import annotations

import calendar
import json
import os
import re
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rb_node.withheld import Withheld

from .jobs import clean, ledger_for
from .store import _within, valid_msg_id

STALE_AFTER_S = 900  # three default timer intervals
MAX_BODY = 20000
_NODE_ID = re.compile(r"^(\d{20})-")
_KEEP = "\n\t"


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
    return p if p.is_file() and _within(p, d) else None


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
            "node_version", "protocol", "withheld_extra", "hub_withheld_extra",
            "hub_withheld_rejected")
    out = {"synced": st is not None}  # type: dict
    for k in keys:
        out[k] = st.get(k) if st else None
    age = _age_s(out["last_ok_at"]) if st else None
    out["age_s"] = None if age is None else round(age)
    out["stale"] = age is None or age > STALE_AFTER_S
    out["undelivered"] = _undelivered(cfg, node)
    return out


# -- text -------------------------------------------------------------------------------
def _clean_chars(text: str) -> str:
    out = []
    for ch in text:
        if ch in _KEEP:
            out.append(ch)
            continue
        cat = unicodedata.category(ch)
        if cat[0] == "C" or cat in ("Zl", "Zp"):
            continue  # control, format (bidirectional overrides) and line separators
        out.append(ch)
    return "".join(out)


def clean_block(text: str, limit: int) -> str:
    """Like `jobs.clean` but keeps newlines and tabs. Appends a marker when the text is cut."""
    out = _clean_chars("" if text is None else str(text))
    return out[:limit] + "\n[truncated]" if len(out) > limit else out


def node_time(rec: dict) -> str:
    """UTC time of a record (design 6.7 rule 4): the node's out-item id carries `time_ns`
    zero-padded; otherwise the hub's `created`."""
    rid = rec.get("id")
    if rec.get("direction") == "in" and isinstance(rid, str):
        m = _NODE_ID.match(rid)
        if m:
            try:
                return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(m.group(1)) // 10 ** 9))
            except (ValueError, OverflowError, OSError):
                pass
    created = rec.get("created")
    return created if isinstance(created, str) else ""


def read_body(cfg: Any, rec: dict, wh: Withheld, limit: int = MAX_BODY) -> dict:
    """The stored body, masked again with `wh`, cleaned and cut. {"text", "missing", "truncated"}."""
    p = body_path(cfg, rec)
    text = None  # type: Optional[str]
    if p is not None:
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, ValueError):
            text = None
    if text is None:
        return {"text": "", "missing": True, "truncated": False}
    cleaned = wh.mask_text(_clean_chars(text))[0]
    return {"text": clean_block(cleaned, limit), "missing": False, "truncated": len(cleaned) > limit}


def attachments(cfg: Any, rec: dict, wh: Withheld) -> dict:
    """Attachment facts from provenance.json. Quarantined files appear as a reason code only."""
    out = {"files": [], "quarantined": []}  # type: Dict[str, List[dict]]
    d = stored_dir(cfg, rec)
    if d is None:
        return out
    pf = d / "provenance.json"
    try:
        if not pf.is_file() or not _within(pf, d):
            return out
        prov = json.loads(pf.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    entries = prov.get("files", prov.get("attachments")) if isinstance(prov, dict) else None
    for e in entries if isinstance(entries, list) else []:
        if not isinstance(e, dict):
            continue
        if e.get("status") == "quarantined":
            out["quarantined"].append({"reason": clean(e.get("reason"), 60)})
            continue
        name = str(e.get("name", ""))
        out["files"].append({
            "name": "(withheld)" if wh.name_hit(_clean_chars(name)) else clean(name, 200),
            "bytes": e.get("bytes"), "sha256": clean(e.get("sha256"), 64),
            "status": clean(e.get("status", "ok"), 40)})
    return out


# -- thread building ----------------------------------------------------------------------
_CACHE = {}  # type: Dict[str, Tuple[Tuple[int, int], dict]]
_CACHE_LOCK = threading.Lock()


def _event_json(cfg: Any, rec: dict) -> Optional[dict]:
    p = body_path(cfg, rec)
    if p is None:
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _sort_key(rec: dict) -> Tuple[str, str]:
    return (node_time(rec), str(rec.get("id")))


def _ordered(recs: List[dict], order: Dict[str, int]) -> List[dict]:
    """Records by time (design 6.7 rule 4), ties broken by ledger order, not by id: a reply that
    arrives in the same second as its message must not sort before it. A record whose reply_to
    names a record of this thread never sorts before that record, even when the node clock is
    behind the hub clock: its sort time is raised to the time of the record it answers."""
    by_id = {r["id"]: r for r in recs}
    memo = {}  # type: Dict[str, Tuple[str, int]]

    def eff(r: dict, seen: frozenset = frozenset()) -> Tuple[str, int]:
        """(sort time, depth below the root of the reply chain)."""
        if r["id"] in memo:
            return memo[r["id"]]
        t, depth = node_time(r), 0
        rt = r.get("reply_to")
        if isinstance(rt, str) and rt in by_id and rt != r["id"] and rt not in seen:
            pt, pd = eff(by_id[rt], seen | {r["id"]})
            t, depth = max(t, pt), pd + 1
        memo[r["id"]] = (t, depth)
        return t, depth
    return sorted(recs, key=lambda r: eff(r) + (order.get(r["id"], 0),))


def _root(recs: List[dict]) -> dict:
    """The thread's root: the first record whose reply_to is outside the thread. Clock skew can
    sort a reply before its message; the thread keeps the message's id."""
    ids = {r["id"] for r in recs}
    for r in recs:
        rt = r.get("reply_to")
        if not (isinstance(rt, str) and rt in ids and rt != r["id"]):
            return r
    return recs[0]


def _build(cfg: Any, latest: List[dict], mtime: Optional[int]) -> dict:
    msgs = [r for r in latest if r.get("kind") == "message" and isinstance(r.get("id"), str)]
    job_recs = [r for r in latest if r.get("kind") == "job"]
    job_ids = {j.get("id") for j in job_recs}
    jobs_out = {j.get("id"): dict(j, events=[]) for j in job_recs}
    orphans = []  # type: List[dict]
    by_node = {}  # type: Dict[str, List[dict]]
    vertices = []  # type: List[dict]
    for r in msgs:
        if r.get("msg_kind") == "event":
            info = _event_json(cfg, r) if r.get("direction") == "in" else None
            if info is not None and info.get("event") == "job_finished" \
                    and isinstance(info.get("job_id"), str):
                if info["job_id"] in job_ids:
                    jobs_out[info["job_id"]]["events"].append(r)
                else:
                    orphans.append(r)
                continue
            if not (isinstance(r.get("reply_to"), str) and r.get("reply_to")):
                by_node.setdefault(str(r.get("node")), []).append(r)
                continue
        vertices.append(r)
    ids = {r["id"] for r in vertices}
    parent = {i: i for i in ids}  # type: Dict[str, str]

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for r in vertices:
        rt = r.get("reply_to")
        if isinstance(rt, str) and rt in ids and rt != r["id"]:
            parent[find(r["id"])] = find(rt)
    groups = {}  # type: Dict[str, List[dict]]
    for r in vertices:
        groups.setdefault(find(r["id"]), []).append(r)
    order = {r["id"]: i for i, r in enumerate(latest) if isinstance(r.get("id"), str)}
    thread_list = []
    by_msg = {}  # type: Dict[str, str]
    for recs in groups.values():
        recs = _ordered(recs, order)
        root = _root(recs)
        tid = root["id"]
        for r in recs:
            by_msg[r["id"]] = tid
        non_event = [r for r in recs if r.get("msg_kind") != "event"]
        if any(r.get("direction") == "out" and r.get("status") == "pending_send" for r in recs):
            state = "delivery pending"
        elif non_event and non_event[-1].get("direction") == "in":
            state = "open"
        else:
            state = "answered"
        thread_list.append({
            "id": tid, "node": root.get("node"), "records": recs, "state": state,
            "last_at": max(node_time(r) for r in recs),
            "undelivered": sum(1 for r in recs if r.get("direction") == "in"
                               and r.get("delivered") is False),
            "reply_to_unknown": [r["id"] for r in recs
                                 if isinstance(r.get("reply_to"), str) and r.get("reply_to")
                                 and r["reply_to"] not in ids]})
    thread_list.sort(key=lambda t: (t["last_at"], t["id"]), reverse=True)
    for j in jobs_out.values():
        j["events"].sort(key=_sort_key)
    orphans.sort(key=_sort_key)
    for lst in by_node.values():
        lst.sort(key=_sort_key)
    return {"threads": thread_list, "jobs": list(jobs_out.values()), "orphan_events": orphans,
            "events_by_node": by_node, "by_msg": by_msg, "ledger_mtime_ns": mtime}


def load(cfg: Any) -> dict:
    """Threads, jobs and loose events from the ledger (design 6.7). Cached while the ledger's
    size and modification time are unchanged. No writes."""
    led = ledger_for(cfg)
    try:
        st = os.stat(str(led.path))
        sig = (st.st_size, st.st_mtime_ns)  # type: Optional[Tuple[int, int]]
    except OSError:
        sig = None
    key = str(led.path)
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit is not None and sig is not None and hit[0] == sig:
            return hit[1]
        out = _build(cfg, list(led._latest().values()), sig[1] if sig else None)
        if sig is not None:
            _CACHE[key] = (sig, out)
        else:
            _CACHE.pop(key, None)
        return out
