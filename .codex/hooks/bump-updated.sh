#!/usr/bin/env bash
# bump-updated.sh — PostToolUse hook (Write|Edit matcher)
# Deterministically bumps the `updated:` YAML frontmatter field to today's date
# on session-persistent tracking files. No-ops if file isn't tracked or date
# already matches today.
#
# Tracked files (by basename):
#   SESSION_START.md, TASKS.md, MEMORY.md, CLAUDE.md

set -uo pipefail

EVENT=$(cat 2>/dev/null || true)
[[ -z "$EVENT" ]] && exit 0

# Extract file path from event JSON (prefer tool_response.filePath, fall back to tool_input.file_path)
FILE=$(printf '%s' "$EVENT" | python -c "
import sys, json
try:
    d = json.loads(sys.stdin.read())
    fp = (d.get('tool_response') or {}).get('filePath') or (d.get('tool_input') or {}).get('file_path') or ''
    print(fp)
except Exception:
    pass
" 2>/dev/null)

[[ -z "$FILE" ]] && exit 0
[[ ! -f "$FILE" ]] && exit 0

FNAME="$(basename "$FILE")"
case "$FNAME" in
    SESSION_START.md|TASKS.md|MEMORY.md|CLAUDE.md) ;;
    *) exit 0 ;;
esac

# Bump `updated: YYYY-MM-DD` inside the first frontmatter block (between leading --- markers)
python - "$FILE" <<'PY' 2>/dev/null || true
import re, sys, pathlib, datetime
p = pathlib.Path(sys.argv[1])
try:
    s = p.read_text(encoding="utf-8")
except Exception:
    sys.exit(0)

today = datetime.date.today().isoformat()

# Only touch the first frontmatter block (between two --- lines at the top)
m = re.match(r'^(---\n)(.*?)(\n---\n)', s, flags=re.S)
if not m:
    sys.exit(0)  # no frontmatter — skip (e.g., CLAUDE.md has no frontmatter)

fm = m.group(2)
new_fm, n = re.subn(r'(?m)^(updated:\s*)\d{4}-\d{2}-\d{2}', r'\g<1>' + today, fm, count=1)
if n == 0 or new_fm == fm:
    sys.exit(0)

new = m.group(1) + new_fm + m.group(3) + s[m.end():]
if new != s:
    p.write_text(new, encoding="utf-8")
PY

exit 0
