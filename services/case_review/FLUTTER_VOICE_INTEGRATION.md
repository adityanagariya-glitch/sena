# Case Review — Voice Dictation: Flutter Integration Guide

> **Audience:** sena-mobile Flutter team  
> **Service:** `case_review` (port 8084)  
> **Branch:** `ai-services`  
> **Date:** 2026-06-12

---

## What changed

The voice case-note flow is now **two-phase**:

| Phase | Who does it | Endpoint |
|-------|-------------|----------|
| 1 — Draft extraction | AWS Bedrock (Claude Sonnet) | `POST /v1/case-review/voice/draft` |
| 2 — Voice fill gaps | Gemini Live (WebSocket) | `POST /v1/case-review/voice/session` → `WS /ws/case-review/voice/{id}` |

Bedrock extracts as many fields as it can from the shift transcript. Gemini then picks up only the remaining empty fields, so the voice session is shorter and more focused.

---

## Screen flow

```
[Setup screen]
    ↓  "Start"
[Transcript screen]        ← NEW
    ↓  "Process with AI"   ← calls POST /draft
[Draft preview screen]     ← NEW
    ↓  "Fill remaining with voice"
[Voice session screen]     ← existing, no WS changes
```

---

## New endpoint — `POST /v1/case-review/voice/draft`

### Request

```
POST /v1/case-review/voice/draft
Content-Type: application/json
X-Tenant-Id: <tenant_id>
X-User-Id:   <user_id>
X-User-Roles: worker
```

```json
{
  "transcript": "Today I supported Liam with his morning routine..."
}
```

### Response `200 OK`

```json
{
  "initial_values": {
    "summary": {
      "summaryOfShift": "Participant was supported with morning routine and community access..."
    },
    "activitiesAndSkill": {
      "assisted": "Worker assisted with showering, dressing, and meal preparation.",
      "practisedSkill": "Participant practised independent meal preparation with verbal prompting.",
      "participantsLevelOfIndependence": "Moderate — required physical assistance for showering.",
      "observation": "Participant demonstrated increased confidence during checkout."
    },
    "wellbeingAndBehaviour": {
      "mood": "Participant presented as calm and engaged throughout the shift.",
      "anyConcerns": false
    },
    "safetyAndHealth": {
      "medicationReminderGiven": true,
      "safetyHazardObserved": false,
      "anyInjuries": false
    },
    "handover": {
      "handover": "No issues to report. Evening worker to follow up on appointment booking."
    }
  },
  "filled_count": 9,
  "gaps_note": "Handover note and further support fields not mentioned — Gemini will ask."
}
```

### Dart model

```dart
class DraftTranscriptRequest {
  final String transcript;
  const DraftTranscriptRequest({required this.transcript});
  Map<String, dynamic> toJson() => {'transcript': transcript};
}

class DraftTranscriptResponse {
  final Map<String, Map<String, dynamic>> initialValues;
  final String? gapsNote;
  final int filledCount;

  const DraftTranscriptResponse({
    required this.initialValues,
    this.gapsNote,
    required this.filledCount,
  });

  factory DraftTranscriptResponse.fromJson(Map<String, dynamic> json) {
    final raw = (json['initial_values'] as Map<String, dynamic>?) ?? {};
    return DraftTranscriptResponse(
      initialValues: raw.map(
        (k, v) => MapEntry(k, Map<String, dynamic>.from(v as Map)),
      ),
      gapsNote: json['gaps_note'] as String?,
      filledCount: (json['filled_count'] as num).toInt(),
    );
  }
}
```

### Error handling

| Status | Meaning | Action |
|--------|---------|--------|
| `200` | Fields extracted | Show draft preview |
| `403` | Not a staff role | Redirect to login |
| `422` | Transcript missing/empty | Validate before calling |
| `500` | Bedrock error | Show retry banner; transcript still usable for voice-only session |

---

## Updated endpoint — `POST /v1/case-review/voice/session`

`initial_values` is now accepted in the request body. Pass the value from the draft response directly.

### Request

```json
{
  "client_id": "e64ae455-eee5-4e19-9edc-88bcf846569d",
  "shift_id": "shift-001",
  "initial_values": {
    "summary": { "summaryOfShift": "..." },
    "activitiesAndSkill": { "assisted": "..." }
  }
}
```

`initial_values` is **optional** — if the user skips the draft step (or Bedrock fails), send an empty object `{}` or omit the field entirely.

### Dart model update

```dart
class CreateVoiceSessionRequest {
  final String clientId;
  final String shiftId;
  final Map<String, Map<String, dynamic>> initialValues; // NEW — was missing

  const CreateVoiceSessionRequest({
    required this.clientId,
    required this.shiftId,
    this.initialValues = const {},
  });

  Map<String, dynamic> toJson() => {
    'client_id': clientId,
    'shift_id': shiftId,
    if (initialValues.isNotEmpty) 'initial_values': initialValues,
  };
}
```

---

## WebSocket — no protocol changes

The WS contract is **unchanged**. All existing event types (`turn_start`, `turn_complete`, `field_updated`, `agent_said`, `user_said`, `error`, etc.) work identically.

The only difference: when the `ready` event arrives, the `state` object already has values in pre-filled fields (source = `"system"`). The agent will skip those fields and go directly to empty ones.

```json
{
  "type": "ready",
  "state": {
    "values": {
      "summary": {
        "summaryOfShift": {
          "value": "Participant was supported with...",
          "source": "system",
          "confidence": 0.9
        }
      }
    }
  }
}
```

---

## Visual treatment for pre-filled fields

Fields with `source: "system"` in the state were extracted by Bedrock, not dictated by the user. Recommended treatment:

| State | Visual |
|-------|--------|
| `source: "system"` (Bedrock) | Light blue background, "AI Draft" chip/tag, editable |
| `source: "voice"` (Gemini) | Standard filled colour, no chip |
| Empty | Standard empty state |

The user should be able to **edit or clear** any Bedrock-pre-filled field before submitting. Do not lock them.

---

## Draft preview screen — recommended content

After the draft API responds, show:

1. **Summary line** — `"9 fields auto-filled from transcript"`
2. **Gaps note** (if present) — `"⚠ Handover note not mentioned — Gemini will ask."` — shown as an info banner
3. **Field preview** — list of filled sections/fields with their extracted values (read-only preview, not the full form)
4. **Two CTAs:**
   - `"Fill remaining with voice"` → creates session + opens WS
   - `"Skip to voice"` → creates session with empty `initial_values` (voice-only fallback)

---

## Transcript screen — recommended content

1. **Multiline text field** — "Paste or type your shift notes"
2. **Word count** — disable "Process with AI" button under ~5 words
3. **Loading state** during Bedrock call — typical latency 2–5 seconds
4. **Error state** if draft fails — show retry + "Skip to voice" fallback

---

## Auth headers (unchanged)

All requests require:

```
X-Tenant-Id:  <uuid>
X-User-Id:    <uuid>
X-User-Roles: worker   (or staff / support_worker / admin)
```

The `/draft` endpoint enforces the same staff-only gate as `/session`.

---

## URLs — localtunnel (dev) + local fallback

> **If logs are not showing in your terminal, the app is still hitting the deployed EC2 URL.**  
> Use the localtunnel URLs below to route through your local terminal.

### Start tunnels (one per service port)

```powershell
# Onboarding (port 8083) — already running
npx localtunnel --port 8083 --subdomain bosc-sena-backend
# → https://bosc-sena-backend.loca.lt

# Case Review (port 8084) — start this for the voice draft feature
npx localtunnel --port 8084 --subdomain bosc-sena-case-review
# → https://bosc-sena-case-review.loca.lt

# Voice (port 8082) — if needed
npx localtunnel --port 8082 --subdomain bosc-sena-voice
# → https://bosc-sena-voice.loca.lt
```

### Start the services (separate terminals)

```powershell
# Case Review — draft + voice session + WS
cd services\case_review
.\.venv\Scripts\uvicorn.exe src.case_review.main:create_app --factory --reload --port 8084

# Voice service
cd services\voice
.\.venv\Scripts\uvicorn.exe src.voice.main:create_app --factory --reload --port 8082

# Onboarding
cd services\onboarding
.\.venv\Scripts\uvicorn.exe src.onboarding.main:create_app --factory --reload --port 8083
```

### URL table

| Service | Localtunnel (dev) | Local fallback |
|---------|-------------------|----------------|
| **case_review** | `https://bosc-sena-case-review.loca.lt` | `http://localhost:8084` |
| onboarding | `https://bosc-sena-backend.loca.lt` | `http://localhost:8083` |
| voice | `https://bosc-sena-voice.loca.lt` | `http://localhost:8082` |

### Endpoints for this feature

```
POST https://bosc-sena-case-review.loca.lt/v1/case-review/voice/draft
POST https://bosc-sena-case-review.loca.lt/v1/case-review/voice/session
WS   wss://bosc-sena-case-review.loca.lt/ws/case-review/voice/{session_id}
```

### Required header — localtunnel bypass

Localtunnel shows a browser warning page unless you send this header on every HTTP request:

```dart
'bypass-tunnel-reminder': 'true',
```

Add it alongside your auth headers:

```dart
headers: {
  'Content-Type':            'application/json',
  'X-Tenant-Id':             tenantId,
  'X-User-Id':               userId,
  'X-User-Roles':            'worker',
  'bypass-tunnel-reminder':  'true',   // ← required for localtunnel
},
```

### WebSocket URL (localtunnel = wss://, always TLS)

```dart
// Localtunnel dev
const host = 'bosc-sena-case-review.loca.lt';
const scheme = 'wss';

final wsUrl = '$scheme://$host/ws/case-review/voice/$sessionId'
    '?tenant_id=${Uri.encodeComponent(tenantId)}'
    '&participant_id=${Uri.encodeComponent(clientId)}'
    '&roles=worker';
```

> **Note:** localtunnel uses `wss://` (TLS), not `ws://`. Local-only (no tunnel) uses `ws://localhost:8084`.

### Switch base URL in Flutter

```dart
// lib/core/constants/app_strings.dart
class AppStrings {
  // ── Localtunnel dev (logs visible in terminal) ──
  static const caseReviewBaseUrl = 'https://bosc-sena-case-review.loca.lt';

  // ── EC2 production ──
  // static const caseReviewBaseUrl = 'https://<your-ec2-domain>';
}
```

---

## Summary of Dart changes required

| File | Change |
|------|--------|
| `case_review_api.dart` (or equivalent) | Add `draft(DraftTranscriptRequest)` method |
| `create_voice_session_request.dart` | Add `initialValues` field |
| `draft_transcript_response.dart` | New model |
| Navigation / routing | Add transcript screen + draft preview screen |
| Voice form widget | Render `source: "system"` fields with AI Draft chip |
