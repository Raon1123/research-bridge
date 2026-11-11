"""Store polled node items on the hub, re-checking withheld patterns."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from rb_node.withheld import Withheld

from .client import RemoteError
from .config import HostConfig


# Names a hub Claude session may load as instructions (SEC-02). Node-supplied files with
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


def mask_body(wh: Withheld, text: str, kind: Any) -> Any:
    """(masked text, blanked line count). An event whose body was blanked entirely becomes a
    `withheld` event, as on the node, so it stays an event (hard rule 7)."""
    body, n = wh.mask_text(text)
    if n and not body.strip() and kind == "event":
        body = json.dumps({"event": "withheld", "withheld_lines": n})
    return body, n


def store_incoming(cfg: HostConfig, node: str, item: dict, client: Any) -> dict:
    """Fetch and check one polled item. Files that fail go to quarantine/, never inbox/.

    provenance.json (in the inbox dir) never contains the name of a quarantined file,
    only its index; the real name exists only inside quarantine/.
    """
    # the shape is checked before anything is written, so a malformed item leaves nothing behind
    msg_id = item.get("id") if isinstance(item, dict) else None
    if not isinstance(msg_id, str) or not valid_msg_id(msg_id):
        raise ValueError("unsafe message id")
    atts = item.get("attachments", [])
    if not isinstance(atts, list) or not all(
            isinstance(a, dict) and isinstance(a.get("name", ""), str)
            and isinstance(a.get("original", ""), (str, type(None))) for a in atts):
        raise ValueError("malformed attachment list")
    wh = Withheld.load(Path(cfg.withheld_patterns_file))
    root = Path(cfg.data_root)
    inbox = root / "inbox" / node / msg_id
    quar = root / "quarantine" / node / msg_id
    stage_dir = quar / (".stage-%d-%s" % (os.getpid(), uuid.uuid4().hex[:8]))
    body, body_hits = mask_body(wh, str(item.get("body", "")), item.get("kind"))
    inbox.mkdir(parents=True, exist_ok=True)
    # the masked body is stored before the caller acks the item (PM-09)
    _atomic_write(inbox / "body.txt", body)
    files = []  # type: list
    used = set()  # type: set
    for idx, att in enumerate(atts):
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
        while name.lower() in _OWN_FILES or name.lower() in used:
            name = "%d-%s" % (idx, name)  # repeated until unique ("2-a.txt" may already exist)
            entry["name"] = name
        if not _within(inbox / name, inbox) or not _within(quar / name, quar):
            entry.update(status="quarantined", reason="bad_name")
            del entry["name"]
            files.append(entry)
            continue
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
    try:
        quar.rmdir()  # only succeeds when empty (nothing was quarantined)
    except OSError:
        pass
    prov_files = []
    for f in files:
        pf = dict(f)
        if pf["status"] == "quarantined":
            pf.pop("name", None)  # the name itself may be the withheld content
        prov_files.append(pf)
    prov = {"node": node, "msg_id": msg_id,
            "received_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "body_withheld_lines": body_hits, "files": prov_files}
    _atomic_write(inbox / "provenance.json", json.dumps(prov, ensure_ascii=False, indent=2))
    return {"msg_id": msg_id, "node": node, "kind": item.get("kind"),
            "reply_to": item.get("reply_to"), "body": body,
            "files": [f["name"] for f in files if f["status"] == "ok"],
            "quarantined": sum(1 for f in files if f["status"] == "quarantined")}


_TMP_NAME = re.compile(r"^\.(body\.txt|provenance\.json)\.[0-9a-f]{8}\.tmp$")


def _sweep_tmp_files(cfg: HostConfig, node: str, older_than_s: float, now_s: float) -> None:
    """Remove `.body.txt.<hex>.tmp` and `.provenance.json.<hex>.tmp` left by a killed writer in
    `inbox/<node>/*` and `outbox/<node>/*` when they are older than `older_than_s`."""
    for top in ("inbox", "outbox"):
        base = Path(cfg.data_root) / top / node
        try:
            dirs = [p for p in base.iterdir() if p.is_dir() and not p.is_symlink()]
        except OSError:
            continue
        for d in dirs:
            try:
                names = [p for p in d.iterdir() if _TMP_NAME.match(p.name)]
            except OSError:
                continue
            for f in names:
                try:
                    if (f.is_symlink() or not f.is_file()
                            or now_s - f.stat().st_mtime <= older_than_s):
                        continue
                    f.unlink()
                except OSError:
                    continue


def sweep_stage_dirs(cfg: HostConfig, node: str, older_than_s: float = 3600,
                     now_s: Optional[float] = None) -> int:
    """Remove `quarantine/<node>/*/.stage-*` directories left by a killed process and then
    their empty parents, and stale temporary body and provenance files. Returns the number of
    stage directories removed; never raises."""
    base = Path(cfg.data_root) / "quarantine" / node
    now_s = time.time() if now_s is None else now_s
    removed = 0
    try:
        _sweep_tmp_files(cfg, node, older_than_s, now_s)
    except Exception:
        pass
    try:
        parents = [p for p in base.iterdir() if p.is_dir() and not p.is_symlink()]
    except OSError:
        return 0
    for parent in parents:
        try:
            stages = [p for p in parent.iterdir() if p.name.startswith(".stage-")]
        except OSError:
            continue
        for st in stages:
            try:
                if st.is_symlink() or not st.is_dir() or not _within(st, base):
                    continue
                if now_s - st.stat().st_mtime <= older_than_s:
                    continue
                shutil.rmtree(str(st), ignore_errors=True)
                if not st.exists():
                    removed += 1
            except OSError:
                continue
        try:
            parent.rmdir()
        except OSError:
            pass
    return removed


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(".%s.%s.tmp" % (path.name, uuid.uuid4().hex[:8]))
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(str(tmp), str(path))
    except BaseException:
        try:
            os.unlink(str(tmp))
        except OSError:
            pass
        raise


def store_outgoing(cfg: HostConfig, node: str, msg_id: str, body: str,
                   files: List[Path]) -> dict:
    """Keep a masked copy of an outgoing body under outbox/<node>/<msg_id>/ (design 6.5).

    The copy is masked with the hub's patterns, so it is not always the text that was sent.
    Attachment files are not copied; only name, size and hash are recorded."""
    if not valid_msg_id(msg_id):
        raise ValueError("unsafe msg_id")
    cfg.alias(node)
    root = Path(cfg.data_root) / "outbox" / node
    d = root / msg_id
    if not _within(d, root):
        raise ValueError("unsafe msg_id")
    wh = Withheld.load(Path(cfg.withheld_patterns_file))
    masked, hits = wh.mask_text(body)
    atts = []  # type: List[Dict[str, Any]]
    for idx, f in enumerate(files):
        atts.append({"index": idx, "name": "(withheld)" if wh.name_hit(f.name) else f.name,
                     "bytes": f.stat().st_size, "sha256": _sha(f)})
    body_file = d / "body.txt"
    body_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    prov_file = d / "provenance.json"
    if body_file.is_file():
        # compare the hash of the unmasked body, so a changed pattern file does not matter;
        # a record from before the hash existed falls back to the masked text
        try:
            old_sha = json.loads(prov_file.read_text(encoding="utf-8")).get("body_sha256")
        except (OSError, ValueError, AttributeError):
            old_sha = None
        if isinstance(old_sha, str):
            same = old_sha == body_sha
        else:
            same = body_file.read_text(encoding="utf-8") == masked
        if not same:
            raise ValueError("msg_id already used with a different body")
    d.mkdir(parents=True, exist_ok=True)
    if not body_file.is_file():
        _atomic_write(body_file, masked)
    if not prov_file.is_file():
        prov = {"node": node, "msg_id": msg_id,
                "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "body_chars": len(body), "body_sha256": body_sha, "body_withheld_lines": hits, "attachments": atts}
        _atomic_write(prov_file, json.dumps(prov, ensure_ascii=False, indent=2))
    return {"dir": str(d), "body_withheld_lines": hits, "attachments": atts}
