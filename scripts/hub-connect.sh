#!/bin/sh
# Hub side: create the two SSH keys, the ssh config block and the host.json entry for one node.
# Prints by default; ~/.ssh/config is edited only with --apply-ssh-config. Run on the hub.
set -eu
NODE=""; HOST=""; PORT=22; USER_=""; KEYDIR="$HOME/.ssh/research-bridge"; APPLY=0
usage() { echo "usage: scripts/hub-connect.sh --node NAME --host HOST --port PORT --user USER [--keydir DIR] [--apply-ssh-config]"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --node) NODE=$2; shift 2;; --host) HOST=$2; shift 2;; --port) PORT=$2; shift 2;;
    --user) USER_=$2; shift 2;; --keydir) KEYDIR=$2; shift 2;;
    --apply-ssh-config) APPLY=1; shift;; -h|--help) usage; exit 0;; *) usage >&2; exit 2;;
  esac
done
[ -n "$NODE" ] && [ -n "$HOST" ] && [ -n "$USER_" ] || { usage >&2; exit 2; }
REPO=$(cd "$(dirname "$0")/.." && pwd)
RB="uv run --directory $REPO --extra host rb"

mkdir -p "$KEYDIR"; chmod 700 "$KEYDIR"
for kind in "" harness_; do
  f="$KEYDIR/${NODE}_${kind}ed25519"
  [ -f "$f" ] || { echo "generating $f (ssh-keygen asks for a passphrase)"; \
    ssh-keygen -t ed25519 -f "$f" -C "research-bridge-${kind:-hub}"; }
done

BLOCK="Host rb-$NODE
    HostName $HOST
    Port $PORT
    User $USER_
    IdentityFile $KEYDIR/${NODE}_ed25519
    IdentitiesOnly yes
    StrictHostKeyChecking yes

Host rb-$NODE-harness
    HostName $HOST
    Port $PORT
    User $USER_
    IdentityFile $KEYDIR/${NODE}_harness_ed25519
    IdentitiesOnly yes
    StrictHostKeyChecking yes"
CFG="$HOME/.ssh/config"
if [ "$APPLY" = 1 ]; then
  mkdir -p "$HOME/.ssh"; touch "$CFG"
  if grep -q "^Host rb-$NODE\$" "$CFG"; then echo "ssh config already has rb-$NODE; left alone"
  else cp "$CFG" "$CFG.bak.$(date +%Y%m%d%H%M%S)"; printf '\n%s\n' "$BLOCK" >> "$CFG"; chmod 600 "$CFG"; echo "appended to $CFG"; fi
else
  echo "--- add to $CFG (or rerun with --apply-ssh-config) ---"; echo "$BLOCK"
fi

echo "--- host key: verify this fingerprint through a separate channel, then add it ---"
ssh-keyscan -p "$PORT" "$HOST" 2>/dev/null | ssh-keygen -lf - || true
echo "  ssh-keyscan -p $PORT $HOST >> ~/.ssh/known_hosts"

[ -f "$($RB config path | head -1 | awk '{print $2}')" ] || $RB config init
$RB config add-node "$NODE" || echo "(node entry exists; use rb config add-node --force)"

echo "--- give the node (node-install.sh --hub-pubkey / --harness-pubkey) ---"
echo "  $KEYDIR/${NODE}_ed25519.pub   $KEYDIR/${NODE}_harness_ed25519.pub"
echo "--- then verify ---"
echo "  ssh-add $KEYDIR/${NODE}_ed25519 $KEYDIR/${NODE}_harness_ed25519"
echo "  $RB config check && $RB git-status --node $NODE"
