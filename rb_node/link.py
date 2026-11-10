"""rb-node link: register `rb-node serve-local` as a project MCP server for a live session."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import List, Optional

from . import spawn

WARNING = ("warning: a live session and the spawned responder are not arbitrated; both can answer "
           "the same message (GitHub issue 41).")


def _launcher() -> Optional[str]:
    argv = spawn.launcher_argv()
    if argv and os.path.isabs(argv[0]) and len(argv) == 1:
        return argv[0]
    fallback = os.path.expanduser("~/.local/bin/rb-node")
    if os.path.isfile(fallback) and os.access(fallback, os.X_OK):
        return fallback
    return None


def entry(cfg_path_env: Optional[str]) -> dict:
    launcher = _launcher()
    if launcher is None:
        raise FileNotFoundError("rb-node is not installed; run scripts/node-install.sh")
    server = {"type": "stdio", "command": launcher, "args": ["serve-local"]}  # type: dict
    if cfg_path_env:
        server["env"] = {"RB_NODE_CONFIG": cfg_path_env}
    return {"mcpServers": {"rb-node": server}}


def main(argv: List[str]) -> int:
    apply = "--apply" in argv
    rest = [a for a in argv if a != "--apply"]
    if len(rest) > 1 or any(a.startswith("-") for a in rest):
        sys.stderr.write("usage: rb-node link [DIR] [--apply]\n")
        return 2
    try:
        if rest:
            target = Path(rest[0])
        else:
            from .config import load_config
            target = Path(load_config().trm_root)
        data = entry(os.environ.get("RB_NODE_CONFIG"))
    except FileNotFoundError as exc:
        sys.stderr.write("%s\n" % exc)
        return 1
    except (OSError, ValueError) as exc:
        sys.stderr.write("rb-node link: %s\n" % exc)
        return 1
    text = json.dumps(data, indent=2)
    print(text)
    print(WARNING)
    if not apply:
        return 0
    path = target / ".mcp.json"
    if path.exists():
        print("%s exists; merge by hand or run: claude mcp add --scope project rb-node -- %s "
              "serve-local" % (path, data["mcpServers"]["rb-node"]["command"]))
        return 1
    path.write_text(text + "\n", encoding="utf-8")
    print("wrote %s" % path)
    return 0
