#!/usr/bin/env bash
# stop.sh — Stop hook
# Fires when Claude stops (including /clear, /compact, resume boundaries).
# Emits a system message reminding that session-persistent files should be current.

set -uo pipefail

cat <<'JSON'
{"systemMessage":"Session boundary. Verify .claude/tasks/TASKS.md reflects task status changes from this session. Auto-bump hook refreshes timestamps on SESSION_START.md/TASKS.md/MEMORY.md/CLAUDE.md."}
JSON

exit 0
