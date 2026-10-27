"""rb-node command line: serve-remote and stubs for later tasks."""
from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

SUBCOMMANDS = ("serve-remote", "serve-local", "run-job", "respond", "harness-receive")


def _not_implemented(name: str) -> int:
    sys.stderr.write("rb-node %s: not implemented yet\n" % name)
    return 2


def _harness_receive() -> int:
    # Forced command for the harness key; harness-send is only reachable through it.
    from .config import load_config
    from .harness import harness_receive
    cmd = os.environ.get("SSH_ORIGINAL_COMMAND", "")
    if cmd not in ("", "harness-push", "harness-send"):
        sys.stderr.write("rb-node harness-receive: unknown command\n")
        return 1
    try:
        cfg = load_config()
    except (OSError, ValueError) as exc:
        sys.stderr.write("rb-node: %s\n" % exc)
        return 1
    return harness_receive(cfg, cmd, sys.stdin.buffer, sys.stdout.buffer)


def _run_job(args: List[str]) -> int:
    from pathlib import Path
    from .config import load_config
    from .run_job import run_job
    if "--" not in args:
        sys.stderr.write("rb-node run-job: missing -- before command\n")
        return 2
    i = args.index("--")
    p = argparse.ArgumentParser(prog="rb-node run-job")
    p.add_argument("--gpus", required=True)
    p.add_argument("--gpu-hours", type=float, required=True)
    p.add_argument("--job-id", required=True)
    ns = p.parse_args(args[:i])
    argv = args[i + 1:]
    try:
        gpus = [int(g) for g in ns.gpus.split(",")]
        cfg = load_config()
    except (OSError, ValueError) as exc:
        sys.stderr.write("rb-node run-job: %s\n" % exc)
        return 2
    if not argv or not gpus or ns.gpu_hours <= 0:
        sys.stderr.write("rb-node run-job: invalid arguments\n")
        return 2
    return run_job(gpus, ns.gpu_hours, ns.job_id, argv, Path(cfg.mailbox_root) / "state")


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "run-job":
        return _run_job(args[1:])
    parser = argparse.ArgumentParser(prog="rb-node")
    parser.add_argument("command", choices=SUBCOMMANDS)
    ns, _rest = parser.parse_known_args(argv)
    if ns.command == "serve-remote":
        # SSH_ORIGINAL_COMMAND is deliberately ignored: the protocol is on stdin.
        from .config import load_config
        from .remote import serve
        try:
            cfg = load_config()
        except (OSError, ValueError) as exc:
            sys.stderr.write("rb-node: %s\n" % exc)
            return 1
        return serve(cfg, sys.stdin.buffer, sys.stdout.buffer)
    if ns.command == "serve-local":
        from .config import load_config
        from .local import serve_local
        try:
            cfg = load_config()
        except (OSError, ValueError) as exc:
            sys.stderr.write("rb-node: %s\n" % exc)
            return 1
        for stream in (sys.stdin, sys.stdout):
            try:
                stream.reconfigure(encoding="utf-8")
            except (AttributeError, ValueError):
                pass
        return serve_local(cfg, sys.stdin, sys.stdout)
    if ns.command == "respond":
        from .config import load_config
        from .spawn import respond
        if len(_rest) != 1:
            sys.stderr.write("usage: rb-node respond <msg_id>\n")
            return 2
        try:
            cfg = load_config()
        except (OSError, ValueError) as exc:
            sys.stderr.write("rb-node: %s\n" % exc)
            return 1
        return respond(cfg, _rest[0])
    if ns.command == "harness-receive":
        return _harness_receive()
    return _not_implemented(ns.command)


if __name__ == "__main__":
    sys.exit(main())
