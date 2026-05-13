#!/usr/bin/env bash
# ctx7-flag.sh — PostToolUse hook (Context7 MCP tools)
# Sets ctx7-session.flag  → satisfies RULE 2 (any .py write gate)
# Sets ctx7-gemini.flag   → satisfies RULE 3 (gemini/demo_live file gate)
#   ctx7-gemini.flag is set when the context7 query/libraryName contains
#   gemini, google-genai, genai, or google-gen terms.
# Fires when any mcp__plugin_context7_context7__* tool is called.

set -uo pipefail

EVENT=$(cat 2>/dev/null || true)
[[ -z "$EVENT" ]] && exit 0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_STATE="$SCRIPT_DIR/../hooks-state"
mkdir -p "$HOOKS_STATE"

# Always satisfy the generic ctx7 gate
touch "$HOOKS_STATE/ctx7-session.flag"

# Extract query and libraryName from the tool input to detect gemini-specific fetch
CTX7_QUERY=$(printf '%s' "$EVENT" | python -c "
import sys, json
d = json.loads(sys.stdin.read())
inp = d.get('tool_input') or {}
parts = [
    str(inp.get('query', '')),
    str(inp.get('libraryName', '')),
    str(inp.get('libraryId', '')),
]
print(' '.join(parts).lower())
" 2>/dev/null || true)

if printf '%s' "$CTX7_QUERY" | grep -qiE 'gemini|google.gen|genai|google-gen|live.api|live_api'; then
    touch "$HOOKS_STATE/ctx7-gemini.flag"
fi

exit 0
