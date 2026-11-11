#!/bin/sh
# shellcheck disable=SC2016  # the single-quoted markers must reach the remote side unexpanded
# B2 security checks, hub side (docs/provisioning.md §B2 rows 1, 2, 3, 6; row 4 optional).
# Run by the user in a hub terminal, from the research-bridge main checkout:
#
#     scripts/b2-hub.sh [NODE] [--shared-alias SSH_ALIAS]
#
# NODE defaults to the only node in host.json. --shared-alias names the ssh alias of your own
# login with <SHARED_KEY> (row 4); without it row 4 is skipped. It opens SSH connections to the
# node but writes nothing there. It never prints what the node sent for rows 1 and 2 (a failing
# row could carry /etc/passwd); it prints only whether the shell marker or passwd lines appeared.
# Rows 1 and 2 fail as "not reached" when ssh exits with status 255, prints a connection or
# authentication error, or does not end within 30 s: absent markers then prove nothing.
# Exit status: 0 when every row holds, 1 otherwise.
set -u

NODE=""; SHARED=""
while [ $# -gt 0 ]; do
  case "$1" in
    --shared-alias) SHARED="${2:?--shared-alias needs a value}"; shift 2 ;;
    -h|--help) sed -n '3,14p' "$0"; exit 0 ;;
    *) NODE="$1"; shift ;;
  esac
done

cd "$(dirname "$0")/.." || exit 2
RB="${RB:-uv run --extra host rb}"
VARS=$(uv run --extra host python - "$NODE" <<'PY'
import os, shlex, sys
from rb_host.config import load_host_config
nodes = load_host_config(os.environ.get("RB_HOST_CONFIG") or None).nodes
name = sys.argv[1] or (next(iter(nodes)) if len(nodes) == 1 else "")
if name not in nodes:
    sys.exit("give NODE; host.json has: %s" % ", ".join(sorted(nodes)))
n = nodes[name]
print("NODE=%s ALIAS=%s HALIAS=%s" % tuple(shlex.quote(v) for v in (
    name, n.get("alias", "rb-" + name), n.get("harness_alias", "rb-" + name + "-harness"))))
PY
) || exit 2  # a failed lookup stops here; inside eval "$(...)" its status was lost
eval "$VARS"

FAILS=0
pass() { echo "PASS row $1: $2"; }
fail() { echo "FAIL row $1: $2"; FAILS=$((FAILS + 1)); }
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
# The marker is computed by a shell: "$((40+2))MARK" becomes "42MARK" only if a shell ran it.
# An echo of the input by the protocol would keep the literal "$((40+2))MARK".

# not_reached ROW STATUS FILE: true when ssh did not reach the forced command. Status 255 is
# ssh's own error status; 124 is timeout's. Prints only fixed text, never the file's content.
SSH_ERR='^ssh: |Permission denied|Host key verification failed|Could not resolve hostname'
SSH_ERR="$SSH_ERR|Connection (refused|closed|reset|timed out)|No route to host|kex_exchange_identification"
not_reached() {
  if [ "$2" = 124 ]; then fail "$1" "not reached: ssh did not end within 30 s (output not shown)"; return 0; fi
  if [ "$2" = 255 ] || grep -qE "$SSH_ERR" "$3"; then
    fail "$1" "not reached: ssh exit $2 or an ssh error line (output not shown)"; return 0
  fi
  return 1
}

echo "B2 hub checks for node $NODE (alias $ALIAS, harness alias $HALIAS)"

# Row 1: no shell on the bridge key. Feed a shell line on stdin; the forced command reads protocol.
printf 'echo $((40+2))MARK\n' | timeout 30 ssh -T "$ALIAS" >"$TMP/r1" 2>&1
rc=$?  # status of the last command of the pipeline: timeout, which passes on ssh's status
if grep -q '42MARK' "$TMP/r1"; then fail 1 "a shell ran input on the bridge key"
elif not_reached 1 "$rc" "$TMP/r1"; then :
else pass 1 "no shell on $ALIAS ($(wc -c <"$TMP/r1") bytes of protocol output, not shown)"; fi

# Row 2: the requested command is ignored.
timeout 30 ssh "$ALIAS" 'echo $((40+3))MARK; cat /etc/passwd' </dev/null >"$TMP/r2" 2>&1
rc=$?
if grep -q '43MARK' "$TMP/r2" || grep -q '^root:' "$TMP/r2"; then
  fail 2 "the requested command ran (marker or passwd lines in the output)"
elif not_reached 2 "$rc" "$TMP/r2"; then :
else pass 2 "requested command ignored ($(wc -c <"$TMP/r2") bytes, not shown)"; fi

# Row 3: the harness key accepts only its own commands.
timeout 30 ssh "$HALIAS" ls </dev/null >"$TMP/r3" 2>&1; rc=$?
if [ "$rc" = 1 ] && grep -q 'rb-node harness-receive: unknown command' "$TMP/r3"; then
  pass 3 "harness key refused 'ls' (exit 1, unknown command)"
else fail 3 "harness key: exit $rc, expected text absent ($(wc -c <"$TMP/r3") bytes, not shown)"; fi

# Row 4 (record only): what your own login with the shared key gives.
if [ -n "$SHARED" ]; then
  timeout 30 ssh -o BatchMode=yes "$SHARED" 'echo $((40+4))MARK' </dev/null >"$TMP/r4" 2>&1; rc=$?
  if grep -q '44MARK' "$TMP/r4"; then echo "INFO row 4: $SHARED gives a normal shell (unrestricted); record it for decision 5"
  else echo "INFO row 4: $SHARED did not run a shell command (exit $rc); record it for decision 5"; fi
else
  echo "SKIP row 4: give --shared-alias SSH_ALIAS to record what the shared key gives"
fi

# Row 6: hub doctor against the node.
$RB doctor --node "$NODE" >"$TMP/r6" 2>&1
missing=""
for id in known_host ssh_options reachable node_withheld node_approval; do
  grep -q "^ok $id " "$TMP/r6" || missing="$missing $id"
done
if grep -q '^fail ' "$TMP/r6" || [ -n "$missing" ]; then
  fail 6 "rb doctor --node $NODE: not ok:$missing $(grep '^fail ' "$TMP/r6" | cut -d' ' -f2 | tr '\n' ' ')"
else pass 6 "rb doctor --node $NODE: $(grep '^summary:' "$TMP/r6")"; fi

echo "Rows 5, 7, 8 run on the node console: scripts/b2-node.sh"
if [ "$FAILS" = 0 ]; then echo "hub side: all rows hold"; exit 0; fi
echo "hub side: $FAILS row(s) failed; stop and write a postmortem (docs/postmortems/README.md)"; exit 1
