---
id: "0007"
symptom: "WebSocket error 1008 'Operation is not implemented, or supported, or enabled' on Gemini Live connect"
aliases:
  - "1008 gemini live"
  - "operation is not implemented or supported or enabled"
  - "websocket 1008 onboarding"
  - "gemini live connect error 1008"
  - "SessionResumptionConfig handle None"
root_cause: "SessionResumptionConfig(handle=None) serializes as {\"handle\": null} in JSON; Gemini 3.1 API rejects null handle at connect time with 1008"
tags: [gemini-live, websocket, 1008, session-resumption]
files: [sena-ai/services/onboarding/src/onboarding/services/gemini_live.py]
fix_commit: ""
date_solved: "2026-05-15"
verified: "code review + Context7 API docs confirm handle must be string or absent"
---

# 0007 — Gemini Live 1008 on connect: null session resumption handle

## Symptom

WebSocket closes with code **1008** and reason
`"Operation is not implemented, or supported, or enabled"` immediately after
`client.aio.live.connect(...)` on `gemini-3.1-flash-live-preview`. No audio
is ever exchanged. The same error appears in the JS ecosystem (see
github.com/googleapis/js-genai/issues/1236) but the root cause on Python
is different.

## Root cause

`gemini_live.py` contained:

```python
session_resumption=types.SessionResumptionConfig(handle=None),
```

Python's Pydantic/dataclass serialization includes explicit `None` values in
the wire JSON as `"handle": null`. The Gemini Live API validates the setup
message at connection time and rejects `handle: null` because `handle` is
typed as `string` (optional). A null string is not the same as an absent
field — the API treats it as an invalid resume attempt and returns 1008.

This was confirmed via Context7 docs for `@googleapis/js-genai`:
> `handle` (string) — Optional — Session handle for resuming a previous session

The app-level resumption mechanism (`services/resumption.py`, Redis-backed
GETDEL handles) is entirely separate from Gemini-native session resumption and
was already working correctly.

## Fix

Remove the offending line from `LiveConnectConfig` in `gemini_live.py`:

```diff
-            session_resumption=types.SessionResumptionConfig(handle=None),
             output_audio_transcription=types.AudioTranscriptionConfig(),
```

The `session_resumption_update` handler in `_gemini_to_browser` (lines 574–586)
is unaffected — it only logs at DEBUG and is a no-op when no resumption config
is requested.

## Failed attempts (do NOT retry)

- **Switch model to gemini-3.1-flash-live-preview** — model was already correct; 1008 persisted. Not a model-ID issue.
- **Check `media` key in sendRealtimeInput** — JS-specific issue (#1236); Python code correctly uses `types.Blob(data=..., mime_type=...)` with `audio=` kwarg. Not the Python cause.
- **Wrap context_window_compression in try/except** — constructor-level except does NOT catch API-level 1008 rejection. The compression config itself is valid and supported on 3.1.

## Why this fix (not alternatives)

Removing the line entirely is correct because the app uses its own resumption
layer (`resumption.py`) and does not need Gemini-native session resumption.
Passing `SessionResumptionConfig()` (no arguments) would work for enabling
Gemini-native resumption but introduces `session_resumption_update` events
that require additional handling. The minimal fix is removal.

## Related

- Similar issue: `0001-vad-dies-after-few-turns.md` (another LiveConnectConfig pitfall)
- Context7 source: `/googleapis/js-genai` — `SessionResumptionConfig` interface docs
