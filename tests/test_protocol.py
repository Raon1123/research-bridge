from __future__ import annotations

import io

import pytest

from rb_node import protocol


def test_round_trip_korean():
    obj = {"id": "1", "op": "send", "args": {"text": "안녕하세요 연구 브리지"}}
    data = protocol.encode(obj)
    assert data.endswith(b"\n")
    assert "안녕하세요".encode("utf-8") in data
    assert protocol.read_message(io.BytesIO(data)) == obj


def test_read_message_none_on_eof():
    assert protocol.read_message(io.BytesIO(b"")) is None


def test_over_long_line_raises():
    stream = io.BytesIO(b"x" * 100 + b"\n")
    with pytest.raises(protocol.ProtocolError) as ei:
        protocol.read_message(stream, max_line=10)
    assert ei.value.code == "line_too_long"


def test_err_and_ok_shapes():
    e = protocol.err("1", "denied", "x")
    assert e["error"]["code"] == "denied"
    assert e["ok"] is False and e["id"] == "1"
    o = protocol.ok("2", {"a": 1})
    assert o == {"id": "2", "ok": True, "result": {"a": 1}}
