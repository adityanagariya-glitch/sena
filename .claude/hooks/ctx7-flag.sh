#!/usr/bin/env bash
# ctx7-flag.sh — PostToolUse hook (Context7 MCP tools)
# Sets ctx7-session.flag to satisfy RULE 2 (Context7 gate) in pre-tool-use.sh.
# Fires when any mcp__plugin_context7_context7__* tool is called.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_STATE="$SCRIPT_DIR/../hooks-state"
mkdir -p "$HOOKS_STATE"
touch "$HOOKS_STATE/ctx7-session.flag"
exit 0
