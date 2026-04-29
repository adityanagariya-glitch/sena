#!/usr/bin/env bash
# pre-tool-use.sh — PreToolUse hook (all tools)
# THREE DETERMINISTIC ENFORCEMENT RULES — hardcoded, not prompt-based.
#
# RULE 1 — WRITE GUARD
#           Write/Edit/NotebookEdit outside SENA_AI/ are BLOCKED.
#           Parent sena-mobile/ tree is READ-ONLY for reference only.
#
# RULE 2 — CONTEXT7 GATE
#           First Python (.py) implementation write per session is BLOCKED
#           until Context7 live-doc fetch occurs. Flag cleared at SessionStart.
#           Flag: .claude/hooks-state/ctx7-session.flag
#
# RULE 3 — GEMINI SKILL GATE
#           Edit to gemini*/demo_live* files BLOCKED until
#           Skill: gemini-live-api-dev invoked this session. Flag cleared at SessionStart.
#           Flag: .claude/hooks-state/skills-gemini.flag
#
# RULE 4 — SAFETY
#           Blocks rm -rf on critical dirs; blocks force push to main/master.

set -uo pipefail

EVENT=$(cat 2>/dev/null || true)
[[ -z "$EVENT" ]] && exit 0

TOOL=$(printf '%s' "$EVENT" | python -c "import sys,json; print(json.loads(sys.stdin.read()).get('tool_name',''))" 2>/dev/null || true)
FILE=$(printf '%s' "$EVENT" | python -c "import sys,json; d=json.loads(sys.stdin.read()); print((d.get('tool_input') or {}).get('file_path',''))" 2>/dev/null || true)
CMD=$(printf '%s' "$EVENT" | python -c "import sys,json; d=json.loads(sys.stdin.read()); print((d.get('tool_input') or {}).get('command',''))" 2>/dev/null || true)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_STATE="$SCRIPT_DIR/../hooks-state"

# ─── RULE 1: WRITE GUARD ─────────────────────────────────────────────────────
# Absolute paths must contain SENA_AI. Relative paths are CWD-relative
# (CWD = SENA_AI/) so they are always inside the project — skip the check.
if [[ "$TOOL" == "Write" || "$TOOL" == "Edit" || "$TOOL" == "NotebookEdit" ]]; then
    if [[ -n "$FILE" ]]; then
        FILE_NORM=$(printf '%s' "$FILE" | sed 's|\\|/|g')
        # Only check absolute paths
        if [[ "$FILE_NORM" == /* ]] || [[ "$FILE_NORM" =~ ^[A-Za-z]: ]]; then
            if ! printf '%s' "$FILE_NORM" | grep -qi 'SENA_AI'; then
                python -c "
import json
print(json.dumps({
    'decision': 'block',
    'reason': (
        'WRITE BLOCKED — Rule 1 (hook-enforced): '
        'Path is outside SENA_AI/. '
        'The parent sena-mobile/ tree is READ-ONLY — for reference only. '
        'All writes must target files inside SENA_AI/. '
        'Correct your file path and retry.'
    )
}))
"
                exit 2
            fi
        fi
    fi
fi

# ─── RULE 2: CONTEXT7 GATE ───────────────────────────────────────────────────
# Python implementation writes require Context7 live-doc fetch first this session.
if [[ "$TOOL" == "Write" || "$TOOL" == "Edit" ]]; then
    FILE_LOWER=$(printf '%s' "$FILE" | tr '[:upper:]' '[:lower:]')
    if printf '%s' "$FILE_LOWER" | grep -qE '\.py$'; then
        CTX7_FLAG="$HOOKS_STATE/ctx7-session.flag"
        if [[ ! -f "$CTX7_FLAG" ]]; then
            python -c "
import json
print(json.dumps({
    'decision': 'block',
    'reason': (
        'CONTEXT7 GATE — Rule 2 (hook-enforced): '
        'Python implementation write requires live documentation fetch via Context7 FIRST this session. '
        'Required steps before writing any .py file: '
        '1) mcp__plugin_context7_context7__resolve-library-id for each library you will use '
        '(fastapi, sqlalchemy, redis, google-generativeai, etc). '
        '2) mcp__plugin_context7_context7__query-docs to fetch current API docs. '
        '3) Then proceed with implementation. '
        'Flag auto-sets on first Context7 call — gate will not fire again this session.'
    )
}))
"
            exit 2
        fi
    fi
fi

# ─── RULE 3: GEMINI SKILL GATE ───────────────────────────────────────────────
# Gemini/demo_live file edits require gemini-live-api-dev skill invoked first.
if [[ "$TOOL" == "Write" || "$TOOL" == "Edit" ]]; then
    FNAME_LOWER=$(printf '%s' "$FILE" | tr '[:upper:]' '[:lower:]')
    if printf '%s' "$FNAME_LOWER" | grep -qE 'gemini|demo_live'; then
        SKILL_FLAG="$HOOKS_STATE/skills-gemini.flag"
        if [[ ! -f "$SKILL_FLAG" ]]; then
            python -c "
import json
print(json.dumps({
    'decision': 'block',
    'reason': (
        'GEMINI SKILL GATE — Rule 3 (hook-enforced): '
        'Editing a gemini/demo_live file requires Skill: gemini-live-api-dev invoked FIRST this session. '
        'Model: gemini-3.1-flash-live-preview. '
        'Correct API: send_realtime_input(audio=types.Blob(data=raw, mime_type=\"audio/pcm;rate=16000\")). '
        'NEVER use legacy LiveClientRealtimeInput. '
        'Invoke the skill via the Skill tool, then retry this edit.'
    )
}))
"
            exit 2
        fi
    fi
fi

# ─── RULE 4: SAFETY ──────────────────────────────────────────────────────────
if [[ "$TOOL" == "Bash" ]]; then
    CMD_LOWER=$(printf '%s' "$CMD" | tr '[:upper:]' '[:lower:]')

    if printf '%s' "$CMD_LOWER" | grep -qE 'rm\s+-rf.*(sena-ai|wiki|ndis_wiki|migrations|shared|\.claude)'; then
        python -c "
import json
print(json.dumps({
    'decision': 'block',
    'reason': 'SAFETY BLOCKED — Rule 4: rm -rf on critical directory. Confirm with user before any destructive delete.'
}))
"
        exit 2
    fi

    if printf '%s' "$CMD_LOWER" | grep -qE 'git push.*(--force|-f).*(main|master)'; then
        python -c "
import json
print(json.dumps({
    'decision': 'block',
    'reason': 'SAFETY BLOCKED — Rule 4: Force push to main/master is not permitted.'
}))
"
        exit 2
    fi
fi

exit 0
