"""Store polled node items on the laptop, re-checking withheld patterns."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict

from rb_node.withheld import Withheld

from .client import RemoteError
from .config import HostConfig


# Names a laptop Claude session may load as instructions (SEC-02). Node-supplied files with
# these names, or any dot-name, are stored with UNTRUSTED appended so nothing loads them.
INSTRUCTION_NAMES = frozenset(["claude.md", "claude.local.md", "agents.md"])
UNTRUSTED = ".untrusted"


def untrusted_name(base: str) -> str:
    """Local name for one node-supplied path component (SEC-02, PM-06)."""
    base = base.replace(":", "_")  # drive letters (C:x) and NTFS alternate streams
    if base.rstrip(" .").lower() in INSTRUCTION_NAMES or base.startswith("."):
        return base + UNTRUSTED  # Windows drops trailing dots and spaces, so check without them
    return base


# Windows device names are reserved with or without an extension (PM-06).
_RESERVED = re.compile(r"^(con|prn|aux|nul|conin\$|conout\$|(com|lpt)[1-9¹²³])$",
                       re.IGNORECASE)
_BAD_CHARS = re.compile(r'[\x00-\x1f<>:"/\|?*]')
_OWN_FILES = frozenset(["body.txt", "provenance.json"])
_MSG_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]*$")


def valid_remote_name(name: str) -> bool:
    """True when a node-supplied basename is safe to turn into a local file name (PM-06).

    Rejects drive letters and stream syntax (colon), control and wildcard characters,
    Windows device names (CON, NUL, COM1, ... with or without extension) and names that
    end in a dot or space (Windows drops those, so two names could collide).
    Dot-names and instruction file names are valid here; SEC-02 renames them afterwards.
    """
    if not name or name in (".", "..") or _BAD_CHARS.search(name):
        return False
    if name.endswith((".", " ")) and untrusted_name(name) == name:
        return False
    return not _RESERVED.match(name.split(".", 1)[0].rstrip(" "))


def valid_msg_id(msg_id: str) -> bool:
    """Message ids become directory names: conservative ASCII, no device names (PM-06)."""
    return bool(_MSG_ID.fullmatch(msg_id)) and not msg_id.endswith((".", " ")) \
        and not _RESERVED.match(msg_id.split(".", 1)[0].rstrip(" "))


def _within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def _remote_name(name: str) -> str:
    base = str(name).replace("\\", "/").rsplit("/", 1)[-1]
    return base if base not in ("", ".", "..") else "unnamed"


def _safe_name(name: str) -> str:
    """Local file name for a node-supplied name: basename only, never an instruction file."""
    return untrusted_name(_remote_name(name))


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(str(path), "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def store_incoming(cfg: HostConfig, node: str, item: dict, client: Any) -> dict:
    """Fetch and check one polled item. Files that fail go to quarantine/, never inbox/.

    provenance.json (in the inbox dir) never contains the name of a quarantined file,
    only its index; the real name exists only inside quarantine/.
    """
    wh = Withheld.load(Path(cfg.withheld_patterns_file))
    msg_id = str(item["id"])
    if not valid_msg_id(msg_id):
        raise ValueError("unsafe message id")
    root = Path(cfg.data_root)
    inbox = root / "inbox" / node / msg_id
    quar = root / "quarantine" / node / msg_id
    stage_dir = quar / ".stage"
    body, body_hits = wh.mask_text(str(item.get("body", "")))
    inbox.mkdir(parents=True, exist_ok=True)
    # the masked body is stored before the caller acks the item (PM-09)
    (inbox / "body.txt").write_text(body, encoding="utf-8")
    files = []  # type: list
    used = set()  # type: set
    for idx, att in enumerate(item.get("attachments", [])):
        remote = _remote_name(att.get("name", ""))
        name = untrusted_name(remote)
        entry = {"index": idx, "name": name, "status": "ok"}  # type: Dict[str, Any]
        if not valid_remote_name(remote) or not _within(inbox / name, inbox) \
                or not _within(quar / name, quar):
            # never fetched or written; the name itself is not recorded (PM-06)
            entry.update(status="quarantined", reason="bad_name")
            del entry["name"]
            files.append(entry)
            continue
        # never collide with the files this module writes, or with an earlier attachment
        if name.lower() in _OWN_FILES or name.lower() in used:
            name = "%d-%s" % (idx, name)
            entry["name"] = name
        used.add(name.lower())
        name_bad = wh.name_hit(remote) or wh.name_hit(str(att.get("original", "")))
        # keep the node's extension for check_file; the index prefix keeps it from being CLAUDE.md
        stage = stage_dir / ("%d-%s" % (idx, remote.replace(":", "_")))
        try:
            client.get_file("out", "%s/%s" % (msg_id, remote), stage)
        except RemoteError as exc:
            entry.update(status="quarantined", reason="node_denied" if exc.code == "denied"
                         else "fetch_" + exc.code)
            files.append(entry)
            continue
        verdict = "deny_name" if name_bad else wh.check_file(stage)
        if verdict == "ok":
            dest = inbox / name
        else:
            quar.mkdir(parents=True, exist_ok=True)
            dest = quar / name
            entry.update(status="quarantined", reason=verdict)
        shutil.move(str(stage), str(dest))
        entry["sha256"] = _sha(dest)
        entry["bytes"] = dest.stat().st_size
        files.append(entry)
    shutil.rmtree(str(stage_dir), ignore_errors=True)
    prov_files = []
    for f in files:
        pf = dict(f)
        if pf["status"] == "quarantined":
            pf.pop("name", None)  # the name itself may be the withheld content
        prov_files.append(pf)
    prov = {"node": node, "msg_id": msg_id,
            "received_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "body_withheld_lines": body_hits, "files": prov_files}
    (inbox / "provenance.json").write_text(json.dumps(prov, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
    return {"msg_id": msg_id, "node": node, "kind": item.get("kind"),
            "reply_to": item.get("reply_to"), "body": body,
            "files": [f["name"] for f in files if f["status"] == "ok"],
            "quarantined": sum(1 for f in files if f["status"] == "quarantined")}
