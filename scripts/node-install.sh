#!/bin/sh
# Install or update rb_node on THIS machine (the experiment node) from a research-bridge checkout.
# Copies code into a release directory and swaps a symlink, writes the wrapper, creates node.json,
# creates the mailbox directories and records the git commit that was installed. It prints the
# authorized_keys lines and edits ~/.ssh/authorized_keys only with --apply-authorized-keys, on a
# terminal, after a y/N answer. Everything that edits a file or derives a value is in
# `python3 -m rb_node.install` (tested in Python). See docs/manual/node-setup.md.
# Needs GNU coreutils `mv -T` (the node is Linux).
set -eu

SRC=$(cd "$(dirname "$0")/.." && pwd)
ROOT=""; HUBKEY=""; HUBKEYFILE=""; HARNESSKEY=""; HARNESSKEYFILE=""; FROM=""; WFILE=""
APPLY=0; UPDATE=0; DRY=0

usage() {
  cat <<'USAGE'
usage: scripts/node-install.sh [--research-root DIR] [--update] [--dry-run]
         [--hub-key 'ssh-ed25519 AAAA...' | --hub-pubkey FILE]
         [--harness-key '...' | --harness-pubkey FILE] [--hub-from ADDR]
         [--withheld-file FILE] [--apply-authorized-keys]
  --research-root DIR      research tree on this node (alias --trm-root); sets node.json trm_root
                           and the paths derived from it. Without it node.json is kept; with no
                           node.json you are asked once on a terminal, else give this flag.
  --hub-key KEY            hub bridge public key, inline (the serve-remote line)
  --hub-pubkey FILE        the same, from a file
  --harness-key KEY        hub harness public key, inline (the harness-receive line)
  --harness-pubkey FILE    the same, from a file
  --hub-from ADDR          value for from="...": addresses or CIDR ranges, comma-separated
                           (alias --hub-subnet)
  --withheld-file FILE     withheld pattern file (JSON); validated, copied to
                           ~/.research-bridge/withheld-patterns.json, set as withheld_source.
                           Replacing a different file needs a terminal and a y answer.
  --apply-authorized-keys  show the change to ~/.ssh/authorized_keys and apply it after y/N on a
                           terminal (backup first); without a terminal the lines are only printed
  --update                 git pull --ff-only in this checkout first (never pushes)
  --dry-run                print every action, write nothing
  -h, --help               this text
USAGE
}

need() { [ "$1" -ge 2 ] || { usage >&2; exit 2; }; }
while [ $# -gt 0 ]; do
  case "$1" in
    --research-root|--trm-root) need $#; ROOT=$2; shift 2;;
    --hub-key) need $#; HUBKEY=$2; shift 2;;
    --hub-pubkey) need $#; HUBKEYFILE=$2; shift 2;;
    --harness-key) need $#; HARNESSKEY=$2; shift 2;;
    --harness-pubkey) need $#; HARNESSKEYFILE=$2; shift 2;;
    --hub-from|--hub-subnet) need $#; FROM=$2; shift 2;;
    --withheld-file) need $#; WFILE=$2; shift 2;;
    --apply-authorized-keys) APPLY=1; shift;;
    --update) UPDATE=1; shift;;
    --dry-run) DRY=1; shift;;
    -h|--help) usage; exit 0;;
    *) usage >&2; exit 2;;
  esac
done

run() { if [ "$DRY" = 1 ]; then echo "[dry-run] $*"; else "$@"; fi; }
say() { if [ "$DRY" = 1 ]; then echo "[dry-run] $*"; else echo "$*"; fi; }

# -- prerequisites ---------------------------------------------------------------------------
PY=$(command -v python3 || true)
[ -n "$PY" ] || { echo "python3 not found" >&2; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' \
  || { echo "python3 >= 3.8 required" >&2; exit 1; }
case "$PY" in *[!A-Za-z0-9_./+-]*) echo "python3 path has characters the wrapper cannot hold: $PY" >&2; exit 1;; esac
command -v git >/dev/null || { echo "git not found" >&2; exit 1; }
command -v pdftotext >/dev/null || echo "note: pdftotext missing; pdf files will be denied"
command -v claude >/dev/null || echo "note: claude not found on PATH; the responder needs claude_bin"

DEST="$HOME/.local/share/research-bridge"
BIN="$HOME/.local/bin"
RB="$HOME/.research-bridge"
NODEJSON=${RB_NODE_CONFIG:-$RB/node.json}
RBN="$BIN/rb-node"
# A hub keeps host.json and ledger.jsonl in its data root: the default one, or the one named by
# RB_HOST_ROOT; RB_HOST_CONFIG names its host.json directly.
for d in "$DEST" "${RB_HOST_ROOT:-}"; do
  [ -n "$d" ] || continue
  if [ -e "$d/host.json" ] || [ -e "$d/ledger.jsonl" ]; then
    echo "$d holds hub data (host.json or ledger.jsonl); this machine is a hub: not installing a node here" >&2
    exit 1
  fi
done
if [ -n "${RB_HOST_CONFIG:-}" ] && [ -e "$RB_HOST_CONFIG" ]; then
  echo "RB_HOST_CONFIG names an existing hub config ($RB_HOST_CONFIG); this machine is a hub: not installing a node here" >&2
  exit 1
fi
pyinst() { PYTHONPATH="$SRC" "$PY" -m rb_node.install "$@"; }

# Decide the research root before anything is written.
case "$ROOT" in "~"*) ROOT="$HOME${ROOT#"~"}";; esac
if [ -z "$ROOT" ] && [ ! -f "$NODEJSON" ]; then
  if [ -t 0 ] && [ -t 1 ]; then
    printf 'Research tree on this node: '
    read -r ROOT
    case "$ROOT" in "~"*) ROOT="$HOME${ROOT#"~"}";; esac
    [ -n "$ROOT" ] || { echo "give --research-root DIR" >&2; exit 2; }
  else
    echo "no node.json yet: give --research-root DIR" >&2
    exit 2
  fi
fi
if [ -n "$ROOT" ]; then
  [ -d "$ROOT" ] || { echo "research root is not a directory: $ROOT" >&2; exit 2; }
  ROOT=$(cd "$ROOT" && pwd)
fi

# Validate keys and --hub-from before anything is written.
if { [ -n "$HUBKEY" ] || [ -n "$HUBKEYFILE" ]; } && [ -n "$FROM" ]; then
  set -- authorized-keys --hub-from "$FROM" --bindir "$BIN" --check
  [ -z "$HUBKEY" ] || set -- "$@" --hub-key "$HUBKEY"
  [ -z "$HUBKEYFILE" ] || set -- "$@" --hub-pubkey "$HUBKEYFILE"
  [ -z "$HARNESSKEY" ] || set -- "$@" --harness-key "$HARNESSKEY"
  [ -z "$HARNESSKEYFILE" ] || set -- "$@" --harness-pubkey "$HARNESSKEYFILE"
  pyinst "$@" || exit 2
fi

# -- --update --------------------------------------------------------------------------------
# A pull can replace this very file while sh is still reading it, so when HEAD moves the rest of
# the run is the new script's, started afresh with the same options minus --update (postmortem
# 2026-11-10-first-live-run.md PM-03). The whole if-block is parsed before it runs.
if [ "$UPDATE" = 1 ]; then
  if git -C "$SRC" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' >/dev/null 2>&1; then
    OLDHEAD=$(git -C "$SRC" rev-parse HEAD)
    run git -C "$SRC" pull --ff-only
    if [ "$DRY" = 0 ] && [ "$(git -C "$SRC" rev-parse HEAD)" != "$OLDHEAD" ]; then
      set --
      [ -z "$ROOT" ] || set -- "$@" --research-root "$ROOT"
      [ -z "$HUBKEY" ] || set -- "$@" --hub-key "$HUBKEY"
      [ -z "$HUBKEYFILE" ] || set -- "$@" --hub-pubkey "$HUBKEYFILE"
      [ -z "$HARNESSKEY" ] || set -- "$@" --harness-key "$HARNESSKEY"
      [ -z "$HARNESSKEYFILE" ] || set -- "$@" --harness-pubkey "$HARNESSKEYFILE"
      [ -z "$FROM" ] || set -- "$@" --hub-from "$FROM"
      [ -z "$WFILE" ] || set -- "$@" --withheld-file "$WFILE"
      [ "$APPLY" = 0 ] || set -- "$@" --apply-authorized-keys
      echo "checkout updated; running the updated scripts/node-install.sh"
      exec sh "$SRC/scripts/node-install.sh" "$@"
    fi
  else
    echo "no upstream for this branch; installing the current checkout"
  fi
fi

# -- code: release directory, then an atomic symlink swap -------------------------------------
STAMP="$(date +%Y%m%d%H%M%S)-$$"
REL="$DEST/releases/$STAMP"
run mkdir -p "$REL" "$BIN" "$RB"
run chmod 700 "$RB"
run cp -R "$SRC/rb_node" "$REL/rb_node"
run find "$REL/rb_node" -name __pycache__ -prune -exec rm -rf {} +
if [ -d "$DEST/rb_node" ] && [ ! -L "$DEST/rb_node" ]; then
  # first run over a plain directory: one moment without code, on this run only
  run mkdir -p "$DEST/releases/legacy"
  run rm -rf "$DEST/releases/legacy/rb_node"
  run mv "$DEST/rb_node" "$DEST/releases/legacy/rb_node"
fi
run rm -f "$DEST/rb_node.new"
run ln -s "releases/$STAMP/rb_node" "$DEST/rb_node.new"
run mv -T "$DEST/rb_node.new" "$DEST/rb_node"
if [ "$DRY" = 0 ]; then
  # keep the two newest releases (by mtime) and the one in use; "legacy" is never pruned
  INUSE=$(readlink "$DEST/rb_node" | cut -d/ -f2)
  ls -1t "$DEST/releases" | grep -v '^legacy$' | tail -n +3 | while read -r old; do
    [ "$old" = "$INUSE" ] || rm -rf "$DEST/releases/$old"
  done
fi

# -- wrapper with the absolute python found now -----------------------------------------------
if [ "$DRY" = 1 ]; then
  echo "[dry-run] write $RBN (python $PY)"
else
  cat > "$RBN.new" <<WRAP
#!/bin/sh
PYTHONPATH="\$HOME/.local/share/research-bridge" exec $PY -m rb_node.cli "\$@"
WRAP
  chmod 755 "$RBN.new"
  mv -f "$RBN.new" "$RBN"
fi

# -- node.json --------------------------------------------------------------------------------
if [ ! -f "$NODEJSON" ]; then run "$RBN" config init; fi
if [ -n "$ROOT" ]; then run "$RBN" config set trm_root "$ROOT"; fi
if [ "$DRY" = 0 ]; then
  CB=$("$RBN" config show | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("claude_bin") or "")')
  if ! { [ -n "$CB" ] && [ -f "$CB" ] && [ -x "$CB" ]; }; then
    CL=$(command -v claude || true)
    if [ -n "$CL" ]; then "$RBN" config set claude_bin "$CL"; fi
  fi
else
  echo "[dry-run] set claude_bin only when the current value is not an executable file"
fi

if [ -n "$WFILE" ]; then
  if [ "$DRY" = 1 ]; then
    pyinst withheld --file "$WFILE" --dry-run || exit 1
  else
    pyinst withheld --file "$WFILE" || { echo "withheld file refused; stopping" >&2; exit 1; }
  fi
fi

# -- mailbox, install record ------------------------------------------------------------------
if [ "$DRY" = 1 ]; then
  echo "[dry-run] create mailbox in, out, state, state/acked (mode 700)"
  echo "[dry-run] rb-node install-record $SRC"
else
  pyinst mailbox
  "$RBN" install-record "$SRC"
fi

# -- authorized_keys --------------------------------------------------------------------------
if { [ -n "$HUBKEY" ] || [ -n "$HUBKEYFILE" ]; } && [ -n "$FROM" ]; then
  set -- authorized-keys --hub-from "$FROM" --bindir "$BIN"
  [ -z "$HUBKEY" ] || set -- "$@" --hub-key "$HUBKEY"
  [ -z "$HUBKEYFILE" ] || set -- "$@" --hub-pubkey "$HUBKEYFILE"
  [ -z "$HARNESSKEY" ] || set -- "$@" --harness-key "$HARNESSKEY"
  [ -z "$HARNESSKEYFILE" ] || set -- "$@" --harness-pubkey "$HARNESSKEYFILE"
  [ "$APPLY" = 0 ] || set -- "$@" --apply
  [ "$DRY" = 0 ] || set -- "$@" --dry-run
  pyinst "$@"
else
  echo "authorized_keys: give --hub-key (or --hub-pubkey) and --hub-from to print the lines"
fi

# -- host key fingerprints, then the doctor ---------------------------------------------------
pyinst fingerprints
if [ "$DRY" = 1 ]; then
  echo "[dry-run] rb-node doctor"
else
  "$RBN" doctor || true
fi
echo "Next (you, on this console): rb-node approve-key set"
