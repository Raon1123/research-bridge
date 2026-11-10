"""rb: user-run approval CLI. Approval happens here (or the localhost 8765 endpoint), never in MCP."""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from typing import List, Optional

from . import configure, jobs
from .config import HostConfig, default_root
from .client import RemoteError, TransportError


def _interactive() -> bool:
    """True only when a person is at a terminal. Tests replace this; no flag or variable does."""
    try:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return False
        if os.name == "nt":
            # os.isatty() is also True for the NUL device; only a real console answers
            # GetConsoleMode.
            import ctypes
            import msvcrt
            mode = ctypes.c_uint32()
            for stream in (sys.stdin, sys.stdout):
                handle = msvcrt.get_osfhandle(stream.fileno())
                if not ctypes.windll.kernel32.GetConsoleMode(ctypes.c_void_p(handle),
                                                             ctypes.byref(mode)):
                    return False
        return True
    except (AttributeError, ValueError, OSError):
        return False


def _need_terminal(what: str) -> bool:
    if _interactive():
        return True
    print("error: rb %s must be run by the user in an interactive terminal "
          "(stdin and stdout must be a terminal); a session cannot run it" % what)
    return False


def _host_cfg() -> Optional[HostConfig]:
    """host.json, or None after one error line (no traceback)."""
    try:
        return jobs.load_cfg()
    except (FileNotFoundError, ValueError) as exc:
        print(configure.host_json_error(exc))
        return None


def _approve(args: argparse.Namespace) -> int:
    if not _need_terminal("approve"):
        return 1
    cfg = _host_cfg()
    if cfg is None:
        return 1
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
    sys.stdout.write("Approve? [y/N] ")
    sys.stdout.flush()
    ans = sys.stdin.readline().strip().lower()
    if ans not in ("y", "yes"):
        print("not approved")
        return 1
    # always typed by the user; there is no flag, file or variable for it
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
    if not _need_terminal("reject"):
        return 1
    cfg = _host_cfg()
    if cfg is None:
        return 1
    try:
        out = jobs.reject(jobs.ledger_for(cfg), args.job_id)
    except ValueError as exc:
        print("error: %s" % exc)
        return 1
    print(out["status"])
    return 0


def _pending(args: argparse.Namespace) -> int:
    cfg = _host_cfg()
    if cfg is None:
        return 1
    led = jobs.ledger_for(cfg)
    for r in led.pending_jobs():
        print(jobs.describe(r))
        print("---")
    return 0


def _harness(args: argparse.Namespace) -> int:
    from . import harness
    cfg = _host_cfg()
    if cfg is None:
        return 1
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


def _git_status(args: argparse.Namespace) -> int:
    """Ask the node for the git state of its research tree and installed code (read only)."""
    import json
    from .client import NodeClient
    cfg = _host_cfg()
    if cfg is None:
        return 1
    try:
        name = args.node or (next(iter(cfg.nodes)) if len(cfg.nodes) == 1 else "")
        if not name:
            print("error: --node is required")
            return 1
        with NodeClient(cfg.alias(name)) as c:
            res = c.call("git_status")
    except (ValueError, RemoteError, TransportError) as exc:
        print("error: %s" % exc)
        return 1
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


def _setup(args: argparse.Namespace) -> int:
    from . import setup
    if not args.yes_print_only and not _need_terminal("setup"):
        return 1
    return setup.main(setup.Args(node=args.node, host=args.host, port=args.port, user=args.user,
                                 keydir=args.keydir, hub_from=args.hub_from,
                                 research_root=args.research_root, print_only=args.yes_print_only))


def _agent(args: argparse.Namespace) -> int:
    from . import setup
    if not _need_terminal("agent"):
        return 1
    if _host_cfg() is None:
        return 1
    return setup.agent_main(args.node)


def _doctor(args: argparse.Namespace) -> int:
    from . import doctor
    return doctor.main(args.node, offline_only=args.offline)


def _service(args: argparse.Namespace) -> int:
    from . import service
    if args.action == "status":
        return service.status()
    if not args.print and not _need_terminal("service install"):
        return 1
    if _host_cfg() is None:
        return 1
    return service.install(args.interval, args.port, args.print)


def _sync(args: argparse.Namespace) -> int:
    """One pass (or --watch SECONDS) of everything that is safe to do unattended: fetch new node
    messages and events, refresh the board cache, read the git state. Hub to node only. Never
    approves a job and never touches the harness channel."""
    import json
    import time
    from . import board, server
    from .client import NodeClient

    def once() -> int:
        cfg = jobs.load_cfg()
        names = [args.node] if args.node else sorted(cfg.nodes)
        bad = 0
        for n in names:
            line = {"node": n}
            try:
                got = server._poll_node(cfg, n)
                line["new_items"] = len(got.get("items", [])) if isinstance(got, dict) else 0
                res = board.refresh(cfg, n)
                line["board"] = {r["source"].split(":")[1]: ("ok" if r["ok"] else r["error"])
                                 for r in res}
                with NodeClient(cfg.alias(n)) as c:
                    g = c.call("git_status")
                line["trm_head"] = (g.get("trm") or {}).get("head")
                line["trm_dirty"] = (g.get("trm") or {}).get("dirty_files")
            except (ValueError, RemoteError, TransportError, OSError) as exc:
                line["error"] = str(exc)
                bad += 1
            print(json.dumps(line, ensure_ascii=False), flush=True)
        return 1 if bad else 0

    if not args.watch:
        return once()
    if args.watch < 30:
        print("error: --watch must be at least 30 seconds")
        return 1
    try:
        while True:
            once()
            time.sleep(args.watch)
    except KeyboardInterrupt:
        return 0


def _share(args: argparse.Namespace) -> int:
    from . import share
    if args.action == "serve":
        from . import share_serve
        try:
            cfg = jobs.load_cfg()
            share_serve.serve(share.share_dir(cfg), args.bind, args.port)
        except (FileNotFoundError, ValueError, OSError) as exc:
            print("error: %s" % exc)
            return 1
        return 0
    try:
        cfg = jobs.load_cfg()
    except FileNotFoundError:
        print("error: no host.json; see docs/manual/hub-setup.md")
        return 1
    if args.days < 0:
        print("error: --days must be >= 0")
        return 1
    res = share.build(cfg, args.days, args.tier)
    for p in res["paths"]:
        print(p)
    conf = cfg.share if isinstance(cfg.share, dict) else {}
    if not isinstance(conf.get("labels"), list):
        print('labels not configured: all project and track labels shown as "other"')
    print("dropped %d" % res["dropped"])
    if res["dropped"] > 0:
        sys.stderr.write("dropped %d item(s) by the withheld re-check\n" % res["dropped"])
    return 1 if res["dropped"] > 0 else 0


def _config(args: argparse.Namespace) -> int:
    import json
    from . import configure as c
    try:
        if args.action == "path":
            print("host.json   %s" % c.host_path())
            print("local.json  %s" % c.local_path())
        elif args.action == "init":
            print("wrote %s" % c.init(args.data_root, args.force))
        elif args.action == "add-node":
            e = c.add_node(args.name, args.alias, args.harness_alias, args.force)
            print("node %s: alias %s, harness_alias %s" % (args.name, e["alias"], e["harness_alias"]))
        elif args.action == "remove-node":
            c.remove_node(args.name)
            print("node %s removed" % args.name)
        elif args.action == "set":
            c.set_key(args.key, args.value)
            print("%s set" % args.key)
        elif args.action == "local":
            if not (args.laptop_home or args.node_home):
                print("error: give --laptop-home and/or --node-home")
                return 1
            print("wrote %s" % c.set_local(args.laptop_home, args.node_home))
        elif args.action == "show":
            path = c.host_path()
            print("# %s" % path)
            print(json.dumps(c.read_json(path), ensure_ascii=False, indent=2) if path.is_file()
                  else "(missing)")
            lp = c.local_path()
            print("# %s" % lp)
            print(json.dumps(c.read_json(lp), ensure_ascii=False, indent=2) if lp.is_file()
                  else "(missing)")
        elif args.action == "mcp":
            print("Add under \"mcpServers\" in ~/.claude.json (rb does not edit that file):")
            print(json.dumps(c.mcp_entry(), indent=2)[1:-1].strip())
        else:
            from . import doctor
            return doctor.main(None, offline_only=True, only_problems=True)
    except c.ConfigError as exc:
        print("error: %s" % exc)
        return 1
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="rb")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pending").set_defaults(fn=_pending)
    su = sub.add_parser("setup", help="link a node: host.json, keys, ssh config, host key, agent, "
                        "node command, MCP command")
    su.add_argument("--node", required=True, metavar="NAME")
    su.add_argument("--host", default="")
    su.add_argument("--port", type=int, default=None)
    su.add_argument("--user", default="")
    su.add_argument("--keydir", default="", help="key directory (default ~/.ssh/research-bridge)")
    su.add_argument("--hub-from", default="", help="address the node sees this hub as")
    su.add_argument("--research-root", default="", help="research tree on the node (printed only)")
    su.add_argument("--yes-print-only", action="store_true",
                    help="show every change and command; write and ask nothing")
    su.set_defaults(fn=_setup)
    ag = sub.add_parser("agent", help="load the bridge and harness keys into the ssh-agent")
    ag.add_argument("--node")
    ag.set_defaults(fn=_agent)
    dr = sub.add_parser("doctor", help="check the hub side (and the node, unless --offline)")
    dr.add_argument("--node")
    dr.add_argument("--offline", action="store_true", help="no SSH connection")
    dr.set_defaults(fn=_doctor)
    sv_ = sub.add_parser("service", help="systemd user units for unattended sync and the hub page")
    sva = sv_.add_subparsers(dest="action", required=True)
    svi = sva.add_parser("install", help="write the three unit files after a y; prints systemctl commands")
    svi.add_argument("--interval", type=int, default=300, metavar="SECONDS")
    svi.add_argument("--port", type=int, default=8767)
    svi.add_argument("--print", action="store_true", help="show the units, write nothing")
    sva.add_parser("status", help="state of the three units and lingering")
    sv_.set_defaults(fn=_service)
    a = sub.add_parser("approve")
    a.add_argument("job_id")
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
    g = sub.add_parser("git-status", help="git state of the node's research tree and installed code")
    g.add_argument("--node")
    g.set_defaults(fn=_git_status)
    sy = sub.add_parser("sync", help="poll + board refresh + git state in one pass (no approvals)")
    sy.add_argument("--node")
    sy.add_argument("--watch", type=int, default=0, metavar="SECONDS", help="repeat (min 30)")
    sy.set_defaults(fn=_sync)
    sh = sub.add_parser("share", help="shared status page snapshot (no node contact)")
    ss = sh.add_subparsers(dest="action", required=True)
    sb = ss.add_parser("build", help="write snapshot.json and index.html from the local caches")
    sb.add_argument("--days", type=int, default=7)
    sb.add_argument("--tier", choices=["shared", "owner"], default="shared")
    sv = ss.add_parser("serve", help="serve the shared directory read-only")
    sv.add_argument("--port", type=int, default=8766)
    sv.add_argument("--bind", default="127.0.0.1")
    sh.set_defaults(fn=_share)
    c = sub.add_parser("config", help="write and check host.json and private/local.json")
    cs = c.add_subparsers(dest="action", required=True)
    cs.add_parser("path", help="print where the config files are")
    ci = cs.add_parser("init", help="create host.json (mode 600)")
    ci.add_argument("--data-root", default="", help="hub data directory (default %s)"
                    % default_root())
    ci.add_argument("--force", action="store_true", help="overwrite an existing host.json")
    ca = cs.add_parser("add-node", help="register a node and its SSH aliases")
    ca.add_argument("name")
    ca.add_argument("--alias", default="", help="SSH alias for the bridge key (default rb-<name>)")
    ca.add_argument("--harness-alias", default="",
                    help="SSH alias for the harness key (default rb-<name>-harness)")
    ca.add_argument("--force", action="store_true", help="replace an existing entry")
    cr = cs.add_parser("remove-node", help="delete a node entry")
    cr.add_argument("name")
    cv = cs.add_parser("set", help="set one value: data_root, withheld_patterns_file, "
                       "board.portfolio|priorities, share.calendar_sessions|calendar_status|runs, nodes.<n>.alias|harness_alias, "
                       "nodes.<n>.board.state|events|kanban")
    cv.add_argument("key")
    cv.add_argument("value")
    cl = cs.add_parser("local", help="write private/local.json (real home paths, gitignored)")
    cl.add_argument("--laptop-home", default="")
    cl.add_argument("--node-home", default="")
    cs.add_parser("show", help="print both files")
    cs.add_parser("mcp", help="print the ~/.claude.json entry for the MCP server")
    cs.add_parser("check", help="list what is missing or would leak; exit 1 if anything")
    c.set_defaults(fn=_config)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
