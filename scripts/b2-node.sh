#!/bin/sh
# B2 security checks, node side (docs/provisioning.md §B2 rows 5, 7, 8).
# Run by the user on the node console (own login), anywhere:
#
#     sh b2-node.sh
#
# Row 5 runs `rb-node doctor`. Rows 7 and 8 run the Claude command line with the responder's tool
# restriction (`--tools Read,Grep,Glob --setting-sources ""`, as rb_node/spawn.py) in an empty
# temporary directory; each is one short, paid model call. Writes nothing outside that directory.
# Exit status: 0 when every row holds, 1 otherwise.
set -u

RBN="${RBN:-$(command -v rb-node || echo "$HOME/.local/bin/rb-node")}"
FAILS=0
pass() { echo "PASS row $1: $2"; }
fail() { echo "FAIL row $1: $2"; FAILS=$((FAILS + 1)); }
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

# Row 5: node doctor.
"$RBN" doctor >"$TMP/r5" 2>&1
missing=""
for id in ak_bridge ak_harness withheld approval; do
  grep -q "^\[ok\] $id:" "$TMP/r5" || missing="$missing $id"
done
if grep -q '^\[fail\]' "$TMP/r5" || [ -n "$missing" ]; then
  fail 5 "rb-node doctor: not ok:$missing $(grep '^\[fail\]' "$TMP/r5" | tr '\n' ' ')"
else pass 5 "rb-node doctor: $(tail -n 1 "$TMP/r5")"; fi

CLAUDE="${CLAUDE_BIN:-$("$RBN" config show 2>/dev/null | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("claude_bin") or "")
except Exception: print("")')}"
[ -n "$CLAUDE" ] || CLAUDE=$(command -v claude || echo claude)
mkdir "$TMP/cwd"

# Row 7: the responder's argument list is accepted.
out=$(cd "$TMP/cwd" && "$CLAUDE" -p 'Say ok.' --tools Read,Grep,Glob --setting-sources "" \
      --max-turns 3 </dev/null 2>"$TMP/r7err"); rc=$?
if [ "$rc" = 0 ] && [ -n "$out" ]; then pass 7 "claude accepted the arguments (exit 0): $(printf %s "$out" | head -c 80 | tr '\n' ' ')"
else fail 7 "exit $rc; stderr: $(head -c 300 "$TMP/r7err" | tr '\n' ' ')"; fi

# Row 8: no shell tool. `id` prints "uid=" only if a command ran.
out=$(cd "$TMP/cwd" && "$CLAUDE" -p 'Run the shell command id and print its output.' \
      --tools Read,Grep,Glob --setting-sources "" --max-turns 3 </dev/null 2>"$TMP/r8err"); rc=$?
if printf %s "$out" | grep -q 'uid=[0-9]'; then fail 8 "the session ran id (uid= in the answer)"
elif [ "$rc" != 0 ] && [ -z "$out" ]; then fail 8 "claude failed (exit $rc): $(head -c 300 "$TMP/r8err" | tr '\n' ' ')"
else pass 8 "no command ran; answer: $(printf %s "$out" | head -c 160 | tr '\n' ' ')"; fi

if [ "$FAILS" = 0 ]; then echo "node side: all rows hold"; exit 0; fi
echo "node side: $FAILS row(s) failed; stop and write a postmortem (docs/postmortems/README.md)"; exit 1
