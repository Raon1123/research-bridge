from __future__ import annotations

import hashlib
import os

import pytest

from rb_node.mailbox import Mailbox
from rb_node.protocol import ProtocolError


@pytest.fixture
def mb(tmp_path):
    return Mailbox(tmp_path / "rb")


def _put(mb, msg_id, box, name, data):
    stored, fh = mb.open_part(msg_id, box, name)
    fh.write(data)
    fh.close()
    return stored


def test_dirs_created(mb):
    for d in ("in", "out", "state"):
        assert (mb.root / d).is_dir()
    if os.name == "posix":
        assert (mb.root.stat().st_mode & 0o777) == 0o700


def test_sanitize_korean_windows_path():
    assert Mailbox.sanitize(r"C:\x\결과 그림.png", set()) == "결과 그림.png"


def test_sanitize_collision_suffix():
    taken = set()
    first = Mailbox.sanitize("결과 그림.png", taken)
    taken.add(first)
    second = Mailbox.sanitize("결과 그림.png", taken)
    taken.add(second)
    assert second == "결과 그림-2.png"
    assert Mailbox.sanitize("결과 그림.png", taken) == "결과 그림-3.png"


def test_sanitize_edge_cases():
    assert Mailbox.sanitize("a/b/../c.txt", set()) == "c.txt"
    assert Mailbox.sanitize("x\x00y\x1f.txt", set()) == "xy.txt"
    assert Mailbox.sanitize("..", set()) == "attachment"
    assert Mailbox.sanitize("dir/", set()) == "attachment"
    assert Mailbox.sanitize("", set()) == "attachment"


def test_new_message_idempotent(mb):
    d1 = mb.new_message("m1", {"body": "first"})
    d2 = mb.new_message("m1", {"body": "second"})
    assert d1 == d2
    assert len(list((mb.root / "in").iterdir())) == 1
    assert mb.inbox()[0]["body"] == "first"


def test_bad_ids_rejected(mb):
    for bad in ("../x", "a/b", r"a\b", "", "."):
        with pytest.raises(ProtocolError):
            mb.new_message(bad, {})


def test_part_commit_ok(mb):
    mb.new_message("m1", {})
    data = b"hello" * 1000
    stored = _put(mb, "m1", "in", "a b.txt", data)
    att = mb.root / "in" / "m1" / "attachments"
    assert not (att / stored).exists()  # invisible until verified
    mb.commit_part("m1", "in", stored, hashlib.sha256(data).hexdigest())
    assert (att / stored).read_bytes() == data
    assert not (att / (stored + ".part")).exists()


def test_checksum_mismatch_leaves_nothing(mb):
    mb.new_message("m1", {})
    stored = _put(mb, "m1", "in", "x.bin", b"data")
    with pytest.raises(ProtocolError) as ei:
        mb.commit_part("m1", "in", stored, "0" * 64)
    assert ei.value.code == "checksum"
    att = mb.root / "in" / "m1" / "attachments"
    assert list(att.iterdir()) == []


def test_same_name_twice_gets_suffix_and_original_kept(mb):
    mb.new_message("m1", {})
    data = b"d"
    sha = hashlib.sha256(data).hexdigest()
    s1 = _put(mb, "m1", "in", "결과 그림.png", data)
    mb.commit_part("m1", "in", s1, sha)
    s2 = _put(mb, "m1", "in", r"C:\q\결과 그림.png", data)
    mb.commit_part("m1", "in", s2, sha)
    assert (s1, s2) == ("결과 그림.png", "결과 그림-2.png")
    names = mb.attachment_names("m1", "in")
    assert names["결과 그림-2.png"] == r"C:\q\결과 그림.png"


def test_two_open_parts_same_name_do_not_collide(mb):
    mb.new_message("m1", {})
    a, fa = mb.open_part("m1", "in", "f.txt")
    b, fb = mb.open_part("m1", "in", "f.txt")
    fa.close()
    fb.close()
    assert a != b


def test_post_out_undelivered_until_ack(mb, tmp_path):
    src = tmp_path / "fig.png"
    src.write_bytes(b"png")
    i1 = mb.post_out("reply", "hi", [src], "m1")
    i2 = mb.post_out("event", "ev", [], None)
    items = mb.undelivered()
    assert [x["id"] for x in items] == sorted([i1, i2])
    assert mb.undelivered() == items  # stable until ack
    one = next(x for x in items if x["id"] == i1)
    assert one["kind"] == "reply" and one["body"] == "hi" and one["reply_to"] == "m1"
    assert one["attachments"][0]["name"] == "fig.png"
    assert (mb.root / "out" / i1 / "attachments" / "fig.png").read_bytes() == b"png"
    mb.ack([i1])
    assert [x["id"] for x in mb.undelivered()] == [i2]
    mb.ack([i1, i2])
    assert mb.undelivered() == []


def test_post_out_bad_kind(mb):
    with pytest.raises(ProtocolError):
        mb.post_out("bogus", "x", [], None)


def test_post_out_attachment_name_collision(mb, tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "f.txt").write_text("1")
    (tmp_path / "b" / "f.txt").write_text("2")
    i = mb.post_out("reply", "", [tmp_path / "a" / "f.txt", tmp_path / "b" / "f.txt"], None)
    d = mb.root / "out" / i / "attachments"
    assert sorted(p.name for p in d.iterdir()) == ["f-2.txt", "f.txt"]


def test_inbox_status(mb):
    mb.new_message("m1", {"body": "a"})
    mb.new_message("m2", {"body": "b"})
    assert {m["status"] for m in mb.inbox()} == {"new"}
    mb.set_status("m1", "answered")
    assert [m["id"] for m in mb.inbox("answered")] == ["m1"]
    assert [m["id"] for m in mb.inbox("new")] == ["m2"]
    with pytest.raises(ProtocolError):
        mb.set_status("m1", "weird")
    with pytest.raises(ProtocolError):
        mb.set_status("nope", "failed")
