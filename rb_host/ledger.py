"""Append-only JSONL ledger; readers take the last line per id."""
from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, List, Optional

LOCK_STALE_S = 30.0    # a lock file older than this belongs to a crashed process
LOCK_TIMEOUT_S = 10.0  # how long to wait for the lock before giving up
_THREAD_LOCKS = {}  # type: Dict[str, threading.RLock]
_THREAD_LOCKS_GUARD = threading.Lock()


def _thread_lock(path: Path) -> threading.RLock:
    key = os.path.normcase(os.path.abspath(str(path)))
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.RLock())


class Ledger:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._depth = {}  # type: Dict[int, int]  # thread id -> lock nesting depth

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Exclusive lock for read-modify-write on this ledger (PM-11). Re-entrant in a thread;
        across processes it is an O_EXCL lock file `<ledger>.lock` with a stale timeout, which
        works on Windows and POSIX. Hold it only for ledger work, never across a network call."""
        tl = _thread_lock(self.path)
        with tl:
            tid = threading.get_ident()
            depth = self._depth.get(tid, 0)
            if depth == 0:
                self._acquire_file()
            self._depth[tid] = depth + 1
            try:
                yield
            finally:
                self._depth[tid] = depth
                if depth == 0:
                    del self._depth[tid]
                    try:
                        os.unlink(self._lock_path())
                    except OSError:
                        pass

    def _lock_path(self) -> str:
        return str(self.path) + ".lock"

    def _acquire_file(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lp = self._lock_path()
        deadline = time.monotonic() + LOCK_TIMEOUT_S
        while True:
            try:
                fd = os.open(lp, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode("ascii"))
                os.close(fd)
                return
            except FileExistsError:
                pass
            try:
                if time.time() - os.stat(lp).st_mtime > LOCK_STALE_S:
                    os.unlink(lp)
                    continue
            except OSError:
                continue  # vanished or locked by a racer; try again
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

    def thread(self, msg_id: str) -> List[dict]:
        return [r for r in self._latest().values()
                if r.get("id") == msg_id or r.get("reply_to") == msg_id
                or r.get("msg_id") == msg_id]

    def pending_jobs(self) -> List[dict]:
        return [r for r in self._latest().values()
                if r.get("kind") == "job" and r.get("status") == "pending_approval"]
