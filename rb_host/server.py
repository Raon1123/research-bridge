"""FastMCP server `research-bridge` (stdio). Mutations only create pending_approval records."""
from __future__ import annotations

import base64
import hashlib
import os
import re
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from rb_node.protocol import CHUNK
from rb_node.withheld import Withheld

from . import jobs
from .client import NodeClient, RemoteError, TransportError
from .jobs import ledger_for, load_cfg
from .store import _remote_name, _safe_name, store_incoming

mcp = FastMCP("research-bridge")
_DOC_ID = re.compile(r"^(H|EXP)-\d+$")


def _run(node: str, fn: Callable[[NodeClient], Any]) -> Any:
    """Run fn with a connected client; node errors are reported by code only."""
    cfg = load_cfg()
    try:
        with jobs.connect(cfg, node) as c:
            return fn(c)
    except RemoteError as exc:
        return {"error": exc.code}
    except TransportError as exc:
        return {"error": str(exc)}


def nodes() -> dict:
    """List configured node names."""
    return {"nodes": sorted(load_cfg().nodes)}


def _upload(c: NodeClient, msg_id: str, body: str, files: List[Path],
            from_session: Optional[str]) -> None:
    metas = []
    for f in files:
        h = hashlib.sha256()
        size = 0
        with open(str(f), "rb") as fh:
            for chunk in iter(lambda: fh.read(CHUNK), b""):
                h.update(chunk)
                size += len(chunk)
        metas.append({"name": f.name, "bytes": size, "sha256": h.hexdigest()})
    res = c.call("msg_begin", msg_id=msg_id, body=body, from_session=from_session,
                 attachments=metas)
    for f, stored in zip(files, res["names"]):
        with open(str(f), "rb") as fh:
            seq = 0
            while True:
                data = fh.read(CHUNK)
                if not data and seq > 0:
                    break
                c.call("put_chunk", msg_id=msg_id, name=stored, seq=seq,
                       data_b64=base64.b64encode(data).decode("ascii"))
                seq += 1
                if len(data) < CHUNK:
                    break
    c.call("msg_commit", msg_id=msg_id)


def send_message(node: str, body: str, attachments: List[str] = [],
                 reply_to: Optional[str] = None, from_session: str = "",
                 msg_id: Optional[str] = None) -> dict:
    """Send a message to a node. Pass the returned msg_id again to retry a failed send."""
    cfg = load_cfg()
    cfg.alias(node)
    files = [Path(a) for a in attachments]
    for f in files:
        if not f.is_file():
            raise ValueError("attachment not found: %s" % f.name)
    led = ledger_for(cfg)
    mid = msg_id or uuid.uuid4().hex
    if led.get(mid) is None:
        led.append({"kind": "message", "id": mid, "direction": "out", "node": node,
                    "reply_to": reply_to, "from_session": from_session,
                    "attachments": [f.name for f in files], "body_chars": len(body),
                    "status": "pending_send", "created": jobs.now()})
    res = _run(node, lambda c: _upload(c, mid, body, files, from_session or None))
    if isinstance(res, dict) and "error" in res:
        return {"msg_id": mid, "status": "pending_send", "error": res["error"]}
    led.update(mid, status="sent")
    return {"msg_id": mid, "status": "sent"}


def _poll_node(cfg: Any, node: str) -> Any:
    led = ledger_for(cfg)

    def work(c: NodeClient) -> dict:
        items = c.call("poll").get("items", [])
        new, ack, errors = [], [], 0
        for it in items:
            iid = str(it.get("id"))
            seen = led.get(iid)
            if seen is not None and seen.get("direction") == "in":
                ack.append(iid)
                continue
            try:
                stored = store_incoming(cfg, node, it, c)
            except ValueError:
                errors += 1
                continue
            led.append({"kind": "message", "id": iid, "direction": "in", "node": node,
                        "msg_kind": stored["kind"], "reply_to": stored["reply_to"],
                        "files": stored["files"], "quarantined": stored["quarantined"],
                        "status": "received", "created": jobs.now()})
            new.append(stored)
            ack.append(iid)
        if ack:
            c.call("ack", ids=ack)
        return {"items": new, "rejected": errors}

    return _run(node, work)


def poll(node: Optional[str] = None) -> dict:
    """Fetch new node items, store and ack them. Bodies are already masked."""
    cfg = load_cfg()
    names = [node] if node else sorted(cfg.nodes)
    items: List[dict] = []
    errors: Dict[str, str] = {}
    for n in names:
        cfg.alias(n)
        r = _poll_node(cfg, n)
        if "error" in r:
            errors[n] = r["error"]
        else:
            items.extend(r["items"])
    out: Dict[str, Any] = {"items": items}
    if errors:
        out["errors"] = errors
    return out


def thread(msg_id: str) -> List[dict]:
    """Ledger records for a message and its replies."""
    return ledger_for(load_cfg()).thread(msg_id)


def read_doc(node: str, ref: str) -> dict:
    """Read a document via the node policy. ref is H-123, EXP-015, or a path."""
    args = {"id": ref} if _DOC_ID.match(ref) else {"path": ref}
    return _run(node, lambda c: c.call("read_doc", **args))


def fetch_file(node: str, path: str) -> dict:
    """Download a node file through the node policy; returns the local stored path."""
    cfg = load_cfg()
    cfg.alias(node)
    dest = Path(cfg.data_root) / "fetched" / node / _safe_name(path)
    # downloaded under the node's extension (check_file needs it), renamed after the check (SEC-02)
    stage = dest.parent / ("fetch-" + _remote_name(path).replace(":", "_"))

    def work(c: NodeClient) -> dict:
        try:
            sha = c.get_file("doc", path, stage)
        except (RemoteError, TransportError):
            part = stage.with_suffix(stage.suffix + ".part")
            if part.exists():
                part.unlink()
            raise
        return {"sha256": sha}

    res = _run(node, work)
    if "error" in res:
        return res
    verdict = Withheld.load(Path(cfg.withheld_patterns_file)).check_file(stage)
    if verdict != "ok":
        stage.unlink()
        return {"error": "withheld"}
    os.replace(str(stage), str(dest))
    return {"path": str(dest), "sha256": res["sha256"]}


def queue_status(node: str) -> dict:
    """Job queue entries on the node."""
    return _run(node, lambda c: c.call("queue_status"))


def gpu_status(node: str) -> dict:
    """GPU usage on the node."""
    return _run(node, lambda c: c.call("gpu_status"))


def submit_job(node: str, config_path: str, gpus: List[int], gpu_hours: float,
               idempotency_key: str, note: str = "") -> dict:
    """Request a job. Creates a pending_approval record only; the user approves with `rb approve`."""
    cfg = load_cfg()
    rec = jobs.create_submit(ledger_for(cfg), cfg, node, config_path, gpus, gpu_hours,
                             idempotency_key, note)
    return {"job_id": rec["id"], "status": rec["status"]}


def cancel_job(node: str, job_id: str, idempotency_key: str) -> dict:
    """Request a cancel. Creates a pending_approval record only; the user approves with `rb approve`."""
    cfg = load_cfg()
    rec = jobs.create_cancel(ledger_for(cfg), cfg, node, job_id, idempotency_key)
    return {"job_id": rec["id"], "status": rec["status"]}


for _fn in (nodes, send_message, poll, thread, read_doc, fetch_file, queue_status, gpu_status,
            submit_job, cancel_job):
    mcp.tool()(_fn)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
