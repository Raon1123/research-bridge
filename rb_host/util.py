"""Small helpers shared by hub modules: file hash, UTC time stamp, age of a time stamp.

Standard library only and no rb_host import, so that every hub module (also `share`, which
imports no client, server, jobs or board module) can use it without an import cycle.
"""
from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

STAMP = "%Y-%m-%dT%H:%M:%SZ"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(str(path), "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):  # a read buffer, not the transfer chunk
            h.update(block)
    return h.hexdigest()


def now() -> str:
    """The current UTC time as the ledger and the status files write it."""
    return time.strftime(STAMP, time.gmtime())


def parse_utc(ts: Any) -> Optional[datetime]:
    """An aware UTC datetime from an ISO 8601 string (`Z` or an offset), or None."""
    if not isinstance(ts, str):
        return None
    try:
        d = datetime.fromisoformat(ts.strip().replace("Z", "+00:00"))
        return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def age_s(ts: Any, now_s: Optional[float] = None) -> Optional[float]:
    """Seconds since the time stamp `ts`, at least 0; None when `ts` is not a time stamp."""
    d = parse_utc(ts)
    if d is None:
        return None
    return max(0.0, (time.time() if now_s is None else now_s) - d.timestamp())
