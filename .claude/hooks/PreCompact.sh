#!/usr/bin/env bash
# PreCompact hook — fires before Claude Code compacts the conversation.
#
# Purpose: append a snapshot of in-progress work to .claude/memory/sena-memory.md
# so the next session can resume. Compaction otherwise erases trailing turns
# silently — this guarantees a durable resume marker.
#
# Captures: branch, last commit, working-tree state, active task count.
# Idempotent: if today's compaction marker already exists, no-op.

set -euo pipefail

MEMORY_FILE=".claude/memory/sena-memory.md"
TASKS_FILE=".claude/tasks/TASKS.md"
NOW="$(date -u +%Y-%m-%d)"

# Exit silently if bootstrap hasn't completed.
[[ -f "$MEMORY_FILE" ]] || exit 0

# Skip if today's compaction marker already present (idempotent within a day).
if grep -q "^$NOW main — Compaction snapshot" "$MEMORY_FILE" 2>/dev/null; then
  exit 0
fi

# Capture lightweight state. Each command is non-fatal — fall back to placeholders.
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'no-branch')"
COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo 'no-commit')"

DIRTY="clean"
if ! { git diff --quiet 2>/dev/null && git diff --cached --quiet 2>/dev/null; }; then
  DIRTY="DIRTY"
fi

ACTIVE_TASKS=0
if [[ -f "$TASKS_FILE" ]]; then
  ACTIVE_TASKS="$(grep -c '^### #' "$TASKS_FILE" 2>/dev/null || echo 0)"
fi

# Append the snapshot. Read on next session via .claude/SESSION_START.md → TASKS.md.
{
  echo ""
  echo "$NOW main — Compaction snapshot — branch=$BRANCH commit=$COMMIT working_tree=$DIRTY active_tasks=$ACTIVE_TASKS; resume order: .claude/SESSION_START.md → .claude/tasks/TASKS.md → FLUTTER_DEV_HANDOFF.md (if Flutter work in flight) → onboarding_system.md (if voice-prompt work in flight)."
} >> "$MEMORY_FILE"

exit 0
