# Case Review API Reference

## Endpoint 1: POST `/v1/case-review/context` — Rolling Case-Note Summary

**Purpose:** Pre-meeting brief for staff. Fetches recent case notes and compresses them into a concise summary.

### Request

```json
{
  "staff_id": "30d4f882-93d0-4c5d-9af6-22612908817e",
  "client_id": "dab57916-9863-4b49-ba39-92441547ba5b",
  "limit": 10
}
```

### Flow

**Step 1: Fetch notes** (JWT-scoped org backend `/mobile` endpoints)

```
Note 1 (June 15): 
  transcript: "Meal prep, community access, participant cooperative"

Note 2 (June 10): 
  transcript: "Physiotherapy, mild pain, used mobility aids"

Note 3 (June 5): 
  transcript: "Shopping, social anxiety expressed, reassurance helped"
```

**Step 2: Check cache** (Replay guard — avoid double-processing)

```
Existing summary from June 5:
"Participant engaged in community activities (shopping, meals). 
Physiotherapy ongoing. Mild social anxiety noted — responds to reassurance."

New notes since June 5: Note 1 + Note 2 (June 10, 15)
→ Yes, new notes detected. Compress old + add new.
```

**Step 3: Call LLM** (Claude Haiku via Bedrock)

- **Input:** Past summary + New notes (formatted)
- **Task:** Compress into 150-300 words; extract goals, progress, patterns, strategies, incidents, risks
- **Model:** `au.anthropic.claude-haiku-4-5-20251001-v1:0` (summarizer_model)

### Response

```json
{
  "summary_text": "Participant has been actively engaged in community and 
    functional activities. Over the past two weeks, participated in meal 
    preparation and community access (shopping, outdoor outings). 
    Physiotherapy continuing with mild pain managed via mobility aids. 
    Social anxiety patterns noted in earlier sessions; participant responds 
    well to reassurance and staff presence. No significant incidents reported. 
    Support strategies focus on community engagement and independence building.",
  "metadata": {
    "note_count": 3,
    "last_dates": ["2024-06-15", "2024-06-10", "2024-06-05"],
    "incident_count": 0,
    "risk_flags": ["social_anxiety_mild"]
  },
  "rolling_summary_id": "uuid",
  "notes_included": 3
}
```

### Caching

- **Hit:** No new notes since last fetch → returns cached summary (~10ms)
- **Miss:** New notes detected → calls LLM, stores result, returns (~2-3s)
- **Key:** (tenant_id, staff_id, client_id) + processed_note_ids

### Auth

- **Type:** JWT Bearer
- **Header:** `Authorization: Bearer <JWT>`
- **Scoped to:** Calling staff member (notes fetched are member-scoped)

---

## Endpoint 2: POST `/v1/case-review/classify` — Extract Structured Fields

**Purpose:** Staff writes rough free-text paragraph. System extracts structured fields and flags missing required information.

### Request

```json
{
  "staff_id": "30d4f882-93d0-4c5d-9af6-22612908817e",
  "client_id": "dab57916-9863-4b49-ba39-92441547ba5b",
  "raw_paragraph": "Had a good session with John today. We went shopping at 
    Coles and he paid for items himself at the checkout. Was a bit anxious 
    in the crowd but managed it with some breathing exercises I taught him. 
    He seemed happy afterwards. Didn't mention any injuries or concerns."
}
```

### Flow

**Step 1: Call LLM** (Claude Haiku via Bedrock with tool use)

- **Input:** Raw paragraph + Field schema (25 fields)
- **Task:** Extract values for each field; identify missing required fields
- **Model:** `au.anthropic.claude-haiku-4-5-20251001-v1:0` (classifier_model)

**Step 2: Extract & Validate**

Fields in schema:
- `describe` (required): What activities?
- `mood` (required): Emotional state?
- `behavioural_events` (optional): Any incidents?
- `safety_hazards_observed` (optional): Yes/No?
- `any_injuries` (optional): Injuries?
- `medication_reminders_given` (optional): Med management?
- [15+ more fields...]

### Response

```json
{
  "classified_fields": {
    "describe": "John attended shopping at Coles and independently managed 
      checkout transactions with support. Demonstrated anxiety management 
      techniques (breathing exercises) in crowded environments.",
    "mood": "Happy, positive throughout session",
    "behavioural_events": null,
    "safety_hazards_observed": false,
    "any_injuries": false,
    "injury_description": null,
    "what_went_well": "John managed anxiety independently using taught coping 
      strategies. Positive mood post-activity.",
    "what_needs_further_support": null,
    "medication_reminders_given": null,
    "carer_feedback": null
  },
  "confidence": {
    "describe": 0.95,
    "mood": 0.90,
    "behavioural_events": 0.85,
    "what_went_well": 0.92,
    "medication_reminders_given": 0.0
  },
  "missing_required": [
    "observed_safety_hazards",
    "behavioural_baseline"
  ],
  "reask_prompts": [
    {
      "field_id": "observed_safety_hazards",
      "label": "Safety Hazards",
      "reason": "Your note doesn't mention whether any safety hazards were 
        observed during the session.",
      "suggested_question": "Did you notice any safety hazards during shopping 
        (e.g., wet floors, crowding, unsafe handling of items)?"
    },
    {
      "field_id": "behavioural_baseline",
      "label": "Behaviour Baseline",
      "reason": "No baseline behaviour description provided to compare current 
        behaviour against.",
      "suggested_question": "How was John's behaviour today compared to his 
        usual? Any changes from what you normally see?"
    }
  ]
}
```

### Staff Workflow

1. **Review extracted fields** ✓ (describe, mood, progress populated)
2. **Answer re-ask prompts** (staff fills in missing required fields)
3. **Submit for review** → Triggers `/review` pipeline

### Confidence Scoring

- **0.9–1.0:** Explicitly stated in paragraph
- **0.5–0.8:** Reasonable inference from context
- **Below 0.5:** Unreliable — flagged as missing
- **0.0:** No evidence in paragraph

### Auth

- **Type:** JWT Bearer
- **Header:** `Authorization: Bearer <JWT>`

---

## Comparison

| Aspect | `/context` | `/classify` |
|--------|-----------|-----------|
| **Input** | Multiple case notes | Single free-text paragraph |
| **Output** | Pre-meeting brief (prose) | Structured fields + missing list |
| **LLM Task** | Compress + summarize | Extract + validate |
| **Use Case** | Before client meeting | After staff writes rough note |
| **Caching** | Yes (per staff-client pair) | No (per request) |
| **Response Time** | 10ms (cache) / 2-3s (miss) | ~1-2s |
| **Model** | Haiku (summarizer) | Haiku (classifier) |

---

## Architecture Notes

### Case-Note Fetching (`/context`)

1. **Member-scoped discovery:** `GET /mobile/organization-member/case-note/get-all-data`
   - Returns: `{ items: [{shiftId, clientId, startTime, ...}] }`
2. **Concurrent content fetch:** `GET /mobile/organization-member/case-note/get-data/{shiftId}/{clientId}`
   - Returns: Full structured note with sections (Activities, Wellbeing, Outcomes, Safety, Feedback, Handover)
3. **Compose into text:** Structured sections flattened into readable prose for LLM
4. **LLM summary:** Past summary + new notes → rolling brief

### Field Extraction (`/classify`)

1. **Paragraph input:** Free-text from staff
2. **Field schema:** 25+ fields (required + optional)
3. **Tool use:** Claude enforces JSON schema via Bedrock tool calling
4. **Confidence scoring:** Each field gets 0.0–1.0 confidence
5. **Re-ask logic:** Missing required fields → conversational prompts
6. **Persistence:** Classified fields stored in review_session

---

## Error Handling

### `/context`
- **No notes:** Returns empty summary + metadata
- **API timeout:** Logs warning, returns cached if available, else 504
- **LLM error:** Logs error, returns 500

### `/classify`
- **Empty paragraph:** Returns error (400)
- **LLM tool use error:** Retries, logs, returns 500 if persistent
- **Invalid schema:** Returns 422 (unprocessable)

---

## Future Enhancements

- Real-time streaming summaries (WebSocket)
- Custom field schema per organization
- Confidence-based re-ask filtering (only low-confidence fields)
- Multi-language support (currently AU English)
- Incident auto-detection from extracted fields

---

## Performance & Costs (Endpoints 1-2)


### Cost Breakdown (/context & /classify)

| Endpoint | LLM | Tokens | Latency | Cost / 1M Tokens | Est. Cost / Req |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`/context`** | Haiku | 800-1500 | 2-3s | $0.08 | $0.00006 - $0.00012 |
| **`/classify`** | Haiku | 1200-2000 | 1-2s | $0.08 | $0.00010 - $0.00016 |

---

## Endpoint 3: POST `/v1/case-review/review` — Risk & Compliance Analysis

**Purpose:** Analyze classified case note for restrictive practices, NDIS compliance flags, and risk indicators.

### Request

```json
{
  "review_session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Flow

**Step 1: Load review session**
- Must have `raw_paragraph` or `classified_fields` populated (from `/classify`)

**Step 2: Triage** (cheap Haiku gate)
- **Model:** `au.anthropic.claude-haiku-4-5-20251001-v1:0`
- **Input:** Case note text
- **Output:** `flagged: bool` (signals for potential RP?)
- **Cost:** ~500 tokens, ~400ms

**Step 3: If flagged → Evaluator** (Claude Sonnet deep dive)
- **Model:** `au.anthropic.claude-sonnet-4-6`
- **Input:** Full case note + triage signal
- **Output:** Structured verdict with practice category, confidence, reporting requirement
- **Cost:** ~2000 tokens, ~2-3s

**Step 4: Map to FlagItems**
- Extract: risks, restrictive_practices, anomalies, improvements
- Add NDIS references (Rules 2018, etc.)
- Determine severity (low | medium | high | critical)

**Step 5: Persist & Return**
- Update review_session (status → "reviewed")
- Append audit log
- Return structured flags

### Response

```json
{
  "review_session_id": "550e8400-e29b-41d4-a716-446655440000",
  "risks": [
    {
      "category": "Mandatory Reporting Required",
      "description": "Incident must be reported to the NDIS Quality and 
        Safeguards Commission within 24 hours.",
      "severity": "critical",
      "ndis_reference": "NDIS (Incident Management and Reportable Incidents) 
        Rules 2016 — Category 1 (24 hours)"
    }
  ],
  "restrictive_practices": [
    {
      "category": "Physical Restraint",
      "description": "Staff applied physical hold to prevent participant from 
        leaving building without permission. Duration ~5 minutes.",
      "severity": "high",
      "ndis_reference": "NDIS (Restrictive Practices and Behaviour Support) 
        Rules 2018"
    }
  ],
  "anomalies": [
    {
      "category": "Unusual Language",
      "description": "Staff used term 'locked in' describing evening routine, 
        which may indicate unauthorized restriction.",
      "severity": "medium",
      "ndis_reference": null
    }
  ],
  "improvements": [
    {
      "category": "Documentation",
      "description": "Note was well-structured and detailed. Clear reasoning 
        provided for interventions.",
      "severity": "low",
      "ndis_reference": null
    }
  ],
  "status": "reviewed"
}
```

### Pipeline Decision Tree

```
Triage gates?
  ├─ NO → flags: ["compliant"], status: reviewed ✓
  └─ YES → Evaluator analysis
       ├─ incident_detected?
       │  ├─ NO → flags: ["no_violation"], status: reviewed ✓
       │  └─ YES → practice_category found?
       │     ├─ NO → flags: ["ambiguous"], status: reviewed_requires_escalation
       │     └─ YES → reporting_required?
       │        ├─ NO → flags: ["authorized_use"], status: reviewed ✓
       │        └─ YES → severity + timeframe assigned
       │           → flags: ["must_report_24h"] or ["must_report_5_days"]
       │           → status: reviewed_reportable
       └─ Error? → status: review_failed, error logged
```

### Auth

- **Type:** JWT Bearer
- **Header:** `Authorization: Bearer <JWT>`

---

## Endpoint 4: POST `/v1/case-review/incident/detect` — Detect Reportable Incidents

**Purpose:** Determine if case note describes an incident meeting NDIS reporting thresholds. Creates placeholder for drafting if yes.

### Request

```json
{
  "review_session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Flow

**Step 1: Load review session** (must exist)

**Step 2: Triage** (cheap gate)
- Not flagged? → `incident_detected: false`, return empty

**Step 3: Evaluator** (confirm + extract markers)
- **Input:** Case note
- **Output:** `incident_detected: bool`, `practice_category`, `trigger_phrases`

**Step 4: If detected → Create draft placeholder**
- Creates `IncidentDraft` row with empty fields
- Stores `autofill_source` metadata
- Returns draft ID for `/draft` step

**Step 5: Append audit log**

### Response

```json
{
  "review_session_id": "550e8400-e29b-41d4-a716-446655440000",
  "incident_detected": true,
  "incident_draft_id": "660f9511-e39c-42e5-b827-557744441111",
  "markers": [
    "staff applied physical hold",
    "participant crying and distressed",
    "duration approximately 5 minutes",
    "no documented behaviour support plan"
  ]
}
```

### When called after `/review`

If `/review` already ran and populated flags, `/detect` is idempotent:
- Re-running with same session returns cached result
- Avoids duplicate LLM calls

### Auth

- **Type:** JWT Bearer
- **Header:** `Authorization: Bearer <JWT>`

---

## Endpoint 5: POST `/v1/case-review/incident/draft` — Autofill Incident Report

**Purpose:** Run NDIS incident drafter LLM to populate 20+ incident report fields from case note. Staff must review + confirm before submission.

### Request

```json
{
  "review_session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Flow

**Step 1: Load review session + existing draft (if any)**

**Step 2: Build case note input**
- Source: `raw_paragraph` OR `classified_fields` (auto-composed)
- Fail if both empty (422)

**Step 3: Run incident drafter** (Claude Sonnet via Bedrock)
- **Model:** `au.anthropic.claude-sonnet-4-6`
- **Input:** Case note + NDIS incident report schema
- **Output:** 20+ fields auto-filled (incident_type, date, location, staff_involved, description, risk_assessment, reporting_status, notification_timeframe, severity, etc.)
- **Reasoning:** Full Sonnet reasoning for complex incident analysis
- **Cost:** ~3000 tokens, ~3-4s

**Step 4: Persist draft**
- Creates or overwrites `IncidentDraft` row
- Stores `draft_fields` (populated) + `autofill_source` (metadata)
- Sets status → `draft`

**Step 5: Return for review**

### Response

```json
{
  "incident_draft_id": "660f9511-e39c-42e5-b827-557744441111",
  "draft_fields": {
    "incident_type": "Unauthorized restrictive practice — physical restraint",
    "date_of_incident": "2024-06-20",
    "time_of_incident": "15:30",
    "location": "Group home, Acacia Lane, suburb",
    "staff_involved": "Sarah Johnson (Support Worker), John Lee (Supervisor)",
    "incident_description": "Staff member (Sarah) applied physical hold to 
      participant's arm to prevent departure from building. Hold lasted 
      approximately 5 minutes. Participant was crying and distressed. No prior 
      behaviour support plan documented for this intervention.",
    "immediate_actions_taken": "Supervisor (John) arrived and de-escalated. 
      Participant calmed within 2 minutes of release. No injuries observed.",
    "restrictive_practice_used": "Physical restraint — arm hold",
    "restrictive_practice_category": "Regulated Restrictive Practice",
    "risk_assessment": "HIGH RISK. Unauthorized use of physical restraint. No 
      documented BSP authorization. Incident meets Category 1 reporting threshold.",
    "contributing_factors": "Lack of behaviour support plan. Staff may not have 
      received training on de-escalation alternatives.",
    "follow_up_actions": [
      "Notify NDIS Commission within 24 hours",
      "Conduct incident review with all staff",
      "Develop behaviour support plan if not existing",
      "Provide de-escalation training"
    ],
    "compliance_checks": "Fails — unauthorized use without BSP authorization",
    "reportable": true,
    "notification_timeframe": "24 hours",
    "notification_authority": "NDIS Quality and Safeguards Commission",
    "severity": "High",
    "incident_categories": ["Unauthorized restrictive practice", "Safeguarding"],
    "ongoing_risk_present": true,
    "participant_currently_safe": true,
    "staff_currently_safe": true,
    "emergency_services_required": false
  },
  "autofill_source": {
    "source": "drafter",
    "model": "au.anthropic.claude-sonnet-4-6",
    "triage_flagged": true,
    "practice_category": "Physical Restraint"
  },
  "status": "draft"
}
```

### Staff Workflow

1. **Review auto-filled fields** in UI
2. **Edit fields** as needed (e.g., correct dates, add details)
3. **Confirm** → Moves to `/incident/{id}/confirm` step

### Auth

- **Type:** JWT Bearer
- **Header:** `Authorization: Bearer <JWT>`

---

## Endpoint 6: PATCH `/v1/case-review/incident/{incident_id}/confirm` — Staff Confirms Draft

**Purpose:** Staff explicitly signs off on AI-drafted incident report. NDIS non-negotiable: no auto-submit without human sign-off.

### Request

```
PATCH /v1/case-review/incident/660f9511-e39c-42e5-b827-557744441111/confirm
```

**No body required** — confirmation is the action itself.

### Flow

**Step 1: Load IncidentDraft**
- Fail 404 if not found

**Step 2: Update status**
- `status: draft` → `status: confirmed`
- `staff_confirmed: true`
- `confirmed_at: now()`
- `confirmed_by_user_id: auth.user_id`

**Step 3: Append audit log**
- Action: `incident_confirmed`
- Payload: `{ incident_draft_id, confirmed_by }`

**Step 4: Ready for `/submit`**

### Response

```json
{
  "incident_draft_id": "660f9511-e39c-42e5-b827-557744441111",
  "status": "confirmed",
  "staff_confirmed": true
}
```

### Idempotence

- Calling `/confirm` twice on same draft is safe
- Second call returns 200 with same response (no state change if already confirmed)

### Auth

- **Type:** JWT Bearer
- **Header:** `Authorization: Bearer <JWT>`
- **Role check:** Supervisor/Manager only (not all staff)

---

## Incident Workflow Summary

```
POST /classify
    ↓ (staff fills gaps)
POST /review
    ├─ Triage + Evaluator pipeline
    ├─ Flags: risks, RP, anomalies, improvements
    └─ Sets incident_detected on session
        ↓
POST /incident/detect
    ├─ Confirms incident_detected
    └─ Creates IncidentDraft placeholder
        ↓
POST /incident/draft
    ├─ Runs Sonnet drafter
    ├─ Populates 20+ incident fields
    └─ Stores draft (status: draft)
        ↓
        ↓ (staff reviews + edits in UI)
        ↓
PATCH /incident/{id}/confirm
    ├─ Staff explicitly confirms
    └─ status: confirmed, ready for submission
        ↓
POST /submit
    ├─ Persists SubmissionRecord (snapshot of case note + flags)
    ├─ Updates review_session status → submitted
    ├─ Routes confirmed incident for incident submission
    └─ Returns submission confirmation with timestamp
```

### Key Principles

- **Mandatory human sign-off** — No AI auto-submission of incident reports
- **Idempotent detect + draft** — Safe to re-run without duplicate LLM calls
- **Audit trail** — All actions logged with timestamps + actor user ID
- **Scoped to NDIS rules** — Categories, timeframes, reporting thresholds follow NDIS 2018 + 2016 regulations
- **Evidence preservation** — Trigger phrases + extracted markers stored for compliance

---

## Complete Workflow: From Raw Paragraph to Confirmed Incident

```
Staff writes: "Had a good session. We went shopping. 
John was anxious but used breathing techniques."

                    ↓ POST /classify
        
Extracts: { describe, mood, safety, incident_occurred, ... }
Missing: { observed_safety_hazards, behaviour_baseline }
        
                ↓ (staff fills gaps)
                
        ↓ POST /review
        
Triage: not flagged → "compliant, no risks"
Status: reviewed ✓
        
                ↓ no incident detected
                
        ↓ POST /incident/detect
        
incident_detected: false
Response: no draft created
Done ✓

---

ALTERNATE: More Serious Scenario
---

Staff writes: "John was having a bad day. 
We had to restrain him in the office for 20 minutes 
because he wouldn't calm down. He was hitting walls."

                    ↓ POST /classify
        
Extracts: { describe, mood, incident_occurred: true, ... }
        
                ↓ POST /review
        
Triage: FLAGGED → Evaluator runs
Evaluator: incident_detected=true, practice_category="Physical Restraint"
Flags: 
  - risks: ["Mandatory Reporting Required — 24 hours"]
  - restrictive_practices: ["Physical Restraint"]
  - anomalies: ["Extended duration 20 minutes"]
Status: reviewed_reportable
        
                ↓ POST /incident/detect
        
incident_detected: true
Creates: IncidentDraft (empty fields, autofill_source metadata)
Returns: incident_draft_id
        
                ↓ POST /incident/draft
        
Runs Sonnet drafter
Populates:
  - incident_type, date, time, location
  - staff_involved, incident_description
  - risk_assessment, contributing_factors
  - notification_timeframe: "24 hours"
  - reporting_status: "Reportable"
Status: draft
        
        ↓ (staff reviews auto-filled fields in UI, makes edits)
        
        ↓ PATCH /incident/{id}/confirm
        
Staff confirms (signature, timestamp)
Status: confirmed, staff_confirmed: true
        
        ↓ (ready for POST /submit)
        
POST /submit
  ├─ Validates review_session status (must be reviewed/reportable/escalation)
  ├─ Creates SubmissionRecord (immutable snapshot)
  ├─ Updates review_session → submitted
  ├─ Audits submission action
  ├─ If incident confirmed → routes for incident submission
  └─ Returns submission confirmation + timestamp
```

---

## Endpoint 7: POST `/v1/case-review/submit` — Final Submit Gate

**Purpose:** Staff submits reviewed case note. Persists submission snapshot and routes incident if confirmed.

### Request

```json
{
  "review_session_id": "550e8400-e29b-41d4-a716-446655440000",
  "actor_user_id": "30d4f882-93d0-4c5d-9af6-22612908817e"
}
```

### Flow

**Step 1: Load & validate review session**
- Must exist
- Status must be one of: `reviewed`, `reviewed_reportable`, `reviewed_requires_escalation`
- Fail 404 if not found, 400 if invalid status

**Step 2: Create SubmissionRecord**
- Immutable snapshot: raw_paragraph, classified_fields, incident_detected
- Snapshot all flags: risks, restrictive_practices, anomalies, improvements
- Timestamp: submitted_at
- Actor: submitted_by_user_id

**Step 3: Update review_session**
- Status: `submitted`

**Step 4: Append audit log**
- Action: `submitted`
- Payload: submission_id, actor, incident_detected

**Step 5: Route incident (if confirmed)**
- Query IncidentDraft by review_session_id
- If found AND status=`confirmed`:
  - Mark submission as `routed_to_incident`
  - Store incident routing metadata
  - Ready for incident submission platform

**Step 6: Commit & return**

### Response

```json
{
  "review_session_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "submitted",
  "submitted_at": "2024-06-20T16:45:30.123456Z"
}
```

**OR (if incident routed):**

```json
{
  "review_session_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "routed_to_incident",
  "submitted_at": "2024-06-20T16:45:30.123456Z"
}
```

### SubmissionRecord (DB Snapshot)

```
Fields:
  id: uuid
  tenant_id: string
  review_session_id: uuid (FK)
  staff_id: string (nullable)
  client_id: string (nullable)
  submitted_by_user_id: uuid
  submitted_at: datetime
  
  case_note_data: {
    "raw_paragraph": "...",
    "classified_fields": { ...25+ fields... },
    "incident_detected": boolean
  }
  
  flags_summary: {
    "risks": [...FlagItem...],
    "restrictive_practices": [...FlagItem...],
    "anomalies": [...FlagItem...],
    "improvements": [...FlagItem...]
  }
  
  incident_routing_info: {
    "incident_draft_id": "uuid",
    "routed_at": "2024-06-20T16:45:31Z",
    "status": "routed_to_incident"
  } (nullable)
  
  status: "submitted" | "routed_to_incident" | "failed"
  created_at: datetime
```

### Validation Rules

| Condition | Response | Detail |
|-----------|----------|--------|
| review_session not found | 404 | "review_session {id} not found" |
| Invalid status | 400 | "Cannot submit: status must be reviewed/reportable/escalation" |
| No incident + normal review | 200 | status: "submitted" |
| Incident confirmed | 200 | status: "routed_to_incident" + routing_info |
| Incident not confirmed | 200 | status: "submitted" (incident draft ignored) |
| DB error | 500 | Exception logged |

### Idempotence

- NOT idempotent — calling twice creates two SubmissionRecords
- Guard: Check for existing submission before submitting (client-side)

### Audit Trail

Every submit creates:
- SubmissionRecord row (immutable snapshot)
- ReviewAuditLog entry (action: "submitted")
- Updates to ReviewSession (status, timestamps)

### Auth

- **Type:** JWT Bearer
- **Header:** `Authorization: Bearer <JWT>`
- **Scope:** Any authenticated staff member can submit their own session

### Integration Points

1. **Incident Submission (Platform)** — If incident routed:
   - IncidentDraft linked via submission_record_id
   - Ready for external incident submission service
   - Webhook/external API call (future phase)

2. **Case Note Register** — SubmissionRecord serves as:
   - Audit trail of submission
   - Snapshot of what was approved/flagged
   - Historical reference for compliance queries

### Example: Compliant Case Note (No Incident)

```
POST /v1/case-review/submit
{
  "review_session_id": "550e8400-e29b-41d4-a716-446655440000",
  "actor_user_id": "30d4f882-93d0-4c5d-9af6-22612908817e"
}

Response (200):
{
  "review_session_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "submitted",
  "submitted_at": "2024-06-20T16:45:30.123456Z"
}

DB State:
  ReviewSession: status = "submitted"
  SubmissionRecord: created (snapshot of case note + flags: no risks)
  ReviewAuditLog: action="submitted", actor=user_id
```

### Example: Reportable Incident (Confirmed)

```
POST /v1/case-review/submit
{
  "review_session_id": "550e8400-e29b-41d4-a716-446655440000",
  "actor_user_id": "30d4f882-93d0-4c5d-9af6-22612908817e"
}

Response (200):
{
  "review_session_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "routed_to_incident",
  "submitted_at": "2024-06-20T16:45:30.123456Z"
}

DB State:
  ReviewSession: status = "submitted", incident_detected = true
  SubmissionRecord: 
    - status = "routed_to_incident"
    - incident_routing_info = { incident_draft_id, routed_at }
  IncidentDraft: linked to SubmissionRecord for incident submission
  ReviewAuditLog: action="submitted", incident_detected=true
```

---

## Performance & Costs

| Endpoint | LLM | Tokens | Latency | Cached? |
|----------|-----|--------|---------|---------|
| `/context` | Haiku | 800-1500 | 2-3s | Yes (24h) |
| `/classify` | Haiku | 1200-2000 | 1-2s | No |
| `/review` | Haiku+Sonnet | 2500-4500 | 2-4s | No |
| `/incident/detect` | Haiku+Sonnet | 2000-3500 | 2-3s | Idempotent |
| `/incident/draft` | Sonnet | 3000-5000 | 3-4s | Idempotent |
| `/incident/confirm` | None | 0 | 100ms | N/A |
| `/submit` | None | 0 | 50-100ms | No |

### Batch Cost Estimate (per staff-client pair, per shift)

```
Typical flow:
  classify: 2000 tokens × $0.08/1M = $0.00016
  review:   3500 tokens × $1.50/1M = $0.0053
  detect:   2500 tokens × $1.50/1M = $0.0038
  draft:    4000 tokens × $1.50/1M = $0.006
  
Total per case note: ~$0.015 ($1.50 per 100 notes)
Daily (50 notes): ~$0.75
Monthly (1000 notes): ~$15
```

---

## Restrictive Practices API

### RP Endpoint 1: POST `/v1/restrictive-practices/evaluate` — Full Pipeline Evaluation

**Purpose:** Run case note through complete RP detection pipeline (triage + evaluator + incident draft). RSA signature authentication.

### Request

```json
{
  "case_note_id": "550e8400-e29b-41d4-a716-446655440000",
  "client_id": "dab57916-9863-4b49-ba39-92441547ba5b",
  "worker_id": "30d4f882-93d0-4c5d-9af6-22612908817e",
  "transcript": "Good session. Assisted with meal prep and community access. Participant was cooperative."
}
```

### Flow

**Step 1: Triage** (cheap Haiku gate)
- Flagged? → Continue to Evaluator
- Not flagged? → Return CLEAR verdict

**Step 2: Evaluator** (Claude Sonnet deep analysis)
- Input: Case note + Triage signal
- Output: Structured verdict (practice_category, confidence, reporting_required)

**Step 3: Incident Draft** (if detected)
- Runs incident drafter (Sonnet)
- Populates 20+ incident report fields

**Step 4: Build Response**
- Verdict section (outcome, risk_level, action_required)
- Detected practice section (category, reasoning, trigger phrases)
- Authorisation section (BSP status, approval)
- Reporting obligations (must_report, timeframe)

### Response

```json
{
  "verdict": {
    "outcome": "UNAUTHORISED",
    "risk_level": "high",
    "alert_required": true,
    "action_required": "IMMEDIATE ACTION: Notify NDIS Commission within 24 hours...",
    "next_steps": [...]
  },
  "detected_practice": {
    "category": "Physical Restraint",
    "what_happened": "Staff applied hold to prevent participant from leaving",
    "reasoning": "Evidence of unauthorized restrictive practice...",
    "trigger_phrases": ["restrain", "hold", "prevent departure"],
    "suppression_factors": []
  },
  "authorisation": {
    "status": "NOT_AUTHORISED",
    "behaviour_support_plan": {
      "on_file": false,
      "details": "No active BSP found"
    }
  },
  "reporting_obligations": {
    "must_report": true,
    "notify_within": "24 hours",
    "guidance": "Under NDIS Rules 2018, unauthorized use is reportable..."
  },
  "submission": {...},
  "summary": {...},
  "incident_report": {...},
  "privacy": "APP3 - Sensitive Health Information"
}
```

### Auth

- **Type:** RSA signature (X-Signature header)
- **Signing:** RSA-PSS-SHA256, base64-encoded
- **No JWT required** — public API with signature-based auth

---

### RP Endpoint 2: POST `/v1/restrictive-practices/draft` — Autofill Incident Report

**Purpose:** Extract case note into 20+ pre-filled incident report fields.

### Request

```json
{
  "case_note_id": "550e8400-e29b-41d4-a716-446655440000",
  "client_id": "dab57916-9863-4b49-ba39-92441547ba5b",
  "worker_id": "30d4f882-93d0-4c5d-9af6-22612908817e",
  "transcript": "John was restrained for 20 minutes in office..."
}
```

### Response

```json
{
  "incident_draft_id": "uuid",
  "draft_fields": {
    "incident_type": "Unauthorized restrictive practice",
    "date_of_incident": "2024-06-20",
    "time_of_incident": "15:30",
    "location": "Group home, Acacia Lane",
    "staff_involved": "Sarah Johnson",
    "incident_description": "Staff applied physical hold...",
    "risk_assessment": "HIGH RISK",
    "reportable": true,
    "notification_timeframe": "24 hours"
  },
  "status": "draft",
  "autofill_source": {"model": "sonnet"}
}
```

### Auth

- **Type:** JWT Bearer
- **Header:** `Authorization: Bearer <JWT>`

### Performance

- **Model:** Claude Sonnet
- **Tokens:** 3000-5000
- **Latency:** 3-4s
- **Cache:** No (per-request)

---

### RP Endpoint 3: POST `/v1/restrictive-practices/draft/audio` — Transcribe + Autofill

**Purpose:** Upload audio recording, transcribe, extract incident fields.

### Request

```
multipart/form-data:
  audio: <file>
  worker_id: uuid
  client_id: uuid
  case_note_id: uuid (optional)
  shift_date: YYYY-MM-DD (optional)
  shift_time: HH:MM (optional)
```

### Response

```json
{
  "incident_draft_id": "uuid",
  "draft_fields": {...},
  "status": "draft",
  "transcript": "Transcribed text from audio..."
}
```

### Flow

1. **Transcribe:** Amazon Transcribe (en-AU) → transcript
2. **Extract:** Run drafter LLM on transcript
3. **Return:** Pre-filled incident fields

### Auth

- **Type:** JWT Bearer

### Latency

- Transcription: 5-8s (varies by audio duration)
- LLM drafting: 3-4s
- **Total: 8-10s**
- Cost: $0.0005/minute (transcription) + $0.009 (drafting)

---

### RP Endpoint 4: POST `/v1/restrictive-practices/bsp` — Register Behaviour Support Plan

**Purpose:** Register an approved BSP for a client-practice pair.

### Request

```json
{
  "client_id": "dab57916-9863-4b49-ba39-92441547ba5b",
  "practice_type": "Physical Restraint",
  "status": "Active",
  "approved_dosage": "As needed during crisis de-escalation",
  "approved_conditions": "Only after verbal de-escalation failed. Max 10 min duration.",
  "authorised_by": "Dr. Jane Smith (Behaviour Support Practitioner)",
  "valid_from": "2024-06-01",
  "valid_until": "2025-06-01"
}
```

### Response

```json
{
  "id": "uuid",
  "client_id": "uuid",
  "practice_type": "Physical Restraint",
  "status": "Active",
  "approved_dosage": "...",
  "approved_conditions": "...",
  "authorised_by": "...",
  "valid_from": "2024-06-01",
  "valid_until": "2025-06-01",
  "created_at": "2024-06-20T10:00:00Z"
}
```

### Auth

- **Type:** JWT Bearer

### Latency

- DB insert: ~50ms
- No LLM
- Status: 201 Created

---

### RP Endpoint 5: GET `/v1/restrictive-practices/bsp/{client_id}` — List BSPs

**Purpose:** Retrieve all active BSPs for a client.

### Request

```
GET /v1/restrictive-practices/bsp/dab57916-9863-4b49-ba39-92441547ba5b
```

### Response

```json
[
  {
    "id": "uuid",
    "client_id": "uuid",
    "practice_type": "Physical Restraint",
    "status": "Active",
    "valid_from": "2024-06-01",
    "valid_until": "2025-06-01"
  },
  {
    "id": "uuid",
    "client_id": "uuid",
    "practice_type": "Chemical Sedation",
    "status": "Expired",
    "valid_until": "2024-03-01"
  }
]
```

### Auth

- **Type:** JWT Bearer

### Latency

- DB query: ~10ms
- Ordered by created_at descending
- Status: 200 OK

---

### RP Endpoint 6: PATCH `/v1/restrictive-practices/bsp/{bsp_id}/status` — Update BSP Status

**Purpose:** Change BSP status (Active → Expired or Revoked).

### Request

```json
{
  "status": "Revoked"
}
```

### Valid Statuses

- `Active` — Current authorization in effect
- `Expired` — Validity date has passed
- `Revoked` — Manually disabled

### Response

```json
{
  "id": "uuid",
  "client_id": "uuid",
  "practice_type": "Physical Restraint",
  "status": "Revoked",
  "valid_from": "2024-06-01",
  "valid_until": "2025-06-01",
  "created_at": "2024-06-20T10:00:00Z"
}
```

### Auth

- **Type:** JWT Bearer

### Latency

- DB update: ~50ms
- Status: 200 OK

---

## Voice API (Draft)

### POST `/v1/case-review/voice/session` — Create Voice Session

**Purpose:** Initiate a WebSocket voice session for real-time case-note dictation with Gemini Live.

### Request

```json
{
  "client_id": "dab57916-9863-4b49-ba39-92441547ba5b",
  "worker_id": "30d4f882-93d0-4c5d-9af6-22612908817e",
  "case_note_id": "550e8400-e29b-41d4-a716-446655440000",
  "initial_values": {},
  "readonly_paths": [],
  "worker_display_name": "Sarah Johnson"
}
```

### Response

```json
{
  "session_id": "abc123def456",
  "ws_url": "/v1/case-review/voice/ws/abc123def456",
  "expires_at": "2024-06-20T11:00:00Z"
}
```

### Auth

- **Type:** JWT Bearer
- **Header:** `Authorization: Bearer <JWT>`

### Performance

- **Model:** Gemini 3.1 Flash Live (WebSocket)
- **Latency:** ~50-200ms per token
- **Session timeout:** 3600s

---

### POST `/v1/case-review/voice/draft` — Draft From Transcript

**Purpose:** Convert voice transcript to structured case-note draft.

### Request

```json
{
  "transcript": "Good session today. John participated in meal prep and shopping. Was cooperative.",
  "worker_id": "30d4f882-93d0-4c5d-9af6-22612908817e",
  "client_id": "dab57916-9863-4b49-ba39-92441547ba5b",
  "case_note_id": "550e8400-e29b-41d4-a716-446655440000",
  "shift_date": "2024-06-20",
  "shift_time": "14:00"
}
```

### Response

```json
{
  "case_note_id": "550e8400-e29b-41d4-a716-446655440000",
  "classified_fields": {
    "describe": "John participated in meal prep and shopping activities...",
    "mood": "Cooperative and engaged",
    "what_went_well": "Participated independently in activities"
  },
  "missing_required": [],
  "reask_prompts": [],
  "status": "drafted"
}
```

### Auth

- **Type:** JWT Bearer
- **Header:** `Authorization: Bearer <JWT>`

### Performance

- **Model:** Claude Sonnet (transcription + extraction)
- **Tokens:** 2000-3000
- **Latency:** 2-3s

---

## Restrictive Practices Performance & Costs

| Endpoint | LLM | Tokens | Latency | Cached? |
|----------|-----|--------|---------|---------|
| `POST /evaluate` | Haiku+Sonnet+Incident | 5000-8000 | 4-5s | Redis (24h) |
| `POST /draft` | Sonnet | 3000-5000 | 3-4s | No |
| `POST /draft/audio` | Transcribe+Sonnet | 3000-5000 | 8-10s* | No |
| `POST /bsp` | None | 0 | 50ms | No |
| `GET /bsp/{client_id}` | None | 0 | 10ms | No |
| `PATCH /bsp/{bsp_id}/status` | None | 0 | 50ms | No |

*Audio transcription time varies by duration

### Batch Cost Estimate

```
Evaluation flow:
  draft:    4000 tokens × $1.50/1M = $0.006
  evaluate: 6000 tokens × $1.50/1M = $0.009
  
Total per evaluation: ~$0.015
Daily (20 evaluations): ~$0.30
Monthly (400 evaluations): ~$6

Audio transcription: $0.0005/minute (Amazon Transcribe)
  10-min session: ~$0.005 + $0.015 (evaluate) = ~$0.020
```
