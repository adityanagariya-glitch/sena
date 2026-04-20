# Voice Assistant Repository Research Report

Researched 2026-04-13. All repos are LiveKit ecosystem projects.

---

## 1. gemini-live-quickstart

**Repo:** https://github.com/livekit-examples/gemini-live-quickstart

### What It Implements
A minimal starter kit for building voice + vision agents using Gemini Live API over LiveKit. The single `agent.py` (~80 lines) creates a `VisionAgent` that can see the user's camera/screenshare and hold voice conversations. Includes a Next.js frontend with mic/camera controls. Has a "sports commentator" branch showing persona customization.

### Tech Stack
- **LLM:** Google Gemini 2.5 Flash Native Audio (`gemini-2.5-flash-native-audio-preview-12-2025`) via `livekit.plugins.google`
- **STT/TTS:** None separate — Gemini Live handles audio-in and audio-out natively (single model)
- **Framework:** `livekit-agents[google,images]~=1.3`, Python 3.10+
- **Frontend:** Next.js (in `/frontend`), pnpm
- **Voice:** "Aoede" (configurable)

### Tool Calling
No tool calling demonstrated in this quickstart. The agent is purely conversational + vision. Would need to add `@function_tool` decorators manually.

### System Prompt / Context Injection
- `PERSONA_INSTRUCTIONS` variable passed to the `VisionAgent` constructor
- `BASE_VIDEO_AWARENESS` baked into the Agent class as a static prefix to instructions
- Instructions are passed as a single string to `Agent(instructions=...)` — no documented size limit beyond Gemini's context window
- Context is set once at session start, not dynamically updated mid-session in this example

### VAD / Barge-in / Interruption
- **Gemini Live API includes built-in VAD-based turn detection** (enabled by default)
- No separate Silero VAD — the realtime model handles it natively
- Barge-in is inherent to Gemini Live's audio stream processing
- No configurable interruption thresholds in this example

### Vision / Camera Support
- **Yes, first-class.** `room_options=room_io.RoomOptions(video_input=True)`
- Tracks video subscribe/unsubscribe events
- Agent is aware of when camera is on/off via track event handlers
- Video frames sent to Gemini Live natively (multimodal input)

### Session Management
- `AgentSession` object created per `JobContext`
- `AgentServer` with `@server.rtc_session()` decorator handles room lifecycle
- LiveKit room-based session — one agent per room connection
- No persistent state across sessions

### Gemini Live Native Audio
- **YES — this is the primary purpose of this repo.** Uses `google.realtime.RealtimeModel` which is a single model doing STT + reasoning + TTS in one pass. No separate STT/TTS pipeline.

---

## 2. livekit/agents (core framework)

**Repo:** https://github.com/livekit/agents

### What It Implements
The **core LiveKit Agents framework** (10k+ GitHub stars, 3k+ forks). This is not a demo — it's the production framework that all other repos depend on. Provides:
- `AgentSession` orchestrator (manages STT → LLM → TTS pipeline or Realtime API)
- `Agent` base class with `instructions`, `tools`, lifecycle hooks (`on_enter`, etc.)
- `@function_tool` decorator for tool calling
- Plugin system for 15+ providers
- Semantic turn detection (transformer model)
- Job scheduling and dispatch APIs
- Built-in test/eval framework
- Native MCP (Model Context Protocol) support
- Telephony/SIP integration

The `examples/` directory contains production-quality reference implementations:
- `voice_agents/` — 25+ examples (basic, tool use, realtime models, multi-agent, vision, push-to-talk, background audio, LangGraph, speaker ID)
- `drive-thru/` — full drive-through ordering agent
- `healthcare/` — medical agent
- `frontdesk/` — reception agent
- `telephony/` — SIP calling examples
- `survey/` — automated survey agent
- `warm-transfer/` — call handoff to humans

### Tech Stack
- **LLM:** Any — OpenAI GPT-4.1, Anthropic Claude, Google Gemini, Groq, AWS Bedrock, X.AI Grok, NVIDIA, Cerebras
- **STT:** Deepgram Nova-3, AssemblyAI, Gladia, Cartesia, Sarvam
- **TTS:** Cartesia Sonic-3, ElevenLabs, Rime, PlayAI, Inworld, OpenAI
- **VAD:** Silero VAD (prewarmed in process)
- **Realtime APIs:** OpenAI Realtime, Google Gemini Live, AWS Nova Sonic, Phonic
- **Framework:** `livekit-agents~=1.4` (current stable), Python 3.10+
- **Unified API:** `inference.STT("deepgram/nova-3")`, `inference.LLM("openai/gpt-4.1-mini")`, `inference.TTS("cartesia/sonic-3")` via LiveKit Inference (hosted gateway)

### Tool Calling
**Comprehensive support:**
- `@function_tool` decorator on Agent methods or standalone functions
- Args defined via Python type hints + docstrings (auto-converted to function schema)
- `RunContext` provides session state to tools
- Works with both pipeline mode (STT→LLM→TTS) and Realtime APIs
- `async_tool_agent.py` — async tools that don't block speech
- `long_running_function.py` — tools that take time, agent keeps talking
- `raw_function_agent.py` — low-level function call handling
- `annotated_tool_args.py` — advanced argument annotations
- `EndCallTool` built-in for graceful call termination
- Native MCP support — integrate MCP server tools with one line of code
- LangGraph integration for complex tool orchestration

### System Prompt / Context Injection
- `Agent(instructions="...")` — system prompt set at construction
- `session.generate_reply(instructions="...")` — per-turn instruction override
- `agent.update_chat_ctx(chat_ctx)` — dynamically update conversation context mid-session
- `realtime_load_chat_history.py` — shows loading previous chat history into realtime models
- `change_agent_instructions` example — dynamic instruction modification
- `context_variables` example — injecting runtime context
- No hard limit documented; bounded by underlying LLM context window

### VAD / Barge-in / Interruption
**Most sophisticated of all repos:**
- **Silero VAD** — prewarmed at process start for latency
- **Semantic turn detection** — transformer model (`MultilingualModel()`) that understands *when the user is done speaking*, not just silence
- **Configurable interruption handling:**
  ```python
  turn_handling=TurnHandlingOptions(
      turn_detection=MultilingualModel(),
      interruption={
          "min_interruption_duration": 0.5,  # ignore < 500ms interruptions
      }
  )
  ```
- **Push-to-talk mode** — disables automatic VAD, user controls when to speak
- Background voice cancellation via `noise_cancellation.BVC()` and `ai_coustics` plugin
- For Realtime APIs (Gemini, OpenAI), the model's built-in VAD is used but can be augmented with LiveKit's turn detector

### Vision / Camera Support
- `room_options=room_io.RoomOptions(video_input=True)` to enable
- `VoiceActivityVideoSampler` — configurable FPS (default: 1fps while speaking, 0.3fps silent)
- Works with Gemini Live and OpenAI Realtime (multimodal models)
- `realtime_video_agent.py` example with Google Gemini
- Image/byte stream handling for non-realtime vision (Moondream, GPT-4V)

### Session Management
- `AgentServer` — manages process pool and job dispatch
- `AgentSession` — per-conversation session with full state
- `JobContext` — room connection context with logging
- `@server.rtc_session(agent_name="my-agent")` — named agents for dispatch
- Prewarm via `setup_fnc` — preload models before sessions
- `MetricsCollectedEvent` — latency/cost tracking
- RPCs and Data APIs for client-agent data exchange
- Reconnection handling built into LiveKit transport

### Gemini Live Native Audio
- **Yes, fully supported** via `google.realtime.RealtimeModel()` plugin
- Also supports OpenAI Realtime and AWS Nova Sonic
- Can combine realtime model with external TTS (`realtime_with_tts.py`)

---

## 3. vision-demo

**Repo:** https://github.com/livekit-examples/vision-demo

> **NOTE:** Marked as **outdated** by LiveKit. Vision is now built into the agent-starter-python and core framework.

### What It Implements
A voice + video AI assistant with a native iOS frontend. The agent sees the user's camera feed or screen share and can discuss what it sees in real-time. Includes background mode — continues voice conversations while the user multitasks on their phone.

### Tech Stack
- **LLM:** Google Gemini via `google.beta.realtime.RealtimeModel` (voice="Puck")
- **STT/TTS:** Gemini Live native audio (single model)
- **Framework:** `livekit-agents[google,images]~=1.0` (older, >=1.0.18)
- **Frontend:** Native iOS (Swift SDK, Xcode 16, iOS 17+)
- **Noise cancellation:** `livekit-plugins-noise-cancellation` (BVC)

### Tool Calling
No tool calling in this demo. Pure conversational vision agent.

### System Prompt / Context Injection
- `Agent(instructions="You are a helpful voice assistant.")` — minimal prompt
- Images received via LiveKit byte stream are injected into `chat_ctx` as `ImageContent`
- Dynamic context update: `await self.update_chat_ctx(chat_ctx)` after receiving images

### VAD / Barge-in / Interruption
- Relies on Gemini Live's built-in VAD
- No separate Silero VAD or turn detector configured
- Background noise cancellation via `noise_cancellation.BVC()`

### Vision / Camera Support
- **Primary feature of this repo**
- Front and back camera support on iOS
- Live screen sharing
- Video frames sampled at **1 FPS while speaking, 0.3 FPS when silent**
- Images sent as JPEG at 1024x1024 max
- `RoomInputOptions(video_enabled=True)`
- Image byte stream handler for custom image injection
- Background mode — continues in background while using other apps

### Session Management
- `AgentSession()` per `JobContext`
- `WorkerOptions` + `cli.run_app()` (older API pattern, pre-AgentServer)
- Compatible with LiveKit Agents Playground for browser testing

### Gemini Live Native Audio
- **Yes.** Uses `google.beta.realtime.RealtimeModel` — single model for audio I/O + reasoning + vision.

---

## 4. agent-starter-python

**Repo:** https://github.com/livekit-examples/agent-starter-python

### What It Implements
The **official recommended starting point** for building voice AI agents with LiveKit. A production-ready template with:
- Complete STT → LLM → TTS voice pipeline
- Multilingual turn detection
- Background voice cancellation (two options: BVC + ai_coustics)
- Eval/test suite
- Dockerfile for production deployment
- AGENTS.md for coding assistants

### Tech Stack
- **LLM:** OpenAI GPT-5.3 via `inference.LLM("openai/gpt-5.3-chat-latest")` (LiveKit Inference gateway)
- **STT:** Deepgram Nova-3 multilingual via `inference.STT("deepgram/nova-3")`
- **TTS:** Cartesia Sonic-3 via `inference.TTS("cartesia/sonic-3")`
- **VAD:** Silero VAD (prewarmed)
- **Turn Detection:** `MultilingualModel()` from `livekit.plugins.turn_detector.multilingual`
- **Noise Cancellation:** `ai_coustics` plugin + `noise_cancellation.BVC()`
- **Framework:** `livekit-agents[silero,turn-detector]~=1.5`, Python 3.10-3.14
- **Frontend:** None included — use separate starter repos (React, Swift, Flutter, React Native, Android, web embed)

### Tool Calling
- Commented-out example of `@function_tool` in the source code showing the pattern
- Shows `lookup_weather` tool with `RunContext` and `location` arg
- Designed to be extended by the developer

### System Prompt / Context Injection
- `Agent(instructions="...")` — voice-aware system prompt
- `session.generate_reply(instructions="greet the user")` for initial greeting
- No dynamic context injection shown, but `update_chat_ctx` is available from the framework

### VAD / Barge-in / Interruption
- **Silero VAD** prewarmed at process start
- **Multilingual semantic turn detector** — `MultilingualModel()`
- Configurable interruption: `min_interruption_duration: 0.5` seconds
- `ai_coustics` for AI-powered noise cancellation
- `noise_cancellation.BVC()` for background voice cancellation

### Vision / Camera Support
Not included in the default template, but the README notes it can be added easily with `RoomInputOptions(video_enabled=True)`.

### Session Management
- `AgentServer` with `@server.rtc_session(agent_name="my-agent")`
- `prewarm` function for model preloading
- `ctx.log_context_fields` for structured logging
- Dockerfile included for LiveKit Cloud deployment
- Compatible with all LiveKit frontend SDKs and telephony

### Gemini Live Native Audio
Not the default (uses pipeline mode), but the README mentions 50+ model providers including Realtime models. Switching to Gemini Live would require changing to `google.realtime.RealtimeModel`.

---

## 5. python-agents-examples

**Repo:** https://github.com/livekit-examples/python-agents-examples

### What It Implements
The **comprehensive example cookbook** — 50+ single-concept demos plus 20+ production-style complex agents. This is the reference library for every LiveKit Agents pattern. Categories:

**Fundamentals:** listen & respond, tool calling, context variables, changing instructions, changing language, custom LLM, greeting agent

**Session & State:** restore session, handoff patterns, agent transfer, multi-agent orchestration

**Telephony:** answer call, make call, warm handoff, SIP lifecycle, survey caller, IVR navigator

**Vision & Multimodal:** Gemini Live Vision, Vision Agent (Grok-2), Moondream Vision

**Advanced:** structured output, parallel tool calls, guardrails, long-running tasks, streaming responses, file upload, MCP integration

**Complex Agents (with frontends):** drive-thru, restaurant host, call moderation, call queue, Deepgram configure, Exa deep research, music agent, podcaster, storyteller, flashcard tutor, trivia game, avatars (Hedra, Tavus), vision agent, IVR agent

### Tech Stack
- **LLM:** OpenAI, Anthropic, Google Gemini, Groq, Cerebras, AWS Bedrock, X.AI — all demonstrated
- **STT:** Deepgram, Gladia, Sarvam, AssemblyAI, Cartesia
- **TTS:** Cartesia, ElevenLabs, Rime, PlayAI, Inworld, OpenAI
- **VAD:** Silero
- **Realtime:** OpenAI Realtime, Google Gemini Live, AWS Nova Sonic
- **Avatar:** Hedra, Tavus, LemonSlice
- **Vision:** GPT-4V, Google Gemini, Grok-2 Vision, Moondream
- **Framework:** `livekit-agents` (requires 1.0+), Python 3.10+
- **Additional:** LangChain, LangGraph, MCP, Firecrawl, Flask, pandas, annoy (vector search)

### Tool Calling
**Most extensively demonstrated:**
- Basic `@function_tool` pattern
- Parallel tool calls
- Long-running async tools
- Tools with RunContext for session state access
- Structured output from tools
- LangGraph-based tool orchestration
- MCP server tool integration
- Guardrails on tool outputs
- Multi-agent tool delegation

### System Prompt / Context Injection
- All examples use `Agent(instructions="...")`
- `change_agent_instructions` example — modify instructions mid-session
- `context_variables` example — inject runtime data into agent context
- `restore_session` example — reload previous conversation state
- `realtime_load_chat_history` — preload chat history into realtime models
- Dynamic `update_chat_ctx` for mid-conversation context changes

### VAD / Barge-in / Interruption
- Silero VAD across all examples
- Semantic turn detection where shown
- `preemptive_generation=True` on AgentSession — agent starts generating before user fully finishes (reduces latency)
- Push-to-talk examples available in core repo

### Vision / Camera Support
- `gemini_live_vision.py` — Gemini 2.5 Flash with `RoomInputOptions(video_enabled=True)`, proactivity enabled, affective dialog
- `vision` complex agent — Grok-2 Vision
- `moondream_vision` — adds vision to non-vision LLMs via Moondream

### Session Management
- Same `AgentServer` / `AgentSession` / `JobContext` pattern as core framework
- Session restore examples
- Multi-agent handoff/transfer patterns
- Call queue management for production telephony

### Gemini Live Native Audio
- **Yes.** `gemini_live_vision.py` uses `google.beta.realtime.RealtimeModel` with `gemini-2.5-flash-native-audio-preview-09-2025`
- Also demonstrates `proactivity=True` (agent speaks unprompted) and `enable_affective_dialog=True` (emotional tone)

---

## 6. BexTuychiev Gist (agent.py)

**Repo:** https://gist.github.com/BexTuychiev/9d5fbb22d58db26f1147c60ff48978a7

### What It Implements
A **single-file tutorial companion** showing a voice assistant with Gemini Live API + Firecrawl web search + Gmail integration. Demonstrates practical tool calling with real external services. Class: `ResearchAssistant(Agent)`.

### Tech Stack
- **LLM:** Google Gemini 2.5 Flash Native Audio (`gemini-2.5-flash-native-audio-preview-12-2025`) via `livekit.plugins.google`
- **STT/TTS:** Gemini Live native audio (single model)
- **Framework:** LiveKit Agents (version not pinned in gist)
- **Voice:** "Puck"
- **External APIs:** Firecrawl (web search), Gmail (IMAP + SMTP)

### Tool Calling
**Three practical tools demonstrated:**
1. `web_search(query)` — uses Firecrawl API to search the web, returns formatted results with titles/descriptions/URLs
2. `read_emails(count)` — reads recent Gmail inbox via IMAP, returns sender/subject/preview
3. `send_email(to, subject, body)` — sends email via Gmail SMTP

All defined as standalone `@function_tool` async functions (not Agent methods). Passed to AgentSession via `tools=[web_search, read_emails, send_email]`.

### System Prompt / Context Injection
```
"You are a helpful research assistant with access to web search and email.
You can search the web for current information, read the user's recent emails,
and send emails on their behalf. Always confirm before sending emails.
Keep your responses concise and conversational since you're communicating via voice."
```
- Set once at `Agent.__init__`
- No dynamic context injection shown

### VAD / Barge-in / Interruption
- Relies entirely on Gemini Live's built-in VAD
- No Silero VAD or turn detector configured
- No interruption configuration

### Vision / Camera Support
**None.** Audio-only agent.

### Session Management
- `AgentServer` + `@server.rtc_session()` pattern
- `AgentSession` created per room connection
- No persistent state, session restore, or multi-agent patterns

### Gemini Live Native Audio
- **Yes.** Uses `google.realtime.RealtimeModel` — single model for STT + reasoning + TTS.

---

## Comparative Summary Table

| Feature | 1. gemini-live-quickstart | 2. livekit/agents (framework) | 3. vision-demo | 4. agent-starter-python | 5. python-agents-examples | 6. BexTuychiev gist |
|---|---|---|---|---|---|---|
| **Purpose** | Gemini + vision quickstart | Core framework + examples | Vision + iOS demo | Production starter template | Cookbook (70+ examples) | Tutorial companion |
| **Primary LLM** | Gemini 2.5 Flash | Any (15+ providers) | Gemini (beta realtime) | OpenAI GPT-5.3 | All major providers | Gemini 2.5 Flash |
| **STT** | Gemini native | Deepgram, AssemblyAI, Gladia, etc. | Gemini native | Deepgram Nova-3 | All major | Gemini native |
| **TTS** | Gemini native | Cartesia, ElevenLabs, etc. | Gemini native | Cartesia Sonic-3 | All major | Gemini native |
| **Framework version** | ~=1.3 | ~=1.4 (latest) | ~=1.0 (old) | ~=1.5 | 1.0+ | Not pinned |
| **Tool calling** | None | Full (@function_tool, MCP, LangGraph) | None | Commented example | Extensive (10+ patterns) | 3 practical tools |
| **System prompt** | Static + video awareness | Dynamic, updatable mid-session | Minimal | Static + greeting | Dynamic, restorable | Static |
| **VAD** | Gemini built-in | Silero + semantic turn detector | Gemini built-in | Silero + multilingual turn detector | Silero + semantic | Gemini built-in |
| **Barge-in** | Gemini native | Configurable (min_duration, semantic) | Gemini native | Configurable (0.5s threshold) | Configurable | Gemini native |
| **Vision/camera** | Yes (video_input) | Yes (configurable FPS) | Yes (primary feature, iOS) | Not default, easy to add | Yes (3 examples) | No |
| **Session mgmt** | Basic (per-room) | Full (dispatch, metrics, reconnect) | Basic (per-room) | Production (Docker, logging) | Full (restore, transfer, queue) | Basic (per-room) |
| **Gemini Live native audio** | YES | YES (+ OpenAI RT, Nova Sonic) | YES | No (pipeline mode) | YES | YES |
| **Noise cancellation** | No | Yes (BVC + ai_coustics) | Yes (BVC) | Yes (BVC + ai_coustics) | Yes | No |
| **Telephony/SIP** | No | Yes | No | Compatible | Yes (6 examples) | No |
| **MCP support** | No | Yes (native) | No | No | Yes | No |
| **Frontend included** | Next.js | No (separate repos) | Swift/iOS | No (separate repos) | Yes (20+ complex agents) | No |
| **Test framework** | No | Yes (built-in) | No | Yes (pytest) | No | No |

---

## Key Takeaways for SENA

1. **For Gemini Live native audio (single-model STT+reasoning+TTS):** Repos 1, 3, 5, and 6 all demonstrate this. The pattern is simply `llm=google.realtime.RealtimeModel(model="gemini-2.5-flash-native-audio-preview-*")` with no separate STT/TTS needed.

2. **For tool calling mid-conversation:** Repo 2 (framework) and Repo 5 (examples) are the authoritative references. The `@function_tool` decorator works with both pipeline mode and Realtime APIs. The gist (Repo 6) shows the simplest practical pattern.

3. **For production readiness:** Repo 4 (agent-starter-python) is the recommended starting template, and Repo 2 (livekit/agents) is the framework itself with ~=1.5 being current.

4. **For vision support with Gemini:** Repo 1 is the latest/cleanest example. Repo 3 is outdated but shows the iOS frontend pattern.

5. **Context injection at session start** is straightforward (pass to `instructions`). Dynamic mid-session context update uses `update_chat_ctx()`. For Gemini Live, preloading context into System Instructions avoids tool-call latency during conversation.

6. **VAD/interruption:** When using Gemini Live native audio, the model handles VAD internally. For pipeline mode (STT→LLM→TTS), LiveKit provides Silero VAD + a semantic turn detector that understands conversational context, plus configurable interruption thresholds.
