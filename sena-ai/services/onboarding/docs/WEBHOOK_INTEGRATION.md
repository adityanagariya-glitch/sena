# SENA Onboarding — Webhook Integration Guide

**Audience:** App backend (Flutter team / API server) developer  
**Purpose:** The onboarding voice service fires an HTTP POST to your backend when a participant completes a step. Your server must accept this event and persist the collected state.

---

## When the webhook fires

The webhook fires exactly once per completed step, via two paths:

| Trigger | Path |
|---------|------|
| Participant confirms verbally ("Yes, submit") → voice `advance_step` tool | Automatic — no REST call needed |
| App calls `POST /v1/onboarding/session/{id}/complete` | Explicit REST completion |

Both paths fire the same event with the same payload shape.

---

## Configuration (server-side env vars)

| Env var | Required | Description |
|---------|----------|-------------|
| `SENA_AI_APP_WEBHOOK_URL` | Yes | Full URL the POST is sent to, e.g. `https://api.isena.org/api/mobile/onboarding/webhook` |
| `SENA_AI_APP_WEBHOOK_SECRET` | Recommended | Shared secret for HMAC-SHA256 signature verification. Empty = no signature. |

---

## HTTP request

```
POST {SENA_AI_APP_WEBHOOK_URL}
Content-Type: application/json
X-SENA-AI-Event: onboarding.session.completed
X-SENA-AI-Signature: <hex-digest or empty>
X-SENA-AI-Timestamp: <ISO-8601 UTC>
```

**Retry policy:** 3 attempts, exponential backoff — 1 s, 4 s, 16 s. Your endpoint must return a `2xx` status to acknowledge delivery. Any non-2xx causes the next retry.

---

## Payload shape

```json
{
  "event": "onboarding.session.completed",
  "session_id": "uuid",
  "participant_id": "uuid",
  "tenant_id": "uuid | null",
  "step": "personal_information",
  "confirmation_transcript": "Yes, that looks right.",
  "started_at": "2026-05-19T10:11:41.697084+00:00",
  "completed_at": "2026-05-19T10:15:07.254Z",
  "state": { ... },
  "transcript": [ ... ]
}
```

### `state` — full FormState snapshot

```json
{
  "session_id": "uuid",
  "step_id": "personal_information",
  "participant_id": "uuid",
  "tenant_id": "uuid | null",
  "locale": "en-AU",
  "completed": true,
  "completed_at": "2026-05-19T10:15:07.254Z",
  "started_at": "2026-05-19T10:11:41.697084Z",
  "values": {
    "basics": {
      "full_name":  { "value": "Aditya Nagariya", "source": "voice", "confidence": 1.0 },
      "phone":      { "value": "+61482698312",    "source": "voice", "confidence": 1.0 },
      "email":      { "value": "aditya@yopmail.com", "source": "app", "confidence": null },
      "date_of_birth": { "value": "2000-02-25",   "source": "app",   "confidence": null }
    },
    "emergency_contacts": [
      {
        "name":     { "value": "Ethan Hunt",         "source": "voice", "confidence": 1.0 },
        "relation": { "value": "Friend",             "source": "voice", "confidence": 1.0 },
        "email":    { "value": "ethan.hunt@abc.com", "source": "voice", "confidence": 1.0 },
        "phone":    { "value": "+61400013999",       "source": "voice", "confidence": 1.0 }
      }
    ],
    "home_address": {
      "address":  { "value": "12 Main St", "source": "app", "confidence": null },
      "state":    { "value": "NSW",        "source": "app", "confidence": null },
      "city":     { "value": "Sydney",     "source": "app", "confidence": null },
      "zip_code": { "value": "2000",       "source": "app", "confidence": null }
    }
  },
  "completion": {
    "required_total": 8,
    "required_filled": 8,
    "optional_total": 3,
    "optional_filled": 1
  }
}
```

**`source` values:**

| Value | Meaning |
|-------|---------|
| `"voice"` | Captured via the voice agent this session |
| `"app"` | Pre-filled by the app at session creation (bootstrap data) |
| `"typed"` | Entered via on-screen keyboard |

**Repeatable sections** (emergency_contacts, morning_routine, etc.) are always a **JSON array** of row objects. Each row contains the same `{value, source, confidence}` FieldValue structure per field.

### `transcript` — conversation turns

```json
[
  { "speaker": "user",  "text": "Hi",                    "turn_id": 0, "timestamp": "..." },
  { "speaker": "agent", "text": "Hi Aditya, welcome...", "turn_id": 1, "timestamp": "..." }
]
```

---

## Signature verification

The `X-SENA-AI-Signature` header is an **HMAC-SHA256** hex digest of the raw request body, keyed with `SENA_AI_APP_WEBHOOK_SECRET`.

**Python verification example:**
```python
import hashlib, hmac

def verify_webhook(body: bytes, secret: str, received_sig: str) -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, received_sig)
```

**Node.js / TypeScript:**
```typescript
import { createHmac, timingSafeEqual } from 'crypto';

function verifyWebhook(body: Buffer, secret: string, receivedSig: string): boolean {
  const expected = createHmac('sha256', secret).update(body).digest('hex');
  return timingSafeEqual(Buffer.from(expected), Buffer.from(receivedSig));
}
```

If `SENA_AI_APP_WEBHOOK_SECRET` is not configured, the header value is an empty string — skip verification (dev/test only; not recommended for production).

---

## Your endpoint contract

1. **Verify signature** before processing.
2. **Parse `state.values`** and persist each field to your database under `(participant_id, step_id)`.
3. **Return `200 OK`** (or any `2xx`) immediately — do not wait for your DB write to complete before responding. Heavy processing should be async/background.
4. **Idempotency:** The same `session_id` may arrive more than once (retry storm on transient network error). Key your upsert on `session_id` + `step_id` to ensure idempotency.
5. **Mark step complete** in your onboarding progress tracker for `(participant_id, step_id)`.

---

## What NOT to do

- Do not reject the webhook because optional fields are missing — they will be absent from `values` but the step is legitimately complete.
- Do not assume all fields were filled by voice — `source: "app"` fields were pre-filled by your own app and should be treated as already valid.
- Do not hold the connection open for DB writes — the voice session is waiting for the `2xx` acknowledgement to close cleanly.

---

## Testing locally

Point `SENA_AI_APP_WEBHOOK_URL` at a local receiver (e.g. [ngrok](https://ngrok.com/) or [webhook.site](https://webhook.site)) and run a full session through the test harness at `http://localhost:8083/harness`. The server logs will show `webhook_delivered` or `webhook_failed_all_retries` so you can confirm delivery.

---

## Environment variable quick-reference

```env
SENA_AI_APP_WEBHOOK_URL=https://api.isena.org/api/mobile/onboarding/webhook
SENA_AI_APP_WEBHOOK_SECRET=your-shared-secret-here
```

Both use the `SENA_AI_` prefix — same as all other onboarding service settings.
