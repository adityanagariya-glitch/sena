# NDIS Restrictive Practices Detection — Demo Guide

## Setup (One Command)

```bash
conda activate sena_env
cd C:\Users\Admin\Documents\SENA\restrictive_practices

make demo-setup   # starts DB, downloads 5 NDIS PDFs, seeds demo BSPs
make server       # starts API on port 8084
```

`demo-setup` takes 3–5 minutes on first run (PDF downloads + embedding ~300 chunks).

---

## API Endpoint

```
POST http://localhost:8084/v1/restrictive-practices/evaluate
Content-Type: application/json
```

**Request:**
```json
{
  "case_note_id": "<any UUID>",
  "client_id": "<see demo clients below>",
  "worker_id": "worker-001",
  "transcript": "<case note text>"
}
```

**Response includes:**
- `triage.flagged` — fast YES/NO gate (Gemini Flash)
- `evaluator.practice_category` — which of the 5 RP types
- `evaluator.policy_violation_risk` — Low / Medium / High / Critical
- `evaluator.reasoning` — evidence-based quote from case note
- `evaluator.reporting_required` — true if NDIS Commission notification triggered
- `evaluator.notification_timeframe` — "5 business days" or "24 hours"
- `cross_check.authorisation_status` — AUTHORISED / UNAUTHORISED / NO_INCIDENT
- `alert_required` — true = escalate immediately
- `privacy_notice` — APP 3 compliance statement

**Response headers:**
- `X-Privacy-Classification: Sensitive-Health-Information-APP3`
- `X-Data-Retention: No-Retention-Session-Only`

---

## Demo Scenarios

### 1 — Clean Note (No Restrictive Practice)

Demonstrates the cost-saving early-exit path. Triage returns `flagged=false`, pipeline ends — no RAG or evaluator called.

```bash
curl -s -X POST http://localhost:8084/v1/restrictive-practices/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "case_note_id": "00000000-0000-0000-0000-000000000001",
    "client_id": "client-demo-unauth",
    "worker_id": "worker-001",
    "transcript": "Had a great session with James today. We went to the park, played basketball, and made lunch together. James was calm and engaged throughout. No incidents to report."
  }' | python -m json.tool
```

**Expected:** `triage.flagged=false`, `alert_required=false`, no evaluator output.

---

### 2 — Unauthorised Physical Restraint (Alert Required)

Worker physically held a client without an active BSP. Full pipeline runs, triggers alert and 5-day reporting obligation.

```bash
curl -s -X POST http://localhost:8084/v1/restrictive-practices/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "case_note_id": "00000000-0000-0000-0000-000000000002",
    "client_id": "client-demo-unauth",
    "worker_id": "worker-001",
    "transcript": "Tom became very agitated and started hitting himself. I grabbed his wrists and held his arms tightly against his sides for about three minutes until he calmed down. He was upset but settled after that."
  }' | python -m json.tool
```

**Expected:** `alert_required=true`, `authorisation_status="Unauthorised Restrictive Practice"`, `reporting_required=true`, `notification_timeframe="5 business days"`.

---

### 3 — Authorised Chemical Restraint (Review Only)

PRN medication administered. Client `client-demo-chem` has an active BSP for Chemical Restraint — so this is AUTHORISED_REVIEW, not an alert.

```bash
curl -s -X POST http://localhost:8084/v1/restrictive-practices/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "case_note_id": "00000000-0000-0000-0000-000000000003",
    "client_id": "client-demo-chem",
    "worker_id": "worker-001",
    "transcript": "Maria became severely agitated around 2pm and began banging her head on the wall. After verbal de-escalation failed I administered 5mg Diazepam PRN as per her behaviour support plan. She settled within 20 minutes and rested for an hour."
  }' | python -m json.tool
```

**Expected:** `alert_required=false`, `authorisation_status="Authorised Use (Review Required)"`, `reporting_required=false`.

---

### 4 — Unauthorised Seclusion (Alert Required)

Worker confined a participant in a room. No BSP covers seclusion for this client.

```bash
curl -s -X POST http://localhost:8084/v1/restrictive-practices/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "case_note_id": "00000000-0000-0000-0000-000000000004",
    "client_id": "client-demo-unauth",
    "worker_id": "worker-001",
    "transcript": "After a major meltdown at 11am, I guided Daniel into his bedroom and held the door closed from the outside for approximately fifteen minutes to give him time to calm down. He kept trying to open the door but I kept it shut until he stopped crying."
  }' | python -m json.tool
```

**Expected:** `alert_required=true`, `practice_category` includes "Seclusion", `reporting_required=true`.

---

### 5 — Complex Multi-Practice Note (Sarah / Liam)

Realistic 700-word shift note with physical restraint, chemical restraint, seclusion, and environmental restraint signals. Client `liam-001` has active BSPs for Physical and Chemical — but NOT seclusion.

```bash
python scripts/test_sarah_note.py
```

**Expected:** Multiple practices detected; BSP match on physical + chemical = AUTHORISED_REVIEW; seclusion with no BSP = UNAUTHORISED.

---

## Privacy Compliance Notes

This system processes **sensitive health information** under the Australian Privacy Act 1988:

| APP | Requirement | Implementation |
|-----|-------------|----------------|
| APP 1 | Transparent data handling policy | `privacy_notice` field in every response |
| APP 3 | Consent for sensitive health data | System used only for NDIS compliance monitoring (primary purpose) |
| APP 6 | Use limitation | Case note text not retained; only audit metadata stored in `rp_case_note_runs` |
| APP 11 | Security of personal information | Data processed in AU region (`australia-southeast1`); no cross-border transfer |

**For production deployment:**
- Obtain participant consent for AI-assisted compliance monitoring
- Complete a Privacy Impact Assessment (OAIC guidance, Oct 2024)
- Enable `SENA_AI_VERTEX_AI_DISABLE_LOGGING=true` to suppress Vertex AI prompt logging

---

## Verify DB State

```bash
# Chunk counts by document type
docker exec sena-ai-db psql -U sena_ai -d sena_ai \
  -c "SELECT document_type, COUNT(*) FROM rp_ndis_policy_chunks GROUP BY document_type ORDER BY COUNT(*) DESC;"

# Last 10 pipeline runs
docker exec sena-ai-db psql -U sena_ai -d sena_ai \
  -c "SELECT case_note_id, client_id, triage_flagged, authorisation_status, alert_required, processing_time_ms FROM rp_case_note_runs ORDER BY created_at DESC LIMIT 10;"

# Demo BSPs
docker exec sena-ai-db psql -U sena_ai -d sena_ai \
  -c "SELECT client_id, practice_type, status, authorised_by FROM behaviour_support_plans ORDER BY client_id;"
```
