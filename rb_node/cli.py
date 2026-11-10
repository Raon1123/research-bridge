"""rb-node command line: serve-remote and stubs for later tasks."""
from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

SUBCOMMANDS = ("serve-remote", "serve-local", "run-job", "respond", "harness-receive",
               "approve-key", "config", "git-status", "install-record", "doctor", "link")


# keys a session driven by bridge messages must not move: the approval verifier path, the roots
# that bound what the bridge reads and writes, and the withheld pattern source (SEC-01)
GUARDED_KEYS = ("withheld_source", "approval_path", "read_roots", "write_roots")


def _interactive() -> bool:
    """True when a person is at a terminal (stdin and stdout). Tests replace this."""
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except (AttributeError, ValueError, OSError):
        return False


def _ask(prompt: str) -> bool:
    """Write the prompt, read one stdin line; y or yes is True. Tests replace this."""
    sys.stdout.write(prompt + " ")
    sys.stdout.flush()
    try:
        line = sys.stdin.readline()
    except (OSError, ValueError):
        return False
    return line.strip().lower() in ("y", "yes")


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


def _config(rest: List[str]) -> int:
    """Create, edit and check node.json. Node console only: no bridge op reaches this."""
    import json
    from . import configure as c
    from .config import config_path
    ap = argparse.ArgumentParser(prog="rb-node config")
    sub = ap.add_subparsers(dest="action", required=True)
    sub.add_parser("path", help="print the node.json path (RB_NODE_CONFIG overrides it)")
    i = sub.add_parser("init", help="write node.json with the defaults (mode 600)")
    i.add_argument("--force", action="store_true", help="overwrite an existing file")
    sub.add_parser("show", help="print node.json")
    s = sub.add_parser("set", help="set one key; lists take JSON, e.g. '[\"a\", \"b\"]'")
    s.add_argument("key")
    s.add_argument("value")
    sub.add_parser("check", help="list what is missing; exit 1 when a check fails")
    ns = ap.parse_args(rest)
    path = config_path()
    try:
        if ns.action == "path":
            print(path)
            return 0
        if ns.action == "init":
            if path.exists() and not ns.force:
                sys.stderr.write("%s exists; use --force to overwrite\n" % path)
                return 1
            if path.exists() and not _interactive():
                try:
                    old = c.read_json(path)
                except (c.ConfigError, OSError):
                    old = {}
                dflt = c.node_defaults()
                for k in GUARDED_KEYS:
                    if old.get(k) and old.get(k) != dflt.get(k):
                        sys.stderr.write("rb-node config init --force would reset %s; "
                                         "run it in an interactive terminal\n" % k)
                        return 1
            c.write_json(path, c.node_defaults())
            print("wrote %s" % path)
            return 0
        if not path.is_file():
            sys.stderr.write("no %s; run `rb-node config init` first\n" % path)
            return 1
        data = c.read_json(path)
        if ns.action == "show":
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return 0
        if ns.action == "set":
            if ns.key in GUARDED_KEYS and not _interactive():
                sys.stderr.write("rb-node config set %s must be run by the user in "
                                 "an interactive terminal\n" % ns.key)
                return 1
            c.write_json(path, c.node_set(data, ns.key, c.parse_value(ns.value)))
            print("%s set" % ns.key)
            return 0
        from . import doctor
        checks = doctor.config_checks(data, path)
        print(doctor.render(checks, only_problems=True))
        return doctor.exit_code(checks)
    except (c.ConfigError, OSError) as exc:
        sys.stderr.write("rb-node config: %s\n" % exc)
        return 1


def _approve_key(rest: List[str]) -> int:
    """Set or clear the job approval verifier. Node console only: no bridge op reaches this."""
    import getpass
    from pathlib import Path
    from . import approval
    from .config import load_config
    if rest not in (["set"], ["clear"]):
        sys.stderr.write("usage: rb-node approve-key set|clear\n")
        return 2
    try:
        cfg = load_config()
    except (OSError, ValueError) as exc:
        sys.stderr.write("rb-node: %s\n" % exc)
        return 1
    path = Path(cfg.approval_path)
    if not _interactive():
        sys.stderr.write("rb-node approve-key must be run by the user in an interactive "
                         "terminal\n")
        return 1
    if rest == ["clear"]:
        if not _ask("Remove the approval verifier? [y/N]"):
            sys.stderr.write("not removed\n")
            return 1
        if path.exists():
            path.unlink()
        print("approval verifier removed; job_submit and job_cancel are refused")
        return 0
    pw = getpass.getpass("New approval passphrase: ")
    if len(pw) < approval.MIN_PASSPHRASE:
        sys.stderr.write("passphrase must have at least %d characters\n" % approval.MIN_PASSPHRASE)
        return 1
    if getpass.getpass("Repeat: ") != pw:
        sys.stderr.write("passphrases differ\n")
        return 1
    rec, _key = approval.make_record(pw)
    approval.write_record(path, rec)
    print("approval verifier written to %s" % path)
    return 0


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
    return run_job(gpus, ns.gpu_hours, ns.job_id, argv, Path(cfg.mailbox_root) / "state",
                   trm_root=Path(cfg.trm_root))


def _git_status() -> int:
    """Print the git state of trm_root and the install record (node console, read only)."""
    import json
    from pathlib import Path
    from . import gitinfo
    from .config import load_config
    try:
        cfg = load_config()
    except (OSError, ValueError) as exc:
        sys.stderr.write("rb-node: %s\n" % exc)
        return 1
    print(json.dumps({"trm": gitinfo.repo_state(Path(cfg.trm_root)),
                      "install": gitinfo.read_install(Path(cfg.mailbox_root).parent)},
                     indent=2))
    return 0


def _install_record(rest: List[str]) -> int:
    """Write ~/.research-bridge/install.json from a research-bridge checkout (node-install.sh)."""
    from pathlib import Path
    from . import __version__, gitinfo
    from .config import DEFAULT_RB, _home
    if len(rest) != 1:
        sys.stderr.write("usage: rb-node install-record <research-bridge checkout>\n")
        return 2
    rec = gitinfo.write_install(Path(_home(DEFAULT_RB)), Path(rest[0]), __version__)
    src = rec["source"]
    print("install record: version %s, commit %s%s" % (
        rec["version"], (src.get("head") or "unknown")[:12],
        " (dirty)" if src.get("dirty_files") else ""))
    return 0


SUBHELP = {
    "doctor": "usage: rb-node doctor\n\nRun every node check (configuration, approval, withheld patterns, authorized_keys,\n"
              "responder, git exposure) and print one line per check. Exit 1 when a check fails.\n",
    "link": "usage: rb-node link [DIR] [--apply]\n\nPrint the .mcp.json entry that links a Claude session on the node to the local\n"
            "rb-node MCP server. DIR defaults to trm_root. With --apply, write DIR/.mcp.json\n"
            "(refused when it exists).\n",
    "approve-key": "usage: rb-node approve-key set|clear\n\nset: ask for the approval passphrase twice and store its verifier.\n"
                   "clear: remove the verifier. Both need an interactive terminal.\n",
    "git-status": "usage: rb-node git-status\n\nPrint, as JSON, the git state of trm_root and the install record. Read only.\n",
    "config": "usage: rb-node config path|init [--force]|show|set KEY VALUE|check [-h]\n\n"
              "path: print the node.json path. init: write the defaults (mode 600). show: print node.json.\n"
              "set: set one key; lists take JSON. check: list what is missing; exit 1 when a check fails.\n"
              "Setting approval_path, read_roots, write_roots or withheld_source needs an interactive terminal.\n",
}


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "run-job":
        return _run_job(args[1:])
    if len(args) >= 2 and args[0] in SUBHELP and args[1] in ("-h", "--help"):
        sys.stdout.write(SUBHELP[args[0]])
        return 0
    parser = argparse.ArgumentParser(prog="rb-node")
    parser.add_argument("command", choices=SUBCOMMANDS)
    ns, _rest = parser.parse_known_args(argv)
    if ns.command == "serve-remote":
        # SSH_ORIGINAL_COMMAND is deliberately ignored: the protocol is on stdin.
        from .config import load_config
        from .remote import serve, serve_unconfigured
        try:
            cfg = load_config()
        except (FileNotFoundError, ValueError) as exc:
            # Missing or invalid node.json: stay alive so the hub's `hello` can say so.
            sys.stderr.write("rb-node: %s\n" % exc)
            return serve_unconfigured(sys.stdin.buffer, sys.stdout.buffer)
        except OSError as exc:
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
    if ns.command == "approve-key":
        return _approve_key(_rest)
    if ns.command == "config":
        return _config(_rest)
    if ns.command == "git-status":
        return _git_status()
    if ns.command == "install-record":
        return _install_record(_rest)
    if ns.command == "doctor":
        from . import doctor
        checks = doctor.run()
        print(doctor.render(checks, only_problems=False))
        return doctor.exit_code(checks)
    if ns.command == "link":
        from . import link
        return link.main(_rest)
    return _not_implemented(ns.command)


if __name__ == "__main__":
    sys.exit(main())
