# SENA Onboarding Voice API — WebSocket Protocol

**Version:** v1  
**Endpoint:** `WSS /ws/onboarding/{session_id}[?resume=<handle>]`  
**Port:** 8083

---

## Connection Lifecycle

```
Client                          Server
  |                               |
  |-- TCP/WS upgrade -----------> |
  |<-- 101 Switching Protocols -- |
  |                               |
  |-- {"type":"start"} ---------> |  (must be first text frame)
  |<-- {"type":"ready",...} ----- |  (form state + prompt version)
  |                               |
  |-- [audio PCM16 frames] -----> |  (continuous stream)
  |<-- [audio PCM16 frames] ----- |  (Gemini speech)
  |<-- {"type":"turn_start"} ---- |
  |<-- {"type":"turn_complete"} - |
  |                               |
  |-- {"type":"stop"} ----------> |  (graceful close)
  |<-- {"type":"resumable",...} - |  (if step not complete)
  |<-- WS close 1000 ------------ |
```

---

## Query Parameters

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `resume` | string (UUID4) | No | Resumption handle issued on previous disconnect. See Phase E Resumption. |

---

## Client → Server Messages

### Binary frames
Raw PCM16, little-endian, 16 kHz mono audio. Send continuously while mic is active.

### `start`
Must be sent as the first text frame after WS upgrade.

```json
{ "type": "start" }
```

### `user_text`
Send typed text as an alternative to audio input.

```json
{ "type": "user_text", "text": "My name is Jane Smith" }
```

### `audio_end`
Signal end-of-utterance to flush Gemini's audio buffer.

```json
{ "type": "audio_end" }
```

### `screen_state`
Notify the agent of the participant's current screen state. Idempotent — identical consecutive payloads are silently dropped server-side.

```json
{
  "type": "screen_state",
  "data": {
    "current_screen": "personal_information",
    "visible_fields": ["full_name", "date_of_birth", "phone"],
    "prefilled": { "full_name": "John Smith" },
    "app_context": "user is on step 1 of 5"
  }
}
```

| Field | Type | Max | Required |
|-------|------|-----|----------|
| `data.current_screen` | string | 64 chars | No |
| `data.visible_fields` | string[] | 32 entries | No |
| `data.prefilled` | object | — | No |
| `data.app_context` | string | 256 chars | No |

**Size limit:** `SENA_AI_SCREEN_STATE_MAX_BYTES` (default 8192). Over-cap → `error` event, WS stays open.  
**Unknown keys** in `data` are silently ignored (forward-compatible).

### `stop`
Client-initiated graceful close.

```json
{ "type": "stop" }
```

---

## Server → Client Messages

### Binary frames
Raw PCM16, little-endian, 24 kHz mono. Gemini speech output.

### `ready`
Sent immediately after `start` handshake. Contains current FormState.

```json
{
  "type": "ready",
  "state": { "...FormState fields..." },
  "prompt_version": "v1"
}
```

### `turn_start`
Gemini has begun speaking (first audio chunk incoming).

```json
{ "type": "turn_start" }
```

### `turn_complete`
Gemini has finished its turn.

```json
{ "type": "turn_complete" }
```

### `interrupted`
User spoke over the agent. Client should stop audio playback.

```json
{ "type": "interrupted" }
```

### `user_said`
Input transcription — what the participant said.

```json
{ "type": "user_said", "text": "My name is Jane" }
```

### `agent_said`
Output transcription — what the agent said.

```json
{ "type": "agent_said", "text": "Hi there! I'm Sena." }
```

### `field_updated`
A form field was captured by the agent.

```json
{
  "type": "field_updated",
  "section": "basics",
  "field": "full_name",
  "value": "Jane Smith",
  "repeatable_index": null,
  "confidence": 0.95,
  "turn_id": 2
}
```

### `state`
Full FormState snapshot after any field update.

```json
{ "type": "state", "state": { "...FormState fields..." } }
```

### `step_completed`
Step is done. Webhook has been fired. WS will close after agent farewell.

```json
{
  "type": "step_completed",
  "state": { "...FormState fields..." },
  "webhook_delivered": true
}
```

### `escalated`
Safety incident flagged. Session continues.

```json
{
  "type": "escalated",
  "reason": "abuse",
  "transcript_excerpt": "my carer hit me"
}
```

### `resumable`
Sent immediately before graceful close when the step is NOT yet complete.  
Client must store the handle and pass it as `?resume=<handle>` on reconnect.

```json
{
  "type": "resumable",
  "handle": "550e8400-e29b-41d4-a716-446655440000",
  "ttl_sec": 600
}
```

**Handle rules:**
- Opaque UUID4 — not the session_id
- Single-use: consumed on first valid redeem (GETDEL)
- Expires after `ttl_sec` seconds
- Log only first 8 chars — never full UUID in logs

### `screen_state_ack` *(debug mode only)*
Sent when `SENA_AI_DEBUG=true` after a valid `screen_state` ingestion.

```json
{ "type": "screen_state_ack", "accepted": true }
```

### `error`
Any error condition.

```json
{
  "type": "error",
  "code": "session_locked",
  "message": "Another voice connection is already active for this session"
}
```

---

## Close Codes

| Code | Name | Trigger |
|------|------|---------|
| 1000 | Normal | Graceful close (step completed or `stop` received) |
| 4004 | `session_not_found` | Session not in Redis (expired or never created) |
| 4008 | `protocol_error` | First message was not `{"type":"start"}` |
| 4009 | `session_locked` | Another WS is already active for this session |
| 4010 | `resume_invalid` | Resumption handle missing, expired, or mapped to wrong session_id |

---

## Phase E Resumption Flow

```
1. Client disconnects mid-step (network drop, app background)
2. Server emits {"type":"resumable","handle":"<uuid>","ttl_sec":600} before close
3. Client stores handle in app state
4. Client reconnects: WSS /ws/onboarding/{session_id}?resume=<handle>
5. Server validates handle (GETDEL — single-use), rehydrates FormState + transcript
6. Server injects [RESUME] text turn into Gemini so agent continues naturally
7. Client sends {"type":"start"} as normal
8. Server sends {"type":"ready"} as normal
```

**Error case:** expired or invalid handle → close 4010 `resume_invalid`.  
Client should start a fresh connection (without `?resume`) on 4010.

---

## Schema Versioning

The `prompt_version` field in `ready` is the current schema contract version.  
Breaking changes (new required fields, removed fields) increment this version.  
Non-breaking additions (new optional fields, new server envelope types) do not.  
Unknown server envelope types must be silently ignored by clients (forward-compat).

---

## Error Taxonomy

| Category | Codes | Client action |
|----------|-------|---------------|
| Session lifecycle | 4004, 4008 | Re-create session via REST |
| Concurrency | 4009 | Wait and retry, or close existing session |
| Resumption | 4010 | Reconnect without `?resume` (fresh) |
| Payload validation | `screen_state_invalid`, `screen_state_too_large` | Fix payload, WS stays open |
| Internal | `internal_error` | Log and retry |
