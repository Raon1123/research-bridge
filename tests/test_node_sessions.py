"""The node operation `sessions` (docs/design/2026-11-11-node-sessions.md §6.1, §7, §8).

Record files are written under tmp_path only. No real session record is read."""
from __future__ import annotations

import io
import json
import os
import sys
import time
from pathlib import Path

import pytest

from rb_node import sessions as S
from rb_node.config import NodeConfig, load_config
from rb_node.protocol import ProtocolError, encode
from rb_node.remote import Node, serve
from rb_node.withheld import Withheld

REPO = Path(__file__).resolve().parents[1]
SID = ["0a1b2c3d-0000-4000-8000-%012d" % i for i in range(1, 10)]
T0 = 1_794_355_200.0  # 2026-11-11T00:00:00Z
NOW = T0 + 12 * 3600
DAY = "2026-11-11"


# -- fixture builder ------------------------------------------------------------------------
# The record format is ASSUMED: design docs/design/2026-11-11-node-sessions.md §8 "Assumed
# record format". Nobody looked at a real record for this work; these lines follow that
# section: one JSON object per line, most lines with top-level "timestamp" (ISO 8601 UTC, `Z`,
# fractional seconds) and "cwd", some lines with neither, plus other keys.
def ts(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".%03dZ" % int((t % 1) * 1000)


def line(t=None, cwd=None, **extra):
    rec = {"type": "user", "sessionId": "x", "gitBranch": "main",
           "message": {"role": "user", "content": "text"}}
    rec.update(extra)
    if t is not None:
        rec["timestamp"] = ts(t)
    if cwd is not None:
        rec["cwd"] = cwd
    return json.dumps(rec)


def write(sdir, project, name, lines, mtime=None, end="\n"):
    p = Path(sdir) / project / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + end, encoding="utf-8")
    if mtime is not None:
        os.utime(str(p), (mtime, mtime))
    return p


@pytest.fixture
def env(tmp_path):
    trm = tmp_path / "trm"
    (trm / "lab" / "experiments").mkdir(parents=True)
    sdir = tmp_path / "projects"
    sdir.mkdir()
    wp = tmp_path / "withheld.json"
    wp.write_text(json.dumps({"patterns": ["unrelatedfam_"]}), encoding="utf-8")
    return {"trm": trm, "sdir": sdir, "cache": tmp_path / "rb" / S.CACHE_NAME,
            "wh": Withheld.load(wp), "tmp": tmp_path, "wp": wp}


def collect(env, days=8, now=NOW, cache=True, **kw):
    return S.collect(str(env["sdir"]), str(env["trm"]), env["cache"] if cache else None,
                     env["wh"], days, now=now, **kw)


def session(env, sid, times, cwd=None, project="proj-a", mtime=NOW):
    cwd = str(env["trm"] / "lab" / "experiments") if cwd is None else cwd
    return write(env["sdir"], project, sid + ".jsonl",
                 [line(t, cwd) for t in times], mtime=mtime)


# -- reduction ------------------------------------------------------------------------------
def test_plain_reduction(env):
    session(env, SID[0], [T0 + 3600, T0 + 3660, T0 + 3720.5])
    r = collect(env)
    assert r["days"] == 8 and r["now"] == "2026-11-11T12:00:00Z" and r["tree"] == "trm"
    assert r["files"] == 1 and r["outside"] == 0 and r["unparsed"] == 0
    assert r["truncated"] is False
    assert r["sessions"] == [{"id": SID[0], "label": "lab/experiments",
                              "start": "2026-11-11T01:00:00Z", "end": "2026-11-11T01:02:00Z",
                              "days": {DAY: 120}}]


def test_lines_without_time_or_cwd_are_ignored(env):
    cwd = str(env["trm"])
    write(env["sdir"], "p", SID[0] + ".jsonl",
          [json.dumps({"type": "summary"}), line(T0 + 10), line(None, cwd), line(T0 + 20),
           "not json", "[1, 2]", line(T0 + 30, "/elsewhere")], mtime=NOW)
    (s,) = collect(env)["sessions"]
    assert s["label"] == "." and s["days"] == {DAY: 20}  # first cwd found wins


def test_gap_rule_and_day_of_the_earlier_time(env):
    # gaps 100, 400 (idle), 200 -> 300 s; a gap across midnight goes to the earlier day
    session(env, SID[0], [T0 + 100, T0 + 200, T0 + 600, T0 + 800])
    session(env, SID[1], [T0 - 60, T0 + 60])
    r = {s["id"]: s for s in collect(env)["sessions"]}
    assert r[SID[0]]["days"] == {DAY: 300}
    assert r[SID[1]]["days"] == {"2026-11-10": 120}
    assert r[SID[1]]["start"] == "2026-11-10T23:59:00Z"


def test_out_of_order_time_is_not_a_negative_gap(env):
    session(env, SID[0], [T0 + 100, T0 + 50, T0 + 150])
    (s,) = collect(env)["sessions"]
    assert s["days"] == {DAY: 100} and s["start"] == ts(T0 + 50)[:19] + "Z"


def test_session_spanning_two_days(env):
    session(env, SID[0], [T0 - 200, T0 - 100, T0 + 100, T0 + 250])
    (s,) = collect(env)["sessions"]
    assert s["days"] == {"2026-11-10": 300, DAY: 150}


def test_one_line_session_counts_with_no_active_seconds(env):
    session(env, SID[0], [T0 + 5])
    (s,) = collect(env)["sessions"]
    assert s["start"] == s["end"] == "2026-11-11T00:00:05Z" and s["days"] == {}


def test_time_formats(env):
    assert S.parse_ts("2026-11-11T00:00:00Z") == T0
    assert S.parse_ts("2026-11-11T09:00:00+09:00") == T0
    assert S.parse_ts("2026-11-11T00:00:00.123456Z") == pytest.approx(T0 + 0.123456)
    for bad in ("2026-11-11 00:00:00Z", "2026-13-01T00:00:00Z", "2026-11-11T00:00:00", 5, None,
                "x" * 50):
        assert S.parse_ts(bad) is None, bad


def test_days_window(env):
    session(env, SID[0], [T0 - 3 * 86400, T0 - 3 * 86400 + 60], mtime=T0 - 3 * 86400 + 60)
    session(env, SID[1], [T0 - 2 * 86400 - 100, T0 + 100, T0 + 200])
    assert {s["id"] for s in collect(env, days=1)["sessions"]} == {SID[1]}
    r = {s["id"]: s for s in collect(env, days=8)["sessions"]}
    assert set(r) == {SID[0], SID[1]}
    assert collect(env, days=1)["sessions"][0]["days"] == {DAY: 100}  # older days left out


def test_label_rules(env, tmp_path):
    cwd_ctl = str(env["trm"] / "lab\x1b[1m‮dir")
    session(env, SID[0], [T0 + 1], cwd=str(env["trm"]))
    session(env, SID[1], [T0 + 2], cwd=cwd_ctl)
    session(env, SID[2], [T0 + 3], cwd=str(env["trm"] / ("d" * 200)))
    session(env, SID[3], [T0 + 4], cwd=str(env["trm"]) + "/lab/../lab/./x/")
    session(env, SID[4], [T0 + 5], cwd=str(env["trm"] / "unrelatedfam_run"))
    r = {s["id"]: s["label"] for s in collect(env)["sessions"]}
    assert r[SID[0]] == "."
    assert r[SID[1]] == "lab[1mdir"
    assert r[SID[2]] == "d" * 120
    assert r[SID[3]] == "lab/x"
    assert r[SID[4]] == "(withheld)"


def test_tree_through_a_symlink_matches_both_spellings(env, tmp_path):
    link = tmp_path / "trm-link"
    link.symlink_to(env["trm"])
    session(env, SID[0], [T0 + 1], cwd=str(env["trm"] / "a"))
    session(env, SID[1], [T0 + 2], cwd=str(link / "b"))
    r = S.collect(str(env["sdir"]), str(link), None, env["wh"], now=NOW)
    assert sorted(s["label"] for s in r["sessions"]) == ["a", "b"] and r["tree"] == "trm-link"


def test_outside_and_missing_cwd_are_only_counted(env):
    session(env, SID[0], [T0 + 1], cwd="/somewhere/else")
    session(env, SID[1], [T0 + 2], cwd="relative/path")
    write(env["sdir"], "p", SID[2] + ".jsonl", [line(T0 + 3)], mtime=NOW)  # no cwd at all
    session(env, SID[3], [T0 + 4])
    r = collect(env)
    assert [s["id"] for s in r["sessions"]] == [SID[3]] and r["outside"] == 3


def test_files_without_usable_time_are_unparsed(env):
    write(env["sdir"], "p", SID[0] + ".jsonl", ["not json", json.dumps({"type": "x"})], mtime=NOW)
    write(env["sdir"], "p", SID[1] + ".jsonl", [line(None, "/x")], mtime=NOW)
    write(env["sdir"], "p", SID[2] + ".jsonl", [], mtime=NOW, end="")
    write(env["sdir"], "p", "NOT-AN-ID.jsonl", [line(T0 + 1, str(env["trm"]))], mtime=NOW)
    session(env, SID[3], [T0 + 4])
    r = collect(env)
    assert r["files"] == 5 and r["unparsed"] == 3 and r["ignored"] == 1 and len(r["sessions"]) == 1


def test_file_not_named_like_a_session_is_ignored_and_never_opened(env, monkeypatch):
    p = write(env["sdir"], "p", "not-a-session.jsonl", [json.dumps({"cmd": "x", "ok": True})],
              mtime=NOW)
    opens = Opens(monkeypatch)
    r = collect(env)
    assert str(p) not in opens.paths and opens.paths == []
    assert r["files"] == 1 and r["ignored"] == 1 and r["unparsed"] == 0 and r["sessions"] == []


def test_nested_timestamp_and_cwd_are_not_taken(env):
    nested = {"type": "assistant",
              "message": {"timestamp": ts(T0 + 1), "cwd": str(env["trm"]),
                          "content": [{"timestamp": ts(T0 + 2), "cwd": str(env["trm"])}]}}
    write(env["sdir"], "p", SID[0] + ".jsonl", [json.dumps(nested)], mtime=NOW)
    nested_cwd = dict(nested, timestamp=ts(T0 + 3))
    write(env["sdir"], "p", SID[1] + ".jsonl", [json.dumps(nested_cwd)], mtime=NOW)
    r = collect(env)
    assert r["unparsed"] == 1 and r["outside"] == 1 and r["sessions"] == []


def test_only_depth_two_jsonl_files_inside_the_directory_are_read(env, tmp_path):
    good = [line(T0 + 1, str(env["trm"]))]
    write(env["sdir"], "", SID[0] + ".jsonl", good, mtime=NOW)  # depth 1
    write(env["sdir"], "p/sub", SID[1] + ".jsonl", good, mtime=NOW)  # depth 3
    write(env["sdir"], "p", SID[2] + ".json", good, mtime=NOW)  # other suffix
    outside = tmp_path / "outside-dir"
    write(outside, "", SID[3] + ".jsonl", good, mtime=NOW)
    (env["sdir"] / "p" / (SID[4] + ".jsonl")).symlink_to(outside / (SID[3] + ".jsonl"))
    (env["sdir"] / "linked-dir").symlink_to(outside)
    (env["sdir"] / "p" / (SID[5] + ".jsonl")).mkdir()  # a directory with the suffix
    r = collect(env)
    assert r["sessions"] == [] and r["files"] == 0 and r["unparsed"] == 0
    assert r["ignored"] == 0 and r["deeper"] == 1 and r["shallower"] == 1  # counted, not read


# -- record files one level off (sessions_dir set one level too high or too low) -------------
def test_files_one_level_off_are_counted_by_name_and_time_only(env, tmp_path, monkeypatch):
    good = [line(T0 + 1, str(env["trm"]))]
    old = T0 - 20 * 86400
    outside = tmp_path / "outside-dir"
    write(outside, "", SID[8] + ".jsonl", good, mtime=NOW)
    write(outside, "q", SID[8] + ".jsonl", good, mtime=NOW)
    # one level deeper: <sessions_dir>/<a>/<b>/<id>.jsonl
    write(env["sdir"], "a/p1", SID[0] + ".jsonl", good, mtime=NOW)
    write(env["sdir"], "a/p2", SID[1] + ".jsonl", good, mtime=NOW)
    write(env["sdir"], "a/p2", "history.jsonl", good, mtime=NOW)  # not an id: not counted
    write(env["sdir"], "a/p2", SID[2] + ".jsonl", good, mtime=old)  # outside the window
    (env["sdir"] / "a" / "p2" / (SID[3] + ".jsonl")).symlink_to(outside / (SID[8] + ".jsonl"))
    (env["sdir"] / "a" / "linked").symlink_to(outside / "q")  # a directory out of sessions_dir
    (env["sdir"] / "a" / "p2" / (SID[4] + ".jsonl")).mkdir()  # not a regular file
    # one level shallower: <sessions_dir>/<id>.jsonl
    write(env["sdir"], "", SID[5] + ".jsonl", good, mtime=NOW)
    write(env["sdir"], "", SID[6] + ".jsonl", good, mtime=old)
    write(env["sdir"], "", "notes.jsonl", good, mtime=NOW)
    (env["sdir"] / (SID[7] + ".jsonl")).symlink_to(outside / (SID[8] + ".jsonl"))
    opens = Opens(monkeypatch)
    r = collect(env)
    assert opens.paths == []  # counted by name and modification time, never opened
    assert r["deeper"] == 2 and r["shallower"] == 1
    assert r["files"] == 0 and r["ignored"] == 0 and r["unparsed"] == 0 and r["sessions"] == []
    assert r["truncated"] is False


def test_level_counts_only_when_no_session_is_listed_and_none_is_outside(env, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the level listing ran")
    write(env["sdir"], "a/p", SID[0] + ".jsonl", [line(T0 + 1, str(env["trm"]))], mtime=NOW)
    session(env, SID[1], [T0 + 2])
    with monkeypatch.context() as m:
        m.setattr(S, "_levels", boom)
        r = collect(env)
    assert len(r["sessions"]) == 1 and r["deeper"] == 0 and r["shallower"] == 0
    session(env, SID[1], [T0 + 2], cwd="/elsewhere")
    with monkeypatch.context() as m:
        m.setattr(S, "_levels", boom)
        r = collect(env)
    assert r["sessions"] == [] and r["outside"] == 1 and r["deeper"] == r["shallower"] == 0
    (env["sdir"] / "proj-a" / (SID[1] + ".jsonl")).unlink()
    assert collect(env)["deeper"] == 1


def test_level_listing_shares_the_listing_bound(env, monkeypatch):
    write(env["sdir"], "a/p", SID[0] + ".jsonl", [line(T0 + 1, str(env["trm"]))], mtime=NOW)
    r = collect(env, cache=False)
    assert r["deeper"] == 1 and r["truncated"] is False
    with monkeypatch.context() as m:
        m.setattr(S, "MAX_LISTED", 3)  # the depth-2 listing sees 2 entries, the level listing 2 more
        r = collect(env, cache=False)
    assert r["truncated"] is True and r["deeper"] == 0
    with monkeypatch.context() as m:
        m.setattr(S, "MAX_LISTED", 1)  # bound hit by the depth-2 listing: no level listing
        r = collect(env, cache=False)
    assert r["truncated"] is True and r["deeper"] == 0 and r["shallower"] == 0


def test_symlink_inside_the_directory_is_followed(env):
    p = session(env, SID[0], [T0 + 1])
    (env["sdir"] / "alias").symlink_to(p.parent)
    r = collect(env)
    assert [s["id"] for s in r["sessions"]] == [SID[0]] and r["files"] == 2


def test_same_id_in_two_project_directories_is_one_session(env):
    session(env, SID[0], [T0 + 100, T0 + 160], project="p1", cwd=str(env["trm"] / "old"))
    session(env, SID[0], [T0 + 50, T0 + 70, T0 + 400], project="p2", cwd=str(env["trm"] / "new"))
    (s,) = collect(env)["sessions"]
    assert s["label"] == "new" and s["start"] == "2026-11-11T00:00:50Z"
    assert s["end"] == "2026-11-11T00:06:40Z" and s["days"] == {DAY: 60}


def test_very_long_line_is_handled(env, monkeypatch):
    big = "y" * (5 << 20)
    cwd = str(env["trm"])
    lines = [json.dumps({"message": {"content": big}, "timestamp": ts(T0 + 10), "cwd": cwd}),
             line(T0 + 20, cwd)]
    write(env["sdir"], "p", SID[0] + ".jsonl", lines, mtime=NOW)
    (s,) = collect(env, cache=False)["sessions"]
    assert s["start"] == "2026-11-11T00:00:10Z" and s["days"] == {DAY: 10}
    # above LINE_MAX the line is read through and skipped; the rest still reduces
    with monkeypatch.context() as m:
        m.setattr(S, "LINE_MAX", 1 << 20)
        (s,) = collect(env, cache=False)["sessions"]
    assert s["start"] == s["end"] == "2026-11-11T00:00:20Z"


# -- cache ----------------------------------------------------------------------------------
class Opens:
    def __init__(self, monkeypatch):
        self.paths = []
        real = open

        def counting(path, *a, **k):
            self.paths.append(str(path))
            return real(path, *a, **k)
        monkeypatch.setattr(S, "open", counting, raising=False)


def test_unchanged_file_is_not_opened_again(env, monkeypatch):
    p = session(env, SID[0], [T0 + 1, T0 + 2])
    first = collect(env)
    opens = Opens(monkeypatch)
    assert collect(env) == first
    assert opens.paths == []
    assert str(p) not in json.dumps(json.loads(env["cache"].read_text(encoding="utf-8")))


def test_grown_file_is_read_from_the_offset(env, monkeypatch):
    p = session(env, SID[0], [T0 + 1, T0 + 2])
    collect(env)
    size = p.stat().st_size
    with open(str(p), "a", encoding="utf-8") as fh:
        fh.write(line(T0 + 100, str(env["trm"])) + "\n")
    os.utime(str(p), (NOW, NOW))
    seen = []
    real_read = S._read

    def spy(fh, ent, budget, roots):
        seen.append(ent["offset"])
        return real_read(fh, ent, budget, roots)
    with monkeypatch.context() as m:
        m.setattr(S, "_read", spy)
        grown = collect(env)
    assert seen == [size]
    assert grown == collect(env, cache=False)
    assert grown["sessions"][0]["days"] == {DAY: 99}


def test_half_written_last_line_waits_for_its_newline(env):
    cwd = str(env["trm"])
    p = write(env["sdir"], "p", SID[0] + ".jsonl", [line(T0 + 1, cwd), line(T0 + 2, cwd)[:30]],
              mtime=NOW, end="")
    assert collect(env)["sessions"][0]["end"] == "2026-11-11T00:00:01Z"
    p.write_text(line(T0 + 1, cwd) + "\n" + line(T0 + 2, cwd) + "\n", encoding="utf-8")
    os.utime(str(p), (NOW, NOW))
    r = collect(env)
    assert r == collect(env, cache=False) and r["sessions"][0]["days"] == {DAY: 1}


def test_shrunk_or_rewritten_file_is_read_again(env):
    p = session(env, SID[0], [T0 + 1, T0 + 2, T0 + 3])
    collect(env)
    session(env, SID[0], [T0 + 500])  # shorter
    assert collect(env)["sessions"][0]["start"] == "2026-11-11T00:08:20Z"
    old = p.read_text(encoding="utf-8")
    new = old.replace(ts(T0 + 500), ts(T0 + 900))  # same size, other first bytes
    assert len(new) == len(old)
    p.write_text(new + line(T0 + 901, str(env["trm"])) + "\n", encoding="utf-8")
    os.utime(str(p), (NOW, NOW))
    r = collect(env)
    assert r["sessions"][0]["start"] == "2026-11-11T00:15:00Z" and r == collect(env, cache=False)


def test_corrupt_or_foreign_cache_is_rebuilt(env):
    session(env, SID[0], [T0 + 1, T0 + 2])
    fresh = collect(env, cache=False)
    env["cache"].parent.mkdir(parents=True)
    for bad in ("{not json", "[]", json.dumps({"schema": 99, "files": {}}),
                json.dumps({"schema": 1, "fingerprint": "x", "files": {"k": {}}})):
        env["cache"].write_text(bad, encoding="utf-8")
        assert collect(env) == fresh
        assert json.loads(env["cache"].read_text(encoding="utf-8"))["schema"] == 1
    data = json.loads(env["cache"].read_text(encoding="utf-8"))
    for e in data["files"].values():
        e["days"] = "broken"
    env["cache"].write_text(json.dumps(data), encoding="utf-8")
    assert collect(env) == fresh


def test_cache_is_not_written_when_asked_not_to(env):
    session(env, SID[0], [T0 + 1])
    collect(env, write_cache=False)
    assert not env["cache"].exists() and not env["cache"].parent.exists()


# -- bounds ---------------------------------------------------------------------------------
def test_big_file_is_finished_over_several_calls(env, monkeypatch):
    times = [T0 + i for i in range(0, 2000, 2)]
    session(env, SID[0], times)
    fresh = collect(env, cache=False)
    assert fresh["truncated"] is False
    with monkeypatch.context() as m:
        m.setattr(S, "MAX_NEW_BYTES", 20000)
        results = [collect(env) for _ in range(30)]
    assert results[0]["truncated"] is True
    done = [i for i, r in enumerate(results) if not r["truncated"]]
    assert done and done[0] > 1
    assert results[done[0]] == fresh


def test_session_and_file_bounds(env, monkeypatch):
    for i in range(3):
        session(env, SID[i], [T0 + 10 * i], mtime=NOW - 100 + i)
    with monkeypatch.context() as m:
        m.setattr(S, "MAX_SESSIONS", 2)
        r = collect(env, cache=False)
    assert r["truncated"] is True and [s["id"] for s in r["sessions"]] == [SID[2], SID[1]]
    with monkeypatch.context() as m:
        m.setattr(S, "MAX_FILES", 1)
        r = collect(env, cache=False)
    assert r["truncated"] is True and r["files"] == 1 and [s["id"] for s in r["sessions"]] == [SID[2]]
    with monkeypatch.context() as m:
        m.setattr(S, "MAX_LISTED", 2)
        assert collect(env, cache=False)["truncated"] is True


def test_old_files_are_not_opened(env, monkeypatch):
    session(env, SID[0], [T0 - 20 * 86400], mtime=T0 - 20 * 86400)
    opens = Opens(monkeypatch)
    r = collect(env)
    assert opens.paths == [] and r["files"] == 0 and r["sessions"] == []


# -- the operation --------------------------------------------------------------------------
@pytest.fixture
def ncfg(env):
    mb = env["tmp"] / "rb" / "mailbox"
    return NodeConfig(trm_root=str(env["trm"]), read_roots=["lab/experiments"],
                      write_roots=[str(mb / "in")], queue_dir=str(env["trm"] / "q"),
                      withheld_source=str(env["wp"]), mailbox_root=str(mb),
                      audit_path=str(env["tmp"] / "rb" / "audit.jsonl"),
                      approval_path=str(env["tmp"] / "rb" / "approve.json"),
                      claude_bin=str(env["tmp"] / "no-claude"), sessions_dir=str(env["sdir"]))


def call(cfg, *reqs):
    stdin = io.BytesIO(b"".join(
        encode({"id": str(i), "op": op, "args": args}) for i, (op, args) in enumerate(reqs)))
    stdout = io.BytesIO()
    assert serve(cfg, stdin, stdout) == 0
    return [json.loads(x) for x in stdout.getvalue().decode("utf-8").splitlines()]


def test_op_answers_and_caches_beside_the_mailbox(env, ncfg):
    now = time.time()
    session(env, SID[0], [now - 120, now - 60], mtime=now)
    (resp,) = call(ncfg, ("sessions", {}))
    r = resp["result"]
    assert resp["ok"] is True and r["days"] == 8 and r["sessions"][0]["id"] == SID[0]
    assert (env["tmp"] / "rb" / S.CACHE_NAME).is_file()
    assert call(ncfg, ("sessions", {"days": 31}))[0]["result"]["days"] == 31


@pytest.mark.parametrize("days", [0, 32, -1, "3", True, 1.5, None])
def test_op_bad_days(ncfg, days):
    (resp,) = call(ncfg, ("sessions", {"days": days}))
    assert resp["ok"] is False and resp["error"]["code"] == "bad_args"


def test_op_unset_or_missing_directory(env, ncfg):
    ncfg.sessions_dir = ""
    (resp,) = call(ncfg, ("sessions", {}))
    assert resp["error"]["code"] == "not_configured"
    with pytest.raises(ProtocolError) as ei:
        S.run(ncfg, env["wh"])
    assert ei.value.code == "not_configured"
    ncfg.sessions_dir = str(env["tmp"] / "no-such-dir")
    assert call(ncfg, ("sessions", {}))[0]["error"]["code"] == "not_found"


def test_nothing_else_leaves_the_node(env, ncfg):
    now = time.time()
    inside = str(env["trm"] / "lab" / "experiments")
    lines = [json.dumps({"type": "user", "timestamp": ts(now - 30), "cwd": inside,
                         "gitBranch": "MARKER-BRANCH-77", "sessionId": SID[0],
                         "message": {"role": "user", "content": "MARKER-TEXT-31 see "
                                     "/home/MARKER-ABS-12/file.py"}}),
             json.dumps({"type": "assistant", "timestamp": ts(now - 20), "cwd": inside,
                         "toolUseResult": {"filePath": "/abs/MARKER-ABS-12/x"},
                         "message": {"content": [{"type": "text", "text": "MARKER-TEXT-31"}]}})]
    write(env["sdir"], "-home-proj", SID[0] + ".jsonl", lines, mtime=now)
    write(env["sdir"], "-home-other", SID[1] + ".jsonl",
          [line(now - 10, "/home/MARKER-OUTSIDE-5/project")], mtime=now)
    (resp,) = call(ncfg, ("sessions", {}))
    assert resp["ok"] is True and resp["result"]["outside"] == 1
    blobs = [json.dumps(resp), Path(ncfg.audit_path).read_text(encoding="utf-8"),
             (env["tmp"] / "rb" / S.CACHE_NAME).read_text(encoding="utf-8")]
    for blob in blobs:
        for marker in ("MARKER-BRANCH", "MARKER-TEXT", "MARKER-ABS", "MARKER-OUTSIDE",
                       str(env["tmp"]), "-home-proj", "-home-other"):
            assert marker not in blob, marker
    audit = [json.loads(x) for x in blobs[1].splitlines()]
    assert set(audit[-1]) == {"id", "op", "ok", "ts"} and audit[-1]["op"] == "sessions"


def test_hello_lists_sessions_and_a_subprocess_node_answers(env, ncfg, tmp_path):
    from dataclasses import asdict
    from rb_host.client import NodeClient
    now = time.time()
    session(env, SID[0], [now - 60, now - 30], mtime=now)
    conf = tmp_path / "node.json"
    conf.write_text(json.dumps(asdict(ncfg)), encoding="utf-8")
    assert load_config(conf).sessions_dir == str(env["sdir"])
    nenv = {"RB_NODE_CONFIG": str(conf), "PYTHONPATH": str(REPO),
            "PATH": os.environ.get("PATH", "")}
    serve_argv = [sys.executable, "-m", "rb_node.cli", "serve-remote"]
    with NodeClient("local-test", ssh_argv=serve_argv, env=nenv) as c:
        assert "sessions" in c.call("hello")["ops"]
        r = c.call("sessions", days=2)
    assert r["days"] == 2 and [s["id"] for s in r["sessions"]] == [SID[0]]
    assert r["sessions"][0]["days"] and r["sessions"][0]["label"] == "lab/experiments"


def test_config_key(tmp_path, monkeypatch):
    assert NodeConfig().sessions_dir == ""
    p = tmp_path / "node.json"
    monkeypatch.setenv("HOME", str(tmp_path))
    p.write_text(json.dumps({"sessions_dir": "~/x"}), encoding="utf-8")
    assert load_config(p).sessions_dir == str(tmp_path / "x")
    p.write_text(json.dumps({"sessions_dir": 5}), encoding="utf-8")
    assert load_config(p).sessions_dir == ""
    assert "sessions" in Node(load_config(p)).ops


# -- node console ---------------------------------------------------------------------------
@pytest.fixture
def console(env, ncfg, tmp_path, monkeypatch):
    from dataclasses import asdict
    conf = tmp_path / "node.json"
    conf.write_text(json.dumps(asdict(ncfg)), encoding="utf-8")
    monkeypatch.setenv("RB_NODE_CONFIG", str(conf))
    return conf


def test_cli_sessions_prints_what_the_op_returns(env, ncfg, console, capsys):
    from rb_node import cli
    now = time.time()
    session(env, SID[0], [now - 90, now - 30], mtime=now)
    assert cli.main(["sessions", "--days", "3"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert not (env["tmp"] / "rb" / S.CACHE_NAME).exists()  # the console command writes nothing
    (resp,) = call(ncfg, ("sessions", {"days": 3}))
    printed.pop("now"), resp["result"].pop("now")
    assert printed == resp["result"] and printed["sessions"][0]["id"] == SID[0]
    assert cli.main(["sessions"]) == 0 and json.loads(capsys.readouterr().out)["days"] == 8
    with pytest.raises(SystemExit) as ei:
        cli.main(["sessions", "--days", "0"])
    assert ei.value.code == 2
    assert cli.main(["sessions", "-h"]) == 0
    assert "usage: rb-node sessions" in capsys.readouterr().out


def test_cli_sessions_not_configured(env, ncfg, console, capsys):
    from dataclasses import asdict
    from rb_node import cli
    ncfg.sessions_dir = ""
    console.write_text(json.dumps(asdict(ncfg)), encoding="utf-8")
    assert cli.main(["sessions"]) == 1
    out = capsys.readouterr()
    assert out.out == "" and len(out.err.strip().splitlines()) == 1
    assert "sessions_dir" in out.err


def test_doctor_sessions_check(env, ncfg, tmp_path):
    from rb_node import doctor
    ncfg.sessions_dir = ""
    c = doctor._sessions_check(ncfg)
    assert c.id == "sessions" and c.level == "ok" and "not set" in c.message
    ncfg.sessions_dir = str(tmp_path / "missing")
    c = doctor._sessions_check(ncfg)
    assert c.level == "warn" and "does not exist" in c.message and c.fix
    ncfg.sessions_dir = str(env["sdir"])
    now = time.time()
    write(env["sdir"], "p", SID[0] + ".jsonl", ["not json"], mtime=now)
    c = doctor._sessions_check(ncfg)
    assert c.level == "warn" and "none could be read" in c.message and c.fix
    session(env, SID[1], [now - 60, now - 30], mtime=now)
    session(env, SID[2], [now - 60], cwd="/elsewhere", mtime=now)
    c = doctor._sessions_check(ncfg)
    assert c.level == "ok", c
    assert "1 session(s)" in c.message and "1 unparsed" in c.message and "1 outside" in c.message
    assert "ignored" not in c.message
    assert not (env["tmp"] / "rb" / S.CACHE_NAME).exists()  # doctor writes nothing
    assert "sessions" in {x.id for x in doctor.system_checks(ncfg)}


LAYOUT = "<sessions_dir>/<project directory>/<session id>.jsonl"


def _doctor(ncfg):
    from rb_node import doctor
    return doctor._sessions_check(ncfg)


def test_doctor_sessions_found_names_the_ignored_files(env, ncfg):
    now = time.time()
    session(env, SID[0], [now - 60, now - 30], mtime=now)
    write(env["sdir"], "p", "not-a-session.jsonl", ["{}"], mtime=now)
    c = _doctor(ncfg)
    assert c.level == "ok" and "1 session(s)" in c.message and "1 ignored" in c.message, c
    (env["sdir"] / "p" / "not-a-session.jsonl").unlink()
    session(env, SID[0], [now - 60], cwd="/elsewhere", mtime=now)  # outside only: still ok
    c = _doctor(ncfg)
    assert c.level == "ok" and "1 outside" in c.message and "ignored" not in c.message, c


def test_doctor_sessions_dir_one_level_too_high(env, ncfg):
    now = time.time()
    write(env["sdir"], "projects/p", SID[0] + ".jsonl", [line(now - 60, str(env["trm"]))],
          mtime=now)
    write(env["sdir"], "logs", "not-a-session.jsonl", ["{}"], mtime=now)
    c = _doctor(ncfg)
    assert c.level == "warn", c
    assert c.message == ("sessions_dir looks one level too high: 1 session record file(s) are "
                         "one level deeper")
    assert LAYOUT in c.fix and "~/.claude/projects" in c.fix


def test_doctor_sessions_dir_one_level_too_low(env, ncfg):
    now = time.time()
    write(env["sdir"], "", SID[0] + ".jsonl", [line(now - 60, str(env["trm"]))], mtime=now)
    write(env["sdir"], "", SID[1] + ".jsonl", [line(now - 60, str(env["trm"]))], mtime=now)
    c = _doctor(ncfg)
    assert c.level == "warn", c
    assert c.message == ("sessions_dir looks one level too low: 2 session record file(s) are "
                         "one level shallower")
    assert LAYOUT in c.fix and "~/.claude/projects" in c.fix


def test_doctor_only_files_not_named_like_a_session(env, ncfg):
    now = time.time()
    write(env["sdir"], "logs", "not-a-session.jsonl", ['{"cmd": "x", "ok": true}'], mtime=now)
    c = _doctor(ncfg)
    assert c.level == "warn", c
    assert c.message == ("1 .jsonl file(s) were found but none is named like a session record: "
                         "sessions_dir is probably not the Claude projects directory")
    assert LAYOUT in c.fix and "~/.claude/projects" in c.fix


def test_doctor_id_named_files_none_usable(env, ncfg):
    now = time.time()
    write(env["sdir"], "p", SID[0] + ".jsonl", ['{"type": "x"}'], mtime=now)
    write(env["sdir"], "p", "not-a-session.jsonl", ["{}"], mtime=now)
    c = _doctor(ncfg)
    assert c.level == "warn" and "none could be read as a session" in c.message, c
    assert "the assumed record format may be wrong" in c.message and "deeper" not in c.message
    assert "section 8" in c.fix
    # id-named files at the expected depth say the level is right: the format warning wins,
    # and a deeper count is only added to it
    write(env["sdir"], "p/" + SID[0], SID[1] + ".jsonl", ['{"type": "x"}'], mtime=now)
    c = _doctor(ncfg)
    assert c.level == "warn" and "the assumed record format may be wrong" in c.message, c
    assert "1 more session record file(s) one level deeper" in c.message


def test_doctor_nothing_in_the_window(env, ncfg):
    c = _doctor(ncfg)
    assert c.level == "ok" and c.message == "no record file in the last 8 days", c
    old = time.time() - 20 * 86400
    write(env["sdir"], "p", SID[0] + ".jsonl", [line(old, str(env["trm"]))], mtime=old)
    assert _doctor(ncfg).message == "no record file in the last 8 days"


def test_doctor_record_files_whose_times_are_older_than_the_window(env, ncfg):
    # modified inside the window, every time inside it older: no session, nothing wrong
    now, old = time.time(), time.time() - 20 * 86400
    write(env["sdir"], "p", SID[0] + ".jsonl", [line(old, str(env["trm"]))], mtime=now)
    c = _doctor(ncfg)
    assert c.level == "ok" and "0 session(s)" in c.message and "1 record file(s)" in c.message, c


def test_a_full_day_is_capped_at_86400_seconds_and_the_hub_keeps_it(env):
    # gaps go to the day of the earlier time, so a day can collect up to 86400 + 299 s raw
    from rb_host import sessions as hub_sessions
    times = [T0 + 10 + 250 * i for i in range(int((86400 + 600) / 250))]
    session(env, SID[0], times, mtime=times[-1])
    r = collect(env, now=times[-1] + 60)
    (s,) = r["sessions"]
    assert s["days"][DAY] == 86400 and max(s["days"].values()) <= 86400
    checked, skipped = hub_sessions.validate(r, env["wh"])
    assert skipped == 0 and checked["sessions"][SID[0]]["days"][DAY] == 86400
