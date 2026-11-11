"""Claude session record files on the node, reduced to times and one label per session.

Design: docs/design/2026-11-11-node-sessions.md (§7 security, §8 data). Standard library only,
Python >= 3.8.

The record format is ASSUMED (design §8 "Assumed record format"; no real record was read while
building this): `<sessions_dir>/<project dir>/<session id>.jsonl`, one JSON object per line,
most lines with a top-level `timestamp` (ISO 8601, UTC) and `cwd` (absolute path). From a line
only those two top-level values are taken. Nothing else of a record is kept, cached, logged or
returned; files that give no usable time are counted in `unparsed`, so a wrong assumption shows.

What leaves the node per session: the file stem as id, start and end times, active seconds per
UTC day, and the working directory relative to `trm_root` (cleaned, cut, masked). Sessions whose
working directory is outside the tree are one number (`outside`).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .protocol import ProtocolError
from .withheld import Withheld

GAP_S = 300  # a gap between two record times up to this long counts as active
DAYS_DEFAULT = 8
DAYS_MAX = 31
# Per-call bounds (design §7 "Bounds"). Module constants so that tests can lower them.
MAX_FILES = 2000  # record files looked at
MAX_LISTED = 20000  # directory entries visited while listing
MAX_NEW_BYTES = 64 << 20  # bytes newly read
MAX_SECONDS = 20.0  # time spent reading
MAX_SESSIONS = 500  # sessions returned, most recently active first
LINE_MAX = 8 << 20  # a longer line is read through and skipped, never held or parsed
LABEL_MAX = 120
HEAD_N = 4096  # bytes hashed to notice a rewritten file
CACHE_NAME = "sessions-cache.json"
CACHE_SCHEMA = 1
ID_RE = re.compile(r"^[0-9a-f-]{8,64}$")
_TS = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?(Z|[+-]\d{2}:\d{2})$")


# -- small helpers ---------------------------------------------------------------------------
def parse_ts(v: Any) -> Optional[float]:
    """Seconds since the epoch for an ISO 8601 time with `Z` or an offset; None otherwise."""
    if not isinstance(v, str) or len(v) > 40:
        return None
    m = _TS.match(v)
    if m is None:
        return None
    try:
        t = datetime(*(int(x) for x in m.groups()[:6]), tzinfo=timezone.utc).timestamp()
    except (ValueError, OverflowError):
        return None
    tz = m.group(8)
    if tz != "Z":
        off = int(tz[1:3]) * 3600 + int(tz[4:6]) * 60
        t -= off if tz[0] == "+" else -off
    return t + (float(m.group(7)) if m.group(7) else 0.0)


def iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def day_of(t: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(t))


def clean(s: str, limit: int = LABEL_MAX) -> str:
    """Control, format and line or paragraph separator characters removed; cut at `limit`."""
    return "".join(ch for ch in s if not (unicodedata.category(ch)[0] == "C"
                                          or unicodedata.category(ch) in ("Zl", "Zp")))[:limit]


def shown(s: str, wh: Withheld) -> str:
    """A label as it may leave the node: cleaned and cut, `(withheld)` on a pattern hit."""
    c = clean(s)
    if wh.name_hit(s) or wh.name_hit(c):
        return "(withheld)"
    return c or "(unnamed)"


def _inside(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False


def label_for(cwd: Any, roots: List[str]) -> Optional[str]:
    """The working directory relative to the tree (`.` for its root), or None when it is not
    an absolute path inside one of `roots`. The value is treated as a string, never looked up."""
    if not isinstance(cwd, str) or not cwd or "\x00" in cwd or not os.path.isabs(cwd):
        return None
    c = os.path.normpath(cwd)
    for r in roots:
        if _inside(c, r):
            rel = os.path.relpath(c, r)
            return "." if rel == "." else rel.replace(os.sep, "/")
    return None


def tree_roots(trm_root: str) -> List[str]:
    out = []  # type: List[str]
    for r in (os.path.normpath(trm_root), os.path.realpath(trm_root)):
        if r not in out:
            out.append(r)
    return out


# -- cache -----------------------------------------------------------------------------------
def cache_path(cfg: Any) -> Path:
    """`sessions-cache.json` in the node data directory (the parent of the mailbox, where
    install.json also lives; beside node.json with the default layout)."""
    return Path(cfg.mailbox_root).parent / CACHE_NAME


def _fingerprint(base: str, roots: List[str]) -> str:
    return hashlib.sha256("\x00".join([base] + roots).encode("utf-8", "replace")).hexdigest()


def _key(rel: str) -> str:
    """Cache key of a record file: a hash of its path below sessions_dir (no path text kept)."""
    return hashlib.sha256(rel.encode("utf-8", "surrogateescape")).hexdigest()[:32]


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _ent_ok(e: Any) -> bool:
    if not isinstance(e, dict):
        return False
    for k in ("size", "mtime_ns", "offset", "head_n", "n"):
        if not isinstance(e.get(k), int) or isinstance(e.get(k), bool) or e[k] < 0:
            return False
    for k in ("start", "end", "last"):
        if e.get(k) is not None and not _num(e.get(k)):
            return False
    days = e.get("days")
    return (isinstance(e.get("head"), str) and isinstance(e.get("cwd"), bool)
            and isinstance(e.get("tail"), bool)
            and (e.get("label") is None or isinstance(e.get("label"), str))
            and isinstance(days, dict)
            and all(isinstance(d, str) and _num(s) for d, s in days.items()))


def _load_cache(path: Path, fp: str) -> Dict[str, dict]:
    """Entries of a usable cache; {} when it is missing, unparseable, of another schema or of
    another sessions_dir or tree. A malformed entry is dropped (its file is read again)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return {}
    if (not isinstance(data, dict) or data.get("schema") != CACHE_SCHEMA
            or data.get("fingerprint") != fp or not isinstance(data.get("files"), dict)):
        return {}
    return {k: e for k, e in data["files"].items() if isinstance(k, str) and _ent_ok(e)}


def _write_cache(path: Path, fp: str, files: Dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".sessions-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"schema": CACHE_SCHEMA, "fingerprint": fp, "files": files}, fh)
        os.chmod(tmp, 0o600)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# -- reading ---------------------------------------------------------------------------------
class _Budget:
    def __init__(self) -> None:
        self.bytes = MAX_NEW_BYTES
        self.deadline = time.monotonic() + MAX_SECONDS

    def left(self) -> bool:
        return self.bytes > 0 and time.monotonic() < self.deadline


def _fresh() -> dict:
    return {"size": 0, "mtime_ns": 0, "offset": 0, "head": "", "head_n": 0, "n": 0,
            "start": None, "end": None, "last": None, "days": {}, "cwd": False, "label": None,
            "tail": False}


def _head(fh: Any, n: int) -> str:
    fh.seek(0)
    return hashlib.sha256(fh.read(n)).hexdigest()


def _take(ent: dict, line: bytes, roots: List[str]) -> None:
    """Fold one record line into the entry: its top-level `timestamp` and, until one is found,
    its top-level `cwd`. Nothing else of the line is looked at."""
    try:
        obj = json.loads(line)
    except (ValueError, RecursionError):
        return
    if not isinstance(obj, dict):
        return
    if not ent["cwd"]:
        cwd = obj.get("cwd")
        if isinstance(cwd, str) and cwd:
            ent["cwd"] = True
            ent["label"] = label_for(cwd, roots)
    t = parse_ts(obj.get("timestamp"))
    if t is None:
        return
    last = ent["last"]
    if last is not None and 0 <= t - last <= GAP_S:  # attributed to the day of the earlier time
        d = day_of(last)
        ent["days"][d] = ent["days"].get(d, 0) + (t - last)
    ent["last"] = t
    ent["start"] = t if ent["start"] is None else min(ent["start"], t)
    ent["end"] = t if ent["end"] is None else max(ent["end"], t)
    ent["n"] += 1


def _read(fh: Any, ent: dict, budget: _Budget, roots: List[str]) -> None:
    """Read complete lines from ent["offset"] while the budget lasts. The offset only moves past
    newline-terminated lines; a half-written last line is left for the next call (`tail`)."""
    fh.seek(ent["offset"])
    ent["tail"] = False
    while budget.left():
        line = fh.readline(LINE_MAX + 1)
        if not line:
            return
        budget.bytes -= len(line)
        if line.endswith(b"\n"):
            ent["offset"] += len(line)
            _take(ent, line, roots)
            continue
        if len(line) <= LINE_MAX:  # end of file inside a line
            ent["tail"] = True
            return
        size = len(line)  # longer than LINE_MAX: read through to its newline, keep nothing
        del line
        while True:
            more = fh.readline(1 << 20)
            if not more:
                ent["tail"] = True
                return
            size += len(more)
            budget.bytes -= len(more)
            if more.endswith(b"\n"):
                break
        ent["offset"] += size


def _list(base: str) -> Tuple[List[tuple], bool]:
    """Regular `.jsonl` files at depth 2 under `base` (resolved), whose resolved path stays
    inside it: (rel, real path, stem, size, mtime, mtime_ns). True when MAX_LISTED was hit."""
    out = []  # type: List[tuple]
    seen = 0
    for top in sorted(os.scandir(base), key=lambda e: e.name):
        seen += 1
        if seen > MAX_LISTED:
            return out, True
        real_dir = os.path.realpath(top.path)
        if not _inside(real_dir, base) or real_dir == base or not os.path.isdir(real_dir):
            continue
        try:
            entries = sorted(os.scandir(real_dir), key=lambda e: e.name)
        except OSError:
            continue
        for f in entries:
            seen += 1
            if seen > MAX_LISTED:
                return out, True
            if not f.name.endswith(".jsonl"):
                continue
            real = os.path.realpath(f.path)
            if not _inside(real, base):
                continue
            try:
                st = os.stat(real)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            out.append((top.name + "/" + f.name, real, f.name[:-len(".jsonl")], st.st_size,
                        st.st_mtime, st.st_mtime_ns))
    return out, False


def _update(ent: Optional[dict], real: str, size: int, mtime_ns: int, budget: _Budget,
            roots: List[str]) -> Tuple[dict, bool]:
    """(entry, complete). An unchanged file is not opened. A grown file with the same first
    bytes is read from its offset; a shrunk or rewritten one from the start."""
    if ent is not None and ent["size"] == size and ent["mtime_ns"] == mtime_ns and (
            ent["offset"] >= size or ent["tail"]):
        return ent, True
    if not budget.left():
        return (ent if ent is not None else _fresh()), False
    with open(real, "rb") as fh:
        # grown, or unchanged but not read to the end in an earlier call (budget)
        keep = (ent is not None and ent["offset"] <= size and ent["head_n"] > 0
                and (size > ent["size"] or (size == ent["size"] and mtime_ns == ent["mtime_ns"]))
                and _head(fh, ent["head_n"]) == ent["head"])
        new = dict(ent, days=dict(ent["days"])) if keep and ent is not None else _fresh()
        _read(fh, new, budget, roots)
        new["head_n"] = min(size, HEAD_N)
        new["head"] = _head(fh, new["head_n"])
    new["size"], new["mtime_ns"] = size, mtime_ns
    return new, new["offset"] >= size or new["tail"]


def _merge(a: dict, b: dict) -> dict:
    """Two records of one session id (the hub's merge rule): earlier start, later end, larger
    seconds per day; the label of the more recently active one."""
    newer, older = (a, b) if a["end"] >= b["end"] else (b, a)
    days = dict(older["days"])
    for d, s in newer["days"].items():
        days[d] = max(days.get(d, 0), s)
    return {"label": newer["label"], "start": min(a["start"], b["start"]),
            "end": max(a["end"], b["end"]), "days": days}


def collect(sessions_dir: str, trm_root: str, cache_file: Optional[Path], wh: Withheld,
            days: int = DAYS_DEFAULT, now: Optional[float] = None,
            write_cache: bool = True) -> dict:
    """The answer of the `sessions` operation (design §8 "Operation result").

    Raises ProtocolError("not_configured") when `sessions_dir` is empty and
    ProtocolError("not_found") when it is not a directory. The cache is written only when
    `write_cache` is true and something changed."""
    if not sessions_dir:
        raise ProtocolError("not_configured", "sessions_dir is not set in node.json")
    base = os.path.realpath(os.path.expanduser(sessions_dir))
    if not os.path.isdir(base):
        raise ProtocolError("not_found", "sessions directory not found")
    now = time.time() if now is None else now
    cutoff = now - days * 86400
    first_day = day_of(cutoff)
    roots = tree_roots(trm_root)
    fp = _fingerprint(base, roots)
    old = _load_cache(cache_file, fp) if cache_file is not None else {}
    listed, truncated = _list(base)
    files = {}  # type: Dict[str, dict]
    if truncated:
        files.update(old)  # not every file was seen: keep entries of the unseen ones
    for rel, _real, _stem, _size, _mtime, _ns in listed:
        k = _key(rel)
        if k in old:
            files[k] = old[k]
    window = sorted((x for x in listed if x[4] >= cutoff), key=lambda x: (-x[4], x[0]))
    if len(window) > MAX_FILES:
        window, truncated = window[:MAX_FILES], True
    budget = _Budget()
    unparsed = outside = 0
    by_id = {}  # type: Dict[str, dict]
    for rel, real, stem, size, _mtime, ns in window:
        if not ID_RE.match(stem):
            unparsed += 1  # a .jsonl file that cannot be a session record: counted, not read
            continue
        k = _key(rel)
        try:
            ent, complete = _update(files.get(k), real, size, ns, budget, roots)
        except OSError:
            unparsed += 1
            continue
        files[k] = ent
        if not complete:
            truncated = True
        if ent["n"] == 0:
            if complete:
                unparsed += 1
            continue
        if ent["end"] < cutoff:
            continue
        if ent["label"] is None:
            outside += 1
            continue
        rec = {"label": ent["label"], "start": ent["start"], "end": ent["end"],
               "days": {d: s for d, s in ent["days"].items() if d >= first_day}}
        by_id[stem] = _merge(by_id[stem], rec) if stem in by_id else rec
    ordered = sorted(by_id.items(), key=lambda kv: (-kv[1]["end"], kv[0]))
    if len(ordered) > MAX_SESSIONS:
        ordered, truncated = ordered[:MAX_SESSIONS], True
    sessions = []
    for sid, r in ordered:
        sessions.append({"id": sid, "label": shown(r["label"], wh), "start": iso(r["start"]),
                         "end": iso(r["end"]),
                         "days": {d: int(round(s)) for d, s in sorted(r["days"].items())
                                  if int(round(s)) > 0}})
    if write_cache and cache_file is not None and files != old:
        _write_cache(cache_file, fp, files)
    return {"days": days, "now": iso(now),
            "tree": shown(os.path.basename(os.path.normpath(trm_root)), wh),
            "sessions": sessions, "outside": outside, "unparsed": unparsed,
            "files": len(window), "truncated": truncated}


def run(cfg: Any, wh: Withheld, days: int = DAYS_DEFAULT, write_cache: bool = True) -> dict:
    """`collect` with the paths of node.json."""
    return collect(cfg.sessions_dir, cfg.trm_root, cache_path(cfg), wh, days,
                   write_cache=write_cache)


def check_days(v: Any) -> int:
    if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= DAYS_MAX:
        raise ProtocolError("bad_args", "days must be an integer from 1 to %d" % DAYS_MAX)
    return v
