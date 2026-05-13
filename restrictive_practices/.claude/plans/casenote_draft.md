# Plan: Case Note Drafting Endpoint

## Context

Module #50 (Case Note Drafting, Mobile) — support workers record a voice transcript after a shift; this endpoint uses Gemini Pro to extract and map the transcript content into the structured 6-section case note form already modelled as `CaseNoteInput`. The draft is returned pre-filled for worker review before submission. No DB write — human approval happens later.

This lives in `restrictive_practices/` because `CaseNoteInput` and the Gemini client pattern are already here. No new service needed.

---

## New Endpoint

```
POST /v1/restrictive-practices/draft
```

**Input:** transcript + shift metadata  
**Output:** pre-filled form fields (all 6 sections) ready for worker review  
**No DB access needed** — pure AI extraction, stateless

---

## Files to Change

### 1. `models/schemas.py` — add 2 new models

**`DraftInput`** (request body):
```python
class DraftInput(BaseModel):
    transcript: str                        # required — voice transcript text
    worker_id: str
    client_id: str
    case_note_id: UUID = Field(default_factory=uuid4)
    shift_date: str | None = None          # pass-through; AI also tries to extract if absent
    shift_time: str | None = None
    worker_position: str | None = None
```

**`CaseDraftResponse`** (response body — mirrors CaseNoteInput form fields, all optional):
```python
class CaseDraftResponse(BaseModel):
    case_note_id: UUID
    client_id: str
    worker_id: str
    shift_date: str | None
    shift_time: str | None
    worker_position: str | None
    # Section 1
    describe: str | None
    # Section 2
    assisted: str | None
    practised_skill: str | None
    participants_level_of_independence: str | None
    observations: str | None
    # Section 3
    mood: str | None
    behavioural_events: str | None
    any_concerns: bool
    # Section 4
    what_went_well: str | None
    what_needs_further_support: str | None
    participant_comments: str | None
    # Section 5
    medication_reminders_given: bool
    safety_hazards_observed: bool
    any_injuries: bool
    injury_description: str | None
    # Section 6
    carer_feedback: str | None
    incident_occurred: bool
    # Draft metadata
    draft_note: str | None = None   # AI-generated note on extraction quality/gaps
```

Note: `uploaded_documents` excluded — cannot be derived from transcript.

---

### 2. `pipeline/drafter.py` — new file

Follows exact same pattern as `evaluator.py`:

- Private `_DrafterResponse(BaseModel)` — mirrors `CaseDraftResponse` form fields (no metadata; merged in async wrapper)
- `_make_client()` — identical to evaluator/triage
- `_run_drafter(transcript: str) -> _DrafterResponse` — sync Gemini call:
  ```python
  response = client.models.generate_content(
      model=settings.evaluator_model,     # Gemini Pro — accuracy matters
      contents=_DRAFT_PROMPT.format(transcript=transcript),
      config=types.GenerateContentConfig(
          response_mime_type="application/json",
          response_schema=_DrafterResponse,
          temperature=0.0,
          max_output_tokens=4096,
      ),
  )
  data = json.loads(response.text)        # NOT response.parsed
  return _DrafterResponse(**data)
  ```
- `async run_drafter(payload: DraftInput) -> CaseDraftResponse` — offloads via `asyncio.to_thread`, merges metadata fields

**Prompt (`_DRAFT_PROMPT`):**
- Role: "you are an NDIS case note writer"
- Explain each of the 6 form sections and what each field captures
- Extract content from transcript into each field; `null` when not mentioned
- Set boolean flags based on explicit mentions in transcript
- `draft_note`: note any gaps, ambiguities, or fields that could not be extracted

---

### 3. `api/routes.py` — add 1 route

```python
from models.schemas import DraftInput, CaseDraftResponse
from pipeline.drafter import run_drafter

@router.post("/draft", response_model=CaseDraftResponse)
async def draft_case_note(payload: DraftInput) -> CaseDraftResponse:
    """Extract form fields from a voice transcript into a structured case note draft."""
    try:
        return await run_drafter(payload)
    except Exception as exc:
        logger.error("Drafter error worker=%s: %s", payload.worker_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc
```

No privacy headers (no participant health data stored/returned raw).  
No `db` dependency (stateless).

---

## Critical Rules

- `json.loads(response.text)` — never `response.parsed`
- `asyncio.to_thread` — never call Gemini directly in async fn
- `temperature=0.0` — compliance doc, must be deterministic
- `max_output_tokens=4096` — structured JSON output can be large
- `response_schema=_DrafterResponse` — Pydantic model
- `settings.evaluator_model` — Gemini Pro; accuracy > speed

---

## Verification

```bash
# Start server
conda activate sena_env && uvicorn main:app --reload --port 8084

# Hit the draft endpoint
curl -s -X POST http://localhost:8084/v1/restrictive-practices/draft \
  -H "Content-Type: application/json" \
  -d '{
    "transcript": "This morning I supported Marcus at community access. We went grocery shopping at Woolworths and he chose his own items. He was in a good mood. I reminded him to take his medication at 10am. No incidents occurred.",
    "worker_id": "worker-grace-001",
    "client_id": "client-demo-auth",
    "shift_date": "12 May 2025",
    "shift_time": "9:00 AM - 1:00 PM"
  }' | python -m json.tool

# Then chain: submit returned fields to /evaluate to verify end-to-end
```

---

## Out of Scope

- Audio → transcript (caller provides text)
- DB persistence of draft (platform team stores after worker approves)
- Auth middleware
- Streaming response
