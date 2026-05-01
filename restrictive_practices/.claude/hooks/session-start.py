"""SessionStart hook — injects SESSION_START.md + TASKS.md context."""
import json, sys

payload = {
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": (
            "RESTRICTIVE PRACTICES MODULE — SESSION RESUME PROTOCOL\n\n"
            "1. READ: .claude/SESSION_START.md — what was built last session + critical gotchas\n"
            "2. READ: .claude/tasks/TASKS.md — live task status (done / in-progress / backlog)\n"
            "3. ISSUES-SOLVED RULE: grep .claude/issues-solved/INDEX.md BEFORE debugging anything.\n\n"
            "KEY FACTS:\n"
            "- All 7 pipeline steps + webhook + privacy headers implemented and verified end-to-end\n"
            "- Pipeline: triage(Flash) → rag(pgvector) → evaluator(Pro) → cross_check(SQL) → CaseNoteRun audit\n"
            "- Real NDIS PDFs ingested (~400+ chunks); demo BSPs seeded; DEMO.md has curl commands\n"
            "- DB: docker-compose up -d from restrictive_practices/, port 5433\n"
            "- Quick start: make demo-setup && make server\n"
            "- Models: gemini-3-flash-preview (triage), gemini-3.1-pro-preview (evaluator)\n\n"
            "GOTCHAS (do NOT re-derive):\n"
            "- Use HALFVEC not HalfVector in mapped_column\n"
            "- json.loads(response.text) not response.parsed (applies to ALL gemini-2.x and gemini-3.x)\n"
            "- LangGraph node names must not match TypedDict state keys (use _step suffix)\n"
            "- max_output_tokens=4096 minimum for evaluator\n"
            "- google-genai>=1.74.0 required for thinking_budget\n"
            "- Ingest+query embedding models must match — see config.py for current model\n\n"
            "BEFORE SESSION END: update .claude/tasks/TASKS.md + add any new issues to .claude/issues-solved/."
        ),
    }
}
print(json.dumps(payload))
sys.exit(0)
