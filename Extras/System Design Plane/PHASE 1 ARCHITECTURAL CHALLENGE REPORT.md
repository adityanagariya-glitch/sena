
# === PHASE 1: ARCHITECTURAL CHALLENGE REPORT ===

## TOPOLOGY DECISION

**Current**: Hierarchical — Centralized API Gateway → Independent Per-Module LangGraph StateGraphs → Shared Service Layer

**Challenge**: The hierarchical topology is **defensible but carries hidden costs** that the document underplays:

1. **The API Gateway is a SPOF that the design doesn't fully acknowledge.** Section 3.3's comparison table claims hierarchical has "Yes" for failure isolation — but if the gateway (auth + rate limiter + router) goes down, ALL modules are unreachable. The document designs no gateway redundancy or bypass mechanism.

2. **The "hierarchical" label is misleading.** This is really "independent microservices behind a shared gateway" — a well-established pattern. There's no hierarchy of agents, no supervisor agent, no delegation chain. Calling it "hierarchical" overpromises complexity that doesn't exist (which is actually good). The design should acknowledge this is closer to a **federated microservice architecture with a shared gateway**, which is easier to reason about.

3. **The gateway adds latency to every request.** JWT validation + rate limiting + request routing + audit entry creation adds ~20-50ms per request. For OCR/RAG (3-5s total), this is negligible. For voice (<1s target), this is 2-5% of the budget. The voice flow diagram (Flow D, §3.4) shows voice going through the gateway — but the real-time WebRTC loop bypasses it (goes through LiveKit). The document should make explicit that **the gateway is only on session initiation, not per-turn**.

4. **Could a different topology reduce latency by 50%?** No. The bottleneck is LLM inference (300-400ms per call), not routing topology. The topology choice is not the latency constraint.

**Recommendation**: **Keep the topology. Rename it to "Federated Microservices with Shared Gateway" for clarity.** Add explicit gateway HA requirements (minimum 2 instances, health-check-based failover). Document that voice bypasses the gateway for per-turn communication.

---

## AGENT ANALYSIS

**Total agents: 8 LLM agents + 10 deterministic components**

This is a **well-right-sized design** — but there are 3 specific challenges:

### Agent 1: Document Extractor — **KEEP, but challenge the LLM usage**
The document claims LLM vision is needed for "damaged/non-standard layouts, handwriting, and NDIS registration forms with variable structure." But:
- Google Document AI's Form Parser already handles variable-structure forms
- The hybrid approach (Cloud OCR primary + LLM fallback) is correct, but the fallback trigger isn't well-defined: "confidence threshold" is mentioned but no threshold value is specified
- **Gap**: What happens when BOTH Cloud OCR and LLM Vision produce low-confidence results? The design has no "abort and request manual entry" path
- **Recommendation**: Keep. Add explicit confidence thresholds (e.g., Cloud OCR < 0.7 → try LLM; LLM < 0.6 → request manual entry). Add the "manual entry" terminal state to the StateGraph.

### Agent 2: Policy Synthesizer — **KEEP**
Correctly identified as needing LLM for cross-chunk reasoning. No challenge.

### Agent 3: Conversational Agent — **KEEP, but this is actually 2 agents**
The document lists ONE Conversational Agent serving both Voice Onboarding (M1) and Case Note Drafting (M2). These have **fundamentally different objectives**:
- Onboarding: structured form filling with known fields, constrained output
- Case Note: free-form dictation with clinical structure detection, open-ended output
Using one agent with shared system prompts increases prompt complexity and error surface.
- **Recommendation**: Split into `OnboardingAgent` and `DictationAgent`. They share the voice infrastructure (LiveKit, Redis session) but have separate system prompts and output schemas. This makes each agent easier to test, evaluate, and optimize independently.

### Agent 4: Clinical Reviewer — **CHALLENGE: Could this be merge with Risk Classifier?**
Clinical Reviewer (M3) checks case note completeness. Risk Classifier (M6) analyzes the same case note for NDIS risk categories. Both:
- Take a case note as input
- Reference NDIS rules via RAG
- Produce structured assessments

Merging them into a single "Case Note Analyzer" agent (one LLM call with a combined prompt) would:
- Cut one LLM call per case note (~300ms latency, ~$0.0003/call)
- Reduce prompt engineering surface area
- But: makes evaluation harder (can't measure completeness vs. risk accuracy independently)

**Recommendation**: **Keep separate for now** — independent evaluation is more valuable than the marginal cost saving at MVP scale. Consider merging post-MVP if both agents consistently use the same context chunks.

### Agent 5: Risk Classifier — **KEEP**
Correct: NDIS risk classification requires nuanced reasoning. No deterministic rule engine can capture "restrictive practice" detection from natural language.

### Agent 6: Report Synthesizer — **KEEP, but flag the long-context risk**
The design proposes using Gemini Pro's 128K context window to fit an entire reporting period in one call. At ~100K tokens input + 5K system:
- This is a $0.125 per report call (expensive at scale)
- A single lost/corrupt response means regenerating the entire report
- **Recommendation**: Consider a map-reduce approach: synthesize each section independently (parallel Gemini Flash calls at ~$0.001 each), then merge sections deterministically. Cheaper, more reliable, parallelizable.

### Agent 7: Sentiment Analyzer — **CHALLENGE: Could this be a fine-tuned classifier?**
The document argues off-the-shelf sentiment models don't work for disability care communications. True. But:
- A fine-tuned BERT classifier on NDIS communication data would be: faster (<50ms vs ~500ms), cheaper ($0 per inference vs ~$0.0002), deterministic (reproducible), and easier to evaluate
- The argument "domain-specific reasoning required" doesn't mean it needs to be generative — classification is sufficient
- **Recommendation**: **Start with LLM (Gemini Flash) for MVP** to avoid the cold-start problem of needing labeled training data. Collect approved/rejected flags from the approval queue as training data. Migrate to a fine-tuned classifier when you have 1,000+ labeled examples. Add this to the technical roadmap.

### Agent 8: Health Risk Detector — **KEEP**
Cross-referencing medication + case notes + behavioral patterns genuinely requires reasoning over variable combinations. Cannot be deterministic.

### Summary Table

| Agent | Verdict | Change |
|---|---|---|
| Document Extractor | Keep | Add "manual entry" abort path, define confidence thresholds |
| Policy Synthesizer | Keep | No change |
| Conversational Agent | **Split** | Separate into `OnboardingAgent` + `DictationAgent` |
| Clinical Reviewer | Keep (for now) | Consider merging with Risk Classifier post-MVP |
| Risk Classifier | Keep | No change |
| Report Synthesizer | Keep | Consider map-reduce instead of single long-context call |
| Sentiment Analyzer | Keep (for now) | Plan migration to fine-tuned classifier with training data from approval queue |
| Health Risk Detector | Keep | No change |

**Revised agent count: 9 LLM agents** (after Conversational Agent split) + 10 deterministic components.

---

## COMMUNICATION BOTTLENECKS

### Bottleneck 1: Sequential RAG Pipeline
**Current path** (§3.4 Flow B): `embed_query → hybrid_search → rerank → synthesize → format → audit`
- `embed_query` (~100ms) must complete before `hybrid_search` (depends on embedding)
- `hybrid_search` runs vector + BM25 — **these two are independent and should be parallel** but the design doesn't specify parallelism
- `rerank` (~300ms) is marked as "optional, deferred" — good
- `synthesize` (~1-2s) is the real bottleneck — unavoidable LLM call

**Impact**: ~500ms wasted if vector search + BM25 run sequentially instead of in parallel  
**Fix**: In the LangGraph implementation, use `asyncio.gather()` within the `hybrid_search` node to run vector and BM25 queries concurrently. Document this as a mandatory implementation detail.

### Bottleneck 2: Case Note → Risk Flagging Async Chain
**Current path**: Case Note Graph → Pub/Sub `case_note.submitted` → Risk Flagging Graph → Approval Queue
- The hop from Case Note to Risk Flagging is async (Pub/Sub), but the Risk Flagging graph itself does `retrieve_ndis_rules → classify_risks → generate_justification → route_escalation`
- `retrieve_ndis_rules` requires RAG retrieval (~500ms)
- `classify_risks` + `generate_justification` are sequential LLM calls (~600ms total)
- **These two LLM calls could potentially be one**: classify risks AND generate justification in a single prompt with structured output
  
**Impact**: ~300ms per case note, ~600s/day at 2,000 case notes/day  
**Fix**: Combine `classify_risks` + `generate_justification` into a single LLM call with a structured output schema that includes both classification and justification. This is the single most impactful latency optimization in the async pipeline.

### Bottleneck 3: Voice Turn — STT + Reasoning as Separate Steps
**Current path** (§3.4 Flow D): `VAD → transport → STT → reasoning → form update → response gen → TTS → transport`
- The document already identifies the optimization: "Pipeline STT + reasoning into single Gemini multimodal call"
- But the StateGraph definition in Appendix A.4 still has separate `current_transcript` field (implying STT happens separately)

**Impact**: ~200-300ms if STT and reasoning are separate vs. combined  
**Fix**: The design document and the state definition are inconsistent. Align them: the state should have `audio_input: bytes` instead of `current_transcript: str` if using Gemini multimodal natively.

### Bottleneck 4: Audit Logging as a Synchronous Node
Every graph has `audit` as a sequential node before `END`. For synchronous paths (OCR, RAG), this adds latency.

**Impact**: ~10-50ms per request (DB write)  
**Fix**: Make audit logging fire-and-forget (async background task, not a graph node). The audit write should not be on the critical response path. Log to Redis first (sub-ms), flush to PostgreSQL in background. If Redis audit log is lost, the response was already delivered — the audit gap is acceptable for a brief window.

---

## THEORETICAL MINIMUM vs. CURRENT LATENCY

| Path | Current Design (ms) | Theoretical Minimum (ms) | Gap | Root Cause |
|---|---|---|---|---|
| Voice turn | 1,100 | 600 | 500 | Separate STT, synchronous audit, sequential TTS |
| OCR (standard) | 2,500 | 1,800 | 700 | Synchronous audit, sequential post-processing |
| RAG query | 3,500 | 2,200 | 1,300 | Sequential vector + BM25, synchronous audit |
| Risk flagging | 2,000 | 1,200 | 800 | Separate classify + justify LLM calls |

---

## ADDITIONAL ARCHITECTURAL GAPS IDENTIFIED

1. **No API versioning strategy.** All endpoints are `/v1/...` but there's no plan for what happens when `/v2/` is needed. With no API contracts with the platform team, breaking changes would be catastrophic.

2. **No rate limiting specifics.** The gateway mentions "per-tenant rate limiter" but doesn't define limits. Voice sessions are long-running — does rate limiting apply per-request or per-session? A tenant with 50 concurrent voice sessions could exhaust LLM quotas.

3. **No graceful shutdown protocol.** What happens to in-progress LangGraph executions (especially voice sessions) during deployment? The design needs a drain-then-shutdown protocol.

4. **LangGraph version pinning risk.** Section 12 acknowledges this (R7) but the mitigation ("abstract graph construction behind factory functions") is vague. The real risk is that LangGraph's checkpoint serialization format could change, breaking paused HITL workflows mid-approval.

5. **No data migration strategy.** When pgvector eventually can't handle scale and you migrate to Qdrant (§9.4), how do you migrate active embeddings without downtime? This needs at minimum a documented migration sketch.

---

Type **'continue'** for Phase 2: Memory & State Deep Dive.