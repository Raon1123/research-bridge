"""serve-remote: line-delimited JSON dispatcher over stdin/stdout (stdlib only)."""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, BinaryIO, Callable, Dict, List

from . import PROTOCOL, __version__, approval, doctor, gitinfo, jobs, spawn
from .audit import Audit
from .config import NodeConfig
from .mailbox import Mailbox, _check_id, _read_json
from .paths import PathPolicy, PolicyError
from .protocol import CHUNK, ProtocolError, encode, err, ok, read_message
from .withheld import Withheld

# Text documents whose withheld lines are blanked rather than the whole file denied.
MASK_EXT = {".md", ".txt", ".csv", ".json"}
QUEUE_STATES = ("jobs", "processing", "done", "failed")
_EXP_RE = re.compile(r"^EXP-\d+$")
_H_RE = re.compile(r"^H-\d+$")
_HEADING_RE = re.compile(r"^(#+)\s")


def _arg(args: dict, key: str, typ: type) -> Any:
    v = args.get(key)
    if not isinstance(v, typ) or (typ is int and isinstance(v, bool)):
        raise ProtocolError("bad_args", "missing or invalid argument: %s" % key)
    return v


class Node:
    def __init__(self, cfg: NodeConfig) -> None:
        self.cfg = cfg
        self.mb = Mailbox(Path(cfg.mailbox_root))
        self.policy = PathPolicy(Path(cfg.trm_root), list(cfg.read_roots), list(cfg.write_roots))
        src = Path(cfg.withheld_source) if cfg.withheld_source else None
        self.withheld = Withheld.load(src)
        self.audit = Audit(Path(cfg.audit_path))
        if src is not None and self.withheld.source_error:
            # Path and reason only, never pattern text. Fallback patterns stay active.
            self.audit.record(op="withheld_source", ok=False, source=str(src),
                              reason=self.withheld.source_error)
        self.ops = {
            "hello": self.hello, "msg_begin": self.msg_begin, "put_chunk": self.put_chunk,
            "msg_commit": self.msg_commit, "poll": self.poll, "ack": self.ack,
            "get_file": self.get_file, "read_doc": self.read_doc,
            "queue_status": self.queue_status, "gpu_status": self.gpu_status,
            "job_submit": self.job_submit, "job_cancel": self.job_cancel,
            "approve_params": self.approve_params, "git_status": self.git_status,
        }  # type: Dict[str, Callable[[dict], Any]]

    # -- messages ----------------------------------------------------------
    def hello(self, args: dict) -> dict:
        return {"node": socket.gethostname(), "version": __version__,
                "withheld_extra": self.withheld.extra_count,
                "protocol": PROTOCOL, "ops": sorted(self.ops),
                "state": doctor.state(self.cfg, self.withheld)}

    def _msg_dir(self, msg_id: str) -> Path:
        return self.mb.root / "in" / _check_id(msg_id)

    def _rec(self, msg_id: str) -> dict:
        try:
            return _read_json(self._msg_dir(msg_id) / "message.json")
        except (OSError, ValueError):
            raise ProtocolError("no_message", "unknown message")

    def msg_begin(self, args: dict) -> dict:
        msg_id = _check_id(_arg(args, "msg_id", str))
        body = _arg(args, "body", str)
        atts = args.get("attachments", [])
        if not isinstance(atts, list):
            raise ProtocolError("bad_args", "attachments must be a list")
        for a in atts:
            if not (isinstance(a, dict) and isinstance(a.get("name"), str)
                    and isinstance(a.get("bytes"), int) and isinstance(a.get("sha256"), str)):
                raise ProtocolError("bad_args", "invalid attachment entry")
            if a["bytes"] > self.cfg.max_file:
                raise ProtocolError("too_large", "attachment exceeds %d bytes" % self.cfg.max_file)
        if (self._msg_dir(msg_id) / "message.json").exists():  # retry with the same id
            rec = self._rec(msg_id)
            old = rec.get("attachments", [])
            if len(old) != len(atts) or any(
                    o["original"] != a["name"] or o["sha256"] != a["sha256"].lower()
                    or o["bytes"] != a["bytes"] for o, a in zip(old, atts)):
                raise ProtocolError("conflict", "msg_id already used with different content")
            return {"names": [o["name"] for o in old]}
        taken = set()  # type: set
        entries = []
        for a in atts:
            stored = Mailbox.sanitize(a["name"], taken)
            taken.add(stored)
            entries.append({"name": stored, "original": a["name"], "bytes": a["bytes"],
                            "sha256": a["sha256"].lower()})
        self.mb.new_message(msg_id, {
            "body": body, "from_session": args.get("from_session"), "status": "uploading",
            "attachments": entries, "received": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
        return {"names": [e["name"] for e in entries]}

    def _entry(self, rec: dict, name: str) -> dict:
        for e in rec.get("attachments", []):
            if e["name"] == name:
                return e
        raise ProtocolError("no_attachment", "unknown attachment name")

    def put_chunk(self, args: dict) -> dict:
        msg_id = _check_id(_arg(args, "msg_id", str))
        name = _arg(args, "name", str)
        seq = _arg(args, "seq", int)
        try:
            data = base64.b64decode(_arg(args, "data_b64", str), validate=True)
        except (binascii.Error, ValueError):
            raise ProtocolError("bad_b64", "invalid base64")
        entry = self._entry(self._rec(msg_id), name)
        att = self._msg_dir(msg_id) / "attachments"
        if (att / entry["name"]).is_file():
            return {"written": 0}  # already committed; retry is a no-op
        part = att / (entry["name"] + ".part")
        if seq < 0:
            raise ProtocolError("bad_seq", "negative seq")
        if seq == 0:
            mode, offset = "wb", 0
        else:
            offset = seq * CHUNK
            if not part.is_file() or part.stat().st_size != offset:
                raise ProtocolError("bad_seq", "chunk out of order")
            mode = "ab"
        if offset + len(data) > min(entry["bytes"], self.cfg.max_file):
            if part.is_file():
                part.unlink()
            raise ProtocolError("too_large", "upload exceeds declared size")
        att.mkdir(parents=True, exist_ok=True)
        with open(str(part), mode) as fh:
            fh.write(data)
        try:
            os.chmod(str(part), 0o600)
        except OSError:
            pass
        return {"written": len(data)}

    def msg_commit(self, args: dict) -> dict:
        msg_id = _check_id(_arg(args, "msg_id", str))
        rec = self._rec(msg_id)
        att = self._msg_dir(msg_id) / "attachments"
        for e in rec.get("attachments", []):
            if (att / e["name"]).is_file():
                continue
            part = att / (e["name"] + ".part")
            if not part.is_file():
                raise ProtocolError("no_part", "attachment not uploaded: %s" % e["name"])
            if part.stat().st_size != e["bytes"]:
                raise ProtocolError("incomplete", "attachment incomplete: %s" % e["name"])
            self.mb.commit_part(msg_id, "in", e["name"], e["sha256"])
        triggered = False
        if rec.get("status") == "uploading":
            self.mb.set_status(msg_id, "new")
            # Job uploads (job- prefix) are handled by the job ops, not the responder.
            if not msg_id.startswith("job-"):
                try:
                    spawn.trigger(self.cfg, msg_id)
                    triggered = True
                except Exception as exc:  # message stays "new"
                    self.audit.record(op="spawn_trigger", msg_id=msg_id, ok=False,
                                      code=type(exc).__name__)
        return {"status": "new", "triggered": triggered}

    def poll(self, args: dict) -> dict:
        # Single egress point for out/ items. Items are stored raw by post_out and masked here
        # with the current patterns, so a pattern added later also covers older items.
        items = []
        for it in self.mb.undelivered():
            it = dict(it)
            body = it.get("body")
            if isinstance(body, str):
                it["body"], n = self.withheld.mask_text(body)
                it["withheld_lines"] = n
                if n and not it["body"].strip() and it.get("kind") == "event":
                    it["body"] = json.dumps({"event": "withheld", "withheld_lines": n})
            rt = it.get("reply_to")
            if isinstance(rt, str) and self.withheld.name_hit(rt):
                it["reply_to"] = None
            kept, dropped = [], 0
            for a in it.get("attachments", []) or []:
                names = [a.get(k) for k in ("name", "original")] if isinstance(a, dict) else []
                if any(isinstance(x, str) and self.withheld.name_hit(x) for x in names):
                    dropped += 1
                else:
                    kept.append(a)
            if "attachments" in it:
                it["attachments"] = kept
            it["withheld_attachments"] = dropped
            items.append(it)
        return {"items": items}

    def ack(self, args: dict) -> dict:
        ids = _arg(args, "ids", list)
        if not all(isinstance(i, str) for i in ids):
            raise ProtocolError("bad_args", "ids must be strings")
        self.mb.ack(ids)
        return {"acked": len(ids)}

    # -- documents ---------------------------------------------------------
    def _doc_path(self, ref: str) -> Path:
        p = self.policy.resolve_read(ref)
        if self.withheld.name_hit(str(p)):
            raise PolicyError("withheld")
        if not p.is_file():
            raise ProtocolError("not_found", "no such document")
        return p

    def _bytes_for(self, p: Path) -> bytes:
        """File bytes as they may leave the node: text masked; everything else must pass check_file."""
        if p.stat().st_size > self.cfg.max_file:
            raise ProtocolError("too_large", "file exceeds %d bytes" % self.cfg.max_file)
        if p.suffix.lower() in MASK_EXT:
            text, _n = self.withheld.mask_text(p.read_bytes().decode("utf-8", "replace"))
            return text.encode("utf-8")
        if self.withheld.check_file(p) != "ok":
            raise PolicyError("withheld")
        return p.read_bytes()

    def get_file(self, args: dict) -> dict:
        kind = _arg(args, "kind", str)
        ref = _arg(args, "ref", str)
        seq = _arg(args, "seq", int)
        if kind == "doc":
            p = self._doc_path(ref)
        elif kind == "out":
            parts = ref.split("/")
            if len(parts) != 2 or parts[1] in ("", ".", "..") or "\\" in parts[1]:
                raise PolicyError("bad out ref")
            _check_id(parts[0])
            p = self.mb.root / "out" / parts[0] / "attachments" / parts[1]
            if self.withheld.name_hit(str(p)):
                raise PolicyError("withheld")
            if not p.is_file():
                raise ProtocolError("not_found", "no such file")
        else:
            raise ProtocolError("bad_args", "kind must be out or doc")
        data = self._bytes_for(p)
        if seq < 0 or (seq > 0 and seq * CHUNK >= len(data)):
            raise ProtocolError("bad_seq", "seq out of range")
        chunk = data[seq * CHUNK:(seq + 1) * CHUNK]
        eof = (seq + 1) * CHUNK >= len(data)
        res = {"data_b64": base64.b64encode(chunk).decode("ascii"), "eof": eof}  # type: dict
        if eof:
            res["sha256"] = hashlib.sha256(data).hexdigest()
        return res

    def _h_section(self, text: str, hid: str) -> str:
        lines = text.split("\n")
        pat = re.compile(r"(?<![\w-])%s(?!\d)" % re.escape(hid))
        start, level = -1, 0
        for i, line in enumerate(lines):
            m = _HEADING_RE.match(line)
            if m and pat.search(line):
                start, level = i, len(m.group(1))
                break
        if start < 0:
            raise ProtocolError("not_found", "no section for %s" % hid)
        end = len(lines)
        for j in range(start + 1, len(lines)):
            m = _HEADING_RE.match(lines[j])
            if m and len(m.group(1)) <= level:
                end = j
                break
        return "\n".join(lines[start:end])

    def _exp_ref(self, did: str) -> str:
        """EXP-015.md, or EXP-015_<slug>.md as in the 2026-10 layout (exactly one match)."""
        base = self.cfg.experiments_dir.rstrip("/")
        d = Path(self.cfg.trm_root) / base
        hits = sorted(p.name for p in d.glob(did + ".md")) or sorted(
            p.name for p in d.glob(did + "_*.md")) if d.is_dir() else []
        if len(hits) != 1:
            raise ProtocolError("not_found", "no unique document for %s" % did)
        return "%s/%s" % (base, hits[0])

    def read_doc(self, args: dict) -> dict:
        if isinstance(args.get("id"), str):
            did = args["id"]
            if _EXP_RE.match(did):
                p = self._doc_path(self._exp_ref(did))
                text = p.read_bytes().decode("utf-8", "replace")
            elif _H_RE.match(did):
                p = self._doc_path(self.cfg.hypotheses_path)
                text = self._h_section(p.read_bytes().decode("utf-8", "replace"), did)
            else:
                raise ProtocolError("bad_id", "id must look like H-123 or EXP-015")
        else:
            p = self._doc_path(_arg(args, "path", str))
            if p.suffix.lower() not in MASK_EXT | {".tex"}:
                raise PolicyError("not a text document")
            if p.suffix.lower() == ".tex" and self.withheld.check_file(p) != "ok":
                raise PolicyError("withheld")  # same rule as get_file (hard rule 3)
            text = p.read_bytes().decode("utf-8", "replace")
        if len(text) > self.cfg.max_file:
            raise ProtocolError("too_large", "document too large")
        masked, n = self.withheld.mask_text(text)
        return {"text": masked, "withheld_lines": n}

    # -- status ------------------------------------------------------------
    def queue_status(self, args: dict) -> dict:
        # Job file names carry run names, so they leave the node only after the withheld check
        # (hard rule 3): a hit keeps its state and mtime, the name becomes "(withheld)".
        entries = []  # type: List[dict]
        hidden = 0
        for state in QUEUE_STATES:
            d = Path(self.cfg.queue_dir) / state
            if not d.is_dir():
                continue
            found = []
            for p in d.iterdir():
                try:
                    found.append((p.stat().st_mtime, p.name))
                except OSError:
                    continue
            found.sort(reverse=True)
            for mtime, name in found[:200]:
                if self.withheld.name_hit(name):
                    name = "(withheld)"
                    hidden += 1
                entries.append({"name": name, "mtime": mtime, "state": state})
        return {"entries": entries, "withheld_entries": hidden}

    def gpu_status(self, args: dict) -> dict:
        exe = shutil.which("nvidia-smi")
        if not exe:
            return {"gpus": [], "error": "nvidia-smi not found"}
        try:
            r = subprocess.run(
                [exe, "--query-gpu=index,name,memory.used,memory.total,utilization.gpu",
                 "--format=csv,noheader,nounits"],
                timeout=15, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except (OSError, subprocess.SubprocessError):
            return {"gpus": [], "error": "nvidia-smi failed"}
        if r.returncode != 0:
            return {"gpus": [], "error": "nvidia-smi failed"}
        gpus = []
        for line in r.stdout.decode("utf-8", "replace").splitlines():
            f = [x.strip() for x in line.split(",")]
            if len(f) != 5:
                continue
            try:
                gpus.append({"index": int(f[0]), "name": f[1], "memory_used": int(f[2]),
                             "memory_total": int(f[3]), "utilization": int(f[4])})
            except ValueError:
                continue
        return {"gpus": gpus}

    # -- jobs --------------------------------------------------------------
    def job_submit(self, args: dict) -> dict:
        st = self.gpu_status({})
        # None = could not read (jobs.submit -> gpu_status_unavailable); empty set = read, zero GPUs.
        known = None if st.get("error") else {g["index"] for g in st.get("gpus", [])}
        return jobs.submit(self.cfg, self.mb, args, known)

    def job_cancel(self, args: dict) -> dict:
        return jobs.cancel(self.cfg, self.mb, args)

    def git_status(self, args: dict) -> dict:
        """Read-only git state of trm_root and of the installed rb_node (no names, no diffs)."""
        trm = gitinfo.mask_state(gitinfo.repo_state(Path(self.cfg.trm_root)), self.withheld)
        inst = gitinfo.read_install(Path(self.cfg.mailbox_root).parent)
        if inst and isinstance(inst.get("source"), dict):
            inst = dict(inst, source=gitinfo.mask_state(inst["source"], self.withheld))
        return {"trm": trm, "install": inst}

    def approve_params(self, args: dict) -> dict:
        approval.require_safe_path(self.cfg)
        return approval.params(Path(self.cfg.approval_path))

    # -- dispatch ----------------------------------------------------------
    def handle(self, msg: dict) -> dict:
        rid = msg.get("id")
        rid = rid if isinstance(rid, str) else str(rid or "")
        op = msg.get("op")
        args = msg.get("args", {})
        fields = {"id": rid, "op": op if isinstance(op, str) else None}  # type: Dict[str, Any]
        try:
            fn = self.ops.get(op) if isinstance(op, str) else None
            if fn is None:
                raise ProtocolError("unknown_op", "unknown op")
            if not isinstance(args, dict):
                raise ProtocolError("bad_args", "args must be an object")
            for k in ("msg_id", "name"):
                if isinstance(args.get(k), str):
                    fields[k] = args[k]
            result = fn(args)
            fields["ok"] = True
            resp = ok(rid, result)
        except ProtocolError as exc:
            fields.update(ok=False, code=exc.code)
            resp = err(rid, exc.code, str(exc))
        except PolicyError:
            fields.update(ok=False, code="denied")
            resp = err(rid, "denied", "denied")
        except OSError as exc:
            fields.update(ok=False, code="io_error")
            resp = err(rid, "io_error", type(exc).__name__)
        except Exception as exc:  # never echo details that might hold document text
            fields.update(ok=False, code="internal")
            resp = err(rid, "internal", type(exc).__name__)
        self.audit.record(**fields)
        return resp


class Unconfigured:
    """Answers `hello` when node.json is missing or invalid. Writes nothing, creates nothing."""

    def handle(self, msg: dict) -> dict:
        rid = msg.get("id")
        rid = rid if isinstance(rid, str) else str(rid or "")
        if msg.get("op") == "hello":
            return ok(rid, {"node": socket.gethostname(), "version": __version__,
                            "withheld_extra": 0, "protocol": PROTOCOL, "ops": ["hello"],
                            "state": {"configured": False}})
        return err(rid, "not_configured", "node.json missing or invalid")


def _loop(node: Any, stdin: BinaryIO, stdout: BinaryIO) -> int:
    while True:
        try:
            msg = read_message(stdin)
        except ProtocolError as exc:
            stdout.write(encode(err("", exc.code, str(exc))))
            stdout.flush()
            if exc.code == "line_too_long":
                return 1  # stream position is unreliable after an oversized line
            continue
        if msg is None:
            return 0
        stdout.write(encode(node.handle(msg)))
        stdout.flush()


def serve(cfg: NodeConfig, stdin: BinaryIO, stdout: BinaryIO) -> int:
    return _loop(Node(cfg), stdin, stdout)


def serve_unconfigured(stdin: BinaryIO, stdout: BinaryIO) -> int:
    return _loop(Unconfigured(), stdin, stdout)
