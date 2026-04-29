#!/usr/bin/env bash
# stop.sh — Stop hook for restrictive_practices module
# Fires at every session boundary. Reminds Claude to keep task list current.

set -uo pipefail

cat <<'JSON'
{"systemMessage":"Session boundary — restrictive_practices module. Before stopping: update .claude/tasks/TASKS.md with any status changes from this session (done → completed, new discoveries → backlog). SESSION_START.md gotchas section should reflect any new issues solved."}
JSON

exit 0
