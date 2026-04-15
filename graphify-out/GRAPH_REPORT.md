# Graph Report - .  (2026-04-13)

## Corpus Check
- 89 files · ~102,382 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 339 nodes · 339 edges · 75 communities detected
- Extraction: 90% EXTRACTED · 10% INFERRED · 0% AMBIGUOUS · INFERRED: 33 edges (avg confidence: 0.69)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_API Contracts & Form State|API Contracts & Form State]]
- [[_COMMUNITY_Bedrock LLM & Dictation Pipeline|Bedrock LLM & Dictation Pipeline]]
- [[_COMMUNITY_Approval Workflow & DB Models|Approval Workflow & DB Models]]
- [[_COMMUNITY_Sprint Gates & Gap Tracking|Sprint Gates & Gap Tracking]]
- [[_COMMUNITY_Platform Constraints & Decisions|Platform Constraints & Decisions]]
- [[_COMMUNITY_Multi-Agent System Design|Multi-Agent System Design]]
- [[_COMMUNITY_Observability & External Services|Observability & External Services]]
- [[_COMMUNITY_POC Onboarding Chatbot|POC Onboarding Chatbot]]
- [[_COMMUNITY_API Phase 1 Tests|API Phase 1 Tests]]
- [[_COMMUNITY_Voice API Routes|Voice API Routes]]
- [[_COMMUNITY_Auth Service|Auth Service]]
- [[_COMMUNITY_SNS Event Service|SNS Event Service]]
- [[_COMMUNITY_Test Fixtures|Test Fixtures]]
- [[_COMMUNITY_Session Start Tests|Session Start Tests]]
- [[_COMMUNITY_App Factory & Lifespan|App Factory & Lifespan]]
- [[_COMMUNITY_DB Session Dependencies|DB Session Dependencies]]
- [[_COMMUNITY_Voice Settings Config|Voice Settings Config]]
- [[_COMMUNITY_Approval Tests|Approval Tests]]
- [[_COMMUNITY_Health Check Tests|Health Check Tests]]
- [[_COMMUNITY_Turn Processing Tests|Turn Processing Tests]]
- [[_COMMUNITY_Pydantic Schemas|Pydantic Schemas]]
- [[_COMMUNITY_Voice Repository|Voice Repository]]
- [[_COMMUNITY_Redis State Service|Redis State Service]]
- [[_COMMUNITY_LiveKit Service|LiveKit Service]]
- [[_COMMUNITY_Transcription Service|Transcription Service]]
- [[_COMMUNITY_Personal Details Service|Personal Details Service]]
- [[_COMMUNITY_Dictation Prompt Template|Dictation Prompt Template]]
- [[_COMMUNITY_Personal Details Prompt|Personal Details Prompt]]
- [[_COMMUNITY_Idempotency Utils|Idempotency Utils]]
- [[_COMMUNITY_Logging Config|Logging Config]]
- [[_COMMUNITY_OCR Service Scaffold|OCR Service Scaffold]]
- [[_COMMUNITY_OCR Routes & Config|OCR Routes & Config]]
- [[_COMMUNITY_OCR Tests|OCR Tests]]
- [[_COMMUNITY_Shared DB Base|Shared DB Base]]
- [[_COMMUNITY_Shared DB Session|Shared DB Session]]
- [[_COMMUNITY_Shared Error Middleware|Shared Error Middleware]]
- [[_COMMUNITY_Shared Request ID Middleware|Shared Request ID Middleware]]
- [[_COMMUNITY_Shared Tenant Middleware|Shared Tenant Middleware]]
- [[_COMMUNITY_Shared Error Schemas|Shared Error Schemas]]
- [[_COMMUNITY_Shared Response Schemas|Shared Response Schemas]]
- [[_COMMUNITY_Shared Tenant Tests|Shared Tenant Tests]]
- [[_COMMUNITY_Shared Common Init|Shared Common Init]]
- [[_COMMUNITY_Shared Auth Init|Shared Auth Init]]
- [[_COMMUNITY_Shared Config Init|Shared Config Init]]
- [[_COMMUNITY_Shared DB Init|Shared DB Init]]
- [[_COMMUNITY_Shared Middleware Init|Shared Middleware Init]]
- [[_COMMUNITY_Shared Schemas Init|Shared Schemas Init]]
- [[_COMMUNITY_Shared Config Settings|Shared Config Settings]]
- [[_COMMUNITY_Shared Test Conftest|Shared Test Conftest]]
- [[_COMMUNITY_Voice Init|Voice Init]]
- [[_COMMUNITY_Voice API Init|Voice API Init]]
- [[_COMMUNITY_Voice Core Init|Voice Core Init]]
- [[_COMMUNITY_Voice Models Init|Voice Models Init]]
- [[_COMMUNITY_Voice Services Init|Voice Services Init]]
- [[_COMMUNITY_Voice Repos Init|Voice Repos Init]]
- [[_COMMUNITY_Voice Prompts Init|Voice Prompts Init]]
- [[_COMMUNITY_Voice Utils Init|Voice Utils Init]]
- [[_COMMUNITY_OCR Init|OCR Init]]
- [[_COMMUNITY_OCR API Init|OCR API Init]]
- [[_COMMUNITY_OCR Core Init|OCR Core Init]]
- [[_COMMUNITY_OCR Models Init|OCR Models Init]]
- [[_COMMUNITY_OCR Service Init|OCR Service Init]]
- [[_COMMUNITY_Alembic Migrations|Alembic Migrations]]
- [[_COMMUNITY_Seed Dev Data|Seed Dev Data]]
- [[_COMMUNITY_Session End Tests|Session End Tests]]
- [[_COMMUNITY_Sprint 0 Plan|Sprint 0 Plan]]
- [[_COMMUNITY_Voice Onboarding Timeline|Voice Onboarding Timeline]]
- [[_COMMUNITY_Git Commands Reference|Git Commands Reference]]
- [[_COMMUNITY_Client Questions|Client Questions]]
- [[_COMMUNITY_Remaining Questions|Remaining Questions]]
- [[_COMMUNITY_Plan V1|Plan V1]]
- [[_COMMUNITY_Plan V2 Revised|Plan V2 Revised]]
- [[_COMMUNITY_Requirements File|Requirements File]]
- [[_COMMUNITY_README Overview|README Overview]]
- [[_COMMUNITY_GEMINI Config|GEMINI Config]]

## God Nodes (most connected - your core abstractions)
1. `VoiceRepository` - 26 edges
2. `RedisService` - 10 edges
3. `PersonalDetailsService` - 9 edges
4. `Base` - 8 edges
5. `DictationService` - 8 edges
6. `SENA Platform Overview` - 8 edges
7. `Voice Onboarding Implementation Timeline` - 8 edges
8. `Merged Sprint 0 + Voice Execution Plan` - 8 edges
9. `BedrockService` - 7 edges
10. `Voice Service (Flow B)` - 7 edges

## Surprising Connections (you probably didn't know these)
- `Extras Claude.md Project Context` --semantically_similar_to--> `SENA Platform Overview`  [INFERRED] [semantically similar]
  Extras/Claude.md → CLAUDE.md
- `Sliding Window Context Manager` --semantically_similar_to--> `Token Budget Guard with Fallback Summarization`  [INFERRED] [semantically similar]
  VOICE_ONBOARDING_TIMELINE.md → plan-hybridVoiceFormContext.prompt.md
- `Circuit Breaker Pattern` --semantically_similar_to--> `Circuit Breaker Configuration Table`  [INFERRED] [semantically similar]
  VOICE_ONBOARDING_TIMELINE.md → SENA_Architecture_Audit (1).md
- `DictationAgent (Bedrock Claude Sonnet)` --semantically_similar_to--> `Approach A: Manual Backend WS + Tool Calling`  [INFERRED] [semantically similar]
  Extras/FlowB.md → voice_architecture_analysis.md
- `Audit: Context Preloader Timing Risk` --semantically_similar_to--> `Global Session Memory + Screen-Scoped Context`  [INFERRED] [semantically similar]
  SENA_Architecture_Audit (1).md → plan-hybridVoiceFormContext.prompt.md

## Hyperedges (group relationships)
- **Voice Architecture Design Evolution (v1 -> Audit -> Hybrid)** — voice_arch_analysis, vaa_recommendation, sena_audit, audit_degradation_ladder, plan_hybrid_voice, flowb_implementation_guide [INFERRED 0.85]
- **Sprint 0 Gate Dependencies (Must -> Should -> Voice Promotion)** — sprint0_plan, merged_execution_plan, mep_gate_a, mep_gate_b, mep_gate_c, plan_gated_merge, phase12_gap_tracker [EXTRACTED 0.90]
- **System Design Document Version Chain (v1 -> v2 -> v3)** — extras_plan, plan_v1, multi_agent_design, new_plan_v2, plan_v2_revised, revised_plan_v3 [EXTRACTED 0.90]

## Communities

### Community 0 - "API Contracts & Form State"
Cohesion: 0.09
Nodes (36): Allergy, ContextPacket, EmergencyContact, FieldUpdateItem, FieldUpdateResponse, FormState, generate_webrtc_token(), get_state() (+28 more)

### Community 1 - "Bedrock LLM & Dictation Pipeline"
Cohesion: 0.08
Nodes (8): BedrockService, DictationService, _compute_completeness(), _compute_missing(), PersonalDetailsService, RedisService, TranscribeService, TranscribeTurn

### Community 2 - "Approval Workflow & DB Models"
Cohesion: 0.09
Nodes (10): ApprovalService, ApprovalQueueItem, Base, CaseNoteDraft, DictationTurn, OutboxEvent, PersonalDetailsDraft, VoiceSession (+2 more)

### Community 3 - "Sprint Gates & Gap Tracking"
Cohesion: 0.08
Nodes (27): Circuit Breaker Configuration Table, Audit: Context Preloader Timing Risk, Graceful Degradation Ladder (5 Levels), Audit Blind Spot: No Fallback Voice Pipeline, Gap P2-G1: Gemini Multimodal Not Integrated, Gap P2-G2: Typed Extraction Pipeline Missing, Gap P2-G3: Sliding Window Context Manager Missing, Gate A: Sprint 0 Must Requirements (+19 more)

### Community 4 - "Platform Constraints & Decisions"
Cohesion: 0.09
Nodes (26): Audit Blind Spot: No Multi-Tenancy Model in Voice, Australian Data Residency, Human-in-the-Loop Approval, Hybrid Search (Vector + Keyword) Decision, Multi-Tenant Data Isolation, NDIS Compliance, pgvector for Embeddings Decision, Row-Level Security (RLS) Decision (+18 more)

### Community 5 - "Multi-Agent System Design"
Cohesion: 0.1
Nodes (22): Dual Postgres Pattern (AI DB + Shared DB), 10 AI Modules Scope, Hierarchical Multi-Agent Topology, LangGraph StateGraph Framework, Shared Service Layer (RAG, Audit, Approval, Tenant), Multi-Agent System Design Document, System Design v2 (Federated Microservices), Federated Microservices Topology (v2) (+14 more)

### Community 6 - "Observability & External Services"
Cohesion: 0.1
Nodes (21): Audit: NON_BLOCKING Tool Calls Experimental Risk, Audit Blind Spot: No Observability Architecture, Hardened Session State Machine, Audit: VAD Reliability in Noisy Environments, AWS Bedrock (Claude 3.5 Sonnet), LiveKit Real-Time Voice, Redis Session State, AWS SNS Event Publishing (+13 more)

### Community 7 - "POC Onboarding Chatbot"
Cohesion: 0.15
Nodes (11): AgentState, OnboardingState, Use this tool to search for NDIS or company policies if the user asks a question, Use this tool to update the onboarding form when the user provides their details, Executes the tool and updates the form data in the state., Route to tools if the LLM called a tool, otherwise end turn., route_actions(), search_policy() (+3 more)

### Community 8 - "API Phase 1 Tests"
Cohesion: 0.15
Nodes (12): Test Case 5: Verify Redis Persistence (State Retrieval)     Prove that Redis ho, Test Case 1: Initial Connection     Verify the system handles empty states corr, Test Case 6: WebRTC Telemetry Auth Token     Ensure the backend generates a val, Test Case 2: Provide Single Field (Standard Turn)     Verify the router acknowl, Test Case 3: Bulk Fulfillment     Verify the router skips fulfilled fields and, Test Case 4: Verify Complex Nested Structures     Verify the Pydantic models cl, test_01_initial_connection(), test_02_provide_single_field() (+4 more)

### Community 9 - "Voice API Routes"
Cohesion: 0.24
Nodes (6): end_personal_details_session(), end_session(), process_personal_details_turn(), process_turn(), start_personal_details_session(), start_session()

### Community 10 - "Auth Service"
Cohesion: 0.57
Nodes (5): auth_context_dependency(), AuthContext, get_auth_context_from_dev_headers(), get_auth_context_from_jwt(), _parse_uuid()

### Community 11 - "SNS Event Service"
Cohesion: 0.4
Nodes (1): EventService

### Community 12 - "Test Fixtures"
Cohesion: 0.5
Nodes (0): 

### Community 13 - "Session Start Tests"
Cohesion: 0.5
Nodes (0): 

### Community 14 - "App Factory & Lifespan"
Cohesion: 0.67
Nodes (0): 

### Community 15 - "DB Session Dependencies"
Cohesion: 0.67
Nodes (0): 

### Community 16 - "Voice Settings Config"
Cohesion: 0.67
Nodes (2): BaseSettings, VoiceSettings

### Community 17 - "Approval Tests"
Cohesion: 0.67
Nodes (0): 

### Community 18 - "Health Check Tests"
Cohesion: 0.67
Nodes (0): 

### Community 19 - "Turn Processing Tests"
Cohesion: 0.67
Nodes (0): 

### Community 20 - "Pydantic Schemas"
Cohesion: 0.67
Nodes (2): Tenant A's private document chunks are invisible to Tenant B., test_tenant_a_cannot_see_tenant_b_document_chunks()

### Community 21 - "Voice Repository"
Cohesion: 1.0
Nodes (0): 

### Community 22 - "Redis State Service"
Cohesion: 1.0
Nodes (0): 

### Community 23 - "LiveKit Service"
Cohesion: 1.0
Nodes (0): 

### Community 24 - "Transcription Service"
Cohesion: 1.0
Nodes (0): 

### Community 25 - "Personal Details Service"
Cohesion: 1.0
Nodes (0): 

### Community 26 - "Dictation Prompt Template"
Cohesion: 1.0
Nodes (0): 

### Community 27 - "Personal Details Prompt"
Cohesion: 1.0
Nodes (2): Authentication Modes (dev_header / jwt), Gap P1-G1: JWT Validation Middleware Missing

### Community 28 - "Idempotency Utils"
Cohesion: 1.0
Nodes (2): Cost Governor / Zombie Session Protection, Cost Guard (Token Caps + Retries)

### Community 29 - "Logging Config"
Cohesion: 1.0
Nodes (2): Extras plan.md (Original Design v1), System Design v1 (Hierarchical Multi-Agent)

### Community 30 - "OCR Service Scaffold"
Cohesion: 1.0
Nodes (0): 

### Community 31 - "OCR Routes & Config"
Cohesion: 1.0
Nodes (0): 

### Community 32 - "OCR Tests"
Cohesion: 1.0
Nodes (0): 

### Community 33 - "Shared DB Base"
Cohesion: 1.0
Nodes (0): 

### Community 34 - "Shared DB Session"
Cohesion: 1.0
Nodes (0): 

### Community 35 - "Shared Error Middleware"
Cohesion: 1.0
Nodes (0): 

### Community 36 - "Shared Request ID Middleware"
Cohesion: 1.0
Nodes (0): 

### Community 37 - "Shared Tenant Middleware"
Cohesion: 1.0
Nodes (0): 

### Community 38 - "Shared Error Schemas"
Cohesion: 1.0
Nodes (0): 

### Community 39 - "Shared Response Schemas"
Cohesion: 1.0
Nodes (0): 

### Community 40 - "Shared Tenant Tests"
Cohesion: 1.0
Nodes (0): 

### Community 41 - "Shared Common Init"
Cohesion: 1.0
Nodes (0): 

### Community 42 - "Shared Auth Init"
Cohesion: 1.0
Nodes (0): 

### Community 43 - "Shared Config Init"
Cohesion: 1.0
Nodes (0): 

### Community 44 - "Shared DB Init"
Cohesion: 1.0
Nodes (0): 

### Community 45 - "Shared Middleware Init"
Cohesion: 1.0
Nodes (0): 

### Community 46 - "Shared Schemas Init"
Cohesion: 1.0
Nodes (0): 

### Community 47 - "Shared Config Settings"
Cohesion: 1.0
Nodes (0): 

### Community 48 - "Shared Test Conftest"
Cohesion: 1.0
Nodes (0): 

### Community 49 - "Voice Init"
Cohesion: 1.0
Nodes (0): 

### Community 50 - "Voice API Init"
Cohesion: 1.0
Nodes (0): 

### Community 51 - "Voice Core Init"
Cohesion: 1.0
Nodes (0): 

### Community 52 - "Voice Models Init"
Cohesion: 1.0
Nodes (0): 

### Community 53 - "Voice Services Init"
Cohesion: 1.0
Nodes (0): 

### Community 54 - "Voice Repos Init"
Cohesion: 1.0
Nodes (0): 

### Community 55 - "Voice Prompts Init"
Cohesion: 1.0
Nodes (0): 

### Community 56 - "Voice Utils Init"
Cohesion: 1.0
Nodes (0): 

### Community 57 - "OCR Init"
Cohesion: 1.0
Nodes (0): 

### Community 58 - "OCR API Init"
Cohesion: 1.0
Nodes (0): 

### Community 59 - "OCR Core Init"
Cohesion: 1.0
Nodes (0): 

### Community 60 - "OCR Models Init"
Cohesion: 1.0
Nodes (0): 

### Community 61 - "OCR Service Init"
Cohesion: 1.0
Nodes (0): 

### Community 62 - "Alembic Migrations"
Cohesion: 1.0
Nodes (0): 

### Community 63 - "Seed Dev Data"
Cohesion: 1.0
Nodes (0): 

### Community 64 - "Session End Tests"
Cohesion: 1.0
Nodes (0): 

### Community 65 - "Sprint 0 Plan"
Cohesion: 1.0
Nodes (1): Python + FastAPI Framework Decision

### Community 66 - "Voice Onboarding Timeline"
Cohesion: 1.0
Nodes (1): PII Filter for Observability

### Community 67 - "Git Commands Reference"
Cohesion: 1.0
Nodes (1): Cloud Run Deployment Decision (v2)

### Community 68 - "Client Questions"
Cohesion: 1.0
Nodes (1): System Design v2 Revised (plan_v2.md)

### Community 69 - "Remaining Questions"
Cohesion: 1.0
Nodes (1): Database Schema Needed from Client

### Community 70 - "Plan V1"
Cohesion: 1.0
Nodes (1): AWS Account Access Question

### Community 71 - "Plan V2 Revised"
Cohesion: 1.0
Nodes (1): Decision A.1: Cloud Provider (Open)

### Community 72 - "Requirements File"
Cohesion: 1.0
Nodes (1): Decision A.2: Deployment Model (Open)

### Community 73 - "README Overview"
Cohesion: 1.0
Nodes (1): Git Workflow Master Guide

### Community 74 - "GEMINI Config"
Cohesion: 1.0
Nodes (1): Root requirements.txt Dependencies

## Knowledge Gaps
- **75 isolated node(s):** `In Phase 2, this node will call Gemini Multimodal to extract fields     from th`, `Deterministic routing: checks FormState against required fields.     If missing`, `Fetches the current session state, applies frontend overrides,     invokes the`, `Helper endpoint to verify the full FormState directly out of Redis.`, `Generates a secure LiveKit JWT so the frontend can connect to the voice room.` (+70 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Voice Repository`** (2 nodes): `configure_logging()`, `logging.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Redis State Service`** (2 nodes): `build_user_prompt()`, `dictation_prompt.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `LiveKit Service`** (2 nodes): `build_personal_details_user_prompt()`, `personal_details_prompt.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Transcription Service`** (2 nodes): `generate_livekit_access()`, `livekit_service.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Personal Details Service`** (2 nodes): `build_idempotency_key()`, `idempotency.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Dictation Prompt Template`** (2 nodes): `test_session_end.py`, `test_end_session_not_found()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Personal Details Prompt`** (2 nodes): `Authentication Modes (dev_header / jwt)`, `Gap P1-G1: JWT Validation Middleware Missing`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Idempotency Utils`** (2 nodes): `Cost Governor / Zombie Session Protection`, `Cost Guard (Token Caps + Retries)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Logging Config`** (2 nodes): `Extras plan.md (Original Design v1)`, `System Design v1 (Hierarchical Multi-Agent)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `OCR Service Scaffold`** (1 nodes): `env.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `OCR Routes & Config`** (1 nodes): `seed_dev_data.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `OCR Tests`** (1 nodes): `main.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Shared DB Base`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Shared DB Session`** (1 nodes): `routes.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Shared Error Middleware`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Shared Request ID Middleware`** (1 nodes): `config.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Shared Tenant Middleware`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Shared Error Schemas`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Shared Response Schemas`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Shared Tenant Tests`** (1 nodes): `conftest.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Shared Common Init`** (1 nodes): `test_routes.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Shared Auth Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Shared Config Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Shared DB Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Shared Middleware Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Shared Schemas Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Shared Config Settings`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Shared Test Conftest`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Voice Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Voice API Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Voice Core Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Voice Models Init`** (1 nodes): `settings.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Voice Services Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Voice Repos Init`** (1 nodes): `base.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Voice Prompts Init`** (1 nodes): `session.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Voice Utils Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `OCR Init`** (1 nodes): `error_handler.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `OCR API Init`** (1 nodes): `request_id.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `OCR Core Init`** (1 nodes): `tenant_context.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `OCR Models Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `OCR Service Init`** (1 nodes): `errors.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Alembic Migrations`** (1 nodes): `responses.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Seed Dev Data`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Session End Tests`** (1 nodes): `conftest.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Sprint 0 Plan`** (1 nodes): `Python + FastAPI Framework Decision`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Voice Onboarding Timeline`** (1 nodes): `PII Filter for Observability`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Git Commands Reference`** (1 nodes): `Cloud Run Deployment Decision (v2)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Client Questions`** (1 nodes): `System Design v2 Revised (plan_v2.md)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Remaining Questions`** (1 nodes): `Database Schema Needed from Client`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Plan V1`** (1 nodes): `AWS Account Access Question`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Plan V2 Revised`** (1 nodes): `Decision A.1: Cloud Provider (Open)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Requirements File`** (1 nodes): `Decision A.2: Deployment Model (Open)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `README Overview`** (1 nodes): `Git Workflow Master Guide`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `GEMINI Config`** (1 nodes): `Root requirements.txt Dependencies`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `SENA Platform Overview` connect `Platform Constraints & Decisions` to `Observability & External Services`?**
  _High betweenness centrality (0.045) - this node is a cross-community bridge._
- **Why does `Sprint 0 Plan` connect `Platform Constraints & Decisions` to `Sprint Gates & Gap Tracking`?**
  _High betweenness centrality (0.042) - this node is a cross-community bridge._
- **Why does `Merged Sprint 0 + Voice Execution Plan` connect `Sprint Gates & Gap Tracking` to `Platform Constraints & Decisions`?**
  _High betweenness centrality (0.034) - this node is a cross-community bridge._
- **Are the 9 inferred relationships involving `VoiceRepository` (e.g. with `ApprovalQueueItem` and `CaseNoteDraft`) actually correct?**
  _`VoiceRepository` has 9 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `RedisService` (e.g. with `DictationService` and `PersonalDetailsService`) actually correct?**
  _`RedisService` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `PersonalDetailsService` (e.g. with `BedrockService` and `RedisService`) actually correct?**
  _`PersonalDetailsService` has 4 INFERRED edges - model-reasoned connections that need verification._
- **What connects `In Phase 2, this node will call Gemini Multimodal to extract fields     from th`, `Deterministic routing: checks FormState against required fields.     If missing`, `Fetches the current session state, applies frontend overrides,     invokes the` to the rest of the system?**
  _75 weakly-connected nodes found - possible documentation gaps or missing edges._