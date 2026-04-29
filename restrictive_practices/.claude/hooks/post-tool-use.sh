#!/usr/bin/env bash
# post-tool-use.sh — PostToolUse hook for restrictive_practices module
# Auto-bumps the updated: date in TASKS.md and SESSION_START.md
# whenever Claude writes or edits any file.

set -uo pipefail

# Read tool name from stdin JSON
STDIN=$(cat)
TOOL=$(echo "$STDIN" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('tool_name', ''))
except Exception:
    print('')
" 2>/dev/null || echo "")

# Only bump on file-modifying tools
case "$TOOL" in
    Write|Edit|NotebookEdit) ;;
    *) exit 0 ;;
esac

TODAY=$(date +%Y-%m-%d)
PROJ_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TASKS="$PROJ_ROOT/.claude/tasks/TASKS.md"
SESSION="$PROJ_ROOT/.claude/SESSION_START.md"

# Replace updated: line with today's date
update_date() {
    local file="$1"
    if [ -f "$file" ]; then
        python3 -c "
import sys
path = sys.argv[1]
today = sys.argv[2]
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()
import re
content = re.sub(r'^updated: \d{4}-\d{2}-\d{2}', f'updated: {today}', content, flags=re.MULTILINE)
with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
" "$file" "$TODAY" 2>/dev/null || true
    fi
}

update_date "$TASKS"
update_date "$SESSION"

exit 0
