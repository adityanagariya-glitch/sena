#!/usr/bin/env bash
# session-start.sh — SessionStart hook
# 1. Clears per-session gate flags (ctx7, skills) — fresh enforcement each session.
# 2. Injects read-order protocol + 3 enforcement rule reminders as additionalContext.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_STATE="$SCRIPT_DIR/../hooks-state"

# Clear session-scoped flags — deterministic fresh start every session
mkdir -p "$HOOKS_STATE"
rm -f "$HOOKS_STATE/ctx7-session.flag"
rm -f "$HOOKS_STATE/skills-gemini.flag"

cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"SENA_AI SESSION START (hook-enforced — deterministic)\n\n── READ ORDER ──────────────────────────────────────────────────────────────\n1. .claude/SESSION_START.md  ← authoritative context guide\n2. .claude/tasks/TASKS.md    ← current tasks + statuses\n3. ~/.claude/projects/.../memory/MEMORY.md  ← user/project/feedback memories\n\n── 3 ENFORCEMENT RULES (PreToolUse hook BLOCKS violations) ─────────────────\nRULE 1 — WRITE GUARD:\n  Only Write/Edit inside SENA_AI/. Parent sena-mobile/ is READ-ONLY.\n  Absolute paths outside SENA_AI/ → hard block.\n\nRULE 2 — CONTEXT7 GATE (flag cleared — must re-fetch this session):\n  First .py write BLOCKED until Context7 live-doc fetch.\n  Steps: resolve-library-id → query-docs for EACH library → then implement.\n  Flag auto-sets on first Context7 MCP call.\n\nRULE 3 — GEMINI SKILL GATE (flag cleared — must re-invoke this session):\n  Any edit to gemini*/demo_live* files BLOCKED until Skill: gemini-live-api-dev invoked.\n  Flag auto-sets when Skill tool fires with gemini/vertex skill name.\n\n── INSTALLED SKILLS (invoke before touching related code) ──────────────────\n  gemini-live-api-dev     → Gemini Live API (streaming voice, send_realtime_input)\n  gemini-api-dev          → Gemini REST API (generate, embed, function calling)\n  gemini-interactions-api → Interaction patterns\n  vertex-ai-api-dev       → Vertex AI / Google Cloud AI\n\n── GEMINI LIVE (current patterns from CLAUDE.md) ───────────────────────────\n  Model: gemini-3.1-flash-live-preview\n  Audio: send_realtime_input(audio=types.Blob(data=raw, mime_type='audio/pcm;rate=16000'))\n  Receive: wrap session.receive() in while True loop\n  NEVER gate mic on _agent_speaking → silent VAD death after 2-4 turns\n  START_SENSITIVITY_LOW — HIGH fires on ambient noise between turns\n\n── NEVER READ ───────────────────────────────────────────────────────────────\n  /archive | .venv | .vscode | ndis_markdown_docs/"}}
JSON

exit 0
