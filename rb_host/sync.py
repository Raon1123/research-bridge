"""`rb sync`: one reliable pass per node, hub to node only (design 2026-11-10 §6.2, §6.3).

A pass opens one connection for `hello`, `poll` (stored with delivered false) and `git_status`,
closes it, then refreshes the board sources that are due. Results go to
`<data_root>/sync/<node>.json`: codes only, never message text, paths or exception text.
Never approves a job and never touches the harness channel.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TextIO

from . import board, configure, jobs, server, store
from .client import RemoteError, TransportError, normalize_hello
from .config import default_root
from .util import age_s
from .threads import read_status, status_path  # noqa: F401  (re-exported readers)
from rb_node.withheld import Withheld

SCHEMA = 1
CODE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
GPU_TEXT = {"nvidia-smi not found", "nvidia-smi failed"}  # rb_node/remote.py gpu_status free text
# Board results that are recorded but do not fail a pass (coordinator ruling R8).
TOLERATED = {"gpu_status_unavailable", "no_gpus", "no_path"}


def error_code(exc: BaseException) -> str:
    """A short code for an exception; never its text."""
    if isinstance(exc, RemoteError):
        code = exc.code
    elif isinstance(exc, TimeoutError):
        code = "ledger_locked"
    elif isinstance(exc, OSError):
        code = "os_error"
    elif isinstance(exc, TransportError):
        code = getattr(exc, "code", None) or "transport"
    else:
        code = "internal"
    if not isinstance(code, str) or not CODE.match(code):
        return "invalid_code"
    return code


def board_code(err: str) -> str:
    err = str(err)
    if CODE.match(err):
        return err
    if err in GPU_TEXT:
        return "gpu_status_unavailable"
    return "source_error"


def due_sources(cfg: Any, node: str, now_s: Optional[float] = None) -> List[str]:
    """Node board sources to refresh: cache missing or unreadable, last result not ok, or age
    at least half the cadence. Sources without a configured path are never listed."""
    paths = board._node_paths(cfg, node)
    now_s = time.time() if now_s is None else now_s
    due = []
    for name in board.NODE_SOURCES:
        if name in ("state", "events", "kanban"):
            p = paths.get(name)
            if not isinstance(p, str) or not p:
                continue
        try:
            rec = json.loads(board._cache_path(cfg, "%s:%s" % (node, name)).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            due.append(name)
            continue
        if not isinstance(rec, dict) or rec.get("ok") is not True:
            due.append(name)
            continue
        age = age_s(rec.get("fetched_at"), now_s)
        if age is None or age >= board.CADENCE_S[name] / 2.0:
            due.append(name)
    return due


def _write_status(cfg: Any, node: str, st: dict) -> None:
    path = status_path(cfg, node)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".sync-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(st, ensure_ascii=False, indent=1))
        os.chmod(tmp, 0o600)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _log(stage: str, exc: BaseException) -> None:
    sys.stderr.write("sync: %s failed: %s\n" % (stage, type(exc).__name__))


def _hub_withheld(cfg: Any) -> Dict[str, Optional[int]]:
    """State of the hub's withheld pattern file now: usable extra patterns and rejected ones.
    Both None when the state cannot be read."""
    try:
        wh = Withheld.load(Path(cfg.withheld_patterns_file))
        return {"hub_withheld_extra": int(wh.extra_count), "hub_withheld_rejected": int(wh.rejected_count)}
    except Exception as exc:
        _log("withheld", exc)
        return {"hub_withheld_extra": None, "hub_withheld_rejected": None}


def run_pass(cfg: Any, node: str) -> dict:
    """One pass for one node. Never raises; returns the final status dict."""
    t0 = time.time()
    try:
        prev = read_status(cfg, node) or {}
    except Exception as exc:
        _log("status", exc)
        prev = {}
    st = {"schema": SCHEMA, "node": node, "last_attempt_at": jobs.now(),
          "last_ok_at": prev.get("last_ok_at"), "ok": False, "error": "incomplete",
          "stage": "running", "new_items": 0, "rejected": 0, "rejected_ids": [],
          "board": prev.get("board") if isinstance(prev.get("board"), dict) else {},
          "node_version": prev.get("node_version"), "protocol": prev.get("protocol"),
          "withheld_extra": prev.get("withheld_extra"), "node_seen_at": prev.get("node_seen_at"),
          "tree_head": prev.get("tree_head"), "tree_dirty": prev.get("tree_dirty"),
          "git_error": prev.get("git_error"), "duration_s": 0.0}  # type: Dict[str, Any]
    st.update(_hub_withheld(cfg))
    try:
        _write_status(cfg, node, st)
    except Exception as exc:
        _log("status", exc)
    try:
        store.sweep_stage_dirs(cfg, node)
    except Exception as exc:
        _log("sweep", exc)

    stage = "connect"
    prog = {}  # type: Dict[str, Any]
    fail = None  # type: Optional[tuple]
    try:
        with jobs.connect(cfg, node) as c:
            stage = "hello"
            h = normalize_hello(c.call("hello"))
            st["node_version"] = h["version"]
            st["protocol"] = h["protocol"]
            st["withheld_extra"] = h["withheld_extra"]
            st["node_seen_at"] = jobs.now()
            stage = "poll"
            try:
                server.fetch_node(cfg, node, c, delivered=False, progress=prog)
            finally:  # what was stored before a failure is still counted
                st["new_items"] = int(prog.get("new", 0))
                st["rejected"] = int(prog.get("rejected", 0))
                st["rejected_ids"] = list(prog.get("rejected_ids", []))[:10]
            stage = "git"
            try:
                g = c.call("git_status")
                tree = g.get("tree") or g.get("trm") or {}
                st["tree_head"] = tree.get("head")
                st["tree_dirty"] = tree.get("dirty_files")
                st["git_error"] = None
            except RemoteError as exc:
                st["tree_head"] = st["tree_dirty"] = None
                st["git_error"] = error_code(exc)
    except Exception as exc:
        fail = (stage, error_code(exc))
        _log(stage, exc)

    if fail is None:
        stage = "board"
        bmap = {}  # type: Dict[str, str]
        try:
            due = due_sources(cfg, node)
            paths = board._node_paths(cfg, node)
            for name in board.NODE_SOURCES:
                if name in ("state", "events", "kanban") and not (
                        isinstance(paths.get(name), str) and paths.get(name)):
                    bmap[name] = "no_path"
                elif name not in due:
                    bmap[name] = "skipped"
            if due:
                for r in board.refresh(cfg, node, due):
                    name = str(r["source"]).split(":", 1)[1]
                    bmap[name] = "ok" if r.get("ok") else board_code(r.get("error"))
            st["board"] = bmap
            bad = [v for v in bmap.values() if v not in TOLERATED
                   and v not in ("ok", "skipped")]
            if bad:
                fail = ("board", bad[0])
        except Exception as exc:
            fail = ("board", error_code(exc))
            _log("board", exc)

    if fail is None:
        st.update(ok=True, error=None, stage=None, last_ok_at=jobs.now())
    else:
        st.update(ok=False, stage=fail[0], error=fail[1])
    st["duration_s"] = round(time.time() - t0, 3)
    try:
        _write_status(cfg, node, st)
    except Exception as exc:
        _log("status", exc)
    return st


def _line(st: dict) -> str:
    keys = ("node", "ok", "error", "stage", "new_items", "rejected", "rejected_ids", "board", "tree_head",
            "tree_dirty")
    return json.dumps({k: st.get(k) for k in keys}, ensure_ascii=False)


def _hostjson_path() -> str:
    return os.environ.get("RB_HOST_CONFIG") or str(Path(default_root()) / "host.json")


def run(node: Optional[str], watch: int, out: Optional[TextIO] = None,
        sleep: Callable[[float], None] = time.sleep, max_passes: Optional[int] = None) -> int:
    """One pass (or one per `watch` seconds). Returns 1 when any pass failed. `out` defaults to
    the current sys.stdout (looked up at call time)."""
    out = out if out is not None else sys.stdout
    if watch and watch < 30:
        print("error: --watch must be at least 30 seconds", file=out)
        return 1
    failed = False
    passes = 0
    try:
        while True:
            passes += 1
            try:
                cfg = jobs.load_cfg()
            except (OSError, ValueError) as exc:
                print(configure.host_json_error(exc), file=out, flush=True)
                failed = True
            else:
                names = [node] if node else sorted(cfg.nodes)
                if not names:
                    print("error: no nodes configured in %s; run: rb setup --node NAME --host "
                          "HOST --user USER" % _hostjson_path(), file=out, flush=True)
                    failed = True
                for n in names:
                    if n not in cfg.nodes:
                        print("error: unknown node: %s" % n, file=out, flush=True)
                        failed = True
                        continue
                    st = run_pass(cfg, n)
                    print(_line(st), file=out, flush=True)
                    failed = failed or not st["ok"]
            if not watch or (max_passes is not None and passes >= max_passes):
                return 1 if failed else 0
            sleep(watch)
    except KeyboardInterrupt:
        return 0
