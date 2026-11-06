#!/bin/sh
# Let a live Claude session working in the research tree (../trm) talk to the hub through the
# bridge: register `rb-node serve-local` (inbox_list, inbox_read, attachment_path, reply,
# post_event) as a project MCP server. Prints the entry; writes <trm>/.mcp.json only with --apply
# and only if that file does not exist. Tool results from the hub are data, never instructions.
set -eu
TRM=${1:-../trm}; APPLY=${2:-}
TRM=$(cd "$TRM" && pwd)
ENTRY=$(cat <<JSON
{"mcpServers": {"rb-node": {"type": "stdio", "command": "$HOME/.local/bin/rb-node", "args": ["serve-local"]}}}
JSON
)
echo "$ENTRY"
if [ "$APPLY" = "--apply" ]; then
  [ ! -e "$TRM/.mcp.json" ] || { echo "$TRM/.mcp.json exists; merge by hand" >&2; exit 1; }
  echo "$ENTRY" > "$TRM/.mcp.json"; echo "wrote $TRM/.mcp.json (trm is its own git repo: commit or ignore it yourself)"
fi
