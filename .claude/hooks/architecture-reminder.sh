#!/usr/bin/env bash
# architecture-reminder.sh — PostToolUse Write hook
# RULE 3: When a new service file is created, remind Claude to update CLAUDE.md
# architecture section (port, service path, env vars).
# Triggers on: new main.py, pyproject.toml, or any file under services/ or a
# top-level new service directory.

set -uo pipefail

EVENT=$(cat 2>/dev/null || true)
[[ -z "$EVENT" ]] && exit 0

FILE=$(printf '%s' "$EVENT" | python -c "
import sys, json
try:
    d = json.loads(sys.stdin.read())
    print((d.get('tool_input') or {}).get('file_path', ''))
except Exception:
    pass
" 2>/dev/null)

[[ -z "$FILE" ]] && exit 0

FILE_LOWER=$(echo "$FILE" | tr '[:upper:]' '[:lower:]' | tr '\\\\' '/')

# Trigger on: new service main.py, pyproject.toml, settings.py, or any file under /services/
if echo "$FILE_LOWER" | grep -qE '/(services/[^/]+/(main|pyproject|settings)\.py?|services/[^/]+/src/)'; then
    python -c "
import json
msg = (
    'CLAUDE.md ARCHITECTURE RULE (hook-enforced):\\n'
    'A new service file was just written. CLAUDE.md must be updated to reflect:\\n'
    '  1. New service name and path under sena-ai/services/\\n'
    '  2. Port number (next available after 8082)\\n'
    '  3. New env vars (SENA_AI_ prefix)\\n'
    '  4. Any new external dependencies\\n'
    'Update the Architecture section in CLAUDE.md before ending this session.'
)
print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PostToolUse', 'additionalContext': msg}}))
"
fi

exit 0
