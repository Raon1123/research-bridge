"""Hub store of the sessions that run on the nodes (docs/design/2026-11-11-node-sessions.md §8).

`<data_root>/sessions/<node>.json` is written only by `rb sync` (`record`, `record_failure`),
atomically. The answer of the node operation `sessions` is untrusted data: every field is
type-checked, times are parsed, ids matched, labels checked and re-checked against the hub's
withheld patterns; an entry that fails is skipped and counted.

Standard library, `rb_node.withheld` and `.util` only: `share` imports this module, and must
not load a client, server, jobs or board module.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from rb_node.withheld import Withheld

from .util import STAMP, parse_utc

SCHEMA = 1
DAYS = 8  # the window asked of the node on every pass
NODE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
ID_RE = re.compile(r"^[0-9a-f-]{8,64}$")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LABEL_MAX = 120
# File counts of the answer kept in the store. `ignored`, `deeper` and `shallower` came later
# (an answer of an older node lacks them).
COUNTS = ("outside", "unparsed", "ignored", "files", "deeper", "shallower")


class BadAnswer(ValueError):
    """The answer is not an object with a `sessions` list."""


def store_path(cfg: Any, node: str) -> Path:
    if not isinstance(node, str) or not NODE_NAME.match(node):
        raise ValueError("bad node name")
    return Path(cfg.data_root) / "sessions" / ("%s.json" % node)


def _time(v: Any) -> Optional[str]:
    if not isinstance(v, str) or len(v) > 40:
        return None
    d = parse_utc(v)
    return d.strftime(STAMP) if d is not None else None


def _day(v: Any) -> bool:
    if not isinstance(v, str) or not DAY_RE.match(v):
        return False
    try:
        date.fromisoformat(v)
    except ValueError:
        return False
    return True


def _count(v: Any) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


def label_ok(v: Any, wh: Withheld) -> Optional[str]:
    """The label when it is a plain relative-directory label as the node sends it: a string of
    1 to 120 characters with no control, format or separator character and no withheld
    pattern hit; None otherwise (the entry is dropped). HTML-special characters are legal in a
    directory name and are kept: the page escapes every string."""
    if not isinstance(v, str) or not 0 < len(v) <= LABEL_MAX:
        return None
    for ch in v:
        cat = unicodedata.category(ch)
        if cat[0] == "C" or cat in ("Zl", "Zp"):
            return None
    if wh.name_hit(v):
        return None
    return v


def _entry(e: Any, wh: Withheld) -> Optional[Tuple[str, dict]]:
    if not isinstance(e, dict):
        return None
    sid = e.get("id")
    if not isinstance(sid, str) or not ID_RE.match(sid):
        return None
    label = label_ok(e.get("label"), wh)
    start, end = _time(e.get("start")), _time(e.get("end"))
    days = e.get("days")
    if label is None or start is None or end is None or start > end or not isinstance(days, dict):
        return None
    clean = {}  # type: Dict[str, int]
    for d, s in days.items():
        if not _day(d) or not isinstance(s, int) or isinstance(s, bool) or not 0 <= s <= 86400:
            return None
        clean[d] = s
    return sid, {"label": label, "start": start, "end": end, "days": clean}


def merge_entry(old: dict, new: dict) -> dict:
    """The merge rule of design §8: the new label, the earlier start, the later end, and per
    day the larger number of active seconds."""
    days = dict(old.get("days", {}))
    for d, s in new["days"].items():
        days[d] = max(days.get(d, 0), s)
    return {"label": new["label"], "start": min(old["start"], new["start"]),
            "end": max(old["end"], new["end"]), "days": dict(sorted(days.items()))}


def validate(ans: Any, wh: Withheld) -> Tuple[dict, int]:
    """(checked answer, skipped entries). Raises BadAnswer for an answer of the wrong shape."""
    if not isinstance(ans, dict) or not isinstance(ans.get("sessions"), list):
        raise BadAnswer("bad sessions answer")
    sessions = {}  # type: Dict[str, dict]
    skipped = 0
    for e in ans["sessions"]:
        got = _entry(e, wh)
        if got is None:
            skipped += 1
            continue
        sid, rec = got
        sessions[sid] = merge_entry(sessions[sid], rec) if sid in sessions else rec
    out = {"tree": label_ok(ans.get("tree"), wh), "truncated": ans.get("truncated") is True,
           "sessions": sessions}
    for k in COUNTS:  # a node without a field gives 0
        out[k] = _count(ans.get(k))
    return out, skipped


def load(cfg: Any, node: str) -> Tuple[Optional[dict], Optional[str]]:
    """(store, error): (None, None) when there is none, (None, "unreadable"|"unparseable") when
    it cannot be used. Never raises for a bad file."""
    try:
        data = json.loads(store_path(cfg, node).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, None
    except OSError:
        return None, "unreadable"
    except (ValueError, RecursionError):
        return None, "unparseable"
    if not isinstance(data, dict) or not isinstance(data.get("sessions"), dict):
        return None, "unparseable"
    return data, None


def write_store(cfg: Any, node: str, data: dict) -> None:
    path = store_path(cfg, node)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".sessions-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, ensure_ascii=False, indent=1))
        os.chmod(tmp, 0o600)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _old_sessions(store: Optional[dict], wh: Withheld) -> Dict[str, dict]:
    """Stored entries that still pass the checks (a pattern added later drops its hits)."""
    out = {}  # type: Dict[str, dict]
    for sid, rec in (store or {}).get("sessions", {}).items():
        got = _entry(dict(rec, id=sid), wh) if isinstance(rec, dict) else None
        if got is not None:
            out[got[0]] = got[1]
    return out


def record(cfg: Any, node: str, ans: Any, wh: Withheld, now: str) -> int:
    """Check the answer, merge it into the store and write it. Returns the skipped count.
    A store that cannot be read is replaced (the node's window refills it)."""
    checked, skipped = validate(ans, wh)
    store, _err = load(cfg, node)
    sessions = _old_sessions(store, wh)
    for sid, rec in checked["sessions"].items():
        sessions[sid] = merge_entry(sessions[sid], rec) if sid in sessions else rec
    data = {"schema": SCHEMA, "node": node, "fetched_at": now, "attempted_at": now, "ok": True,
            "error": None, "tree": checked["tree"]}
    data.update((k, checked[k]) for k in COUNTS)
    data.update(truncated=checked["truncated"], skipped=skipped,
                sessions=dict(sorted(sessions.items())))
    write_store(cfg, node, data)
    return skipped


def record_failure(cfg: Any, node: str, code: str, now: str) -> None:
    """A failed or refused fetch on a node that has a store: keep `sessions` and `fetched_at`,
    set `ok`, `error` and `attempted_at`. Without a store nothing is written (the sync status
    file holds the code)."""
    store, _err = load(cfg, node)
    if store is None:
        return
    store.update(ok=False, error=code, attempted_at=now)
    write_store(cfg, node, store)
