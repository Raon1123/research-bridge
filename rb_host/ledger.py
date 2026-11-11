"""Append-only JSONL ledger; readers take the last line per id."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional

LOCK_STALE_S = 30.0    # a lock file older than this belongs to a crashed process
LOCK_TIMEOUT_S = 10.0  # how long to wait for the lock before giving up
_THREAD_LOCKS = {}  # type: Dict[str, threading.RLock]
_HELD = {}  # type: Dict[str, list]  # lock key -> [depth, token]; guarded by the thread lock
_THREAD_LOCKS_GUARD = threading.Lock()


def _key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _thread_lock(path: Path) -> threading.RLock:
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(_key(path), threading.RLock())


class Ledger:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Exclusive lock for read-modify-write on this ledger (PM-11). Re-entrant in a thread
        (depth is kept per ledger path, so separate Ledger objects for one file nest correctly);
        across processes it is an O_EXCL lock file `<ledger>.lock` holding a unique token, with a
        stale timeout; works on Windows and POSIX. Hold it only for ledger work, never across a
        network call."""
        with _thread_lock(self.path):
            held = _HELD.get(_key(self.path))
            if held is None:
                held = _HELD[_key(self.path)] = [0, self._acquire_file()]
            held[0] += 1
            try:
                yield
            finally:
                held[0] -= 1
                if held[0] == 0:
                    del _HELD[_key(self.path)]
                    self._release_file(held[1])

    def _lock_path(self) -> str:
        return str(self.path) + ".lock"

    def _release_file(self, token: str) -> None:
        """Remove the lock file only if it still holds our token (never someone else's lock)."""
        lp = self._lock_path()
        try:
            with open(lp, "r", encoding="ascii") as fh:
                mine = fh.read() == token
            if mine:
                os.unlink(lp)
        except OSError:
            pass

    def _take_over_stale(self, lp: str) -> None:
        """Move a lock file that looked stale out of the way. The rename succeeds for only one
        contender. The file that was moved is re-checked: if it turns out to be fresh (another
        contender already replaced the stale lock), it is put back."""
        moved = "%s.stale-%s" % (lp, uuid.uuid4().hex)
        try:
            os.replace(lp, moved)
        except OSError:
            return  # someone else took it over first
        try:
            if time.time() - os.stat(moved).st_mtime <= LOCK_STALE_S:
                try:
                    os.link(moved, lp)  # fails if lp exists again; then that lock stands
                except OSError:
                    pass
        except OSError:
            pass
        try:
            os.unlink(moved)
        except OSError:
            pass

    def _acquire_file(self) -> str:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lp = self._lock_path()
        token = "%d-%s" % (os.getpid(), uuid.uuid4().hex)
        deadline = time.monotonic() + LOCK_TIMEOUT_S
        while True:
            try:
                fd = os.open(lp, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, token.encode("ascii"))
                os.close(fd)
                return token
            except FileExistsError:
                pass
            try:
                if time.time() - os.stat(lp).st_mtime > LOCK_STALE_S:
                    self._take_over_stale(lp)
                    continue
            except OSError:
                continue  # vanished meanwhile; try again
            if time.monotonic() > deadline:
                raise TimeoutError("ledger is locked: %s" % lp)
            time.sleep(0.01)

    def _lines(self) -> List[dict]:
        if not self.path.is_file():
            return []
        out = []
        with open(str(self.path), "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue  # torn trailing line from a crash
                if isinstance(rec, dict):
                    out.append(rec)
        return out

    def _write(self, rec: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(str(self.path), "ab") as fh:
            fh.write((json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8"))

    def _latest(self) -> Dict[str, dict]:
        latest = {}  # type: Dict[str, dict]
        for r in self._lines():
            if "id" in r:
                latest[r["id"]] = r
        return latest

    def append(self, rec: dict) -> bool:
        key = (rec.get("kind"), rec.get("id"))
        with self.locked():
            for r in self._lines():
                if (r.get("kind"), r.get("id")) == key:
                    return False
            self._write(rec)
            return True

    def get(self, id: str) -> Optional[dict]:
        return self._latest().get(id)

    def update(self, id: str, **fields: object) -> dict:
        with self.locked():
            cur = self.get(id)
            if cur is None:
                raise KeyError(id)
            new = dict(cur)
            new.update(fields)
            self._write(new)
            return new

    def claim(self, match: Callable[[dict], bool], **fields: object) -> List[dict]:
        """Under the lock: one read, then one appended line `dict(r, **fields)` for every latest
        record that `match` accepts. Returns the written records in ledger order. Two callers
        never receive the same record, because the second reads what the first wrote."""
        with self.locked():
            out = []  # type: List[dict]
            for r in list(self._latest().values()):
                if match(r):
                    new = dict(r, **fields)
                    self._write(new)
                    out.append(new)
            return out

    def thread(self, msg_id: str) -> List[dict]:
        return [r for r in self._latest().values()
                if r.get("id") == msg_id or r.get("reply_to") == msg_id]

    def pending_jobs(self) -> List[dict]:
        return [r for r in self._latest().values()
                if r.get("kind") == "job" and r.get("status") == "pending_approval"]
