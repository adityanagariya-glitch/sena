# SENA Improvements — Receptionist Lift

**Updated:** 2026-05-22
**Scope:** patterns to lift from the Pipecat-based AI Healthcare Receptionist reference (`sena-mobile/sena-mobile/{prompt.py,PIPELINE.md,AGENTS.md}`) into SENA voice services.
**Constraint:** stay on `gemini-3.1-flash-live-preview`. We're learning approaches, not transports.

---

## What this system is (reference, not target)

A Pipecat-based 24x7 AI Healthcare Receptionist for medical clinics. Inbound Twilio PSTN call → Deepgram STT → Pipecat pipeline → Bedrock Claude Haiku 4.5 → ElevenLabs TTS → Twilio out. Backend integrations to Halo Connect (practice management) for patient records, appointments, billing.

We are NOT adopting the framework. We ARE lifting the architectural patterns.

---

## Architectural pattern map

### 1. PromptBuilder as a FrameProcessor — state-machine-driven prompt swap

The receptionist's `PromptBuilder` sits between user-turn aggregator and the LLM. On every turn it:

1. Reads current `CONVERSATION_STATE` enum (IDENTIFY_CALL_PURPOSE, GET_PATIENT_RECORD, APPOINTMENT_MANAGEMENT, GENERAL_INQUIRY, EMERGENCY).
2. Swaps in a short, focused prompt for that state only (40–250 lines each, NOT a monolith).
3. Swaps in a state-specific tool subset — `IDENTIFY_CALL_PURPOSE` exposes only `collect_call_purpose`, etc.
4. Always appends 2 terminal tools (`end_conversation`, `transfer_to_frontdesk`).
5. A separate `EMERGENCY_CHECKING_PROMPT` sub-call detects safety issues independently each turn.

**Why our 663-line monolith is the wrong shape:** ALL 24 rules ship every turn. The reference proves slicing into ~5–7 focused prompts makes the agent MORE reliable — less attention dilution.

**How SENA adopts this:** SENA's per-screen Gemini Live session model is a natural fit. Each onboarding step (or case-note section) = fresh WS session = fresh `system_instruction` = de facto state swap. We don't need mid-session injection hacks — the session boundary IS the state transition.

For case-note voice we'd have ~8 states (one per form section + READBACK_AND_CONFIRM + SUBMITTING).

### 2. BaseIntegration + per-domain subclass tool registration

The receptionist's 4 integrations (`ConfigTools`, `BPAppointmentHandling`, `BPBillingIntegration`, `BPPatientIdentification`) all extend `BaseIntegration`. `BaseIntegration.register_tools(llm)` reads `get_tools_list()`, wraps each in a traced callback, routes by name to a method on the instance. `_no_rerun_tools` list marks terminal tools.

This is much cleaner than SENA's one-class `ToolDispatcher` with 10 handlers as methods.

**How SENA adopts this:** for `restrictive_practices` day one, split `voice/tools.py` into:

```
voice/tools/
├── base.py            BaseToolProvider — registration, error format, transcript write
├── case_note.py       update_field, clear_field
└── compliance.py      advance_step, escalate_incident
```

Adding tools later becomes "new class," not "surgery on 2000 lines." Also smooths the eventual `voice_bridge` extraction since each integration is already shaped like a `ToolProvider`.

### 3. Pre-fetch + in-memory cache (SlotCache pattern)

The receptionist background-fetches doctor slots at call start; first tool call hits a hot cache.

**How SENA adopts this:** while the worker is dictating section 1 of a case note, run the LLM-/draft pipeline IN PARALLEL on the running transcript so sections 2–7 have suggested values ready when the agent reaches them. Agent says *"I heard you mention X earlier — does that go here?"* instead of asking cold.

### 4. Long-tool-call audio feedback

A `function_detector` plays "please hold" + a typing loop while tools >1s run. Idle timeout is suspended during long tool calls.

**How SENA adopts this:** for `restrictive_practices`, `advance_step` runs triage→RAG→evaluator→cross-check→summary, ~5–15s. Without audio feedback the worker thinks the session hung.

- Server emits `processing_started` event before pipeline call
- Pre-rendered "let me check that" WAV streams during the tool window
- Flutter plays the holding tone
- Idle timeout suspended for the duration

Onboarding gets the same treatment for `advance_step` (1–5s with validators + webhook + retries).

### 5. MasterDataConfig + PatientData per-call dataclass — eager domain context at session create

Pre-fetched at call start: clinic metadata, doctors list, knowledge-base vector store, patient records matching caller number, DVA/pension entitlements. The agent reasons with this context locally — no API roundtrip during the chat.

**How SENA adopts this:** at session-create, build a `ClientShiftContext` with:
- Active BSP from existing `GET /v1/restrictive-practices/bsp/{client_id}` (authorised restrictive practices)
- Top 3 most-recent case notes for that client (known triggers / risk markers)
- Worker's qualifications + authorisation level

Then the agent can say *"I see your BSP authorises PRN diazepam — was that what you administered?"* instead of generic prompts.

For onboarding this is already done via the cross-screen bucket — document the pattern as canonical.

### 6. Per-call transcript file + S3 upload on close

`data/transcripts/live_calls/{call_id}.json` opened at pipeline start; uploaded to S3 on `on_pipeline_finished`; local file unlinked.

**How SENA adopts this:** SENA has Redis ring buffers but no durable archive. Add S3 upload inside the same coroutine that fires the webhook on `step_completed`. NDIS APP 11 audit + legal need it.

Path shape: `s3://{bucket}/sena/transcripts/{tenant_id}/{step_id}/{YYYY}/{MM}/{DD}/{session_id}.json`. Tenant prefix MANDATORY for NDIS APP 8 data-residency partitioning.

### 7. Frame-level observability (LLMObs + Datadog) — selective

The receptionist's `_run_bot_impl` opens an LLMObs `phone_call` workflow span tagged with `clinic` + `call_sid`; annotates "Call completed" at end.

**How SENA adopts this:** wrap each WS session in a `voice_session` workflow span. Tag with `tenant_id`, `participant_id`, `step_id`, `session_id`. Annotate `"session completed"` on clean close, `"session errored"` on exception. Today we have `session_id` in every structlog line but no aggregated view — per-session timeline triage requires grepping JSONL.

---

## What NOT to borrow

| Anti-pattern | Why skip |
|---|---|
| Pipecat framework | They need it for PSTN+STT+LLM+TTS swaps. Gemini Live is all four in one WebSocket. Adopting Pipecat = 6-month rewrite for zero gain. |
| Twilio + Deepgram + ElevenLabs | Three external services per call. Gemini Live native audio (16k in / 24k out) is sufficient. |
| Emergency check as a separate Bedrock call per turn | At our turn rate this is expensive. Better: a single rule in the main prompt + trust the agent to call `escalate_incident` on triggers (self-harm, abuse, imminent injury). |
| 1451-line `prompt.py` | Half of it is anti-slop verbosity. Stay tight — SENA's 4f391c7 strip taught us this (1116 → 663 lines). |
| Stored procedures + raw SQL | They inherited a 20-year-old PMS. We have Pydantic + SQLAlchemy. Don't copy. |
| Per-turn `temperature=0` `max_tokens=100` | Reasonable for one-shot receptionist replies, too constraining for case-note dictation that needs to capture compound phrases. Keep our adaptive settings. |
| AMD (Answering Machine Detection) | We're inbound (Flutter WS) only. No PSTN. |
| Phonetic name matching (Metaphone/Soundex) | STT hint injection at session create is the lighter equivalent — list known participant first names with high prior, ASR variance drops. |

---

## Concrete diffs to apply

The canonical execution target is `~/.claude/plans/jazzy-imagining-hollerith.md` (voice assistant for `restrictive_practices`). These diffs apply ON TOP of that plan.

| Plan section | Diff |
|---|---|
| §1 layout | Split `voice/tools.py` → `voice/tools/{case_note,compliance,base}.py` |
| §6 dispatcher | Compose `BaseIntegration` subclasses; pass list to `VoiceSession` |
| §7 prompt | Split 1 prompt file → ~8 state-specific prompts + shared invariants prefix |
| §8 prompt builder | Add `select_prompt_for_state()`; track `CaseNoteVoiceState.conversation_state` (per-screen Gemini Live session = de-facto state machine — no mid-session injection needed) |
| §9 `advance_step` | Emit `processing_started` before pipeline; S3 upload transcript on success |
| §9 voice routes | Eager-load `ClientShiftContext` from BSP + recent case notes at session create |
| §10 tests | Cover state transitions + per-state tool subset visibility |
| §11 evaluate inline | Stays — but now the agent has BSP context for the conversation BEFORE submission |

---

## Onboarding back-port

The same patterns improve the existing onboarding service. Light touch, no behaviour change:

| Pattern | Onboarding back-port |
|---|---|
| #2 BaseIntegration | Split `services/onboarding/.../tools.py` (~2000 lines) into a base class + concern subclasses. Each subclass extracted in its own commit. Tests pass unchanged. Sets the natural shape for the `ToolProvider` protocol in the `voice_bridge` extraction. |
| #4 Audio masking | Wire pre-rendered "let me check that" WAV for `advance_step` (1–5s with validators + webhook). Feature-flag, Flutter opt-in via `Sec-WebSocket-Protocol`. |
| #6 S3 archive | Add transcript upload on WS close. Tenant-prefixed path. Fire-and-forget; failure does not block close. |
| #7 LLMObs span | Wrap `GeminiLiveSession.run()` in a workflow span. ~3 h work, no behavioural risk. |
| #5 Eager context | Already done via cross-screen bucket. Document as canonical pattern. |

---

## One-line summary

> **Steal:** state-machine-driven prompt swap (per-screen session = natural fit), composable `BaseIntegration` tool classes, parallel pre-fetch during dictation, "please hold" audio for long pipeline calls, eager domain context (BSP + recent notes) at session start, S3 transcript archive, LLMObs span tagging.
>
> **Skip:** Pipecat, multi-vendor audio stack, per-turn emergency sub-call, prompt verbosity, stored procedures, AMD, phonetic matching.

---

## Cross-references

- **Canonical execution plan:** `~/.claude/plans/jazzy-imagining-hollerith.md` — voice assistant for `restrictive_practices`
- **Voice patterns deep-dive:** `sena-ai/SENA_VOICE_IMPROVEMENTS_PLAN.md` — 15 patterns from the same receptionist analysis (this file is the architectural overlay)
- **Shared library extraction:** `sena-ai/VOICE_BRIDGE_EXTRACTION_PLAN.md` — `BaseIntegration` refactor (pattern #2) feeds directly into this
- **Reference source files:** `sena-mobile/sena-mobile/prompt.py`, `PIPELINE.md`, `AGENTS.md` (read-only)
- **Current onboarding prompt:** `sena-ai/services/onboarding/src/onboarding/prompts/onboarding_system.md` (663 lines, target for per-state split under pattern #1)

---

**End of plan.** Execute via the canonical `jazzy-imagining-hollerith.md` plan. This file is the architectural reference for WHY the diffs in that plan exist.
