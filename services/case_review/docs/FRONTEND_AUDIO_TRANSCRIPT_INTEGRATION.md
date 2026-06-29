# Audio Transcript → Incident Analysis (Frontend Integration)

**Audience:** Flutter (mobile) + React (web) teams
**Status:** Live — no backend changes pending
**Base URL:** `http://3.111.109.14:8080/case-review`

---

## TL;DR

The flow is **stateless** — the backend stores nothing. The user submits the
shift form (by voice or manually); if voice, Step 1 returns the transcript, which
you hold client-side and pass into Steps 2 and 3.

```
  ┌────────────┐   transcript    ┌──────────────────┐
  │  /draft/   │ ──────────────► │  your app state  │
  │   audio    │   (voice only)  │  (Flutter/React) │
  └────────────┘                 └────────┬─────────┘
                                          │ case_note_form + voice_transcript
                                          ▼
                                 ┌──────────────────┐
                            ┌──► │ /shift-analysis  │ ──► AI Summary
                            │    │   (Step 2)       │ ──► Risk Summary
                            │    └──────────────────┘ ──► Incident Report
                            │             │ (after the 3 screens render)
                            │             ▼
                            │    ┌──────────────────┐
                            └──► │ /incidents/      │ ──► AI Summary
        same body, same JWT      │   analyze (Step 3)│ ──► Risk Summary
                                 └──────────────────┘ ──► Incident Draft
```

There is **no transcript ID**, no separate fetch, no polling. Manual entry just
skips Step 1 — send the typed `case_note_form` straight to Steps 2/3.

> **Note:** Steps 2 and 3 each run the full AI pipeline. `/shift-analysis` powers
> the three review screens; `/incidents/analyze` is called afterwards. Same body,
> same JWT for both.

---

## Step 1 — Transcribe audio

`POST /v1/restrictive-practices/draft/audio`

Uploads a recording, runs Amazon Transcribe (en-AU), and returns both the raw
transcript **and** a pre-filled draft.

### Request — `multipart/form-data`

| Field             | Type   | Required | Notes                                          |
|-------------------|--------|----------|------------------------------------------------|
| `audio`           | file   | ✅       | mp3, mp4/m4a, wav, flac, ogg, webm             |
| `worker_id`       | string | ✅       | Staff member ID                                |
| `client_id`       | string | ✅       | Participant ID                                 |
| `case_note_id`    | string | —        | Omit to let the server generate one            |
| `shift_date`      | string | —        | e.g. `2026-06-29`                              |
| `shift_time`      | string | —        | e.g. `09:00-17:00`                             |
| `worker_position` | string | —        | e.g. `Support Worker`                          |

**Auth:** `Authorization: Bearer <SENA_JWT>`

### Response — `200 OK`

```jsonc
{
  "case_note_id": "a1b2c3d4-...",
  "client_id": "client-123",
  "worker_id": "worker-456",

  "transcript": "Today I supported John with his morning routine...",  // ◄── KEEP THIS

  "describe": "Morning shift support",
  "mood": "Calm and cooperative",
  "behavioural_events": null,
  "incident_occurred": false,
  // ...other pre-filled draft fields...

  "note_quality_score": 0.82,
  "note_quality_label": "Good",
  "token_usage": { "input_tokens": 2100, "output_tokens": 740, "total_tokens": 2840 }
}
```

> **Store `response.transcript`.** That string is the only thing Step 2 needs from here.

### Error responses

| Status | Meaning                                        | Action                          |
|--------|------------------------------------------------|---------------------------------|
| `400`  | Unsupported audio format                       | Check file type before upload   |
| `422`  | No speech detected                             | Prompt user to re-record        |
| `502`/`504` | Transcription service error / timeout    | Retry                           |
| `503`  | Transcription not configured (backend)         | Escalate to backend team        |

---

## Step 2 — Shift analysis (the 3 review screens)

`POST /v1/case-review/shift-analysis`

This is the call that powers the **AI Summary / Risk Summary / Incident Report**
screens. Send the structured shift form plus the transcript you saved (if voice).

### Request — `application/json`

```jsonc
{
  "case_note_form": {
    "clientId": "client-123",
    "shiftId": "shift-789",
    "summaryOfShift": "Morning support session",
    "activitiesAndSkill": {
      "assisted": "Personal care",
      "practisedSkill": "Meal preparation",
      "participantsLevelOfIndependence": "Moderate",
      "observation": "Engaged well"
    },
    "wellbeingAndBehaviour": {
      "mood": "Calm",
      "behaviouralEvents": null,
      "anyConcerns": false
    },
    "outcomesAndProgress": {
      "whatWentWell": "Completed routine independently",
      "furtherSupport": "Continue current plan",
      "participantsComments": "Happy with support"
    },
    "safetyAndHealth": {
      "medicationReminderGiven": true,
      "safetyHazardObserved": false,
      "anyInjuries": false,
      "injuryDetails": null,
      "reportMedia": []
    },
    "careFeedback": null,
    "anyIncident": false,
    "handoverNote": null,
    "reviewNotes": null
  },

  "voice_transcript": "Today I supported John with his morning routine..."  // ◄── from Step 1 (omit for manual)
}
```

- `case_note_form` is **required**. Only `clientId`, `shiftId`, `summaryOfShift`
  are mandatory; every nested object is optional and defaults to empty.
- `voice_transcript` is **optional**. Omit it for a manual/form-only analysis.

**Auth:** `Authorization: Bearer <SENA_JWT>`

### Response — `200 OK`

```jsonc
{
  "client_id": "client-123",
  "shift_id": "shift-789",
  "incident_detected": false,

  "ai_summary": {                  // Screen 1 — always present
    "reviewed_period": null,       // frontend fills from shift dates
    "ai_confidence": 0.88,
    "confidence_label": "High",
    "progress_rating": "On Track", // On Track | Monitoring | Needs Attention
    "progress_identified": [],
    "goal_progress": [],
    "potential_risks": [],
    "patterns_detected": [],
    "flagged_highlights": [],
    "restrictive_practice_used": false,
    "note_quality_score": 0.82,
    "note_quality_label": "Average"
  },
  "risk_summary": null,            // Screen 2 — null unless the note is flagged
  "incident_report": null,         // Screen 3 — null unless an incident is detected

  "token_usage": { "input_tokens": 3200, "output_tokens": 1100, "total_tokens": 4300 }
}
```

`risk_summary` and `incident_report` are `null` for a clean shift — render those
screens conditionally. (Human-only incident fields — date/time, location,
individuals, witnesses, reported-to, additional notes — are **not** returned;
the worker fills those in the Incident Report form.)

---

## Step 3 — Incident analysis (called after the screens render)

`POST /v1/restrictive-practices/incidents/analyze`

Called once Step 2's screens are shown. Same body shape, same JWT. Returns the
same three sections in the older `ai_summary / risk_summary / incident_draft`
shape.

### Request — `application/json`

Identical body to Step 2 (`case_note_form` + optional `voice_transcript`).

### Response — `200 OK`

```jsonc
{
  "case_note_id": "shift-789",
  "client_id": "client-123",
  "shift_id": "shift-789",
  "incident_detected": false,

  "ai_summary":   { /* progress, risks, anomalies, quality_gaps */ },
  "risk_summary": null,            // populated only when an incident is flagged
  "incident_draft": null,          // populated only when an incident is drafted

  "token_usage": { "input_tokens": 3200, "output_tokens": 1100, "total_tokens": 4300 }
}
```

`risk_summary` and `incident_draft` are `null` for a clean note — render those
screens conditionally.

---

## Authentication

Both endpoints use the **same SENA JWT** as every other case_review endpoint —
no special signing, no second credential.

| Endpoint              | Method     | Header                          |
|-----------------------|------------|---------------------------------|
| `/draft/audio`        | JWT Bearer | `Authorization: Bearer <jwt>`   |
| `/shift-analysis`     | JWT Bearer | `Authorization: Bearer <jwt>`   |
| `/incidents/analyze`  | JWT Bearer | `Authorization: Bearer <jwt>`   |

The JWT carries `organizationId`, `userId`, and optionally `roles` (or `role`) —
roles are optional and are not required to call any of these endpoints.

---

## Client examples

### Flutter (Dart)

```dart
import 'dart:convert';
import 'package:http/http.dart' as http;

const base = 'http://3.111.109.14:8080/case-review';

// Step 1 — upload audio, get transcript
Future<String> transcribeAudio(File audio, String jwt,
    {required String workerId, required String clientId}) async {
  final req = http.MultipartRequest(
    'POST', Uri.parse('$base/v1/restrictive-practices/draft/audio'),
  )
    ..headers['Authorization'] = 'Bearer $jwt'
    ..fields['worker_id'] = workerId
    ..fields['client_id'] = clientId
    ..files.add(await http.MultipartFile.fromPath('audio', audio.path));

  final res = await http.Response.fromStream(await req.send());
  if (res.statusCode != 200) {
    throw Exception('Transcribe failed (${res.statusCode}): ${res.body}');
  }
  return jsonDecode(res.body)['transcript'] as String; // ◄── hold this
}

// Shared POST helper for Steps 2 & 3 (same body, only the path differs)
Future<Map<String, dynamic>> _postAnalysis(
    String path, Map<String, dynamic> caseNoteForm, String transcript, String jwt) async {
  final res = await http.post(
    Uri.parse('$base$path'),
    headers: {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer $jwt',
    },
    body: jsonEncode({
      'case_note_form': caseNoteForm,
      'voice_transcript': transcript, // from Step 1 (or '' for manual)
    }),
  );
  if (res.statusCode != 200) {
    throw Exception('Analysis failed (${res.statusCode}): ${res.body}');
  }
  return jsonDecode(res.body) as Map<String, dynamic>;
}

// Step 2 — the 3 review screens
Future<Map<String, dynamic>> shiftAnalysis(
        Map<String, dynamic> caseNoteForm, String transcript, String jwt) =>
    _postAnalysis('/v1/case-review/shift-analysis', caseNoteForm, transcript, jwt);

// Step 3 — incident analysis (after the screens render)
Future<Map<String, dynamic>> analyze(
        Map<String, dynamic> caseNoteForm, String transcript, String jwt) =>
    _postAnalysis('/v1/restrictive-practices/incidents/analyze', caseNoteForm, transcript, jwt);
```

### React (TypeScript)

```ts
const BASE = "http://3.111.109.14:8080/case-review";

// Step 1 — upload audio, get transcript
export async function transcribeAudio(
  audio: File, jwt: string, workerId: string, clientId: string,
): Promise<string> {
  const form = new FormData();
  form.append("audio", audio);
  form.append("worker_id", workerId);
  form.append("client_id", clientId);

  const res = await fetch(`${BASE}/v1/restrictive-practices/draft/audio`, {
    method: "POST",
    headers: { Authorization: `Bearer ${jwt}` }, // do NOT set Content-Type for FormData
    body: form,
  });
  if (!res.ok) throw new Error(`Transcribe failed: ${res.status}`);

  const data = await res.json();
  return data.transcript as string; // ◄── hold this
}

// Shared POST helper for Steps 2 & 3 (same body, only the path differs)
async function postAnalysis(
  path: string, caseNoteForm: Record<string, unknown>, transcript: string, jwt: string,
) {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${jwt}`,
    },
    body: JSON.stringify({
      case_note_form: caseNoteForm,
      voice_transcript: transcript, // from Step 1 (or "" for manual)
    }),
  });
  if (!res.ok) throw new Error(`Analysis failed: ${res.status}`);
  return res.json();
}

// Step 2 — the 3 review screens
export const shiftAnalysis = (form: Record<string, unknown>, transcript: string, jwt: string) =>
  postAnalysis("/v1/case-review/shift-analysis", form, transcript, jwt);

// Step 3 — incident analysis (after the screens render)
export const analyze = (form: Record<string, unknown>, transcript: string, jwt: string) =>
  postAnalysis("/v1/restrictive-practices/incidents/analyze", form, transcript, jwt);
```

---

## FAQ

**Does the backend store the transcript?**
No. Both endpoints are stateless — nothing is written to the database. If the
user closes the app between steps, the transcript is gone; re-record or re-run
Step 1.

**Can I skip Step 1 and type the transcript manually?**
Yes. `voice_transcript` is just a string — provide it from any source, or omit
it entirely for a form-only analysis.

**What if `/draft/audio` already gave me good draft fields — do I resend them?**
No. Step 2 only consumes `case_note_form` (your structured form) + the raw
`voice_transcript`. The draft fields from Step 1 are for showing the user a
pre-fill; the analysis re-derives everything from form + transcript.

**Why are there two analysis calls (`/shift-analysis` then `/incidents/analyze`)?**
`/shift-analysis` powers the three review screens (it's the new, UI-aligned
shape). `/incidents/analyze` is called afterwards and returns the same three
sections in the older `incident_draft` shape. Send the **same body and JWT** to
both. They each run the AI pipeline, so expect token usage on both.

**The user typed the form instead of recording — what changes?**
Skip Step 1. Send the typed `case_note_form` straight to Steps 2/3 with
`voice_transcript` omitted (or `""`).

**What auth do these use?**
All three use the same SENA JWT (`Authorization: Bearer <jwt>`) as every other
case_review endpoint. `roles`/`role` in the token are optional — not required to
call any of them.
