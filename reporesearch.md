 All three research agents complete. Synthesizing the full analysis now.

  ★ Insight ─────────────────────────────────────
  Why this matters architecturally: Your current voice service is a turn-based HTTP pipeline (client sends transcript →
  server calls Bedrock → returns text). The design brief wants a real-time streaming voice agent (continuous
  bidirectional audio, <500ms latency, barge-in). These are fundamentally different architectures. The repos below each
  solve different pieces of that transition.
  ─────────────────────────────────────────────────

  ---
  Feature-to-Repo Mapping for SENA Voice Assistant

  Your Requirements (from design docs + brief)

  ┌─────┬───────────────────────────────────────────────────────────┬──────────┐
  │  #  │                          Feature                          │ Priority │
  ├─────┼───────────────────────────────────────────────────────────┼──────────┤
  │ F1  │ Gemini Live native audio (single-model STT+reasoning+TTS) │ Critical │
  ├─────┼───────────────────────────────────────────────────────────┼──────────┤
  │ F2  │ LiveKit Agents Framework integration                      │ Critical │
  ├─────┼───────────────────────────────────────────────────────────┼──────────┤
  │ F3  │ Hybrid Preload — massive system prompt context injection  │ Critical │
  ├─────┼───────────────────────────────────────────────────────────┼──────────┤
  │ F4  │ Non-blocking tool calls (WHEN_IDLE, background)           │ Critical │
  ├─────┼───────────────────────────────────────────────────────────┼──────────┤
  │ F5  │ VAD / barge-in / interruption handling                    │ Critical │
  ├─────┼───────────────────────────────────────────────────────────┼──────────┤
  │ F6  │ Voice-triggered camera + AI description                   │ High     │
  ├─────┼───────────────────────────────────────────────────────────┼──────────┤
  │ F7  │ Session state machine (14 states, idle/cost timeouts)     │ High     │
  ├─────┼───────────────────────────────────────────────────────────┼──────────┤
  │ F8  │ 5-level graceful degradation ladder                       │ High     │
  ├─────┼───────────────────────────────────────────────────────────┼──────────┤
  │ F9  │ Conversational form filling (20+ fields, 7-screen gated)  │ High     │
  ├─────┼───────────────────────────────────────────────────────────┼──────────┤
  │ F10 │ Token budget / sliding window context management          │ Medium   │
  ├─────┼───────────────────────────────────────────────────────────┼──────────┤
  │ F11 │ NDIS compliance (server-side audio, AU residency)         │ Critical │
  ├─────┼───────────────────────────────────────────────────────────┼──────────┤
  │ F12 │ Multi-tenant isolation in voice sessions                  │ Critical │
  ├─────┼───────────────────────────────────────────────────────────┼──────────┤
  │ F13 │ Accessibility (readback, pause/resume, name confirmation) │ High     │
  ├─────┼───────────────────────────────────────────────────────────┼──────────┤
  │ F14 │ Noise cancellation / accent handling                      │ Medium   │
  └─────┴───────────────────────────────────────────────────────────┴──────────┘

  ---
  What Each Repo Provides

  1. gemini-live-quickstart — Your Day-1 Starter

  ┌─────────────────────────────┬──────────┬──────────────────────────────────────────────────────────┐
  │           Feature           │ Coverage │                          Notes                           │
  ├─────────────────────────────┼──────────┼──────────────────────────────────────────────────────────┤
  │ F1 Gemini Live native audio │ Full     │ Uses gemini-2.5-flash-native-audio-preview, single model │
  ├─────────────────────────────┼──────────┼──────────────────────────────────────────────────────────┤
  │ F2 LiveKit Agents           │ Full     │ Built on Agents v1.3, working WebRTC bridge              │
  ├─────────────────────────────┼──────────┼──────────────────────────────────────────────────────────┤
  │ F5 VAD/barge-in             │ Full     │ Gemini's built-in VAD, automatic interruption            │
  ├─────────────────────────────┼──────────┼──────────────────────────────────────────────────────────┤
  │ F6 Camera + vision          │ Full     │ video_input=True — camera/screenshare to Gemini          │
  ├─────────────────────────────┼──────────┼──────────────────────────────────────────────────────────┤
  │ F3 System prompt            │ Partial  │ Supports instructions= but no dynamic preloading pattern │
  ├─────────────────────────────┼──────────┼──────────────────────────────────────────────────────────┤
  │ F4 Tool calling             │ None     │ No tools implemented                                     │
  ├─────────────────────────────┼──────────┼──────────────────────────────────────────────────────────┤
  │ F9 Form filling             │ None     │ No structured extraction                                 │
  └─────────────────────────────┴──────────┴──────────────────────────────────────────────────────────┘

  Verdict: Best starting point to validate Gemini Live audio round-trip with your existing LiveKit token endpoint. Clone
   → run → confirm latency. Then throw away and build properly.

  ---
  2. livekit/agents (core framework) — Your Production Foundation

  ┌────────────────────────┬──────────┬─────────────────────────────────────────────────────────────────────┐
  │        Feature         │ Coverage │                                Notes                                │
  ├────────────────────────┼──────────┼─────────────────────────────────────────────────────────────────────┤
  │ F1 Gemini Live         │ Full     │ google.realtime.RealtimeModel plugin                                │
  ├────────────────────────┼──────────┼─────────────────────────────────────────────────────────────────────┤
  │ F2 LiveKit Agents      │ Full     │ v1.4, the actual framework you'll build on                          │
  ├────────────────────────┼──────────┼─────────────────────────────────────────────────────────────────────┤
  │ F3 System prompt       │ Full     │ Agent(instructions=...) accepts arbitrary length                    │
  ├────────────────────────┼──────────┼─────────────────────────────────────────────────────────────────────┤
  │ F4 Tool calling        │ Full     │ @function_tool decorator, async tools, MCP integration              │
  ├────────────────────────┼──────────┼─────────────────────────────────────────────────────────────────────┤
  │ F5 VAD/barge-in        │ Full     │ Silero VAD + semantic turn detector + configurable thresholds       │
  ├────────────────────────┼──────────┼─────────────────────────────────────────────────────────────────────┤
  │ F8 Degradation         │ Partial  │ Supports provider switching but no automatic ladder                 │
  ├────────────────────────┼──────────┼─────────────────────────────────────────────────────────────────────┤
  │ F9 Form filling        │ Partial  │ restaurant_agent.py shows dynamic knowledge + tool calling patterns │
  ├────────────────────────┼──────────┼─────────────────────────────────────────────────────────────────────┤
  │ F14 Noise cancellation │ Full     │ BVC + Krisp integrations built-in                                   │
  └────────────────────────┴──────────┴─────────────────────────────────────────────────────────────────────┘

  Key examples to study:
  - restaurant_agent.py → tool calling pattern while maintaining conversation flow
  - basic_agent.py → minimal agent setup
  - Healthcare agent demo → closest to your NDIS domain

  Verdict: This IS your framework. Everything else is examples built on top of it.

  ---
  3. vision-demo — Camera/Accessibility Reference

  ┌────────────────────┬──────────┬─────────────────────────────────────────────┐
  │      Feature       │ Coverage │                    Notes                    │
  ├────────────────────┼──────────┼─────────────────────────────────────────────┤
  │ F6 Camera + vision │ Full     │ Gemini sees camera feed, describes verbally │
  ├────────────────────┼──────────┼─────────────────────────────────────────────┤
  │ F1 Gemini Live     │ Full     │ Native audio with vision                    │
  ├────────────────────┼──────────┼─────────────────────────────────────────────┤
  │ F13 Accessibility  │ Partial  │ Voice-only interaction with visual input    │
  └────────────────────┴──────────┴─────────────────────────────────────────────┘

  Verdict: Reference only for your voice-triggered camera feature (GAP 1 from design brief). The iOS Swift client is
  useful if your mobile team needs native reference. Outdated (v1.0) — patterns, not code.

  ---
  4. agent-starter-python — Production Template

  ┌────────────────────────┬──────────┬────────────────────────────────────────────────┐
  │        Feature         │ Coverage │                     Notes                      │
  ├────────────────────────┼──────────┼────────────────────────────────────────────────┤
  │ F2 LiveKit Agents      │ Full     │ v1.5 (newest), production Dockerfile included  │
  ├────────────────────────┼──────────┼────────────────────────────────────────────────┤
  │ F5 VAD/barge-in        │ Full     │ Multilingual turn detector                     │
  ├────────────────────────┼──────────┼────────────────────────────────────────────────┤
  │ F14 Noise cancellation │ Full     │ Dual: BVC + ai_coustics                        │
  ├────────────────────────┼──────────┼────────────────────────────────────────────────┤
  │ F8 Degradation         │ Partial  │ Pipeline mode (swap STT/LLM/TTS independently) │
  └────────────────────────┴──────────┴────────────────────────────────────────────────┘

  Catch: Default stack is Deepgram + OpenAI + Cartesia (NOT Gemini Live). You'd swap to Gemini, but the project
  structure, Dockerfile, eval suite, and production patterns are gold.

  Verdict: Best production scaffolding. Copy project structure, Dockerfile, eval patterns. Swap LLM to Gemini Live.

  ---
  5. python-agents-examples — The Cookbook

  ┌───────────────────────┬──────────┬─────────────────────────────────────────┐
  │        Feature        │ Coverage │                  Notes                  │
  ├───────────────────────┼──────────┼─────────────────────────────────────────┤
  │ F4 Tool calling       │ Full     │ Multiple patterns: sync, async, MCP     │
  ├───────────────────────┼──────────┼─────────────────────────────────────────┤
  │ F6 Vision             │ Full     │ Gemini + Grok + Moondream examples      │
  ├───────────────────────┼──────────┼─────────────────────────────────────────┤
  │ F9 Form filling       │ Partial  │ Structured output examples              │
  ├───────────────────────┼──────────┼─────────────────────────────────────────┤
  │ F7 Session management │ Partial  │ Session restore/context variables demos │
  ├───────────────────────┼──────────┼─────────────────────────────────────────┤
  │ F5 VAD/barge-in       │ Full     │ Multiple turn detection strategies      │
  ├───────────────────────┼──────────┼─────────────────────────────────────────┤
  │ F13 Accessibility     │ Partial  │ Push-to-talk, background audio patterns │
  └───────────────────────┴──────────┴─────────────────────────────────────────┘

  50+ single-concept demos. Cherry-pick patterns:
  - tool_calling/ → your non-blocking tool implementation
  - session_restore/ → your session state recovery after disconnects
  - structured_output/ → your field extraction
  - context_variables/ → your hybrid preload injection
  - guardrails/ → your safety detection

  Verdict: Don't adopt wholesale. Pick 5-6 specific patterns that map to your gaps.

  ---
  6. BexTuychiev/gist (Firecrawl agent) — Simplest Tool Calling Reference

  ┌─────────────────┬──────────┬──────────────────────────────────────────────────────┐
  │     Feature     │ Coverage │                        Notes                         │
  ├─────────────────┼──────────┼──────────────────────────────────────────────────────┤
  │ F4 Tool calling │ Full     │ 3 working tools (web search, Gmail read, Gmail send) │
  ├─────────────────┼──────────┼──────────────────────────────────────────────────────┤
  │ F1 Gemini Live  │ Full     │ google.realtime.RealtimeModel                        │
  └─────────────────┴──────────┴──────────────────────────────────────────────────────┘

  ~150 lines. Shows exactly how @function_tool + tools=[...] + AgentSession wire together.

  Verdict: Read this first before studying the larger repos. Fastest way to understand tool calling with Gemini Live.

  ---
  What NO Repo Provides (You Must Build)

  ┌──────────────────────────────────┬──────────────────────────────────────────────────────────────────────────────┐
  │             Feature              │                               Why It's Missing                               │
  ├──────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────┤
  │ F3 Hybrid Preload                │ Domain-specific — your participant data, phonetic maps, NDIS goals, form     │
  │ (context_preloader.py)           │ fields. No generic solution exists.                                          │
  ├──────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────┤
  │ F7 14-state session machine      │ Your audit spec defines this. Generic agents have start/running/ended only.  │
  ├──────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────┤
  │ F8 5-level degradation ladder    │ Your architecture audit's specific fallback chain (Gemini →                  │
  │                                  │ Deepgram+Claude+ElevenLabs → rule-based → record-only).                      │
  ├──────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────┤
  │ F9 7-screen gated form filling   │ Your api_contracts.py FormState with 40+ fields, gate logic, stale-field     │
  │                                  │ tracking.                                                                    │
  ├──────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────┤
  │ F10 Token budget / sliding       │ Your specific 5100-token cap, 5-turn summarization, tier A/B/C assembly.     │
  │ window                           │                                                                              │
  ├──────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────┤
  │ F11 NDIS compliance layer        │ PII filtering, audit log (blocks submission), consent/retention policy.      │
  ├──────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────┤
  │ F12 Multi-tenant voice isolation │ Redis key prefixes, LiveKit room naming, cost tracking per tenant.           │
  ├──────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────┤
  │ F13 Full accessibility suite     │ Name confirmation via phonetic alias map, readback-then-confirm flow,        │
  │                                  │ incident escalation.                                                         │
  └──────────────────────────────────┴──────────────────────────────────────────────────────────────────────────────┘

  ★ Insight ─────────────────────────────────────
  The 80/20 split is clear: The repos give you ~80% of the transport and audio infrastructure (LiveKit WebRTC, Gemini
  Live STT+TTS, VAD, tool calling framework, noise cancellation). You must build ~100% of the domain logic (NDIS
  compliance, form state machine, context preloading, degradation ladder, multi-tenant isolation, accessibility flows).
  This is expected — no open-source repo solves NDIS voice dictation.

  The critical architectural shift: Your current service treats voice as HTTP request-response (transcript in → text
  out). LiveKit Agents treats voice as a persistent bidirectional stream with an event loop. Your
  dictation_service.process_turn() becomes event handlers inside an Agent class. The routes.py endpoints become session
  lifecycle hooks, not the conversation driver.

  The Gemini Live data residency question is still blocking. None of these repos address whether australia-southeast1
  supports Gemini Live's native audio mode. If it doesn't, your entire Approach D architecture needs the degradation
  ladder (Level 2: Deepgram+Claude+ElevenLabs) as the primary path, not the fallback.
  ─────────────────────────────────────────────────

  ---
  Recommended Study Order

  1. Read first (30 min): BexTuychiev gist → understand tool calling wiring
  2. Validate (1 hour): gemini-live-quickstart → confirm audio round-trip works with your LiveKit
  3. Study patterns (2 hours): python-agents-examples → cherry-pick tool_calling/, context_variables/, session_restore/,
   structured_output/
  4. Study production (2 hours): livekit/agents restaurant_agent.py → tool calling mid-conversation without dead air
  5. Adopt structure (1 hour): agent-starter-python → project layout, Dockerfile, eval suite
  6. Reference only: vision-demo → camera integration patterns when you reach accessibility

  No code changes needed yet. Want me to deep-dive into any specific repo's code, or map out the migration path from
  your current Flow B to the Gemini Live architecture?
