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
  behavioural_events: "Staff held          I held Tom's wrists..."
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
    Behavioural Events: Staff held
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

## Pipeline topology

```
plain text string
      │
      ▼
┌─────────────────────────────────────────────────────────────────┐
│ STEP 1 — triage  (Claude Haiku, Bedrock converse, maxTokens=512) │
│                                                                 │
│  Prompt: FEW_SHOT_TRIAGE + note text                            │
│  Returns: { flagged: bool, action_summary: str|null }           │
└─────────────────────────────────────────────────────────────────┘
      │
      ├── flagged=False ──────────────────────────────────────────┐
      │                                                           │
      └── flagged=True ──→                                        │
            │                                                     │
            ▼                                                     │
┌─────────────────────────────────────────────────────────────┐   │
│ STEP 2 — RAG  (pgvector HNSW, Cohere embed, no LLM)         │   │
│                                                             │   │
│  Embeds: triage.action_summary (1-sentence focus)           │   │
│          OR to_text() if action_summary is null             │   │
│  Queries: HNSW cosine on rp_ndis_policy_chunks              │   │
│           document_type = "Regulatory" (policy chunks)      │   │
│  Returns: top-K PolicyChunk objects                         │   │
└─────────────────────────────────────────────────────────────┘   │
            │                                                     │
            ▼                                                     │
┌─────────────────────────────────────────────────────────────┐   │
│ STEP 3 — evaluator  (Claude Sonnet, maxTokens=8192)         │   │
│                                                             │   │
│  Prompt: STYLE_GUIDE + FEW_SHOT_EVAL_REASONING              │   │
│          + policy chunks (RAG context)                      │   │
│          + to_text() (full note)                            │   │
│          + triage.action_summary (focus hint)               │   │
│  Returns: incident_detected, practice_category,             │   │
│           policy_violation_risk, confidence, reasoning,     │   │
│           trigger_phrases, suppression_factors,             │   │
│           bsp_mentioned_in_note, reporting_required,        │   │
│           notification_timeframe                            │   │
└─────────────────────────────────────────────────────────────┘   │
            │                                                     │
            ▼                                                     │
┌─────────────────────────────────────────────────────────────┐   │
│ STEP 4 — cross_check  (SQL only, no LLM)                    │   │
│                                                             │   │
│  Queries: behaviour_support_plans table                     │   │
│  Match: (client_id, practice_category) case-insensitive     │   │
│         WHERE status='Active'                               │   │
│         AND (valid_until IS NULL OR valid_until > now)      │   │
│  Returns: authorisation_status, bsp_id, notes               │   │
└─────────────────────────────────────────────────────────────┘   │
            │                                                     │
            └──────────────────────┬──────────────────────────────┘
                                   │  (both paths converge here)
                                   ▼
┌─────────────────────────────────────────────────────────────────┐
│ STEP 5 — summary  (Claude Haiku, Bedrock converse, maxTokens=1024)│
│                                                                 │
│  Always runs — every note gets a summary.                       │
│  Prompt: STYLE_GUIDE + FEW_SHOT_SUMMARY + note text             │
│  Heuristic quality scorer (zero LLM cost):                      │
│    score_note() → note_quality_score, label, gaps               │
│  Returns: SummaryOutput                                         │
│    progress_identified, potential_risks, patterns_detected,     │
│    flagged_highlights, ai_confidence,                           │
│    note_quality_score (0.0–1.0), note_quality_label,            │
│    quality_gaps (actionable suggestions for the worker)         │
└─────────────────────────────────────────────────────────────────┘
                                   │
         ┌─── incident_occurred=True OR UNAUTHORISED verdict? ────┐
         │                                                        │
         │ YES                                                    │ NO
         ▼                                                        ▼
┌──────────────────────────────────────────────┐            write audit row
│ STEP 6 — incident_draft                      │            → END
│ (Claude Sonnet, Bedrock converse,            │
│  maxTokens=4096, conditional only)           │
│                                              │
│  Prompt: STYLE_GUIDE + FEW_SHOT_INCIDENT     │
│          + NDIS reportable-incident rules    │
│          + case note text                    │
│          + evaluator findings (if present)   │
│  Returns: IncidentDraftOutput                │
│    incident_type, incident_description,      │
│    immediate_actions_taken, compliance_checks│
│    reportable, notification_timeframe        │
│    severity (Low/Medium/High/Critical)       │
│    incident_categories (multi-select)        │
│    ongoing_risk_present, participant_safe,   │
│    staff_safe, emergency_services_required   │
└──────────────────────────────────────────────┘
         │
         ▼
   write audit row to rp_case_note_runs
         │
         ├── alert_required=True → webhook POST (HMAC-signed)
         │
         ▼
      response
```

---

## POST /draft (stateless, no pipeline)

```
DraftInput { transcript, worker_id, client_id, shift_date, shift_time, worker_position }
      │
      ▼
┌─────────────────────────────────────────────────────────────────────┐
│ drafter  (Claude Sonnet, Bedrock converse, maxTokens=4096)          │
│                                                                     │
│  Prompt: STYLE_GUIDE + FEW_SHOT_DRAFTER (field-description guide   │
│          + Premium/Poor contrast) + transcript                      │
│  Extracts: all 6 form sections from the voice transcript            │
│  After extraction: score_note() runs quality heuristic              │
│  Returns: CaseDraftResponse                                         │
│    all 6 form sections + draft_note (gap detection)                 │
│    transcript (pass-through for /evaluate round-trip)               │
│    note_quality_score, note_quality_label, quality_gaps             │
└─────────────────────────────────────────────────────────────────────┘
      │
      ▼
Worker reviews → edits → submits to POST /evaluate
```

---

## Output shape (`POST /evaluate` response)

```json
{
  "verdict": {
    "outcome": "UNAUTHORISED RESTRICTIVE PRACTICE DETECTED",
    "risk_level": "High",
    "alert_required": true,
    "action_required": "IMMEDIATE ACTION: Notify the NDIS Quality and Safeguards Commission within 5 business days...",
    "next_steps": ["Notify NDIS Commission within 5 business days", "..."]
  },

  "detected_practice": {
    "category": "Physical Restraint",
    "what_happened": "Worker applied hold on participant during behavioural episode",
    "reasoning": "Phrase 'held participant by both arms' constitutes physical restraint under NDIS Rules 2018...",
    "trigger_phrases": ["held participant by both arms", "held the door closed"],
    "suppression_factors": []
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
    "case_note_id": "...",
    "client_id": "client-demo-001",
    "worker_id": "worker-001",
    "screening_result": "Flagged for detailed review",
    "screening_summary": "Staff physically restrained participant during behavioural episode"
  },

  "summary": {
    "ai_confidence": 0.87,
    "confidence_label": "High",
    "progress_identified": ["Participant demonstrated..."],
    "potential_risks": ["Ongoing escalation risk without BSP in place"],
    "patterns_detected": ["Repeated physical intervention without authorisation"],
    "flagged_highlights": ["held participant by both arms and guided him inside the room"],
    "note_quality_score": 0.68,
    "note_quality_label": "Average",
    "quality_gaps": ["Section 2 (Observations) is brief - add specific observable details"]
  },

  "incident_report": {
    "incident_type": "Unauthorised Restrictive Practice",
    "date_of_incident": "14 May 2026",
    "time_of_incident": "2:00 PM - 6:00 PM",
    "location": null,
    "staff_involved": ["worker-dave-002"],
    "incident_description": "Participant refused to enter the house and became physically aggressive. Support worker held participant by both arms to guide him inside and held the door closed from outside until he calmed. No behaviour support plan was in place.",
    "immediate_actions_taken": ["Physical de-escalation applied", "Participant guided inside", "Incident documented"],
    "restrictive_practice_used": true,
    "restrictive_practice_category": "Physical Restraint",
    "risk_assessment": "Immediate risk: High",
    "contributing_factors": ["No BSP in place", "Participant refusal to enter"],
    "follow_up_actions": ["Develop urgent BSP", "Debrief worker", "Notify NDIS Commission"],
    "compliance_checks": [
      {"label": "Incident documented within required timeframe", "passed": true},
      {"label": "Restrictive practice authorisation verified", "passed": false}
    ],
    "reportable": true,
    "notification_timeframe": "5 business days",
    "notification_authority": "NDIS Quality and Safeguards Commission",
    "severity": "High",
    "incident_categories": ["Restrictive practice", "Behavioural incident"],
    "ongoing_risk_present": true,
    "participant_currently_safe": true,
    "staff_currently_safe": true,
    "emergency_services_required": false
  },

  "privacy": "Processed under APP 3 (Privacy Act 1988) as sensitive health information..."
}
```

`detected_practice`, `authorisation`, and `incident_report` are `null` when not applicable.

---

## Verdict paths (6 outcomes)

```
triage flagged=False
  → outcome="CLEAR"
  → detected_practice=null, authorisation=null, incident_report=null
  → alert_required=false
  → summary ALWAYS populated

triage flagged=True + evaluator incident_detected=False OR confidence=LOW
  → outcome="NO INCIDENT DETECTED"
  → detected_practice=null
  → alert_required=false

triage flagged=True + incident_detected=True + BSP on file (active, matching client+practice)
  → outcome="AUTHORISED USE — REVIEW RECOMMENDED"
  → alert_required=false

triage flagged=True + incident_detected=True + bsp_mentioned_in_note=True + no DB record
  → outcome="ADMINISTRATIVE REVIEW REQUIRED — BSP reference but no DB match"
  → alert_required=false

triage flagged=True + incident_detected=True + confidence=MEDIUM + no BSP
  → outcome="POSSIBLE RESTRICTIVE PRACTICE — ADMINISTRATIVE REVIEW"
  → alert_required=false

triage flagged=True + incident_detected=True + confidence=HIGH + no BSP
  → outcome="UNAUTHORISED RESTRICTIVE PRACTICE DETECTED"
  → alert_required=true
  → webhook fires → platform backend notified
  → incident_report populated (STEP 6 triggered)
```

---

## Incident draft trigger logic

```python
worker_flagged   = note.incident_occurred
pipeline_flagged = (
    evaluator.incident_detected
    and evaluator.confidence != LOW
    and cross_check.authorisation_status == UNAUTHORISED
)
run_incident_draft = worker_flagged or pipeline_flagged
```

NDIS reportable incident notification timeframes (authoritative in the prompt):
- **24 hours** — death, serious injury, abuse/neglect, unlawful contact/assault, sexual misconduct
- **5 business days** — unauthorised use of a regulated restrictive practice (no BSP/authorisation)

---

## Gold-standard prompt architecture

All 5 LLM prompts share the same style foundation from `pipeline/style_examples.py`:

```
pipeline/style_examples.py  ←  single source of truth
        │
        ├── STYLE_GUIDE         →  all 5 prompts  (third-person clinical register)
        ├── FEW_SHOT_TRIAGE     →  triage.py      (clean + RP contrast)
        ├── FEW_SHOT_SUMMARY    →  summary.py     (Premium bullet examples)
        ├── FEW_SHOT_DRAFTER    →  drafter.py     (field guidance + Premium/Poor contrast)
        ├── FEW_SHOT_INCIDENT   →  incident_draft.py  (Verbal Escalation report example)
        └── FEW_SHOT_EVAL_REASONING → evaluator.py (clinical citation style)
```

Style RAG (optional, supplements inline few-shots):
```
retrieve_style_chunks(query, document_type, db, top_k)
  document_type = "Casenote Style Standard"     → for summary.py
  document_type = "Field Description Standard"  → for drafter.py
  document_type = "Incident Report Standard"    → for incident_draft.py
```

---

## Key files

| Concern | File |
|---------|------|
| Input model + `to_text()` | `models/schemas.py` |
| Pipeline wiring (LangGraph) | `pipeline/graph.py` |
| Triage prompt + Bedrock call | `pipeline/triage.py` |
| RAG embedding + pgvector query | `pipeline/rag.py` |
| Evaluator prompt + Bedrock call | `pipeline/evaluator.py` |
| BSP SQL lookup | `pipeline/cross_check.py` |
| Shift summariser + quality scorer wiring | `pipeline/summary.py` |
| Incident report drafter | `pipeline/incident_draft.py` |
| Voice transcript → form fields | `pipeline/drafter.py` |
| Style few-shots (single source of truth) | `pipeline/style_examples.py` |
| Heuristic quality scorer | `pipeline/quality_score.py` |
| Webhook fire | `pipeline/webhook.py` |
| API response builder | `api/routes.py` — `_build_response()` |
| Gold-standard chunk ingest | `scripts/ingest_style_standards.py` |
