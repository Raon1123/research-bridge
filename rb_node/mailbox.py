"""File-backed mailbox: in/ (host to node), out/ (node to host), state/ (stdlib only)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import BinaryIO, Dict, List, Optional, Set, Tuple

from .protocol import CHUNK, MAX_FILE, ProtocolError

STATUSES = ("new", "responding", "answered", "failed")
KINDS = ("reply", "event")
BOXES = ("in", "out")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _check_id(value: str) -> str:
    if not isinstance(value, str) or not _ID_RE.match(value) or value.endswith("."):
        raise ProtocolError("bad_id", "invalid id")
    return value


def _check_box(box: str) -> str:
    if box not in BOXES:
        raise ProtocolError("bad_box", "box must be in or out")
    return box


def _mkdir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(str(p), 0o700)
    except OSError:
        pass


def _chmod_file(p: Path) -> None:
    try:
        os.chmod(str(p), 0o600)
    except OSError:
        pass


def _write_json(path: Path, obj: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    _chmod_file(tmp)
    os.replace(str(tmp), str(path))


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class Mailbox:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        for d in (self.root, self.root / "in", self.root / "out", self.root / "state",
                  self.root / "state" / "acked"):
            _mkdir(d)

    # -- names -------------------------------------------------------------
    @staticmethod
    def sanitize(name: str, taken: Set[str]) -> str:
        base = re.split(r"[\\/]", name)[-1]
        base = "".join(c for c in base if ord(c) >= 32 and ord(c) != 127).strip()
        if base in ("", ".", ".."):
            base = "attachment"
        if base not in taken:
            return base
        stem, ext = os.path.splitext(base)
        if not stem:  # dotfile such as ".bashrc"
            stem, ext = base, ""
        n = 2
        while "%s-%d%s" % (stem, n, ext) in taken:
            n += 1
        return "%s-%d%s" % (stem, n, ext)

    # -- inbox / outbox directories ----------------------------------------
    def _item_dir(self, box: str, msg_id: str) -> Path:
        return self.root / _check_box(box) / _check_id(msg_id)

    def _att_dir(self, box: str, msg_id: str) -> Path:
        return self._item_dir(box, msg_id) / "attachments"

    def new_message(self, msg_id: str, meta: dict) -> Path:
        d = self._item_dir("in", msg_id)
        if (d / "message.json").exists():
            return d
        _mkdir(d)
        _mkdir(d / "attachments")
        record = dict(meta)
        record["id"] = msg_id
        record.setdefault("status", "new")
        _write_json(d / "message.json", record)
        return d

    # -- attachments -------------------------------------------------------
    def _names_path(self, box: str, msg_id: str) -> Path:
        return self._item_dir(box, msg_id) / "attachment_names.json"

    def attachment_names(self, msg_id: str, box: str) -> Dict[str, str]:
        """Map stored (sanitized) name to the original name as sent."""
        p = self._names_path(box, msg_id)
        try:
            return _read_json(p)
        except (OSError, ValueError):
            return {}

    def open_part(self, msg_id: str, box: str, name: str) -> Tuple[str, BinaryIO]:
        att = self._att_dir(box, msg_id)
        _mkdir(att)
        names = self.attachment_names(msg_id, box)
        taken = set(names) | {p.name for p in att.iterdir()}
        stored = self.sanitize(name, taken)
        names[stored] = name
        _write_json(self._names_path(box, msg_id), names)
        part = att / (stored + ".part")
        fh = open(str(part), "wb")
        _chmod_file(part)
        return stored, fh

    def commit_part(self, msg_id: str, box: str, name: str, sha256: str) -> None:
        att = self._att_dir(box, msg_id)
        part = att / (name + ".part")
        if "/" in name or "\\" in name or not part.is_file():
            raise ProtocolError("no_part", "no pending upload for %s" % name)
        h = hashlib.sha256()
        size = 0
        with open(str(part), "rb") as fh:
            for chunk in iter(lambda: fh.read(CHUNK), b""):
                h.update(chunk)
                size += len(chunk)
        if size > MAX_FILE:
            part.unlink()
            raise ProtocolError("too_large", "attachment exceeds %d bytes" % MAX_FILE)
        if h.hexdigest() != str(sha256).lower():
            part.unlink()
            raise ProtocolError("checksum", "sha256 mismatch for %s" % name)
        os.replace(str(part), str(att / name))

    # -- outbox ------------------------------------------------------------
    def post_out(self, kind: str, body: str, attachments: List[Path],
                 reply_to: Optional[str]) -> str:
        if kind not in KINDS:
            raise ProtocolError("bad_kind", "kind must be reply or event")
        out_id = "%020d-%s" % (time.time_ns(), uuid.uuid4().hex[:8])
        d = self._item_dir("out", out_id)
        att = d / "attachments"
        _mkdir(att)
        taken: Set[str] = set()
        entries = []
        for src in attachments:
            src = Path(src)
            stored = self.sanitize(src.name, taken)
            taken.add(stored)
            dest = att / stored
            shutil.copyfile(str(src), str(dest))
            _chmod_file(dest)
            entries.append({"name": stored, "original": src.name})
        _write_json(d / "message.json", {
            "id": out_id, "kind": kind, "body": body,
            "reply_to": reply_to, "attachments": entries,
        })
        return out_id

    def undelivered(self) -> List[dict]:
        acked = self.root / "state" / "acked"
        items = []
        for d in sorted((self.root / "out").iterdir()):
            if not d.is_dir() or (acked / d.name).exists():
                continue
            try:
                items.append(_read_json(d / "message.json"))
            except (OSError, ValueError):
                continue  # still being written
        return items

    def ack(self, ids: List[str]) -> None:
        acked = self.root / "state" / "acked"
        _mkdir(acked)
        for i in ids:
            marker = acked / _check_id(i)
            marker.touch()
            _chmod_file(marker)

    # -- inbox status ------------------------------------------------------
    def inbox(self, status: Optional[str] = None) -> List[dict]:
        items = []
        for d in sorted((self.root / "in").iterdir()):
            try:
                rec = _read_json(d / "message.json")
            except (OSError, ValueError):
                continue
            if status is None or rec.get("status") == status:
                items.append(rec)
        return items

    def set_status(self, msg_id: str, status: str) -> None:
        if status not in STATUSES:
            raise ProtocolError("bad_status", "unknown status %s" % status)
        path = self._item_dir("in", msg_id) / "message.json"
        try:
            rec = _read_json(path)
        except (OSError, ValueError):
            raise ProtocolError("no_message", "unknown message %s" % msg_id)
        rec["status"] = status
        _write_json(path, rec)
