"""Job records (ledger only) and the approval step. Called by the rb CLI, never by an MCP tool."""
from __future__ import annotations

import hashlib
import os
import time
import uuid
from pathlib import Path
from typing import List, Optional

from rb_node import approval

from .client import NodeClient, RemoteError
from .config import HostConfig, load_host_config
from .ledger import Ledger

DONE = {"submit": "queued", "cancel": "cancelled_requested"}
REFUSED = ("not_authorized", "approval_wait", "no_verifier")  # node refused the approval


def load_cfg() -> HostConfig:
    p = os.environ.get("RB_HOST_CONFIG")
    return load_host_config(Path(p) if p else None)


def ledger_for(cfg: HostConfig) -> Ledger:
    return Ledger(Path(cfg.data_root) / "ledger.jsonl")


def connect(cfg: HostConfig, node: str) -> NodeClient:
    """Client factory; tests replace it. Creating the client does not connect."""
    return NodeClient(cfg.alias(node))


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(str(path), "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _existing(ledger: Ledger, op: str, key: str) -> Optional[dict]:
    for r in ledger._latest().values():
        if r.get("kind") == "job" and r.get("op") == op and r.get("idempotency_key") == key:
            return r
    return None


def create_submit(ledger: Ledger, cfg: HostConfig, node: str, config_path: str,
                  gpus: List[int], gpu_hours: float, idempotency_key: str, note: str = "") -> dict:
    cfg.alias(node)  # unknown node -> ValueError
    if not idempotency_key:
        raise ValueError("idempotency_key required")
    prior = _existing(ledger, "submit", idempotency_key)
    if prior is not None:
        return prior
    p = Path(config_path)
    if not p.is_file():
        raise ValueError("config file not found")
    rec = {"kind": "job", "op": "submit", "id": uuid.uuid4().hex, "node": node,
           "config_path": str(p.resolve()), "config_name": p.name, "config_sha256": _sha(p),
           "gpus": list(gpus), "gpu_hours": gpu_hours, "idempotency_key": idempotency_key,
           "note": note, "status": "pending_approval", "created": now()}
    ledger.append(rec)
    return rec


def create_cancel(ledger: Ledger, cfg: HostConfig, node: str, job_id: str,
                  idempotency_key: str) -> dict:
    cfg.alias(node)
    if not idempotency_key:
        raise ValueError("idempotency_key required")
    prior = _existing(ledger, "cancel", idempotency_key)
    if prior is not None:
        return prior
    rec = {"kind": "job", "op": "cancel", "id": uuid.uuid4().hex, "node": node,
           "target_job_id": job_id, "idempotency_key": idempotency_key,
           "status": "pending_approval", "created": now()}
    ledger.append(rec)
    return rec


def describe(rec: dict) -> str:
    if rec.get("op") == "cancel":
        return "CANCEL job %s on node %s (key %s)" % (rec.get("target_job_id"), rec["node"],
                                                      rec["idempotency_key"])
    return ("SUBMIT job %s\n  node: %s\n  config: %s (%s)\n  gpus: %s\n  gpu_hours: %s\n  note: %s"
            % (rec["id"], rec["node"], rec.get("config_name"), rec.get("config_path"),
               ",".join(str(g) for g in rec.get("gpus", [])), rec.get("gpu_hours"),
               rec.get("note", "")))


def _job(ledger: Ledger, job_id: str) -> dict:
    rec = ledger.get(job_id)
    if rec is None or rec.get("kind") != "job":
        raise ValueError("unknown job: %s" % job_id)
    return rec


def approval_key(c: NodeClient, passphrase: str) -> str:
    """Derive the node's approval key from the typed passphrase (SEC-01). Never stored."""
    p = c.call("approve_params")
    try:
        salt, iters = str(p["salt"]), p["iterations"]
        ok = (isinstance(iters, int) and not isinstance(iters, bool) and len(salt) <= 128
              and approval.MIN_ITERATIONS <= iters <= approval.MAX_ITERATIONS)
        if not ok:
            raise ValueError
        return approval.derive(passphrase, salt, iters)
    except (KeyError, TypeError, ValueError):
        raise ValueError("node approval parameters are not acceptable")


def approve(ledger: Ledger, cfg: HostConfig, job_id: str, passphrase: str) -> dict:
    """Send an approved job to the node. passphrase comes from the user (getpass or the
    8765 form), never from a file, an environment variable or an MCP tool."""
    if not passphrase:
        raise ValueError("approval passphrase required")
    rec = _job(ledger, job_id)
    if rec["status"] in DONE.values():
        return rec  # second approve is a no-op
    if rec["status"] not in ("pending_approval", "approved"):
        raise ValueError("job is %s, cannot approve" % rec["status"])
    if rec["op"] == "submit":
        cp = Path(rec["config_path"])
        if not cp.is_file() or _sha(cp) != rec["config_sha256"]:
            raise ValueError("config file changed since submit; submit again")
    ledger.update(job_id, status="approved", approved_at=now())
    try:
        with connect(cfg, rec["node"]) as c:
            key = approval_key(c, passphrase)
            if rec["op"] == "submit":
                cp = Path(rec["config_path"])
                c.put_file("job-" + job_id, cp)
                result = c.call("job_submit", job_id=job_id, config_name=cp.name,
                                config_sha256=rec["config_sha256"], gpus=rec["gpus"],
                                gpu_hours=rec["gpu_hours"],
                                idempotency_key=rec["idempotency_key"], approval_key=key)
            else:
                result = c.call("job_cancel", job_id=rec["target_job_id"],
                                idempotency_key=rec["idempotency_key"], approval_key=key)
    except (RemoteError, ValueError) as exc:
        if isinstance(exc, ValueError) or exc.code in REFUSED:
            # the node did not accept this approval: the ledger must not say approved
            ledger.update(job_id, status="pending_approval", approved_at=None)
        raise
    return ledger.update(job_id, status=DONE[rec["op"]], result=result)


def reject(ledger: Ledger, job_id: str) -> dict:
    rec = _job(ledger, job_id)
    if rec["status"] == "rejected":
        return rec
    if rec["status"] != "pending_approval":
        raise ValueError("job is %s, cannot reject" % rec["status"])
    return ledger.update(job_id, status="rejected", rejected_at=now())
