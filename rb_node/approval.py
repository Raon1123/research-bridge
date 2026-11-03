"""Node-side job approval (SEC-01, docs/design/2026-11-03-node-side-approval.md; stdlib only).

The node runs job_submit / job_cancel only when the request carries approval_key, the
PBKDF2 key derived from a passphrase the user types at approval time. The node stores only
sha256(key) (the verifier), set from the node console with `rb-node approve-key set`; no
bridge op can set or read it. A holder of the bridge key alone therefore cannot queue or
cancel a job. The laptop derives the key with the same derive() function.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Optional, Tuple

from .protocol import ProtocolError

ITERATIONS = 600000
MIN_ITERATIONS = 100000  # the laptop refuses node params below this (a node could weaken the KDF)
MAX_ITERATIONS = 10000000
MIN_PASSPHRASE = 12
FREE_FAILURES = 5  # wrong keys allowed before the wait starts
BASE_WAIT = 30
MAX_WAIT = 3600
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def derive(passphrase: str, salt_hex: str, iterations: int) -> str:
    """Approval key (hex) from the passphrase and the node's public parameters."""
    raw = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), bytes.fromhex(salt_hex),
                              iterations)
    return raw.hex()


def make_record(passphrase: str, iterations: int = ITERATIONS,
                salt_hex: Optional[str] = None) -> Tuple[dict, str]:
    """(verifier record, approval key). Only the record is stored."""
    salt_hex = salt_hex or secrets.token_hex(16)
    key = derive(passphrase, salt_hex, iterations)
    rec = {"salt": salt_hex, "iterations": iterations,
           "verifier": hashlib.sha256(bytes.fromhex(key)).hexdigest()}
    return rec, key


def write_record(path: Path, rec: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(rec, fh)
    os.replace(str(tmp), str(path))


def _load(path: Path) -> Optional[dict]:
    try:
        rec = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(rec, dict) or not all(isinstance(rec.get(k), t) for k, t in (
            ("salt", str), ("iterations", int), ("verifier", str))):
        return None
    return rec


def params(path: Path) -> dict:
    """Public parameters for the laptop's derive(); no secret."""
    rec = _load(path)
    if rec is None:
        raise ProtocolError("no_verifier", "no approval verifier; run rb-node approve-key set")
    return {"salt": rec["salt"], "iterations": rec["iterations"]}


def _fail_path(state: Path) -> Path:
    return Path(state) / "approve_fail.json"


def _wait_left(state: Path, now: float) -> float:
    try:
        f = json.loads(_fail_path(state).read_text(encoding="utf-8"))
        count, last = int(f["count"]), float(f["last"])
    except (OSError, ValueError, KeyError, TypeError):
        return 0.0
    if count < FREE_FAILURES:
        return 0.0
    wait = min(MAX_WAIT, BASE_WAIT * 2 ** (count - FREE_FAILURES))
    return max(0.0, last + wait - now)


def _record_failure(state: Path, now: float) -> None:
    try:
        count = int(json.loads(_fail_path(state).read_text(encoding="utf-8"))["count"])
    except (OSError, ValueError, KeyError, TypeError):
        count = 0
    Path(state).mkdir(parents=True, exist_ok=True)
    _fail_path(state).write_text(json.dumps({"count": count + 1, "last": now}), encoding="utf-8")


def check(path: Path, state: Path, args: dict, now: Optional[float] = None) -> None:
    """Raise unless args["approval_key"] matches the stored verifier. Writes nothing else."""
    now = time.time() if now is None else now
    rec = _load(path)
    if rec is None:
        raise ProtocolError("not_authorized", "no approval verifier on this node")
    if _wait_left(state, now) > 0:
        raise ProtocolError("approval_wait", "too many wrong approval keys; retry later")
    key = args.get("approval_key")
    good = isinstance(key, str) and bool(_HEX64.match(key)) and hmac.compare_digest(
        hashlib.sha256(bytes.fromhex(key)).hexdigest(), rec["verifier"])
    if not good:
        _record_failure(state, now)
        raise ProtocolError("not_authorized", "approval key not accepted")
    try:
        _fail_path(state).unlink()
    except OSError:
        pass
