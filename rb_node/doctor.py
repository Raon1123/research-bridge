"""Node self-diagnosis. Read only: never creates a directory and never writes an audit record."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from collections import namedtuple
from dataclasses import fields
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import __version__, approval, gitinfo, spawn
from .config import NodeConfig, coerce, config_path, expand_paths
from .jobs import allowed_set
from .withheld import Withheld

Check = namedtuple("Check", "id level message fix")  # level in ("ok", "warn", "fail")

STUCK_NEW_S = 600
CONFIG_PLACEHOLDERS = ("{config}", "{config_dir}", "{config_stem}")  # any one gives the job its config


def _which(name: str) -> Optional[str]:
    return shutil.which(name)


def _run(argv: List[str]) -> Tuple[int, str, str]:
    try:
        r = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def state(cfg: NodeConfig, withheld: Withheld) -> dict:
    """Booleans and counts for `hello` (design section 6.5). No path or pattern text."""
    try:
        verifier = (approval._load(Path(cfg.approval_path)) is not None
                    and not approval.path_inside_roots(cfg))
    except Exception:  # unreadable path of any kind: report False, never raise
        verifier = False
    claude = cfg.claude_bin
    return {
        "configured": True,
        "approval_verifier": verifier,
        "job_template_set": bool(cfg.job_template)
        and any(p in str(a) for a in cfg.job_template for p in CONFIG_PLACEHOLDERS),
        "allowed_gpus_set": bool(allowed_set(cfg.allowed_gpus)),
        "withheld_source_set": bool(withheld.source_set),
        "withheld_loaded": withheld.extra_count,
        "withheld_rejected": withheld.rejected_count,
        "harness_root_set": bool(cfg.harness_root),
        "claude_bin_found": bool(claude) and os.path.isfile(claude) and os.access(claude, os.X_OK),
        "queue_dir_exists": os.path.isdir(cfg.queue_dir),
        "python": "%d.%d.%d" % sys.version_info[:3],
    }


def _ok(cid: str, message: str) -> Check:
    return Check(cid, "ok", message, "")


# -- config checks (rows marked C in the design) ------------------------------------------------
def _coerce(data: dict) -> Tuple[NodeConfig, List[str]]:
    """NodeConfig from node.json data; values of the wrong type are dropped and named
    (the same rule as load_config, config.coerce)."""
    kept, wrong = coerce(data)
    return NodeConfig(**expand_paths(kept)), wrong


def _abs(root: str, p: str) -> Path:
    return Path(p) if os.path.isabs(p) else Path(root) / p


def _inside(p: Path, root: Path) -> bool:
    try:
        Path(os.path.normpath(str(p))).relative_to(os.path.normpath(str(root)))
        return True
    except ValueError:
        return False


def config_checks(data: Optional[dict], path: Optional[Path] = None) -> List[Check]:
    shown = str(path) if path is not None else "node.json"
    fix_init = "rb-node config init (or rerun scripts/node-install.sh)"
    if data is None:
        return [Check("config", "fail", "no node.json at %s" % shown, fix_init)]
    if not isinstance(data, dict):
        return [Check("config", "fail", "%s is not a JSON object" % shown, fix_init)]
    cfg, wrong = _coerce(data)
    out = [_ok("config", "%s is a JSON object" % shown)]
    known = {f.name for f in fields(NodeConfig)}
    bad = ["unknown key %r is ignored" % k for k in data
           if k not in known and not str(k).startswith("_")]
    bad += ["key %r has the wrong type and is ignored" % k for k in wrong]
    out.append(Check("config_keys", "warn", "; ".join(bad), "rb-node config show") if bad
               else _ok("config_keys", "no unknown keys"))
    trm = Path(cfg.trm_root)
    if trm.is_dir():
        out.append(_ok("research_root", "research root exists"))
    else:
        out.append(Check("research_root", "fail", "research root does not exist: %s" % trm,
                         "rb-node config set trm_root DIR"))
    mb = Path(cfg.mailbox_root)
    missing = [_abs(cfg.trm_root, r) for r in cfg.read_roots
               if not _inside(_abs(cfg.trm_root, r), mb) and not _abs(cfg.trm_root, r).is_dir()]
    if missing:
        out.append(Check("read_roots", "warn", "read root does not exist: %s" % missing[0],
                         "mkdir -p %s or rb-node config set read_roots '[...]'" % missing[0]))
    else:
        out.append(_ok("read_roots", "read roots exist"))
    roots = [_abs(cfg.trm_root, r) for r in cfg.read_roots]
    outside = [k for k in ("experiments_dir", "hypotheses_path")
               if not any(_inside(_abs(cfg.trm_root, getattr(cfg, k)), r) for r in roots)]
    if outside:
        out.append(Check("doc_paths", "warn",
                         "%s is outside the read roots: read_doc by id is denied" % outside[0],
                         "rb-node config set %s PATH" % outside[0]))
    else:
        out.append(_ok("doc_paths", "experiment and hypothesis paths are readable"))
    q = Path(cfg.queue_dir)
    jobs = q / "jobs"
    if jobs.is_dir():
        qok = os.access(str(jobs), os.W_OK)
    else:
        qok = q.is_dir() and os.access(str(q), os.W_OK)
    if qok:
        out.append(_ok("queue_dir", "queue directory is usable"))
    else:
        out.append(Check("queue_dir", "warn",
                         "queue directory missing: jobs would be written where no runner watches",
                         "mkdir -p %s or rb-node config set queue_dir DIR" % jobs))
    out.append(_withheld_check(cfg))
    out.extend(_approval_checks(cfg))
    tpl = cfg.job_template
    if not tpl:
        out.append(Check("job_template", "warn",
                         "job_template is empty: job_submit is refused (no_job_template)",
                         "rb-node config set job_template "
                         "'[\"uv\",\"run\",\"train.py\",\"--config\",\"{config}\"]'"))
    elif not any(p in a for a in tpl for p in CONFIG_PLACEHOLDERS):
        out.append(Check("job_template", "fail",
                         "job_template has no {config}, {config_dir} or {config_stem} placeholder",
                         "rb-node config set job_template "
                         "'[\"uv\",\"run\",\"train.py\",\"--config\",\"{config}\"]'"))
    else:
        out.append(_ok("job_template",
                       "job_template has a {config}, {config_dir} or {config_stem} placeholder"))
    if allowed_set(cfg.allowed_gpus):
        out.append(_ok("allowed_gpus", "allowed_gpus lists %d GPU(s)" % len(allowed_set(cfg.allowed_gpus))))
    else:
        out.append(Check("allowed_gpus", "warn",
                         "allowed_gpus is empty: job_submit is refused (no_allowed_gpus)",
                         "rb-node config set allowed_gpus '[4, 5, 6, 7]' (your own GPU indices)"))
    cb = cfg.claude_bin
    if os.path.isfile(cb) and os.access(cb, os.X_OK):
        out.append(_ok("claude_bin", "claude is executable"))
    else:
        out.append(Check("claude_bin", "warn", "claude not found: the responder cannot start",
                         "rb-node config set claude_bin PATH"))
    return out


def _withheld_check(cfg: NodeConfig) -> Check:
    fix = "scripts/node-install.sh --withheld-file FILE or rb-node config set withheld_source PATH"
    if not cfg.withheld_source:
        return Check("withheld", "warn", "no pattern file: five fallback patterns only", fix)
    src = Path(cfg.withheld_source)
    w = Withheld.load(src)
    if w.source_error == "unreadable":
        msg = ("withheld pattern file not found" if not src.exists()
               else "withheld pattern file is unreadable")
        return Check("withheld", "fail", msg, fix)
    if w.source_error:
        return Check("withheld", "fail", "withheld pattern file is not valid JSON", fix)
    if w.rejected_count:
        idx = ", ".join(str(i) for i in w.rejected_indexes)
        return Check("withheld", "fail",
                     "%d pattern(s) do not compile (positions in the flattened string list: %s)"
                     % (w.rejected_count, idx), fix)
    if w.extra_count == 0:
        return Check("withheld", "fail", "withheld pattern file has no pattern", fix)
    return _ok("withheld", "%d pattern(s) loaded besides the fallback" % w.extra_count)


def _approval_checks(cfg: NodeConfig) -> List[Check]:
    ap = Path(cfg.approval_path)
    out = []
    if approval._load(ap) is not None:
        out.append(_ok("approval", "approval verifier present"))
    elif ap.exists():
        out.append(Check("approval", "fail", "approval verifier unreadable", "rb-node approve-key set"))
    else:
        out.append(Check("approval", "fail",
                         "approval verifier missing: job_submit and job_cancel are refused",
                         "rb-node approve-key set"))
    # the rule hello and job_submit use: read, write and mailbox roots, symlinks resolved
    inside = approval.root_holding_path(cfg)
    if inside is None:
        out.append(_ok("approval_path",
                       "approval_path is outside every read, write and mailbox root"))
    else:
        out.append(Check("approval_path", "fail",
                         "approval_path is inside a read/write or mailbox root: %s" % inside,
                         "rb-node config set approval_path ~/.research-bridge/approve.json"))
    return out


# -- authorized_keys ----------------------------------------------------------------------------
def authorized_keys_path() -> Path:
    return Path(os.path.expanduser("~")) / ".ssh" / "authorized_keys"


def _split_outside_quotes(text: str, seps: str) -> List[str]:
    parts, cur, quoted, i = [], [], False, 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and quoted and i + 1 < len(text):
            cur.append(text[i:i + 2])
            i += 2
            continue
        if ch == '"':
            quoted = not quoted
        if ch in seps and not quoted:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    parts.append("".join(cur))
    return parts


_KEYTYPES = ("ssh-", "ecdsa-", "sk-")


def parse_authorized_keys(text: str) -> List[dict]:
    """Per non-comment line: lineno, options (name -> unquoted value, "" for flags), keytype, blob.
    The key comment is dropped on purpose."""
    out = []
    for no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        tokens = [t for t in _split_outside_quotes(line, " \t") if t]
        if tokens and not tokens[0].startswith(_KEYTYPES):
            optstr, rest = tokens[0], tokens[1:]
        else:
            optstr, rest = "", tokens
        if len(rest) < 2:
            continue
        options = {}  # type: Dict[str, str]
        for item in _split_outside_quotes(optstr, ",") if optstr else []:
            name, eq, val = item.partition("=")
            if eq and len(val) >= 2 and val[0] == '"' and val[-1] == '"':
                val = val[1:-1].replace('\\"', '"')
            options[name] = val if eq else ""
        out.append({"lineno": no, "options": options, "keytype": rest[0], "blob": rest[1]})
    return out


def _forced(entry: dict, verb: str) -> Optional[str]:
    """The command path when this line's forced command is `<path> <verb>`, else None."""
    cmd = entry["options"].get("command")
    if not cmd:
        return None
    words = cmd.split()
    return words[0] if len(words) == 2 and words[1] == verb else None


def _ak_check(cid: str, level: str, entries: List[dict], verb: str, suffix: str,
              fix: str) -> Check:
    lines = [(e, _forced(e, verb)) for e in entries]
    lines = [(e, p) for e, p in lines if p is not None]
    if not lines:
        return Check(cid, level, "no %s line%s" % (verb, suffix), fix)
    first = ""
    for e, p in lines:
        n = e["lineno"]
        if "restrict" not in e["options"]:
            problem = "%s line %d lacks restrict" % (verb, n)
        elif not e["options"].get("from"):
            problem = "%s line %d lacks from=" % (verb, n)
        elif not os.path.isabs(p) or not (os.path.isfile(p) and os.access(p, os.X_OK)):
            problem = "%s line %d command path is not absolute or missing" % (verb, n)
        else:
            return _ok(cid, "%s line %d is restricted" % (verb, n))
        first = first or problem
    return Check(cid, level, first + suffix, fix)


def _ak_checks() -> List[Check]:
    try:
        text = authorized_keys_path().read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    entries = parse_authorized_keys(text)
    fix = "scripts/node-install.sh --hub-key '...' --hub-from ADDR --apply-authorized-keys"
    # node-install.sh skips the authorized_keys step without --hub-key, so the harness hint carries both
    hfix = fix.replace("--hub-from", "--harness-key '...' --hub-from")
    out = [_ak_check("ak_bridge", "fail", entries, "serve-remote", "", fix),
           _ak_check("ak_harness", "warn", entries, "harness-receive", " (harness channel only)",
                     hfix)]
    dup = None
    dup_harness = False
    dup_serve = False
    for e in entries:
        if _forced(e, "serve-remote") is None:
            continue
        for other in entries:
            if other is not e and other["blob"] == e["blob"]:
                dup = other["lineno"]
                dup_harness = _forced(other, "harness-receive") is not None
                dup_serve = _forced(other, "serve-remote") is not None
                break
        if dup:
            break
    if dup:
        if dup_harness:
            msg = ("the serve-remote key is also the harness key on line %d (AGENTS.md hard rule 9)"
                   % dup)
        elif dup_serve:
            msg = ("line %d also holds this key (a second serve-remote line): remove it by hand"
                   % dup)
        else:
            msg = "the serve-remote key also appears on line %d without the forced command" % dup
        out.append(Check("ak_duplicate", "fail", msg,
                         "remove line %d from ~/.ssh/authorized_keys" % dup))
    else:
        out.append(_ok("ak_duplicate", "the bridge key appears only on its forced-command line"))
    return out


# -- system checks ------------------------------------------------------------------------------
def _age_of(rec_path: Path, rec: dict) -> float:
    try:
        stamp = rec.get("received")
        if isinstance(stamp, str):
            return time.time() - time.mktime(time.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, OverflowError):
        pass
    try:
        return time.time() - rec_path.stat().st_mtime
    except OSError:
        return 0.0


def _fmt_age(s: float) -> str:
    return "%d min" % (s // 60) if s >= 120 else "%d s" % s


def _lock_checks(cfg: NodeConfig) -> Tuple[Check, bool]:
    """The responder_lock check, and whether a live lock is held."""
    lock = Path(cfg.mailbox_root) / "state" / "responder.lock"
    fix = "rm %s" % lock
    try:
        age = time.time() - lock.stat().st_mtime
    except OSError:
        return _ok("responder_lock", "no responder lock"), False
    if spawn._lock_holder_dead(lock):
        return Check("responder_lock", "warn", "stale responder lock (pid not running)", fix), False
    if age > spawn._lock_stale():
        return Check("responder_lock", "warn", "responder lock older than %d s" % age, fix), False
    return _ok("responder_lock", "a responder holds the lock"), True


def _stuck_check(cfg: NodeConfig, held: bool) -> Check:
    inbox = Path(cfg.mailbox_root) / "in"
    new, stuck = [], []
    try:
        dirs = sorted(d for d in inbox.iterdir() if d.is_dir())
    except OSError:
        dirs = []
    for d in dirs:
        mp = d / "message.json"
        try:
            rec = json.loads(mp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict) or d.name.startswith("job-"):
            continue
        age = _age_of(mp, rec)
        if rec.get("status") == "new" and not held and age > STUCK_NEW_S:
            new.append((age, d.name))
        elif rec.get("status") == "responding" and age > spawn._lock_stale():
            stuck.append((age, d.name))
    msgs, fixes = [], []
    if new:
        oldest = max(new)
        msgs.append("%d message(s) waiting since %s" % (len(new), _fmt_age(oldest[0])))
        fixes.append("rb-node respond %s" % oldest[1])
    if stuck:
        oldest = max(stuck)
        msgs.append("%d message(s) stuck in responding" % len(stuck))
        fixes.append("tail %s/state/respond-%s.log" % (cfg.mailbox_root, oldest[1]))
    if msgs:
        return Check("stuck_messages", "warn", "; ".join(msgs), "; ".join(fixes))
    return _ok("stuck_messages", "no message is waiting or stuck")


def _wrapper_check() -> Check:
    w = Path(os.path.expanduser("~")) / ".local" / "bin" / "rb-node"
    fix = "scripts/node-install.sh"
    try:
        text = w.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return Check("wrapper", "warn", "no wrapper at ~/.local/bin/rb-node", fix)
    import re
    m = re.search(r"exec\s+(\S+)\s+-m\s+rb_node", text)
    py = m.group(1).strip("\"'") if m else ""
    if not py or not os.path.isabs(py):
        return Check("wrapper", "warn", "wrapper runs python from PATH", fix)
    if not (os.path.isfile(py) and os.access(py, os.X_OK)):
        return Check("wrapper", "warn", "wrapper python missing", fix)
    rc, out, _err = _run([py, "-c", "import sys; print('%d %d' % sys.version_info[:2])"])
    try:
        major, minor = [int(x) for x in out.split()]
    except ValueError:
        major = minor = 0
    if rc != 0 or (major, minor) < (3, 8):
        return Check("wrapper", "warn", "wrapper python does not run or is older than 3.8", fix)
    return _ok("wrapper", "wrapper runs python %d.%d" % (major, minor))


def system_checks(cfg: NodeConfig) -> List[Check]:
    out = []
    if _which("pdftotext"):
        out.append(_ok("pdftotext", "pdftotext found"))
    else:
        out.append(Check("pdftotext", "warn", "pdftotext missing: pdf files are denied",
                         "install poppler-utils"))
    out.extend(_ak_checks())
    mb = Path(cfg.mailbox_root)
    problem = None
    for name in ("in", "out", "state"):
        d = mb / name
        try:
            mode = d.stat().st_mode & 0o777
        except OSError:
            problem = "mailbox directory missing: %s" % name
            break
        if mode != 0o700:
            problem = "mailbox directory %s has mode %o, not 700" % (name, mode)
            break
    out.append(Check("mailbox", "warn", problem, "scripts/node-install.sh (creates them)")
               if problem else _ok("mailbox", "mailbox directories exist with mode 700"))
    lock_check, held = _lock_checks(cfg)
    out.append(lock_check)
    out.append(_stuck_check(cfg, held))
    rec = gitinfo.read_install(mb.parent)
    if rec is None:
        out.append(Check("install", "warn", "no install record", "scripts/node-install.sh"))
    elif rec.get("version") != __version__:
        out.append(Check("install", "warn", "installed record %s differs from running code %s"
                         % (rec.get("version"), __version__), "scripts/node-install.sh"))
    else:
        out.append(_ok("install", "install record matches version %s" % __version__))
    out.append(_wrapper_check())
    return out


def run(path: Optional[Path] = None) -> List[Check]:
    p = Path(path) if path is not None else config_path()
    if not p.is_file():
        return config_checks(None, p)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [Check("config", "fail", "%s is not valid JSON" % p,
                      "rb-node config init --force (or edit the file)")]
    checks = config_checks(data, p)
    if not isinstance(data, dict):
        return checks
    cfg, _wrong = _coerce(data)
    return checks + system_checks(cfg)


def render(checks: List[Check], only_problems: bool) -> str:
    lines = []
    for c in checks:
        if c.level == "ok":
            if not only_problems:
                lines.append("[ok] %s: %s" % (c.id, c.message))
            continue
        lines.append("[%s] %s: %s" % (c.level, c.id, c.message))
        lines.append("      next: %s" % c.fix)
    fails = len([c for c in checks if c.level == "fail"])
    warns = len([c for c in checks if c.level == "warn"])
    if not fails and not warns:
        lines.append("ok")
    else:
        parts = ["%d to fix" % fails] if fails else ["all ok"]
        if warns:
            parts.append("%d warning(s)" % warns)
        lines.append(", ".join(parts))
    return "\n".join(lines)


def exit_code(checks: List[Check]) -> int:
    return 1 if any(c.level == "fail" for c in checks) else 0
