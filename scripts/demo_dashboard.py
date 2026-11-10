"""Local demo of the research-bridge dashboard pages, with made-up data only.

    python scripts/demo_dashboard.py [--port 8799] [--web-port 8800] [--dir <empty dir>]

Builds a throwaway node (a local `rb_node.cli serve-remote` subprocess, the same mechanism the
tests use, no SSH), a fake trm tree, a ledger with two pending jobs, a portfolio and a
priorities file, and one stored conversation (a question, a node reply that `rb sync` stored,
and a follow-up). It then serves on 127.0.0.1 the two 8765 pages and the hub page of `rb web`:

    /rb/pending   approval page (rb_pending.py); passphrase: demo passphrase
    /board        unified board (rb_board.py)
    web port      hub page (rb_host/web.py): /, /threads, /thread/<id>, /jobs, /nodes

Approving a job runs the real path: `jobs.approve` derives the key, the node checks it and
writes a queue file, and the board cache is refreshed so `/board` shows it. Nothing outside
--dir is read or written; no real node, ledger or vault file is touched.
Needs the board (rb_host/board.py) and node-side approval (rb_node/approval.py).
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import shutil
import signal
import sys
import tempfile
import threading
import urllib.parse
from pathlib import Path
from typing import Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(1, str(REPO / "vault-export" / "dashboard"))

# rb_host is imported before the page modules: they put the installed checkout on sys.path,
# and the modules already imported from this repository win.
from rb_host import board, jobs, server, sync, web  # noqa: E402
from rb_host.client import NodeClient  # noqa: E402
from rb_node import approval  # noqa: E402
from rb_node.mailbox import Mailbox  # noqa: E402

import rb_board  # noqa: E402
import rb_pending  # noqa: E402

PASSPHRASE = "demo passphrase"
NODE = "demo-node"
STATE_MD = "---\nphase: S5 analysis\ntrack: ARG\nupdated: 2026-11-03\n---\n# State\n"
EVENTS = [
    {"ts": "2026-11-03T08:10:00Z", "stage": "S4", "kind": "monitor", "track": "ARG"},
    {"ts": "2026-11-03T09:25:00Z", "stage": "S5", "kind": "analysis", "track": "ARG"},
    {"ts": "2026-11-03T09:40:00Z", "stage": "S5", "kind": "report", "track": "LEN"},
]
KANBAN = {"cards": [{"column": "todo", "title": "a"}, {"column": "doing", "title": "b"},
                    {"column": "doing", "title": "c"}, {"column": "done", "title": "d"}]}
PORTFOLIO = {"columns": ["ready", "gated", "drafting"], "papers": [
    {"paper_id": "p0", "short": "Paper A", "column": "drafting",
     "tasks": [{"task_id": "a1", "title": "choose baseline", "status": "todo", "user_action": True},
               {"task_id": "a2", "title": "read related work", "status": "todo",
                "user_action": True}]},
    {"paper_id": "p1", "short": "Paper B", "column": "gated", "tasks": []},
    {"paper_id": "p2", "short": "Paper C", "column": "ready", "tasks": []}]}
PRIORITIES = {"meta": {"refreshed": "2026-11-03 09:00"},
              "items": [{"key": "D1", "title": "decide the job template", "actor": "user",
                         "status": "open"},
                        {"key": "D2", "title": "rerun seed sweep", "actor": "server",
                         "status": "open"}],
              "ranking": {"tiers": [{"tier": "now", "keys": ["D1", "D2"]}]}}


def _fake_nvidia_smi(bin_dir: Path) -> None:
    rows = ["0, Demo GPU, 1024, 24576, 3", "1, Demo GPU, 20480, 24576, 97"]
    bin_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        (bin_dir / "nvidia-smi.bat").write_text(
            "@echo off\r\n" + "".join("echo %s\r\n" % r for r in rows), encoding="ascii")
    else:
        p = bin_dir / "nvidia-smi"
        p.write_text("#!/bin/sh\n" + "".join("echo '%s'\n" % r for r in rows), encoding="ascii")
        p.chmod(0o755)


def build(root: Path) -> dict:
    """Write the demo node, host config and data under root; return the node subprocess env."""
    trm = root / "trm"
    for d in ("lab/state", "lab/monitor", "scripts/queue/jobs", "scripts/queue/processing",
              "scripts/queue/done"):
        (trm / d).mkdir(parents=True, exist_ok=True)
    (trm / "lab/state/STATE.md").write_text(STATE_MD, encoding="utf-8")
    (trm / "lab/monitor/events.json").write_text(
        "\n".join(json.dumps(e) for e in EVENTS) + "\n", encoding="utf-8")
    (trm / "lab/monitor/kanban.json").write_text(json.dumps(KANBAN), encoding="utf-8")
    (trm / "scripts/queue/processing/0001_warmup.job").write_text("x", encoding="utf-8")
    (trm / "scripts/queue/done/0000_smoke.job").write_text("x", encoding="utf-8")
    mb = root / "node" / "mailbox"
    node_conf = {
        "trm_root": str(trm), "read_roots": ["lab/state", "lab/monitor", str(mb / "out")],
        "write_roots": [str(mb / "in")], "queue_dir": str(trm / "scripts" / "queue"),
        "withheld_source": None, "claude_bin": str(root / "no-claude"), "mailbox_root": str(mb),
        "audit_path": str(root / "node" / "audit.jsonl"),
        "approval_path": str(root / "node" / "approve.json"),
        "job_template": ["python", "train.py", "--config", "{config}"],
        "allowed_gpus": [0, 1]}
    (root / "node.json").write_text(json.dumps(node_conf), encoding="utf-8")
    approval.write_record(Path(node_conf["approval_path"]),
                          approval.make_record(PASSPHRASE, iterations=approval.MIN_ITERATIONS)[0])
    (root / "withheld.json").write_text(json.dumps({"patterns": []}), encoding="utf-8")
    (root / "portfolio.json").write_text(json.dumps(PORTFOLIO), encoding="utf-8")
    (root / "live.json").write_text(json.dumps(PRIORITIES), encoding="utf-8")
    data = root / "data"
    host = {"nodes": {NODE: {"alias": "demo", "board": {
                "state": "lab/state/STATE.md", "events": "lab/monitor/events.json",
                "kanban": "lab/monitor/kanban.json"}}},
            "data_root": str(data), "withheld_patterns_file": str(root / "withheld.json"),
            "board": {"portfolio": str(root / "portfolio.json"),
                      "priorities": str(root / "live.json")}}
    (root / "host.json").write_text(json.dumps(host), encoding="utf-8")
    os.environ["RB_HOST_CONFIG"] = str(root / "host.json")
    os.environ["RB_HOST_ROOT"] = str(data)
    _fake_nvidia_smi(root / "bin")
    return {"RB_NODE_CONFIG": str(root / "node.json"), "PYTHONPATH": str(REPO),
            "PATH": str(root / "bin") + os.pathsep + os.environ.get("PATH", "")}


def seed(root: Path) -> None:
    cfg = jobs.load_cfg()
    led = jobs.ledger_for(cfg)
    for name, gpus, hours, note in (("sweep-lr.yaml", [0], 4, "lr sweep, 3 values"),
                                    ("ablation-depth.yaml", [1], 12, "depth ablation")):
        p = root / "configs" / name
        p.parent.mkdir(exist_ok=True)
        p.write_text("lr: 0.001\n", encoding="utf-8")
        jobs.create_submit(led, cfg, NODE, str(p), gpus, hours, "demo-" + name, note=note)
    led.append({"kind": "message", "id": "demo-reply-1", "direction": "in", "node": NODE,
                "msg_kind": "reply", "status": "received", "created": "2026-11-03T09:41:00Z"})
    # one conversation through the real code paths: send, a node reply stored by rb sync
    # (delivered: false, so the next poll returns it), and a follow-up to that reply
    m1 = server.send_message(NODE, "Demo question: which learning rates finished?")["msg_id"]
    oid = Mailbox(root / "node" / "mailbox").post_out(
        "reply", "Demo answer: all three learning rates finished.", [], m1)
    sync.run_pass(cfg, NODE)
    server.send_message(NODE, "Demo follow-up: please queue the depth ablation.", reply_to=oid)
    board.refresh(cfg)


def map_host(host: Optional[str], port: int) -> Optional[str]:
    """The vault page modules accept only 127.0.0.1:8765 / localhost:8765. The demo listens on
    another port, so its own loopback names are presented to them as the 8765 name; any other
    or missing Host is passed unchanged (the module then answers 403)."""
    if isinstance(host, str) and host.lower() in ("127.0.0.1:%d" % port, "localhost:%d" % port):
        return "127.0.0.1:8765"
    return host


def map_origin(origin: Optional[str], port: int) -> Optional[str]:
    if isinstance(origin, str) and origin.lower() in ("http://127.0.0.1:%d" % port,
                                                      "http://localhost:%d" % port):
        return "http://127.0.0.1:8765"
    return origin


class Handler(http.server.BaseHTTPRequestHandler):
    def _host(self) -> Optional[str]:
        return map_host(self.headers.get("Host"), self.server.server_address[1])

    def _send(self, status: int, text: str, ctype: str = "text/html") -> None:
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "%s; charset=utf-8" % ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/":
            self.send_response(302)
            self.send_header("Location", "/board")
            self.end_headers()
        elif self.path == "/rb/pending":
            self._send(*rb_pending.handle_get(self.client_address[0], self._host()))
        elif self.path == "/board":
            self._send(*rb_board.handle_get(self.client_address[0], self._host()))
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self) -> None:  # same form handling as vault-export/dashboard/server.py.patch
        if self.path not in ("/rb/approve", "/rb/reject"):
            self._send(404, "not found", "text/plain")
            return
        length = int(self.headers.get("Content-Length", "0"))
        qs = urllib.parse.parse_qs(self.rfile.read(min(length, 65536)).decode("utf-8", "replace"))
        form = {k: v[0] for k, v in qs.items()}
        origin = map_origin(self.headers.get("Origin"), self.server.server_address[1])
        status, text = rb_pending.handle_post(self.client_address[0], form, rb_pending.CSRF_TOKEN,
                                              self.path.rsplit("/", 1)[1], self._host(), origin)
        if status == 200:
            board.refresh(jobs.load_cfg())
        self._send(status, text + '\n\n<a href="/rb/pending">back to pending</a> · '
                   '<a href="/board">board</a>' if status == 200 else text,
                   "text/html" if status == 200 else "text/plain")

    def log_message(self, fmt: str, *args: object) -> None:  # request line only, never bodies
        sys.stderr.write("%s\n" % (fmt % args))


def start(root: Path, port: int, web_port: int) -> Tuple[http.server.ThreadingHTTPServer,
                                                          http.server.ThreadingHTTPServer]:
    """Build and seed the demo under `root`; return the 8765-style server and the hub page server
    (bound, not yet serving). Installs the local-node connection in `jobs.connect`."""
    root.mkdir(parents=True, exist_ok=True)
    nenv = build(root)
    os.chdir(str(REPO))  # `python -m rb_node.cli` puts the cwd first on sys.path
    serve = [sys.executable, "-m", "rb_node.cli", "serve-remote"]
    jobs.connect = lambda cfg, node: NodeClient("demo", ssh_argv=serve, env=nenv)
    seed(root)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    try:
        web_srv = web.make_server(jobs.load_cfg(), "127.0.0.1", web_port)
    except BaseException:
        srv.server_close()
        raise
    return srv, web_srv


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--web-port", type=int, default=None, help="hub page port (default: port + 1)")
    ap.add_argument("--dir", help="empty directory for the demo data (default: a new temp dir)")
    a = ap.parse_args()
    temp = not a.dir  # a directory this script created is removed on exit; --dir is left alone
    root = Path(a.dir) if a.dir else Path(tempfile.mkdtemp(prefix="rb-demo-"))

    def stop(signum: int, frame: object) -> None:  # SIGTERM ends like Ctrl+C
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        srv, web_srv = start(root, a.port, a.web_port if a.web_port is not None else a.port + 1)
        threading.Thread(target=web_srv.serve_forever, daemon=True).start()
        print("demo data: %s" % root, flush=True)
        print("open http://127.0.0.1:%d/board and /rb/pending (passphrase: %s)" % (
            srv.server_address[1], PASSPHRASE), flush=True)
        print("hub page: http://127.0.0.1:%d/ (also /threads, /jobs, /nodes)"
              % web_srv.server_address[1], flush=True)
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        os.chdir("/")  # start() changed into the repository; do not stay inside what is removed
        if temp:
            shutil.rmtree(str(root), ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
