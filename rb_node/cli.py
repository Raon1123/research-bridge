"""rb-node command line: serve-remote and stubs for later tasks."""
from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

SUBCOMMANDS = ("serve-remote", "serve-local", "run-job", "respond", "harness-receive", "harness-send")


def _not_implemented(name: str) -> int:
    sys.stderr.write("rb-node %s: not implemented yet\n" % name)
    return 2


def _harness_receive() -> int:
    # Forced command for the harness key. Task 10 implements both paths.
    cmd = os.environ.get("SSH_ORIGINAL_COMMAND", "")
    if cmd in ("", "harness-send"):
        return _not_implemented("harness-receive")
    sys.stderr.write("rb-node harness-receive: unknown command\n")
    return 1


def main(argv: Optional[List[str]] = None) -> int:
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
    if ns.command == "harness-receive":
        return _harness_receive()
    return _not_implemented(ns.command)


if __name__ == "__main__":
    sys.exit(main())
