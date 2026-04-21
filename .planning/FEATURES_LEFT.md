# SENA — Features Left To Implement

> Snapshot: 2026-04-20. Demo voice loop working (greet + multi-turn chat). Everything below is **not yet in demo** and needs building.

Categories ordered roughly by dependency / priority.

---

## 1. System prompt + form-aware behavior
**Current:** demo has a minimal "friendly NDIS assistant" prompt; no form knowledge.

- [ ] Form-aware system prompt — inject `FormState` schema (sections, field names, field types, required vs optional) into `system_instruction`
- [ ] Deterministic question sequencing — follow Figma section order (Personal Details → Requirements → NDIS Plan → Documents → Medical)
- [ ] Re-prompt logic — if user skips or gives ambiguous value, agent asks for clarification, doesn't just move on
- [ ] Phonetic name map (`name_alias_map.py`) — so model recognises Australian/migrant names correctly (CTX-07)
- [ ] Completion detection — agent stops when all required fields filled, announces summary

## 2. Tool calling (function_tools via Gemini Live)
**Current:** none. Agent just chats.

Required tools (from `.planning` / FlowB requirements):
- [ ] `update_field(field_id, value, confidence)` — writes to Redis form state (TOOL-02)
- [ ] `get_session_context()` — agent reads current form state mid-conversation (TOOL-03)
- [ ] `lookup_ndis_policy(query)` — rule-based in v1, RAG in v2 (TOOL-04)
- [ ] `escalate_incident(description)` — creates escalation record + supervisor notify (TOOL-05)
- [ ] `describe_camera_image(image_data)` — multimodal camera frame description (TOOL-06)
- [ ] Validation layer — regex/format checks for NDIS number, Medicare, phone, DOB before accepting an `update_field`

## 3. Screen / visual context (multimodal grounding)
**Current:** none. Voice-only.

- [ ] Form screen state sync — frontend pushes current visible screen + focused field via data channel; injected into agent context on each turn
- [ ] Camera frame streaming — `send_realtime_input(video=Blob(..., image/jpeg))` for `describe_camera_image` tool
- [ ] Manual override reconciliation — if user edits form on screen, agent must see the change and skip that field
- [ ] Real-time field highlight — on `update_field` tool call, frontend highlights the filled field

## 4. Context preloading
- [ ] `context_preloader.py` — fetches participant data, shift info, form schema, NDIS goals from client platform APIs before session starts (CTX-01)
- [ ] 2s preload budget with 6-tier token prioritisation (CTX-02, CTX-03)
- [ ] Redis 15-min cache of participant context (CTX-04)
- [ ] Tenant-specific form schema load (CTX-05)
- [ ] Graceful degradation — fall back to identity-only prompt if preload fails (CTX-06)

## 5. RAG (NDIS knowledge base)
**Blocked:** waiting on sample NDIS docs from client (Q#7 in open questions).

- [ ] Structure-aware chunking (tables, numbered sections, nested headings preserved)
- [ ] pgvector store in `ai-db` (already provisioned)
- [ ] Hybrid search (vector + keyword) — decision already logged
- [ ] Per-tenant vs shared NDIS docs isolation (RLS)
- [ ] Ingestion pipeline — portal upload or API? (still open question)

## 6. Multi-tenancy + auth (legal hard constraint)
- [ ] JWT validation — flip `SENA_AI_AUTH_MODE` from `dev_header` to `jwt`; validate against client's public key
- [ ] Row-Level Security policies on every voice-related table (tenant_id session variable)
- [ ] Ensure demo path does NOT bypass RLS — currently demo has no tenant at all

## 7. Flow B — case note dictation (separate flow from personal details)
- [ ] LiveKit Agent instead of HTTP turn loop (DICT-01)
- [ ] SOAP-format dictation system prompt (DICT-02)
- [ ] `draft_case_note` tool — updates live draft in Redis during session (DICT-03)
- [ ] Session-end compile → `ApprovalQueueItem` + SNS event (DICT-04)
- [ ] Manager approve/reject workflow (already partial — `approval_service.py`) (DICT-05)

## 8. Session state + persistence
- [ ] Form state schema in `ai-db` (SQLAlchemy model)
- [ ] Session state machine — STARTED / LISTENING / PROCESSING / COMPLETE / APPROVED
- [ ] Session resume — use Gemini Live `session_resumption.handle` across reconnects
- [ ] Audit trail — every `update_field` logged (who/when/confidence/source)

## 9. Compliance / data residency
- [ ] All AI calls route through `ap-southeast-2` / Sydney region
- [ ] PII redaction log before audio/transcript storage (if stored at all)
- [ ] Retention policy per tenant
- [ ] Consent capture before session starts

## 10. Approval workflow (Flow B)
Partially implemented. Gaps:
- [ ] `/v1/approval/decision` end-to-end tested with real case note draft
- [ ] Manager notification channel (email/SNS → client platform)
- [ ] Rejection → corrective re-dictation flow

## 11. OCR service
- [ ] Currently scaffolded only. Full implementation deferred — NDIS plan / medical doc parsing
- [ ] Depends on document samples from client

## 12. Production wiring of new Gemini Live API
- [ ] `services/voice/src/voice/services/gemini_live_service.py` uses **old** API (`session.send(LiveClientRealtimeInput(media_chunks=...))`). Migrate to `send_realtime_input(audio=Blob(...))` pattern from working demo
- [ ] Reconcile `ws_routes.py` with demo's VAD config + receive-loop pattern (see `wiki/pages/gemini-live-multi-turn-config.md`)

## 13. Observability
- [ ] Structured JSON logs (session_id, tenant_id, turn_no, latency)
- [ ] Metrics — turn latency p50/p95, VAD hit-rate, tool-call success rate
- [ ] Distributed tracing for the Gemini-call → tool-call → DB-write chain

---

## What IS working today
- Gemini Live multi-turn voice (demo stack, `sena-ai/demo_*`)
- Postgres + Redis infra (docker-compose)
- Basic FastAPI scaffold for voice service
- Auth in `dev_header` mode
- SNS event publisher stub
- Wiki + graphify knowledge base

## Open questions blocking work
See `wiki/pages/open-questions.md`:
1. Complete Figma form spec (sections + field types + validation) — blocks items 1, 2
2. Sample NDIS policy documents — blocks item 5 (RAG)
3. Participant/shift/tenant API contracts from client — blocks item 4 (context preloading)
4. Client JWT claims structure — blocks item 6 (auth)
