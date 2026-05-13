#!/usr/bin/env bash
# issue-capture-reminder.sh — PostToolUse hook
# Detects "debug signature": same file edited 3+ times in a session.
# When threshold hit, emits a reminder to log the fix to .claude/issues-solved/.
#
# Design:
#   - State file: .claude/hooks-state/edit-counts.txt
#   - Format:     <file-path>|<count>|<reminded-flag>
#   - Reset:      state file older than 2h = assume new session, wipe
#   - Heuristic:  3 edits = enough debugging to warrant logging
#   - Silent pass if no threshold hit (no noise on single-edit work)

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
STATE_DIR="$REPO_ROOT/.claude/hooks-state"
STATE_FILE="$STATE_DIR/edit-counts.txt"
THRESHOLD=3
RESET_AFTER_SECONDS=7200   # 2h

mkdir -p "$STATE_DIR"

# Reset state if stale (new session heuristic)
if [[ -f "$STATE_FILE" ]]; then
    mtime=$(stat -c %Y "$STATE_FILE" 2>/dev/null || stat -f %m "$STATE_FILE" 2>/dev/null || echo 0)
    now=$(date +%s)
    if (( now - mtime > RESET_AFTER_SECONDS )); then
        : > "$STATE_FILE"
    fi
fi
touch "$STATE_FILE"

# Read event JSON from stdin
EVENT=$(cat 2>/dev/null || true)

# Extract tool_name and file_path — only care about Write/Edit on real code files
tool_name=$(echo "$EVENT" | grep -o '"tool_name"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"\([^"]*\)"$/\1/')
file_path=$(echo "$EVENT" | grep -o '"file_path"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"\([^"]*\)"$/\1/')

# Bail if not an edit tool or no file path
case "$tool_name" in
    Write|Edit|NotebookEdit) ;;
    *) exit 0 ;;
esac
[[ -z "$file_path" ]] && exit 0

# Only track code files — skip docs, configs, planning
case "$file_path" in
    *.py|*.ts|*.tsx|*.js|*.jsx|*.html|*.css|*.sh|*.go|*.rs|*.java) ;;
    *) exit 0 ;;
esac

# Skip files inside .claude/issues-solved itself (avoid recursion noise)
case "$file_path" in
    *.claude/issues-solved/*|*.claude/hooks/*) exit 0 ;;
esac

# Increment counter for this file
current_line=$(grep -F "$file_path|" "$STATE_FILE" 2>/dev/null | head -1)
if [[ -z "$current_line" ]]; then
    echo "$file_path|1|0" >> "$STATE_FILE"
    exit 0
fi

count=$(echo "$current_line" | awk -F'|' '{print $2}')
reminded=$(echo "$current_line" | awk -F'|' '{print $3}')
new_count=$((count + 1))

# Update counter — write to temp, swap
grep -v -F "$file_path|" "$STATE_FILE" > "$STATE_FILE.tmp" 2>/dev/null || true
echo "$file_path|$new_count|$reminded" >> "$STATE_FILE.tmp"
mv "$STATE_FILE.tmp" "$STATE_FILE"

# Emit reminder on threshold crossing, only once per file per session
if (( new_count >= THRESHOLD )) && [[ "$reminded" == "0" ]]; then
    # Mark as reminded
    grep -v -F "$file_path|" "$STATE_FILE" > "$STATE_FILE.tmp" 2>/dev/null || true
    echo "$file_path|$new_count|1" >> "$STATE_FILE.tmp"
    mv "$STATE_FILE.tmp" "$STATE_FILE"

    # Emit to stderr — Claude Code surfaces stderr as system message
    cat >&2 <<EOF
[issue-capture-reminder] File '$file_path' edited $new_count times this session — debug signature detected.
If you solved a non-trivial bug, log it:
  1. Copy .claude/issues-solved/TEMPLATE.md to NNNN-kebab-symptom.md
  2. Fill symptom, root_cause, fix, failed_attempts, fix_commit
  3. Prepend row to .claude/issues-solved/INDEX.md
  4. Commit: docs(issues-solved): NNNN <symptom>
Or use /solve <symptom> first to check if it's already logged.
EOF
fi

exit 0
