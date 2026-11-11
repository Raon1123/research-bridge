"""SSH client for the node's serve-remote protocol."""
from __future__ import annotations

import base64
import hashlib
import os
import re
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import sshenv
from rb_node.protocol import CHUNK, MAX_FILE, ProtocolError, encode, read_message


CODES = ("no_agent", "agent_empty", "key_not_loaded", "node_refused_key", "host_key_unknown",
         "host_key_changed", "unknown_alias", "unreachable", "timeout", "closed")
AGENT_CODES = ("no_agent", "agent_empty", "key_not_loaded")
NODE_DOCTOR = ("on the node: rb-node doctor (node code before 0.2.0 has no doctor: "
               "run scripts/node-install.sh --update first, or rb-node config check)")


class TransportError(Exception):
    def __init__(self, message: str, code: str = "closed", hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.hint = hint

    def __str__(self) -> str:
        return "%s (next: %s)" % (self.message, self.hint) if self.hint else self.message


class AgentLockedError(TransportError):
    pass


class RemoteError(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__("%s: %s" % (code, message) if message else code)
        self.code = code
        self.message = message


def default_argv(alias: str) -> List[str]:
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3", alias]


def _error(code: str, message: str, hint: str) -> TransportError:
    cls = AgentLockedError if code in AGENT_CODES else TransportError
    return cls(message, code, hint)


def classify(code: Optional[int], stderr: str, alias: str, node: str,
             sock: Optional[Path]) -> TransportError:
    """Map an ssh failure to a TransportError (design 6.4). stderr is matched, never copied."""
    if code == 255:
        if "REMOTE HOST IDENTIFICATION HAS CHANGED" in stderr:
            return _error("host_key_changed", "host key of %s changed" % alias,
                          "do not connect; compare fingerprints on the node console, "
                          "see rb doctor --node %s" % node)
        if "host key is known for" in stderr or "Host key verification failed" in stderr:
            return _error("host_key_unknown", "no known_hosts entry for %s" % alias,
                          "rb setup --node %s" % node)
        m = re.search(r"Could not resolve hostname ([^\s:]+)", stderr)
        if m and m.group(1).lower() == alias.lower():
            return _error("unknown_alias", "ssh has no Host block for %s" % alias,
                          "rb setup --node %s --host HOST --user USER" % node)
        if ("Timeout, server" in stderr or "timed out during banner exchange" in stderr
                or "Connection timed out" in stderr):
            return _error("timeout", "%s did not answer in time" % alias,
                          "retry; if it repeats: rb doctor --node %s" % node)
        if ("Could not resolve host" in stderr or "Connection refused" in stderr
                or "No route to host" in stderr or "Network is unreachable" in stderr):
            return _error("unreachable", "cannot reach %s (network or address)" % alias,
                          "rb doctor --node %s" % node)
        if "Permission denied (publickey" in stderr:
            refused = _error(
                "node_refused_key", "%s refused the key" % alias,
                "%s (authorized_keys line and from=); --hub-from may be wrong if a router "
                "translates addresses" % NODE_DOCTOR)
            key = sshenv.identity_file(alias, sshenv.key_names(node))
            if key is not None and sshenv.key_unencrypted(key):
                return refused
            rc = sshenv.agent_rc(sock)
            if rc == 2:
                return _error("no_agent", "no ssh-agent reachable for %s" % alias, "rb agent")
            if rc == 1:
                return _error("agent_empty", "the ssh-agent holds no keys", "rb agent")
            fp = sshenv.fingerprint(Path(str(key) + ".pub")) if key is not None else None
            if fp is None or sock is None or fp in sshenv.agent_fingerprints(sock):
                return refused
            return _error("key_not_loaded", "the key for %s is not in the ssh-agent" % alias,
                          "rb agent --node %s" % node)
    return _error("closed", "connection to %s closed (exit %s)" % (alias, code), NODE_DOCTOR)


def normalize_hello(raw: Any) -> Dict[str, Any]:
    """Return a hello result with protocol-2 keys present (protocol 1 when the node omits them)."""
    if not isinstance(raw, dict):
        raise TransportError("bad response to hello (not an object)")
    protocol = raw.get("protocol")
    extra = raw.get("withheld_extra")
    return {
        "node": str(raw.get("node", "")),
        "version": str(raw.get("version", "")),
        "protocol": protocol if isinstance(protocol, int) and not isinstance(protocol, bool) else 1,
        "ops": raw["ops"] if isinstance(raw.get("ops"), list) else None,
        "state": raw["state"] if isinstance(raw.get("state"), dict) else None,
        "withheld_extra": extra if isinstance(extra, int) and not isinstance(extra, bool) else None,
    }


def _popen(argv: List[str], env: Optional[Dict[str, str]]) -> subprocess.Popen:
    return subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env)


class NodeClient:
    def __init__(self, alias: str, ssh_argv: Optional[List[str]] = None,
                 env: Optional[Dict[str, str]] = None, node: str = "") -> None:
        self.alias = alias
        self.node = node or (alias[3:] if alias.startswith("rb-") else alias)
        self.default_argv = ssh_argv is None
        self.argv = list(ssh_argv) if ssh_argv is not None else default_argv(alias)
        self.env = env
        self.agent_sock = None  # type: Optional[Path]
        self.proc = None  # type: Optional[subprocess.Popen]
        self._n = 0
        self._err = []  # type: List[bytes]
        self._err_thread = None  # type: Optional[threading.Thread]

    def __enter__(self) -> "NodeClient":
        extra = self.env
        if self.default_argv and self.env is None:
            self.agent_sock = sshenv.agent_socket(self.alias, sshenv.key_names(self.node))
            if self.agent_sock is not None:
                extra = {"SSH_AUTH_SOCK": str(self.agent_sock)}
        env = None
        if extra is not None:
            env = dict(os.environ)
            env.update(extra)
        try:
            self.proc = _popen(self.argv, env)
        except OSError as exc:
            raise TransportError("cannot start ssh (%s)" % type(exc).__name__, "closed",
                                 "install openssh-client")
        self._err_thread = threading.Thread(target=self._drain, daemon=True)
        self._err_thread.start()
        return self

    def hello(self) -> Dict[str, Any]:
        return normalize_hello(self.call("hello"))

    def _drain(self) -> None:
        try:
            for line in self.proc.stderr:  # type: ignore[union-attr]
                if len(self._err) < 200:
                    self._err.append(line)
        except (OSError, ValueError):
            pass

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        p = self.proc
        if p is None:
            return
        try:
            if p.stdin:
                p.stdin.close()
        except OSError:
            pass
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
        if self._err_thread:
            self._err_thread.join(timeout=2)
        for s in (p.stdout, p.stderr):
            try:
                if s:
                    s.close()
            except OSError:
                pass
        self.proc = None

    def _transport_failure(self) -> TransportError:
        p = self.proc
        code = None
        if p is not None:
            try:
                code = p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
                code = p.wait()
            if self._err_thread:
                self._err_thread.join(timeout=2)
        stderr = b"".join(self._err).decode("utf-8", "replace")
        sock = self.agent_sock
        if sock is None and self.env and self.env.get("SSH_AUTH_SOCK"):
            sock = Path(self.env["SSH_AUTH_SOCK"])
        exc = classify(code, stderr, self.alias, self.node, sock)
        if exc.code in AGENT_CODES or exc.code == "node_refused_key":
            sshenv.forget(self.alias)
        return exc

    def call(self, op: str, **args: Any) -> Any:
        if self.proc is None or self.proc.stdin is None or self.proc.stdout is None:
            raise TransportError("client not connected")
        self._n += 1
        rid = str(self._n)
        try:
            self.proc.stdin.write(encode({"id": rid, "op": op, "args": args}))
            self.proc.stdin.flush()
            resp = read_message(self.proc.stdout)
        except (OSError, ValueError):
            raise self._transport_failure()
        except ProtocolError:
            raise TransportError("bad response from %s" % self.alias, "closed", NODE_DOCTOR)
        if resp is None:
            raise self._transport_failure()
        if resp.get("ok") is not True:
            e = resp.get("error") if isinstance(resp.get("error"), dict) else {}
            raise RemoteError(str(e.get("code", "unknown")), str(e.get("message", "")))
        return resp.get("result")

    # -- files -------------------------------------------------------------
    def put_files(self, msg_id: str, paths: List[Path], body: str = "",
                  from_session: Optional[str] = None) -> List[str]:
        """Upload a message with its attachments (msg_begin, 1 MiB chunks, msg_commit); returns
        the sanitized stored names in the order of `paths`. An empty file is sent as one empty
        chunk with seq 0."""
        paths = [Path(p) for p in paths]
        metas = []
        for path in paths:
            h = hashlib.sha256()
            size = 0
            with open(str(path), "rb") as fh:
                for chunk in iter(lambda: fh.read(CHUNK), b""):
                    h.update(chunk)
                    size += len(chunk)
            metas.append({"name": path.name, "bytes": size, "sha256": h.hexdigest()})
        res = self.call("msg_begin", msg_id=msg_id, body=body, from_session=from_session,
                        attachments=metas)
        stored_names = list(res["names"])
        for path, stored in zip(paths, stored_names):
            with open(str(path), "rb") as fh:
                seq = 0
                while True:
                    data = fh.read(CHUNK)
                    if not data and seq > 0:
                        break
                    self.call("put_chunk", msg_id=msg_id, name=stored, seq=seq,
                              data_b64=base64.b64encode(data).decode("ascii"))
                    seq += 1
                    if len(data) < CHUNK:
                        break
        self.call("msg_commit", msg_id=msg_id)
        return stored_names

    def put_file(self, msg_id: str, path: Path, body: str = "",
                 from_session: Optional[str] = None) -> str:
        """Upload one file as a one-attachment message; returns the sanitized stored name."""
        return self.put_files(msg_id, [Path(path)], body, from_session)[0]

    def get_file(self, kind: str, ref: str, dest: Path) -> str:
        dest = Path(dest)
        part = dest.with_suffix(dest.suffix + ".part")
        dest.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        seq = 0
        want = None
        total = 0
        too_large = False
        stalled = False
        with open(str(part), "wb") as fh:
            while True:
                res = self.call("get_file", kind=kind, ref=ref, seq=seq)
                data = base64.b64decode(res["data_b64"])
                if not data and not res.get("eof"):
                    stalled = True  # an empty non-eof chunk makes no progress
                    break
                total += len(data)
                if total > MAX_FILE:  # hard rule 5 / PM-10: a node must not fill the disk
                    too_large = True
                    break
                fh.write(data)
                h.update(data)
                if res.get("eof"):
                    want = res.get("sha256")
                    break
                seq += 1
        if stalled:
            part.unlink()
            raise RemoteError("stalled", "node sent an empty chunk without eof")
        if too_large:
            part.unlink()
            raise RemoteError("too_large", "download exceeds %d bytes" % MAX_FILE)
        got = h.hexdigest()
        if want != got:
            part.unlink()
            raise TransportError("sha256 mismatch for %s" % dest.name)
        os.replace(str(part), str(dest))
        return got
