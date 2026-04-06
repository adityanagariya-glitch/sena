
# === PHASE 2: MEMORY & STATE DEEP DIVE ===

## VECTOR DB DECISION

**Chosen**: pgvector (HNSW) running in PostgreSQL 16 on Cloud SQL

### Challenge: Is pgvector TRULY the right choice?

**The Good — pgvector is defensible for this project:**
- Unified RLS enforcement: setup_rls.sql shows `document_chunks` already has tenant isolation with SYSTEM tenant whitelist. This is a massive simplification — you don't have to build a separate ACL layer for a dedicated vector DB.
- Zero additional infrastructure for a 2-person team
- The HNSW index algorithm (since pgvector 0.5.0) is production-quality for <5M vectors

**The Bad — the document glosses over real limitations:**

1. **HNSW index build time is brutal at scale.** The design cites "handles ~5M vectors" but doesn't mention: building an HNSW index on 5M 768-dim vectors takes **~45 minutes** on a db-custom-4-16384 instance, and during index build, **all insert operations block** (or use significant resources if building concurrently). For a platform that ingests new documents daily across 50+ tenants, this is a real operational concern.

2. **pgvector does NOT support filtered vector search natively with HNSW.** When you add a `WHERE tenant_id = :id` clause to a vector similarity query, PostgreSQL may choose a sequential scan instead of the HNSW index, especially when few rows match the filter. This is the #1 performance pitfall of pgvector. The document's confidence that RLS "just works" with vector search is technically true (correct isolation) but potentially false (terrible performance).

   **Concrete risk**: Tenant with 200 documents gets a vector search. pgvector's HNSW index scans ALL vectors, then PostgreSQL filters by `tenant_id` post-hoc. At 5M total vectors, this means scanning 5M vectors to return 200. At 10M+, this becomes untenable.

   **Fix**: Use **partitioned tables** by `tenant_id` (one HNSW index per partition), or use pgvector's built-in metadata filtering via partial indexes: `CREATE INDEX ON document_chunks USING hnsw (embedding vector_cosine_ops) WHERE tenant_id = :specific_tenant`. This requires index-per-tenant management, which is operational overhead the design doesn't account for.

3. **No backup granularity for vectors.** Cloud SQL backup is all-or-nothing. You can't snapshot just the vector data for migration testing. If you need to test a Qdrant migration, you have to export vectors via custom code.

4. **Missing: Distance metric choice.** The design says "HNSW index" but never specifies the distance operator. pgvector supports `vector_cosine_ops`, `vector_l2_ops`, and `vector_ip_ops`. For Vertex AI's `text-embedding-004`, **cosine similarity** (`vector_cosine_ops`) is correct (embeddings are normalized). This should be explicitly documented — using the wrong metric silently degrades retrieval quality with no error.

### Cost Analysis

| Scale | Vector Count | Cloud SQL Instance | Monthly Cost | Query Latency (p95) |
|---|---|---|---|---|
| MVP (5-10 orgs) | ~50K vectors | db-custom-2-8192 | ~$180/mo | <50ms |
| Growth (50 orgs) | ~500K vectors | db-custom-4-16384 | ~$350/mo | <100ms |
| Scale (200 orgs) | ~2M vectors | db-custom-8-32768 | ~$700/mo | <200ms |
| Limit (500 orgs) | ~5M vectors | db-custom-16-65536 | ~$1,400/mo | <500ms (with filter degradation) |
| **Upgrade trigger** | >5M vectors | Migrate to Qdrant | ~$1,400 + $200 Qdrant | <50ms (dedicated ANN) |

### Disaster Recovery

**Gap**: The design mentions no vector-specific DR strategy. Cloud SQL automated backups cover the base case, but:
- **Point-in-time recovery**: Cloud SQL supports it (binary log replay), so vector data recovery to any point in the last 7 days is covered.
- **Cross-region failover**: Cloud SQL HA covers this IF the cross-region replica is configured. The design doesn't specify if HA is enabled.
- **Embedding model version change**: If you upgrade from `text-embedding-004` to a future model, ALL existing vectors become incompatible. The document has **zero migration strategy** for this. You'd need to re-embed every document — at 500K documents × $0.025/1M tokens ≈ $6.25, it's cheap but operationally complex (background job, validate, swap indexes).

**Recommendation**: **Keep pgvector.** Add these mandatory implementation details:
1. Explicitly use `vector_cosine_ops` distance metric
2. Add partial HNSW indexes per large tenant (>10K vectors) or use table partitioning
3. Document the embedding re-indexing procedure for model version changes
4. Enable Cloud SQL HA for the production instance

---

## EMBEDDING STRATEGY

**Model**: Vertex AI `text-embedding-004` (768 dimensions)

### Challenge: Is This the Right Embedding Model?

**The Good:**
- AU data residency via Vertex AI's `australia-southeast1` region — hard legal requirement satisfied
- 768 dimensions is a good balance: lower storage cost than OpenAI's 3072, higher quality than 384-dim models
- $0.025/1M tokens is very cheap — embedding cost is negligible

**The Concerns:**

1. **Quality gap vs. best-in-class is real.** On MTEB (Massive Text Embedding Benchmark), `text-embedding-004` scores ~63-65% on retrieval tasks. OpenAI's `text-embedding-3-large` scores ~68-70%. For NDIS policy documents with precise regulatory language, this 5-7% quality gap could mean the difference between retrieving "Practice Standard 4.3.2 Restrictive Practices" vs. a tangentially related section. The hybrid search (BM25) mitigates this for exact-match queries, but for semantic queries, the embedding quality IS the retrieval quality.

2. **No fallback tested.** The design lists BGE-large-en (self-hosted) as fallback. But:
   - BGE-large produces 1024-dim vectors; `text-embedding-004` produces 768-dim
   - These are **incompatible** — you can't mix them in the same pgvector index
   - The fallback would require a separate column and index, or re-embedding everything
   - **Practical fallback**: If the Vertex AI embedding API is down, hybrid search degrades to BM25-only (keyword). This is the REAL fallback, and it should be documented as such.

3. **Embedding batch optimization not specified.** When ingesting a new NDIS policy document with 200 chunks, are embeddings generated one-by-one (200 API calls) or batched? Vertex AI supports batch embedding. The design should mandate batch embedding during ingestion with a configurable batch size (e.g., 100 chunks per API call).

### Cost at Scale

| Scale | Embeddings/Month | Token Volume | Monthly Cost |
|---|---|---|---|
| MVP | ~5K (initial docs + queries) | ~2.5M tokens | ~$0.06 |
| Growth | ~50K (daily ingestion + queries) | ~25M tokens | ~$0.63 |
| Scale | ~200K | ~100M tokens | ~$2.50 |

Embedding cost is essentially free. The bottleneck is not cost — it's latency and quality.

### Embedding Latency

- Single embedding: ~100-150ms (Vertex AI, AU region)
- Batch of 100: ~300-500ms (amortized ~3-5ms per embedding)
- This latency is on the critical path for every RAG query (must embed the query before searching)

**Recommendation**: **Keep `text-embedding-004`.** Add:
1. Mandatory batch embedding during document ingestion
2. Acknowledge BM25-only as the real fallback (not BGE-large, which is incompatible)
3. Plan an embedding quality evaluation: test top-10 retrieval accuracy on the NDIS Q&A evaluation set. If retrieval quality < 80%, consider OpenAI via Azure OpenAI in AU East (preserves data residency)

---

## RETRIEVAL OPTIMIZATION

### Current Design
- **Algorithm**: Hybrid (Vector similarity + BM25 keyword) with Reciprocal Rank Fusion
- **Top-K**: Not explicitly specified (mentioned as "top-10 post-rerank" for RAG, but no value for initial retrieval)
- **Reranking**: Deferred
- **Cache**: RAG query cache in Redis (5-min TTL, same query + same tenant)

### Deep Challenges

1. **Top-K is undefined for the initial retrieval step.** The design says "top-10 post-rerank" but what about pre-rerank? If you retrieve top-20 from vector search and top-20 from BM25, then RRF-fuse them to top-10, that's a specific design. If you retrieve top-50 and fuse to top-10, the quality is different. This parameter has a **direct impact on RAG accuracy** and must be specified.

   **Recommendation**: Initial retrieval = top-30 from each method (vector and BM25), RRF fusion to top-10, pass to LLM. Start here, tune empirically against the evaluation set.

2. **BM25 implementation details are missing.** PostgreSQL's `tsvector`/`tsquery` is not true BM25 — it's a simplified tf-idf ranking (`ts_rank` or `ts_rank_cd`). For actual BM25, you'd need:
   - A custom ranking function, or
   - An external search index (Elasticsearch/OpenSearch), or
   - A Python-side BM25 implementation (e.g., `rank_bm25` library) over pre-fetched chunks

   The design casually says "BM25 keyword search" as if it's native to Postgres. It's not. **This is a gap that will surface during implementation.**

   **Recommendation**: Start with `ts_rank_cd` (Postgres-native, good enough for MVP). If keyword retrieval quality is insufficient, add a BM25 Python-side implementation. Do NOT add Elasticsearch — that's a whole new infrastructure component for a 2-person team.

3. **RRF (Reciprocal Rank Fusion) parameters.** The constant `k` in $RRF(d) = \sum_{r \in R} \frac{1}{k + r(d)}$ is typically set to 60 (the original paper) but the design doesn't specify it. Different `k` values weight vector vs. keyword results differently. `k=60` is the standard default. Document it.

4. **Cache strategy has a subtle bug.** The cache key is "same query + same tenant within TTL." But if a tenant uploads a new policy document, the cached RAG results are stale — they don't include the new document's chunks. **Cache invalidation must be triggered on document ingestion events**, not just TTL-based.

   **Recommendation**: Cache invalidation on `document.ingested` event for the affected tenant. Simplest implementation: delete all RAG cache keys for `tenant_id` when a new document is ingested (coarse but correct).

5. **Reranking deferral is correct for MVP, but the trigger is wrong.** The design says "add if RAG accuracy < 85% on evaluation set." But:
   - Cross-encoder reranking primarily helps when initial retrieval returns noisy results (many partially-relevant chunks)
   - The right trigger is: "add if RAG accuracy < 85% AND retrieval recall is high (chunks exist in top-30) but precision is low (correct chunk not in top-3)"
   - If retrieval recall itself is low (correct chunk not in top-30), reranking won't help — you need better embeddings or better chunking

### Similarity Metric Recommendation

For `text-embedding-004` (which produces normalized vectors):
- **Use cosine similarity** (`<=>` operator in pgvector) — equivalent to dot product for normalized vectors, but more explicit
- The design never specifies this. It must be explicit to prevent someone accidentally using L2 distance.

---

## STATE EDGE CASES

### 1. Concurrent State Updates

**Scenario**: Two support workers submit case notes for the same participant at the same time. Both trigger risk flagging. Both risk flagging instances try to read and update the same participant's risk flag history.

**Current protection**: The design doesn't address this. Risk Flagging is stateless per-case-note (§6.3 says "each case note analyzed independently"), which is correct — but the downstream **risk flag aggregation** (pattern detection over time) has no concurrency control.

**Recommendation**: Risk flag writes use `INSERT` (append-only), not `UPDATE`. Pattern detection queries read historical flags with `SELECT` (no locks). This naturally handles concurrent writes via PostgreSQL's MVCC. Document this as a design constraint: risk flag history is append-only.

### 2. State Corruption: LangGraph Checkpoint in Redis

**Scenario**: Voice session pauses at HITL node. Checkpoint saved to Redis. Redis undergoes maintenance restart. Checkpoint lost. Manager approves, system tries to resume — checkpoint not found.

**Current protection**: None documented. Redis is volatile by design. TTL is 24h for form state, but Memorystore Redis doesn't guarantee persistence across restarts unless AOF (Append-Only File) persistence is enabled.

**Recommendation**: 
- Enable AOF persistence on Memorystore Redis (adds ~10% latency to writes, but prevents data loss)
- Alternatively, dual-write LangGraph checkpoints to both Redis (fast reads) and PostgreSQL (durable). Resume from PostgreSQL if Redis miss.
- At minimum: if checkpoint is missing, return explicit "Session recovery failed, please restart" instead of crashing

### 3. State Size Explosion: Voice Session

**Scenario**: Participant goes through a 45-minute onboarding session with 60+ turns. Form has 50+ fields. Each turn adds `FieldUpdate` objects. Session state in Redis grows to multi-MB.

**Current protection**: TTL (1h for voice sessions) prevents zombie sessions. But during the session:
- No documented size limit on Redis keys
- No monitoring for oversized sessions
- Memorystore basic tier has a 1GB limit; a few hundred concurrent sessions at multi-MB each could hit this

**Recommendation**: 
- Cap voice session Redis value at 512KB (more than enough for any realistic form)
- Monitor Redis memory usage; alert at 70% capacity
- Compact form state: only store current field values, not the full history of every update (history goes to audit log in PostgreSQL)

### 4. Agent Crash Mid-Update

**Scenario**: Risk Classifier agent crashes after writing risk flags to the database but before publishing the `risk.flagged` event to Pub/Sub.

**Current protection**: None explicit. This is a classic "dual write" problem.

**Recommendation**: Use the **Transactional Outbox Pattern**:
1. Within the same database transaction, write risk flags AND insert an event record into an `outbox` table
2. A background worker polls the `outbox` table and publishes to Pub/Sub
3. Mark outbox record as "published" after successful Pub/Sub delivery
4. This guarantees at-least-once event delivery without requiring distributed transactions

This pattern is well-established and critical for the case note → risk flagging → approval queue chain to be reliable.

### 5. Redis-PostgreSQL Consistency for Voice Sessions

**Scenario**: Voice session completes. Form data in Redis. The `voice.session_complete` event is published. The event handler reads form data from Redis to create an approval queue item. Between event publish and event handling, Redis evicts the key (TTL expired or OOM).

**Current protection**: Redis TTL is 1h for voice sessions, 24h for form state. If the form state TTL is on the form itself (not the session), this is mostly safe — but not guaranteed.

**Recommendation**: When a voice session completes:
1. Read form data from Redis
2. Write completed form to PostgreSQL (permanent storage) within the session completion handler
3. Publish `voice.session_complete` event with `form_data` IN the event payload (not a Redis reference)
4. Don't depend on Redis for post-session data — Redis is a working cache, not the source of truth for completed work

---

## SHORT-TERM vs. LONG-TERM MEMORY: REVIEW

### What Goes Where — Current Design Review

| Data | Current Location | Challenge |
|---|---|---|
| Voice conversation turns | Redis (short-term) | **Correct** — transient, TTL-based, fast |
| Voice form state | Redis (short-term) | **Correct for active sessions.** But completed form must flush to PostgreSQL. |
| LangGraph checkpoints | Redis | **RISK** — volatile. Must dual-write to PostgreSQL for HITL workflows that span hours/days |
| RAG query cache | Redis (5-min TTL) | **Correct** — but needs cache invalidation on document ingestion |
| Document embeddings | pgvector (long-term) | **Correct** |
| Case note history | PostgreSQL (long-term) | **Correct** |
| Audit logs | PostgreSQL (episodic) | **Correct**, but eventually needs archival policy (see below) |
| Risk flag history | PostgreSQL (long-term) | **Correct** — append-only, queried for trend analysis |

### Promotion Strategy: Short-term → Long-term

The document doesn't define when/how data moves from Redis to PostgreSQL. This needs explicit rules:

| Trigger | Action | Source → Destination |
|---|---|---|
| Voice session completes | Flush form data + transcript summary | Redis → PostgreSQL |
| HITL approval > 1h old | Persist checkpoint to PostgreSQL | Redis → PostgreSQL |
| Session timeout (TTL expiry) | Log incomplete session for review | Redis → PostgreSQL (audit) |
| Case note submitted | Write structured note immediately | Direct to PostgreSQL (no Redis) |

### Eviction Policy: What the Design Misses

**Audit log retention**: The audit log stores EVERY LLM call's full input and output. At 50 orgs with 2,000 shifts/day + RAG queries + voice + risk flagging, this is conservatively ~10K audit entries/day, each ~5KB (average prompt + response). That's **50MB/day = 1.5GB/month = 18GB/year**. Cloud SQL storage is ~$0.17/GB/month, so the cost is trivial (~$3/yr), but the table will grow indefinitely.

**Recommendation**: 
- Retain full audit data for 90 days (NDIS compliance window)
- After 90 days, move to cold storage (GCS, compressed JSONL)
- Keep summary record in PostgreSQL (agent, timestamp, token count, confidence, status) permanently
- This keeps the audit table queryable for recent compliance audits while preventing unbounded growth

### PII in Vectors — Critical Gap

The design stores document embeddings in pgvector. If the source documents contain participant PII (names, Medicare numbers, NDIS plan details), the **embedding vectors themselves are PII** under Australian Privacy Act — vectors can potentially be reversed to recover source text (Embedding Inversion Attacks, Morris et al. 2023).

**Implications**:
- Vector data falls under the same data residency requirements as source text
- Right-to-deletion (Australian Privacy Principle 13) requires the ability to delete a participant's vectors
- The current design has no mechanism to identify which vectors contain a specific participant's data

**Recommendation**:
- Add `participant_id` metadata to chunks that contain participant-specific data (most RAG chunks are policy docs without PII — this only applies to case note embeddings if those get embedded)
- For MVP (policy docs only), this is not urgent — NDIS policy documents don't contain PII
- Flag this as a Phase 3 requirement when case note embeddings are added

---

## SUMMARY: PRIORITY RECOMMENDATIONS

| Priority | Issue | Impact | Effort |
|---|---|---|---|
| **P0** | Specify cosine distance metric for pgvector HNSW | Wrong metric = silently bad retrieval | 1 line of code |
| **P0** | Dual-write LangGraph checkpoints (Redis + PostgreSQL) for HITL | Lost checkpoint = lost work + compliance gap | Medium |
| **P0** | Transactional Outbox Pattern for event publishing | Missing events = broken async chains | Medium |
| **P1** | Cache invalidation on document ingestion | Stale cache = wrong RAG answers | Small |
| **P1** | Flush completed voice session data to PostgreSQL | Redis data loss = lost session | Small |
| **P1** | BM25 implementation clarification (Postgres `ts_rank_cd` vs. true BM25) | Incorrect assumption during implementation | Documentation |
| **P1** | Specify RRF constant `k=60` and initial Top-K=30 | Undefined parameters delay implementation | Documentation |
| **P2** | Partial HNSW indexes per tenant for large tenants | Performance degradation at scale | Medium (can defer) |
| **P2** | Audit log archival policy (90-day hot, cold storage after) | Table growth, query slowdown | Medium (defer to production) |
| **P2** | Embedding model migration runbook | Enables future model upgrades | Documentation |
| **P3** | PII in vectors tracking (`participant_id` metadata) | Privacy compliance for case note embeddings | Small (Phase 3) |

---

Type **'continue'** for Phase 3: Cost & Latency Optimization.