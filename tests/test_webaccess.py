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
    (tmp_path / "data").mkdir()
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


BAD_FILES = ["", "not json", "[]", "null", "\x00\xff"]


@pytest.mark.parametrize("content", BAD_FILES)
def test_corrupt_file_denies_aborts_writes_and_only_revoke_repairs(cfg, clock, content):
    access(cfg).parent.mkdir(parents=True)
    access(cfg).write_text(content, encoding="utf-8", errors="ignore")
    before = access(cfg).read_bytes()
    assert webaccess.counts(cfg) == (0, 0)
    assert webaccess.redeem(cfg, "A" * 43) is None
    assert not webaccess.session_ok(cfg, "A" * 43)
    with pytest.raises(webaccess.AccessError):
        webaccess.issue_key(cfg, 10, 12)
    assert access(cfg).read_bytes() == before
    assert webaccess.revoke_all(cfg) == (0, 0)  # writes a fresh file regardless
    assert json.loads(access(cfg).read_text()) == {"keys": [], "sessions": []}
    assert webaccess.redeem(cfg, webaccess.issue_key(cfg, 10, 12)) is not None


@pytest.mark.parametrize("content", ['{"keys": 5}',
                                     '{"keys": [{"sha256": 1}], "sessions": ["x", null]}',
                                     '{"keys": [{"sha256": "a", "expires_at": "soon"}]}'])
def test_malformed_entries_are_dropped(cfg, clock, content):
    access(cfg).parent.mkdir(parents=True)
    access(cfg).write_text(content, encoding="utf-8")
    assert webaccess.counts(cfg) == (0, 0)
    assert webaccess.redeem(cfg, "A" * 43) is None


def test_sha256_must_be_lowercase_hex(cfg, clock):
    key = webaccess.issue_key(cfg, 10, 12)
    good = json.loads(access(cfg).read_text())
    e = good["keys"][0]
    bad = [dict(e, sha256="é" * 64), dict(e, sha256=e["sha256"].upper()), dict(e, sha256="ab")]
    token, _ = webaccess.redeem(cfg, key)
    sess = json.loads(access(cfg).read_text())["sessions"]
    access(cfg).write_text(json.dumps({"keys": bad, "sessions": [
        dict(sess[0], sha256="é" * 64)] + sess}), encoding="utf-8")
    assert webaccess.counts(cfg) == (0, 1)
    assert webaccess.session_ok(cfg, token)  # no compare_digest error from the junk entry
    assert webaccess.redeem(cfg, "A" * 43) is None


def listing(cfg):
    return sorted(str(p.relative_to(cfg.data_root)) for p in Path(cfg.data_root).rglob("*"))


def test_failed_redeem_is_read_only(cfg, clock):
    before = listing(cfg)
    assert webaccess.redeem(cfg, "A" * 43) is None  # no web/ yet
    assert listing(cfg) == before
    key = webaccess.issue_key(cfg, 1, 1)
    webaccess.redeem(cfg, webaccess.issue_key(cfg, 10, 12))
    before, st = listing(cfg), access(cfg).stat()
    content = access(cfg).read_bytes()
    assert webaccess.redeem(cfg, "B" * 43) is None
    clock.t += 61  # the one-minute key expired
    assert webaccess.redeem(cfg, key) is None
    assert listing(cfg) == before and access(cfg).read_bytes() == content
    assert (access(cfg).stat().st_ino, access(cfg).stat().st_mtime_ns) == (st.st_ino, st.st_mtime_ns)


def test_read_error_under_lock_writes_nothing(cfg, clock, monkeypatch):
    key = webaccess.issue_key(cfg, 10, 12)
    token, _ = webaccess.redeem(cfg, webaccess.issue_key(cfg, 10, 12))
    content = access(cfg).read_bytes()
    real = Path.read_text

    def failing(self, *a, **k):
        if self.name == "access.json" and failing.armed:
            raise OSError(24, "Too many open files")
        return real(self, *a, **k)
    failing.armed = False
    monkeypatch.setattr(Path, "read_text", failing)
    orig_enter = webaccess._Locked.__enter__

    def enter(self):  # the lock-free read has passed; the read under the lock fails
        out = orig_enter(self)
        failing.armed = True
        return out
    monkeypatch.setattr(webaccess._Locked, "__enter__", enter)
    assert webaccess.redeem(cfg, key) is None
    failing.armed = True
    with pytest.raises(webaccess.AccessError):
        webaccess.issue_key(cfg, 10, 12)
    failing.armed = False
    assert access(cfg).read_bytes() == content
    assert webaccess.session_ok(cfg, token) and webaccess.counts(cfg) == (1, 1)


def test_missing_data_root_is_not_created(tmp_path):
    bad = HostConfig(nodes={}, data_root=str(tmp_path / "nothing" / "data"))
    assert webaccess.redeem(bad, "A" * 43) is None
    with pytest.raises(FileNotFoundError):
        webaccess.issue_key(bad, 10, 12)
    with pytest.raises(FileNotFoundError):
        webaccess.revoke_all(bad)
    assert not (tmp_path / "nothing").exists()


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
