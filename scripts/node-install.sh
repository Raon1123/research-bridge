#!/bin/sh
# Install or update rb_node on THIS machine (the experiment node) from a research-bridge checkout.
# Safe by default: copies code, writes the wrapper, creates node.json, records the git commit that
# was installed. It prints the authorized_keys lines and edits ~/.ssh/authorized_keys only with
# --apply-authorized-keys. See docs/manual/node-setup.md.
set -eu

SRC=$(cd "$(dirname "$0")/.." && pwd)
TRM=""; PUBKEY=""; HARNESS_PUBKEY=""; SUBNET=""; APPLY=0; UPDATE=0; DRY=0
usage() {
  cat <<USAGE
usage: scripts/node-install.sh [--trm-root DIR] [--update] [--dry-run]
         [--hub-pubkey FILE --harness-pubkey FILE --hub-subnet CIDR [--apply-authorized-keys]]
  --trm-root DIR       research tree (sets node.json trm_root; default keeps node.json / ~/project/trm)
  --update             git pull --ff-only in this checkout first (never pushes)
  --hub-pubkey FILE    hub's bridge public key   (for the serve-remote line)
  --harness-pubkey FILE hub's harness public key (for the harness-receive line)
  --hub-subnet CIDR    value for from="..." (the hub's address or subnet)
  --apply-authorized-keys  append the two lines (backup first); without it they are only printed
USAGE
}
while [ $# -gt 0 ]; do
  case "$1" in
    --trm-root) TRM=$2; shift 2;; --update) UPDATE=1; shift;; --dry-run) DRY=1; shift;;
    --hub-pubkey) PUBKEY=$2; shift 2;; --harness-pubkey) HARNESS_PUBKEY=$2; shift 2;;
    --hub-subnet) SUBNET=$2; shift 2;; --apply-authorized-keys) APPLY=1; shift;;
    -h|--help) usage; exit 0;; *) usage >&2; exit 2;;
  esac
done
run() { if [ "$DRY" = 1 ]; then echo "[dry-run] $*"; else "$@"; fi; }

command -v python3 >/dev/null || { echo "python3 not found" >&2; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' \
  || { echo "python3 >= 3.8 required" >&2; exit 1; }
command -v git >/dev/null || { echo "git not found" >&2; exit 1; }
command -v pdftotext >/dev/null || echo "note: pdftotext missing; pdf files will be denied"

if [ "$UPDATE" = 1 ]; then run git -C "$SRC" pull --ff-only; fi

DEST="$HOME/.local/share/research-bridge"
BIN="$HOME/.local/bin"
RB="$HOME/.research-bridge"
run mkdir -p "$DEST" "$BIN" "$RB"
run chmod 700 "$RB"

# Code: replace rb_node/ wholesale so removed modules do not linger. LF endings come from git.
run rm -rf "$DEST/rb_node"
run cp -r "$SRC/rb_node" "$DEST/rb_node"
run find "$DEST/rb_node" -name __pycache__ -prune -exec rm -rf {} +

if [ "$DRY" = 1 ]; then echo "[dry-run] write $BIN/rb-node"; else
  cat > "$BIN/rb-node" <<'WRAP'
#!/bin/sh
PYTHONPATH="$HOME/.local/share/research-bridge" exec python3 -m rb_node.cli "$@"
WRAP
  chmod 755 "$BIN/rb-node"
fi
RBN="$BIN/rb-node"

if [ "$DRY" = 0 ]; then
  [ -f "$RB/node.json" ] || "$RBN" config init
  [ -z "$TRM" ] || "$RBN" config set trm_root "$(cd "$TRM" && pwd)"
  CL=$(command -v claude || true)
  [ -z "$CL" ] || "$RBN" config set claude_bin "$CL"
  "$RBN" install-record "$SRC"       # git commit/branch/dirty of what was installed
fi

# authorized_keys lines (forced commands, restrict, from=)
if [ -n "$PUBKEY" ] && [ -n "$HARNESS_PUBKEY" ] && [ -n "$SUBNET" ]; then
  k1=$(cut -d' ' -f1,2 "$PUBKEY"); k2=$(cut -d' ' -f1,2 "$HARNESS_PUBKEY")
  L1="restrict,from=\"$SUBNET\",command=\"$BIN/rb-node serve-remote\" $k1 research-bridge-hub"
  L2="restrict,from=\"$SUBNET\",command=\"$BIN/rb-node harness-receive\" $k2 research-bridge-harness"
  echo "--- authorized_keys lines ---"; echo "$L1"; echo "$L2"
  if [ "$APPLY" = 1 ] && [ "$DRY" = 0 ]; then
    AK="$HOME/.ssh/authorized_keys"; mkdir -p "$HOME/.ssh"; chmod 700 "$HOME/.ssh"; touch "$AK"
    cp "$AK" "$AK.bak.$(date +%Y%m%d%H%M%S)"
    for L in "$L1" "$L2"; do grep -qxF "$L" "$AK" || echo "$L" >> "$AK"; done
    chmod 600 "$AK"; echo "appended to $AK (backup kept)"
  fi
else
  echo "authorized_keys: give --hub-pubkey, --harness-pubkey and --hub-subnet to print the lines"
fi

if [ "$DRY" = 0 ]; then
  echo "--- node.json check ---"; "$RBN" config check || true
  echo "--- git state ---"; "$RBN" git-status
fi
echo "Next (you, on this console): rb-node approve-key set"
