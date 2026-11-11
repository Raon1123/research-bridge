"""`rb config`: write and check the hub's config files from the command line.

Files: host.json (<data root>/host.json, or RB_HOST_CONFIG; data root in rb_host.config) and private/local.json in the
checkout (gitignored). Every write is refused if git would track the target
(rb_node.configure.git_exposure). ~/.ssh/config and ~/.claude.json are only read, never
written: `rb config mcp` prints the entry for the user to add.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rb_node.configure import ConfigError, read_json, write_json

from . import config

REPO = Path(__file__).resolve().parent.parent
NODE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
NODE_NAME_RULE = "letters, digits, '_' or '-', at most 32 characters, starting with a letter or digit"


def node_name_problem(name: str) -> str:
    """Why `name` cannot be a node name, or ''. `id` is refused: its key file would be
    OpenSSH's default personal key `id_ed25519`."""
    if not isinstance(name, str) or not NODE_NAME.fullmatch(name):
        return "invalid node name %r; use %s" % (name, NODE_NAME_RULE)
    if name == "id":
        return ("node name 'id' is refused: its key file id_ed25519 is OpenSSH's default "
                "personal key; choose another name")
    return ""
TOP_KEYS = ("data_root", "withheld_patterns_file")
BOARD_KEYS = ("portfolio", "priorities")
SHARE_KEYS = ("calendar_sessions", "calendar_status", "runs")
NODE_KEYS = ("alias", "harness_alias")
NODE_BOARD_KEYS = ("state", "events", "kanban")


def host_path() -> Path:
    return config.host_json_path()


def local_path() -> Path:
    return REPO / "private" / "local.json"


def _load(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise ConfigError("no %s; run `rb config init` first" % path)
    return read_json(path)


def init(data_root: str = "", force: bool = False) -> Path:
    path = host_path()
    if path.exists() and not force:
        raise ConfigError("%s exists; use --force to overwrite" % path)
    data: Dict[str, Any] = {"nodes": {}}
    if data_root:
        data["data_root"] = data_root
    write_json(path, data)
    return path


def add_node(name: str, alias: str = "", harness_alias: str = "", force: bool = False) -> Dict:
    problem = node_name_problem(name)
    if problem:
        raise ConfigError(problem)
    path = host_path()
    data = _load(path)
    nodes = data.setdefault("nodes", {})
    if name in nodes and not force:
        raise ConfigError("node %s exists; use --force to replace it" % name)
    entry = {"alias": alias or "rb-" + name, "harness_alias": harness_alias or "rb-%s-harness" % name}
    nodes[name] = entry
    write_json(path, data)
    return entry


def remove_node(name: str) -> None:
    path = host_path()
    data = _load(path)
    if name not in data.get("nodes", {}):
        raise ConfigError("unknown node: %s" % name)
    del data["nodes"][name]
    write_json(path, data)


def set_key(key: str, value: str) -> None:
    """Dotted keys: data_root, withheld_patterns_file, board.<portfolio|priorities>,
    share.<calendar_sessions|calendar_status|runs>, nodes.<name>.<alias|harness_alias>, nodes.<name>.board.<state|events|kanban>."""
    path = host_path()
    data = _load(path)
    parts = key.split(".")
    if len(parts) == 1 and key in TOP_KEYS:
        data[key] = value
    elif len(parts) == 2 and parts[0] == "board" and parts[1] in BOARD_KEYS:
        data.setdefault("board", {})[parts[1]] = value
    elif len(parts) == 2 and parts[0] == "share" and parts[1] in SHARE_KEYS:
        data.setdefault("share", {})[parts[1]] = value
    elif len(parts) >= 3 and parts[0] == "nodes":
        node = data.get("nodes", {}).get(parts[1])
        if node is None:
            raise ConfigError("unknown node %s; add it with `rb config add-node`" % parts[1])
        if len(parts) == 3 and parts[2] in NODE_KEYS:
            node[parts[2]] = value
        elif len(parts) == 4 and parts[2] == "board" and parts[3] in NODE_BOARD_KEYS:
            node.setdefault("board", {})[parts[3]] = value
        else:
            raise ConfigError("unknown key %s" % key)
    else:
        raise ConfigError("unknown key %s; see `rb config set --help`" % key)
    write_json(path, data)


def set_local(laptop_home: str = "", node_home: str = "") -> Path:
    path = local_path()
    data = read_json(path) if path.is_file() else {}
    if laptop_home:
        data["laptop_home"] = laptop_home.replace("\\", "/")
    if node_home:
        data["node_home"] = node_home
    write_json(path, data)
    return path


def mcp_entry() -> Dict[str, Any]:
    root = REPO.as_posix()
    entry: Dict[str, Any] = {"type": "stdio", "command": shutil.which("uv") or "uv",
                             "args": ["run", "--directory", root, "--extra", "host",
                                      "python", "-m", "rb_host.server"]}
    env = {"RB_HOST_CONFIG": str(host_path().absolute())}
    if os.environ.get("RB_HOST_ROOT"):
        env["RB_HOST_ROOT"] = os.environ["RB_HOST_ROOT"]
    entry["env"] = env
    return {"research-bridge": entry}


def mcp_command() -> str:
    """The command the user runs to register the MCP server (rb never edits ~/.claude.json)."""
    entry = mcp_entry()["research-bridge"]
    return "claude mcp add-json --scope user research-bridge " + shlex.quote(json.dumps(entry))


def claude_json_path() -> Path:
    return Path.home() / ".claude.json"


def _read_obj(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def registered_entry(checkout: Path) -> Optional[Dict[str, Any]]:
    """The `research-bridge` MCP entry, read only: ~/.claude.json (user scope, then the
    checkout's project scope), then <checkout>/.mcp.json."""
    cj = _read_obj(claude_json_path())
    projects = cj.get("projects") if isinstance(cj.get("projects"), dict) else {}
    proj = projects.get(str(checkout)) if isinstance(projects.get(str(checkout)), dict) else {}
    for holder in (cj, proj, _read_obj(Path(checkout) / ".mcp.json")):
        servers = holder.get("mcpServers")
        if isinstance(servers, dict) and isinstance(servers.get("research-bridge"), dict):
            return servers["research-bridge"]
    return None


def mcp_registered(checkout: Path) -> Tuple[bool, str]:
    """(found, problem); problem is "", "missing path", "worktree", "from_worktree" or "differs".

    "from_worktree": this rb runs from a git worktree and the entry is the one a main checkout
    would print (only the --directory value differs). A warning, not a difference.
    """
    entry = registered_entry(checkout)
    if entry is None:
        return False, ""
    cmd = entry.get("command")
    if not isinstance(cmd, str) or not cmd or not (
            Path(cmd).exists() if os.path.isabs(cmd) else shutil.which(cmd)):
        return True, "missing path"
    args = entry.get("args") if isinstance(entry.get("args"), list) else []
    if "--directory" in args and args.index("--directory") + 1 < len(args):
        directory = str(args[args.index("--directory") + 1])
        if "/.claude/worktrees/" in directory.replace("\\", "/") + "/":
            return True, "worktree"
        if not Path(directory).is_dir():
            return True, "missing path"
    want = mcp_entry()["research-bridge"]
    got_env = entry.get("env") if isinstance(entry.get("env"), dict) else {}
    in_worktree = "/.claude/worktrees/" in REPO.as_posix() + "/"
    if in_worktree and "--directory" in args and "--directory" in want["args"]:
        want_args = list(want["args"])
        want_args[want_args.index("--directory") + 1] = args[args.index("--directory") + 1]
        same_but_path = (args == want_args and Path(cmd).name == Path(want["command"]).name
                         and all(got_env.get(k) == v for k, v in want["env"].items())
                         and not ("RB_HOST_ROOT" in got_env and "RB_HOST_ROOT" not in want["env"]))
        if same_but_path:
            return True, "from_worktree"
    if (args != want["args"]
            or Path(cmd).name != Path(want["command"]).name
            or any(got_env.get(k) != v for k, v in want["env"].items())
            or ("RB_HOST_ROOT" in got_env and "RB_HOST_ROOT" not in want["env"])):
        return True, "differs"
    return True, ""


def registered_where(entry: Dict[str, Any]) -> str:
    """What a registered entry runs: its --directory value, else its command (for messages)."""
    args = entry.get("args") if isinstance(entry.get("args"), list) else []
    if "--directory" in args and args.index("--directory") + 1 < len(args):
        return str(args[args.index("--directory") + 1])
    return str(entry.get("command", ""))


def entry_differences(entry: Dict[str, Any]) -> List[str]:
    """The parts of a registered entry that differ from the one rb setup prints:
    "command", "args", "env <KEY>" (a missing or wrong RB_HOST_* value, or a stray RB_HOST_ROOT)."""
    want = mcp_entry()["research-bridge"]
    cmd = entry.get("command")
    args = entry.get("args") if isinstance(entry.get("args"), list) else []
    env = entry.get("env") if isinstance(entry.get("env"), dict) else {}
    out = []
    if not isinstance(cmd, str) or Path(cmd).name != Path(want["command"]).name:
        out.append("command")
    if args != want["args"]:
        out.append("args")
    out += ["env " + k for k, v in want["env"].items() if env.get(k) != v]
    if "RB_HOST_ROOT" in env and "RB_HOST_ROOT" not in want["env"]:
        out.append("env RB_HOST_ROOT")
    return out


HOST_SETUP_HINT = "run: rb setup --node NAME --host HOST --user USER"


def host_json_error(exc: Exception) -> str:
    """The one line for a missing or unusable host.json (no traceback); coordinator ruling R9."""
    path = host_path()
    if isinstance(exc, FileNotFoundError):
        return "error: no usable host.json at %s; %s" % (path, HOST_SETUP_HINT)
    if isinstance(exc, config.WrongTypes):
        return "error: no usable host.json at %s (%s); fix or move it, then %s" % (
            path, str(exc).replace("\n", " "), HOST_SETUP_HINT)
    if isinstance(exc, OSError):
        return "error: no usable host.json at %s (cannot be read: %s); %s" % (
            path, (exc.strerror or type(exc).__name__).replace("\n", " "), HOST_SETUP_HINT)
    return ("error: no usable host.json at %s (not valid JSON: %s); fix or move it, then %s"
            % (path, str(exc).replace("\n", " "), HOST_SETUP_HINT))


def host_cfg(quiet: bool = False):
    """host.json as a HostConfig, or None after one error line on stdout (the shared helper of
    every `rb` command). Imports `jobs` here, not at module level, to keep imports acyclic."""
    from . import jobs
    try:
        return jobs.load_cfg()
    except (OSError, ValueError) as exc:
        if not quiet:
            print(host_json_error(exc))
        return None


def check() -> List[str]:
    """Problems, one line each; empty = ready. The offline part of `rb doctor`, non-ok lines."""
    from . import doctor
    return [r.message for r in doctor.offline() if r.level != "ok"]
