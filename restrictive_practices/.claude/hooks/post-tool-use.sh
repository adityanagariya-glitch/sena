#!/usr/bin/env bash
# post-tool-use.sh — PostToolUse hook for restrictive_practices module
# 1. Auto-bumps the updated: date in TASKS.md and SESSION_START.md on any file write/edit
# 2. Reminds to log the issue when a file inside issues-solved/ is written

set -uo pipefail

STDIN=$(cat)
TOOL=$(echo "$STDIN" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('tool_name', ''))
except Exception:
    print('')
" 2>/dev/null || echo "")

# Only act on file-modifying tools
case "$TOOL" in
    Write|Edit|NotebookEdit) ;;
    *) exit 0 ;;
esac

TODAY=$(date +%Y-%m-%d)
PROJ_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TASKS="$PROJ_ROOT/.claude/tasks/TASKS.md"
SESSION="$PROJ_ROOT/.claude/SESSION_START.md"
ISSUES_INDEX="$PROJ_ROOT/.claude/issues-solved/INDEX.md"

# Replace updated: line with today's date
update_date() {
    local file="$1"
    if [ -f "$file" ]; then
        python3 -c "
import sys, re
path, today = sys.argv[1], sys.argv[2]
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()
content = re.sub(r'^updated: \d{4}-\d{2}-\d{2}', f'updated: {today}', content, flags=re.MULTILINE)
with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
" "$file" "$TODAY" 2>/dev/null || true
    fi
}

update_date "$TASKS"
update_date "$SESSION"

# Check if a new issues-solved file was just written — remind to update INDEX
FILE_PATH=$(echo "$STDIN" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    p = d.get('tool_input', {})
    print(p.get('file_path', p.get('path', '')))
except Exception:
    print('')
" 2>/dev/null || echo "")

if echo "$FILE_PATH" | grep -q "issues-solved/[0-9]"; then
    # A numbered issue file was written — check if INDEX.md needs updating
    BASENAME=$(basename "$FILE_PATH")
    if ! grep -q "$BASENAME" "$ISSUES_INDEX" 2>/dev/null; then
        echo '{"systemMessage":"New issue file written but not yet in INDEX.md. Add a row to .claude/issues-solved/INDEX.md before the session ends."}' >&2
    fi
fi

exit 0
