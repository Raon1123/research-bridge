"""rb: user-run approval CLI. Approval happens here (or the localhost 8765 endpoint), never in MCP."""
from __future__ import annotations

import argparse
import getpass
import sys
from typing import List, Optional

from . import jobs
from .client import RemoteError, TransportError


def _approve(args: argparse.Namespace) -> int:
    cfg = jobs.load_cfg()
    led = jobs.ledger_for(cfg)
    rec = led.get(args.job_id)
    if rec is None or rec.get("kind") != "job":
        print("unknown job: %s" % args.job_id)
        return 1
    print(jobs.describe(rec))
    print("status: %s" % rec["status"])
    if rec["status"] in jobs.DONE.values():
        print("already %s" % rec["status"])
        return 0
    if rec["status"] not in ("pending_approval", "approved"):
        print("job is %s, cannot approve" % rec["status"])
        return 1
    if not args.yes:
        sys.stdout.write("Approve? [y/N] ")
        sys.stdout.flush()
        ans = sys.stdin.readline().strip().lower()
        if ans not in ("y", "yes"):
            print("not approved")
            return 1
    # always typed by the user, also with --yes; there is no flag, file or variable for it
    passphrase = getpass.getpass("Approval passphrase: ")
    if not passphrase:
        print("not approved")
        return 1
    try:
        out = jobs.approve(led, cfg, args.job_id, passphrase)
    except (ValueError, RemoteError, TransportError) as exc:
        print("error: %s" % exc)
        return 1
    print(out["status"])
    return 0


def _reject(args: argparse.Namespace) -> int:
    cfg = jobs.load_cfg()
    try:
        out = jobs.reject(jobs.ledger_for(cfg), args.job_id)
    except ValueError as exc:
        print("error: %s" % exc)
        return 1
    print(out["status"])
    return 0


def _pending(args: argparse.Namespace) -> int:
    led = jobs.ledger_for(jobs.load_cfg())
    for r in led.pending_jobs():
        print(jobs.describe(r))
        print("---")
    return 0


def _harness(args: argparse.Namespace) -> int:
    from . import harness
    cfg = jobs.load_cfg()
    try:
        if args.action == "diff":
            out = harness.diff(cfg, args.stamp)
            sys.stdout.write(out if out else "no differences\n")
            return 0
        if not args.node:
            print("error: --node is required")
            return 1
        if args.action == "push":
            for line in harness.push(cfg, args.node, args.dry_run):
                print(line)
            return 0
        path, n = harness.pull(cfg, args.node)
        print("pulled %d files into %s" % (n, path))
        return 0
    except (harness.HarnessError, ValueError, TransportError) as exc:
        print("error: %s" % exc)
        return 1


def _board(args: argparse.Namespace) -> int:
    import json
    from . import board
    from .config import HostConfig
    try:
        cfg = jobs.load_cfg()
    except FileNotFoundError:
        if args.action == "refresh":
            print("error: no host.json; see docs/manual/hub-setup.md")
            return 1
        cfg = HostConfig()  # show: laptop sources only, as the 8765 page does
    if args.action == "refresh":
        try:
            results = board.refresh(cfg, args.node, args.source or None)
        except ValueError as exc:
            print("error: %s" % exc)
            return 1
        for r in results:
            print("%s %s" % (r["source"], "ok" if r["ok"] else "error %s" % r["error"]))
        return 0
    b = board.load(cfg)
    sys.stdout.write(json.dumps(b, ensure_ascii=False, indent=1) + "\n" if args.json
                     else board.render_text(b))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="rb")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pending").set_defaults(fn=_pending)
    a = sub.add_parser("approve")
    a.add_argument("job_id")
    a.add_argument("--yes", action="store_true", help="skip the y/N prompt")
    a.set_defaults(fn=_approve)
    r = sub.add_parser("reject")
    r.add_argument("job_id")
    r.set_defaults(fn=_reject)
    h = sub.add_parser("harness", help="manual harness channel (no apply command exists)")
    hs = h.add_subparsers(dest="action", required=True)
    hp = hs.add_parser("push", help="send the allowlisted laptop harness to node staging")
    hp.add_argument("--node", required=True)
    hp.add_argument("--dry-run", action="store_true", help="list files, send nothing")
    hl = hs.add_parser("pull", help="fetch the node's allowlisted harness into laptop staging")
    hl.add_argument("--node", required=True)
    hd = hs.add_parser("diff", help="unified diff of a pulled staging dir against the live harness")
    hd.add_argument("stamp")
    h.set_defaults(fn=_harness)
    b = sub.add_parser("board", help="unified board cache (read only; approval stays on rb approve)")
    bs = b.add_subparsers(dest="action", required=True)
    br = bs.add_parser("refresh", help="fetch node sources through the bridge into the board cache")
    br.add_argument("--node")
    br.add_argument("--source", action="append", choices=["queue", "gpu", "state", "events",
                                                          "kanban"])
    bw = bs.add_parser("show", help="print the board from the cache; opens no connection")
    bw.add_argument("--json", action="store_true")
    b.set_defaults(fn=_board)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
