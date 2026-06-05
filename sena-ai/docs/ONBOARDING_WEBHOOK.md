# Onboarding Voice Session — Webhook Contract

When the voice assistant completes an onboarding step (participant says "yes, submit" and all
required fields pass validation), SENA AI fires an outbound webhook to your backend. This
document tells you everything you need to persist the collected state.

---

## Trigger flow

```
Participant: "Yes, submit it."
    │
    ▼
advance_step() validates FormState
    │  all required fields filled
    ▼
POST  <APP_WEBHOOK_URL>          ← server-to-server webhook (this doc)
    │
    ▼ (simultaneous)
WS event  step_completed         ← Flutter client notification (close session UI)
```

---

## Webhook request

**Method:** `POST`  
**URL:** value of env var `SENA_AI_APP_WEBHOOK_URL`  
**Content-Type:** `application/json`  
**Timeout:** 10 s  
**Retries:** 3 attempts with exponential backoff — 1 s → 4 s → 16 s

### Headers

| Header | Value | Notes |
|--------|-------|-------|
| `Content-Type` | `application/json` | Always |
| `X-SENA-AI-Event` | `onboarding.session.completed` | Event type |
| `X-SENA-AI-Signature` | `<hex string>` | HMAC-SHA256 of raw body (see below) |
| `X-SENA-AI-Timestamp` | `2026-05-19T10:15:01.000Z` | UTC ISO 8601 |

### Signature verification

```python
import hashlib, hmac, json

def verify(body_bytes: bytes, signature_header: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)
```

- `body_bytes` — the raw POST body exactly as received (do not parse then re-serialise)
- `secret` — the value you set in `SENA_AI_APP_WEBHOOK_SECRET` on the SENA side
- Return **400** if verification fails; SENA will NOT retry a 4xx response

---

## Payload shape

```jsonc
{
  "event": "onboarding.session.completed",
  "session_id": "73514488-1bba-4f9f-b39f-5452d07c32b4",
  "participant_id": "14b4a183-6ccc-453e-9aea-ef552a7dcccc",
  "tenant_id": "3f7279a3-7da0-45d6-9c8b-4a4bd3bd096a",
  "step": "personal_information",
  "started_at": "2026-05-19T10:15:26.476Z",
  "completed_at": "2026-05-19T10:15:01.000Z",
  "transcript": [
    { "speaker": "user", "text": "Hi", "turn_id": 0, "timestamp": "..." },
    { "speaker": "agent", "text": "Hi Aditya...", "turn_id": 1, "timestamp": "..." }
  ],
  "state": { /* FormState — see below */ }
}
```

---

## FormState — the data you need to save

`state.values` is the collected form data. Structure depends on section type.

### Scalar section (one set of fields)

```jsonc
"basics": {
  "full_name":   { "value": "Aditya Nagariya", "source": "app",   "confidence": null },
  "phone":       { "value": "+61482698312",    "source": "voice", "confidence": 1.0  },
  "email":       { "value": "aditya@example.com", "source": "app", "confidence": null },
  "date_of_birth": { "value": "2000-02-25",   "source": "app",   "confidence": null },
  "gender":      { "value": "male",           "source": "voice", "confidence": 0.95 }
}
```

### Repeatable section (list of rows, e.g. emergency contacts)

```jsonc
"emergency_contacts": [
  {
    "name":     { "value": "Ethan Hunt",          "source": "voice", "confidence": 1.0 },
    "relation": { "value": "Friend",              "source": "voice", "confidence": 1.0 },
    "email":    { "value": "ethan.hunt@abc.com",  "source": "voice", "confidence": 1.0 },
    "phone":    { "value": "+61400013999",         "source": "voice", "confidence": 1.0 }
  }
]
```

### FieldValue fields

| Field | Type | Notes |
|-------|------|-------|
| `value` | any | The captured value. Type matches the field schema (string, bool, list of strings, etc.) |
| `source` | `"voice"` \| `"app"` | `"voice"` = captured by the assistant. `"app"` = pre-filled by your app at session create |
| `confidence` | `float 0–1` \| `null` | Confidence from voice capture. Null for app-seeded values |
| `turn_id` | `int` \| `null` | Which voice turn captured this value |
| `updated_at` | ISO string \| `null` | Last write timestamp |
| `input_method` | `"voice"` \| `"typed"` \| `null` | How the value was entered |

### Completion stats

```jsonc
"completion": {
  "required_total":  8,
  "required_filled": 8,
  "optional_total":  3,
  "optional_filled": 1
}
```

---

## Minimal persistence logic (pseudocode)

```python
@app.post("/webhooks/sena")
async def receive_webhook(request: Request):
    body = await request.body()

    # 1. Verify signature
    if not verify(body, request.headers["X-SENA-AI-Signature"], WEBHOOK_SECRET):
        return Response(status_code=400)

    data = json.loads(body)
    if data["event"] != "onboarding.session.completed":
        return Response(status_code=200)   # ack unknown events

    state   = data["state"]
    step    = data["step"]          # e.g. "personal_information"
    p_id    = data["participant_id"]
    values  = state["values"]

    # 2. Extract what you need per step
    if step == "personal_information":
        basics = values.get("basics", {})
        save_personal_info(p_id, {
            "full_name":     basics.get("full_name", {}).get("value"),
            "phone":         basics.get("phone",     {}).get("value"),
            "email":         basics.get("email",     {}).get("value"),
            # ... other fields
        })

        contacts = values.get("emergency_contacts", [])
        save_emergency_contacts(p_id, [
            {
                "name":     row.get("name",     {}).get("value"),
                "relation": row.get("relation", {}).get("value"),
                "email":    row.get("email",    {}).get("value"),
                "phone":    row.get("phone",    {}).get("value"),
            }
            for row in contacts
        ])

    # 3. Return 2xx within 10 s to acknowledge
    return Response(status_code=200)
```

---

## Fallback: REST polling

If your webhook endpoint is temporarily down, the state is still available via:

```
GET /v1/onboarding/session/{session_id}/state
```

Returns the full `FormState`. Safe to poll after the `step_completed` WS event fires on
the Flutter side.

---

## Flutter `step_completed` event (parallel notification)

When the voice assistant submits, the Flutter client also receives a WS event:

```json
{ "type": "step_completed", "webhook_delivered": true }
```

- `webhook_delivered: true` — webhook was accepted by your backend
- `webhook_delivered: false` — all 3 webhook attempts failed; use the REST fallback above

Flutter must close the voice session and navigate to the next onboarding step when this
event fires. Do not wait for the webhook — it is server-to-server only.

---

## Environment variables to configure

| Var | Description | Example |
|-----|-------------|---------|
| `SENA_AI_APP_WEBHOOK_URL` | Your endpoint URL | `https://api.isena.org/webhooks/sena` |
| `SENA_AI_APP_WEBHOOK_SECRET` | Shared HMAC secret | any random 32-byte string |

---

## Step IDs → your onboarding step mapping

| `step` value | Screen |
|---|---|
| `personal_information` | Step 1 — name, phone, address, emergency contacts |
| `participant_requirements` | Step 2 — goals, communication, routines |
| `ndis_plan` | Step 3 — NDIS number, plan dates, management type |
| `documents` | Step 4 — uploaded documents |
| `medical_information` | Step 5 — diagnoses, medications |
| `consent` | Step 6 — consent forms |

> Step IDs are set by your app in the `POST /v1/onboarding/session` request body (`step` field).
> The table above reflects the current fixture set; add rows as new steps are onboarded.
