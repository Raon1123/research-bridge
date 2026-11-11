"""Shared status page snapshot builder (docs/design/2026-11-06-shared-status-page.md).

Reads local caches only (session-calendar and run-view JSON, the board cache, the ledger), reduces
them to counts and allowlisted labels, and writes snapshot.json and index.html. It opens no
connection and writes to no source. Input formats of the calendar and run files are assumed; see
the task brief. Stdlib plus rb_node.withheld only (no client, server, jobs or board import at
module level).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from rb_node.withheld import Withheld

from .config import HostConfig
from .ledger import Ledger
from .util import age_s, now, parse_utc

SCHEMA_VERSION = 1
NODE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
ERROR_CODE = re.compile(r"^[a-z_]{1,40}$")
SHARED_FILES = ("index.html", "snapshot.json")
LOCAL_CADENCE_S = 3600
NODE_SOURCES = ("queue", "gpu", "events")
STAGE = re.compile(r"^S[0-8]$")
FAILED = ("failed", "error", "crashed")
QUEUE_KEYS = {"queued": "queued", "pending": "queued", "running": "running", "done": "done",
              "finished": "done", "failed": "failed", "error": "failed"}


def share_dir(cfg: HostConfig) -> Path:
    return Path(cfg.data_root) / "share"


def owner_dir(cfg: HostConfig) -> Path:
    return share_dir(cfg) / "owner"


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _in_period(d: date, start: date, end: date) -> bool:
    return start <= d <= end


# -- label rule -----------------------------------------------------------------------
def _label(v: Any, wh: Withheld, labels: Optional[Set[str]]) -> Tuple[Optional[str], bool]:
    """(label, hit). A string with a withheld hit gives (None, True); the caller drops the item."""
    if not isinstance(v, str):
        return "other", False
    if wh._hit(v):
        return None, True
    return (v if labels is not None and v in labels else "other"), False


# -- source reading (read only) ---------------------------------------------------------
def _read_list(path: Any, key: str) -> Tuple[Optional[list], Optional[str], Optional[str]]:
    """(records, error, fetched_at). Missing -> 'missing'; bad JSON or wrong type -> 'unparseable'."""
    if not isinstance(path, str) or not path:
        return None, "not_configured", None
    p = Path(path)
    if not p.is_file():
        return None, "missing", None
    try:
        data = json.loads(p.read_bytes().decode("utf-8-sig"))
        fetched = _iso(datetime.fromtimestamp(p.stat().st_mtime, timezone.utc))
    except OSError:
        return None, "unreadable", None
    except (ValueError, RecursionError):
        return None, "unparseable", None
    if isinstance(data, dict) and isinstance(data.get(key), list):
        data = data[key]
    if not isinstance(data, list):
        return None, "unparseable", None
    return data, None, fetched


def _source(sid: str, fetched_at: Optional[str], ok: bool, error: Optional[str],
            cadence_s: Optional[int]) -> dict:
    age = age_s(fetched_at)
    stale = False if cadence_s is None else (age is None or age > cadence_s)
    return {"id": sid, "fetched_at": fetched_at, "ok": ok, "error": error, "stale": stale}


# -- reducers ---------------------------------------------------------------------------
def reduce_sessions(recs: list, start: date, end: date, wh: Withheld,
                    labels: Optional[Set[str]]) -> Tuple[list, dict, int]:
    """(per_day, totals, dropped). Routines are counted in totals only, with no active hours."""
    acc = {}  # type: Dict[Tuple[str, str, str], List[float]]
    routines = 0
    dropped = 0
    for r in recs:
        if not isinstance(r, dict):
            continue
        s = parse_utc(r.get("start"))
        if s is None or not _in_period(s.date(), start, end):
            continue
        proj, hit = _label(r.get("project"), wh, labels)
        if hit:
            dropped += 1
            continue
        if r.get("kind", "session") == "routine":
            routines += 1
            continue
        lane_raw = r.get("machine", r.get("lane"))
        lane = "laptop" if lane_raw == "laptop" else "server"
        hours = 0.0
        e = parse_utc(r.get("end"))
        if e is not None:
            h = (e - s).total_seconds() / 3600.0
            if 0 <= h <= 24:
                hours = h
        cell = acc.setdefault((s.date().isoformat(), lane, proj or "other"), [0, 0.0])
        cell[0] += 1
        cell[1] += hours
    per_day = [{"date": d, "lane": ln, "project": p, "count": int(c), "active_h": round(h, 2)}
               for (d, ln, p), (c, h) in sorted(acc.items())]
    totals = {"sessions": sum(x["count"] for x in per_day), "routines": routines,
              "active_h": round(sum(x["active_h"] for x in per_day), 2)}
    return per_day, totals, dropped


def reduce_runs(recs: list, start: date, end: date, wh: Withheld,
                labels: Optional[Set[str]]) -> Tuple[list, int]:
    acc = {}  # type: Dict[Tuple[str, str], List[int]]
    dropped = 0
    for r in recs:
        if not isinstance(r, dict):
            continue
        proj, hit = _label(r.get("project"), wh, labels)
        if hit:
            dropped += 1
            continue
        status = r.get("status")
        if isinstance(status, str) and wh._hit(status):
            dropped += 1
            continue
        failed = isinstance(status, str) and status.lower() in FAILED
        s = parse_utc(r.get("started"))
        e = parse_utc(r.get("ended"))
        if s is not None and _in_period(s.date(), start, end):
            cell = acc.setdefault((s.date().isoformat(), proj or "other"), [0, 0, 0])
            cell[0] += 1
            if failed and e is None:  # crashed before writing `ended`: failed on its start date
                cell[2] += 1
        if e is not None and _in_period(e.date(), start, end):
            cell = acc.setdefault((e.date().isoformat(), proj or "other"), [0, 0, 0])
            cell[2 if failed else 1] += 1
    return ([{"date": d, "project": p, "started": c[0], "finished": c[1], "failed": c[2]}
             for (d, p), c in sorted(acc.items())], dropped)


def reduce_queue(items: list) -> dict:
    out = {"queued": 0, "running": 0, "done": 0, "failed": 0}
    for it in items:
        if not isinstance(it, dict) or not isinstance(it.get("state"), str):
            continue
        key = QUEUE_KEYS.get(it["state"].lower())
        n = it.get("count")
        if key and isinstance(n, int) and not isinstance(n, bool) and n >= 0:
            out[key] += n
    return out


def reduce_gpu(items: list) -> Tuple[int, int]:
    """(in_use, total)."""
    gpus = [g for g in items if isinstance(g, dict)]

    def pos(v: Any) -> bool:
        return isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0

    return sum(1 for g in gpus if pos(g.get("utilization")) or pos(g.get("memory_used"))), len(gpus)


def reduce_tracks(items: list, wh: Withheld, labels: Optional[Set[str]]) -> Tuple[list, int]:
    """Newest event (by parsed ts, any input order) per track. Bad stage or withheld text drops the track."""
    newest = {}  # type: Dict[str, Tuple[float, dict]]
    for ev in items:
        if not isinstance(ev, dict) or not isinstance(ev.get("track"), str):
            continue
        age = age_s(ev.get("ts"))
        if age is None:
            continue
        raw = ev["track"]
        if raw not in newest or age < newest[raw][0]:
            newest[raw] = (age, ev)
    seen = {}  # type: Dict[str, float]
    stages = {}  # type: Dict[str, str]
    dropped = 0
    for raw in sorted(newest):
        age, ev = newest[raw]
        track, hit = _label(raw, wh, labels)
        stage = ev.get("stage")
        if hit or not isinstance(stage, str) or wh._hit(stage) or not STAGE.match(stage):
            dropped += 1
            continue
        age = max(0.0, age)
        track = track or "other"
        if track not in seen or age < seen[track]:
            seen[track], stages[track] = age, stage
    return ([{"track": t, "stage": stages[t], "last_event_age_s": int(seen[t])}
             for t in sorted(seen)], dropped)


def _node_cache(cfg: HostConfig, sid: str) -> dict:
    p = Path(cfg.data_root) / "board" / (sid.replace(":", "_") + ".json")
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except OSError:
        return {"fetched_at": None, "ok": False, "error": "never_fetched", "cadence_s": 600,
                "items": []}
    except (ValueError, RecursionError):
        return {"fetched_at": None, "ok": False, "error": "unparseable", "cadence_s": 600,
                "items": []}
    if not isinstance(rec, dict):
        return {"fetched_at": None, "ok": False, "error": "unparseable", "cadence_s": 600,
                "items": []}
    return rec


def _ledger(cfg: HostConfig, start: date, end: date) -> Tuple[int, float]:
    """(pending_approvals, gpu_hours_in_period) from job records."""
    pending, hours = 0, 0.0
    for r in Ledger(Path(cfg.data_root) / "ledger.jsonl")._latest().values():
        if r.get("kind") != "job":
            continue
        if r.get("status") == "pending_approval":
            pending += 1
        c = parse_utc(r.get("created"))
        g = r.get("gpu_hours")
        if (c is not None and _in_period(c.date(), start, end)
                and isinstance(g, (int, float)) and not isinstance(g, bool)):
            hours += g
    return pending, round(hours, 2)


# -- build ------------------------------------------------------------------------------
def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + ".part")
    part.write_bytes(data)
    os.replace(str(part), str(path))


def build(cfg: HostConfig, days: int = 7, tier: str = "shared",
          today: Optional[date] = None) -> dict:
    """Write snapshot.json and index.html for the tier. Returns {"snapshot","paths","dropped"}."""
    if tier not in ("shared", "owner"):
        raise ValueError("tier must be shared or owner")
    from . import share_serve  # lazy: rendering lives in its own module

    end = today if today is not None else datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    wh = Withheld.load(Path(cfg.withheld_patterns_file))
    conf = cfg.share if isinstance(cfg.share, dict) else {}
    raw_labels = conf.get("labels")
    labels = ({x for x in raw_labels if isinstance(x, str)}
              if isinstance(raw_labels, list) else None)  # type: Optional[Set[str]]
    dropped = 0
    sources = []  # type: List[dict]

    recs, err, fetched = _read_list(conf.get("calendar_sessions"), "sessions")
    sources.append(_source("calendar:sessions", fetched, err is None, err, LOCAL_CADENCE_S))
    per_day, totals = [], {"sessions": 0, "routines": 0, "active_h": 0.0}  # type: list, dict
    if recs is not None:
        per_day, totals, n = reduce_sessions(recs, start, end, wh, labels)
        dropped += n

    cost = None  # type: Any
    cal_fetched, cal_err = None, "not_configured"  # type: Optional[str], Optional[str]
    sp = conf.get("calendar_status")
    if isinstance(sp, str) and sp:
        if not Path(sp).is_file():
            cal_err = "missing"
        else:
            try:
                st = json.loads(Path(sp).read_bytes().decode("utf-8-sig"))
                if not isinstance(st, dict):
                    raise ValueError
                cal_err = None
                gen = st.get("generated")
                cal_fetched = _iso(parse_utc(gen)) if parse_utc(gen) else None
                c = st.get("cost_usd")
                cost = c if isinstance(c, (int, float)) and not isinstance(c, bool) else None
            except OSError:
                cal_err = "unreadable"
            except (ValueError, RecursionError):
                cal_err = "unparseable"
    sources.append(_source("calendar:status", cal_fetched, cal_err is None, cal_err,
                           LOCAL_CADENCE_S))

    recs, err, fetched = _read_list(conf.get("runs"), "runs")
    sources.append(_source("runs", fetched, err is None, err, LOCAL_CADENCE_S))
    runs_per_day = []  # type: list
    if recs is not None:
        runs_per_day, n = reduce_runs(recs, start, end, wh, labels)
        dropped += n

    queue = {"queued": 0, "running": 0, "done": 0, "failed": 0}
    in_use, total, tracks = 0, 0, []  # type: int, int, list
    for node in sorted(cfg.nodes):
        if not isinstance(node, str) or not NODE_NAME.match(node) or wh._hit(node):
            dropped += 1
            continue
        for name in NODE_SOURCES:
            sid = "%s:%s" % (node, name)
            rec = _node_cache(cfg, sid)
            ok = rec.get("ok") is True
            e = rec.get("error") if not ok else None
            if not ok and not isinstance(e, str):
                e = "unavailable"
            if isinstance(e, str) and not ERROR_CODE.match(e):
                e = "bad_error_code"
            if isinstance(e, str) and wh._hit(e):
                e, dropped = "withheld", dropped + 1
            cad = rec.get("cadence_s")
            fa = parse_utc(rec.get("fetched_at"))
            sources.append(_source(sid, _iso(fa) if fa else None, ok, e,
                                   cad if isinstance(cad, int) and not isinstance(cad, bool)
                                   else 600))
            items = rec.get("items") if ok and isinstance(rec.get("items"), list) else []
            if name == "queue":
                for k, v in reduce_queue(items).items():
                    queue[k] += v
            elif name == "gpu":
                a, b = reduce_gpu(items)
                in_use, total = in_use + a, total + b
            else:
                t, n = reduce_tracks(items, wh, labels)
                tracks.extend(t)
                dropped += n

    try:
        pending, gpu_hours = _ledger(cfg, start, end)
        sources.append(_source("rb:ledger", now(), True, None, None))
    except (OSError, ValueError, TypeError, AttributeError):
        pending, gpu_hours = 0, 0.0
        sources.append(_source("rb:ledger", None, False, "unreadable", None))
    sources.append(_source("withheld:patterns", None, wh.source_error is None,
                           None if wh.source_error is None else str(wh.source_error), None))
    queue["pending_approvals"] = pending

    snap = {
        "schema_version": SCHEMA_VERSION, "tier": tier, "built_at": now(),
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "sources": sources,
        "sessions": {"per_day": per_day, "totals": totals},
        "experiments": {"queue": queue,
                        "gpu": {"in_use": in_use, "total": total, "gpu_hours_period": gpu_hours},
                        "runs_per_day": runs_per_day, "tracks": tracks},
    }  # type: Dict[str, Any]
    if tier == "owner":
        from . import board  # lazy: owner tier only
        waiting = []
        for w in board.load(cfg).get("waiting", []):
            if not isinstance(w, dict):
                continue
            what, ref = w.get("what"), w.get("ref")
            texts = [x for x in (what, ref, w.get("source")) if isinstance(x, str)]
            if any(wh._hit(x) for x in texts):
                dropped += 1
                continue
            waiting.append({"source": w.get("source"), "ref": ref, "what": what})
        snap["waiting"] = waiting
        snap["sessions"]["totals"]["cost_usd"] = cost
    snap["dropped"] = dropped

    body = json.dumps(snap, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
    out = share_dir(cfg) if tier == "shared" else owner_dir(cfg)
    html_path, json_path = out / SHARED_FILES[0], out / SHARED_FILES[1]
    page = share_serve.render_html(snap).encode("utf-8")  # render first: a failure keeps both files
    _write_atomic(json_path, body)
    _write_atomic(html_path, page)
    counts = {"sessions.per_day": len(per_day), "experiments.runs_per_day": len(runs_per_day),
              "experiments.tracks": len(tracks)}
    if tier == "owner":
        counts["waiting"] = len(snap["waiting"])
    rec = {"ts": now(), "tier": tier, "sources": [s["id"] for s in sources], "items": counts,
           "dropped": dropped, "sha256": hashlib.sha256(body).hexdigest()}
    audit = share_dir(cfg) / "audit.jsonl"
    audit.parent.mkdir(parents=True, exist_ok=True)
    with open(str(audit), "ab") as fh:
        fh.write((json.dumps(rec) + "\n").encode("utf-8"))
    return {"snapshot": snap, "paths": [html_path, json_path], "dropped": dropped}
