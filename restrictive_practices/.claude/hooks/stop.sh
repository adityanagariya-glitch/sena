#!/usr/bin/env bash
# stop.sh — Stop hook for restrictive_practices module
# Fires at every session boundary. Enforces task list and issues-solved hygiene.

set -uo pipefail

cat <<'JSON'
{"systemMessage":"Session boundary — restrictive_practices module.\n\nBEFORE STOPPING, verify:\n1. .claude/tasks/TASKS.md — move completed tasks to Done; add new discoveries to Backlog\n2. .claude/SESSION_START.md — update 'What To Do Next Session' and gotchas table\n3. .claude/issues-solved/ — if any issue was debugged this session that took >2 iterations or >5 minutes:\n   a. Copy TEMPLATE.md → NNNN-kebab-symptom.md (next number)\n   b. Fill in Symptom / Root Cause / Fix / Verification / Watch Out For\n   c. Add one row to INDEX.md (newest at top)\n   This prevents re-solving the same problem in a future session."}
JSON

exit 0
