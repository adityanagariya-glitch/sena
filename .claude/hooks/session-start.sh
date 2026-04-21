#!/usr/bin/env bash
# session-start.sh — SessionStart hook
# Injects deterministic read-order reminder on every new session so Claude
# always lands in the same state. This runs regardless of what Claude "remembers".

set -uo pipefail

cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"SENA SESSION RESUME PROTOCOL (hook-enforced, deterministic):\n\n1. READ FIRST: .claude/SESSION_START.md — authoritative read-order guide for this project.\n2. THEN: .claude/tasks/TASKS.md — current state, active/pending/backlog tasks.\n3. THEN: ~/.claude/projects/C--Users-Admin-Downloads-SENA/memory/MEMORY.md — memory index (points to user/project/feedback memories).\n4. For task-specific context (voice demo, Gemini Live, roadmap), follow the links inside SESSION_START.md — do not re-grep the repo.\n\nBEFORE SESSION END: ensure .claude/tasks/TASKS.md reflects current task statuses. The PostToolUse bump-updated hook auto-refreshes 'updated:' frontmatter on SESSION_START.md/TASKS.md/MEMORY.md/CLAUDE.md when you edit them.\n\nRULES RELOADED EVERY SESSION (from CLAUDE.md):\n- Gemini Live code → invoke Skill: gemini-live-api-dev BEFORE editing\n- Use send_realtime_input(audio=Blob) — NOT the legacy LiveClientRealtimeInput path\n- session.receive() returns per-turn — wrap in while True with continue\n- NEVER read /archive, .venv, .vscode"}}
JSON

exit 0
