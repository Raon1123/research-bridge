"""FastMCP server `research-bridge` (stdio). Mutations only create pending_approval records."""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from rb_node.withheld import Withheld

from . import jobs, store, threads
from .client import NodeClient, RemoteError, TransportError
from .jobs import ledger_for, load_cfg
from .store import (_remote_name, _safe_name, _within, store_incoming, store_outgoing,
                    valid_msg_id, valid_remote_name)

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
    """List the configured nodes and the state of the last `rb sync` pass for each.

    Returns {"nodes": [names], "status": {name: {...}}}. Per node: `synced` (false when `rb sync`
    never ran; the fields below are then null), `ok`, `error` (a code), `stage`, `last_attempt_at`,
    `last_ok_at`, `age_s`, `stale` (no successful pass in the last 900 s), `node_seen_at` (latest
    successful contact with the node), `node_version`, `protocol`, `withheld_extra` (0 means the
    node loaded no pattern file), `hub_withheld_extra` and `hub_withheld_rejected` (usable and
    non-compiling patterns in the hub's own pattern file at the last pass; null in a status file
    written before these fields existed) and `undelivered` (stored replies that no `poll` has returned yet).
    """
    cfg = load_cfg()
    names = sorted(cfg.nodes)
    return {"nodes": names, "status": {n: threads.summary(cfg, n) for n in names}}


def send_message(node: str, body: str, attachments: Optional[List[str]] = None,
                 reply_to: Optional[str] = None, from_session: str = "",
                 msg_id: Optional[str] = None) -> dict:
    """Send a message to a node session.

    Arguments: node (a configured node name); body (text); attachments (local file paths, at most
    50 MB each); reply_to (id of the node message this answers); from_session (free label);
    msg_id (omit for a new message; pass the returned id again to retry a failed send).
    Returns {"msg_id", "status": "sent"}, or {"msg_id", "status": "pending_send", "error"} when the
    node could not be reached. A masked copy of the body (lines that match a withheld pattern are
    blanked) is kept on the hub under outbox/; the text sent to the node is not changed.
    Raises ValueError for an unknown node, a missing attachment, an unsafe msg_id, a msg_id that
    belongs to an inbound message, or a msg_id already used with a different body.
    """
    cfg = load_cfg()
    cfg.alias(node)
    files = [Path(a) for a in (attachments or [])]
    for f in files:
        if not f.is_file():
            raise ValueError("attachment not found: %s" % f.name)
    led = ledger_for(cfg)
    mid = msg_id or uuid.uuid4().hex
    if not valid_msg_id(mid):
        raise ValueError("unsafe msg_id")
    existing = led.get(mid)
    if existing is not None and existing.get("direction") != "out":
        raise ValueError("msg_id belongs to an inbound message")
    store_outgoing(cfg, node, mid, body, files)
    if existing is None:
        led.append({"kind": "message", "id": mid, "direction": "out", "node": node,
                    "reply_to": reply_to, "from_session": from_session,
                    "attachments": [f.name for f in files], "body_chars": len(body),
                    "status": "pending_send", "created": jobs.now()})
    res = _run(node, lambda c: c.put_files(mid, files, body, from_session or None))
    if isinstance(res, dict) and "error" in res:
        return {"msg_id": mid, "status": "pending_send", "error": res["error"]}
    led.update(mid, status="sent")
    return {"msg_id": mid, "status": "sent"}


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, RemoteError):
        return exc.code
    if isinstance(exc, TimeoutError):
        return "ledger_locked"
    if isinstance(exc, TransportError):
        return str(exc)
    return "internal"


def fetch_node(cfg: Any, node: str, c: Any, delivered: bool,
               progress: Optional[dict] = None) -> dict:
    """Fetch, store and acknowledge the node's pending items on the open client `c`.

    Items not yet in the ledger are stored and appended with `delivered` set to the argument
    (`rb sync` passes False: a later `poll` claims them; `poll` passes True). Only items whose
    append succeeded are returned. With delivered=False every exception propagates. With
    delivered=True an exception after the first append returns the appended items with an
    "error" entry instead (those records are already marked delivered; the next fetch
    acknowledges them without returning them again). When `progress` is a dict, it receives
    `new` and `rejected` (counts so far) even when an exception propagates."""
    led = ledger_for(cfg)
    items = c.call("poll").get("items", [])
    new = []  # type: List[dict]
    ack = []  # type: List[str]
    rejected = 0
    rejected_ids = []  # type: List[str]  # ids only, valid ones, at most 10

    def reject(iid: str) -> None:
        nonlocal rejected
        rejected += 1
        if len(rejected_ids) < 10 and valid_msg_id(iid) and iid not in rejected_ids:
            rejected_ids.append(iid)

    def work() -> None:
        if not isinstance(items, list):
            raise ValueError("malformed poll result")
        # one read for the seen-check; append still checks under the lock
        known = {r["id"]: r for r in led.records()} if items else {}
        for it in items:
            iid = it.get("id") if isinstance(it, dict) else None
            if not isinstance(iid, str):  # D3: reject one malformed item, keep the others
                reject("")
                continue
            seen = known.get(iid)
            if seen is not None and seen.get("direction") == "in":
                if iid not in ack:
                    ack.append(iid)
                continue
            if seen is not None:  # the id belongs to an outgoing or job record: do not ack
                reject(iid)
                continue
            try:
                stored = store_incoming(cfg, node, it, c)
            except (ValueError, OSError, KeyError, AttributeError, TypeError):
                reject(iid)
                continue
            rec = {"kind": "message", "id": iid, "direction": "in", "node": node,
                   "msg_kind": stored["kind"], "reply_to": stored["reply_to"],
                   "files": stored["files"], "quarantined": stored["quarantined"],
                   "status": "received", "created": jobs.now(), "delivered": delivered}
            if delivered:
                rec["delivered_at"] = jobs.now()
            if led.append(rec):
                new.append(stored)
                known[iid] = rec
            else:
                cur = led.get(iid)
                if cur is None or cur.get("direction") != "in":
                    reject(iid)  # lost the race to a non-inbound record: leave it on the node
                    continue
                known[iid] = cur
            ack.append(iid)
        if ack:
            c.call("ack", ids=ack)

    try:
        if not delivered:
            work()
        else:
            try:
                work()
            except Exception as exc:
                if not new:
                    raise
                return {"items": new, "rejected": rejected, "error": _error_text(exc)}
        return {"items": new, "rejected": rejected}
    finally:
        if progress is not None:
            progress.update(new=len(new), rejected=rejected, rejected_ids=list(rejected_ids))


def _poll_node(cfg: Any, node: str) -> Any:
    return _run(node, lambda c: fetch_node(cfg, node, c, delivered=True))


def claim_undelivered(cfg: Any, names: List[str]) -> List[dict]:
    """Mark the stored, undelivered inbound records of `names` as delivered and return them as
    poll items. The body is read from disk and masked again with the current hub patterns. A
    record without a `delivered` key predates the flag and is never claimed."""
    claimed = ledger_for(cfg).claim(
        lambda r: r.get("kind") == "message" and r.get("direction") == "in"
        and r.get("node") in names and r.get("delivered") is False,
        delivered=True, delivered_at=jobs.now())
    if not claimed:
        return []
    wh = Withheld.load(Path(cfg.withheld_patterns_file))

    def hide(v: Any) -> Any:
        return "(withheld)" if isinstance(v, str) and wh.name_hit(v) else v
    out = []
    for r in claimed:
        item = {"msg_id": r.get("id"), "node": r.get("node"), "kind": r.get("msg_kind"),
                "reply_to": hide(r.get("reply_to")),
                "files": [hide(f) for f in r.get("files", [])],
                "quarantined": r.get("quarantined", 0), "stored": True}
        p = threads.body_path(cfg, r)
        text = None
        if p is not None:
            try:
                text = p.read_text(encoding="utf-8")
            except (OSError, ValueError):
                text = None
        if text is None:
            item["body"] = ""
            item["body_missing"] = True
        else:
            item["body"] = store.mask_body(wh, text, r.get("msg_kind"))[0]
        out.append(item)
    return out


def poll(node: Optional[str] = None) -> dict:
    """Return new node items (replies and events), each one once.

    Argument: node (a configured node name; omit for all nodes). Bodies are masked on the node and
    checked again on the hub before being returned; stored bodies are masked again with the
    current patterns. Items that `rb sync` stored earlier are included (`stored: true`).
    Note that each item is returned by one poll only, however it arrived. Result: {"items": [{"msg_id", "node",
    "kind", "reply_to", "body", "files", "quarantined"}], "errors": {node or "ledger": text}};
    "errors" is present only when something failed, and a node that could not be reached still
    yields its stored items. A stored body that is missing on disk gives body "" and
    body_missing true. Raises ValueError for an unknown node.
    """
    cfg = load_cfg()
    names = [node] if node else sorted(cfg.nodes)
    items: List[dict] = []
    errors: Dict[str, str] = {}
    for n in names:
        cfg.alias(n)
    for n in names:
        try:
            r = _poll_node(cfg, n)
        except TimeoutError:
            errors["ledger"] = "ledger_locked"
            continue
        except Exception:  # a malformed node result must not skip the claim below
            errors[n] = "internal"
            continue
        if not isinstance(r, dict):
            errors[n] = "internal"
            continue
        items.extend(r.get("items", []))
        if "error" in r:
            errors[n] = r["error"]
    try:
        items.extend(claim_undelivered(cfg, names))
    except TimeoutError:
        errors["ledger"] = "ledger_locked"
    out: Dict[str, Any] = {"items": items}
    if errors:
        out["errors"] = errors
    return out


def thread(msg_id: str) -> List[dict]:
    """Ledger records for a message and its direct replies (one level).

    Argument: msg_id (an outgoing or incoming message id). Returns a list of records (id, kind,
    direction, node, reply_to, status, created, ...). Each row also has `has_body` (a stored body
    file exists) and `stored_dir` (absolute path of the folder under inbox/ or outbox/, or null);
    read body.txt there with a file tool. Bodies are never in the ledger.
    """
    cfg = load_cfg()
    wh = Withheld.load(Path(cfg.withheld_patterns_file))
    rows = []
    for r in ledger_for(cfg).thread(msg_id):
        d = threads.stored_dir(cfg, r)
        for k in ("reply_to",):
            if isinstance(r.get(k), str) and wh.name_hit(r[k]):
                r = dict(r, **{k: "(withheld)"})
        if isinstance(r.get("files"), list):
            r = dict(r, files=["(withheld)" if isinstance(f, str) and wh.name_hit(f) else f
                               for f in r["files"]])
        rows.append(dict(r, has_body=threads.body_path(cfg, r) is not None,
                         stored_dir=str(d) if d is not None else None))
    return rows


def read_doc(node: str, ref: str) -> dict:
    """Read a hypothesis or experiment document through the node's read policy.

    Arguments: node (configured node name); ref (an id such as H-123 or EXP-015, or a path
    relative to a read root set in the node configuration). Lines that match a withheld pattern are
    blanked on the node and again on the hub with the hub's patterns (`hub_withheld_lines` counts
    the hub's blanks). Returns the node's result ({"text", ...}) or {"error": code} such as
    "not_found" or "denied". Raises ValueError for an unknown node.
    """
    args = {"id": ref} if _DOC_ID.match(ref) else {"path": ref}
    res = _run(node, lambda c: c.call("read_doc", **args))
    if isinstance(res, dict) and isinstance(res.get("text"), str):
        # the hub checks again with its own patterns (hard rule 3), as it does for poll bodies
        text, n = Withheld.load(Path(load_cfg().withheld_patterns_file)).mask_text(res["text"])
        res = dict(res, text=text, hub_withheld_lines=n)
    return res


def fetch_file(node: str, path: str) -> dict:
    """Download a node file through the node's read policy and check it again on the hub.

    Arguments: node (configured node name); path (relative to a node read root). Returns
    {"path": local file, "sha256"} or {"error": code}; codes include "bad_name", "denied",
    "withheld" (the file matched a pattern and was deleted) and the node's codes. A file named
    CLAUDE.md, AGENTS.md or starting with a dot is stored with ".untrusted" appended, so no session
    loads it as instructions. Raises ValueError for an unknown node.
    """
    cfg = load_cfg()
    cfg.alias(node)
    if not valid_remote_name(_remote_name(path)):
        return {"error": "bad_name"}  # PM-06: nothing is requested or written
    dest = Path(cfg.data_root) / "fetched" / node / _safe_name(path)
    if not _within(dest, Path(cfg.data_root) / "fetched" / node):
        return {"error": "bad_name"}
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
    """Read the node's job queue (read-only).

    Argument: node (configured node name). Returns {"entries": [{"name", "mtime", "state"}],
    "withheld_entries"} or {"error": text}. A job name that matches a withheld pattern (on the
    node, or again on the hub) is returned as "(withheld)"; withheld_entries counts them.
    Raises ValueError for an unknown node.
    """
    res = _run(node, lambda c: c.call("queue_status"))
    if not isinstance(res, dict) or "error" in res:
        return res
    wh = Withheld.load(Path(load_cfg().withheld_patterns_file))
    entries, hidden = [], 0
    for e in res.get("entries", []):
        if not isinstance(e, dict):
            continue
        name = e.get("name")
        if not isinstance(name, str) or name == "(withheld)" or wh.name_hit(name):
            e = dict(e, name="(withheld)")
            hidden += 1
        entries.append(e)
    return {"entries": entries, "withheld_entries": hidden}


def gpu_status(node: str) -> dict:
    """Read the node's GPU usage (read-only).

    Argument: node (configured node name). Returns {"gpus": [{"index", "name", "memory_used",
    "memory_total", "utilization"}]}; when the GPU tool cannot be read the result also has an
    "error" text. Failure to reach the node gives {"error": text}. Raises ValueError for an
    unknown node.
    """
    return _run(node, lambda c: c.call("gpu_status"))


def submit_job(node: str, config_path: str, gpus: List[int], gpu_hours: float,
               idempotency_key: str, note: str = "") -> dict:
    """Request a job. This only creates a pending_approval record; nothing is sent to the node.

    Arguments: node; config_path (local job config file); gpus (GPU indices); gpu_hours (budget);
    idempotency_key (the same key returns the same job); note (free text). Returns {"job_id",
    "status": "pending_approval"}. The user approves or rejects it with `rb approve <job_id>` in a
    hub terminal, where the approval passphrase is typed; no tool can approve. Raises ValueError
    for an unknown node, an empty idempotency_key, a missing config file, a gpus value that is not
    a non-empty list of distinct non-negative integers, or a gpu_hours that is not a number with
    0 < gpu_hours <= 168. Whether the GPUs exist and are allowed on the node is checked by the
    node after approval; a refusal then returns the job to pending_approval.
    """
    cfg = load_cfg()
    rec = jobs.create_submit(ledger_for(cfg), cfg, node, config_path, gpus, gpu_hours,
                             idempotency_key, note)
    return {"job_id": rec["id"], "status": rec["status"]}


def cancel_job(node: str, job_id: str, idempotency_key: str) -> dict:
    """Request a job cancel. This only creates a pending_approval record; nothing is sent.

    Arguments: node; job_id (the node's job id; a job started on the node console is not in the
    hub ledger and can be named too); idempotency_key (the same key returns the same request).
    Returns {"job_id": the cancel request id, "status": "pending_approval"}. The user approves
    with `rb approve <id>` in a hub terminal; no tool can approve. Raises ValueError for an unknown
    node or an empty idempotency_key. The job id is not checked on the hub: the node answers
    not_found after approval when it has no pending or running job with that id.
    """
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
