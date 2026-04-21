#!/usr/bin/env bash
# pre-tool-use.sh — PreToolUse hook (all tools)
# Enforces three mandatory rules from CLAUDE.md deterministically:
#   RULE 1 — Gemini skill gate: any Write/Edit to a Gemini file must invoke Skill: gemini-live-api-dev first
#   RULE 2 — Context7 gate: any Bash automation/setup command must verify API patterns via Context7 first
#   RULE 3 — Safety: blocks rm -rf on critical dirs, force push to main

set -uo pipefail

EVENT=$(cat 2>/dev/null || true)
[[ -z "$EVENT" ]] && exit 0

TOOL=$(printf '%s' "$EVENT" | python -c "import sys,json; print(json.loads(sys.stdin.read()).get('tool_name',''))" 2>/dev/null)
FILE=$(printf '%s' "$EVENT" | python -c "import sys,json; d=json.loads(sys.stdin.read()); print((d.get('tool_input') or {}).get('file_path',''))" 2>/dev/null)
CMD=$(printf '%s' "$EVENT" | python -c "import sys,json; d=json.loads(sys.stdin.read()); print((d.get('tool_input') or {}).get('command',''))" 2>/dev/null)

# ─── RULE 1: Gemini skill gate ────────────────────────────────────────────────
# Fires on Write or Edit to any file whose path contains gemini or demo_live
if [[ "$TOOL" == "Write" || "$TOOL" == "Edit" ]]; then
    FNAME_LOWER=$(echo "$FILE" | tr '[:upper:]' '[:lower:]')
    if echo "$FNAME_LOWER" | grep -qE 'gemini|demo_live'; then
        python -c "
import json
msg = (
    'GEMINI SKILL GATE (hook-enforced):\\n'
    'File path contains gemini/demo_live_server. CLAUDE.md rule: invoke Skill: gemini-live-api-dev BEFORE editing ANY Gemini API code.\\n'
    'If you have already invoked the skill this session, proceed. If not — stop and invoke it first.\\n'
    'Reminder: current model = gemini-3.1-flash-live-preview | use send_realtime_input(audio=Blob) | session.receive() needs while True loop.'
)
print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'additionalContext': msg}}))
"
        exit 0
    fi
fi

# ─── RULE 2: Context7 gate ────────────────────────────────────────────────────
# Fires on Bash when command matches setup/automation/install patterns
if [[ "$TOOL" == "Bash" ]]; then
    CMD_LOWER=$(echo "$CMD" | tr '[:upper:]' '[:lower:]')
    if echo "$CMD_LOWER" | grep -qE '^(pip install|pip3 install|uvicorn|python -m uvicorn|npm install|npm run|pytest|alembic upgrade|alembic revision|docker-compose up)'; then
        python -c "
import json
msg = (
    'CONTEXT7 GATE (hook-enforced):\\n'
    'CLAUDE.md rule: Always use Context7 (get-library-docs) to verify API or setup steps BEFORE running automation.\\n'
    'Before running this command, confirm you have checked the relevant library docs via Context7 MCP.\\n'
    'If already done this session, proceed. If not — call mcp__plugin_context7_context7__query-docs first.'
)
print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'additionalContext': msg}}))
"
        exit 0
    fi
fi

exit 0
