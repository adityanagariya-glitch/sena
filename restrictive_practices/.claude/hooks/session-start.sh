#!/usr/bin/env bash
# session-start.sh — SessionStart hook for restrictive_practices module
# Injects context from SESSION_START.md, TASKS.md, and issues-solved INDEX.

set -uo pipefail

cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"RESTRICTIVE PRACTICES MODULE — SESSION RESUME PROTOCOL\n\n1. READ: .claude/SESSION_START.md — what was built last session + critical gotchas\n2. READ: .claude/tasks/TASKS.md — live task status (done / in-progress / backlog)\n3. ISSUES-SOLVED RULE: Before debugging ANY error, run:\n   grep -i \"<symptom keywords>\" .claude/issues-solved/INDEX.md\n   If match → read the linked file → apply fix directly. DO NOT re-derive.\n   If no match → solve it, then add a new entry to issues-solved/.\n\nKEY FACTS:\n- All 7 pipeline steps + webhook + privacy headers implemented and verified end-to-end\n- Pipeline: triage(Flash) → rag(pgvector) → evaluator(Flash fallback) → cross_check(SQL) → webhook → CaseNoteRun audit\n- Real NDIS PDFs ingested (~400+ chunks); demo BSPs seeded; DEMO.md has curl commands\n- DB: docker-compose up -d from restrictive_practices/, port 5433\n- Quick start: make demo-setup && make server\n- Models: gemini-2.5-flash (triage+evaluator fallback), gemini-embedding-001 (Vertex) or gemini-embedding-2 (AI Studio)\n\nGOTCHAS (full list in SESSION_START.md):\n- Use HALFVEC not HalfVector in mapped_column\n- json.loads(response.text) not response.parsed for gemini-2.5-x\n- LangGraph node names must not match TypedDict state keys (use _step suffix)\n- max_output_tokens=4096 minimum for evaluator\n- google-genai>=1.74.0 required for thinking_budget\n- Ingest+query embedding models must match — see config.py for current model\n\nBEFORE SESSION END: update .claude/tasks/TASKS.md + add any new issues to .claude/issues-solved/."}}
JSON

exit 0
