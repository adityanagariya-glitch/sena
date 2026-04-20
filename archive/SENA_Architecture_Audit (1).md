# SENA — System Architecture Audit & Hardened Implementation Blueprint

**Audit Date:** April 2026
**Source Document:** SENA Voice Architecture & Accessibility Design Brief v1.0
**Reference Material:** Prior research audit (used as directional input, not taken as ground truth)

---

## 1. Architectural Audit & Identified Gaps

### Vague Assumptions

**Assumption 1: "Gemini Live handles VAD and turn detection reliably"**

The design brief selects LiveKit Agents with Gemini Live and states it includes "built-in VAD, barge-in, turn detection, reconnection handling." This is accurate for controlled audio environments. It is dangerously optimistic for SENA's actual deployment context — a disability support worker in a participant's home with televisions, other residents vocalising, children, pets, and road noise during transit.

The specific failure mode: Gemini's default VAD thresholds are tuned for single-speaker close-mic scenarios. In a noisy home, background voices will trigger false turn starts, causing Gemini to begin responding mid-sentence. Worse, the document describes a pause/resume flow ("hold on" → pause, "continue" → resume) but never defines how the system distinguishes the command "hold on" directed at SENA from the phrase "hold on" spoken to a participant as part of natural conversation. Without a disambiguation mechanism — either a push-to-talk hardware fallback, a wake-word prefix, or a confidence-gated command parser — the pause system will misfire constantly in real environments.

**Assumption 2: "80%+ of questions are answered instantly with zero database lookups"**

Stated twice in the design brief without measurement basis or adaptation mechanism. This ratio is plausible for simple shifts with well-known participants, but will degrade significantly for: complex participants with multi-year histories and dozens of incidents, new workers unfamiliar with participants (they ask more questions), and plan review periods when goals change and cached data becomes stale. There is no mechanism to measure this ratio in production, no telemetry to detect when it degrades, and no strategy to adapt preload content when the ratio drops below a useful threshold. If it turns out to be 50/50, the current architecture still works but the latency profile changes dramatically — half of all interactions now involve tool call latency.

**Assumption 3: "GPS capture is reliable at session start"**

The brief treats GPS as a silent background task: capture at start, ask the suburb on failure. It does not account for: GPS accuracy inside high-density apartment buildings (extremely common for NDIS participants in supported independent living), GPS permission revocation after OS updates (iOS and Android both reset location permissions periodically), or workers starting sessions while still in transit. A GPS fix captured in a moving car 10 minutes before arrival is confidently wrong but will be stored as the session location.

**Assumption 4: "Context preloader runs before the first word is spoken"**

The system prompt injection is assumed complete before the session is usable. But the preloader must hit Redis, PostgreSQL, and potentially tenant-specific configuration endpoints. If any of these are slow — a cold Redis instance, a large participant history query, a tenant config cache miss — the worker may begin speaking before the prompt is ready. The brief describes a "loading state" in the checklist but provides no implementation detail: no "SENA is getting ready" audio announcement, no partial-load fallback, and no defined behaviour for what happens when the worker speaks during INITIALISING state.

**Assumption 5: "NON_BLOCKING tool calls with WHEN_IDLE scheduling"**

These are presented as the primary RAG strategy. As of April 2026, `NON_BLOCKING` function calling behaviour and `WHEN_IDLE` scheduling are features of the Gemini Live API that have been in experimental/preview status. The brief uses them as load-bearing infrastructure without defining a fallback if the feature is removed, changed, or rate-limited differently in a future model update. This is a single point of failure for the entire tool call pipeline.

**Assumption 6: "LiveKit Agent dispatched per session — lifecycle undefined"**

The brief says "dispatch SENA agent" at session start but never defines whether agents are long-lived processes serving multiple sessions or spawned per session. If per-session: what is the cold-start time, and does it add to the preload delay? If long-lived: how is tenant isolation enforced between workers sharing an agent process? This is a security question with NDIS compliance implications — one worker must never have access to another's audio stream or participant context.

**Assumption 7: "Latency targets are achievable under load"**

The brief states ~250–320ms for no-tool-call and ~350–520ms with tool calls. These figures appear to be single-session benchmarks. There is no load context: what happens at 50 concurrent sessions? 200? The LiveKit server, the agent process pool, and Gemini's API all have throughput limits. Without load testing data or even projected concurrency targets, these numbers are aspirational, not architectural.

---

### Edge Case Matrix

| # | Category | Edge Case | Current Handling | Risk |
|---|----------|-----------|-----------------|------|
| 1 | **Network** | Worker loses 4G mid-dictation (common in regional AU) | Not defined | 🔴 |
| 2 | **Network** | LiveKit WebRTC ICE failure and reconnect | Assumed handled by LiveKit — no verification or custom behaviour | 🔴 |
| 3 | **Network** | Gemini Live WebSocket drops mid-sentence | Not defined | 🔴 |
| 4 | **Network** | High latency spike (>2s) on Gemini response — worker thinks session frozen | Not defined | 🟡 |
| 5 | **Audio** | Worker's microphone muted by OS (incoming call, notification, Bluetooth disconnect) | Not defined | 🔴 |
| 6 | **Audio** | Participant starts speaking — Gemini interprets as worker input | Mentioned in GAP 7 solution (pause/resume) but no speaker diarisation or filtering mechanism | 🔴 |
| 7 | **Audio** | Echo from speaker output fed back into microphone | Not defined | 🟡 |
| 8 | **Audio** | Worker uses speakerphone in car (echo + road noise + wind) | Not defined | 🟡 |
| 9 | **State** | Preload completes AFTER worker has already begun speaking | Not defined — no loading gate | 🔴 |
| 10 | **State** | Redis session state corrupted or evicted mid-session | Not defined | 🟡 |
| 11 | **State** | Worker taps submit twice (double-tap, network retry, accessibility switch bounce) | Not defined — no idempotency key | 🔴 |
| 12 | **State** | Supervisor opens participant profile while worker is mid-session editing a draft | Not defined — no optimistic locking or conflict detection | 🔴 |
| 13 | **State** | Worker resumes a draft from yesterday but participant data has changed overnight | Not defined — stale context in resumed session | 🟡 |
| 14 | **Concurrency** | 50+ workers start sessions simultaneously — Gemini rate limit hit | Not defined | 🔴 |
| 15 | **Concurrency** | Two workers accidentally assigned the same LiveKit room name | Not defined — room name generation strategy unclear | 🔴 |
| 16 | **Concurrency** | Agent process pool exhausted — new sessions queued | Not defined | 🟡 |
| 17 | **Data** | Participant has no NDIS goals (new participant, plan pending, plan expired) | Not defined | 🟡 |
| 18 | **Data** | Redis cache TTL expires mid-session (15min participant cache) | Not defined — session could lose context | 🟡 |
| 19 | **Data** | New participant added to tenant today — phonetic alias map not yet populated | No real-time update mechanism defined | 🟡 |
| 20 | **Data** | Form schema changes mid-session (admin updates template while worker is active) | Not defined | 🟢 |
| 21 | **Compliance** | Audit log write fails at submission time | Not defined — submission may proceed without audit trail | 🔴 |
| 22 | **Compliance** | Gemini returns PII in a tool call response that gets logged verbatim to observability stack | Not defined — no PII scrubbing layer | 🟡 |
| 23 | **Compliance** | Worker records audio of a participant who has not consented to recording | Not defined — no consent verification gate | 🟡 |
| 24 | **AI** | Gemini hallucinates participant details not present in system prompt | No output validation layer | 🔴 |
| 25 | **AI** | Gemini refuses a request due to safety filter (e.g., incident involving self-harm description) | Not defined | 🟡 |
| 26 | **AI** | System prompt exceeds Gemini context window for a participant with 3+ years of history | Mentioned in brief as "everything preloaded" — no truncation strategy | 🔴 |
| 27 | **AI** | Gemini model version changes and tool call behaviour changes | NON_BLOCKING is experimental — no version pinning strategy | 🟡 |
| 28 | **Recovery** | App crashes mid-readback — draft exists but worker doesn't know | No notification mechanism for orphaned drafts | 🟡 |
| 29 | **Recovery** | Phone battery dies mid-session — partial transcript in Redis, no submission | Not defined — no auto-draft-save on connection drop | 🟡 |
| 30 | **Recovery** | Worker force-closes app during submission — transaction half-complete | Not defined — no saga pattern or idempotent submission | 🔴 |

---

### Macro-Level Blind Spots

**Blind Spot 1: No Observability Architecture**

The design brief mentions "audit logging hooks" as a late implementation task. This is architecturally backwards. Without observability from day one, you cannot diagnose why a session was slow, whether a compliance event was logged, what Gemini actually said in a disputed note, or what the cost per session was. There is no defined: structured log schema, distributed trace ID propagation (a single ID flowing from mobile → LiveKit → Agent → Gemini → DB → audit), latency SLO alerting, or per-tenant cost monitoring. These must exist before application code is written, not after.

**Blind Spot 2: No Multi-Tenancy Model**

The brief is written as though SENA serves a single organisation. NDIS providers often operate as franchises — there are hundreds of separate provider organisations, each with their own participants, workers, compliance requirements, and data isolation obligations. The document has no tenant ID propagation through the stack, no per-tenant rate limiting, no per-tenant Redis namespace isolation, no per-tenant form schema configuration, and no per-tenant cost tracking. A single shared Redis keyspace means a bug in key generation could leak one tenant's participant data to another — a catastrophic compliance failure under the Privacy Act.

**Blind Spot 3: No Fallback Voice Pipeline**

The brief mentions "degrade to text-based Claude if Gemini fails" without defining what "text-based" means for a system whose primary users are blind. "Degrade to text" is not a degradation for a blind worker — it is a total loss of service. The fallback must itself be voice-capable. This requires a defined alternative STT→LLM→TTS pipeline (e.g., Deepgram → Claude → ElevenLabs) that activates when the Gemini circuit breaker opens. The brief does not define this pipeline, its latency characteristics, or how context is transferred from a failed Gemini session to the fallback.

**Blind Spot 4: No Note Versioning or Conflict Resolution**

Worker starts a note, gets interrupted, saves a draft. Later, a supervisor views the participant's profile and sees the draft. Worker resumes and submits. Meanwhile the participant's NDIS plan was updated. There is no version conflict resolution, no optimistic locking on draft records, and no mechanism to inform the worker that underlying data changed while they were drafting. In a voice-only interface, conflict resolution is especially hard — you can't show a diff. This needs explicit design.

**Blind Spot 5: No Cost Ceiling or Zombie Session Protection**

Gemini Live charges by audio-minutes. A worker who leaves a session open accidentally — phone in pocket, session not explicitly closed — will stream continuous audio. There is no maximum session duration, no idle-audio detection to auto-close, and no per-worker or per-tenant cost ceiling. At scale (hundreds of workers across multiple tenants), a handful of zombie sessions per day could generate significant unexpected cost.

**Blind Spot 6: Context Window Budget Management**

The brief recommends preloading "everything" — participant history, form fields, validation rules, NDIS goals, phonetic maps. For a long-term participant with 3+ years of notes, multiple incidents, and several plan reviews, this preload could exceed Gemini's context window. There is no defined truncation strategy, no priority ordering of what to include when space is limited, and no detection mechanism for when the prompt approaches the limit. Silently exceeding the context window can cause Gemini to drop the earliest content (often the system instructions) — a silent, catastrophic failure.

**Blind Spot 7: Post-Submission Event Architecture**

The brief traces the note lifecycle to "approval queue" and stops. There is no defined event or notification for: approval completed (does the worker hear about it?), approval rejected with changes required (how is this communicated to a voice-only user?), supervisor override (supervisor edits a note after submission — does the worker know?), or escalation timeout (an incident report sits in the queue for 24 hours with no approval). The entire downstream lifecycle after submission is unspecified.

**Blind Spot 8: Mobile App Resilience and Offline Behaviour**

The brief focuses entirely on the server-side voice pipeline. The mobile app's behaviour during network interruptions, backgrounding, low memory, OS-level audio interrupts (incoming call, alarm), and offline scenarios is not addressed. For a voice-first app that blind users depend on, the mobile client's resilience is as critical as the server architecture.

**Blind Spot 9: Consent and Audio Retention Policy**

SENA streams participant audio through its servers for processing. The brief addresses APP 8 (cross-border transfer) and APP 11 (security), but does not define: whether raw audio is retained and for how long, who can access audio recordings, whether participants must consent to AI-assisted note-taking, or what happens when a participant (or their guardian) requests deletion of all their data. NDIS participants are vulnerable persons — the consent model needs explicit definition.

---

## 2. Hardened System Architecture Design

### Core Architectural Principles

1. **Explicit State Machine with Persisted Transitions** — Every session has a finite set of states with defined transitions, error states, and recovery actions. State is persisted to Redis on every transition. If anything crashes, the system resumes from the last persisted state — not from the beginning.

2. **Circuit Breakers on Every External Dependency, Independently Configured** — Gemini Live, LiveKit, Redis, PostgreSQL, GPS service, and the Audit Log each have their own circuit breaker with tuned thresholds. A Gemini outage does not take down PostgreSQL writes. A Redis failure does not block audit logging.

3. **Trace-First Observability** — A `session_trace_id` (UUID v7, sortable) is minted at session creation and propagates through every log line, every service call, every DB write, every Gemini interaction. This is the single correlation key for debugging, compliance, and cost attribution.

4. **Tenant Isolation at Every Layer** — `tenant_id` is a first-class citizen in Redis key prefixes, DB row-level security, LiveKit room naming, log line fields, and cost aggregation. There is no shared namespace where tenant data can collide.

5. **Graceful Degradation Ladder Preserving Voice** — The system has defined fallback levels, each of which preserves voice capability. "Degrade to text" is not a valid fallback for this system. Every level must support a blind user.

6. **Defence in Depth for Data Integrity** — No note is ever lost. Drafts are auto-saved. Submissions use a saga pattern with compensating actions. Audit log failure blocks submission (not the other way around). Idempotency keys prevent double-submit.

### Session State Machine

```
INITIALISING
    │ Context preload + LiveKit room + GPS all dispatched
    │
    ├─ (preload complete, room ready) ──→ READY_TO_START
    │                                        │
    │                                        │ (worker says "start" or equivalent)
    │                                        ▼
    │                                    ACTIVE_DICTATION ◄──────────────┐
    │                                        │                          │
    │                                        ├─ ("hold on" / "pause")   │
    │                                        ▼                          │
    │                                    PAUSED ───("continue")────────┘
    │                                        │
    │                                        ├─ ("submit" / "I'm done")
    │                                        ▼
    │                                    PENDING_READBACK
    │                                        │ (full readback complete)
    │                                        │ (worker says "I confirm")
    │                                        ▼
    │                                    PENDING_SUBMISSION
    │                                        │ (DB + audit + queue all succeed)
    │                                        ▼
    │                                    SUBMITTED
    │                                        │ (async approval event)
    │                                        ▼
    │                                    APPROVED | RETURNED_FOR_CHANGES
    │
    ├─ (preload timeout/fail) ──→ PRELOAD_FAILED
    │                                → Recovery: retry once with partial prompt,
    │                                  announce "Give me a moment"
    │                                → If retry fails: start with minimal prompt
    │                                  (identity + form fields only), log DEGRADED
    │
    ├─ (connection lost)     ──→ CONNECTION_LOST
    │                                → Recovery: auto-save draft to Redis,
    │                                  on reconnect resume from persisted state
    │                                → Worker hears: "Connection lost. Your work
    │                                  is saved. Reconnecting..."
    │
    └─ (submission fails)    ──→ SUBMISSION_FAILED
                                     → Recovery: draft preserved in Redis (24h TTL),
                                       worker hears: "I had trouble saving. Your
                                       note is safe as a draft. Try again shortly."
                                     → Retry with exponential backoff (max 3 attempts)

TIMEOUT states:
    IDLE_WARNING  — 90s silence → "Are you still there?"
    IDLE_TIMEOUT  — 120s silence → auto-save draft, end session
    COST_WARNING  — 20min audio → verbal warning
    COST_TIMEOUT  — 30min audio → force save draft, end session
```

Every state transition persists to Redis: `{previous_state, new_state, timestamp, trigger_event, session_trace_id}`. On crash recovery, the system reads the last persisted state and resumes.

### Graceful Degradation Ladder

```
Level 0 (Normal):
    Pipeline: Gemini Live API (unified STT + reasoning + TTS)
    Features: Full context preload, NON_BLOCKING tool calls, ~250-320ms latency
    Activation: Default when all systems healthy

Level 1 (Degraded Gemini):
    Pipeline: Gemini Live API with BLOCKING tool calls only
    Features: NON_BLOCKING unavailable; worker hears "One moment..." during lookups
    Activation: NON_BLOCKING feature errors detected (3 failures in 60s)
    Latency: ~400-600ms with tool calls

Level 2 (Alternative Voice Pipeline):
    Pipeline: Deepgram STT → Claude Sonnet API → ElevenLabs TTS
    Features: Separate services, still fully voice-capable
    Activation: Gemini Live circuit breaker opens
    Latency: ~600-900ms
    Context: System prompt transferred from Redis (same prompt, different LLM)

Level 3 (Minimal Voice):
    Pipeline: Deepgram STT → Rule-based field prompter → ElevenLabs TTS
    Features: No LLM reasoning — sequential field-by-field prompting
    Activation: All LLM providers (Gemini + Claude) unavailable
    Latency: ~300-500ms (no reasoning delay)

Level 4 (Emergency — Record Only):
    Pipeline: Raw audio → S3 storage → async transcription later
    Features: Worker dictates freely, transcription and structuring done offline
    Activation: All real-time processing fails
    Worker hears: "I'm having technical difficulties. I'll record everything
    and process it later. Just speak naturally."
```

Degradation level is set per-session at initialisation. Existing sessions are NOT migrated mid-conversation unless a hard failure forces it. New sessions start at whatever level the circuit breakers currently indicate.

### Infrastructure Components

| Component | Responsibility | Status |
|-----------|---------------|--------|
| **Session Orchestrator** | Owns state machine. Mints trace IDs. Dispatches agents. Enforces timeouts. Coordinates preload, GPS, and LiveKit room creation. | New — currently implicit in routes.py |
| **Context Preloader** | Builds system prompt from Redis/DB within 2s SLA. Token budget guard. Priority-based truncation. | Formalised — partially described in brief |
| **Audit Log Service** | Append-only log of all LLM I/O, tool calls, submissions, state transitions. Separate database from application DB. | New |
| **Cost Governor** | Tracks audio-minutes per session and per tenant. Enforces time limits. Produces daily cost reports. | New |
| **Note Version Store** | Versioned drafts with content hashing. Optimistic locking on submission. Conflict detection and verbal resolution. | New |
| **Degradation Manager** | Monitors circuit breaker states. Sets degradation level for new sessions. Manages fallback pipeline instantiation. | New |
| **PII Filter** | Scrubs PII from all log/observability output before write. Whitelists fields safe for logging. | New |
| **Tenant Config Service** | Per-tenant form schemas, validation rules, rate limits, feature flags. Cached in Redis with invalidation. | New — currently assumed single-tenant |

### Circuit Breaker Configuration

| Dependency | Failure Threshold | Recovery Probe Interval | Fallback Action |
|-----------|-------------------|------------------------|-----------------|
| Gemini Live API | 3 failures in 30s | Probe every 60s | New sessions → Level 2 pipeline |
| Gemini NON_BLOCKING | 3 errors in 60s | Probe every 120s | New sessions → Level 1 (BLOCKING only) |
| LiveKit Server | 2 failures in 10s | Probe every 30s | Cannot degrade — surface error, save draft |
| PostgreSQL (write) | 2 failures in 20s | Probe every 45s | Queue writes to Redis, async retry |
| PostgreSQL (read) | 3 failures in 30s | Probe every 45s | Serve from Redis cache |
| Redis | 2 failures in 10s | Probe every 20s | In-memory session state (single instance, no persistence) |
| Audit Log Service | 1 failure | Probe every 30s | **Block submission** — never proceed without audit trail |
| GPS Service | Immediate timeout (10s) | N/A | Queue verbal suburb prompt at READY_TO_START |
| Deepgram (Level 2 STT) | 3 failures in 30s | Probe every 60s | New sessions → Level 3 |
| ElevenLabs (Level 2 TTS) | 3 failures in 30s | Probe every 60s | New sessions → Level 3 |
| Claude API (Level 2 LLM) | 3 failures in 30s | Probe every 60s | New sessions → Level 3 |

---

## 3. Component & Communication Flow

### Initialisation Flow (hardened)

```
1. Mobile App
   → POST /api/v1/sessions/create
     {worker_id, participant_id, shift_id, tenant_id, client_version, idempotency_key}
   → Session Orchestrator

2. Session Orchestrator
   → Validate tenant_id (worker belongs to this tenant)
   → Check idempotency_key (reject duplicate creation)
   → Check tenant rate limit: Redis INCR on ratelimit:{tenant_id}:sessions (sliding window)
   → Mint session_trace_id (UUID v7 — time-sortable for log correlation)
   → Determine degradation_level from Degradation Manager
   → Write to Redis: session:{tenant_id}:{session_id}:state = INITIALISING, TTL=4h
   → Request LiveKit room token with room name: sena:{tenant_id}:{session_id}
   → Dispatch Context Preloader (async, non-blocking)
   → Dispatch GPS capture (async, 10s timeout)
   → Return {session_id, session_trace_id, livekit_token, room_name, degradation_level}

3. Mobile App
   → Joins LiveKit room using token
   → Publishes audio track
   → Screen reader announces: "SENA is getting ready"
   → If READY_TO_START not received within 5s: "Still loading, one moment"

4. Context Preloader (parallel)
   → Check Redis: participant:{tenant_id}:{participant_id}:context (TTL: 15min)
   → On cache miss: query PostgreSQL for participant + goals + recent notes + incidents
   → Load tenant-specific form schema from Tenant Config Service
   → Build system prompt with token budget guard:
       Priority 1 (always): participant identity + phonetic map
       Priority 2 (always): current shift details + form fields + validation rules
       Priority 3 (always): NDIS goals (current plan period)
       Priority 4 (if space): recent incidents (last 30 days)
       Priority 5 (if space): last 3 session summaries
   → If total > 80% of context window: truncate from Priority 5 upward, log PROMPT_TRUNCATED
   → Write prompt to Redis: session:{tenant_id}:{session_id}:prompt, TTL=4h
   → Emit PRELOAD_COMPLETE to Session Orchestrator
   → If timeout (>2000ms): emit PRELOAD_DEGRADED with partial prompt (Priority 1+2 only)

5. Session Orchestrator (on PRELOAD_COMPLETE or PRELOAD_DEGRADED)
   → Dispatch LiveKit Agent into room with system prompt reference
   → Write state: READY_TO_START
   → Agent announces: "SENA ready. Say start when you're ready."
   → If PRELOAD_DEGRADED: agent adds "I have basic information loaded.
     Some details about past sessions may not be available right now."

6. GPS Service (parallel, 10s timeout)
   → Attempt GPS fix
   → On success + high confidence: write to session context silently
   → On success + low confidence (<50m accuracy): queue verbal confirmation
     "I think you're near [suburb]. Is that right?"
   → On failure: queue verbal prompt for READY_TO_START:
     "I couldn't get your location. What suburb are you in?"
   → On motion detected (speed > 5km/h): flag as IN_TRANSIT, re-capture on
     first pause or when worker says "I've arrived"
```

### Active Dictation Flow (hardened)

```
Worker speaks
    │
    ▼
LiveKit Agent (audio processing layer)
    ├─ Acoustic echo cancellation (AEC) enabled on agent-side
    ├─ If speaker diarisation available: suppress non-worker audio
    ├─ Pause command detection: "hold on" / "pause" / "stop"
    │   → Immediately: state → PAUSED, draft auto-saved, confirm verbally
    ├─ Resume detection: "continue" / "go ahead" / "I'm back"
    │   → state → ACTIVE_DICTATION, resume from last position
    └─ Forward audio to voice pipeline (Level 0: Gemini, Level 2: Deepgram)

Voice Pipeline (Level 0 — Gemini Live)
    ├─ Processes audio (unified STT + reasoning + TTS)
    ├─ Emits text transcript → stored in Redis: session:{tid}:{sid}:transcript
    ├─ Tool call handling:
    │   ├─ NON_BLOCKING (Level 0): Gemini continues, result at WHEN_IDLE
    │   └─ BLOCKING (Level 1): Gemini says "One moment...", waits for result
    ├─ Output validation layer (before TTS):
    │   ├─ Check: does response reference data NOT in system prompt? → flag hallucination
    │   ├─ Check: does response contain names/numbers not in context? → suppress, re-prompt
    │   └─ Note: this is heuristic, not perfect — but catches obvious fabrications
    └─ Audio response → LiveKit → mobile

Voice Pipeline (Level 2 — Deepgram + Claude + ElevenLabs)
    ├─ Deepgram STT: audio → text (streaming)
    ├─ Claude Sonnet: text + system prompt → response text
    ├─ ElevenLabs TTS: response text → audio
    └─ Audio → LiveKit → mobile

Every voice pipeline I/O event:
    → Structured log line:
      {session_trace_id, tenant_id, worker_id, participant_id,
       event_type, timestamp, degradation_level,
       input_tokens?, output_tokens?, tool_name?, latency_ms}
    → PII Filter: scrub participant names/numbers from log payload
    → Async write to Audit Log Service (non-blocking to voice path)

Idle detection (runs parallel):
    → 90s silence → agent: "Are you still there?"
    → 30s more silence → auto-save draft, state → IDLE_TIMEOUT, end session

Cost Governor (runs parallel):
    → Tracks audio_seconds via LiveKit participant events
    → At 1200s (20min): agent warns verbally
    → At 1800s (30min): force PAUSED, save draft, end session
```

### Submission Flow (hardened)

```
Worker says "submit" or "I'm done"
    │
    ▼
State → PENDING_READBACK
    │
    ├─ Agent reads back every section in plain language
    ├─ Pauses after each section: "Is that right?"
    ├─ On "change" or "wait" → return to ACTIVE_DICTATION with specific field prompt
    ├─ On "I confirm" for all sections:
    │
    ▼
State → PENDING_SUBMISSION
    │
    ├─ Generate idempotency_key for this submission attempt
    ├─ Check note version integrity (hash comparison against Note Version Store)
    │   └─ On conflict → return to ACTIVE_DICTATION:
    │      "Someone else updated this participant's information. Let me tell you what changed."
    │
    ├─ Run server-side validation (belt-and-suspenders, in case prompt missed something):
    │   ├─ All required fields present?
    │   ├─ Time range valid?
    │   ├─ Incident flagged if keywords detected?
    │   └─ On failure → return to ACTIVE_DICTATION with specific prompt
    │
    ├─ Saga transaction (ordered steps with compensating actions):
    │   Step A: Write note to PostgreSQL
    │           {note_id, content, version, worker_id, participant_id, tenant_id,
    │            session_trace_id, submitted_at, idempotency_key}
    │           Compensation: DELETE note by id
    │   Step B: Write to Audit Log Service
    │           {event_type: SUBMISSION, session_trace_id, full note content hash}
    │           Compensation: None (audit entries are append-only, never deleted)
    │           CRITICAL: If this step fails, the entire saga rolls back.
    │                     A note without an audit event is a compliance violation.
    │   Step C: Enqueue approval event
    │           {note_id, tenant_id, priority, submitted_at}
    │           Compensation: Cancel queue entry
    │
    ├─ On saga success:
    │   ├─ State → SUBMITTED
    │   ├─ Release cost governor counter
    │   ├─ Keep Redis session state for 24h (recovery/audit)
    │   └─ Agent: "Progress note for [participant] saved and sent for approval."
    │
    └─ On saga failure:
        ├─ State → SUBMISSION_FAILED (draft preserved)
        ├─ Retry up to 3 times with exponential backoff
        └─ Agent: "I had trouble saving. Your note is safe as a draft. Please try again."
```

### Post-Submission Event Flow (new — addresses Blind Spot 7)

```
Approval Queue Consumer
    │
    ├─ Supervisor approves:
    │   → Write audit event: APPROVED
    │   → State → APPROVED
    │   → Push notification to worker's mobile: "Your note for [participant] was approved"
    │   → If worker is in an active SENA session: verbal notification at next pause
    │
    ├─ Supervisor returns for changes:
    │   → Write audit event: RETURNED_FOR_CHANGES
    │   → State → RETURNED_FOR_CHANGES
    │   → Push notification with reason text
    │   → On worker's next session start: "You have a note for [participant] that needs changes.
    │     The feedback is: [reason]. Would you like to update it now?"
    │
    └─ No action within 24h:
        → Alert to supervisor's manager
        → Escalation event logged
```

---

## 4. End-to-End Implementation Blueprint (Step-by-Step)

### Phase 0: Infrastructure Foundation *(Week 0 — before any application code)*

**Goal:** Every service has a home, every dependency is reachable, every secret is managed, every log line has a trace ID.

**Create:** Secrets management entries
- Provision AWS Secrets Manager (or Vault): `GEMINI_API_KEY`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `DATABASE_URL`, `REDIS_SESSION_URL`, `REDIS_AUDIT_URL`, `DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY`, `ANTHROPIC_API_KEY`
- No secrets in environment variables in production
- Rotation schedule: LLM keys every 90 days, infrastructure keys every 180 days

**Create:** Redis provisioning
- Two separate Redis instances:
  - `redis-session`: hot path, in-memory optimised, for session state and context cache
  - `redis-audit`: persistence-enabled (AOF + RDB), for draft recovery and transcript storage
- Key namespace schema:

```
session:{tenant_id}:{session_id}:state              TTL: 4h
session:{tenant_id}:{session_id}:prompt              TTL: 4h
session:{tenant_id}:{session_id}:transcript          TTL: 24h
session:{tenant_id}:{session_id}:draft               TTL: 24h
session:{tenant_id}:{session_id}:version             TTL: 24h
participant:{tenant_id}:{participant_id}:context      TTL: 15min
tenant:{tenant_id}:config                            TTL: 60min
tenant:{tenant_id}:form_schema                       TTL: 60min
ratelimit:{tenant_id}:sessions                       TTL: 1min (sliding window)
ratelimit:{tenant_id}:gemini_calls                   TTL: 1min (sliding window)
```

**Create:** Database schema

```sql
-- Session tracking
ALTER TABLE voice_sessions ADD COLUMN session_trace_id UUID NOT NULL;
ALTER TABLE voice_sessions ADD COLUMN state VARCHAR(32) NOT NULL DEFAULT 'INITIALISING';
ALTER TABLE voice_sessions ADD COLUMN degradation_level INTEGER NOT NULL DEFAULT 0;
ALTER TABLE voice_sessions ADD COLUMN tenant_id UUID NOT NULL;
ALTER TABLE voice_sessions ADD COLUMN preload_duration_ms INTEGER;
ALTER TABLE voice_sessions ADD COLUMN audio_seconds INTEGER DEFAULT 0;
ALTER TABLE voice_sessions ADD COLUMN idempotency_key VARCHAR(64) UNIQUE;
CREATE INDEX idx_sessions_tenant_state ON voice_sessions(tenant_id, state);
CREATE INDEX idx_sessions_trace ON voice_sessions(session_trace_id);

-- Audit log (separate database recommended; same DB acceptable for MVP with clear schema separation)
CREATE TABLE audit_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_trace_id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    worker_id UUID NOT NULL,
    participant_id UUID NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    event_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_audit_session ON audit_events(session_trace_id);
CREATE INDEX idx_audit_tenant_created ON audit_events(tenant_id, created_at);
CREATE INDEX idx_audit_type ON audit_events(event_type, created_at);

-- Note versioning
CREATE TABLE note_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    note_id UUID NOT NULL REFERENCES progress_notes(id),
    version_number INTEGER NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    content JSONB NOT NULL,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(note_id, version_number)
);

-- Tenant configuration
CREATE TABLE tenant_configs (
    tenant_id UUID PRIMARY KEY,
    form_schema JSONB NOT NULL,
    validation_rules JSONB NOT NULL,
    max_session_duration_seconds INTEGER DEFAULT 1800,
    max_concurrent_sessions INTEGER DEFAULT 100,
    features JSONB DEFAULT '{}',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Cost tracking
CREATE TABLE session_cost_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_trace_id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    audio_seconds INTEGER NOT NULL,
    degradation_level INTEGER NOT NULL,
    estimated_cost_usd NUMERIC(10, 6),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_cost_tenant_date ON session_cost_events(tenant_id, created_at);
```

**Create:** Observability stack
- Deploy OpenTelemetry Collector sidecar
- Configure trace export to chosen backend (Grafana Tempo, Datadog, or AWS X-Ray)
- Trace schema: every trace starts with `session.create` span, `session_trace_id` as root trace ID
- Three dashboards before writing application code:
  1. **Session Health**: active sessions by state, by tenant, by degradation level
  2. **Latency**: P50/P95/P99 by operation (preload, voice response, submission) and by degradation level
  3. **Cost**: audio-minutes by tenant per day, sessions by tenant per day

**Create:** `services/voice/src/voice/telemetry.py`

```python
import opentelemetry.trace as trace
from opentelemetry.trace import SpanKind
from typing import Optional
import uuid

tracer = trace.get_tracer("sena.voice")

def mint_session_trace_id() -> str:
    """UUID v7 — time-sortable for log correlation."""
    return str(uuid.uuid7())

def create_session_span(
    session_trace_id: str,
    tenant_id: str,
    worker_id: str,
    participant_id: str,
    operation: str
) -> trace.Span:
    span = tracer.start_span(
        name=f"session.{operation}",
        kind=SpanKind.INTERNAL,
        attributes={
            "session.trace_id": session_trace_id,
            "session.tenant_id": tenant_id,
            "session.worker_id": worker_id,
            "session.participant_id": participant_id,
        }
    )
    return span

def log_event(
    session_trace_id: str,
    tenant_id: str,
    event_type: str,
    payload: dict,
    worker_id: Optional[str] = None,
    participant_id: Optional[str] = None
) -> None:
    """Structured log line — every line has session_trace_id and tenant_id."""
    # Implementation writes to structured logger (JSON lines)
    # PII filter applied before write
    ...
```

**Blocking Gate:** Gemini Live API region verification
- Confirm `australia-southeast1` availability on Vertex AI for Gemini Live
- If unavailable: sign Google Cloud Data Processing Addendum for US processing
- Document decision in compliance register — do not proceed without this

**Gate:** Redis reachable from application network, both instances. Database schema applied. OpenTelemetry collector receiving spans. Secrets resolvable. Region decision documented.

---

### Phase 1: Session Orchestrator *(Week 1)*

**Goal:** The central nervous system exists before any voice code is written.

**Create:** `services/voice/src/voice/models/session_state.py`

```python
from enum import Enum

class SessionState(str, Enum):
    INITIALISING = "INITIALISING"
    READY_TO_START = "READY_TO_START"
    ACTIVE_DICTATION = "ACTIVE_DICTATION"
    PAUSED = "PAUSED"
    PENDING_READBACK = "PENDING_READBACK"
    PENDING_SUBMISSION = "PENDING_SUBMISSION"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    RETURNED_FOR_CHANGES = "RETURNED_FOR_CHANGES"
    PRELOAD_FAILED = "PRELOAD_FAILED"
    CONNECTION_LOST = "CONNECTION_LOST"
    SUBMISSION_FAILED = "SUBMISSION_FAILED"
    IDLE_TIMEOUT = "IDLE_TIMEOUT"
    COST_TIMEOUT = "COST_TIMEOUT"

# Valid transitions: {current_state: [allowed_next_states]}
VALID_TRANSITIONS: dict[SessionState, list[SessionState]] = {
    SessionState.INITIALISING: [
        SessionState.READY_TO_START,
        SessionState.PRELOAD_FAILED,
        SessionState.CONNECTION_LOST,
    ],
    SessionState.READY_TO_START: [
        SessionState.ACTIVE_DICTATION,
        SessionState.CONNECTION_LOST,
        SessionState.IDLE_TIMEOUT,
    ],
    SessionState.ACTIVE_DICTATION: [
        SessionState.PAUSED,
        SessionState.PENDING_READBACK,
        SessionState.CONNECTION_LOST,
        SessionState.IDLE_TIMEOUT,
        SessionState.COST_TIMEOUT,
    ],
    SessionState.PAUSED: [
        SessionState.ACTIVE_DICTATION,
        SessionState.PENDING_READBACK,
        SessionState.CONNECTION_LOST,
        SessionState.IDLE_TIMEOUT,
        SessionState.COST_TIMEOUT,
    ],
    SessionState.PENDING_READBACK: [
        SessionState.ACTIVE_DICTATION,  # worker wants changes
        SessionState.PENDING_SUBMISSION,
        SessionState.CONNECTION_LOST,
    ],
    SessionState.PENDING_SUBMISSION: [
        SessionState.SUBMITTED,
        SessionState.SUBMISSION_FAILED,
        SessionState.ACTIVE_DICTATION,  # validation failure
    ],
    SessionState.SUBMISSION_FAILED: [
        SessionState.PENDING_SUBMISSION,  # retry
        SessionState.ACTIVE_DICTATION,    # worker wants to edit
    ],
    SessionState.SUBMITTED: [
        SessionState.APPROVED,
        SessionState.RETURNED_FOR_CHANGES,
    ],
}

class DegradationLevel(int, Enum):
    NORMAL = 0           # Gemini Live, NON_BLOCKING
    DEGRADED_GEMINI = 1  # Gemini Live, BLOCKING only
    ALTERNATIVE = 2      # Deepgram + Claude + ElevenLabs
    MINIMAL = 3          # Deepgram + rule-based + ElevenLabs
    EMERGENCY = 4        # Record audio only

class SessionError(str, Enum):
    PRELOAD_TIMEOUT = "PRELOAD_TIMEOUT"
    PRELOAD_DB_FAILURE = "PRELOAD_DB_FAILURE"
    GEMINI_CONNECTION_FAILED = "GEMINI_CONNECTION_FAILED"
    LIVEKIT_CONNECTION_FAILED = "LIVEKIT_CONNECTION_FAILED"
    REDIS_FAILURE = "REDIS_FAILURE"
    SUBMISSION_DB_FAILURE = "SUBMISSION_DB_FAILURE"
    AUDIT_LOG_FAILURE = "AUDIT_LOG_FAILURE"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    CONTEXT_WINDOW_EXCEEDED = "CONTEXT_WINDOW_EXCEEDED"

class ErrorRecoveryAction(str, Enum):
    RETRY = "RETRY"
    DEGRADE = "DEGRADE"
    SAVE_DRAFT = "SAVE_DRAFT"
    SURFACE_TO_WORKER = "SURFACE_TO_WORKER"
    BLOCK_SUBMISSION = "BLOCK_SUBMISSION"
```

**Create:** `services/voice/src/voice/services/session_orchestrator.py`

```python
from uuid import UUID
from voice.models.session_state import (
    SessionState, DegradationLevel, SessionError,
    ErrorRecoveryAction, VALID_TRANSITIONS
)
from voice.telemetry import mint_session_trace_id, log_event, create_session_span

class SessionOrchestrator:

    async def create_session(
        self,
        worker_id: UUID,
        participant_id: UUID,
        shift_id: UUID,
        tenant_id: UUID,
        idempotency_key: str,
    ) -> "SessionCreationResult":
        # 1. Idempotency check
        # 2. Validate worker belongs to tenant
        # 3. Check tenant rate limit (Redis sliding window)
        # 4. Mint session_trace_id
        # 5. Determine degradation_level from DegradationManager
        # 6. Write INITIALISING state to Redis with TTL=4h
        # 7. Request LiveKit room token (room name: sena:{tenant_id}:{session_id})
        # 8. Dispatch context_preloader (async)
        # 9. Dispatch GPS capture (async, 10s timeout)
        # 10. Write OpenTelemetry span: session.create
        # 11. Return {session_id, session_trace_id, livekit_token, room_name, degradation_level}
        ...

    async def transition_state(
        self,
        session_id: UUID,
        tenant_id: UUID,
        new_state: SessionState,
        metadata: dict | None = None,
    ) -> None:
        # 1. Read current state from Redis
        # 2. Validate transition is in VALID_TRANSITIONS
        # 3. Atomic write: {previous_state, new_state, timestamp, trigger}
        # 4. Emit OpenTelemetry span event
        # 5. If new_state is terminal: schedule cleanup
        ...

    async def handle_error(
        self,
        session_id: UUID,
        tenant_id: UUID,
        error: SessionError,
    ) -> ErrorRecoveryAction:
        # Maps error type + current state to recovery action
        ERROR_RECOVERY: dict[SessionError, ErrorRecoveryAction] = {
            SessionError.PRELOAD_TIMEOUT: ErrorRecoveryAction.DEGRADE,
            SessionError.GEMINI_CONNECTION_FAILED: ErrorRecoveryAction.DEGRADE,
            SessionError.REDIS_FAILURE: ErrorRecoveryAction.SAVE_DRAFT,
            SessionError.AUDIT_LOG_FAILURE: ErrorRecoveryAction.BLOCK_SUBMISSION,
            SessionError.RATE_LIMIT_EXCEEDED: ErrorRecoveryAction.SURFACE_TO_WORKER,
        }
        ...

    async def get_session_state(
        self,
        session_id: UUID,
        tenant_id: UUID,
    ) -> "SessionSnapshot":
        # Returns current state, degradation level, draft status, timestamps
        ...
```

**Modify:** `services/voice/src/voice/api/routes.py`
- Replace current session creation logic with `session_orchestrator.create_session()`
- All session state reads go through orchestrator — no direct Redis access in route handlers
- Add `idempotency_key` to creation endpoint
- Add `tenant_id` extraction from JWT/auth token

**Gate:** Session creation returns valid LiveKit token. State persisted in Redis with tenant prefix. Trace ID present in all log lines. Duplicate creation rejected by idempotency key.

---

### Phase 2: Context Preloader with Token Budget Guard *(Week 1)*

**Goal:** System prompt is always ready before the worker starts, always within token limits, always tenant-aware.

**Create:** `services/voice/src/voice/services/context_preloader.py`

```python
from uuid import UUID
import time
import hashlib

# Constants
MAX_PROMPT_TOKENS = 28_000          # 80% of Gemini 2.0 Flash 32k context
PRELOAD_TIMEOUT_MS = 2_000
PARTICIPANT_CACHE_TTL = 900         # 15 minutes

# Priority levels for token budget management
PRIORITY_IDENTITY = 1       # ~500 tokens — always included
PRIORITY_SHIFT_FORM = 2     # ~2000 tokens — always included
PRIORITY_VALIDATION = 3     # ~1000 tokens — always included
PRIORITY_GOALS = 4          # ~500 tokens — always included
PRIORITY_INCIDENTS = 5      # ~1500 tokens — included if space
PRIORITY_HISTORY = 6        # variable — included if space

class ContextPreloader:

    async def build_system_prompt(
        self,
        session_id: UUID,
        participant_id: UUID,
        shift_id: UUID,
        tenant_id: UUID,
    ) -> "PromptBuildResult":
        start = time.monotonic()

        # Fetch tenant-specific form schema
        form_schema = await self._get_tenant_form_schema(tenant_id)

        # Priority-ordered data fetching with timeout
        context = await self._fetch_with_timeout(
            participant_id, shift_id, tenant_id, PRELOAD_TIMEOUT_MS
        )

        # Assemble prompt sections in priority order
        sections = [
            (PRIORITY_IDENTITY, self._build_identity_section(context.participant)),
            (PRIORITY_SHIFT_FORM, self._build_form_section(context.shift, form_schema)),
            (PRIORITY_VALIDATION, self._build_validation_section(form_schema)),
            (PRIORITY_GOALS, self._build_goals_section(context.goals)),
            (PRIORITY_INCIDENTS, self._build_incidents_section(context.incidents)),
            (PRIORITY_HISTORY, self._build_history_section(context.recent_notes)),
        ]

        prompt = self._assemble_within_budget(sections, MAX_PROMPT_TOKENS)

        # Cache and store
        await self._cache_participant_context(tenant_id, participant_id, context)
        await self._store_session_prompt(tenant_id, session_id, prompt)

        duration_ms = int((time.monotonic() - start) * 1000)
        return PromptBuildResult(
            prompt=prompt,
            duration_ms=duration_ms,
            truncated_priorities=[s[0] for s in sections if s not in prompt.included],
            token_count=prompt.token_count,
        )

    def _assemble_within_budget(
        self,
        sections: list[tuple[int, str]],
        max_tokens: int,
    ) -> "AssembledPrompt":
        """Include sections in priority order until budget exhausted."""
        ...

    def _estimate_tokens(self, text: str) -> int:
        """Conservative estimate: 1 token per 3.5 characters for English."""
        return int(len(text) / 3.5)
```

**Create:** `services/voice/src/voice/services/name_alias_service.py`

```python
class NameAliasService:
    async def get_phonetic_map(
        self, tenant_id: UUID, participant_id: UUID
    ) -> dict[str, list[str]]:
        """Returns {canonical_name: [phonetic_variants]}."""
        ...

    async def update_aliases(
        self, tenant_id: UUID, participant_id: UUID, aliases: list[str]
    ) -> None:
        """Called when participant record is updated. Invalidates cache."""
        ...
```

**Gate:** Preload completes within 2,000ms at P95. Prompt token count never exceeds budget. Truncation events logged and alertable. Tenant-specific form schemas loaded correctly.

---

### Phase 3: LiveKit Agent with Degradation Ladder *(Week 2)*

**Goal:** End-to-end voice conversation works at Level 0, with automatic fallback to Level 2.

**Create:** `services/voice/src/voice/agents/gemini_agent.py`

```python
from livekit.agents import AgentSession, WorkerOptions, cli
from livekit.plugins import google
from voice.models.session_state import DegradationLevel

async def create_agent_session(
    session_id: str,
    tenant_id: str,
    degradation_level: DegradationLevel,
) -> AgentSession:

    system_prompt = await _load_system_prompt(tenant_id, session_id)

    if degradation_level == DegradationLevel.NORMAL:
        llm = google.realtime.RealtimeModel(
            model="gemini-2.0-flash-live-001",
            voice="Puck",
            system_instructions=system_prompt,
            tools=[search_knowledge_base, get_participant_history, get_ndis_guideline],
        )
    elif degradation_level == DegradationLevel.DEGRADED_GEMINI:
        llm = google.realtime.RealtimeModel(
            model="gemini-2.0-flash-live-001",
            voice="Puck",
            system_instructions=system_prompt,
            tools=[search_knowledge_base, get_participant_history, get_ndis_guideline],
            # Force BLOCKING tool calls — NON_BLOCKING disabled
        )
    elif degradation_level == DegradationLevel.ALTERNATIVE:
        llm = _build_level2_pipeline(system_prompt, tenant_id, session_id)
    elif degradation_level == DegradationLevel.MINIMAL:
        llm = _build_level3_pipeline(system_prompt, tenant_id, session_id)
    else:
        # Level 4: emergency recording
        return _build_recording_only_session(tenant_id, session_id)

    session = AgentSession(llm=llm)

    # Audit logging hooks
    session.on("user_speech_committed", lambda ev: _log_transcript(tenant_id, session_id, "USER", ev))
    session.on("agent_speech_committed", lambda ev: _log_transcript(tenant_id, session_id, "AGENT", ev))
    session.on("function_calls_collected", lambda ev: _log_tool_call(tenant_id, session_id, ev))

    return session


def _build_level2_pipeline(
    system_prompt: str, tenant_id: str, session_id: str
) -> "AgentSession":
    """Deepgram STT → Claude Sonnet → ElevenLabs TTS"""
    # Uses livekit-plugins-deepgram for STT
    # Uses Anthropic Claude Sonnet via standard API for reasoning
    # Uses livekit-plugins-elevenlabs for TTS
    # System prompt is the same — transferred from Redis
    ...
```

**Create:** `services/voice/src/voice/agents/tools/rag_tools.py`

```python
from voice.telemetry import log_event

# Each tool must complete within 800ms at P95
# Each tool result is PII-filtered before logging

async def search_knowledge_base(
    query: str,
    tenant_id: str,
    session_id: str,
) -> str:
    """Search tenant's knowledge base (NDIS guidelines, policies)."""
    ...

async def get_participant_history(
    participant_id: str,
    lookback_days: int,
    tenant_id: str,
    session_id: str,
) -> str:
    """Retrieve previous session summaries for this participant."""
    ...

async def get_ndis_guideline(
    topic: str,
    tenant_id: str,
    session_id: str,
) -> str:
    """Look up specific NDIS practice standard or guideline."""
    ...
```

**Create:** `services/voice/src/voice/agents/circuit_breakers.py`

```python
from circuitbreaker import CircuitBreaker

gemini_live_breaker = CircuitBreaker(
    failure_threshold=3,
    recovery_timeout=60,
    expected_exception=(GeminiConnectionError, GeminiTimeoutError),
    name="gemini_live",
)

gemini_nonblocking_breaker = CircuitBreaker(
    failure_threshold=3,
    recovery_timeout=120,
    expected_exception=GeminiNonBlockingError,
    name="gemini_nonblocking",
)

deepgram_breaker = CircuitBreaker(
    failure_threshold=3,
    recovery_timeout=60,
    expected_exception=DeepgramConnectionError,
    name="deepgram_stt",
)

elevenlabs_breaker = CircuitBreaker(
    failure_threshold=3,
    recovery_timeout=60,
    expected_exception=ElevenLabsConnectionError,
    name="elevenlabs_tts",
)

claude_breaker = CircuitBreaker(
    failure_threshold=3,
    recovery_timeout=60,
    expected_exception=AnthropicAPIError,
    name="claude_api",
)
```

**Create:** `services/voice/src/voice/services/degradation_manager.py`

```python
class DegradationManager:
    def get_current_level(self) -> DegradationLevel:
        """Check all circuit breakers, return appropriate level for new sessions."""
        if gemini_live_breaker.state == "open":
            if deepgram_breaker.state == "open" or claude_breaker.state == "open":
                if deepgram_breaker.state == "open":
                    return DegradationLevel.EMERGENCY
                return DegradationLevel.MINIMAL
            return DegradationLevel.ALTERNATIVE
        if gemini_nonblocking_breaker.state == "open":
            return DegradationLevel.DEGRADED_GEMINI
        return DegradationLevel.NORMAL
```

**Gate:** Audio conversation works end-to-end at Level 0. Level 2 tested by mocking Gemini failures (circuit breaker opens, new session starts at Level 2, voice works). All I/O logged with session_trace_id and tenant_id.

---

### Phase 4: Voice Validation and Accessibility Layer *(Week 2)*

**Goal:** All 9 accessibility gaps are addressed in the voice pipeline. A blind user can complete the entire flow without screen interaction.

**Create:** `services/voice/src/voice/prompts/validation_rules.py`

```python
class ValidationRuleGenerator:
    def generate_prompt_section(
        self, form_schema: dict, tenant_id: str
    ) -> str:
        """Converts tenant form schema into conversational validation rules
        for the system prompt. Rules are in plain English, not error codes."""
        ...
```

**Create:** `services/voice/src/voice/prompts/accessibility_instructions.py`

```python
# Appended to every system prompt regardless of tenant or degradation level

ACCESSIBILITY_BLOCK = """
ACCESSIBILITY RULES — ALWAYS FOLLOW THESE:

NAME CONFIRMATION: Before saving or submitting any information, always read back
the participant's full name and ask for confirmation. Accept "yes", "correct",
"that's right" as confirmation. On any hesitation, re-prompt.

VALIDATION: Never use technical error messages. Catch all errors conversationally
before they reach submission. If a required field is empty, ask for it naturally.
If times conflict, describe the conflict in plain language.

READBACK: Before any submission, read every section back in plain language.
Pause after each section and ask "Is that right?" Wait for confirmation.

PAUSE COMMANDS: If you hear "hold on", "wait", "pause", or "stop for a second",
immediately stop and confirm: "Paused. Say continue whenever you're ready."

SENTENCE STARTERS: If the worker says "I don't know what to say" or "I'm not sure",
offer two or three concrete examples relevant to the field being filled.

INCIDENT DETECTION: If the worker describes any of the following — a fall, an injury,
a behaviour of concern, police involvement, hospital attendance, medication incident —
immediately ask: "Do you need to report this as a critical incident right now?"
If yes, pause the progress note and begin the incident report form.

TIMEOUT: If there is silence for more than 90 seconds, ask: "Are you still there?"
If no response after 30 more seconds, say "I'll save your work as a draft" and end.
"""
```

**Create:** `services/voice/src/voice/services/photo_service.py`
- Voice-triggered camera capture via mobile app bridge
- Captured image sent to Gemini Vision for document type detection
- Agent reads back what was captured: "This looks like a Medicare card for John Smith — is that correct?"
- On mismatch: "That looks like an invoice, not a consent form. Please try again."

**Gate:** All 9 accessibility gaps verified by manual test with screen reader enabled and display off. A tester completes a full progress note entirely by voice, including: name confirmation, field prompting, pause/resume, photo capture, readback, and submission confirmation.

---

### Phase 5: Submission Pipeline with Saga Pattern *(Week 3)*

**Goal:** No note is ever lost. No note is ever submitted without an audit trail. No double-submit is possible.

**Create:** `services/voice/src/voice/services/submission_service.py`

```python
from uuid import UUID
from voice.models.session_state import SessionState

class SubmissionService:

    async def submit_note(
        self,
        session_id: UUID,
        tenant_id: UUID,
        note_data: "NoteSubmission",
        idempotency_key: str,
    ) -> "SubmissionResult":

        # 1. Idempotency check
        existing = await self._check_idempotency(idempotency_key)
        if existing:
            return existing

        # 2. Version integrity check
        current = await self.note_version_store.get_latest(note_data.note_id)
        if note_data.version != current.version_number:
            return SubmissionResult.VERSION_CONFLICT

        # 3. Server-side validation
        validation = await self._validate(note_data, tenant_id)
        if not validation.is_valid:
            return SubmissionResult.VALIDATION_FAILED(validation.failures)

        # 4. Saga transaction
        async with SagaTransaction(session_id=session_id) as saga:
            note_record = await saga.step(
                name="write_note",
                action=lambda: self.note_repo.create(note_data, idempotency_key),
                compensation=lambda r: self.note_repo.delete(r.id),
            )
            await saga.step(
                name="write_audit",
                action=lambda: self.audit_service.log_submission(
                    session_id, tenant_id, note_record
                ),
                compensation=lambda: None,  # Audit entries never deleted
                # CRITICAL: If this fails, entire saga rolls back
            )
            await saga.step(
                name="enqueue_approval",
                action=lambda: self.approval_queue.enqueue(note_record, tenant_id),
                compensation=lambda: self.approval_queue.cancel(note_record.id),
            )

        # 5. Transition state
        await self.session_orchestrator.transition_state(
            session_id, tenant_id, SessionState.SUBMITTED
        )

        # 6. Release cost governor
        await self.cost_governor.end_session(session_id, tenant_id)

        return SubmissionResult.SUCCESS
```

**Create:** `services/voice/src/voice/services/note_version_store.py`

```python
class NoteVersionStore:
    async def save_draft(
        self, note_id: UUID, content: dict, worker_id: UUID
    ) -> int:
        """Returns new version number. Content hash computed and stored."""
        ...

    async def get_latest(self, note_id: UUID) -> "NoteVersion":
        ...

    async def detect_conflict(
        self, note_id: UUID, expected_version: int
    ) -> bool:
        ...
```

**Gate:** Submission tested with: DB failure injection (saga rolls back, draft preserved), audit log failure (submission blocked, worker informed verbally), approval queue failure (note saved, queue retried async), double-submit (second attempt returns idempotent result).

---

### Phase 6: Cost Governor and Session Lifecycle *(Week 3)*

**Goal:** No zombie sessions. No runaway costs. Every session has a defined end.

**Create:** `services/voice/src/voice/services/cost_governor.py`

```python
class CostGovernor:

    DEFAULT_WARN_SECONDS = 1200      # 20 minutes
    DEFAULT_MAX_SECONDS = 1800       # 30 minutes

    async def track_audio(
        self, session_id: UUID, tenant_id: UUID, audio_seconds: int
    ) -> "CostAction | None":
        """Called periodically by LiveKit participant event hooks."""
        total = await self._increment_counter(tenant_id, session_id, audio_seconds)
        max_duration = await self._get_tenant_max_duration(tenant_id)

        if total >= max_duration:
            return CostAction.FORCE_END
        elif total >= max_duration - 600:  # 10 min before max
            return CostAction.WARN
        return None

    async def end_session(
        self, session_id: UUID, tenant_id: UUID
    ) -> None:
        """Write cost event to session_cost_events table."""
        ...

    async def get_tenant_daily_cost(
        self, tenant_id: UUID, date: str
    ) -> "TenantCostSummary":
        ...
```

**Create:** `services/voice/src/voice/services/idle_detector.py`

```python
class IdleDetector:
    SILENCE_WARNING_SECONDS = 90
    SILENCE_TIMEOUT_SECONDS = 120

    async def on_silence_detected(
        self, session_id: UUID, tenant_id: UUID, silence_seconds: int
    ) -> "IdleAction | None":
        if silence_seconds >= self.SILENCE_TIMEOUT_SECONDS:
            return IdleAction.AUTO_SAVE_AND_END
        elif silence_seconds >= self.SILENCE_WARNING_SECONDS:
            return IdleAction.VERBAL_WARNING
        return None
```

**Gate:** Zombie session auto-closes after 30min of audio. Idle session auto-saves after 120s of silence. Cost events written to DB and queryable per tenant per day.

---

### Phase 7: Post-Submission Workflow *(Week 3)*

**Goal:** The note lifecycle doesn't end at submission. Approvals, rejections, and escalations all have defined flows.

**Create:** `services/voice/src/voice/services/approval_consumer.py`

```python
class ApprovalConsumer:

    async def handle_approval(
        self, note_id: UUID, tenant_id: UUID, supervisor_id: UUID
    ) -> None:
        await self.audit_service.log_event("APPROVED", ...)
        await self.session_orchestrator.transition_state(..., SessionState.APPROVED)
        await self.notification_service.notify_worker(
            worker_id, f"Your note for {participant_name} was approved."
        )

    async def handle_return_for_changes(
        self, note_id: UUID, tenant_id: UUID, reason: str
    ) -> None:
        await self.audit_service.log_event("RETURNED", ...)
        await self.session_orchestrator.transition_state(..., SessionState.RETURNED_FOR_CHANGES)
        await self.notification_service.notify_worker(
            worker_id,
            f"Your note for {participant_name} needs changes: {reason}"
        )
        # On worker's next session start, the orchestrator checks for pending returns
        # and offers to resume editing

    async def handle_escalation_timeout(
        self, note_id: UUID, tenant_id: UUID, hours_pending: int
    ) -> None:
        if hours_pending >= 24:
            await self.notification_service.notify_supervisor_manager(...)
```

**Gate:** Approval triggers worker notification. Return triggers worker notification with reason. Escalation timeout at 24h triggers manager alert.

---

### Phase 8: Hardening, Load Testing, and Go-Live Gates *(Week 4)*

**Hardening tasks:**

1. **Load test** — Simulate 50 concurrent sessions per tenant:
   - Verify no Redis key collisions (tenant-prefixed keys)
   - Verify no LiveKit room cross-contamination (tenant+session in room name)
   - Verify Gemini rate limit handling triggers degradation to Level 2 gracefully
   - Measure P95 latencies at load vs. single-session benchmarks

2. **Chaos engineering** — Kill dependencies mid-session:
   - Redis dies → verify in-memory fallback activates, draft recoverable on reconnect
   - PostgreSQL dies during submission → verify saga rolls back, worker informed
   - Gemini WebSocket drops mid-sentence → verify reconnection or Level 2 activation
   - LiveKit server dies → verify draft auto-saved, worker sees CONNECTION_LOST

3. **Security review:**
   - Tenant ID validated on every API call — worker from Tenant A cannot access Tenant B
   - Redis keys prefixed with `tenant:{tenant_id}:` — no cross-tenant key access
   - Gemini tool call responses PII-filtered before audit log write
   - LiveKit room names encode tenant ID, validated server-side before token issuance
   - Session tokens expire after 4 hours
   - Rate limiting per tenant prevents denial-of-service from one tenant affecting others

4. **Compliance verification:**
   - Every note submission has a corresponding audit event (verified by DB query: submissions without audit events = 0)
   - Every audit event has session_trace_id (verified by query)
   - Audio minutes per session logged and queryable per tenant
   - Data residency decision documented and signed off
   - PII filter verified: no participant names/numbers in observability logs

5. **Accessibility verification:**
   - Full end-to-end test with blind tester (screen reader on, display off)
   - All 9 gaps from the design brief verified resolved
   - Voice-triggered camera tested on iOS and Android
   - Pause/resume tested in noisy environment
   - Session timeout verbal warnings audible and actionable

**Go-Live Gates — hard requirements, no exceptions:**

| Gate | Measurement Method | Target |
|------|-------------------|--------|
| End-to-end P95 latency (Level 0) | Synthetic load test, 50 concurrent sessions | < 500ms |
| End-to-end P95 latency (Level 2) | Synthetic load test, 10 concurrent sessions | < 1000ms |
| Preload P95 duration | Production monitoring | < 2,000ms |
| Session state recovery after crash | Manual test: kill agent mid-session, reconnect | < 5s to resume |
| Audit event coverage | DB query: note submissions with no audit event | 0 |
| Cross-tenant isolation | Penetration test: Tenant A worker attempts Tenant B access | 0 findings |
| Double-submit prevention | Load test: rapid duplicate submissions | 0 duplicates |
| Level 2 degradation voice capability | Manual test: Gemini mocked offline, complete full note by voice | Fully functional |
| Zombie session protection | Leave session open 35min, verify auto-close | Draft saved, session ended |
| Accessibility | Full flow test, blind tester, display off, screen reader only | All 9 gaps resolved |
| Data residency | Compliance officer sign-off on region decision | Signed |
| Cost monitoring | Dashboard shows per-tenant daily cost | Accurate within 5% |

---

*End of Audit*
