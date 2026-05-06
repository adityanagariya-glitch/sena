# Data Flow — NDIS Restrictive Practice Detection Pipeline

## Input → `to_text()` gateway

Two paths in, one path out:

```
FORM FIELDS submitted                    TRANSCRIPT submitted
──────────────────────                   ──────────────────────
{                                        {
  case_note_id: "...",                     case_note_id: "...",
  client_id: "...",                        client_id: "...",
  worker_id: "...",                        worker_id: "...",
  describe: "Shift at day centre",         transcript: "Hey it's Sarah,
  behavioural_events: "I held             I held Tom's wrists..."
    Tom's wrists...",                    }
  any_concerns: true,
  incident_occurred: true
}
         │                                        │
         ▼                                        ▼
   to_text() builds                        to_text() returns
   structured narrative:                   transcript as-is
   "Summary of Shift:                      (no transformation)
    Shift at day centre

    Well-being & Behaviour:
    Behavioural Events: I held
    Tom's wrists...
    Any Concerns: Yes

    Safety / Health Monitoring:
    ...
    Notes / Additional Comments:
    Did Any Incident Occur: Yes"
         │                                        │
         └──────────────┬───────────────────────--┘
                        │
                  plain text string
```

`to_text()` defined in `models/schemas.py` — `CaseNoteInput.to_text()`.

---

## Pipeline steps

```
plain text string
      │
      ▼
┌─────────────────────────────────────────────────────────┐
│ STEP 1 — triage  (gemini-3-flash, thinking_budget=0)    │
│                                                         │
│  Prompt injects text → asks: any restrictive practice?  │
│  Returns: { flagged: bool, action_summary: str|null }   │
└─────────────────────────────────────────────────────────┘
      │
      ├── flagged=False ──→  SKIP steps 2-4, write audit row, DONE
      │                      (~70% of notes, zero further LLM cost)
      │
      └── flagged=True ──→
            │
            ▼
┌─────────────────────────────────────────────────────────┐
│ STEP 2 — RAG  (pgvector, no LLM)                        │
│                                                         │
│  Embeds: triage.action_summary (1-sentence focus)       │
│          OR to_text() if action_summary is null         │
│  Queries: HNSW cosine index on rp_ndis_policy_chunks    │
│  Returns: top-5 PolicyChunk objects (NDIS policy text)  │
└─────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────┐
│ STEP 3 — evaluator  (gemini-3.1-pro, max_tokens=4096)   │
│                                                         │
│  Prompt injects:                                        │
│    - policy chunks (RAG context, grounding)             │
│    - to_text() (full note)                              │
│    - triage.action_summary (focus hint)                 │
│  Returns structured JSON:                               │
│    incident_detected, practice_category,                │
│    policy_violation_risk, reasoning,                    │
│    reporting_required, notification_timeframe           │
└─────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────┐
│ STEP 4 — cross_check  (SQL only, no LLM)                │
│                                                         │
│  Queries: behaviour_support_plans table                 │
│  Match: (client_id, practice_category) case-insensitive │
│         WHERE status='Active'                           │
│         AND (valid_until IS NULL OR valid_until > now)  │
│  Returns: authorisation_status, bsp_id, notes          │
└─────────────────────────────────────────────────────────┘
            │
            ▼
      audit row written to rp_case_note_runs
            │
            ├── alert_required=True → webhook POST (HMAC-signed)
            │
            ▼
         response
```

---

## Output shape (`POST /evaluate` response)

```json
{
  "verdict": {
    "outcome": "UNAUTHORISED RESTRICTIVE PRACTICE DETECTED",
    "risk_level": "High",
    "alert_required": true,
    "action_required": "IMMEDIATE ACTION: Notify the NDIS Quality and Safeguards Commission within 5 business days..."
  },

  "detected_practice": {
    "category": "Physical Restraint",
    "what_happened": "Worker applied prone hold for ~3 minutes",
    "reasoning": "Phrase 'guided him firmly to the floor into a prone position' constitutes physical restraint under NDIS Rules 2018..."
  },

  "authorisation": {
    "status": "Unauthorised Restrictive Practice",
    "behaviour_support_plan": {
      "on_file": false,
      "details": "No active Behaviour Support Plan found for this client and practice type."
    }
  },

  "reporting_obligations": {
    "must_report": true,
    "notify_within": "5 business days",
    "notify_authority": "NDIS Quality and Safeguards Commission",
    "guidance": "Under the NDIS (Restrictive Practices and Behaviour Support) Rules 2018..."
  },

  "submission": {
    "case_note_id": "a0000002-...",
    "client_id": "client-demo-unauth",
    "worker_id": "worker-daniel-002",
    "screening_result": "Flagged for detailed review",
    "screening_summary": "Worker applied prone hold on participant during behavioural episode"
  },

  "privacy": "Processed under APP 3 (Privacy Act 1988) as sensitive health information..."
}
```

`detected_practice` and `authorisation` are `null` when outcome is `CLEAR` or `NO INCIDENT DETECTED`.

---

## 4 verdict paths

```
triage flagged=False
  → outcome="CLEAR"
  → detected_practice=null, authorisation=null
  → alert_required=false

triage flagged=True + evaluator incident_detected=False
  → outcome="NO INCIDENT DETECTED"
  → detected_practice=null
  → alert_required=false

triage flagged=True + incident_detected=True + BSP found (Active, matching client+practice)
  → outcome="AUTHORISED USE — REVIEW RECOMMENDED"
  → alert_required=false

triage flagged=True + incident_detected=True + no BSP
  → outcome="UNAUTHORISED RESTRICTIVE PRACTICE DETECTED"
  → alert_required=true
  → webhook fires → platform backend notified
```

---

## Key files

| Concern | File |
|---------|------|
| Input model + `to_text()` | `models/schemas.py` |
| Pipeline wiring (LangGraph) | `pipeline/graph.py` |
| Triage prompt + Gemini call | `pipeline/triage.py` |
| RAG embedding + pgvector query | `pipeline/rag.py` |
| Evaluator prompt + Gemini call | `pipeline/evaluator.py` |
| BSP SQL lookup | `pipeline/cross_check.py` |
| Webhook fire | `pipeline/webhook.py` |
| API response builder | `api/routes.py` — `_build_response()` |
