"""Stop hook — reminds Claude to update TASKS.md at session boundary."""
import json, sys

payload = {
    "systemMessage": (
        "Session boundary — restrictive_practices module. "
        "Before stopping: update .claude/tasks/TASKS.md with status changes from this session "
        "(done → completed, new discoveries → backlog). "
        "SESSION_START.md gotchas section should reflect any new issues solved."
    )
}
print(json.dumps(payload))
sys.exit(0)
