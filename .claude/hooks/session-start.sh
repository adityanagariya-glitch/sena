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
{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"SENA_AI SESSION START (hook-enforced — deterministic)\n\n── PRE-FLIGHT (RUN BEFORE ANY .py EDIT — saves ~5 wasted iterations) ──────\nA. Generic .py Write/Edit → call mcp__plugin_context7_context7__resolve-library-id ONCE (any library).\nB. Touching gemini*/demo_live* → ALSO invoke Skill: gemini-live-api-dev AND query-docs for google-genai.\nC. Verify ls .claude/hooks-state/ shows ctx7-session.flag (and skills/ctx7-gemini if B applies) BEFORE spawning any Python implementer agent.\nD. Sub-agents CANNOT clear gates for themselves — orchestrator must do it in main session first.\nFull checklist in CLAUDE.md '## Pre-flight for Python edits'. Lessons in .claude/memory/lessons.md (2026-05-25).\n\n── READ ORDER ──────────────────────────────────────────────────────────────\n1. .claude/SESSION_START.md  ← authoritative context guide (§0 = pre-flight)\n2. .claude/tasks/TASKS.md    ← current tasks + statuses\n3. ~/.claude/projects/.../memory/MEMORY.md  ← user/project/feedback memories\n4. .claude/memory/lessons.md ← read EVERY session — past mistakes not to repeat\n\n── 3 ENFORCEMENT RULES (PreToolUse hook BLOCKS violations) ─────────────────\nRULE 1 — WRITE GUARD:\n  Only Write/Edit inside SENA_AI/. Parent sena-mobile/ is READ-ONLY.\n  Absolute paths outside SENA_AI/ → hard block.\n\nRULE 2 — CONTEXT7 GATE (flag cleared — must re-fetch this session):\n  First .py write BLOCKED until Context7 live-doc fetch.\n  Steps: resolve-library-id → query-docs for EACH library → then implement.\n  Flag auto-sets on first Context7 MCP call. Verify with ls .claude/hooks-state/ctx7-session.flag.\n\nRULE 3 — GEMINI SKILL GATE (flag cleared — must re-invoke this session):\n  Any edit to gemini*/demo_live* files BLOCKED until Skill: gemini-live-api-dev invoked.\n  Flag auto-sets when Skill tool fires with gemini/vertex skill name.\n\n── INSTALLED SKILLS (invoke before touching related code) ──────────────────\n  gemini-live-api-dev     → Gemini Live API (streaming voice, send_realtime_input)\n  gemini-api-dev          → Gemini REST API (generate, embed, function calling)\n  gemini-interactions-api → Interaction patterns\n  vertex-ai-api-dev       → Vertex AI / Google Cloud AI\n\n── GEMINI LIVE (current patterns from CLAUDE.md) ───────────────────────────\n  Model: gemini-3.1-flash-live-preview\n  Audio: send_realtime_input(audio=types.Blob(data=raw, mime_type='audio/pcm;rate=16000'))\n  Receive: wrap session.receive() in while True loop\n  NEVER gate mic on _agent_speaking → silent VAD death after 2-4 turns\n  START_SENSITIVITY_LOW — HIGH fires on ambient noise between turns\n\n── NEVER READ ───────────────────────────────────────────────────────────────\n  /archive | .venv | .vscode | ndis_markdown_docs/"}}
JSON

exit 0
