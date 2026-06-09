# Mobile Integration Guide — Case Note Drafting (AI-Assisted)

**Audience:** Mobile developer integrating the SENA AI backend into the support worker app.  
**Scope:** Voice-to-form case note drafting only — the `/draft` endpoint and subsequent form submission.  
**Base URL:** `http://<host>:8084/v1/restrictive-practices`

---

## Overview

The case note drafting flow has two steps:

```
1. Support worker records a voice note (post-shift)
         ↓
   App transcribes audio → has raw transcript string
         ↓
2. POST /draft  ←── THIS GUIDE
         ↓
   AI extracts transcript → returns pre-filled form fields
         ↓
3. Worker reviews + edits pre-filled form on screen
         ↓
4. Worker taps Submit → App calls POST /evaluate
         ↓
   AI screens for restrictive practices → returns compliance verdict
```

The mobile app is responsible for steps 2–4. This guide covers step 2 (calling `/draft`) and step 4 (calling `/evaluate`). The compliance verdict from `/evaluate` is read-only — the app surfaces it to a supervisor; the worker cannot change it.

---

## Step 2 — POST /draft

### Endpoint

```
POST /v1/restrictive-practices/draft
Content-Type: application/json
```

No authentication required on this endpoint.

### Request body (`DraftInput`)

```json
{
  "transcript":       "string  REQUIRED — full voice transcript text",
  "worker_id":        "string  REQUIRED — worker identifier from your platform",
  "client_id":        "string  REQUIRED — participant identifier from your platform",
  "case_note_id":     "uuid    OPTIONAL — omit to let server generate one",
  "shift_date":       "string  OPTIONAL — e.g. '12 May 2025'",
  "shift_time":       "string  OPTIONAL — e.g. '9:00 AM – 1:00 PM'",
  "worker_position":  "string  OPTIONAL — e.g. 'Support Worker'"
}
```

**Rule:** `transcript` is the only text the AI reads. Pass the full, unedited transcript from your speech-to-text engine. Do not pre-process or truncate it.

### Minimal example

```json
{
  "transcript": "Today I supported James with his morning routine. He was in a good mood...",
  "worker_id": "w-123",
  "client_id": "client-456",
  "shift_date": "20 May 2026",
  "shift_time": "7:00 AM – 11:00 AM"
}
```

### Response body (`CaseDraftResponse`)

The server returns a flat JSON object. Map each key directly to the matching form field.

```json
{
  "case_note_id":      "uuid   — use this as the ID for the subsequent /evaluate call",
  "client_id":         "string",
  "worker_id":         "string",
  "shift_date":        "string | null — passed through from request",
  "shift_time":        "string | null — passed through from request",
  "worker_position":   "string | null — passed through from request",
  "transcript":        "string | null — original transcript, pass through to /evaluate",

  "describe":                          "string | null",
  "assisted":                          "string | null",
  "practised_skill":                   "string | null",
  "participants_level_of_independence":"string | null",
  "observations":                      "string | null",

  "mood":              "string | null",
  "behavioural_events":"string | null",
  "any_concerns":      "boolean",

  "what_went_well":              "string | null",
  "what_needs_further_support":  "string | null",
  "participant_comments":        "string | null",

  "medication_reminders_given":  "boolean",
  "safety_hazards_observed":     "boolean",
  "any_injuries":                "boolean",
  "injury_description":          "string | null — only populated when any_injuries=true",

  "carer_feedback":    "string | null",
  "incident_occurred": "boolean",

  "uploaded_documents": null,

  "draft_note":         "string | null — AI gaps note, shown as a banner to the worker",
  "note_quality_score": "float  0.0–1.0",
  "note_quality_label": "string — 'Premium' | 'Average' | 'Poor'",
  "quality_gaps":       ["string", ...]
}
```

---

## Form Field Mapping

Map response keys 1-to-1 onto the six case note form sections:

| Section | Form label | Response key | Input type |
|---------|-----------|--------------|------------|
| 1 | Summary of Shift | `describe` | Multiline text |
| 2 | Assisted | `assisted` | Multiline text |
| 2 | Practised skill | `practised_skill` | Single-line text |
| 2 | Level of independence | `participants_level_of_independence` | Single-line text |
| 2 | Observations | `observations` | Multiline text |
| 3 | Mood | `mood` | Single-line text |
| 3 | Behavioural events | `behavioural_events` | Multiline text |
| 3 | Any concerns? | `any_concerns` | Toggle / checkbox |
| 4 | What went well | `what_went_well` | Multiline text |
| 4 | What needs further support | `what_needs_further_support` | Multiline text |
| 4 | Participant's comments | `participant_comments` | Multiline text |
| 5 | Medication reminders given? | `medication_reminders_given` | Toggle |
| 5 | Safety hazards observed? | `safety_hazards_observed` | Toggle |
| 5 | Any injuries? | `any_injuries` | Toggle |
| 5 | Injury description | `injury_description` | Multiline text, shown only when `any_injuries=true` |
| 6 | Carer feedback | `carer_feedback` | Multiline text |
| 6 | Did any incident occur? | `incident_occurred` | Toggle |

Pre-fill each form field with the value from the response. `null` → leave the field blank (not pre-filled). The worker can edit any field freely before submitting.

---

## Surfacing AI Quality Feedback

The response includes two quality signals the UI must show:

### 1. `draft_note` — extraction gaps banner

Show as a yellow info banner at the top of the form **when `draft_note` is not null**.

```
⚠ AI note: "The transcript did not mention medication or any behavioural concerns.
   Please check and complete those fields before submitting."
```

When `draft_note` is null, the AI considers the transcript comprehensive — no banner needed.

### 2. `note_quality_score` / `note_quality_label` / `quality_gaps` — quality chip

Show a quality chip below the form header:

| `note_quality_label` | Display | Colour |
|---------------------|---------|--------|
| `Premium` | ★ Premium | Green |
| `Average` | ◎ Average | Amber |
| `Poor` | ⚠ Poor | Red |

Tapping the chip expands `quality_gaps` — a list of plain-English suggestions:

```
• "Add specific participant goals addressed during the shift"
• "Describe the outcome of the behavioural event in more detail"
```

These are suggestions only — the worker is not blocked from submitting.

---

## Step 4 — POST /evaluate (Submission)

After the worker reviews and approves the form, call `/evaluate` with the complete form state.

### Endpoint

```
POST /v1/restrictive-practices/evaluate
Content-Type: application/json
```

Authentication: HTTP Basic if `SENA_AI_BASIC_AUTH_USER` / `_PASSWORD` are configured on the server. Ask your backend team.

### Request body (`CaseNoteInput`)

Send the current form state — including any edits the worker made:

```json
{
  "case_note_id":     "uuid   — use the case_note_id returned by /draft",
  "client_id":        "string",
  "worker_id":        "string",

  "transcript":       "string | null — include the original transcript from /draft response",
  "shift_date":       "string | null",
  "shift_time":       "string | null",
  "worker_position":  "string | null",

  "describe":                           "string | null",
  "assisted":                           "string | null",
  "practised_skill":                    "string | null",
  "participants_level_of_independence": "string | null",
  "observations":                       "string | null",

  "mood":             "string | null",
  "behavioural_events": "string | null",
  "any_concerns":     "boolean",

  "what_went_well":             "string | null",
  "what_needs_further_support": "string | null",
  "participant_comments":       "string | null",

  "medication_reminders_given": "boolean",
  "safety_hazards_observed":    "boolean",
  "any_injuries":               "boolean",
  "injury_description":         "string | null",
  "uploaded_documents":         ["doc-id-1", "doc-id-2"] or null,

  "carer_feedback":    "string | null",
  "incident_occurred": "boolean"
}
```

**Validation rule (server-enforced):** at least one of `transcript`, `describe`, `behavioural_events`, `observations`, `carer_feedback`, `assisted`, or `mood` must be non-null. An all-empty payload returns HTTP 422. In practice, the form pre-fill from `/draft` ensures this.

### Key field: `transcript`

Always pass the original `transcript` string from the `/draft` response. The compliance pipeline uses the raw transcript as its primary signal — the edited form fields are secondary context.

---

## /evaluate Response — What to Surface

The response is read-only compliance output. The worker cannot change it. Surface these fields:

### `verdict.outcome` — compliance result

| Value | Display | Action |
|-------|---------|--------|
| `CLEAR` | ✅ Passed screening | None |
| `NO INCIDENT DETECTED` | ✅ No incident found | None |
| `AUTHORISED USE — REVIEW RECOMMENDED` | 🔵 Authorised — review BSP | Show next steps |
| `POSSIBLE RESTRICTIVE PRACTICE — ADMINISTRATIVE REVIEW` | 🟡 Possible concern | Show next steps |
| `ADMINISTRATIVE REVIEW REQUIRED — BSP reference but no DB match` | 🟡 Admin review needed | Show next steps |
| `UNAUTHORISED RESTRICTIVE PRACTICE DETECTED` | 🔴 URGENT: Unauthorised practice | Show next steps + notify supervisor immediately |

### `verdict.alert_required`

`true` only for `UNAUTHORISED`. When true: show a persistent red banner, notify supervisor push notification, and prevent the worker from dismissing until acknowledged.

### `verdict.action_required`

Plain English instruction for the worker. Always show this string below the verdict chip.

### `verdict.next_steps`

Ordered list of actions. Show as a checklist when `next_steps` is non-empty.

### `summary` — AI quality feedback (post-submit)

Same `note_quality_score` / `note_quality_label` / `quality_gaps` as from `/draft`, but re-run on the submitted note. Show on the submission confirmation screen.

### `incident_report` — incident form pre-fill

Present **only when `incident_occurred=true` or verdict is `UNAUTHORISED`**. The incident report section is AI-drafted — show it as a pre-filled incident form for the supervisor to review and complete.

Key fields to surface:

| Field | Display |
|-------|---------|
| `severity` | Low / Medium / High / Critical badge |
| `incident_categories` | Multi-select chips (read-only, showing what AI detected) |
| `ongoing_risk_present` | Risk status indicator |
| `participant_currently_safe` | Safety status |
| `reportable` | Whether NDIS Commission must be notified |
| `notification_timeframe` | e.g. "24 hours" or "5 business days" |
| `incident_description` | Full narrative |

---

## Typical Mobile Flow (Pseudocode)

```
// 1. Worker finishes shift, records audio
transcript = await speechToText(audioFile)

// 2. Get AI-pre-filled form
draftResponse = await POST /draft {
  transcript,
  worker_id: currentUser.id,
  client_id: currentShift.clientId,
  shift_date: currentShift.date,
  shift_time: currentShift.timeRange
}

// 3. Pre-fill form with draft values
form.populate(draftResponse)

// Surface quality banner if draft_note present
if (draftResponse.draft_note != null) showBanner(draftResponse.draft_note)

// Surface quality chip
showQualityChip(draftResponse.note_quality_label, draftResponse.quality_gaps)

// 4. Worker edits and approves form

// 5. Submit
evaluateResponse = await POST /evaluate {
  ...form.currentValues,
  case_note_id: draftResponse.case_note_id,  // preserve the ID
  transcript: draftResponse.transcript        // pass original transcript through
}

// 6. Surface compliance result
showVerdict(evaluateResponse.verdict)

if (evaluateResponse.verdict.alert_required) {
  notifySupervisor(evaluateResponse)
  showRedAlert(evaluateResponse.verdict.action_required)
}

if (evaluateResponse.incident_report != null) {
  navigateTo(IncidentReportScreen, prefilled: evaluateResponse.incident_report)
}
```

---

## Error Handling

| HTTP status | Cause | Action |
|-------------|-------|--------|
| `422` | Validation failed — all text fields null, or invalid field value | Show field-level error from `detail` |
| `401` | Basic auth missing or wrong | Show login prompt |
| `500` | AI pipeline error | Show "AI unavailable — please submit manually" fallback; log `detail` |

For 500 errors on `/draft`: let the worker fill the form manually (no pre-fill). The form must still be submittable — `/draft` is an enhancement, not a gate.

---

## Privacy Headers

Every `/evaluate` response includes:

```
X-Privacy-Classification: Sensitive-Health-Information-APP3
X-Data-Retention: No-Retention-Session-Only
```

The AI backend does **not** store the transcript or form fields after the response is returned. Your platform backend is the system of record.

---

## Notes for Implementation

- `case_note_id` from `/draft` must be passed unchanged to `/evaluate`. This links the audit trail.
- `uploaded_documents` — pass document IDs/URLs from your file upload widget. `/draft` always returns `null` for this field; you populate it on `/evaluate` from user uploads.
- `any_injuries=true` → show `injury_description` text field (hidden otherwise).
- `incident_occurred=true` → the server will include a pre-drafted `incident_report` in the `/evaluate` response.
- `behavioural_events` is the highest-signal field for compliance detection. Encourage workers to be specific here — the AI surfaces quality gaps if it's vague.
