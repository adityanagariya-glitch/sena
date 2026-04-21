# Voice Assistant — What `gemini-3.1-flash-live-preview` Can Do Natively

> Scope: voice assistant features only. "Native" = Gemini handles it inside the Live API, no external RAG/OCR/DB layer needed (backend may still persist the result).

Based on the Gemini Live skill (`~/.claude/skills/gemini-live-api-dev/SKILL.md`) capabilities list.

---

## ✅ Fully native — no extra infra

| # | Feature | What Gemini does | Config / API |
|---|---------|------------------|--------------|
| 1 | Multi-turn voice conversation | STT → LLM → TTS, VAD turn detection | `send_realtime_input(audio=Blob)` + `realtime_input_config` ✅ DONE |
| 2 | Form-aware system prompt | Remembers FormState schema + field order | `system_instruction=types.Content(...)` — just add the schema text |
| 3 | Function / tool calling | Decides when to call a tool mid-conversation, fills args from speech | `tools=[types.Tool(function_declarations=[...])]` in config |
| 4 | Input audio transcription | Logs what user said | `input_audio_transcription=AudioTranscriptionConfig()` ✅ DONE |
| 5 | Output audio transcription | Logs what Gemini said | `output_audio_transcription=AudioTranscriptionConfig()` ✅ DONE |
| 6 | Barge-in / interruption | Stops speaking when user speaks over it | `activity_handling=START_OF_ACTIVITY_INTERRUPTS` ✅ DONE |
| 7 | Camera frame input | Accepts JPEG frames, describes visually | `send_realtime_input(video=Blob(mime_type="image/jpeg"))` |
| 8 | Screen capture frames | Same as camera — any JPEG | Same `video=Blob(...)` pattern |
| 9 | Mixed text + audio input | User can type during voice session | `send_realtime_input(text="...")` |
| 10 | Automatic language switching | 70+ languages, detects and switches | Nothing to configure |
| 11 | Google Search grounding | Live web results for NDIS facts | Enable `google_search` tool in config |
| 12 | Session resumption | Session survives ~10min WS lifetime | `session_resumption=SessionResumptionConfig(handle=...)` ✅ partial |
| 13 | Context compression | >15 min sessions stay under 128K | `context_window_compression=ContextWindowCompressionConfig(...)` |
| 14 | Ephemeral tokens | Browser-side auth without exposing API key | `client.auth_tokens.create(...)` |
| 15 | Thinking level | Tune latency vs reasoning depth | `thinking_config=ThinkingConfig(thinking_level=...)` |

## ⚠️ Tool fires natively, backend must execute

Gemini emits the function call, your server runs the side effect and returns the result. All tools in the NDIS spec fit here:

| Tool | Gemini role | Your backend role |
|------|-------------|-------------------|
| `update_field(field_id, value, confidence)` | parses speech → emits call | writes Redis/DB, validates format |
| `get_session_context()` | emits call when unsure | returns current FormState JSON |
| `escalate_incident(description)` | emits call on user request | creates ticket, notifies supervisor |
| `describe_camera_image(prompt)` | Native — just feed frames via `video=Blob`, ask in prompt | none — fully handled by Gemini |
| `lookup_ndis_policy(query)` | emits call | RAG search over pgvector, returns snippet |

## ❌ Cannot be done by Gemini alone

- **RAG over NDIS documents** — need your own pgvector store + structure-aware chunking
- **OCR / document parsing** — need OCR model (planned `ocr-service`)
- **Multi-tenant data isolation** — backend RLS
- **JWT auth / user identity** — backend middleware
- **Persistent storage of form state / case notes** — backend DB writes
- **Approval workflow** — backend state machine
- **Audit trail** — backend logging
- **Proactive audio** (model speaks first unprompted) — not supported on 3.1 preview
- **Affective dialogue** (emotional tone control) — not supported on 3.1 preview
- **Async function calling** — synchronous only; model waits for tool result

---

## Recommended next-step order (voice only, Gemini-native only)

1. **Form-aware system prompt** — inject FormState schema as `system_instruction` text. Zero new infra.
2. **Tool calling scaffold** — add `tools=[...]` with `update_field`, `get_session_context`, `escalate_incident` function declarations. Backend handlers stub-return `{"ok": true}` initially.
3. **Input transcription-driven validation** — use `USER_SAID` text to log what field got what answer.
4. **Camera frame support** — add browser `getUserMedia({video:true})` + periodic `canvas.toBlob('image/jpeg')` → server → `send_realtime_input(video=Blob)`. Enables `describe_camera_image` with zero extra model.
5. **Screen state frames** — same pipeline, but `<canvas>` of the current form. Agent sees which field is focused.
6. **Session resumption** — persist `handle` between reconnects so 10-minute WS limit doesn't kill long onboardings.
7. **Google Search grounding** — turn on for generic NDIS policy questions while RAG is still blocked on client samples.

Everything in this list can be built incrementally on top of the working demo stack — no changes to production voice service required.
