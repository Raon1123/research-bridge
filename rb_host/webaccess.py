"""Access control for the read-only hub page (design 2026-11-10-sync-and-hub-page.md, section 6.6).

A one-time access key is issued in a hub terminal (`rb web key`) and exchanged once, at
`/enter`, for a session cookie. State is one file, `<data_root>/web/access.json`
(directory 0700, file 0600), holding SHA-256 hashes only: a key or session token is never
stored in clear. The command and the server are separate processes and the server is
threaded, so every read-modify-write holds an exclusive `flock` on `access.lock`. A missing,
unreadable or malformed file means "no keys, no sessions" (deny).
"""
from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .store import _atomic_write

MAX_KEYS = 20
MAX_SESSIONS = 50
KEY_MINUTES = (1, 60)
SESSION_HOURS = (1, 168)
TOKEN_SYNTAX = re.compile(r"^[A-Za-z0-9_-]{20,128}$")


def _now() -> float:
    return time.time()


def _dir(cfg: Any) -> Path:
    return Path(cfg.data_root) / "web"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def valid_syntax(value: Any) -> bool:
    return isinstance(value, str) and TOKEN_SYNTAX.fullmatch(value) is not None


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _parse(text: str) -> Dict[str, List[dict]]:
    """keys and sessions from the file text; anything malformed is dropped (deny)."""
    empty = {"keys": [], "sessions": []}  # type: Dict[str, List[dict]]
    try:
        data = json.loads(text)
    except ValueError:
        return empty
    if not isinstance(data, dict):
        return empty
    out = {"keys": [], "sessions": []}  # type: Dict[str, List[dict]]
    for name, extra in (("keys", "session_seconds"), ("sessions", None)):
        items = data.get(name)
        if not isinstance(items, list):
            continue
        for e in items:
            if (isinstance(e, dict) and isinstance(e.get("sha256"), str)
                    and _num(e.get("expires_at"))
                    and (extra is None or (isinstance(e.get(extra), int)
                                           and not isinstance(e.get(extra), bool)
                                           and e[extra] > 0))):
                item = {"sha256": e["sha256"], "expires_at": e["expires_at"]}
                if extra:
                    item[extra] = e[extra]
                out[name].append(item)
    return out


def _read(cfg: Any) -> Dict[str, List[dict]]:
    try:
        return _parse((_dir(cfg) / "access.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"keys": [], "sessions": []}


class _Locked:
    """Exclusive lock on access.lock, creating the directory (0700) and lock file (0600)."""

    def __init__(self, cfg: Any) -> None:
        self.dir = _dir(cfg)
        self.fd = -1

    def __enter__(self) -> "_Locked":
        self.dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(str(self.dir), 0o700)
        self.fd = os.open(str(self.dir / "access.lock"), os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc: Any) -> None:
        os.close(self.fd)  # closing releases the lock

    def load(self) -> Dict[str, List[dict]]:
        try:
            state = _parse((self.dir / "access.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {"keys": [], "sessions": []}
        now = _now()
        return {k: [e for e in v if e["expires_at"] > now] for k, v in state.items()}

    def save(self, state: Dict[str, List[dict]]) -> None:
        for name, cap in (("keys", MAX_KEYS), ("sessions", MAX_SESSIONS)):
            state[name].sort(key=lambda e: e["expires_at"])
            del state[name][:max(0, len(state[name]) - cap)]
        _atomic_write(self.dir / "access.json", json.dumps(state, indent=2))


def issue_key(cfg: Any, minutes: int, session_hours: int) -> str:
    """A new single-use key valid for `minutes`; the session it opens lasts `session_hours`."""
    key = secrets.token_urlsafe(32)
    with _Locked(cfg) as lk:
        state = lk.load()
        while len(state["keys"]) >= MAX_KEYS:  # the entry that expires first goes
            state["keys"].remove(min(state["keys"], key=lambda e: e["expires_at"]))
        state["keys"].append({"sha256": _hash(key), "expires_at": _now() + minutes * 60,
                              "session_seconds": int(session_hours * 3600)})
        lk.save(state)
    return key


def redeem(cfg: Any, key: Any) -> Optional[Tuple[str, int]]:
    """Exchange a pending key for a session: (token, session_seconds), or None."""
    if not valid_syntax(key):
        return None
    digest = _hash(key)
    try:
        with _Locked(cfg) as lk:
            state = lk.load()
            hit = None
            for e in state["keys"]:
                if hmac.compare_digest(e["sha256"], digest):
                    hit = e
            if hit is None:
                lk.save(state)  # also drops expired entries
                return None
            state["keys"].remove(hit)
            token = secrets.token_urlsafe(32)
            while len(state["sessions"]) >= MAX_SESSIONS:
                state["sessions"].remove(min(state["sessions"], key=lambda e: e["expires_at"]))
            seconds = int(hit["session_seconds"])
            state["sessions"].append({"sha256": _hash(token), "expires_at": _now() + seconds})
            lk.save(state)
            return token, seconds
    except OSError:
        return None


def session_ok(cfg: Any, token: Any) -> bool:
    """Read only: the writer replaces the file atomically, so no lock is needed."""
    if not valid_syntax(token):
        return False
    digest = _hash(token)
    now = _now()
    ok = False
    for e in _read(cfg)["sessions"]:
        if hmac.compare_digest(e["sha256"], digest) and e["expires_at"] > now:
            ok = True
    return ok


def revoke_all(cfg: Any) -> Tuple[int, int]:
    """Remove every key and session; returns (keys, sessions) removed (expired entries are not counted)."""
    with _Locked(cfg) as lk:
        state = lk.load()
        _atomic_write(lk.dir / "access.json", json.dumps({"keys": [], "sessions": []}, indent=2))
        return len(state["keys"]), len(state["sessions"])


def counts(cfg: Any) -> Tuple[int, int]:
    """(unexpired pending keys, unexpired sessions)."""
    now = _now()
    st = _read(cfg)
    return (sum(1 for e in st["keys"] if e["expires_at"] > now),
            sum(1 for e in st["sessions"] if e["expires_at"] > now))
