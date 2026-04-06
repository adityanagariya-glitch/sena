# Voice Onboarding Assistant — Implementation Timeline

Since the frontend UI is already built, our methodology emphasizes **API Contract-First driven development**. We will build the system in a LangGraph-orchestrated directed acyclic graph (DAG), enabling us to mock nodes initially and incrementally replace them with production model calls. This allows the frontend team to begin integration testing on Day 2.

### Granular Technical Breakdown Strategy
1. **Transport & Contracts:** WebRTC (LiveKit) plumbing, Redis session management, and API definitions.
2. **State & Orchestration:** Explicit LangGraph `TypedDict` routing mapped to the frontend form schema.
3. **Cognitive Core:** Gemini Multimodal (native STT + reasoning) integration with context window management.
4. **Resilience & Audit:** Circuit breakers, token budgeting, and NDIS compliance audit logging.

---

### Implementation Timeline: Voice Onboarding Agent

| Phase / Week | Task Description (Technical Breakdown) | AI Eng Time | Integration/Testing Time | Dependencies |
| :--- | :--- | :--- | :--- | :--- |
| **Phase 1: Week 1** | **Contracts & Transport Layer**<br>• Define explicit API contracts (JSON schemas for `FormState`, `ContextPacket`, `FieldUpdate`).<br>• Stand up LiveKit instance (WebRTC) and test bidirectional audio transport.<br>• Implement mock LangGraph orchestrator that echoes dummy field updates back to the UI. | 24h | 16h (Frontend configures WS/LiveKit connections) | Finalized Frontend Form Schema |
| **Phase 1: Week 1** | **State Management & Memory**<br>• Implement Redis session store for ephemeral form state and turn-history (TTL: 1h).<br>• Implement security middleware: JWT validation & Tenant ID extraction.<br>• Build the state sync endpoint (accepts `STATE_CHANGE` events from UI). | 16h | 8h (Frontend tests state overrides) | API Contracts |
| **Phase 2: Week 2** | **Cognitive Core: Streaming & Inference**<br>• Integrate Vertex AI Gemini Multimodal stream (direct audio-in).<br>• Engineer specific system prompts (`user_persona`, `tenant_identity`, `active_objective`).<br>• Implement the Sliding Window Context Manager (summarize after 5 turns to stay under 14K token budget). | 32h | 12h (Frontend tests latency and transcription accuracy) | LiveKit Transport, Redis forms state |
| **Phase 2: Week 2** | **LangGraph Routing & Extraction**<br>• Implement deterministic extraction nodes (parsing Gemini output into strictly typed `FieldUpdate` lists).<br>• Build routing logic to determine `next_question` based on missing required form fields.<br>• Wire TTS synthesis delivery path (if not using native multimodal audio-out). | 24h | 16h (E2E UX flow testing with frontend) | Cognitive Core |
| **Phase 3: Week 3** | **Failure Modes & Circuit Breakers**<br>• Implement Circuit Breaker pattern (Timeout, Exponential Backoff, Fallback).<br>• Handle context window blowup failures ("Context Refresh" triggers).<br>• Configure graceful degradation hooks so the frontend can display AI failure/fallback states gracefully. | 20h | 16h (Chaos testing: dropping WebRTC, latency spikes) | LangGraph Orchestrator |
| **Phase 3: Week 3** | **Audit & NDIS Compliance Hardening**<br>• Implement async audit logging (PostgreSQL schema for full agent I/O logs, transcripts, tokens used).<br>• Apply PostgreSQL Row-Level Security (RLS) ensuring strict tenant isolation.<br>• Emit `voice.session_complete` to Pub/Sub for Human-In-The-Loop (HITL) Queue routing. | 24h | 12h (Backend integration & compliance sign-off) | Cognitive Core, RLS Scaffold |
| **Phase 4: Week 4** | **Performance Tuning & Final E2E**<br>• Optimize critical path latency (Target: < 1,000ms Voice-in to Voice-out).<br>• Run accuracy evaluations against test accents/dialects and noisy audio.<br>• Finalizing Load Testing (Concurrent WebRTC sessions and Redis thresholds). | 24h | 24h (UAT, Manager Review Queue testing) | All components |

### Execution Notes for the Engineering Team:
* **Immediate Unblocker:** By defining the Pydantic schemas for `FieldUpdate` and `FormState` on **Day 1**, the frontend team can immediately bind their components to the expected data structures.
* **Context Overload Protection:** The form state is **excluded** from the LLM prompt history and stored only in Redis, keeping the Gemini prompt strictly focused on the current conversational objective to guarantee speed and prevent context blowups. 
* **Frontend Authority:** The UI remains the single source of truth. If a user manually overrides an extracted field via the UI, the frontend fires a `STATE_CHANGE` event to overwrite the AI's Redis memory, forcing the Agent to acknowledge the visual correction.