"""Install helpers called by scripts/node-install.sh (stdlib only).

Run as `PYTHONPATH=<checkout> python3 -m rb_node.install <subcommand>`. Everything that edits a
file or derives a value lives here so that it is tested in Python. Output never contains pattern
text; key blobs are shown only for the lines the user is asked to apply.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import glob
import ipaddress
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Optional, Tuple

from . import configure, doctor
# one copy of the terminal check and the y/N prompt; tests replace install._interactive / _ask
from .cli import _ask, _interactive
from .config import DEFAULT_RB, NodeConfig, config_path, load_config
from .withheld import Withheld

_KEYTYPES = ("ssh-ed25519", "ssh-rsa", "ssh-dss", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384",
             "ecdsa-sha2-nistp521", "sk-ssh-ed25519@openssh.com",
             "sk-ecdsa-sha2-nistp256@openssh.com")


def _run(argv: List[str], input: Optional[bytes] = None) -> Tuple[int, str, str]:
    try:
        r = subprocess.run(argv, input=input, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def _stamp() -> str:
    return time.strftime("%Y%m%d%H%M%S")


# -- keys ----------------------------------------------------------------------------------------
def read_pubkey(inline: str = "", path: str = "") -> Tuple[str, str]:
    """(keytype, blob) from an inline 'type blob [comment]' string or the first key line of a file."""
    text = inline
    if not text and path:
        try:
            lines = Path(path).read_text(encoding="utf-8").splitlines()
        except (OSError, ValueError) as exc:
            raise ValueError("cannot read public key file %s: %s" % (path, exc))
        keyed = [x for x in lines if x.strip() and not x.lstrip().startswith("#")]
        text = keyed[0] if keyed else ""
    fields = text.split()
    if len(fields) < 2:
        raise ValueError("public key needs 'type base64-blob' (comment optional)")
    keytype, blob = fields[0], fields[1]
    if keytype not in _KEYTYPES:
        raise ValueError("unsupported public key type %r" % keytype)
    try:
        base64.b64decode(blob, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("public key blob is not valid base64")
    return keytype, blob


def validate_from(value: str) -> str:
    """Comma-separated addresses or CIDR ranges, each checked; returns the normalized text."""
    parts = [p.strip() for p in value.split(",")]
    if not value.strip() or any(not p for p in parts):
        raise ValueError("--hub-from needs one or more addresses or CIDR ranges, comma-separated")
    out = []
    for p in parts:
        try:
            net = ipaddress.ip_network(p, strict=False)
        except ValueError:
            raise ValueError("not an address or CIDR range: %r" % p)
        out.append(str(net) if "/" in p else str(net.network_address))
    return ",".join(out)


def ak_lines(bridge: Tuple[str, str], harness: Optional[Tuple[str, str]], hub_from: str,
             bindir: Path) -> List[str]:
    def line(key: Tuple[str, str], verb: str, comment: str) -> str:
        return 'restrict,from="%s",command="%s/rb-node %s" %s %s %s' % (
            hub_from, str(bindir), verb, key[0], key[1], comment)
    out = [line(bridge, "serve-remote", "research-bridge-hub")]
    if harness is not None:
        out.append(line(harness, "harness-receive", "research-bridge-harness"))
    return out


def plan_authorized_keys(existing: str, new_lines: List[str]) -> Tuple[str, List[str]]:
    """(new_text, changes). Never removes a line. Raises ValueError when two new lines share a blob."""
    new_blobs = []
    for nl in new_lines:
        parsed = doctor.parse_authorized_keys(nl)
        if len(parsed) != 1:
            raise ValueError("not an authorized_keys line")
        new_blobs.append(parsed[0]["blob"])
    if len(set(new_blobs)) != len(new_blobs):
        raise ValueError("two new lines share one key blob")
    lines = existing.splitlines()
    held = doctor.parse_authorized_keys(existing)
    changes = []  # type: List[str]
    appended = []  # type: List[str]
    for nl, blob in zip(new_lines, new_blobs):
        verb = nl.split('command="', 1)[1].split('"', 1)[0].split()[-1]
        same = [e for e in held if e["blob"] == blob]
        if not same:
            appended.append(nl)
            changes.append("add %s line" % verb)
            continue
        first = same[0]["lineno"]
        if lines[first - 1].strip() == nl:
            changes.append("unchanged %s line (line %d)" % (verb, first))
        else:
            lines[first - 1] = nl
            changes.append("replace line %d (%s)" % (first, verb))
        for other in same[1:]:
            changes.append("line %d also holds this key: remove it by hand" % other["lineno"])
    text = "\n".join(lines + appended)
    return (text + "\n" if text else ""), changes


def _write_private(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, 0o600)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _backup(path: Path) -> Path:
    bak = path.with_name("%s.bak.%s" % (path.name, _stamp()))
    n = 0
    while bak.exists():
        n += 1
        bak = path.with_name("%s.bak.%s.%d" % (path.name, _stamp(), n))
    _write_private(bak, path.read_bytes())
    return bak


def _read_ak(path: Path) -> str:
    """Read authorized_keys without failing on stray non-UTF-8 bytes (kept byte for byte)."""
    return path.read_bytes().decode("utf-8", "surrogateescape")


def apply_authorized_keys(path: Path, new_text: str, changes: List[str]) -> bool:
    path = Path(path)
    for c in changes:
        print("  " + c)
    if not _interactive():
        print("not a terminal: authorized_keys not changed; apply the lines above by hand")
        return False
    if path.is_symlink():
        print("%s is a symlink: not changed; apply the lines above by hand" % path)
        return False
    old = _read_ak(path) if path.exists() else None
    if old == new_text:
        print("authorized_keys is already up to date")
        return False
    if not _ask("Apply? [y/N]"):
        print("authorized_keys not changed")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(str(path.parent), 0o700)
    if old is not None:
        print("backup: %s" % _backup(path))
    _write_private(path, new_text.encode("utf-8", "surrogateescape"))
    print("wrote %s" % path)
    return True


# -- withheld pattern file -----------------------------------------------------------------------
def _count(path: Path) -> int:
    return Withheld.load(path).extra_count


def install_withheld(src: Path, dest: Path, cfg_path: Path, dry_run: bool = False) -> int:
    src, dest, cfg_path = Path(src), Path(dest), Path(cfg_path)
    w = Withheld.load(src)
    problem = w.problem()
    if problem is not None:
        why = {"rejected": "has %d pattern(s) that do not compile" % w.rejected_count,
               "empty": "has no pattern"}.get(problem, "is " + problem)
        sys.stderr.write("withheld file %s: nothing copied\n" % why)
        return 1
    data = {}  # type: dict
    if cfg_path.is_file():
        try:
            data = configure.read_json(cfg_path)
        except (configure.ConfigError, OSError) as exc:
            sys.stderr.write("cannot read node.json: %s\n" % exc)
            return 1
    elif not dry_run:
        sys.stderr.write("no node.json at %s; run rb-node config init first\n" % cfg_path)
        return 1
    new_bytes = src.read_bytes()
    current = data.get("withheld_source")
    existing = []  # type: List[Path]
    if dest.is_file():
        existing.append(dest)
    if isinstance(current, str) and current:
        cur = Path(os.path.expanduser(current))
        if cur.is_file() and not (dest.is_file() and os.path.samefile(str(cur), str(dest))):
            existing.append(cur)
    differing = [p for p in existing if p.read_bytes() != new_bytes]
    if not differing and existing and current == str(dest) and dest.is_file():
        print("withheld file unchanged (%d patterns)" % w.extra_count)
        return 0
    custom_missing = (isinstance(current, str) and bool(current) and current != str(dest)
                      and not Path(os.path.expanduser(current)).is_file())
    if custom_missing and not differing:
        print("withheld_source names a file that is missing; the new file would replace that setting")
        if not _interactive():
            sys.stderr.write("replacing withheld_source needs an interactive terminal; "
                             "nothing changed\n")
            return 1
    if differing:
        old_n = _count(differing[0])
        print("current file: %d patterns; new file: %d patterns" % (old_n, w.extra_count))
        if w.extra_count < old_n:
            print("fewer patterns: masking is narrowed")
        if not _interactive():
            sys.stderr.write("replacing a different withheld file needs an interactive terminal; "
                             "nothing changed\n")
            return 1
        if dry_run:
            print("[dry-run] would ask: Replace? [y/N]")
            return 0
        if not _ask("Replace? [y/N]"):
            sys.stderr.write("not replaced\n")
            return 1
    if dry_run:
        print("[dry-run] would copy %d patterns to %s and set withheld_source" % (w.extra_count, dest))
        return 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file():
        print("backup: %s" % _backup(dest))
    _write_private(dest, new_bytes)
    data["withheld_source"] = str(dest)
    configure.write_json(cfg_path, data)
    print("withheld file installed: %d patterns; withheld_source set" % w.extra_count)
    return 0


# -- mailbox and fingerprints --------------------------------------------------------------------
def make_mailbox(cfg: NodeConfig) -> None:
    root = Path(cfg.mailbox_root)
    for d in (root, root / "in", root / "out", root / "state", root / "state" / "acked"):
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(str(d), 0o700)


def host_fingerprints() -> List[str]:
    pattern = os.environ.get("RB_NODE_HOSTKEY_GLOB", "/etc/ssh/ssh_host_*_key.pub")
    out = []
    for path in sorted(glob.glob(pattern)):
        rc, stdout, _err = _run(["ssh-keygen", "-lf", path])
        if rc == 0 and stdout.strip():
            out.append(stdout.strip().splitlines()[0])
    return out


# -- command line --------------------------------------------------------------------------------
def _keys(ns: argparse.Namespace) -> Tuple[Tuple[str, str], Optional[Tuple[str, str]]]:
    if not (ns.hub_key or ns.hub_pubkey):
        raise ValueError("give --hub-key or --hub-pubkey")
    bridge = read_pubkey(ns.hub_key or "", ns.hub_pubkey or "")
    harness = None
    if ns.harness_key or ns.harness_pubkey:
        harness = read_pubkey(ns.harness_key or "", ns.harness_pubkey or "")
    return bridge, harness


def _authorized_keys(rest: List[str]) -> int:
    ap = argparse.ArgumentParser(prog="install authorized-keys")
    ap.add_argument("--hub-key")
    ap.add_argument("--hub-pubkey")
    ap.add_argument("--harness-key")
    ap.add_argument("--harness-pubkey")
    ap.add_argument("--hub-from", required=True)
    ap.add_argument("--bindir", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true", help="validate the keys and --hub-from only")
    ns = ap.parse_args(rest)
    try:
        bridge, harness = _keys(ns)
        hub_from = validate_from(ns.hub_from)
    except ValueError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return 2
    if harness is not None and harness[1] == bridge[1]:
        sys.stderr.write("bridge and harness keys must differ (AGENTS.md hard rule 9)\n")
        return 2
    if ns.check:
        return 0
    lines = ak_lines(bridge, harness, hub_from, Path(ns.bindir))
    path = doctor.authorized_keys_path()
    try:
        existing = _read_ak(path)
    except OSError:
        existing = ""
    text, changes = plan_authorized_keys(existing, lines)
    print("--- authorized_keys lines ---")
    for ln in lines:
        print(ln)
    print("--- planned change to %s ---" % path)
    if ns.apply and not ns.dry_run:
        apply_authorized_keys(path, text, changes)
    else:
        for c in changes:
            print("  " + c)
        print("authorized_keys not changed (%s)" % (
            "dry run" if ns.dry_run else "give --apply-authorized-keys to apply"))
    return 0


def main(argv: List[str]) -> int:
    if not argv or argv[0] not in ("authorized-keys", "withheld", "mailbox", "fingerprints"):
        sys.stderr.write("usage: python3 -m rb_node.install "
                         "authorized-keys|withheld|mailbox|fingerprints ...\n")
        return 2
    sub, rest = argv[0], argv[1:]
    if sub == "authorized-keys":
        return _authorized_keys(rest)
    if sub == "withheld":
        ap = argparse.ArgumentParser(prog="install withheld")
        ap.add_argument("--file", required=True)
        ap.add_argument("--dry-run", action="store_true")
        ns = ap.parse_args(rest)
        dest = Path(os.path.expanduser(DEFAULT_RB)) / "withheld-patterns.json"
        return install_withheld(Path(ns.file), dest, config_path(), dry_run=ns.dry_run)
    if sub == "mailbox":
        try:
            make_mailbox(load_config())
        except (OSError, ValueError) as exc:
            sys.stderr.write("mailbox: %s\n" % exc)
            return 1
        print("mailbox directories ready")
        return 0
    prints = host_fingerprints()
    print("host key fingerprints: compare with the fingerprint that rb setup --node NAME "
          "shows on the hub")
    for p in prints:
        print("  " + p)
    if not prints:
        print("  none readable here; run: ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
