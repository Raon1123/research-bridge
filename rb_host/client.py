"""SSH client for the node's serve-remote protocol."""
from __future__ import annotations

import base64
import hashlib
import os
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from rb_node.protocol import CHUNK, MAX_FILE, ProtocolError, encode, read_message


class TransportError(Exception):
    pass


class AgentLockedError(TransportError):
    pass


class RemoteError(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__("%s: %s" % (code, message) if message else code)
        self.code = code
        self.message = message


def default_argv(alias: str) -> List[str]:
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", alias]


class NodeClient:
    def __init__(self, alias: str, ssh_argv: Optional[List[str]] = None,
                 env: Optional[Dict[str, str]] = None) -> None:
        self.alias = alias
        self.argv = list(ssh_argv) if ssh_argv is not None else default_argv(alias)
        self.env = env
        self.proc = None  # type: Optional[subprocess.Popen]
        self._n = 0
        self._err = []  # type: List[bytes]
        self._err_thread = None  # type: Optional[threading.Thread]

    def __enter__(self) -> "NodeClient":
        env = None
        if self.env is not None:
            env = dict(os.environ)
            env.update(self.env)
        try:
            self.proc = subprocess.Popen(self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, env=env)
        except OSError as exc:
            raise TransportError("cannot start ssh: %s" % type(exc).__name__)
        self._err_thread = threading.Thread(target=self._drain, daemon=True)
        self._err_thread.start()
        return self

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
        if code == 255 and "Permission denied (publickey" in stderr:
            return AgentLockedError("ssh key unavailable (agent locked?)")
        return TransportError("connection to %s closed (exit %s)" % (self.alias, code))

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
        except ProtocolError as exc:
            raise TransportError("bad response: %s" % exc.code)
        if resp is None:
            raise self._transport_failure()
        if resp.get("ok") is not True:
            e = resp.get("error") if isinstance(resp.get("error"), dict) else {}
            raise RemoteError(str(e.get("code", "unknown")), str(e.get("message", "")))
        return resp.get("result")

    # -- files -------------------------------------------------------------
    def put_file(self, msg_id: str, path: Path, body: str = "",
                 from_session: Optional[str] = None) -> str:
        """Upload one file as a one-attachment message; returns the sanitized stored name."""
        path = Path(path)
        h = hashlib.sha256()
        size = 0
        with open(str(path), "rb") as fh:
            for chunk in iter(lambda: fh.read(CHUNK), b""):
                h.update(chunk)
                size += len(chunk)
        res = self.call("msg_begin", msg_id=msg_id, body=body, from_session=from_session,
                        attachments=[{"name": path.name, "bytes": size, "sha256": h.hexdigest()}])
        stored = res["names"][0]
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
        return stored

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
