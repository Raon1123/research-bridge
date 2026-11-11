"""Status snapshot of the hub page route /status (docs/design/2026-11-11-hub-status-page.md).

`snapshot` reads local files only (the board cache, the ledger, stored event bodies, and the
session and run files named in host.json `share.*`), reduces them to counts and labels, and
writes nothing. It opens no connection. The formats of the session and run files are assumed
(docs/design/2026-11-06-shared-status-page.md §8). Stdlib plus rb_node.withheld only at module
level: no client, server, jobs, threads or board import, so that importing this module loads
neither `mcp` nor a node client (`threads` is imported inside `snapshot`).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from rb_node.withheld import Withheld

from .config import HostConfig
from .util import age_s, now, parse_utc

SCHEMA_VERSION = 2
NODE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
ERROR_CODE = re.compile(r"^[a-z_]{1,40}$")
SHARED_FILES = ("index.html", "snapshot.json")
LOCAL_CADENCE_S = 3600
NODE_SOURCES = ("queue", "gpu", "events")
STAGE = re.compile(r"^S[0-8]$")
FAILED = ("failed", "error", "crashed")
QUEUE_KEYS = {"jobs": "queued", "queued": "queued", "pending": "queued", "processing": "running",
              "running": "running", "done": "done", "finished": "done", "failed": "failed",
              "error": "failed"}  # node state names: rb_node/remote.py QUEUE_STATES
QUEUE_COUNTS = ("queued", "running", "done", "failed", "other")
LANES = ("laptop", "hub", "server")
LABEL_MAX = 60
ACTIVITY_KEYS = ("submits", "cancels", "approved", "finished", "failed", "sent", "received")
_WS = "\n\r\t"


def share_dir(cfg: HostConfig) -> Path:
    return Path(cfg.data_root) / "share"


def owner_dir(cfg: HostConfig) -> Path:
    return share_dir(cfg) / "owner"


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _in_period(d: date, start: date, end: date) -> bool:
    return start <= d <= end


def _clean(v: Any, limit: int) -> str:
    """The rule of `jobs.clean` (this module does not import `jobs`): whitespace controls become
    a space; other control, format (bidirectional) and line-separator characters are removed."""
    out = []
    for ch in "" if v is None else str(v):
        cat = unicodedata.category(ch)
        if ch in _WS:
            out.append(" ")
        elif cat[0] == "C" or cat in ("Zl", "Zp"):
            continue
        else:
            out.append(ch)
    return "".join(out)[:limit]


# -- label rule -----------------------------------------------------------------------
def _label(v: Any, wh: Withheld, labels: Optional[Set[str]]) -> Tuple[Optional[str], bool]:
    """(label, hit). A string with a withheld hit gives (None, True); the caller drops the item.
    With an allowlist, a label outside it is "other"; without one, the cleaned label is kept,
    cut at LABEL_MAX characters (design 2026-11-11 §8)."""
    if not isinstance(v, str):
        return "other", False
    s = _clean(v, 100000).strip()
    if wh.name_hit(v) or wh.name_hit(s):
        return None, True
    if labels is not None and v not in labels:
        return "other", False
    return (s[:LABEL_MAX] or "other"), False


def _error_code(e: Any, wh: Withheld) -> Tuple[Optional[str], bool]:
    """(code, hit) for a source error: None stays None; a non-string is "unavailable"; anything
    outside ERROR_CODE is "bad_error_code"; a withheld hit is "withheld" (hit True)."""
    if e is None:
        return None, False
    if not isinstance(e, str):
        return "unavailable", False
    if not ERROR_CODE.match(e):
        return "bad_error_code", False
    if wh.name_hit(e):
        return "withheld", True
    return e, False


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
                    labels: Optional[Set[str]],
                    lanes: Tuple[str, ...] = LANES) -> Tuple[list, dict, int]:
    """(per_day, totals, dropped). Routines are counted in totals only, with no active hours.
    A lane in `lanes` (laptop, hub, server and the configured node names) is kept, any other
    is "other"."""
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
        lane = lane_raw if isinstance(lane_raw, str) and lane_raw in lanes else "other"
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
    """Counts per kind of state; a state name not in QUEUE_KEYS adds to `other`."""
    out = dict.fromkeys(QUEUE_COUNTS, 0)
    for it in items:
        if not isinstance(it, dict) or not isinstance(it.get("state"), str):
            continue
        key = QUEUE_KEYS.get(it["state"].lower(), "other")
        n = it.get("count")
        if isinstance(n, int) and not isinstance(n, bool) and n >= 0:
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
        d = parse_utc(ev.get("ts"))
        if d is None:
            continue
        age = time.time() - d.timestamp()  # not floored here: the most recent of future stamps wins
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
    except FileNotFoundError:
        return {"fetched_at": None, "ok": False, "error": "never_fetched", "cadence_s": 600,
                "items": []}
    except OSError:
        return {"fetched_at": None, "ok": False, "error": "unreadable", "cadence_s": 600,
                "items": []}
    except (ValueError, RecursionError):
        return {"fetched_at": None, "ok": False, "error": "unparseable", "cadence_s": 600,
                "items": []}
    if not isinstance(rec, dict):
        return {"fetched_at": None, "ok": False, "error": "unparseable", "cadence_s": 600,
                "items": []}
    return rec


def reduce_jobs(job_recs: list, start: date, end: date) -> Tuple[int, float]:
    """(pending_approvals, gpu_hours requested in the period) from job records."""
    pending, hours = 0, 0.0
    for r in job_recs:
        if not isinstance(r, dict) or r.get("kind") != "job":
            continue
        if r.get("status") == "pending_approval":
            pending += 1
        c = parse_utc(r.get("created"))
        g = r.get("gpu_hours")
        if (c is not None and _in_period(c.date(), start, end)
                and isinstance(g, (int, float)) and not isinstance(g, bool)):
            hours += g
    return pending, round(hours, 2)


def _day(ts: Any) -> Optional[str]:
    d = parse_utc(ts)
    return d.date().isoformat() if d is not None else None


def reduce_activity(job_recs: list, messages: List[Tuple[str, str]],
                    finished: List[Tuple[str, bool]], start: date, end: date) -> list:
    """One row per day of the period, newest first (design 2026-11-11 §8).

    `job_recs`: job records; `messages`: (time, direction) of message records that are not
    events; `finished`: (time, failed) of job_finished events. Times are ISO strings."""
    rows = {}  # type: Dict[str, Dict[str, Any]]
    d = end
    while d >= start:
        rows[d.isoformat()] = dict({"date": d.isoformat()}, **dict.fromkeys(ACTIVITY_KEYS, 0))
        d -= timedelta(days=1)

    def add(ts: Any, key: str) -> None:
        day = _day(ts)
        if day in rows:
            rows[day][key] += 1
    for r in job_recs:
        if not isinstance(r, dict) or r.get("kind") != "job":
            continue
        if r.get("op") in ("submit", "cancel"):
            add(r.get("created"), "submits" if r["op"] == "submit" else "cancels")
        add(r.get("approved_at"), "approved")
    for ts, direction in messages:
        if direction in ("out", "in"):
            add(ts, "sent" if direction == "out" else "received")
    for ts, failed in finished:
        add(ts, "finished")
        if failed:
            add(ts, "failed")
    return list(rows.values())


def _ledger_part(cfg: HostConfig, wh: Withheld, start: date,
                 end: date) -> Tuple[int, float, list]:
    """(pending_approvals, gpu_hours_period, activity) from the ledger and stored event bodies,
    read through `threads.load` (one cached ledger pass, shared with the other pages)."""
    from . import threads  # lazy: threads imports jobs, which imports the node client
    data = threads.load(cfg)
    job_recs = data["jobs"]
    pending, hours = reduce_jobs(job_recs, start, end)
    messages = [(threads.node_time(r), str(r.get("direction")))
                for t in data["threads"] for r in t["records"] if r.get("msg_kind") != "event"]
    finished = []  # type: List[Tuple[str, bool]]
    events = [ev for j in job_recs for ev in j.get("events", [])] + list(data["orphan_events"])
    for ev in events:
        when = threads.node_time(ev)
        day = _day(when)
        if day is None or not start.isoformat() <= day <= end.isoformat():
            continue  # bodies are read only for events in the period
        try:  # the masked reader of the /jobs page: a blanked line gives no status
            info = json.loads(threads.read_body(cfg, ev, wh, limit=4000)["text"])
        except ValueError:
            info = None
        status = info.get("status") if isinstance(info, dict) else None
        finished.append((when, isinstance(status, str)
                         and _clean(status, 40).strip().lower() in FAILED))
    return pending, hours, reduce_activity(job_recs, messages, finished, start, end)


# -- snapshot ---------------------------------------------------------------------------
def _calendar_status(sp: Any) -> Tuple[Any, Optional[str], Optional[str]]:
    """(cost_usd, fetched_at, error) from the file at share.calendar_status."""
    if not isinstance(sp, str) or not sp:
        return None, None, "not_configured"
    if not Path(sp).is_file():
        return None, None, "missing"
    try:
        st = json.loads(Path(sp).read_bytes().decode("utf-8-sig"))
    except OSError:
        return None, None, "unreadable"
    except (ValueError, RecursionError):
        return None, None, "unparseable"
    if not isinstance(st, dict):
        return None, None, "unparseable"
    gen = parse_utc(st.get("generated"))
    c = st.get("cost_usd")
    cost = c if isinstance(c, (int, float)) and not isinstance(c, bool) else None
    return cost, _iso(gen) if gen else None, None


def snapshot(cfg: HostConfig, days: int = 7, today: Optional[date] = None) -> dict:
    """The status snapshot of design 2026-11-11 §8 for the period [today - days, today] (UTC).

    Reads only and writes nothing. A missing, unreadable or malformed source never raises: its
    row in `sources` carries an error code and its part of the snapshot stays empty."""
    if days < 0:
        raise ValueError("days must be >= 0")
    end = today if today is not None else datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    wh = Withheld.load(Path(cfg.withheld_patterns_file))
    conf = cfg.share if isinstance(cfg.share, dict) else {}
    raw_labels = conf.get("labels")
    labels = ({x for x in raw_labels if isinstance(x, str)}
              if isinstance(raw_labels, list) else None)  # type: Optional[Set[str]]
    dropped = 0
    sources = []  # type: List[dict]

    def source(sid: str, fetched_at: Optional[str], ok: bool, error: Any,
               cadence_s: Optional[int]) -> None:
        nonlocal dropped
        code, hit = _error_code(None if ok else (error or "unavailable"), wh)
        dropped += 1 if hit else 0
        sources.append(_source(sid, fetched_at, ok, code, cadence_s))

    nodes = []  # type: List[str]
    for node in sorted(cfg.nodes):
        if isinstance(node, str) and NODE_NAME.match(node) and not wh.name_hit(node):
            nodes.append(node)
        else:
            dropped += 1

    per_day, totals = [], {"sessions": 0, "routines": 0, "active_h": 0.0}  # type: list, dict
    recs, err, fetched = _read_list(conf.get("calendar_sessions"), "sessions")
    if recs is not None:
        try:
            per_day, totals, n = reduce_sessions(recs, start, end, wh, labels,
                                                 LANES + tuple(nodes))
            dropped += n
        except Exception:
            recs, err = None, "unparseable"
    source("calendar:sessions", fetched, err is None, err, LOCAL_CADENCE_S)

    cost, cal_fetched, cal_err = _calendar_status(conf.get("calendar_status"))
    source("calendar:status", cal_fetched, cal_err is None, cal_err, LOCAL_CADENCE_S)
    totals["cost_usd"] = cost

    runs_per_day = []  # type: list
    recs, err, fetched = _read_list(conf.get("runs"), "runs")
    if recs is not None:
        try:
            runs_per_day, n = reduce_runs(recs, start, end, wh, labels)
            dropped += n
        except Exception:
            err = "unparseable"
    source("runs", fetched, err is None, err, LOCAL_CADENCE_S)

    queue = dict.fromkeys(QUEUE_COUNTS, 0)
    in_use, total, tracks = 0, 0, []  # type: int, int, list
    for node in nodes:
        for name in NODE_SOURCES:
            sid = "%s:%s" % (node, name)
            rec = _node_cache(cfg, sid)
            ok = rec.get("ok") is True
            cad = rec.get("cadence_s")
            fa = parse_utc(rec.get("fetched_at"))
            items = rec.get("items") if ok and isinstance(rec.get("items"), list) else []
            try:
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
            except Exception:
                ok, rec = False, dict(rec, error="unparseable")
            source(sid, _iso(fa) if fa else None, ok, rec.get("error"),
                   cad if isinstance(cad, int) and not isinstance(cad, bool) else 600)

    try:
        pending, gpu_hours, activity = _ledger_part(cfg, wh, start, end)
        source("rb:ledger", now(), True, None, None)
    except Exception:
        pending, gpu_hours, activity = 0, 0.0, []
        source("rb:ledger", None, False, "unreadable", None)
    source("withheld:patterns", None, wh.source_error is None, wh.source_error, None)
    queue["pending_approvals"] = pending

    return {
        "schema_version": SCHEMA_VERSION, "built_at": now(),
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "sources": sources,
        "sessions": {"per_day": per_day, "totals": totals},
        "experiments": {"queue": queue,
                        "gpu": {"in_use": in_use, "total": total, "gpu_hours_period": gpu_hours},
                        "runs_per_day": runs_per_day, "tracks": tracks},
        "activity": activity,
        "dropped": dropped,
    }


# -- build (the 2026-11-06 page; removed in the next change) -------------------------------
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

    snap = snapshot(cfg, days, today)
    snap["tier"] = tier
    del snap["activity"]
    wh = Withheld.load(Path(cfg.withheld_patterns_file))
    dropped = snap["dropped"]
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
    else:
        del snap["sessions"]["totals"]["cost_usd"]
    snap["dropped"] = dropped

    body = json.dumps(snap, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8")
    out = share_dir(cfg) if tier == "shared" else owner_dir(cfg)
    html_path, json_path = out / SHARED_FILES[0], out / SHARED_FILES[1]
    page = share_serve.render_html(snap).encode("utf-8")  # render first: a failure keeps both files
    _write_atomic(json_path, body)
    _write_atomic(html_path, page)
    counts = {"sessions.per_day": len(snap["sessions"]["per_day"]),
              "experiments.runs_per_day": len(snap["experiments"]["runs_per_day"]),
              "experiments.tracks": len(snap["experiments"]["tracks"])}
    if tier == "owner":
        counts["waiting"] = len(snap["waiting"])
    rec = {"ts": now(), "tier": tier, "sources": [s["id"] for s in snap["sources"]],
           "items": counts, "dropped": dropped, "sha256": hashlib.sha256(body).hexdigest()}
    audit = share_dir(cfg) / "audit.jsonl"
    audit.parent.mkdir(parents=True, exist_ok=True)
    with open(str(audit), "ab") as fh:
        fh.write((json.dumps(rec) + "\n").encode("utf-8"))
    return {"snapshot": snap, "paths": [html_path, json_path], "dropped": dropped}
