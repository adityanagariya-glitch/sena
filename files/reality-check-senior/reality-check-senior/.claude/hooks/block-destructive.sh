#!/usr/bin/env bash
# Pre-tool-use hook: block destructive commands on data/ and checkpoints/.
# The agent's discretion is not enough for these — they get a hard gate.

set -euo pipefail

# Claude Code passes the tool input via $CLAUDE_TOOL_INPUT (JSON).
# We're matching on the Bash tool's `command` field.

CMD="${CLAUDE_TOOL_INPUT_COMMAND:-${1:-}}"

# Patterns to block
BLOCKED_PATTERNS=(
  "rm -rf data"
  "rm -rf ./data"
  "rm -rf /data"
  "rm -rf checkpoints"
  "rm -rf ./checkpoints"
  "rm -rf models"
  "rm -rf ./models"
  "git push --force origin main"
  "git push --force origin master"
  "git push -f origin main"
  "git push -f origin master"
  "dvc remove"
)

for pattern in "${BLOCKED_PATTERNS[@]}"; do
  if [[ "$CMD" == *"$pattern"* ]]; then
    echo "🚫 BLOCKED by hook: command matches destructive pattern '$pattern'."
    echo "   If you genuinely need this, run it manually outside the agent."
    exit 1
  fi
done

exit 0
