"""harness-receive: the harness key's forced command (stdlib only).

Routing (SSH_ORIGINAL_COMMAND):
  "harness-send"            pull path: tar the allowlisted harness subset to stdout
  "" or "harness-push"      push path: stage a received tar under harness-staging/ only
  anything else             refused (exit 1)
There is no apply step on either side; staged files are copied into place by hand.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import tarfile
import time
from pathlib import Path
from typing import BinaryIO, Callable, List, Optional, Tuple

from .audit import Audit
from .config import NodeConfig
from .paths import PathPolicy, PolicyError

# Allowlist: same set the laptop harness bundles use. deliver.ps1 itself carries no
# allowlist (it copies whatever -Path it is given); the single source is
# 60_Tools/sync/prepare_staging.py (HARNESS_FILES, HARNESS_DIRS, HARNESS_EXCLUDE_SUFFIX).
HARNESS_FILES = ["CLAUDE.md", "settings.json", "rtk-reference.md"]
HARNESS_DIRS = ["commands", "agents", "hooks", "workflows"]
EXCLUDE_SUFFIX = (".pyc", ".bak")
MAX_MEMBERS = 5000
MAX_TOTAL = 64 * 1024 * 1024

# Same credential-key rule as prepare_staging.py SENSITIVE_KEY_RE (fail closed).
_SENSITIVE = re.compile(
    r"(?:^|[_-])(api[_-]?key|access[_-]?key|private[_-]?key|token|secret|password|credential)(?:$|[_-])",
    re.IGNORECASE)


class HarnessError(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__("%s: %s" % (code, message) if message else code)
        self.code = code
        self.message = message


def _populated(v: object) -> bool:
    return v not in (None, "", False, [], {})


def _sensitive_paths(value: object, path: str) -> List[str]:
    found = []  # type: List[str]
    if isinstance(value, dict):
        for k, child in value.items():
            cp = "%s.%s" % (path, k)
            if _SENSITIVE.search(str(k)) and _populated(child):
                found.append(cp)
            found.extend(_sensitive_paths(child, cp))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            found.extend(_sensitive_paths(child, "%s[%d]" % (path, i)))
    return found


def check_json(name: str, data: bytes) -> None:
    """Refuse a .json file holding a populated credential-like key. Never echoes values."""
    if not name.lower().endswith(".json"):
        return
    try:
        obj = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise HarnessError("unreadable_json", "cannot inspect %s" % name)
    hits = sorted(set(_sensitive_paths(obj, name)))
    if hits:
        raise HarnessError("credential_key", "populated credential-like key in " + ", ".join(hits))


def collect(root: Path, max_file: int = MAX_TOTAL) -> List[Tuple[str, bytes]]:
    """Allowlisted (arcname, bytes) pairs under root; symlinks and excluded files skipped."""
    root = Path(root)
    out = []  # type: List[Tuple[str, bytes]]
    for name in HARNESS_FILES:
        p = root / name
        if p.is_file() and not p.is_symlink():
            out.append((name, _read(p, max_file)))
    for d in HARNESS_DIRS:
        base = root / d
        if not base.is_dir() or base.is_symlink():
            continue
        for dp, dns, fns in os.walk(str(base), followlinks=False):
            dns[:] = sorted(x for x in dns if x != "__pycache__")
            for fn in sorted(fns):
                p = Path(dp) / fn
                if p.is_symlink() or not p.is_file() or fn.endswith(EXCLUDE_SUFFIX):
                    continue
                out.append(("%s/%s" % (d, p.relative_to(base).as_posix()), _read(p, max_file)))
    return out


def _read(p: Path, max_file: int) -> bytes:
    if p.stat().st_size > max_file:
        raise HarnessError("too_large", "a harness file exceeds %d bytes" % max_file)
    return p.read_bytes()


def build_tar(entries: List[Tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data in entries:
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            ti.mtime = 0
            ti.mode = 0o644
            tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def _check_name(name: str) -> None:
    if (not name or "\x00" in name or "\\" in name or name.startswith("/")
            or re.match(r"^[A-Za-z]:", name)):
        raise HarnessError("bad_member", "unsafe member path")
    parts = name.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise HarnessError("bad_member", "unsafe member path")
    top = parts[0]
    if len(parts) == 1:
        if top not in HARNESS_FILES:
            raise HarnessError("bad_member", "member not in allowlist")
    elif top not in HARNESS_DIRS:
        raise HarnessError("bad_member", "member not in allowlist")


def validate_tar(data: bytes) -> List[tarfile.TarInfo]:
    """Check every member before anything is extracted. Returns regular-file members."""
    try:
        tf = tarfile.open(fileobj=io.BytesIO(data), mode="r:")
        members = tf.getmembers()
    except (tarfile.TarError, EOFError, OSError):
        raise HarnessError("bad_tar", "not a readable tar")
    if len(members) > MAX_MEMBERS:
        raise HarnessError("bad_tar", "too many members")
    files = []  # type: List[tarfile.TarInfo]
    total = 0
    for m in members:
        _check_name(m.name)
        if m.issym() or m.islnk() or not (m.isreg() or m.isdir()):
            raise HarnessError("bad_member", "links and special files are not allowed")
        if m.isreg():
            total += m.size
            files.append(m)
    if total > MAX_TOTAL:
        raise HarnessError("too_large", "tar exceeds %d bytes" % MAX_TOTAL)
    for m in files:
        check_json(m.name, tf.extractfile(m).read())  # type: ignore[union-attr]
    return files


def extract_tar(data: bytes, dest_parent: Path, stamp: str,
                rename: Optional[Callable[[str], str]] = None) -> Tuple[Path, int]:
    """Validate everything, then write into dest_parent/<stamp>/. Nothing is written on rejection.

    rename maps each member's last path component to the stored name (the laptop passes one).
    """
    files = validate_tar(data)
    tf = tarfile.open(fileobj=io.BytesIO(data), mode="r:")
    dest_parent = Path(dest_parent)
    dest_parent.mkdir(parents=True, exist_ok=True)
    tmp = dest_parent / (".%s.part" % stamp)
    if tmp.exists():
        raise HarnessError("busy", "staging directory in use")
    tmp.mkdir()
    try:
        policy = PathPolicy(tmp, [], [str(tmp)])
        for m in files:
            name = m.name
            if rename is not None:
                head, _, last = name.rpartition("/")
                name = (head + "/" if head else "") + rename(last)
            target = policy.resolve_write(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(tf.extractfile(m).read())  # type: ignore[union-attr]
        final = dest_parent / stamp
        n = 1
        while final.exists():
            n += 1
            final = dest_parent / ("%s-%d" % (stamp, n))
        os.rename(str(tmp), str(final))
    except (PolicyError, OSError) as exc:
        _rmtree(tmp)
        if isinstance(exc, PolicyError):
            raise HarnessError("bad_member", "unsafe member path")
        raise HarnessError("io_error", type(exc).__name__)
    except BaseException:
        _rmtree(tmp)
        raise
    return final, len(files)


def _rmtree(p: Path) -> None:
    import shutil
    shutil.rmtree(str(p), ignore_errors=True)


def stage_tar(data: bytes, staging_root: Path, stamp: str) -> Tuple[Path, int]:
    return extract_tar(data, staging_root, stamp)


def utc_stamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


# -- node entry points -------------------------------------------------------
def _fail(code: str, message: str = "") -> int:
    sys.stderr.write("rb-node harness-receive: %s\n" % (("%s: %s" % (code, message)) if message else code))
    return 1


def _root(cfg: NodeConfig) -> Path:
    if not cfg.harness_root:
        raise HarnessError("no_harness_root", "harness_root is not set in node config")
    return Path(os.path.expanduser(cfg.harness_root))


def staging_dir(cfg: NodeConfig) -> Path:
    return Path(cfg.mailbox_root).parent / "harness-staging"


def harness_send(cfg: NodeConfig, stdout: BinaryIO) -> int:
    audit = Audit(Path(cfg.audit_path))
    try:
        entries = collect(_root(cfg), cfg.max_file)
        for name, data in entries:
            check_json(name, data)
        tar = build_tar(entries)
    except HarnessError as exc:
        audit.record(op="harness_send", ok=False, code=exc.code)
        return _fail(exc.code, exc.message if exc.code != "credential_key" else "credential-like key in a harness file")
    except OSError as exc:
        audit.record(op="harness_send", ok=False, code="io_error")
        return _fail("io_error", type(exc).__name__)
    stdout.write(tar)
    stdout.flush()
    audit.record(op="harness_send", ok=True, files=len(entries))
    return 0


def harness_push(cfg: NodeConfig, stdin: BinaryIO) -> int:
    audit = Audit(Path(cfg.audit_path))
    try:
        _root(cfg)  # push is refused too while the node has no harness configured
        data = stdin.read(MAX_TOTAL * 2 + 1)
        if len(data) > MAX_TOTAL * 2:
            raise HarnessError("too_large", "input too large")
        dest, n = extract_tar(data, staging_dir(cfg), utc_stamp())
    except HarnessError as exc:
        audit.record(op="harness_push", ok=False, code=exc.code)
        return _fail(exc.code, exc.message)
    audit.record(op="harness_push", ok=True, files=n)
    sys.stdout.write(json.dumps({"staged": dest.name, "files": n}) + "\n")
    sys.stdout.flush()
    return 0


def harness_receive(cfg: NodeConfig, command: str, stdin: BinaryIO, stdout: BinaryIO) -> int:
    if command == "harness-send":
        return harness_send(cfg, stdout)
    if command in ("", "harness-push"):
        return harness_push(cfg, stdin)
    return _fail("unknown_command")
