"""Manual harness channel, laptop side: push / pull / diff. There is deliberately no apply step.

Portablization is VENDORED from 60_Tools/sync/portablize_harness.py (path mapping, line
classifier, markdown table insertion) because the vault must not be a runtime dependency.
Only the in-memory text transform is kept; the scan/backup/CLI parts are not.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from rb_node.harness import (HarnessError, build_tar, check_json, collect as _collect,
                             extract_tar, utc_stamp)

from .client import default_argv
from .config import HostConfig

STAMP_RE = re.compile(r"^\d{8}T\d{6}Z(-\d+)?$")
TIMEOUT = 300


# ---------------------------------------------------------------------------
# Vendored from portablize_harness.py (source: 90_Claude/60_Tools/sync/portablize_harness.py)
# ---------------------------------------------------------------------------
def _local_homes() -> Tuple[str, str]:
    """(laptop home, node home). Real values stay out of git: they come from
    RB_LAPTOP_HOME / RB_NODE_HOME, else private/local.json (gitignored, keys laptop_home and
    node_home), else the laptop's own home and /home/<laptop login name>."""
    data: Dict[str, str] = {}
    local = Path(__file__).resolve().parent.parent / "private" / "local.json"
    if local.is_file():
        data = json.loads(local.read_text(encoding="utf-8"))
    lap = os.environ.get("RB_LAPTOP_HOME") or data.get("laptop_home") or Path.home().as_posix()
    srv = os.environ.get("RB_NODE_HOME") or data.get("node_home") or "/home/" + Path.home().name
    return lap.replace(chr(92), "/").rstrip("/"), srv.rstrip("/")


LAPTOP_HOME, NODE_HOME = _local_homes()
NODE_USER = NODE_HOME.rsplit("/", 1)[-1]
MAPPING = [
    ("<MASTER_BIB>", "D:/raw/bibtex/references.bib", "<VAULT_TEX_ROOT>/_shared/references.bib"),
    ("<VAULT_PRIMARY_90CLAUDE>", "D:/raw/vault-primary/90_Claude", NODE_HOME + "/raw/vault-primary/90_Claude"),
    ("<VAULT_TEX_ROOT>", "D:/raw/vault-tex", NODE_HOME + "/raw/vault-tex"),
    ("<RAW_ROOT>", "D:/raw", NODE_HOME + "/raw"),
    ("<HOME>", LAPTOP_HOME, NODE_HOME),
]
SKIP_REVIEW = re.compile(r"REVIEW:")
SKIP_PS = re.compile(r"\.ps1|powershell\s+-", re.I)
SKIP_UV = re.compile(r"uv\s+run\s+python")
SKIP_PROHIBIT = re.compile(r"NEVER|금지|절대|쓰지\s*마|do\s+not\s+write|read-?only|CRITICAL-never", re.I)
ICLOUD = re.compile(r"D:/iCloud", re.I)
INTERP = re.compile(r"C:/Python\d+/python\.exe|D:/raw/envs/[^/ ]+/Scripts/python\.exe", re.I)
PATH_RE = re.compile(r"D:/raw|D:/iCloud|" + re.escape(LAPTOP_HOME) + r"|C:/Python\d+", re.I)
FLIP_OPEN = re.compile(r"MACHINE DEFAULTS")
FLIP_CLOSE = re.compile(r"^\s*(?://|#)\s*[-─]{10,}\s*$")
TABLE_ROW = re.compile(r"^\s*\|.*\|")
SERVER_PATH = re.compile(re.escape(NODE_HOME) + r"|/mnt/")
PLACEHOLDER = re.compile(r"<[A-Z][A-Z0-9_]*>")
_STOP = re.escape(chr(34) + chr(39) + chr(96) + ',;:)]}<>|')
TOKEN_TAIL = '[^' + chr(92) + 's' + _STOP + ']*'


def _slash(text: str) -> str:
    return text.replace(chr(92), "/")


def classify(line: str, in_flip: bool = False, is_ps1: bool = False) -> str:
    """AUTO only for lines that are mechanically safe to placeholderize."""
    if is_ps1 or in_flip:
        return "SKIP"
    if TABLE_ROW.match(line) and (SERVER_PATH.search(line) or PLACEHOLDER.search(line)):
        return "SKIP"
    if SKIP_REVIEW.search(line) or SKIP_UV.search(line):
        return "SKIP"
    if SKIP_PS.search(line) or INTERP.search(line) or ICLOUD.search(line) or SKIP_PROHIBIT.search(line):
        return "HUMAN"
    return "AUTO"


def _root_regex(laptop_root: str) -> "re.Pattern[str]":
    parts = [re.escape(seg) for seg in laptop_root.split("/")]
    return re.compile("(?i)" + r"[/\\]".join(parts) + "(" + TOKEN_TAIL + ")")


COMPILED = [(ph, _root_regex(lap), lap, srv) for ph, lap, srv in MAPPING]

TABLE_HEAD = "| Placeholder | Linux server | Windows laptop |\n|---|---|---|\n"
MD_BLOCK = """## Path resolution (machine-dependent — resolve before any file operation)

This file runs on two machines. Resolve these placeholders once, at the start of
your run, by testing which root exists (e.g. `ls -d <candidate>`), then use the
resolved values everywhere below.

{table}{caveat}If neither candidate root exists, stop and report rather than guessing a path.
"""
BIB_CAVEAT = ("\n`<MASTER_BIB>` is **not** under `<VAULT_TEX_ROOT>` on the laptop — "
              "resolve it\nindependently.\n\n")
NAS_BACKED = {
    "<VAULT_PRIMARY_90CLAUDE>": ("VAULT_PRIMARY_90CLAUDE",
                                 [NODE_HOME + "/raw/vault-primary/90_Claude",
                                  "/mnt/<nas>/%s/vault-primary/90_Claude" % NODE_USER]),
    "<VAULT_TEX_ROOT>": ("VAULT_TEX_ROOT",
                         [NODE_HOME + "/raw/vault-tex", NODE_HOME + "/project/vault-tex",
                          "/mnt/<nas>/%s/vault-tex" % NODE_USER]),
}


def _nas_note(used: set) -> str:
    phs = [p for p in NAS_BACKED if p in used]
    if not phs:
        return ""
    names = " and ".join("`%s`" % p for p in phs)
    verb = "are" if len(phs) > 1 else "is"
    out = ("\n**%s %s NAS-backed: the share is mounted at a different point on each\n"
           "server.** Never hardcode one. Resolve each in this order, first hit wins:\n\n"
           % (names, verb))
    for ph in phs:
        env, cands = NAS_BACKED[ph]
        out += ("- `%s` — `$%s` if set; else the first of these that exists: %s;\n"
                "  else stop and report.\n" % (ph, env, ", ".join("`%s`" % c for c in cands)))
    out += ("\nThe `<nas>` share name varies between servers (seen as `banana`, `nas`).\n"
            "Do not guess, and never fall back to the laptop path.\n\n")
    return out


def _rewrite_line(line: str) -> Tuple[str, List[str]]:
    used = []  # type: List[str]
    for ph, rx, _lap, _srv in COMPILED:
        def sub(m, ph=ph):
            used.append(ph)
            return ph + m.group(1).replace(chr(92), "/")
        line = rx.sub(sub, line)
    return line, used


def _insert_md_table(text: str, used: List[str]) -> str:
    if "## Path resolution" in text:
        return text
    u = set(used)
    rows = ""
    for ph, lap, srv in MAPPING:
        if ph in u:
            cell = ("`$%s` → probe (mount differs per server)" % NAS_BACKED[ph][0]
                    if ph in NAS_BACKED else "`%s`" % srv)
            rows += "| `%s` | %s | `%s` |\n" % (ph, cell, lap)
    if not rows:
        return text
    caveat = BIB_CAVEAT if {"<MASTER_BIB>", "<VAULT_TEX_ROOT>"} <= u else "\n"
    caveat = _nas_note(u) + caveat
    block = MD_BLOCK.format(table=TABLE_HEAD + rows, caveat=caveat)
    nl = "\r\n" if text.count("\r\n") > text.count("\n") // 2 else "\n"
    if nl == "\r\n":
        block = block.replace("\n", "\r\n")
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            cut = text.find("\n", end + 1) + 1
            return text[:cut] + nl + block + text[cut:]
    return block + text


def portablize_text(name: str, data: bytes) -> bytes:
    """Markdown-only (.md / .md.off) mechanical placeholderization; everything else unchanged."""
    low = name.lower()
    if not (low.endswith(".md") or low.endswith(".md.off")):
        return data
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    lines = text.splitlines(keepends=True)
    in_flip = False
    used = []  # type: List[str]
    changed = 0
    for idx, raw in enumerate(lines):
        stripped = raw.rstrip("\r\n")
        line = _slash(stripped)
        if FLIP_OPEN.search(line):
            in_flip = True
        elif in_flip and FLIP_CLOSE.match(line):
            in_flip = False
            continue
        if not PATH_RE.search(line) or classify(line, in_flip=in_flip) != "AUTO":
            continue
        new, u = _rewrite_line(stripped)
        if new != stripped:
            lines[idx] = new + raw[len(stripped):]
            used += u
            changed += 1
    if not changed:
        return data
    out = "".join(lines)
    if low.endswith(".md"):
        out = _insert_md_table(out, used)
    return out.encode("utf-8")


# ---------------------------------------------------------------------------
# Channel
# ---------------------------------------------------------------------------
def claude_home() -> Path:
    return Path.home() / ".claude"


def harness_alias(cfg: HostConfig, node: str) -> str:
    cfg.alias(node)  # unknown node -> ValueError
    entry = cfg.nodes.get(node, {})
    alias = entry.get("harness_alias")
    return alias if isinstance(alias, str) and alias else "rb-%s-harness" % node


def transport(cfg: HostConfig, node: str, command: str) -> Tuple[List[str], Optional[Dict[str, str]]]:
    """argv/env for one harness call; tests replace this. Uses the separate harness alias."""
    return default_argv(harness_alias(cfg, node)) + [command], None


def _run(argv: List[str], env: Optional[Dict[str, str]], data: bytes) -> bytes:
    full = None
    if env is not None:
        full = dict(os.environ)
        full.update(env)
    try:
        r = subprocess.run(argv, input=data, env=full, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        raise HarnessError("transport", type(exc).__name__)
    if r.returncode != 0:
        tail = r.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or [""]
        raise HarnessError("node_refused", "exit %s %s" % (r.returncode, tail[0][:200]))
    return r.stdout


def collect(home: Path) -> List[Tuple[str, bytes]]:
    """Allowlisted harness files, credential-checked and portablized."""
    out = []
    for name, data in _collect(Path(home)):
        check_json(name, data)
        out.append((name, portablize_text(name, data)))
    return out


def push(cfg: HostConfig, node: str, dry_run: bool = False) -> List[str]:
    harness_alias(cfg, node)  # unknown node -> ValueError, before anything is read
    entries = collect(claude_home())
    names = [n for n, _ in entries]
    if dry_run:
        return names
    argv, env = transport(cfg, node, "harness-push")
    reply = _run(argv, env, build_tar(entries))
    try:
        info = json.loads(reply.decode("utf-8").strip().splitlines()[-1])
        staged = str(info["staged"])
    except (ValueError, KeyError, IndexError):
        raise HarnessError("bad_reply", "node reply not understood")
    return ["staged on node: %s (%d files)" % (staged, len(names))]


def staging_root(cfg: HostConfig) -> Path:
    return Path(cfg.data_root) / "harness-staging"


def pull(cfg: HostConfig, node: str) -> Tuple[Path, int]:
    argv, env = transport(cfg, node, "harness-send")
    tar = _run(argv, env, b"")
    return extract_tar(tar, staging_root(cfg), utc_stamp())


def diff(cfg: HostConfig, stamp: str) -> str:
    if not STAMP_RE.match(stamp):
        raise HarnessError("bad_stamp", "stamp must look like 20261027T120000Z")
    base = staging_root(cfg) / stamp
    if not base.is_dir():
        raise HarnessError("not_found", "no such staging directory")
    home = claude_home()
    chunks = []  # type: List[str]
    for p in sorted(x for x in base.rglob("*") if x.is_file()):
        rel = p.relative_to(base).as_posix()
        live = home / rel
        new = p.read_bytes()
        old = live.read_bytes() if live.is_file() else None
        if old == new:
            continue
        a = [] if old is None else old.decode("utf-8", "replace").splitlines(keepends=True)
        b = new.decode("utf-8", "replace").splitlines(keepends=True)
        chunks.extend(difflib.unified_diff(
            a, b, "/dev/null" if old is None else "live/" + rel, "staged/" + rel))
    return "".join(c if c.endswith("\n") else c + "\n" for c in chunks)
