#!/usr/bin/env bash
# skills-flag.sh — PostToolUse hook (Skill tool)
# Sets skills-gemini.flag when a Gemini/Vertex skill is invoked,
# satisfying RULE 3 (Gemini skill gate) in pre-tool-use.sh.

set -uo pipefail

EVENT=$(cat 2>/dev/null || true)
[[ -z "$EVENT" ]] && exit 0

SKILL=$(printf '%s' "$EVENT" | python -c "
import sys, json
d = json.loads(sys.stdin.read())
print((d.get('tool_input') or {}).get('skill', ''))
" 2>/dev/null || true)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_STATE="$SCRIPT_DIR/../hooks-state"
mkdir -p "$HOOKS_STATE"

SKILL_LOWER=$(printf '%s' "$SKILL" | tr '[:upper:]' '[:lower:]')
if printf '%s' "$SKILL_LOWER" | grep -qE 'gemini|vertex'; then
    touch "$HOOKS_STATE/skills-gemini.flag"
fi

exit 0
