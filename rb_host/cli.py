"""rb: user-run approval CLI. Approval happens here (or the localhost 8765 endpoint), never in MCP."""
from __future__ import annotations

import argparse
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
    if not args.yes:
        sys.stdout.write("Approve? [y/N] ")
        sys.stdout.flush()
        ans = sys.stdin.readline().strip().lower()
        if ans not in ("y", "yes"):
            print("not approved")
            return 1
    try:
        out = jobs.approve(led, cfg, args.job_id)
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
    print("rb harness %s: not implemented yet" % args.action)
    return 2


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
    h = sub.add_parser("harness")
    h.add_argument("action", choices=["push", "pull", "diff"])
    h.add_argument("--node")
    h.set_defaults(fn=_harness)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
