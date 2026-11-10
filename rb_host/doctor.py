"""`rb doctor`: ordered hub checks with one next command each (design 6.3).

offline() reads local files and runs local commands only (ssh -G, ssh-add -l, ssh-keygen, systemctl).
online() opens one connection and sends `hello`. Output never carries key material or pattern text.
"""
from __future__ import annotations

import json
import os
import shlex
import stat
import time
from collections import namedtuple
from pathlib import Path
from typing import Any, Dict, List, Optional

import rb_node
from rb_node.configure import ConfigError, git_exposure, read_json
from rb_node.withheld import FALLBACK_PATTERNS, Withheld

from . import configure, service, sshenv, threads
from .client import NodeClient, RemoteError, TransportError, normalize_hello
from .config import HostConfig, load_host_config

Result = namedtuple("Result", "id level message next node")

SETUP = "rb setup --node NAME --host HOST --user USER [--port PORT]"
OLD_DOCTOR = "on the node: scripts/node-install.sh --update, then rb-node doctor"
OLD_UNKNOWN = "unknown (node code predates protocol 2)"


def _ok(id_: str, message: str, node: str = "") -> Result:
    return Result(id_, "ok", message, "", node)


def _bad(id_: str, level: str, message: str, nxt: str, node: str = "") -> Result:
    return Result(id_, level, message, nxt, node)


def _aliases(cfg: HostConfig, name: str):
    entry = cfg.nodes.get(name)
    entry = entry if isinstance(entry, dict) else {}
    alias = entry.get("alias") if isinstance(entry.get("alias"), str) else ""
    harness = entry.get("harness_alias") if isinstance(entry.get("harness_alias"), str) \
        else "rb-%s-harness" % name
    return alias, harness


def _load_cfg() -> HostConfig:
    return load_host_config(configure.host_path())


# ---------------------------------------------------------------- offline

def _key_for(cfg: Dict[str, List[str]], alias: str, node: str, harness: bool) -> Optional[Path]:
    names = sshenv.key_names(node)
    return sshenv.pick_identity(cfg.get("identityfile") or [], [names[1] if harness else names[0]])


def _key_file_result(id_: str, level: str, alias: str, cfg: Dict[str, List[str]], name: str,
                     harness: bool) -> Result:
    tail = " (harness channel only)" if harness else ""
    key = _key_for(cfg, alias, name, harness)
    if key is None:
        return _bad(id_, level, "no bridge IdentityFile configured for %s%s" % (alias, tail),
                    "rb setup --node %s" % name, name)
    if not key.is_file():
        return _bad(id_, level, "key file missing: %s%s" % (key, tail),
                    "rb setup --node %s" % name, name)
    mode = stat.S_IMODE(key.stat().st_mode)
    if mode & 0o077:
        return _bad(id_, level, "key file mode is %04o%s" % (mode, tail), "chmod 600 %s" % key, name)
    pub = Path(str(key) + ".pub")
    if not pub.is_file():
        return _bad(id_, level, "public key missing: %s%s" % (pub, tail),
                    "ssh-keygen -y -f %s > %s" % (key, pub), name)
    return _ok(id_, "key file %s" % key, name)


def _withheld_hub(path: Path) -> Result:
    nxt = "copy the session-calendar pattern file to %s" % path
    if not path.is_file():
        return _bad("withheld_hub", "fail",
                    "withheld_patterns_file does not exist: %s (the hub re-check falls back to the "
                    "five built-in patterns only)" % path, nxt)
    w = Withheld.load(path)
    if w.source_error:
        return _bad("withheld_hub", "fail", "hub withheld pattern file %s is not valid JSON" % path, nxt)
    extra = w.patterns[len(FALLBACK_PATTERNS):]
    if not extra:
        return _bad("withheld_hub", "fail", "hub withheld pattern file %s has no pattern" % path, nxt)
    if w.rejected_count:
        return _bad("withheld_hub", "fail", "%d pattern(s) do not compile (indexes %s)"
                    % (w.rejected_count, ", ".join(str(i) for i in w.rejected_indexes)), nxt)
    return _ok("withheld_hub", "%d hub pattern(s) compile" % len(extra))


def _unit_state(name: str):
    """(installed, rc_active, text) for one unit."""
    installed = (service.unit_dir() / name).is_file()
    rc, out = sshenv.systemctl_user("is-active", name)
    return installed, rc, out


def _service_results() -> List[Result]:
    res = []  # type: List[Result]
    timer_in, t_rc, _ = _unit_state("rb-sync.timer")
    web_in, w_rc, _ = _unit_state("rb-web.service")
    if t_rc == 127 or w_rc == 127:
        res.append(_bad("service_sync", "warn", "systemd user manager not available", "rb service install"))
        res.append(_bad("service_web", "warn", "systemd user manager not available", "rb service install"))
        return res
    if not timer_in:
        res.append(_bad("service_sync", "warn", "unattended sync not installed", "rb service install"))
    else:
        enabled = sshenv.systemctl_user("is-enabled", "rb-sync.timer")[0] == 0
        if enabled and t_rc == 0:
            res.append(_ok("service_sync", "rb-sync.timer is enabled and active"))
        else:
            res.append(_bad("service_sync", "warn", "rb-sync.timer is not active",
                            "systemctl --user enable --now rb-sync.timer"))
    if not web_in:
        res.append(_bad("service_web", "warn", "hub page service not installed", "rb service install"))
    elif w_rc == 0:
        res.append(_ok("service_web", "rb-web.service is active"))
    else:
        res.append(_bad("service_web", "warn", "rb-web.service is not active",
                        "systemctl --user enable --now rb-web.service"))
    if timer_in or web_in:
        user = sshenv.user_name()
        if sshenv.linger(user) is True:
            res.append(_ok("linger", "linger is on"))
        else:
            res.append(_bad("linger", "warn", "user units stop at logout (linger off)",
                            "loginctl enable-linger %s" % user))
    return res


def _age(seconds: float) -> str:
    s = int(max(0, seconds))
    if s < 120:
        return "%d s" % s
    if s < 7200:
        return "%d min" % (s // 60)
    if s < 172800:
        return "%d h" % (s // 3600)
    return "%d days" % (s // 86400)


STALE_SECONDS = threads.STALE_AFTER_S  # sync design 6.8: one rule for the page, `nodes` and the doctor


def _sync_status(cfg: HostConfig, name: str) -> Optional[Result]:
    """One staleness rule with `nodes` and the page: threads.read_status / threads.summary."""
    if not (Path(cfg.data_root) / "sync" / ("%s.json" % name)).is_file():
        return None
    nxt = "rb sync --node %s" % name
    data = threads.read_status(cfg, name)
    if data is None:
        return _bad("sync_status", "warn", "sync status file unreadable", nxt, name)
    s = threads.summary(cfg, name)
    err = s["error"] if isinstance(s.get("error"), str) and s["error"] else None
    if s.get("stage") == "running":
        att = threads._age_s(s.get("last_attempt_at"))
        if att is None or att > STALE_SECONDS:
            return _bad("sync_status", "warn",
                        "a sync pass started at an unknown time and never finished" if att is None
                        else "a sync pass started %s ago and never finished" % _age(att), nxt, name)
    if not s["stale"]:
        return _ok("sync_status", "last successful sync %s ago" % _age(s["age_s"]), name)
    when = "no successful sync yet" if s["age_s"] is None else \
        "last successful sync %s ago" % _age(s["age_s"])
    return _bad("sync_status", "warn", "%s (error: %s)" % (when, err or "none"), nxt, name)


def offline(node: Optional[str] = None) -> List[Result]:
    res = []  # type: List[Result]
    hp = configure.host_path()
    cfg = None  # type: Optional[HostConfig]
    if not hp.is_file():
        res.append(_bad("host_json", "fail", "no host.json at %s" % hp, SETUP))
    else:
        try:
            read_json(hp)
            cfg = _load_cfg()
            res.append(_ok("host_json", str(hp)))
        except (ConfigError, ValueError, TypeError, OSError) as exc:
            msg = str(exc)
            if "not valid JSON" not in msg:
                msg = "%s is not valid JSON (%s)" % (hp, msg)
            res.append(_bad("host_json", "fail", msg, "fix or move the file, then rb setup --node NAME "
                                                      "--host HOST --user USER [--port PORT]"))
    leaks = [git_exposure(p) for p in (hp, configure.local_path()) if p.exists()]
    leaks = [x for x in leaks if x]
    if leaks:
        res.append(_bad("host_json_git", "fail", "LEAK RISK: " + "; ".join(leaks),
                        "add the file to .gitignore or move it"))
    else:
        res.append(_ok("host_json_git", "config files are not tracked by git"))
    if cfg is None:
        return res
    if cfg.nodes is None:
        cfg.nodes = {}
    bad = []
    if not isinstance(cfg.nodes, dict) or not all(isinstance(v, dict) for v in cfg.nodes.values()):
        bad.append("nodes must be an object whose values are objects")
    for key in ("data_root", "withheld_patterns_file"):
        if not isinstance(getattr(cfg, key), str):
            bad.append("%s must be a string" % key)
    if bad:
        res.append(_bad("host_json", "fail", "host.json has wrong types: " + "; ".join(bad),
                        "fix %s, then rb doctor" % hp))
        return res

    if Path(cfg.data_root).is_dir():
        mode = stat.S_IMODE(os.stat(cfg.data_root).st_mode) if os.name != "nt" else 0o700
        if mode & 0o077:
            res.append(_bad("data_root", "fail",
                            "data root %s has mode %o: other accounts can read stored messages "
                            "and attachments" % (cfg.data_root, mode),
                            "chmod 700 %s" % shlex.quote(cfg.data_root)))
        else:
            res.append(_ok("data_root", cfg.data_root))
    else:
        res.append(_bad("data_root", "fail", "data root does not exist: %s" % cfg.data_root, SETUP))
    if cfg.nodes:
        res.append(_ok("nodes", "%d node(s)" % len(cfg.nodes)))
    else:
        res.append(_bad("nodes", "fail", "no node in host.json", SETUP))
    if node and node not in cfg.nodes:
        res.append(_bad("nodes", "fail", "unknown node: %s" % node, SETUP))
        names = []  # type: List[str]
    else:
        names = [node] if node else sorted(cfg.nodes)

    sshcfg = {}  # type: Dict[str, Dict[str, List[str]]]
    defined = {}  # type: Dict[str, bool]
    state = {}  # type: Dict[str, Dict[str, Any]]
    for n in names:
        alias, harness = _aliases(cfg, n)
        state[n] = {"alias": alias, "harness": harness}
        for a in (alias, harness):
            if a and a not in sshcfg:
                sshcfg[a] = sshenv.ssh_config(a)
                host = sshcfg[a].get("hostname")
                defined[a] = bool(host) and host[0].lower() != a.lower()

    for n in names:
        a = state[n]["alias"]
        if not a:
            res.append(_bad("alias", "fail", "node %s has no alias in host.json" % n, SETUP, n))
        elif not sshcfg.get(a):
            res.append(_bad("alias", "fail", "ssh -G failed for %s" % a, SETUP, n))
        elif not defined[a]:
            res.append(_bad("alias", "fail", "ssh has no Host block for %s" % a, SETUP, n))
        else:
            res.append(_ok("alias", a, n))
    for n in names:
        h = state[n]["harness"]
        if not sshcfg.get(h):
            res.append(_bad("alias_harness", "warn", "ssh -G failed for %s (harness channel only)" % h,
                            SETUP, n))
        elif not defined[h]:
            res.append(_bad("alias_harness", "warn",
                            "ssh has no Host block for %s (harness channel only)" % h, SETUP, n))
        else:
            res.append(_ok("alias_harness", h, n))
    for n in names:
        diffs = []  # type: List[str]
        for a in (state[n]["alias"], state[n]["harness"]):
            if not defined.get(a):
                continue
            c = sshcfg[a]
            if (c.get("identitiesonly") or [""])[0].lower() != "yes":
                diffs.append("%s: identitiesonly is %s, expected yes"
                             % (a, (c.get("identitiesonly") or ["unset"])[0]))
            if (c.get("stricthostkeychecking") or [""])[0].lower() not in ("true", "yes"):
                diffs.append("%s: stricthostkeychecking is %s, expected true"
                             % (a, (c.get("stricthostkeychecking") or ["unset"])[0]))
        if diffs:
            res.append(_bad("ssh_options", "warn", "; ".join(diffs), "rb setup --node %s" % n, n))
        else:
            res.append(_ok("ssh_options", "identitiesonly and stricthostkeychecking as expected", n))
    for n in names:
        a = state[n]["alias"]
        if defined.get(a):
            res.append(_key_file_result("key_file", "fail", a, sshcfg[a], n, False))
    for n in names:
        h = state[n]["harness"]
        if defined.get(h):
            res.append(_key_file_result("key_file_harness", "warn", h, sshcfg[h], n, True))

    sshenv.forget()
    sock = sshenv.agent_socket()
    keys = {}  # type: Dict[str, Optional[Path]]
    unenc = {}  # type: Dict[str, bool]
    for n in names:
        for a in (state[n]["alias"], state[n]["harness"]):
            if defined.get(a):
                k = _key_for(sshcfg[a], a, n, a == state[n]["harness"] and a != state[n]["alias"])
                keys[a] = k if k is not None and k.is_file() else None
                unenc[a] = keys[a] is not None and sshenv.key_unencrypted(keys[a])
    if sock is not None:
        res.append(_ok("agent", str(sock)))
    else:
        need = any(keys.get(state[n]["alias"]) is not None and not unenc.get(state[n]["alias"])
                   for n in names)
        res.append(_bad("agent", "fail" if need else "warn", "no ssh-agent reachable", "rb agent"))

    loaded_ok = {}  # type: Dict[str, bool]

    def loaded(n: str, alias: str, id_: str, level: str, harness: bool) -> None:
        tail = " (harness channel only)" if harness else ""
        key = keys.get(alias)
        if key is None or not Path(str(key) + ".pub").is_file():
            return
        nxt = "rb agent --node %s" % n
        if unenc.get(alias):
            res.append(_ok(id_, "key for %s has no passphrase" % alias, n))
            loaded_ok[alias] = True
            return
        asock = sshenv.agent_socket(alias, sshenv.key_names(n))
        fp = sshenv.fingerprint(Path(str(key) + ".pub"))
        if asock is None or fp is None or fp not in sshenv.agent_fingerprints(asock):
            res.append(_bad(id_, level, "key for %s is not in the agent%s" % (alias, tail), nxt, n))
            return
        res.append(_ok(id_, "key for %s is in the agent" % alias, n))
        loaded_ok[alias] = True

    for n in names:
        if defined.get(state[n]["alias"]):
            loaded(n, state[n]["alias"], "key_loaded", "fail", False)
    for n in names:
        if defined.get(state[n]["harness"]):
            loaded(n, state[n]["harness"], "key_loaded_harness", "warn", True)
    for n in names:
        a = state[n]["alias"]
        if not loaded_ok.get(a):
            continue
        key = keys[a]
        fp = sshenv.fingerprint(Path(str(key) + ".pub"))
        if unenc.get(a) or any(fp in sshenv.agent_fingerprints(s) for s in sshenv.load_sockets()):
            res.append(_ok("agent_location", "key for %s is in a runtime-directory agent" % a, n))
        else:
            res.append(_bad("agent_location", "warn",
                            "key for %s is only in an agent outside the runtime directory: "
                            "unattended sync and other shells cannot use it" % a,
                            "rb agent --node %s" % n, n))
    for n in names:
        a = state[n]["alias"]
        if defined.get(a):
            if sshenv.known_host(sshcfg[a]):
                res.append(_ok("known_host", "known_hosts has an entry for %s" % a, n))
            else:
                res.append(_bad("known_host", "fail", "no known_hosts entry for %s" % a,
                                "rb setup --node %s" % n, n))

    res.append(_withheld_hub(Path(cfg.withheld_patterns_file)))

    found, problem = configure.mcp_registered(configure.REPO)
    if found and not problem:
        res.append(_ok("mcp_entry", "MCP server registered"))
    else:
        msg = {"missing path": "MCP entry points at a missing path",
               "worktree": "MCP entry points at a worktree",
               "from_worktree": "this rb runs from a git worktree; the registered MCP entry "
                                "points at another checkout",
               "differs": "MCP entry differs from the one rb setup prints (args or RB_HOST_* env); "
                          "re-register it (a leftover SSH_AUTH_SOCK may stay)"}.get(problem, "MCP server not registered")
        res.append(_bad("mcp_entry", "warn", msg,
                        "run rb from the main checkout" if problem == "from_worktree"
                        else configure.mcp_command()))
    if configure.local_path().is_file():
        res.append(_ok("local_json", str(configure.local_path())))
    else:
        res.append(_bad("local_json", "warn",
                        "no private/local.json (only the harness path mapping needs it)",
                        "rb config local --laptop-home ... --node-home ..."))
    res.extend(_service_results())
    for n in names:
        r = _sync_status(cfg, n)
        if r is not None:
            res.append(r)
    return res


# ---------------------------------------------------------------- online

def _connect(cfg: HostConfig, node: str) -> NodeClient:
    return NodeClient(cfg.alias(node), node=node)


def _unknown(id_: str, protocol: int, key: str, level_known: str, ok_msg: str, bad_msg: str,
             nxt: str, state: Dict[str, Any], node: str) -> Result:
    if protocol < 2:
        return _bad(id_, "warn", OLD_UNKNOWN, nxt if "rb-node doctor" not in nxt else OLD_DOCTOR, node)
    v = state.get(key)
    if v is True:
        return _ok(id_, ok_msg, node)
    if v is False:
        return _bad(id_, level_known, bad_msg, nxt, node)
    return _bad(id_, "warn", "unknown (node did not report %s)" % key, nxt, node)


def online(cfg: HostConfig, node: str) -> List[Result]:
    try:
        with _connect(cfg, node) as c:
            hello = normalize_hello(c.hello())
    except ValueError as exc:
        return [_bad("reachable", "fail", str(exc), SETUP, node)]
    except TransportError as exc:
        return [_bad("reachable", "fail", "%s: %s" % (exc.code, exc.message), exc.hint, node)]
    except RemoteError as exc:
        if exc.code == "not_configured":
            return [_bad("reachable", "fail", "node reachable but not configured",
                         "on the node: rb-node doctor (or rerun scripts/node-install.sh)", node)]
        return [_bad("reachable", "fail", "node answered hello with an error: %s" % exc.code,
                     "on the node: rb-node doctor", node)]
    protocol = hello["protocol"]
    state = hello["state"] or {}
    if protocol == 2 and state.get("configured") is False:
        return [_bad("reachable", "fail", "node reachable but not configured",
                     "on the node: rb-node doctor (or rerun scripts/node-install.sh)", node)]
    res = [_ok("reachable", "node answered hello (version %s, protocol %d)"
               % (hello["version"] or "unknown", protocol), node)]
    update = "on the node: scripts/node-install.sh --update"
    if protocol < 2:
        res.append(_bad("node_version", "warn", "node code %s predates protocol 2"
                        % (hello["version"] or "unknown"), update, node))
    elif hello["version"] != rb_node.__version__:
        res.append(_bad("node_version", "warn", "node runs %s, hub has %s"
                        % (hello["version"], rb_node.__version__), update, node))
    else:
        res.append(_ok("node_version", "node runs %s" % hello["version"], node))

    doc = "on the node: rb-node doctor"
    if protocol < 2:
        extra = hello["withheld_extra"]
        if extra:
            msg = "old node reports %d patterns, counted before compiling; update the node" % extra
        else:
            msg = "node reports 0 extra patterns: pattern file not loaded or not configured"
        res.append(_bad("node_withheld", "warn", msg, OLD_DOCTOR, node))
    else:
        loaded, rejected = state.get("withheld_loaded"), state.get("withheld_rejected")
        if state.get("withheld_source_set") is True:
            if isinstance(rejected, int) and rejected > 0:
                res.append(_bad("node_withheld", "fail", "%d node pattern(s) do not compile" % rejected,
                                doc, node))
            elif loaded == 0:
                res.append(_bad("node_withheld", "fail",
                                "node pattern file did not load or has no pattern", doc, node))
            elif isinstance(loaded, int):
                res.append(_ok("node_withheld", "node loaded %d pattern(s)" % loaded, node))
            else:
                res.append(_bad("node_withheld", "warn", "unknown (node did not report withheld_loaded)",
                                doc, node))
        else:
            res.append(_bad("node_withheld", "warn", "no node pattern file: five fallback patterns only",
                            doc, node))
    approve_level = "fail" if protocol == 2 else "warn"
    res.append(_unknown("node_approval", protocol, "approval_verifier", approve_level,
                        "approval verifier is set", "approval verifier not set on the node",
                        "on the node: rb-node approve-key set", state, node))
    res.append(_unknown("node_job_template", protocol, "job_template_set", "warn",
                        "job_template is set", "job_template not set: jobs are refused",
                        "on the node: rb-node config set job_template '[...,\"{config}\"]'", state, node))
    res.append(_unknown("node_responder", protocol, "claude_bin_found", "warn", "claude found",
                        "claude not found on the node: messages wait for a live session", doc, state, node))
    res.append(_unknown("node_queue", protocol, "queue_dir_exists", "warn", "queue directory exists",
                        "queue directory missing on the node", doc, state, node))
    return res


# ---------------------------------------------------------------- output

def _verdict(fails: int, warns: int) -> str:
    """Closing line of the problems-only report: failures and warnings are counted apart."""
    if not fails and not warns:
        return "ok"
    parts = ["%d to fix" % fails] if fails else ["all ok"]
    if warns:
        parts.append("%d warning(s)" % warns)
    return ", ".join(parts)


def render(results: List[Result], only_problems: bool) -> str:
    shown = [r for r in results if not (only_problems and r.level == "ok")]
    order = [""]
    for r in results:
        if r.node not in order:
            order.append(r.node)
    lines = []  # type: List[str]
    for node in order:
        group = [r for r in shown if r.node == node]
        if not group:
            continue
        if node:
            lines.append("node %s:" % node)
        for r in group:
            prefix = "%s %s  " % (r.level, r.id)
            lines.append(prefix + r.message)
            if r.level != "ok" and r.next:
                lines.append("      next: " + r.next)
    if only_problems:
        lines.append(_verdict(sum(1 for r in results if r.level == "fail"),
                              sum(1 for r in results if r.level == "warn")))
    else:
        lines.append("summary: %d ok, %d warn, %d fail" % tuple(
            sum(1 for r in results if r.level == lv) for lv in ("ok", "warn", "fail")))
    return "\n".join(lines) + "\n"


def exit_code(results: List[Result]) -> int:
    return 1 if any(r.level == "fail" for r in results) else 0


def main(node: Optional[str], offline_only: bool, only_problems: bool = False) -> int:
    results = offline(node)
    if not offline_only and not any(r.id == "host_json" and r.level == "fail" for r in results):
        try:
            cfg = _load_cfg()
        except (OSError, ValueError, TypeError):
            cfg = None
        if cfg is not None and isinstance(cfg.nodes, dict):
            names = [node] if node else sorted(cfg.nodes)
            for n in names:
                if n in cfg.nodes:
                    results.extend(online(cfg, n))
    print(render(results, only_problems), end="")
    return exit_code(results)
