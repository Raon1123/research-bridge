"""Store polled node items on the laptop, re-checking withheld patterns."""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any, Dict

from rb_node.withheld import Withheld

from .client import RemoteError
from .config import HostConfig


def _safe_name(name: str) -> str:
    base = str(name).replace("\\", "/").rsplit("/", 1)[-1]
    return base if base not in ("", ".", "..") else "unnamed"


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
    if "/" in msg_id or "\\" in msg_id or msg_id in ("", ".", ".."):
        raise ValueError("unsafe message id")
    root = Path(cfg.data_root)
    inbox = root / "inbox" / node / msg_id
    quar = root / "quarantine" / node / msg_id
    stage_dir = quar / ".stage"
    body, body_hits = wh.mask_text(str(item.get("body", "")))
    inbox.mkdir(parents=True, exist_ok=True)
    files = []  # type: list
    for idx, att in enumerate(item.get("attachments", [])):
        name = _safe_name(att.get("name", ""))
        entry = {"index": idx, "name": name, "status": "ok"}  # type: Dict[str, Any]
        name_bad = wh.name_hit(name) or wh.name_hit(str(att.get("original", "")))
        stage = stage_dir / name
        try:
            client.get_file("out", "%s/%s" % (msg_id, name), stage)
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
            del pf["name"]  # the name itself may be the withheld content
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
