#!/bin/sh
# Hub side: load the bridge keys into a running ssh-agent, once per boot. Run in a terminal.
#
#   scripts/hub-agent.sh [--node NAME] [--persist] [--test]
#
# Nodes come from host.json (rb config path); key files from `ssh -G rb-<node>` and
# `ssh -G rb-<node>-harness`. Agent: the first that answers of $XDG_RUNTIME_DIR/gcr/ssh (desktop),
# $XDG_RUNTIME_DIR/openssh_agent, $XDG_RUNTIME_DIR/rb-ssh-agent, then $SSH_AUTH_SOCK; if none,
# a new ssh-agent bound to $XDG_RUNTIME_DIR/rb-ssh-agent. Keys already in the agent are skipped.
#   --persist  also write SSH_AUTH_SOCK to ~/.bashrc and to the research-bridge entry in
#              ~/.claude.json (backup first; both edits are idempotent)
#   --test     after loading, run `rb git-status --node <node>` (opens one bridge connection)
set -eu
ONLY=""; PERSIST=0; TEST=0
usage() { echo "usage: scripts/hub-agent.sh [--node NAME] [--persist] [--test]"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --node) ONLY=$2; shift 2;; --persist) PERSIST=1; shift;; --test) TEST=1; shift;;
    -h|--help) usage; exit 0;; *) usage >&2; exit 2;;
  esac
done
[ -t 0 ] && [ -t 1 ] || { echo "error: run this in a terminal; ssh-add must ask for passphrases" >&2; exit 1; }
REPO=$(cd "$(dirname "$0")/.." && pwd)
RB="uv run --directory $REPO --extra host rb"
RUN=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}

# ssh-add -l exits 0 (keys), 1 (no keys) or 2 (no agent behind the socket).
alive() { [ -S "$1" ] || return 1; rc=0; SSH_AUTH_SOCK="$1" ssh-add -l >/dev/null 2>&1 || rc=$?; [ "$rc" -ne 2 ]; }
SOCK=""
# Stable per-user sockets first: a login-shell agent ($SSH_AUTH_SOCK under /tmp) dies at logout,
# and --persist would record a path that later points at nothing.
for s in "$RUN/gcr/ssh" "$RUN/openssh_agent" "$RUN/rb-ssh-agent" "${SSH_AUTH_SOCK:-}"; do
  [ -n "$s" ] && alive "$s" && { SOCK=$s; break; }
done
if [ -z "$SOCK" ]; then
  SOCK="$RUN/rb-ssh-agent"; rm -f "$SOCK"
  ssh-agent -a "$SOCK" >/dev/null
  echo "started ssh-agent at $SOCK"
fi
export SSH_AUTH_SOCK="$SOCK"
echo "agent: $SOCK"

HOSTJSON=$($RB config path | awk '/host.json/{print $NF; exit}')
[ -f "$HOSTJSON" ] || { echo "error: no $HOSTJSON; run scripts/hub-connect.sh or rb config init" >&2; exit 1; }
NODES=$(python3 -c 'import json,sys; print(" ".join(sorted(json.load(open(sys.argv[1])).get("nodes",{}))))' "$HOSTJSON")
[ -n "$ONLY" ] && NODES=$ONLY
[ -n "$NODES" ] || { echo "error: no node in $HOSTJSON" >&2; exit 1; }

LOADED=$(ssh-add -l 2>/dev/null | awk '{print $2}' || true)
for n in $NODES; do
  for alias in "rb-$n" "rb-$n-harness"; do
    key=$(ssh -G "$alias" 2>/dev/null | awk '/^identityfile /{print $2; exit}')
    case "$key" in "~/"*) key="$HOME/${key#\~/}";; esac
    case "$key" in */research-bridge/*) ;; *) echo "skip $alias: no research-bridge IdentityFile in ~/.ssh/config"; continue;; esac
    [ -f "$key" ] || { echo "skip $alias: $key missing"; continue; }
    fp=$(ssh-keygen -lf "$key.pub" 2>/dev/null | awk '{print $2}')
    if [ -n "$fp" ] && echo "$LOADED" | grep -qxF "$fp"; then echo "$alias: already loaded"
    else echo "$alias: adding $key"; ssh-add "$key"; fi
  done
done

if [ "$PERSIST" = 1 ]; then
  RC="$HOME/.bashrc"; LINE="export SSH_AUTH_SOCK=$SOCK  # research-bridge hub agent"
  if grep -qF "# research-bridge hub agent" "$RC" 2>/dev/null; then
    grep -qxF "$LINE" "$RC" || { cp "$RC" "$RC.bak.$(date +%Y%m%d%H%M%S)"; \
      sed -i "/# research-bridge hub agent\$/c\\$LINE" "$RC"; echo "updated $RC"; }
  else printf '\n%s\n' "$LINE" >> "$RC"; echo "appended to $RC"; fi
  python3 - "$SOCK" <<'EOF'
import json, os, shutil, sys, time
sock = sys.argv[1]
p = os.path.expanduser("~/.claude.json")
data = json.load(open(p, encoding="utf-8"))
entry = (data.get("mcpServers") or {}).get("research-bridge")
if not isinstance(entry, dict):
    sys.exit("~/.claude.json has no research-bridge MCP entry; add the one from `rb config mcp` first")
if (entry.get("env") or {}).get("SSH_AUTH_SOCK") == sock:
    print("~/.claude.json already has SSH_AUTH_SOCK")
else:
    shutil.copy2(p, p + ".bak." + time.strftime("%Y%m%d%H%M%S"))
    entry.setdefault("env", {})["SSH_AUTH_SOCK"] = sock
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.chmod(tmp, os.stat(p).st_mode & 0o777)
    os.replace(tmp, p)
    print("set SSH_AUTH_SOCK in ~/.claude.json (restart Claude sessions to pick it up)")
EOF
fi

echo "--- agent now holds ---"; ssh-add -l | awk '{print $1, $2, $3}'
if [ "$TEST" = 1 ]; then
  for n in $NODES; do echo "--- rb git-status --node $n ---"; $RB git-status --node "$n" || true; done
else
  echo "connection test (opens one bridge connection): $RB git-status --node <node>"
fi
