"""Line-delimited JSON wire protocol shared by host and node (stdlib only)."""
from __future__ import annotations

import json
from typing import Any, BinaryIO, Optional

CHUNK = 1 << 20
MAX_FILE = 50 * 1024 * 1024


class ProtocolError(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


def encode(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


def read_message(stream: BinaryIO, max_line: int = 4 * CHUNK) -> Optional[dict]:
    line = stream.readline(max_line + 1)
    if not line:
        return None
    if len(line) > max_line:
        raise ProtocolError("line_too_long", "message exceeds %d bytes" % max_line)
    try:
        msg = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ProtocolError("bad_json", str(exc))
    if not isinstance(msg, dict):
        raise ProtocolError("bad_json", "message is not an object")
    return msg


def ok(req_id: str, result: Any) -> dict:
    return {"id": req_id, "ok": True, "result": result}


def err(req_id: str, code: str, message: str) -> dict:
    return {"id": req_id, "ok": False, "error": {"code": code, "message": message}}
