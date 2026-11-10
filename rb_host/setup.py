"""`rb setup` and `rb agent`: link a node in nine idempotent steps (design 6.2).

Edits outside the repository (keys, ~/.ssh/config, known_hosts, agent memory) happen only after a
y typed at a terminal; the cli handler checks the terminal before calling main(). Nothing here
writes ~/.claude.json or ~/.bashrc. Every external command goes through rb_host.sshenv.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from rb_node.configure import ConfigError, git_exposure, read_json

from . import configure, doctor, jobs, sshenv
from .config import HostConfig, load_host_config

STEP_TITLES = ("data root and host.json", "node entry", "keys", "ssh config blocks", "host key",
               "agent and keys", "node command", "MCP registration", "doctor")


def ask(prompt: str) -> bool:
    sys.stdout.write(prompt)
    sys.stdout.flush()
    return sys.stdin.readline().strip().lower() in ("y", "yes")


@dataclass
class Args:
    node: str
    host: str = ""
    port: int = 22
    user: str = ""
    keydir: str = ""
    hub_from: str = ""
    research_root: str = ""
    print_only: bool = False
    alias: str = ""
    harness_alias: str = ""
    cache: Dict[str, Dict[str, List[str]]] = field(default_factory=dict, repr=False)


def _stamp() -> str:
    return time.strftime("%Y%m%d%H%M%S")


def _say(msg: str) -> None:
    print("  " + msg)


def _ssh(a: Args, alias: str, fresh: bool = False) -> Dict[str, List[str]]:
    if fresh or alias not in a.cache:
        a.cache[alias] = sshenv.ssh_config(alias)
    return a.cache[alias]


def _defined(cfg: Dict[str, List[str]], alias: str) -> bool:
    host = cfg.get("hostname")
    return bool(host) and host[0].lower() != alias.lower()


def _tilde(path: Path) -> str:
    home = sshenv.user_home()
    try:
        return "~/" + path.relative_to(home).as_posix()
    except ValueError:
        return str(path)


def _unsafe_target(path: Path) -> Optional[str]:
    """Why setup must not write `path` itself, or None."""
    if os.path.islink(str(path)):
        return ("%s is a symbolic link (a rename would replace the link, and writing through it "
                "would put the text into the link's target)" % path)
    reason = git_exposure(path.resolve())
    if reason:
        return "%s (git would track it)" % reason
    return None


def _backup(path: Path) -> Optional[Path]:
    if not path.is_file():
        return None
    bak = path.with_name("%s.bak.%s" % (path.name, _stamp()))
    shutil.copy2(str(path), str(bak))
    _say("backup: %s" % bak)
    return bak


def _atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, str(path))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _cfg() -> HostConfig:
    try:
        return load_host_config(configure.host_path())
    except (OSError, ValueError):
        return HostConfig()


def _key_paths(a: Args) -> Tuple[Path, Path]:
    names = ("%s_ed25519" % a.node, "%s_harness_ed25519" % a.node)
    if a.keydir:
        kd = sshenv.expand_path(a.keydir) or Path(a.keydir).absolute()
        return kd / names[0], kd / names[1]
    out = []
    for alias, name in zip((a.alias, a.harness_alias), names):
        cfg = _ssh(a, alias)
        files = cfg.get("identityfile") or []
        key = sshenv.expand_path(files[0]) if files and _defined(cfg, alias) else None
        out.append(key or sshenv.user_ssh_dir() / "research-bridge" / name)
    return out[0], out[1]


# ------------------------------------------------------------------ steps

def step_host_json(a: Args) -> str:
    path = configure.host_path()
    if path.exists():
        try:
            read_json(path)
        except ConfigError as exc:
            msg = str(exc)
            print("error: %s; fix it or move it away, then run rb setup" % msg)
            return "failed: %s" % msg
        root = Path(_cfg().data_root)
        if root.is_dir():
            _say("%s exists" % path)
            return "skipped"
        if a.print_only:
            _say("would create the data root %s" % root)
            return "printed"
        root.mkdir(parents=True, exist_ok=True)
        os.chmod(str(root), 0o700)
        _say("created the data root %s" % root)
        return "done"
    root = Path(configure_root())
    if a.print_only:
        _say("would create the data root %s and %s" % (root, path))
        return "printed"
    try:
        root.mkdir(parents=True, exist_ok=True)
        os.chmod(str(root), 0o700)
        configure.init()
    except (ConfigError, OSError) as exc:
        print("error: %s" % exc)
        return "failed: %s" % exc
    _say("wrote %s" % path)
    return "done"


def configure_root() -> str:
    from .config import default_root
    return default_root()


def step_node_entry(a: Args) -> str:
    path = configure.host_path()
    nodes = {}  # type: dict
    if path.is_file():
        try:
            nodes = read_json(path).get("nodes") or {}
        except ConfigError:
            nodes = {}
    entry = nodes.get(a.node)
    if isinstance(entry, dict):
        al, hal = entry.get("alias") or "rb-" + a.node, entry.get("harness_alias") or "rb-%s-harness" % a.node
        if (al, hal) != ("rb-" + a.node, "rb-%s-harness" % a.node):
            _say("node %s already has the aliases %s and %s; using them" % (a.node, al, hal))
        else:
            _say("node %s is in host.json" % a.node)
        return "skipped"
    if a.print_only or not path.is_file():
        _say("would add node %s with the aliases %s and %s" % (a.node, a.alias, a.harness_alias))
        return "printed"
    try:
        configure.add_node(a.node, a.alias, a.harness_alias)
    except ConfigError as exc:
        print("error: %s" % exc)
        return "failed: %s" % exc
    _say("added node %s (aliases %s, %s)" % (a.node, a.alias, a.harness_alias))
    return "done"


def step_keys(a: Args) -> str:
    bridge, harness = _key_paths(a)
    todo = []  # type: List[Tuple[Path, str]]
    broken = []
    for key, comment in ((bridge, "research-bridge-hub"), (harness, "research-bridge-harness")):
        pub = Path(str(key) + ".pub")
        if key.is_file() and pub.is_file():
            continue
        if key.is_file():
            broken.append("public key missing for %s; run: ssh-keygen -y -f %s > %s" % (key, key, pub))
        else:
            todo.append((key, comment))
    for line in broken:
        print("error: " + line)
    if broken:
        return "failed: public key missing"
    if not todo:
        _say("both key pairs exist")
        return "skipped"
    reason = git_exposure(todo[0][0].parent / "x")
    if reason:
        print("error: refusing to create keys here: %s" % reason)
        return "failed: %s" % reason
    names = ", ".join(str(k) for k, _ in todo)
    if a.print_only:
        for key, comment in todo:
            _say("would run: ssh-keygen -t ed25519 -f %s -C %s" % (key, comment))
        return "printed"
    if not ask("Generate %s? [y/N] " % names):
        _say("keys not generated; rerun rb setup --node %s when you want them" % a.node)
        return "failed: keys not generated"
    kd = todo[0][0].parent
    kd.mkdir(parents=True, exist_ok=True)
    os.chmod(str(kd), 0o700)
    _say("ssh-keygen asks for a passphrase twice per key; the same passphrase may be used for both")
    for key, comment in todo:
        if sshenv.run_interactive(["ssh-keygen", "-t", "ed25519", "-f", str(key), "-C", comment]) != 0:
            return "failed: ssh-keygen did not finish for %s" % key
    return "done"


def _block(alias: str, a: Args, key: Path) -> str:
    return ("Host %s\n    HostName %s\n    Port %d\n    User %s\n    IdentityFile %s\n"
            "    IdentitiesOnly yes\n    StrictHostKeyChecking yes\n    ServerAliveInterval 15\n"
            "    ServerAliveCountMax 3\n" % (alias, a.host, a.port, a.user, _tilde(key)))


def _differences(alias: str, cfg: Dict[str, List[str]], a: Args, key: Path) -> List[str]:
    def first(k: str) -> str:
        v = cfg.get(k)
        return v[0] if v else "unset"

    out = []  # type: List[str]
    pairs = [("hostname", first("hostname"), a.host, first("hostname").lower() == a.host.lower()),
             ("port", first("port"), str(a.port), first("port") == str(a.port)),
             ("user", first("user"), a.user, first("user") == a.user)]
    files = cfg.get("identityfile") or []
    got = sshenv.expand_path(files[0]) if files else None
    pairs.append(("identityfile", files[0] if files else "unset", str(key), got == key))
    pairs.append(("identitiesonly", first("identitiesonly"), "yes", first("identitiesonly").lower() == "yes"))
    pairs.append(("stricthostkeychecking", first("stricthostkeychecking"), "true",
                  first("stricthostkeychecking").lower() in ("true", "yes")))
    for opt, have, want, same in pairs:
        if not same:
            out.append("%s: %s is %s, expected %s" % (alias, opt, have, want))
    return out


def step_ssh_config(a: Args) -> str:
    bridge, harness = _key_paths(a)
    pairs = [(a.alias, bridge), (a.harness_alias, harness)]
    add = []  # type: List[Tuple[str, Path]]
    diffs = []  # type: List[str]
    for alias, key in pairs:
        cfg = _ssh(a, alias)
        if _defined(cfg, alias):
            diffs.extend(_differences(alias, cfg, a, key))
        else:
            add.append((alias, key))
    for line in diffs:
        _say(line)
    if diffs:
        _say("these aliases are already defined, so setup does not rewrite them; merge this by hand:")
        for alias, key in pairs:
            print(_block(alias, a, key))
    if not add:
        if not diffs:
            _say("ssh config already defines both aliases with the given values")
        return "skipped" if not diffs else "printed"
    text = "# research-bridge: rb setup %s\n" % time.strftime("%Y-%m-%d") + "\n".join(
        _block(al, a, k) for al, k in add)
    target = sshenv.user_ssh_dir() / "config"
    why = _unsafe_target(target)
    if a.print_only or why:
        if why:
            _say("not writing %s: %s" % (target, why))
        _say("add this to %s%s:" % (target, "" if why else " (would append)"))
        print(text)
        return "printed"
    _say("these blocks are missing from %s:" % target)
    print(text)
    if not ask("Append to %s? [y/N] " % target):
        _say("not written")
        return "skipped"
    old = target.read_bytes() if target.is_file() else b""
    _backup(target)
    sep = b"" if not old or old.endswith(b"\n") else b"\n"
    _atomic_write(target, old + sep + (b"\n" if old else b"") + text.encode("utf-8"))
    os.chmod(str(target.parent), 0o700)
    for alias, key in add:
        for line in _differences(alias, _ssh(a, alias, fresh=True), a, key):
            _say("overridden by an earlier setting in your ssh config (OpenSSH uses the first value "
                 "it reads): " + line)
    return "done"


def step_host_key(a: Args, keys_generated: bool) -> str:
    cfg = dict(_ssh(a, a.alias))
    cfg["hostname"] = [a.host]
    cfg["port"] = [str(a.port)]
    if sshenv.known_host(cfg):
        _say("known_hosts already has an entry for %s" % a.alias)
        return "skipped"
    hashed = (cfg.get("hashknownhosts") or ["no"])[0].lower() == "yes"
    flags = ("-H " if hashed else "")
    scan_cmd = "ssh-keyscan -t ed25519 %s-p %d %s" % (flags, a.port, a.host)
    if a.print_only:
        _say("no known_hosts entry for %s yet; after the node command has run, setup would scan once "
             "(%s), show the fingerprint and ask" % (a.alias, scan_cmd))
        return "printed"
    if keys_generated:
        _say("host key: run the node command below first; it prints the node's host key fingerprints; "
             "then run: rb setup --node %s" % a.node)
        return "printed"
    files = sshenv.known_hosts_files(cfg)
    kind, data = sshenv.keyscan(a.host, a.port, hashed)
    if not data:
        _say("could not read the host key; check that %s is reachable" % a.alias)
        return "printed"
    _say("scanned host key of %s (%s):" % (a.alias, kind))
    for fp in sshenv.scan_fingerprints(data):
        _say("  " + fp)
    _say("compare it with the line of the same type that scripts/node-install.sh printed on the node "
         "(or ssh-keygen -lf /etc/ssh/ssh_host_%s_key.pub run on the node console)" % kind)
    if not files:
        _say("no usable known_hosts file in ssh -G output; add these lines yourself:")
        sys.stdout.write(data.decode("utf-8", "replace"))
        return "printed"
    target = files[0]
    why = _unsafe_target(target)
    if why:
        _say("not writing %s: %s; add these lines yourself:" % (target, why))
        sys.stdout.write(data.decode("utf-8", "replace"))
        return "printed"
    if not ask("If you have not run the node command yet, answer n and run rb setup --node %s "
               "again after it. Does the fingerprint equal the node's? Append to %s? [y/N] "
               % (a.node, target)):
        _say("If the fingerprints differ, do not connect. Check the node's key on its console "
             "(ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub) and find the cause before running "
             "rb setup again.")
        return "skipped"
    old = target.read_bytes() if target.is_file() else b""
    _backup(target)
    sep = b"\n" if old and not old.endswith(b"\n") else b""
    _atomic_write(target, old + sep + data)
    return "done"


def _load_socket() -> Path:
    return sshenv.load_socket() or sshenv.start_agent()


def _load_keys(sock: Path, keys: List[Path]) -> Tuple[int, int]:
    """ssh-add every key not yet listed. Returns (added, failed)."""
    added = failed = 0
    for key in keys:
        fp = sshenv.fingerprint(Path(str(key) + ".pub"))
        if fp and fp in sshenv.agent_fingerprints(sock):
            _say("already loaded: %s" % key)
            continue
        if sshenv.run_interactive(["ssh-add", str(key)], env={"SSH_AUTH_SOCK": str(sock)}) == 0:
            added += 1
        else:
            failed += 1
            _say("ssh-add failed for %s" % key)
    return added, failed


def step_agent(a: Args) -> str:
    keys = [k for k in _key_paths(a) if k.is_file()]
    if not keys:
        _say("no key files yet; nothing to load")
        return "skipped"
    if a.print_only:
        sock = sshenv.load_socket()
        _say("would load %s into %s" % (", ".join(str(k) for k in keys),
                                        sock or "a new ssh-agent at $XDG_RUNTIME_DIR/rb-ssh-agent"))
        return "printed"
    try:
        sock = _load_socket()
    except RuntimeError as exc:
        print("error: %s" % exc)
        return "failed: %s" % exc
    added, failed = _load_keys(sock, keys)
    if failed:
        return "failed: ssh-add did not finish"
    return "done" if added else "skipped"


def _repo_url() -> str:
    rc, out, _ = sshenv.run(["git", "-C", str(configure.REPO), "remote", "get-url", "origin"])
    url = out.strip()
    if rc == 0 and url.startswith("https://") and "@" not in urlparse(url).netloc:
        return url
    return "<REPO_URL>"


def node_command(a: Args, bridge_pub: str, harness_pub: str, hub_from: str, withheld: bool,
                 repo_url: str) -> str:
    lines = ["On the node, in a research-bridge checkout (git clone %s; cd research-bridge):" % repo_url,
             "", "  scripts/node-install.sh \\"]
    if a.research_root:
        lines.append("    --research-root %s \\" % shlex_quote(a.research_root))
    lines += ["    --hub-key '%s' \\" % bridge_pub, "    --harness-key '%s' \\" % harness_pub,
              "    --hub-from %s%s --apply-authorized-keys" % (
                  hub_from, " --withheld-file ~/withheld-patterns.json" if withheld else "")]
    return "\n".join(lines)


def shlex_quote(s: str) -> str:
    import shlex
    return shlex.quote(s)


def step_node_command(a: Args) -> str:
    bridge, harness = _key_paths(a)
    pubs = []
    for key, comment in ((bridge, "research-bridge-hub"), (harness, "research-bridge-harness")):
        try:
            pubs.append(Path(str(key) + ".pub").read_text(encoding="utf-8").strip())
        except OSError:
            if not a.print_only:
                print("error: public key missing: %s.pub" % key)
                return "failed: public key missing"
            pubs.append("ssh-ed25519 AAAA... %s" % comment)
    note = ""
    if a.hub_from:
        hub_from = a.hub_from
    elif a.print_only:
        hub_from, note = "<HUB_ADDR>", "fill in --hub-from: the address of this hub as the node sees it"
    else:
        src = sshenv.route_source(a.host)
        if src:
            hub_from = src
            note = ("the node will see this hub as %s (from ip route get); if a router translates "
                    "addresses between the two machines, pass --hub-from with the address the node "
                    "sees" % src)
        else:
            hub_from, note = "<HUB_ADDR>", ("could not derive the hub address with ip route get; "
                                             "fill in --hub-from with the address the node sees")
    wpath = Path(_cfg().withheld_patterns_file)
    withheld = wpath.is_file()
    print()
    print(node_command(a, pubs[0], pubs[1], hub_from, withheld, _repo_url()))
    print()
    if note:
        _say(note)
    if withheld:
        _say("Before running it, copy %s to ~/withheld-patterns.json on the node." % wpath)
    else:
        _say("The hub withheld pattern file does not exist (%s): the node would use only the five "
             "fallback patterns. Create it, then rerun rb setup." % wpath)
    _say("At the end it prints the node's host key fingerprints. Then run on the hub: "
         "rb setup --node %s" % a.node)
    _say("which shows the fingerprint it scanned; answer y only if it equals the line of the same type.")
    return "printed"


def mcp_step(a: Args) -> str:
    checkout = configure.REPO
    found, problem = configure.mcp_registered(checkout)
    entry = configure.registered_entry(checkout) or {}
    if isinstance(entry.get("env"), dict) and "SSH_AUTH_SOCK" in entry["env"]:
        _say("the MCP entry carries env.SSH_AUTH_SOCK; it is no longer needed (agent discovery finds "
             "the agent) and may stay")
    if "/.claude/worktrees/" in checkout.as_posix() + "/":
        _say("warning: this checkout lies in a git worktree, which is deleted later; run the command "
             "from the main checkout")
    if shutil.which("uv") is None:
        _say("warning: uv is not on PATH; the command below uses the bare name uv")
    if found and not problem:
        _say("MCP server research-bridge is registered")
        return "skipped"
    if found:
        _say("the registered MCP entry has a problem: %s" % (
            "it points at a missing path" if problem == "missing path" else "it points at a worktree"))
        _say("remove it (claude mcp remove research-bridge) and register again:")
    else:
        _say("register the MCP server by running this yourself (rb never edits ~/.claude.json):")
    print()
    print(configure.mcp_command())
    print()
    return "printed"


def step_doctor(a: Args) -> str:
    code = doctor.main(a.node, offline_only=a.print_only)
    if not a.print_only:
        _say("the online part is expected to fail until the node command has been run; afterwards "
             "run: rb setup --node %s" % a.node)
    return "done"


# ------------------------------------------------------------------ main

def _resolve(a: Args) -> int:
    a.alias, a.harness_alias = "rb-" + a.node, "rb-%s-harness" % a.node
    path = configure.host_path()
    if path.is_file():
        try:
            entry = (read_json(path).get("nodes") or {}).get(a.node)
        except ConfigError:
            entry = None
        if isinstance(entry, dict):
            if isinstance(entry.get("alias"), str) and entry["alias"]:
                a.alias = entry["alias"]
            if isinstance(entry.get("harness_alias"), str) and entry["harness_alias"]:
                a.harness_alias = entry["harness_alias"]
    if not (a.host and a.user):
        cfg = _ssh(a, a.alias)
        if not _defined(cfg, a.alias):
            print("error: give --host and --user on the first run")
            return 2
        if not a.host:
            a.host = cfg["hostname"][0]
            a.port = int((cfg.get("port") or [str(a.port)])[0])
        if not a.user:
            a.user = (cfg.get("user") or [""])[0]
    return 0


def main(a: Args) -> int:
    code = _resolve(a)
    if code:
        return code
    results = {}  # type: Dict[int, str]
    steps = [("1", lambda: step_host_json(a)), ("2", lambda: step_node_entry(a)),
             ("3", lambda: step_keys(a)), ("4", lambda: step_ssh_config(a)),
             ("5", lambda: step_host_key(a, results.get(3) == "done")),
             ("6", lambda: step_agent(a)), ("7", lambda: step_node_command(a)),
             ("8", lambda: mcp_step(a)), ("9", lambda: step_doctor(a))]
    for i, (_, fn) in enumerate(steps, 1):
        print("step %d/9 %s" % (i, STEP_TITLES[i - 1]))
        results[i] = fn()
        _say("-> %s" % results[i])
        if i == 1 and results[i].startswith("failed"):
            return 1
        if i == 1:
            a.cache.clear()
    failed = [i for i in range(1, 9) if results[i].startswith("failed")]
    if failed:
        print("setup did not finish: %s" % "; ".join("step %d %s" % (i, results[i]) for i in failed))
        return 1
    print("setup finished; steps that print a command leave it to you to run")
    return 0


def agent_main(node: Optional[str]) -> int:
    try:
        cfg = jobs.load_cfg()
    except (FileNotFoundError, ValueError) as exc:
        print(configure.host_json_error(exc))
        return 1
    names = [node] if node else sorted(cfg.nodes)
    if node and node not in cfg.nodes:
        print("error: unknown node: %s" % node)
        return 1
    if not names:
        print("error: no node in host.json; run: rb setup --node NAME --host HOST --user USER")
        return 1
    keys = []  # type: List[Path]
    code = 0
    for n in names:
        entry = cfg.nodes.get(n) if isinstance(cfg.nodes.get(n), dict) else {}
        for alias, required in ((entry.get("alias") or "rb-" + n, True),
                                (entry.get("harness_alias") or "rb-%s-harness" % n, False)):
            c = sshenv.ssh_config(alias)
            if not _defined(c, alias):
                print("%s: ssh has no Host block for %s%s" % (
                    "error" if required else "note", alias, "" if required else " (harness channel only)"))
                code = code or (1 if required else 0)
                continue
            files = c.get("identityfile") or []
            key = sshenv.expand_path(files[0]) if files else None
            if key is None or not key.is_file():
                print("%s: key file missing: %s" % ("error" if required else "note", key or "(none)"))
                code = code or (1 if required else 0)
                continue
            keys.append(key)
    if not keys:
        return code or 1
    try:
        sock = _load_socket()
    except RuntimeError as exc:
        print("error: %s" % exc)
        return 1
    _, failed = _load_keys(sock, keys)
    print("agent: %s" % sock)
    print("for other ssh commands in this shell (rb harness): export SSH_AUTH_SOCK=%s" % sock)
    return 1 if failed else code
