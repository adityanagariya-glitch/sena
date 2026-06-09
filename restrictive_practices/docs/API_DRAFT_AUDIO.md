# POST /v1/restrictive-practices/draft/audio

Transcribes an audio recording and extracts it into a pre-filled case note draft.
**Stateless — no data is stored.** The worker reviews and edits the returned fields,
then submits the note to `/evaluate` for compliance screening.

---

## Request

**Content-Type:** `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|:--------:|-------------|
| `audio` | File | ✅ | Audio recording. Supported: `mp3`, `mp4`, `m4a`, `wav`, `flac`, `ogg`, `webm` |
| `worker_id` | string | ✅ | Platform worker / staff ID |
| `client_id` | string | ✅ | Platform client / participant ID |
| `case_note_id` | string | ❌ | Case note ID — auto-generated UUID if omitted or blank |
| `shift_date` | string | ❌ | e.g. `"12 May 2025"` |
| `shift_time` | string | ❌ | e.g. `"9:00 AM - 1:00 PM"` |
| `worker_position` | string | ❌ | e.g. `"Support Worker"` |

### Example (curl)

```bash
curl -X POST http://localhost:8084/v1/restrictive-practices/draft/audio \
  -F "audio=@recording.mp3;type=audio/mpeg" \
  -F "worker_id=W123" \
  -F "client_id=C456" \
  -F "shift_date=12 May 2025" \
  -F "shift_time=9:00 AM - 1:00 PM" \
  -F "worker_position=Support Worker"
```

---

## Response — `200 OK`

**Content-Type:** `application/json`

```jsonc
{
  // ── Identifiers ──────────────────────────────────────────────────────────────
  "case_note_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",  // UUID — auto-generated if not sent
  "client_id": "C456",
  "worker_id": "W123",
  "shift_date": "12 May 2025",          // null if not sent in request
  "shift_time": "9:00 AM - 1:00 PM",   // null if not sent in request
  "worker_position": "Support Worker",  // null if not sent in request

  // ── Section 1 — Summary of Shift ─────────────────────────────────────────────
  "describe": "Supported John with morning routine and community access...",

  // ── Section 2 — Activities Completed & Skill-Building ────────────────────────
  "assisted": "Assisted with meal preparation and personal hygiene",
  "practised_skill": "Practised budgeting skills at the supermarket",
  "participants_level_of_independence": "Required moderate prompting",
  "observations": "Participant engaged well during cooking activity",

  // ── Section 3 — Well-being & Behaviour ───────────────────────────────────────
  "mood": "Calm and cooperative throughout the shift",
  "behavioural_events": null,  // null if not mentioned in audio
  "any_concerns": false,

  // ── Section 4 — Outcomes & Progress ──────────────────────────────────────────
  "what_went_well": "Community outing was successful with no incidents",
  "what_needs_further_support": "Participant still requires prompting for hydration",
  "participant_comments": "Participant expressed enjoyment of the outing",

  // ── Section 5 — Safety / Health Monitoring ───────────────────────────────────
  "medication_reminders_given": true,
  "safety_hazards_observed": false,
  "any_injuries": false,
  "injury_description": null,  // non-null only when any_injuries=true

  // ── Section 6 — Notes / Additional Comments ───────────────────────────────────
  "carer_feedback": null,
  "incident_occurred": false,

  // ── Pass-through ──────────────────────────────────────────────────────────────
  // Original transcribed text — send this back as `transcript` when calling /evaluate
  "transcript": "Today I supported John with his morning routine...",
  "uploaded_documents": null,  // always null from this endpoint

  // ── Extraction quality note ───────────────────────────────────────────────────
  // Non-null when the AI couldn't extract something — show as a warning to the worker
  "draft_note": null,

  // ── Note quality (heuristic, zero AI cost) ────────────────────────────────────
  "note_quality_score": 0.82,      // float 0.0–1.0
  "note_quality_label": "Premium", // "Premium" | "Average" | "Poor"
  "quality_gaps": []               // list of actionable strings when score is low
}
```

---

## Field Reference

### Identifiers

| Field | Type | Notes |
|-------|------|-------|
| `case_note_id` | UUID string | Auto-generated if not provided in the request |
| `client_id` | string | Echoed from request |
| `worker_id` | string | Echoed from request |
| `shift_date` | string \| null | Echoed from request |
| `shift_time` | string \| null | Echoed from request |
| `worker_position` | string \| null | Echoed from request |

### Section 1 — Summary of Shift

| Field | Type | Notes |
|-------|------|-------|
| `describe` | string \| null | What the worker and participant did during the shift |

### Section 2 — Activities Completed & Skill-Building

| Field | Type | Notes |
|-------|------|-------|
| `assisted` | string \| null | What the worker assisted with |
| `practised_skill` | string \| null | Skills the participant practised |
| `participants_level_of_independence` | string \| null | How independently the participant performed tasks |
| `observations` | string \| null | Worker's clinical observations |

### Section 3 — Well-being & Behaviour

| Field | Type | Notes |
|-------|------|-------|
| `mood` | string \| null | Participant's mood description |
| `behavioural_events` | string \| null | Any behavioural incidents or notable events |
| `any_concerns` | boolean | Defaults to `false` if not mentioned in audio |

### Section 4 — Outcomes & Progress

| Field | Type | Notes |
|-------|------|-------|
| `what_went_well` | string \| null | Positive outcomes from the shift |
| `what_needs_further_support` | string \| null | Areas needing improvement |
| `participant_comments` | string \| null | Direct quotes or feedback from the participant |

### Section 5 — Safety / Health Monitoring

| Field | Type | Notes |
|-------|------|-------|
| `medication_reminders_given` | boolean | Defaults to `false` |
| `safety_hazards_observed` | boolean | Defaults to `false` |
| `any_injuries` | boolean | Defaults to `false` |
| `injury_description` | string \| null | Populated only when `any_injuries=true` |

### Section 6 — Notes / Additional Comments

| Field | Type | Notes |
|-------|------|-------|
| `carer_feedback` | string \| null | Feedback from carer or family |
| `incident_occurred` | boolean | Defaults to `false`; set `true` → triggers incident report in `/evaluate` |

### Pass-through Fields

| Field | Type | Notes |
|-------|------|-------|
| `transcript` | string \| null | Full transcribed text from the audio — pass back as `transcript` when calling `/evaluate` |
| `uploaded_documents` | null | Always `null`; populated later when the worker attaches photos or documents |

### Quality Fields

| Field | Type | Notes |
|-------|------|-------|
| `draft_note` | string \| null | AI message about extraction gaps — **show as a warning banner** if non-null |
| `note_quality_score` | float (0.0–1.0) | Heuristic quality score |
| `note_quality_label` | string | `"Premium"` \| `"Average"` \| `"Poor"` |
| `quality_gaps` | string[] | Actionable suggestions e.g. `"Behavioural events section is empty"` — show as checklist |

---

## Mobile Integration Notes

1. **Attach `transcript` when calling `/evaluate`** — after the worker approves the draft, send the `transcript` field value in the `/evaluate` request body so the compliance pipeline has the full text.

2. **Show `draft_note` as a warning** — if `draft_note` is non-null, display it as a yellow/amber banner above the form so the worker knows what to manually fill in.

3. **`quality_gaps` as a pre-submit checklist** — render each string in `quality_gaps` as a checklist item. Encourage (but do not block) the worker to address them before submitting.

4. **All text fields can be null** — the AI extracts what it can hear. Null means the topic was not mentioned in the audio; the worker should fill it in manually.

5. **Boolean fields default to `false`** — if the worker mentioned medication reminders, injuries, etc., the model sets the appropriate flag. Workers should review these before submitting.

6. **Audio format** — prefer `mp4`/`m4a` or `wav` for best transcription accuracy in Australian English. The server uses Amazon Transcribe with an `en-AU` language model.

---

## Error Responses

| HTTP Status | When | `detail` |
|-------------|------|----------|
| `400 Bad Request` | Unsupported audio format | `"Unsupported audio format: content_type='audio/x-aiff', filename='recording.aiff'. Supported: ['flac', 'mp3', 'mp4', 'ogg', 'wav', 'webm']"` |
| `503 Service Unavailable` | S3 / Transcribe bucket not configured on server | `"Audio transcription not configured. Set S3_BUCKET (or SENA_AI_TRANSCRIPTION_BUCKET)."` |
| `502 Bad Gateway` | Amazon Transcribe job failed | `"Transcribe job sena-abc123 FAILED: The S3 bucket does not exist."` |
| `504 Gateway Timeout` | Transcribe job exceeded 120 s | `"Transcribe job sena-abc123 did not complete within 120s"` |
| `500 Internal Server Error` | Unexpected server error | `"RuntimeError: ..."` |

### Error response shape

```jsonc
{
  "detail": "Human-readable error message"
}
```
