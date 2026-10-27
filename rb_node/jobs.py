"""Budgeted job submission and cancellation (stdlib only)."""
from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path
from typing import Any, List, Optional, Set

from .config import NodeConfig
from .mailbox import Mailbox, _check_id, _mkdir, _read_json, _write_json
from .protocol import ProtocolError

CONFIG_EXT = (".yaml", ".yml", ".json")
MAX_GPU_HOURS = 168
_NUM_RE = re.compile(r"^(\d+)_")


def _invalid(msg: str) -> ProtocolError:
    return ProtocolError("invalid", msg)


def _idem_path(state: Path) -> Path:
    return state / "idempotency.json"


def _idem_load(state: Path) -> dict:
    try:
        return _read_json(_idem_path(state))
    except (OSError, ValueError):
        return {}


def _idem_lookup(state: Path, key: str, op: str) -> Optional[dict]:
    entry = _idem_load(state).get(key)
    if entry is None:
        return None
    if entry.get("op") != op:
        raise ProtocolError("conflict", "idempotency_key already used by another op")
    return entry["result"]


def _idem_store(state: Path, key: str, op: str, result: dict) -> None:
    data = _idem_load(state)
    data[key] = {"op": op, "result": result}
    _write_json(_idem_path(state), data)  # tmp + os.replace


def _key(args: dict) -> str:
    key = args.get("idempotency_key")
    if not isinstance(key, str) or not key:
        raise ProtocolError("bad_args", "missing or invalid argument: idempotency_key")
    return key


def _str(args: dict, name: str) -> str:
    v = args.get(name)
    if not isinstance(v, str) or not v:
        raise ProtocolError("bad_args", "missing or invalid argument: %s" % name)
    return v


def validate_budget(args: dict, known_gpus: Optional[Set[int]]) -> None:
    gpus = args.get("gpus")
    if not isinstance(gpus, list) or not gpus or not all(
            isinstance(g, int) and not isinstance(g, bool) and g >= 0 for g in gpus):
        raise _invalid("gpus must be a non-empty list of non-negative ints")
    if len(set(gpus)) != len(gpus):
        raise _invalid("gpus must be distinct")
    if known_gpus and not set(gpus) <= known_gpus:
        raise _invalid("unknown gpu index")
    h = args.get("gpu_hours")
    if isinstance(h, bool) or not isinstance(h, (int, float)) or not (0 < h <= MAX_GPU_HOURS):
        raise _invalid("gpu_hours must satisfy 0 < gpu_hours <= %d" % MAX_GPU_HOURS)


def _next_number(queue: Path) -> int:
    top = 0
    for sub in ("jobs", "processing", "done", "failed"):
        d = queue / sub
        if not d.is_dir():
            continue
        for p in d.iterdir():
            m = _NUM_RE.match(p.name)
            if m:
                top = max(top, int(m.group(1)))
    return top + 1


def _finalize_config(cfg: NodeConfig, mb: Mailbox, job_id: str, config_name: str,
                     sha256: str) -> Path:
    """Verify the uploaded config (msg_id job-<id>) and move it to its stored path.

    The upload is deliberately not committed through msg_commit (no responder trigger).
    """
    msg_id = "job-" + job_id
    msg_dir = mb.root / "in" / _check_id(msg_id)
    try:
        rec = _read_json(msg_dir / "message.json")
    except (OSError, ValueError):
        raise ProtocolError("no_message", "config not uploaded")
    entry = None
    for e in rec.get("attachments", []):
        if e.get("original") == config_name:
            entry = e
    if entry is None:
        raise ProtocolError("no_attachment", "config not in upload")
    if entry["sha256"] != sha256.lower():
        raise ProtocolError("checksum", "config_sha256 does not match upload")
    att = msg_dir / "attachments"
    if not (att / entry["name"]).is_file():
        part = att / (entry["name"] + ".part")
        if not part.is_file():
            raise ProtocolError("no_part", "config not uploaded")
        if part.stat().st_size != entry["bytes"]:
            raise ProtocolError("incomplete", "config incomplete")
        mb.commit_part(msg_id, "in", entry["name"], entry["sha256"])
    dest_dir = mb.root / "state" / "configs" / job_id
    _mkdir(dest_dir)
    dest = dest_dir / entry["name"]
    os.replace(str(att / entry["name"]), str(dest))
    return dest


def submit(cfg: NodeConfig, mb: Mailbox, args: dict, known_gpus: Optional[Set[int]]) -> dict:
    state = mb.root / "state"
    key = _key(args)
    prior = _idem_lookup(state, key, "job_submit")
    if prior is not None:
        return prior
    job_id = _check_id(_str(args, "job_id"))
    config_name = _str(args, "config_name")
    sha = _str(args, "config_sha256")
    if os.path.splitext(config_name)[1].lower() not in CONFIG_EXT:
        raise _invalid("config must be one of %s" % ", ".join(CONFIG_EXT))
    validate_budget(args, known_gpus)
    if not cfg.job_template:
        raise ProtocolError("no_job_template", "node has no job_template configured")
    config_path = _finalize_config(cfg, mb, job_id, config_name, sha)
    gpus = args["gpus"]
    argv = ["rb-node", "run-job", "--gpus", ",".join(str(g) for g in gpus),
            "--gpu-hours", str(args["gpu_hours"]), "--job-id", job_id, "--"]
    argv += [t.replace("{config}", str(config_path)) for t in cfg.job_template]
    body = "#!/bin/bash\nexec %s\n" % " ".join(shlex.quote(a) for a in argv)
    queue = Path(cfg.queue_dir)
    jobs_dir = queue / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    target = jobs_dir / ("%04d_%s.job" % (_next_number(queue), job_id))
    tmp = jobs_dir / (target.name + ".tmp")  # not *.job, so the runner never claims it half-written
    with open(str(tmp), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(body)
    os.replace(str(tmp), str(target))
    result = {"queued": str(target)}
    _idem_store(state, key, "job_submit", result)
    return result


def cancel(cfg: NodeConfig, mb: Mailbox, args: dict) -> dict:
    state = mb.root / "state"
    key = _key(args)
    prior = _idem_lookup(state, key, "job_cancel")
    if prior is not None:
        return prior
    job_id = _check_id(_str(args, "job_id"))
    queue = Path(cfg.queue_dir)
    result = None  # type: Any
    pending = sorted((queue / "jobs").glob("*_%s.job" % job_id)) if (queue / "jobs").is_dir() else []
    if pending:
        for p in pending:
            p.unlink()
        _mkdir(state / "jobs")
        _write_json(state / "jobs" / (job_id + ".json"), {"job_id": job_id, "status": "cancelled"})
        result = {"cancelled": "pending"}
    else:
        running = (queue / "processing").is_dir() and any(
            (queue / "processing").glob("*_%s.job*" % job_id))
        rec_path = state / "jobs" / (job_id + ".json")
        if not running and rec_path.is_file():
            try:
                running = _read_json(rec_path).get("status") == "running"
            except (OSError, ValueError):
                running = False
        if not running:
            raise ProtocolError("not_found", "no pending or running job with that id")
        _mkdir(state / "cancel")
        (state / "cancel" / job_id).write_text("cancel\n", encoding="utf-8")
        result = {"cancelled": "requested"}
    _idem_store(state, key, "job_cancel", result)
    return result
