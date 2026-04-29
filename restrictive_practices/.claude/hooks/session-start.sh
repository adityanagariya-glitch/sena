#!/usr/bin/env bash
# session-start.sh — SessionStart hook for restrictive_practices module
# Injects context from SESSION_START.md and TASKS.md so Claude always
# resumes with full awareness of past work and next steps.

set -uo pipefail

cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"RESTRICTIVE PRACTICES MODULE — SESSION RESUME PROTOCOL\n\n1. READ: .claude/SESSION_START.md — what was built last session + critical gotchas\n2. READ: .claude/tasks/TASKS.md — live task status (done / in-progress / backlog)\n\nKEY FACTS THIS SESSION:\n- All 7 pipeline steps implemented and verified end-to-end\n- Pipeline: triage(Flash) → rag(pgvector) → evaluator(Pro) → cross_check(SQL) → CaseNoteRun audit\n- NEXT: HTTP smoke test via uvicorn + curl, then real PDF ingestion\n- DB: docker-compose up -d from sena-ai/, port 5433\n- Models: gemini-2.5-flash (triage), gemini-2.5-pro (evaluator), gemini-embedding-2 (RAG)\n\nGOTCHAS (do NOT re-derive):\n- Use HALFVEC not HalfVector in mapped_column\n- json.loads(response.text) not response.parsed for gemini-2.5-x\n- LangGraph node names must not match TypedDict state keys (use _step suffix)\n- max_output_tokens=4096 minimum for evaluator\n\nBEFORE SESSION END: update .claude/tasks/TASKS.md with any status changes."}}
JSON

exit 0
