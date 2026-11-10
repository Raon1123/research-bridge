"""rb_host.webaccess: one-time keys exchanged for session tokens; hashes only on disk."""
from __future__ import annotations

import json
import os
import stat
import threading
from pathlib import Path

import pytest

from rb_host import webaccess
from rb_host.config import HostConfig


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def cfg(tmp_path):
    return HostConfig(nodes={}, data_root=str(tmp_path / "data"))


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(webaccess, "_now", c)
    return c


def access(cfg):
    return Path(cfg.data_root) / "web" / "access.json"


def test_issue_redeem_session(cfg, clock):
    key = webaccess.issue_key(cfg, 10, 12)
    assert webaccess.valid_syntax(key) and webaccess.counts(cfg) == (1, 0)
    token, secs = webaccess.redeem(cfg, key)
    assert secs == 12 * 3600 and token != key and webaccess.valid_syntax(token)
    assert webaccess.session_ok(cfg, token)
    assert not webaccess.session_ok(cfg, key)
    assert webaccess.counts(cfg) == (0, 1)
    assert webaccess.redeem(cfg, key) is None  # single use


def test_only_hashes_on_disk(cfg, clock):
    key = webaccess.issue_key(cfg, 10, 12)
    token, _ = webaccess.redeem(cfg, key)
    text = access(cfg).read_text(encoding="utf-8")
    assert key not in text and token not in text
    data = json.loads(text)
    assert data["keys"] == [] and data["sessions"][0]["sha256"] == webaccess._hash(token)


def test_modes(cfg, clock):
    webaccess.issue_key(cfg, 10, 12)
    d = access(cfg).parent
    assert stat.S_IMODE(d.stat().st_mode) == 0o700
    assert stat.S_IMODE(access(cfg).stat().st_mode) == 0o600
    assert stat.S_IMODE((d / "access.lock").stat().st_mode) == 0o600
    assert sorted(p.name for p in d.iterdir()) == ["access.json", "access.lock"]


def test_expired_key_and_session(cfg, clock):
    key = webaccess.issue_key(cfg, 1, 1)
    clock.t += 61
    assert webaccess.redeem(cfg, key) is None and webaccess.counts(cfg) == (0, 0)
    key = webaccess.issue_key(cfg, 1, 1)
    token, _ = webaccess.redeem(cfg, key)
    clock.t += 3599
    assert webaccess.session_ok(cfg, token)
    clock.t += 2
    assert not webaccess.session_ok(cfg, token) and webaccess.counts(cfg) == (0, 0)


def test_malformed_values_rejected(cfg, clock):
    key = webaccess.issue_key(cfg, 10, 12)
    for bad in ("", "short", key + "!", key + " ", "A" * 129, None, 5, b"x" * 30, "é" * 30):
        assert webaccess.redeem(cfg, bad) is None
        assert not webaccess.session_ok(cfg, bad)
    assert webaccess.counts(cfg) == (1, 0)


def test_revoke(cfg, clock):
    webaccess.issue_key(cfg, 10, 12)
    webaccess.issue_key(cfg, 10, 12)
    token, _ = webaccess.redeem(cfg, webaccess.issue_key(cfg, 10, 12))
    assert webaccess.revoke_all(cfg) == (2, 1)
    assert not webaccess.session_ok(cfg, token) and webaccess.counts(cfg) == (0, 0)
    assert webaccess.revoke_all(cfg) == (0, 0)


def test_caps_drop_the_entry_that_expires_first(cfg, clock):
    keys = []
    for i in range(webaccess.MAX_KEYS + 3):
        keys.append(webaccess.issue_key(cfg, 1 + i % 5, 12))
        clock.t += 0.001
    assert webaccess.counts(cfg)[0] == webaccess.MAX_KEYS
    assert len(json.loads(access(cfg).read_text())["keys"]) == webaccess.MAX_KEYS
    assert webaccess.redeem(cfg, keys[-1]) is not None  # a late, long key survives
    tokens = []
    for _ in range(webaccess.MAX_SESSIONS + 2):
        k = webaccess.issue_key(cfg, 10, 12)
        tokens.append(webaccess.redeem(cfg, k)[0])
        clock.t += 1
    assert webaccess.counts(cfg)[1] == webaccess.MAX_SESSIONS
    assert not webaccess.session_ok(cfg, tokens[0]) and webaccess.session_ok(cfg, tokens[-1])


@pytest.mark.parametrize("content", ["", "not json", "[]", "null", '{"keys": 5}',
                                     '{"keys": [{"sha256": 1}], "sessions": ["x", null]}',
                                     '{"keys": [{"sha256": "a", "expires_at": "soon"}]}',
                                     "\x00\xff"])
def test_malformed_file_denies(cfg, clock, content):
    access(cfg).parent.mkdir(parents=True)
    access(cfg).write_text(content, encoding="utf-8", errors="ignore")
    assert webaccess.counts(cfg) == (0, 0)
    assert webaccess.redeem(cfg, "A" * 43) is None
    assert not webaccess.session_ok(cfg, "A" * 43)
    assert webaccess.revoke_all(cfg) == (0, 0)
    assert webaccess.redeem(cfg, webaccess.issue_key(cfg, 10, 12)) is not None  # self-heals


def test_missing_file_and_unreadable_dir(cfg, clock):
    assert webaccess.counts(cfg) == (0, 0)
    assert webaccess.redeem(cfg, "A" * 43) is None
    assert not webaccess.session_ok(cfg, "A" * 43)
    # data_root is a file: nothing can be created, redeem denies without raising
    blocked = Path(cfg.data_root).parent / "file"
    blocked.write_text("x")
    bad = HostConfig(nodes={}, data_root=str(blocked / "data"))
    assert webaccess.redeem(bad, "A" * 43) is None


def test_concurrent_redeem_gives_one_session(cfg):
    key = webaccess.issue_key(cfg, 10, 12)
    start = threading.Barrier(8)
    out = []

    def go():
        start.wait()
        out.append(webaccess.redeem(cfg, key))
    ts = [threading.Thread(target=go) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(30)
    assert sum(1 for o in out if o is not None) == 1
    assert webaccess.counts(cfg) == (0, 1)
