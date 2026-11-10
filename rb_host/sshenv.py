"""Local ssh environment: external commands, agent discovery, ssh config lookups.

Every external command of the hub goes through run() / run_interactive() so tests can replace
them. Paths that ssh reads come from the password database, not from $HOME.
"""
from __future__ import annotations

import os
import pwd
import socket
import stat
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

CACHE_S = 30.0
_cache = {}  # type: Dict[Optional[str], Tuple[float, Optional[Path]]]


def _child_env(env: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
    if env is None:
        return None
    merged = dict(os.environ)
    merged.update(env)
    return merged


def run(argv: List[str], env: Optional[Dict[str, str]] = None, timeout: float = 10.0,
        input: Optional[bytes] = None) -> Tuple[int, str, str]:
    """Run a command with captured output. `env` entries are added to os.environ."""
    try:
        p = subprocess.run(argv, input=input, capture_output=True, timeout=timeout,
                           env=_child_env(env))
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", type(exc).__name__
    return (p.returncode, p.stdout.decode("utf-8", "replace"),
            p.stderr.decode("utf-8", "replace"))


def run_interactive(argv: List[str], env: Optional[Dict[str, str]] = None) -> int:
    """Run a command that prompts in the terminal; returns its exit code (127 if not startable)."""
    try:
        return subprocess.call(argv, env=_child_env(env))
    except OSError:
        return 127


def user_home() -> Path:
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


def user_name() -> str:
    return pwd.getpwuid(os.getuid()).pw_name


def user_ssh_dir() -> Path:
    return user_home() / ".ssh"


def runtime_dir() -> Optional[Path]:
    fallback = "/run/user/%d" % os.getuid()
    raw = os.environ.get("XDG_RUNTIME_DIR") or fallback
    p = Path(raw)
    try:
        st = os.stat(str(p))
    except OSError:
        if raw == fallback:
            return None
        p = Path(fallback)  # stale XDG_RUNTIME_DIR (after su or sudo): try the standard place
        try:
            st = os.stat(str(p))
        except OSError:
            return None
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o700:
        return None
    return p


def socket_ok(path: Path) -> bool:
    try:
        st = os.lstat(str(path))
        parent = os.lstat(str(Path(path).parent))
    except OSError:
        return False
    if not stat.S_ISSOCK(st.st_mode) or st.st_uid != os.getuid():
        return False
    return parent.st_uid == os.getuid() and not (parent.st_mode & 0o022)


def _unique(paths: List[Path]) -> List[Path]:
    out = []  # type: List[Path]
    for p in paths:
        if p not in out:
            out.append(p)
    return out


def candidate_sockets() -> List[Path]:
    """Connect order: $SSH_AUTH_SOCK, then guessed names under the runtime directory."""
    cands = []  # type: List[Path]
    inherited = os.environ.get("SSH_AUTH_SOCK")
    if inherited:
        cands.append(Path(inherited))
    rt = runtime_dir()
    if rt is not None:
        cands += [rt / "gcr" / "ssh", rt / "openssh_agent", rt / "rb-ssh-agent"]
    return _unique([p for p in cands if socket_ok(p)])


def _agent_list(sock: Optional[Path]) -> Tuple[int, List[str]]:
    if sock is None:
        return 2, []
    rc, out, _ = run(["ssh-add", "-l"], env={"SSH_AUTH_SOCK": str(sock)})
    fps = []  # type: List[str]
    if rc == 0:
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                fps.append(parts[1])
    return rc, fps


def agent_rc(sock: Optional[Path]) -> int:
    return _agent_list(sock)[0]


def agent_fingerprints(sock: Path) -> List[str]:
    return _agent_list(sock)[1]


def ssh_config(alias: str) -> Dict[str, List[str]]:
    rc, out, _ = run(["ssh", "-G", alias])
    cfg = {}  # type: Dict[str, List[str]]
    if rc != 0:
        return cfg
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            cfg.setdefault(parts[0].lower(), []).extend(parts[1:])
    return cfg


def expand_path(raw: str) -> Optional[Path]:
    home = str(user_home())
    s = raw
    if s == "~" or s.startswith("~/"):
        s = home + s[1:]
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c != "%":
            out.append(c)
            i += 1
            continue
        nxt = s[i + 1:i + 2]
        if nxt == "%":
            out.append("%")
        elif nxt == "d":
            out.append(home)
        else:
            return None
        i += 2
    p = Path("".join(out))
    return p if p.is_absolute() else None


def known_hosts_files(cfg: Dict[str, List[str]]) -> List[Path]:
    files = [expand_path(v) for v in cfg.get("userknownhostsfile", [])]
    return [f for f in files if f is not None]


def alias_defined(alias: str) -> bool:
    hostname = ssh_config(alias).get("hostname") or [alias]
    return hostname[0].lower() != alias.lower()


def key_names(node: str) -> List[str]:
    """File names `rb setup` generates for a node: bridge key, harness key."""
    return ["%s_ed25519" % node, "%s_harness_ed25519" % node]


def default_names(alias: str) -> List[str]:
    """Key names for the default alias convention `rb-<node>[-harness]`; other aliases give []."""
    if not alias.startswith("rb-") or len(alias) <= 3:
        return []
    node = alias[3:]
    if node.endswith("-harness"):
        node = node[:-len("-harness")]
    return key_names(node) if node else []


def pick_identity(files: List[str], names: Sequence[str],
                  keydir: Optional[Path] = None) -> Optional[Path]:
    """The bridge key among the identityfile values `ssh -G` printed for an alias.

    Only a file whose name is one of `names` (the key names `rb setup` generates for the node) or
    that lies in `keydir` counts. Anything else (OpenSSH's default list, a `Host *` value, the
    user's personal key) gives None: the caller reports "no bridge IdentityFile configured"
    and never falls back to another key.
    """
    for f in files:
        p = expand_path(f)
        if p is None:
            continue
        if p.name in names or (keydir is not None and p.parent == keydir):
            return p
    return None


def identity_file(alias: str, names: Optional[Sequence[str]] = None,
                  keydir: Optional[Path] = None) -> Optional[Path]:
    wanted = default_names(alias) if names is None else names
    return pick_identity(ssh_config(alias).get("identityfile") or [], wanted, keydir)


def fingerprint(pub: Path) -> Optional[str]:
    rc, out, _ = run(["ssh-keygen", "-lf", str(pub)])
    parts = out.split()
    if rc != 0 or len(parts) < 2:
        return None
    return parts[1]


def key_unencrypted(key: Path) -> bool:
    return run(["ssh-keygen", "-y", "-P", "", "-f", str(key)])[0] == 0


def agent_socket(alias: Optional[str] = None,
                 names: Optional[Sequence[str]] = None) -> Optional[Path]:
    hit = _cache.get(alias)
    if hit is not None and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    answering = []  # type: List[Tuple[Path, List[str]]]
    for sock in candidate_sockets():
        rc, fps = _agent_list(sock)
        if rc in (0, 1):
            answering.append((sock, fps))
    chosen = answering[0][0] if answering else None
    if alias and answering:
        key = identity_file(alias, names)
        fp = fingerprint(Path(str(key) + ".pub")) if key is not None else None
        if fp:
            for sock, fps in answering:
                if fp in fps:
                    chosen = sock
                    break
    _cache[alias] = (time.monotonic(), chosen)
    return chosen


def forget(alias: Optional[str] = None) -> None:
    if alias is None:
        _cache.clear()
    else:
        _cache.pop(alias, None)


def load_sockets() -> List[Path]:
    """Load order: runtime-directory sockets only (design 7.4)."""
    rt = runtime_dir()
    if rt is None:
        return []
    cands = [rt / "gcr" / "ssh", rt / "openssh_agent", rt / "rb-ssh-agent"]
    inherited = os.environ.get("SSH_AUTH_SOCK")
    if inherited and Path(inherited).parent == rt:
        cands.append(Path(inherited))
    return _unique([p for p in cands if socket_ok(p)])


def load_socket() -> Optional[Path]:
    for sock in load_sockets():
        if agent_rc(sock) in (0, 1):
            return sock
    return None


def socket_refuses(path: Path) -> bool:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.settimeout(2.0)
        s.connect(str(path))
    except ConnectionRefusedError:
        return True
    except OSError:
        return False
    finally:
        s.close()
    return False


def start_agent() -> Path:
    rt = runtime_dir()
    if rt is None:
        raise RuntimeError("no usable runtime directory for an ssh-agent socket")
    target = rt / "rb-ssh-agent"
    if os.path.lexists(str(target)):
        if socket_ok(target) and socket_refuses(target):
            target.unlink()
        else:
            raise RuntimeError("%s exists and is not a dead socket owned by you" % target)
    rc, _, err = run(["ssh-agent", "-a", str(target)])
    if rc != 0:
        raise RuntimeError("ssh-agent did not start (%s)" % (err or rc))
    return target


def known_host(cfg: Dict[str, List[str]]) -> bool:
    alias = cfg.get("hostkeyalias")
    if alias:
        name = alias[0]
    else:
        host = (cfg.get("hostname") or [""])[0]
        port = (cfg.get("port") or ["22"])[0]
        name = host if port == "22" else "[%s]:%s" % (host, port)
    for f in known_hosts_files(cfg):
        if run(["ssh-keygen", "-F", name, "-f", str(f)])[0] == 0:
            return True
    return False


def keyscan(host: str, port: int, hashed: bool) -> Tuple[str, bytes]:
    for kind in ("ed25519", "ecdsa", "rsa"):
        argv = ["ssh-keyscan", "-t", kind, "-p", str(port)] + (["-H"] if hashed else []) + [host]
        rc, out, _ = run(argv, timeout=15.0)
        lines = [ln for ln in out.splitlines() if ln.strip() and not ln.startswith("#")]
        if rc == 0 and lines:
            return kind, ("\n".join(lines) + "\n").encode("utf-8")
    return "", b""


def scan_fingerprints(data: bytes) -> List[str]:
    fd, name = tempfile.mkstemp(prefix="rb-scan-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        rc, out, _ = run(["ssh-keygen", "-lf", name])
    finally:
        try:
            os.unlink(name)
        except OSError:
            pass
    if rc != 0:
        return []
    return [ln.split()[1] for ln in out.splitlines() if len(ln.split()) >= 2]


def route_source(host: str) -> Optional[str]:
    try:
        addr = socket.getaddrinfo(host, None)[0][4][0]
    except (OSError, IndexError):
        return None
    rc, out, _ = run(["ip", "-o", "route", "get", addr])
    if rc != 0:
        return None
    toks = out.split()
    if "src" in toks and toks.index("src") + 1 < len(toks):
        return toks[toks.index("src") + 1]
    return None


def systemctl_user(*args: str) -> Tuple[int, str]:
    rc, out, err = run(["systemctl", "--user"] + list(args))
    if rc != 0 and ("Failed to connect to bus" in err or "Failed to connect to bus" in out):
        return 127, ""  # no user manager: same answer as a missing systemctl
    return rc, out.strip()


def linger(user: str) -> Optional[bool]:
    rc, out, _ = run(["loginctl", "show-user", user, "-p", "Linger"])
    if rc != 0:
        return None
    val = out.strip().partition("=")[2].lower()
    return True if val == "yes" else False if val == "no" else None
