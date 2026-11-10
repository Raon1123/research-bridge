"""In-memory model of the hub's ssh environment, for the setup, doctor and service tests.

`install(monkeypatch, tmp_path)` replaces every external call of rb_host.sshenv with a recorder
driven by this model: an ssh config file (real, under tmp/home/.ssh), key files (real), known_hosts
(real), and in-memory agents. Placeholders only.
"""
from __future__ import annotations

import fnmatch
import hashlib
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from rb_host import configure, sshenv

DEFAULT_KNOWN = "~/.ssh/known_hosts ~/.ssh/known_hosts2"
BOOLISH = {"stricthostkeychecking": {"yes": "true", "no": "false"}}


def fp_of(blob: str) -> str:
    return "SHA256:" + hashlib.sha256(blob.encode()).hexdigest()[:20]


class Hub:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.home = tmp_path / "home"
        self.run_dir = tmp_path / "run"
        self.calls = []  # type: List[tuple]
        self.agents = {}  # type: Dict[str, Optional[List[str]]]
        self.unencrypted = set()  # type: set
        self.ssh_g_fail = False
        self.systemctl = {}  # type: Dict[tuple, tuple]
        self.linger_value = "no"
        self.route = "192.0.2.50"
        self.origin = ""
        self.scan = b""
        self.scan_kind = "ed25519"
        self.asks = []  # type: List[str]
        self.answer = True
        self.keyscan_calls = []  # type: List[tuple]
        self.route_calls = []  # type: List[str]
        self.started = []  # type: List[str]
        self.extra_hostnames = {}  # type: Dict[str, str]

    # -- files -------------------------------------------------------------
    @property
    def ssh_dir(self) -> Path:
        return self.home / ".ssh"

    @property
    def config_path(self) -> Path:
        return self.ssh_dir / "config"

    def write_config(self, text: str) -> None:
        self.ssh_dir.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(text, encoding="utf-8")

    def make_key(self, path: Path, comment: str = "research-bridge-hub") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("PRIVATE KEY PLACEHOLDER\n", encoding="utf-8")
        path.chmod(0o600)
        Path(str(path) + ".pub").write_text(
            "ssh-ed25519 AAAA%s %s\n" % (path.name.replace("_", ""), comment), encoding="utf-8")

    def pub_fp(self, path: Path) -> str:
        return fp_of(Path(str(path) + ".pub").read_text(encoding="utf-8").split()[1])

    def add_agent(self, name: str, fps: Optional[List[str]], runtime: bool = True) -> str:
        base = self.run_dir if runtime else self.tmp / "fwd"
        base.mkdir(parents=True, exist_ok=True)
        sock = str(base / name)
        self.agents[sock] = fps
        return sock

    def write_known_hosts(self, data: bytes) -> Path:
        self.ssh_dir.mkdir(parents=True, exist_ok=True)
        p = self.ssh_dir / "known_hosts"
        p.write_bytes(data)
        return p

    # -- ssh -G ------------------------------------------------------------
    def _blocks(self):
        text = self.config_path.read_text(encoding="utf-8") if self.config_path.is_file() else ""
        blocks = [(["*"], [])]
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            key = parts[0].lower()
            if key == "host":
                blocks.append((parts[1:], []))
            else:
                blocks[-1][1].append((key, parts[1:]))
        return blocks

    def ssh_g(self, alias: str) -> str:
        out = {}  # type: Dict[str, List[str]]
        for pats, opts in self._blocks():
            if not any(fnmatch.fnmatch(alias, p) for p in pats):
                continue
            for key, vals in opts:
                if key == "identityfile":
                    out.setdefault(key, []).extend(vals)
                elif key not in out:
                    out[key] = list(vals)
        out.setdefault("hostname", [self.extra_hostnames.get(alias, alias)])
        out.setdefault("port", ["22"])
        out.setdefault("user", ["hubuser"])
        out.setdefault("identityfile", ["~/.ssh/id_ed25519"])
        out.setdefault("identitiesonly", ["no"])
        out.setdefault("stricthostkeychecking", ["ask"])
        out.setdefault("userknownhostsfile", DEFAULT_KNOWN.split())
        out.setdefault("hashknownhosts", ["no"])
        lines = []
        for key, vals in out.items():
            vals = [BOOLISH.get(key, {}).get(v.lower(), v) for v in vals]
            if key == "identityfile":
                lines.extend("identityfile %s" % v for v in vals)
            else:
                lines.append("%s %s" % (key, " ".join(vals)))
        return "\n".join(lines) + "\n"

    # -- sshenv replacements -----------------------------------------------
    def run(self, argv, env=None, timeout=10.0, input=None):
        self.calls.append(("run", list(argv)))
        a = list(argv)
        sock = (env or {}).get("SSH_AUTH_SOCK", os.environ.get("SSH_AUTH_SOCK", ""))
        if a[:2] == ["ssh", "-G"]:
            if self.ssh_g_fail:
                return 255, "", "Bad owner or permissions"
            return 0, self.ssh_g(a[2]), ""
        if a[:2] == ["ssh-add", "-l"]:
            fps = self.agents.get(sock)
            if sock not in self.agents or fps is None:
                return 2, "", "Could not open a connection to your authentication agent."
            if not fps:
                return 1, "The agent has no identities.\n", ""
            return 0, "".join("256 %s comment (ED25519)\n" % f for f in fps), ""
        if a[:2] == ["ssh-keygen", "-lf"]:
            p = Path(a[2])
            if not p.is_file():
                return 1, "", "No such file"
            text = p.read_text(encoding="utf-8")
            if p.suffix == ".pub":
                return 0, "256 %s comment (ED25519)\n" % fp_of(text.split()[1]), ""
            fps = [fp_of(ln.split()[2]) for ln in text.splitlines() if len(ln.split()) >= 3]
            return 0, "".join("256 %s host (ED25519)\n" % f for f in fps), ""
        if a[:2] == ["ssh-keygen", "-y"]:
            return (0 if a[-1] in self.unencrypted else 1), "", ""
        if a[:2] == ["ssh-keygen", "-F"]:
            name, f = a[2], Path(a[a.index("-f") + 1])
            if f.is_file():
                for ln in f.read_text(encoding="utf-8").splitlines():
                    if ln.split() and name in ln.split()[0].split(","):
                        return 0, ln + "\n", ""
            return 1, "", ""
        if a[0] == "systemctl":
            return self.systemctl.get(tuple(a[2:]), (1, "", ""))
        if a[0] == "loginctl":
            return 0, "Linger=%s\n" % self.linger_value, ""
        if a[0] == "git" and "get-url" in a:
            return (0, self.origin + "\n", "") if self.origin else (1, "", "")
        raise AssertionError("unmodelled external command: %r" % (a,))

    def run_interactive(self, argv, env=None):
        self.calls.append(("interactive", list(argv), dict(env or {})))
        a = list(argv)
        if a[:3] == ["ssh-keygen", "-t", "ed25519"]:
            self.make_key(Path(a[a.index("-f") + 1]), a[a.index("-C") + 1])
            return 0
        if a[0] == "ssh-add":
            sock = (env or {}).get("SSH_AUTH_SOCK", "")
            if sock not in self.agents or self.agents[sock] is None:
                return 2
            self.agents[sock].append(self.pub_fp(Path(a[1])))
            return 0
        raise AssertionError("unmodelled interactive command: %r" % (a,))

    # -- higher-level replacements ----------------------------------------
    def agent_socket(self, alias=None):
        live = [Path(s) for s, f in self.agents.items() if f is not None]
        if alias and live:
            key = sshenv.identity_file(alias)
            if key is not None and Path(str(key) + ".pub").is_file():
                want = self.pub_fp(key)
                for s in live:
                    if want in self.agents[str(s)]:
                        return s
        return live[0] if live else None

    def _runtime_socks(self):
        return [Path(s) for s in self.agents if Path(s).parent == self.run_dir]

    def load_sockets(self):
        return self._runtime_socks()

    def load_socket(self):
        for s in self._runtime_socks():
            if self.agents[str(s)] is not None:
                return s
        return None

    def start_agent(self):
        self.started.append("rb-ssh-agent")
        sock = str(self.run_dir / "rb-ssh-agent")
        self.agents[sock] = []
        return Path(sock)

    def route_source(self, host):
        self.route_calls.append(host)
        return self.route

    def keyscan(self, host, port, hashed):
        self.keyscan_calls.append((host, port, hashed))
        return (self.scan_kind, self.scan) if self.scan else ("", b"")

    def ask(self, prompt):
        self.asks.append(prompt)
        return self.answer(prompt) if callable(self.answer) else self.answer

    def names(self, kind: str) -> List[list]:
        return [c[1] for c in self.calls if c[0] == kind]


def install(monkeypatch, tmp_path: Path) -> Hub:
    from rb_host import setup

    hub = Hub(tmp_path)
    hub.home.mkdir(exist_ok=True)
    monkeypatch.setattr(sshenv, "run", hub.run)
    monkeypatch.setattr(sshenv, "run_interactive", hub.run_interactive)
    monkeypatch.setattr(sshenv, "user_home", lambda: hub.home)
    monkeypatch.setattr(sshenv, "user_name", lambda: "hubuser")
    monkeypatch.setattr(sshenv, "agent_socket", hub.agent_socket)
    monkeypatch.setattr(sshenv, "load_socket", hub.load_socket)
    monkeypatch.setattr(sshenv, "load_sockets", hub.load_sockets)
    monkeypatch.setattr(sshenv, "start_agent", hub.start_agent)
    monkeypatch.setattr(sshenv, "route_source", hub.route_source)
    monkeypatch.setattr(sshenv, "keyscan", hub.keyscan)
    monkeypatch.setattr(setup, "ask", hub.ask)
    monkeypatch.setenv("RB_HOST_ROOT", str(tmp_path / "data"))
    monkeypatch.delenv("RB_HOST_CONFIG", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(configure, "REPO", tmp_path / "checkout")
    (tmp_path / "checkout").mkdir(exist_ok=True)
    return hub


NODE_BLOCKS = """Host rb-node1
    HostName <NODE_HOST>
    Port {port}
    User <NODE_USER>
    IdentityFile {key}
    IdentitiesOnly yes
    StrictHostKeyChecking yes

Host rb-node1-harness
    HostName <NODE_HOST>
    Port {port}
    User <NODE_USER>
    IdentityFile {hkey}
    IdentitiesOnly yes
    StrictHostKeyChecking yes
"""


def linked(hub: Hub, port: int = 22, keydir: Optional[Path] = None, keepalive: bool = False) -> Path:
    """Model a hub already linked (by the old scripts or by rb setup): config blocks, keys,
    known_hosts entry, host.json."""
    import json

    keydir = keydir or hub.ssh_dir / "research-bridge"
    key, hkey = keydir / "node1_ed25519", keydir / "node1_harness_ed25519"
    hub.make_key(key, "research-bridge-hub")
    hub.make_key(hkey, "research-bridge-harness")
    text = NODE_BLOCKS.format(port=port, key=key, hkey=hkey)
    if keepalive:
        text = text.replace("StrictHostKeyChecking yes\n",
                            "StrictHostKeyChecking yes\n    ServerAliveInterval 15\n    ServerAliveCountMax 3\n")
    hub.write_config(text)
    name = "<NODE_HOST>" if port == 22 else "[<NODE_HOST>]:%d" % port
    hub.write_known_hosts(("%s ssh-ed25519 AAAAhostkey\n" % name).encode())
    data = hub.tmp / "data"
    data.mkdir(exist_ok=True)
    hp = data / "host.json"
    hp.write_text(json.dumps({"nodes": {"node1": {"alias": "rb-node1",
                                                  "harness_alias": "rb-node1-harness"}}}),
                  encoding="utf-8")
    hp.chmod(0o600)
    (data / "withheld_patterns.json").write_text(json.dumps({"patterns": ["zz_placeholder_[0-9]+"]}),
                                                 encoding="utf-8")
    return hp
