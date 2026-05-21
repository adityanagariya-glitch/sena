"""PostToolUse hook — bumps updated: date in TASKS.md + SESSION_START.md on Write/Edit."""
import json, re, sys
from datetime import date
from pathlib import Path

try:
    data = json.load(sys.stdin)
    tool = data.get("tool_name", "")
except Exception:
    sys.exit(0)

if tool not in ("Write", "Edit", "NotebookEdit"):
    sys.exit(0)

today = date.today().isoformat()
root = Path(__file__).resolve().parent.parent.parent  # restrictive_practices/

for rel in (".claude/tasks/TASKS.md", ".claude/SESSION_START.md"):
    path = root / rel
    if path.exists():
        text = path.read_text(encoding="utf-8")
        updated = re.sub(r"^updated: \d{4}-\d{2}-\d{2}", f"updated: {today}", text, flags=re.MULTILINE)
        if updated != text:
            path.write_text(updated, encoding="utf-8")

sys.exit(0)
