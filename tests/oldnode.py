"""Stand-in for the node code before protocol 2 (serve-remote of the 2026-11-05 tree).

`hello` answers only `node`, `version`, `withheld_extra`. The ops the tests pin (hello, poll, ack,
git_status and an unknown op) answer as the current code does; the op names in OLD_OPS equal the
current table, so the filter removes none. Bodies of job_submit, job_cancel and the withheld
count differ from origin/main and are not pinned here.
Run as a script with `RB_NODE_CONFIG` and `PYTHONPATH` set, like `rb-node serve-remote`.
"""
from __future__ import annotations

import socket
import sys
from pathlib import Path

OLD_OPS = ("hello", "msg_begin", "put_chunk", "msg_commit", "poll", "ack", "get_file",
           "read_doc", "queue_status", "gpu_status", "job_submit", "job_cancel",
           "approve_params", "git_status")

SERVE_OLD = [sys.executable, str(Path(__file__).resolve())]


def main() -> int:
    from rb_node.config import load_config
    from rb_node import remote

    class OldNode(remote.Node):
        def __init__(self, cfg):
            super().__init__(cfg)
            self.ops = {k: v for k, v in self.ops.items() if k in OLD_OPS}
            self.ops["hello"] = self.old_hello

        def old_hello(self, args):
            return {"node": socket.gethostname(), "version": "0.1.0",
                    "withheld_extra": self.withheld.extra_count}

    return remote._loop(OldNode(load_config()), sys.stdin.buffer, sys.stdout.buffer)


if __name__ == "__main__":
    sys.exit(main())
