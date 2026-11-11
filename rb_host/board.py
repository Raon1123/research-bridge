"""Unified board: a hub-side cache of node sources and of local copies of laptop files (docs/design/2026-11-02-unified-board.md).

Node data comes only through the bridge tools (read_doc, fetch_file, queue_status, gpu_status) and is
re-checked and reduced on the hub before it is cached. `load` never opens a connection and
never writes a source file. No MCP tool is added.
"""
from __future__ import annotations

import calendar
import hashlib
import json
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from rb_node.withheld import Withheld

from . import server
from .config import HostConfig
from .jobs import clean, ledger_for, now

NODE_SOURCES = ("queue", "gpu", "state", "events", "kanban")
CADENCE_S = {"queue": 600, "gpu": 600, "state": 3600, "events": 1800, "kanban": 3600}
# Laptop defaults; host.json "board" overrides them. Node paths have no default: they are
# set per node in host.json nodes.<node>.board and must lie under a read root of node.json.
DEFAULT_PORTFOLIO = ("D:/raw/vault-primary/90_Claude/10_Analysis/11_research-program/"
                     "80_portfolio/portfolio.json")
DEFAULT_PRIORITIES = "D:/raw/priorities/live.json"
EVENT_FIELDS = ("ts", "stage", "kind", "track", "id")
KANBAN_GROUP = ("column", "lane", "status", "stage")
OPEN_TASK = ("todo", "doing", "blocked")
MAX_EVENTS = 50
MAX_VALUE = 200


def board_dir(cfg: HostConfig) -> Path:
    return Path(cfg.data_root) / "board"


def _cache_path(cfg: HostConfig, source: str) -> Path:
    return board_dir(cfg) / (source.replace(":", "_") + ".json")


def _withheld(cfg: HostConfig) -> Withheld:
    return Withheld.load(Path(cfg.withheld_patterns_file))


def _withheld_from(patterns: List[str]) -> Withheld:
    return Withheld(patterns)


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + ".part")
    part.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(str(part), str(path))


def _audit(cfg: HostConfig, source: str, payload: bytes, result: str) -> None:
    """One line per source: no payload, only its size and hash."""
    rec = {"ts": now(), "source": source, "bytes": len(payload),
           "sha256": hashlib.sha256(payload).hexdigest(), "result": result}
    p = board_dir(cfg) / "audit.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(str(p), "ab") as fh:
        fh.write((json.dumps(rec) + "\n").encode("utf-8"))


# -- reducers (hub re-check + keep only listed fields) ------------------------------
def _clean(v: Any, wh: Withheld) -> Optional[Any]:
    """A scalar value that may be cached, or None if it must be dropped."""
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        if wh._hit(v):
            return None
        return v[:MAX_VALUE]
    return None


def reduce_state(text: str, wh: Withheld) -> List[dict]:
    """`key: value` lines of the leading --- frontmatter, after masking. No YAML parser."""
    masked, _n = wh.mask_text(text)
    lines = masked.split("\n")
    out = {}  # type: Dict[str, Any]
    if lines and lines[0].strip() == "---":
        for line in lines[1:]:
            if line.strip() == "---":
                break
            if ":" not in line or line.startswith((" ", "\t", "-")):
                continue
            k, v = line.split(":", 1)
            k, v = k.strip(), _clean(v.strip().strip("'\""), wh)
            if k and v is not None and _clean(k, wh) is not None:
                out[k] = v
    return [out]


def _records(text: str) -> List[Any]:
    try:
        data = json.loads(text)
    except ValueError:
        recs = []
        for line in text.splitlines():
            try:
                recs.append(json.loads(line))
            except ValueError:
                continue
        return recs
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        inner = data.get("events")
        return inner if isinstance(inner, list) else [data]
    return []


def reduce_events(text: str, wh: Withheld) -> List[dict]:
    """Newest first. Keeps EVENT_FIELDS only; a record with any withheld kept value is dropped."""
    out = []
    for rec in reversed(_records(text)):
        if not isinstance(rec, dict):
            continue
        kept = {}
        drop = False
        for f in EVENT_FIELDS:
            if f not in rec:
                continue
            v = _clean(rec[f], wh)
            if v is None and rec[f] is not None:
                drop = True
                break
            kept[f] = v
        if kept and not drop:
            out.append(kept)
        if len(out) >= MAX_EVENTS:
            break
    return out


def reduce_kanban(text: str, wh: Withheld) -> List[dict]:
    """Card counts per column. Titles and other free text are not kept."""
    data = json.loads(text)
    cards = data if isinstance(data, list) else None
    if isinstance(data, dict):
        for key in ("cards", "items", "tasks"):
            if isinstance(data.get(key), list):
                cards = data[key]
                break
    if cards is None:
        raise ValueError("no card list")
    counts = Counter()  # type: Counter
    for c in cards:
        if not isinstance(c, dict):
            continue
        group = next((c[g] for g in KANBAN_GROUP if isinstance(c.get(g), str)), "?")
        if _clean(group, wh) is not None:
            counts[group[:MAX_VALUE]] += 1
    return [{"column": k, "count": n} for k, n in sorted(counts.items())]


def reduce_queue(res: dict, wh: Withheld) -> List[dict]:
    counts = Counter(e.get("state") for e in res.get("entries", []) if isinstance(e, dict))
    return [{"state": s, "count": n} for s, n in sorted(counts.items()) if isinstance(s, str)]


def reduce_gpu(res: dict) -> List[dict]:
    keys = ("index", "name", "memory_used", "memory_total", "utilization")
    return [{k: g.get(k) for k in keys} for g in res.get("gpus", []) if isinstance(g, dict)]


# -- refresh ----------------------------------------------------------------------------
def _node_paths(cfg: HostConfig, node: str) -> Dict[str, str]:
    entry = cfg.nodes.get(node, {})
    paths = entry.get("board") if isinstance(entry, dict) else None
    return paths if isinstance(paths, dict) else {}


def _fetch(cfg: HostConfig, node: str, name: str, wh: Withheld) -> Dict[str, Any]:
    """Returns {"items": [...]} or {"error": code}, plus "payload" bytes for the audit line."""
    if name in ("queue", "gpu"):
        res = (server.queue_status if name == "queue" else server.gpu_status)(node)
        payload = json.dumps(res, sort_keys=True).encode("utf-8")
        if not isinstance(res, dict):
            return {"error": "bad_response", "payload": payload}
        if name == "queue":
            if "error" in res:
                return {"error": str(res["error"]), "payload": payload}
            return {"items": reduce_queue(res, wh), "payload": payload}
        items = reduce_gpu(res)
        if res.get("error"):
            return {"error": str(res["error"]), "items": items, "payload": payload}
        return {"items": items, "payload": payload}
    path = _node_paths(cfg, node).get(name)
    if not isinstance(path, str) or not path:
        return {"error": "no_path", "payload": b""}
    if name == "state":
        res = server.read_doc(node, path)
        if "error" in res:
            return {"error": str(res["error"]), "payload": b""}
        text = str(res.get("text", ""))
        return {"items": reduce_state(text, wh), "payload": text.encode("utf-8")}
    res = server.fetch_file(node, path)
    if "error" in res:
        return {"error": str(res["error"]), "payload": b""}
    fetched = Path(res["path"])
    data = fetched.read_bytes()
    fetched.unlink()  # only the reduced fields stay on the hub (design §4)
    text = data.decode("utf-8", "replace")
    try:
        items = reduce_events(text, wh) if name == "events" else reduce_kanban(text, wh)
    except ValueError:
        return {"error": "unparseable", "payload": data}
    return {"items": items, "payload": data}


def refresh(cfg: HostConfig, node: Optional[str] = None,
            sources: Optional[List[str]] = None) -> List[dict]:
    """Fetch node sources and write one cache file each. A failed source is recorded, not raised."""
    wh = _withheld(cfg)
    names = [node] if node else sorted(cfg.nodes)
    out = []
    for n in names:
        cfg.alias(n)
        for name in NODE_SOURCES:
            if sources and name not in sources:
                continue
            sid = "%s:%s" % (n, name)
            try:
                got = _fetch(cfg, n, name, wh)
            except Exception as exc:  # one source must not stop the others
                got = {"error": type(exc).__name__, "payload": b""}
            err = got.get("error")
            stamp = now()
            if err is None:
                rec = {"source": sid, "fetched_at": stamp, "attempted_at": stamp, "ok": True,
                       "error": None, "cadence_s": CADENCE_S[name],
                       "items": got.get("items", [])}
            else:  # keep the last good items; they show as stale because fetched_at stays old
                prev = _node_source(cfg, sid, name)
                items = prev.get("items", [])
                rec = {"source": sid, "fetched_at": prev.get("fetched_at"),
                       "attempted_at": stamp, "ok": False, "error": err,
                       "cadence_s": CADENCE_S[name], "items": items if isinstance(items, list) else []}
            _write_json(_cache_path(cfg, sid), rec)
            _audit(cfg, sid, got.get("payload", b""), "ok" if err is None else str(err))
            out.append({"source": sid, "ok": err is None, "error": err})
    return out


# -- load (no connection, no write) -------------------------------------------------------
def _age_s(ts: Any) -> Optional[float]:
    try:
        return time.time() - calendar.timegm(time.strptime(str(ts), "%Y-%m-%dT%H:%M:%SZ"))
    except ValueError:
        return None


def _node_source(cfg: HostConfig, sid: str, name: str) -> dict:
    p = _cache_path(cfg, sid)
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rec = {"source": sid, "fetched_at": None, "ok": False, "error": "never_fetched",
               "cadence_s": CADENCE_S[name], "items": []}
    age = _age_s(rec.get("fetched_at"))
    rec["stale"] = age is None or age > rec.get("cadence_s", CADENCE_S[name])
    return rec


def _local(source: str, ok: bool, error: Optional[str], items: List[dict], **extra: Any) -> dict:
    rec = {"source": source, "fetched_at": now(), "ok": ok, "error": error, "cadence_s": 0,
           "stale": False, "items": items}
    rec.update(extra)
    return rec


def _read_json(path: str) -> Any:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(path)
    return json.loads(p.read_bytes().decode("utf-8-sig"))


def _ledger_source(cfg: HostConfig, waiting: List[dict]) -> dict:
    latest = list(ledger_for(cfg)._latest().values())
    answered = {r.get("reply_to") for r in latest
                if r.get("kind") == "message" and r.get("direction") == "out"}
    jobs_by = Counter()  # type: Counter
    msgs = Counter()  # type: Counter
    def c(v: Any) -> str:  # SEC-03: ledger text is shown stripped of control and bidi characters
        return clean(v, 80)

    for r in latest:
        if r.get("kind") == "job":
            jobs_by[c(r.get("status"))] += 1
            if r.get("status") == "pending_approval":
                what = ("approve %s job on %s (%s, %s GPU-h) at /rb/pending"
                        % (c(r.get("op", "submit")), c(r.get("node")),
                           c(r.get("config_name") or r.get("target_job_id")), c(r.get("gpu_hours"))))
                waiting.append({"source": "rb:ledger", "ref": c(r.get("id")), "what": what,
                                "order": 0})
        elif r.get("kind") == "message":
            kind = "event" if r.get("msg_kind") == "event" else c(r.get("direction"))
            msgs[kind] += 1
            if (r.get("direction") == "in" and r.get("msg_kind") != "event"
                    and r.get("id") not in answered):
                waiting.append({"source": "rb:ledger", "ref": c(r.get("id")),
                                "what": "unanswered %s from %s" % (c(r.get("msg_kind", "message")),
                                                                    c(r.get("node"))),
                                "order": 1})
    items = [{"kind": "job", "status": s, "count": n} for s, n in sorted(jobs_by.items())]
    items += [{"kind": "message", "direction": d, "count": n} for d, n in sorted(msgs.items())]
    return _local("rb:ledger", True, None, items)


def _portfolio_source(path: str, waiting: List[dict]) -> dict:
    try:
        data = _read_json(path)
        cols = Counter(p.get("column") for p in data.get("papers", []))
        order = [c for c in data.get("columns", [])] + sorted(
            c for c in cols if c not in data.get("columns", []) and isinstance(c, str))
        items = [{"column": c, "count": cols[c]} for c in order if cols.get(c)]
        for p in data.get("papers", []):  # one line per paper; the kanban has the task list
            n = sum(1 for t in p.get("tasks", [])
                    if t.get("user_action") is True and t.get("status") in OPEN_TASK)
            if n:
                waiting.append({"source": "vault:portfolio", "ref": p.get("paper_id"),
                                "what": "%s: %d open user tasks on /portfolio"
                                        % (p.get("short", p.get("paper_id")), n),
                                "order": 3})
    except FileNotFoundError:
        return _local("vault:portfolio", False, "missing", [])
    except (ValueError, AttributeError, TypeError):
        return _local("vault:portfolio", False, "unparseable", [])
    return _local("vault:portfolio", True, None, items)


def _priorities_source(path: str, waiting: List[dict]) -> dict:
    try:
        data = _read_json(path)
        by_key = {i.get("key"): i for i in data.get("items", []) if isinstance(i, dict)}
        tiers = data.get("ranking", {}).get("tiers", [])
        items = [{"tier": t.get("tier"), "count": len(t.get("keys", []))} for t in tiers]
        for t in tiers:
            if t.get("tier") != "now":
                continue
            for k in t.get("keys", []):
                it = by_key.get(k, {})
                if it.get("actor") == "user" and it.get("status", "open") == "open":
                    waiting.append({"source": "vault:priorities", "ref": k,
                                    "what": str(it.get("title", k)), "order": 2})
        refreshed = data.get("meta", {}).get("refreshed")
    except FileNotFoundError:
        return _local("vault:priorities", False, "missing", [])
    except (ValueError, AttributeError, TypeError):
        return _local("vault:priorities", False, "unparseable", [])
    return _local("vault:priorities", True, None, items, refreshed=refreshed)


def load(cfg: HostConfig) -> dict:
    """The whole board: waiting-on-user items first, then every source with its age."""
    waiting = []  # type: List[dict]
    sources = [_ledger_source(cfg, waiting)]
    for n in sorted(cfg.nodes):
        for name in NODE_SOURCES:
            sources.append(_node_source(cfg, "%s:%s" % (n, name), name))
    portfolio = cfg.board.get("portfolio") or (DEFAULT_PORTFOLIO if os.name == "nt" else None)
    priorities = cfg.board.get("priorities") or (DEFAULT_PRIORITIES if os.name == "nt" else None)
    if portfolio is not None:
        sources.append(_portfolio_source(portfolio, waiting))
    if priorities is not None:
        sources.append(_priorities_source(priorities, waiting))
    waiting.sort(key=lambda w: w["order"])
    for w in waiting:
        del w["order"]
    return {"generated": now(), "waiting": waiting, "sources": sources}


def _item_text(it: dict) -> str:
    return ", ".join("%s=%s" % (k, v) for k, v in it.items())


def render_text(b: dict) -> str:
    lines = ["Waiting on you (%d)" % len(b["waiting"])]
    lines += ["  [%s] %s  %s" % (w["source"], w["ref"], w["what"]) for w in b["waiting"]]
    lines.append("")
    for s in b["sources"]:
        state = "ok" if s["ok"] else "ERROR %s" % s["error"]
        stale = "  STALE" if s.get("stale") else ""
        lines.append("%s  %s  fetched %s%s" % (s["source"], state, s.get("fetched_at"), stale))
        lines += ["    " + _item_text(it) for it in s.get("items", [])[:10]]
    return "\n".join(lines) + "\n"
