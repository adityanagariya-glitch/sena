
# === PHASE 3: COST & LATENCY MODEL ===

## CURRENT COST BREAKDOWN — CHALLENGE & CORRECTION

The design's §9.2 cost model has **three math errors and two missing categories** that significantly undercount costs.

### Error 1: Gemini Flash Token Math Is Wrong

The document claims:
> ~600K calls/mo × ~2K tokens avg × $0.075/1M input + $0.30/1M output = **~$450**

Let's verify:
- 600K calls × 2K tokens = 1.2B tokens/month
- Assume 70% input, 30% output (typical for classification/extraction tasks)
- Input: 840M tokens × $0.075/1M = **$63**
- Output: 360M tokens × $0.30/1M = **$108**
- **Actual total: ~$171**, not $450

The $450 figure is either based on different assumptions (not documented) or simply wrong. Either way, the cost is **lower than claimed**, which is good news — but the methodology must be traceable.

### Error 2: Gemini Pro Token Math Is Also Wrong

The document claims:
> ~8K calls/mo × ~5K tokens avg × $1.25/1M input + $5.00/1M output = **~$250**

Verification:
- 8K calls × 5K tokens = 40M tokens/month
- Assume 80% input (RAG chunks are large), 20% output
- Input: 32M tokens × $1.25/1M = **$40**
- Output: 8M tokens × $5.00/1M = **$40**
- **Actual total: ~$80**, not $250

Again, overstated by ~3x. The document is either using different (undocumented) token assumptions or inflating to build safety margin. Safety margins are fine, but they should be explicit: "We estimate $80 with a 3x safety factor = $240."

### Error 3: Call Volume Assumptions Don't Add Up

The document states: 50 orgs, 500 support workers, 2,000 shifts/day, 200 RAG queries/day, 100 voice sessions/day (10 turns each).

Let's trace the 600K Gemini Flash calls/month:
- Voice: 100 sessions/day × 10 turns × 30 days = **30K calls/month** (STT + response per turn = 60K if counted as 2 calls)
- Risk flagging: 2,000 case notes/day × 30 days = **60K calls/month**
- Clinical review: 2,000 × 30 = **60K calls/month**
- Sentiment analysis: Weekly batch, maybe 10K/month
- **Total traceable: ~190K calls/month**

Where are the remaining 410K calls to reach 600K? Not explained. The volume estimate appears inflated, or there are implicit calls (context summarization, retries, fallback chains) that should be itemized.

### Missing Cost Categories

1. **Network egress**: The document budgets ~$50 for networking, but voice sessions via LiveKit involve substantial audio data. 100 sessions/day × 10 turns × ~50KB audio per turn × 2 directions × 30 days = ~3GB/month. GCP egress is $0.12/GB for first 1TB, so this is negligible (~$0.36). The $50 estimate is actually reasonable here — dominated by inter-region API calls.

2. **LLM Gateway abstraction overhead**: The design proposes an LLM Gateway shared service that adds a hop between modules and Vertex AI. This adds 5-15ms per call but more importantly, if it's a separate service (not a library), it adds a Kubernetes pod and inter-service network cost. The design should clarify: is the LLM Gateway a **library** (imported by each service) or a **microservice** (separate deployment)? For a 2-person team, it should be a library.

3. **Missing: Vertex AI provisioned throughput baseline cost.** If you enable provisioned throughput (§9.3), there's a minimum commitment. At current volumes, pay-per-call is cheaper. But the design should note the crossover point.

### Corrected Cost Model

**Per Request Costs (at scale assumptions):**

| Request Type | LLM Calls | Avg Tokens (in/out) | LLM Cost | Infra Cost | Total |
|---|---|---|---|---|---|
| **OCR (standard)** | 0 LLM (Document AI only) | N/A | $0.00 | $0.01 (Document AI) | **$0.01** |
| **OCR (LLM fallback)** | 1 Gemini Flash | 1.5K / 0.5K | $0.0003 | $0.01 | **$0.01** |
| **RAG query** | 1 embedding + 1 Gemini Pro | 500 embed + 4K/1K synth | $0.01 | ~$0.001 | **$0.01** |
| **Voice turn** | 1 Gemini Flash (multimodal) | 2K / 0.5K | $0.0003 | ~$0.001 | **$0.001** |
| **Voice session (10 turns)** | 10 Gemini Flash | 20K total / 5K total | $0.003 | ~$0.01 | **$0.013** |
| **Case note review** | 1 Gemini Flash | 3K / 1K | $0.0005 | ~$0.001 | **$0.002** |
| **Risk flagging** | 1 RAG retrieval + 1 Gemini Flash | 4K / 1K | $0.0006 | ~$0.001 | **$0.002** |
| **Report generation** | 1 Gemini Pro (long context) | 50K / 5K | $0.088 | ~$0.01 | **$0.10** |

### Corrected Monthly Projections

| Scale | Daily Volume | LLM Cost/mo | Infra Cost/mo | **Total/mo** |
|---|---|---|---|---|
| **MVP (5-10 orgs)** | 200 shifts, 20 RAG, 10 voice, 2 reports/wk | ~$25 | ~$400 | **~$425** |
| **Growth (50 orgs)** | 2K shifts, 200 RAG, 100 voice, 20 reports/wk | ~$180 | ~$550 | **~$730** |
| **Scale (200 orgs)** | 8K shifts, 800 RAG, 400 voice, 80 reports/wk | ~$700 | ~$900 | **~$1,600** |
| **High scale (500 orgs)** | 20K shifts, 2K RAG, 1K voice, 200 reports/wk | ~$2,200 | ~$1,500 | **~$3,700** |

**Key insight**: The design's original $1,600/month at 50 orgs was overestimating LLM costs and underestimating them at higher scale. The actual cost curve is:
- **Infrastructure dominates at MVP** (~94% of cost is Cloud SQL + GKE + Redis)
- **LLM costs dominate at high scale** (~60% of cost at 500 orgs)
- Crossover point: ~200 orgs

This means cost optimization should focus on **infrastructure right-sizing at MVP** and **LLM call optimization at scale**.

---

## CURRENT LATENCY — DEEP DECOMPOSITION

### Critical Path A: Voice Turn (target <1,000ms)

```
Step                          Current    Optimized   Notes
─────────────────────────────────────────────────────────────
VAD detection                  100ms      100ms      LiveKit client-side, not optimizable
Network: mobile → LiveKit       50ms       50ms      Physics (speed of light + mobile latency)
LiveKit → Agent Pod             10ms       10ms      In-cluster networking
Gemini multimodal (audio in)     —        500ms      ★ COMBINED: STT + reasoning + response
  ├─ STT (if separate)        200ms        —         Eliminated by multimodal
  ├─ Reasoning                200ms        —         Merged into multimodal call
  └─ Response generation      300ms        —         Merged into multimodal call
Redis form state update          5ms        5ms      Sub-millisecond in practice
TTS synthesis                  200ms      150ms      Use Gemini native TTS (skip separate API)
Network: LiveKit → mobile       50ms       50ms      Physics
Audit log (async)                0ms        0ms      Background, non-blocking
─────────────────────────────────────────────────────────────
TOTAL                        1,115ms      865ms      22% improvement
```

**Verdict**: The optimized path of ~865ms **meets the <1,000ms target** with ~135ms headroom. But this assumes Gemini multimodal responds in 500ms — this is an **untested assumption**. Gemini multimodal audio processing latency in the `australia-southeast1` region needs empirical measurement before committing to this SLA.

**Risk**: If Gemini multimodal actually takes 700ms (plausible for AU region due to fewer model replicas), the total becomes 1,065ms — over target. The fallback should be documented: "If voice P95 > 1,000ms, degrade to turn-based interaction (no real-time streaming) with explicit user feedback ('Processing...')."

### Critical Path B: RAG Query (target <5,000ms)

```
Step                          Current    Optimized   Notes
─────────────────────────────────────────────────────────────
Gateway (JWT + route + audit)    30ms       30ms      Fixed overhead
Query embedding                 120ms      120ms      Single API call, not optimizable
Vector search (pgvector)         50ms    ┐              
BM25 search (ts_rank_cd)        30ms    ├─  50ms     ★ PARALLELIZE: asyncio.gather()
                                        ┘              (wall clock = max of the two)
RRF fusion (in-memory)            2ms        2ms      Pure Python, negligible
Reranking (deferred)              0ms        0ms      Not enabled at MVP
LLM synthesis (Gemini Pro)     2,000ms    2,000ms    Dominant bottleneck, unavoidable
Citation verification             10ms       10ms     Substring matching, fast
Format response                    5ms        5ms     Serialization
Audit log (async)                  0ms        0ms     Background
─────────────────────────────────────────────────────────────
TOTAL                          2,247ms    2,217ms    1% improvement (barely worth it)
```

**Verdict**: RAG latency is **entirely dominated by the Gemini Pro synthesis call** (~89% of total latency). Parallelizing vector + BM25 saves only ~30ms. The real optimization opportunities are:

1. **Switch RAG synthesis to Gemini Flash**: ~500ms instead of 2,000ms. Saves 1,500ms (67% reduction). Tests needed to validate Flash maintains sufficient answer quality for policy questions.

2. **Streaming response**: Instead of waiting for the full Gemini response, stream tokens as they generate. User sees first tokens at ~200ms. Total perceived latency drops from 2,200ms to ~200ms time-to-first-token. **This is the single most impactful UX optimization for RAG** and the design doesn't mention it.

3. **RAG cache hit**: If query matches cache (Redis, 5-min TTL per tenant), skip everything except gateway → cache → respond. Latency: ~35ms. At scale, common policy questions like "What are the reporting requirements for restrictive practices?" will have high cache hit rates.

### Critical Path C: OCR Standard (target <3,000ms)

```
Step                          Current    Optimized   Notes
─────────────────────────────────────────────────────────────
Gateway                          30ms       30ms      
Image validation                 20ms       20ms      File type, size, dimensions
GCS upload (tenant-scoped)      200ms      200ms      Network to GCS
Document AI API call          1,500ms    1,500ms      Dominant cost, not optimizable
Post-processing                  50ms       50ms      Field normalization
Confidence scoring               10ms       10ms      Arithmetic
Audit log                         0ms        0ms      Async
Response formatting               5ms        5ms      
─────────────────────────────────────────────────────────────
TOTAL                          1,815ms    1,815ms     Already well under 3,000ms target
```

**Verdict**: OCR standard path is **well within SLA (1.8s vs 3.0s target)**. No optimization needed. The 3,000ms SLA has 40% headroom.

**Challenge**: Why does the design claim ~2,500ms for OCR standard (§9.1) when the component breakdown sums to ~1,815ms? Either the estimates are padded (fair — include network variability) or there's an unaccounted step. The design should reconcile these numbers.

### Critical Path D: Case Note → Risk Flagging Chain (target <30s batch)

```
Step                          Current    Optimized   Notes
─────────────────────────────────────────────────────────────
Pub/Sub delivery                200ms      200ms      Message propagation
RAG retrieval (NDIS rules)      250ms    ┐
RAG retrieval (tenant policies) 250ms    ├─ 250ms    ★ PARALLELIZE
                                         ┘
Risk classification (Flash)     500ms    ┐
Justification generation        400ms    ├─ 600ms    ★ MERGE INTO SINGLE LLM CALL
                                         ┘
Escalation routing               10ms       10ms     Deterministic
Approval queue write              20ms       20ms     DB insert
Audit log                          0ms        0ms     Async
─────────────────────────────────────────────────────────────
TOTAL per note                 1,630ms    1,080ms     34% improvement
```

**Critical optimization**: Merging classify + justify into one LLM call and parallelizing the two RAG retrievals cuts ~550ms per case note. At 2,000 case notes/day, this saves ~1,100 seconds of cumulative processing time daily.

---

## OPTIMIZATION RECOMMENDATIONS — RANKED BY IMPACT

| # | Optimization | Latency Savings | Cost Savings/mo (at growth) | Effort | Priority |
|---|---|---|---|---|---|
| 1 | **Stream RAG responses** (time-to-first-token) | 2,000ms → 200ms perceived | $0 (same LLM cost) | Small (LangGraph streaming API) | **P0** |
| 2 | **Merge Risk classify + justify into single LLM call** | 900ms → 600ms per note | ~$15/mo (30K fewer Flash calls) | Small (prompt engineering) | **P0** |
| 3 | **Use Gemini Flash for RAG synthesis** (if quality sufficient) | 2,000ms → 500ms | ~$55/mo (Pro→Flash price diff) | Small + evaluation testing | **P1** |
| 4 | **Parallelize NDIS + tenant policy RAG retrieval** | 500ms → 250ms per risk flag | $0 | Small (asyncio.gather) | **P1** |
| 5 | **Parallelize vector + BM25 in hybrid search** | 80ms → 50ms per RAG query | $0 | Small (asyncio.gather) | **P2** |
| 6 | **Make audit logging async (fire-and-forget)** | 10-30ms per request | $0 | Small | **P2** |
| 7 | **Batch risk flagging** (accumulate N notes) | N/A (throughput, not latency) | ~$20/mo at scale | Medium | **P3** |
| 8 | **Report map-reduce** (parallel section synthesis) | 30-45s → 10-15s | ~$5/mo (Flash vs Pro per section) | Medium | **P3** |

### Optimization #1 Detail: Streaming RAG Responses

This is the highest-impact change not present in the design. Currently, the RAG flow is:

```
User asks question → [2.2 seconds of silence] → Full answer appears
```

With streaming:
```
User asks question → [0.2 seconds] → First words appear → Answer builds progressively
```

LangGraph supports streaming via async generators. The FastAPI endpoint would use `StreamingResponse` with `text/event-stream` content type. The platform frontend consumes via Server-Sent Events (SSE).

**Implementation sketch:**
```python
@router.post("/v1/rag/query")
async def rag_query(request: RAGQueryRequest) -> StreamingResponse:
    async def stream_response():
        async for chunk in rag_graph.astream(state):
            if "answer_chunk" in chunk:
                yield f"data: {json.dumps(chunk)}\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(stream_response(), media_type="text/event-stream")
```

This requires the platform frontend team to support SSE. **Add this to the API contract discussion with Nishant/Jill.**

---

## COST SENSITIVITY ANALYSIS

### What If We're Wrong About Volumes?

| Scenario | Monthly LLM Cost | Monthly Infra | Total |
|---|---|---|---|
| **Base case** (50 orgs, 2K shifts/day) | $180 | $550 | $730 |
| **2x shifts** (50 orgs, 4K shifts/day) | $290 | $550 | $840 (+15%) |
| **Heavy RAG** (1,000 queries/day) | $320 | $550 | $870 (+19%) |
| **Voice-heavy** (500 sessions/day) | $195 | $700 | $895 (+23%) |
| **All 2x** (everything doubles) | $360 | $700 | $1,060 (+45%) |

**Insight**: Even at 2x all volumes, the monthly cost only reaches ~$1,060. The system is **remarkably cost-efficient** because:
1. Gemini Flash is cheap ($0.075/1M input)
2. pgvector eliminates dedicated vector DB cost
3. Embedding costs are negligible

The biggest cost risk is **not volume but model switching**: if Gemini quality proves insufficient and you switch to Azure OpenAI GPT-4o, LLM costs increase ~15-30x. At 50 orgs:
- Gemini Flash: ~$180/mo for LLM
- Azure OpenAI GPT-4o (equivalent volume): ~$3,200/mo for LLM

**Recommendation**: Lock in the Gemini quality evaluation EARLY (Sprint 1). If Gemini fails quality benchmarks for RAG synthesis, the cost model changes fundamentally.

### Cost Per Tenant

| Scale | Total Monthly Cost | Cost Per Tenant | Cost Per Support Worker |
|---|---|---|---|
| MVP (5 orgs) | ~$425 | **$85/tenant** | ~$42/worker |
| Growth (50 orgs) | ~$730 | **$14.60/tenant** | ~$1.46/worker |
| Scale (200 orgs) | ~$1,600 | **$8/tenant** | ~$0.40/worker |

At growth scale, the AI backend costs ~$14.60/tenant/month. Depending on the SaaS subscription pricing, this is likely <5% of revenue per tenant — very healthy unit economics.

---

## MISSING FROM THE DESIGN: COST GUARDRAILS

The current design has **no cost protection mechanisms**. One misconfigured loop or a prompt injection causing repeated LLM calls could generate unbounded costs.

### Mandatory Cost Guardrails:

1. **Per-tenant daily token cap**: Set a maximum daily token budget per tenant (e.g., 500K tokens/day for Flash, 100K tokens/day for Pro). If exceeded, module returns "Daily AI limit reached, please contact administrator." Logged as a P2 alert.

2. **Per-request token ceiling**: No single LLM call should exceed a defined token limit. For Flash calls that should use ~2K tokens, set `max_tokens=4096` as a hard cap. For Pro (reports), set `max_tokens=16384`.

3. **Monthly cost monitoring with auto-alert**: If projected monthly LLM cost exceeds 150% of the budget baseline, fire a P1 alert. If it exceeds 200%, consider automatic throttling (queue requests instead of real-time processing).

4. **Retry budget per request**: Maximum 2 LLM retries (3 total attempts). After 3 failures, return an error — don't keep retrying. The circuit breaker handles this at the service level, but **the per-request retry budget should also be enforced in the LangGraph graph** (via state counter, not just circuit breaker).

---

## LATENCY SLA REALITY CHECK

| Path | Design's Target SLA | My Assessment | Achievable? |
|---|---|---|---|
| Voice turn | <1,000ms | ~865ms with multimodal optimization | **Maybe** — depends on Gemini AU region latency (untested) |
| OCR standard | <3,000ms | ~1,815ms | **Yes** — 40% headroom |
| OCR LLM fallback | <5,000ms | ~3,500ms | **Yes** — 30% headroom |
| RAG query | <5,000ms | ~2,200ms (full) / ~200ms TTFT (streaming) | **Yes** — comfortably |
| Risk flagging | <30s batch | ~1,080ms per note (optimized) | **Yes** — can process ~27 notes within 30s |
| Report generation | <60s | ~30-45s | **Yes** — but at the edge. Map-reduce brings to ~10-15s. |
| Case note review | <5,000ms | ~2,500ms | **Yes** — 50% headroom |

**Overall assessment**: All SLAs are achievable except voice, which is tight and depends on an untested assumption about Gemini multimodal latency in the AU region. The design should add a **contingency plan**: if voice P95 > 1,000ms, switch to a "processing indicator" UX pattern rather than promising real-time.

---

Type **'continue'** for Phase 4: Failure Mode Analysis (FMEA).