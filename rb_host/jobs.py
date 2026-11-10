"""Job records (ledger only) and the approval step. Called by the rb CLI, never by an MCP tool."""
from __future__ import annotations

import hashlib
import os
import time
import unicodedata
import uuid
from pathlib import Path
from typing import List, Optional

from rb_node import approval

from .client import NodeClient, RemoteError
from .config import HostConfig, load_host_config
from .ledger import Ledger

DONE = {"submit": "queued", "cancel": "cancelled_requested"}
REFUSED = ("not_authorized", "approval_wait", "no_verifier",  # node refused the approval
           "gpu_status_unavailable", "no_gpus")  # node refused the job: it is not queued, ask again later
CLAIM_TTL_S = 300.0  # an approve call that died mid-way blocks a retry for this long


ALLOWED_HOSTS = ("127.0.0.1:8765", "localhost:8765")
ALLOWED_ORIGINS = ("http://127.0.0.1:8765", "http://localhost:8765")


def host_allowed(host: object) -> bool:
    """PM-03: the Host header of a request to the 8765 pages must be the loopback name and
    port; a DNS-rebinding page arrives with its own host name."""
    return isinstance(host, str) and host.lower() in ALLOWED_HOSTS


def origin_allowed(origin: object) -> bool:
    """A POST may carry no Origin, but if it does it must be this server's own."""
    return origin is None or (isinstance(origin, str) and origin.lower() in ALLOWED_ORIGINS)


def load_cfg() -> HostConfig:
    p = os.environ.get("RB_HOST_CONFIG")
    return load_host_config(Path(p) if p else None)


def ledger_for(cfg: HostConfig) -> Ledger:
    return Ledger(Path(cfg.data_root) / "ledger.jsonl")


def connect(cfg: HostConfig, node: str) -> NodeClient:
    """Client factory; tests replace it. Creating the client does not connect."""
    return NodeClient(cfg.alias(node), node=node)


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


_WS = "\n\r\t"


def clean(v: object, limit: int = 300) -> str:
    """Text from the ledger is written by a laptop session, so it is shown to the approver
    stripped of control, format (bidi) and other non-printable characters (SEC-03)."""
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


def describe(rec: dict) -> str:
    if rec.get("op") == "cancel":
        return "CANCEL job %s on node %s (key %s)" % (
            clean(rec.get("target_job_id")), clean(rec.get("node")), clean(rec.get("idempotency_key")))
    fields = ("SUBMIT job %s", "  node: %s", "  config: %s", "  config_path: %s",
              "  config_sha256: %s", "  gpus: %s", "  gpu_hours: %s", "  note: %s")
    return ("\n".join(fields)
            % (clean(rec.get("id")), clean(rec.get("node")), clean(rec.get("config_name")),
               clean(rec.get("config_path")), clean(rec.get("config_sha256"))[:12],
               clean(",".join(str(g) for g in rec.get("gpus", []))), clean(rec.get("gpu_hours")),
               clean(rec.get("note", ""))))


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


def _check_config(rec: dict) -> Path:
    """SEC-04: the name the node will see is the file's own name, and the file is the one that
    was shown to the approver (same sha256)."""
    cp = Path(rec["config_path"])
    if rec.get("config_name") != cp.name:
        raise ValueError("config_name does not match config_path; refusing")
    if not cp.is_file() or _sha(cp) != rec["config_sha256"]:
        raise ValueError("config file changed since submit; submit again")
    return cp


def approve(ledger: Ledger, cfg: HostConfig, job_id: str, passphrase: str) -> dict:
    """Send an approved job to the node. passphrase comes from the user (getpass or the
    8765 form), never from a file, an environment variable or an MCP tool.

    The status check and the claim (PM-11) happen under the ledger lock, so two approvals of
    one job (CLI and 8765 page) cannot both reach the node."""
    if not passphrase:
        raise ValueError("approval passphrase required")
    with ledger.locked():
        rec = _job(ledger, job_id)
        if rec["status"] in DONE.values():
            return rec  # second approve is a no-op
        if rec["status"] not in ("pending_approval", "approved"):
            raise ValueError("job is %s, cannot approve" % rec["status"])
        if (rec["status"] == "approved" and rec.get("approving")
                and time.time() - float(rec.get("approving_at") or 0) < CLAIM_TTL_S):
            raise ValueError("another approval of this job is in progress")
        if rec["op"] == "submit":
            _check_config(rec)
        ledger.update(job_id, status="approved", approved_at=now(), approving=uuid.uuid4().hex,
                      approving_at=time.time())
    try:
        with connect(cfg, rec["node"]) as c:
            key = approval_key(c, passphrase)
            if rec["op"] == "submit":
                cp = _check_config(rec)  # again, right before the upload
                c.put_file("job-" + job_id, cp)
                result = c.call("job_submit", job_id=job_id, config_name=cp.name,
                                config_sha256=rec["config_sha256"], gpus=rec["gpus"],
                                gpu_hours=rec["gpu_hours"],
                                idempotency_key=rec["idempotency_key"], approval_key=key)
            else:
                result = c.call("job_cancel", job_id=rec["target_job_id"],
                                idempotency_key=rec["idempotency_key"], approval_key=key)
    except BaseException as exc:
        if isinstance(exc, ValueError) or (isinstance(exc, RemoteError) and exc.code in REFUSED):
            # the node did not accept this approval: the ledger must not say approved
            ledger.update(job_id, status="pending_approval", approved_at=None,
                          approving=None, approving_at=None)
        else:  # transport failure etc.: stays approved so the user can retry
            ledger.update(job_id, approving=None, approving_at=None)
        raise
    queued = result.get("queued") if isinstance(result, dict) else None
    if rec["op"] == "submit" and not (isinstance(queued, str)
                                      and queued.endswith("_%s.job" % job_id)):
        # an old node replays a stored result by idempotency key alone: it may name another job
        ledger.update(job_id, status="pending_approval", approved_at=None,
                      approving=None, approving_at=None)
        raise ValueError("the node answered with another job's queue file; nothing was queued "
                         "for %s (idempotency key reused?)" % job_id)
    return ledger.update(job_id, status=DONE[rec["op"]], result=result,
                         approving=None, approving_at=None)


def reject(ledger: Ledger, job_id: str) -> dict:
    with ledger.locked():
        rec = _job(ledger, job_id)
        if rec["status"] == "rejected":
            return rec
        if rec["status"] != "pending_approval":
            raise ValueError("job is %s, cannot reject" % rec["status"])
        return ledger.update(job_id, status="rejected", rejected_at=now())
