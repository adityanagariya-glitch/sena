# Technical Decisions — To Discuss with Senior / Architect

> These are decisions the AI team needs to make internally. They don't depend on the client — they depend on our own technical judgment, experience, and constraints. Some may benefit from discussion with a senior engineer or architect.
>
> **Status key:** OPEN = undecided | DECIDED = locked in | LEANING = have a preference but want validation
>
> **For each decision:** Options are listed with trade-offs. The "Leaning toward" note (if present) is the current thinking — challenge it if you disagree.

---

## A. Foundational Architecture Decisions

### A.1 Cloud Provider [OPEN — PARTIALLY BLOCKED ON CLIENT]
**Depends on:** What the platform team uses (see QUESTIONS_FOR_CLIENT.md §5.1)

**If the platform team is already on a cloud:**
→ Use the same one. Cross-cloud data transfer adds latency, cost, and complexity for no benefit.

**If it's a greenfield choice, the options:**

| Criteria | GCP | AWS | Azure |
|---|---|---|---|
| AI/ML services | Vertex AI, Gemini, Document AI — strong, tightly integrated | SageMaker, Bedrock, Textract — broadest model selection | Azure OpenAI, Document Intelligence — best if using OpenAI models |
| Managed Kubernetes | GKE Autopilot — best-in-class, minimal ops | EKS — solid but more to manage | AKS — good, well-integrated |
| Vector DB options | pgvector on Cloud SQL, Vertex AI Vector Search | pgvector on RDS, OpenSearch, Pinecone | pgvector on Azure DB, Azure AI Search |
| AU data residency | `australia-southeast1` (Sydney) | `ap-southeast-2` (Sydney) | `australiaeast` (NSW) |
| Cost for AI workloads | Competitive, good free tier for Vertex | Generally more expensive for ML | Competitive if using Azure OpenAI |
| Team familiarity | ? | ? | ? |

**Key question to answer yourself:** Which cloud does the team have the most experience with?

---

### A.2 Deployment Model [OPEN]
**Question:** How do we package and run our AI services?

**Option A: Kubernetes (GKE/EKS/AKS)**
- Pros: Full control, scales well, works for all module types (HTTP APIs, background workers, streaming voice)
- Cons: Operational complexity, steep learning curve if the team hasn't used K8s
- Best for: Teams with K8s experience, projects with diverse workload types (which this is)

**Option B: Serverless Functions (Cloud Functions / Lambda)**
- Pros: Zero ops, pay-per-invocation, auto-scales to zero
- Cons: Cold starts (bad for voice), 60-540s timeouts (bad for report generation), no persistent connections (bad for WebSocket/streaming)
- Best for: Simple request-response APIs like OCR

**Option C: Managed Container Platform (Cloud Run / ECS Fargate / Azure Container Apps)**
- Pros: Docker-based (portable), auto-scaling with scale-to-zero, supports long-running requests, no K8s ops overhead
- Cons: Less control than K8s, some limits on networking (e.g., no raw TCP for voice)
- Best for: HTTP-based services. Voice/streaming may need a separate solution.

**Option D: Hybrid — Cloud Run for HTTP + Dedicated Compute for Voice**
- Pros: Best of both — simple deployment for APIs, dedicated infra for real-time streaming
- Cons: Two deployment models to maintain

**Leaning toward:** Option C or D. Cloud Run (or equivalent) for the HTTP-based modules (OCR, RAG, risk flagging, reporting) because it eliminates K8s operational overhead for a 2-person team. Voice module gets dedicated compute later when we build it (Module 3).

**Decision factor:** Does anyone on the team have Kubernetes experience? If not, the ops overhead of GKE could eat into development time significantly.

---

### A.3 Programming Language & Framework [DECIDED]
**Decision:** Python + FastAPI

**Reasoning:** The AI/ML ecosystem is Python-first — every model SDK, RAG framework, and voice processing library targets Python. FastAPI over Django because the services are AI API endpoints (async, lightweight), not CRUD apps. Team is comfortable with FastAPI.

---

### A.4 Multi-Tenancy Enforcement [DECIDED]
**Decision:** Row-Level Security (RLS) in Postgres + application-level tenant filtering + metadata-filtered vector search

**Reasoning:**
- RLS enforces isolation at the DB level — safety net even if app code has a bug
- Application-level `WHERE tenant_id = :id` as defense-in-depth
- Vector searches always include `tenant_id` metadata filter
- Schema-per-tenant or DB-per-tenant adds operational complexity a 2-person team doesn't need
- Designed with future migration path to physical isolation if scale demands it
- Meets Australian privacy law requirements for mandated data isolation

---

### A.5 LLM Provider & Model Selection [OPEN]
**Question:** Which LLM(s) power the AI features?

| Use Case | Option A: Google Gemini | Option B: OpenAI GPT | Option C: Anthropic Claude | Option D: Open Source (Llama, Mistral) |
|---|---|---|---|---|
| **RAG Chat** | Gemini 1.5 Pro — long context window (1M tokens), good for document QA | GPT-4o — strong reasoning, function calling | Claude 3.5 Sonnet — excellent at following instructions, long context | Llama 3 70B — requires self-hosting, no API cost |
| **Voice (STT/TTS)** | Gemini multimodal (native audio) | Whisper (STT) + TTS API | No native voice | Whisper (self-hosted) |
| **OCR fallback** | Gemini Flash — fast, cheap, multimodal | GPT-4o vision | Claude vision | Not competitive for OCR |
| **Case note structuring** | Gemini Flash — fast, cheap | GPT-4o mini — fast, cheap | Claude Haiku — fast, cheap | Llama 3 8B — self-hosted |
| **AU data residency** | Vertex AI has Sydney region | Azure OpenAI has AU East region; direct OpenAI API does NOT guarantee AU residency | No AU region currently | Self-hosted = full control over residency |
| **Cost** | Pay-per-token via Vertex AI | Pay-per-token | Pay-per-token | Infra cost only (GPU instances) |
| **Vendor lock-in** | Moderate (Vertex AI SDK) | Low (standard API) | Low (standard API) | None |

**Critical constraint: Australian data residency.** If sensitive participant/medical data is included in prompts:
- Google Vertex AI in `australia-southeast1` = compliant
- Azure OpenAI in `australiaeast` = compliant
- Direct OpenAI API = data may be processed in US = potentially non-compliant
- Direct Anthropic API = no AU region = potentially non-compliant
- Self-hosted = compliant by definition

**Leaning toward:** This depends heavily on the cloud provider decision (A.1). If GCP → Gemini via Vertex AI is the natural choice (data stays in AU, tightly integrated, multimodal). If Azure → Azure OpenAI. The key principle: use the cloud provider's AI services for data residency compliance rather than calling third-party APIs with sensitive data.

**Question for yourself:** Have you experimented with any of these models already? Personal experience with a model's strengths/weaknesses beats spec-sheet comparisons.

---

## B. Module-Specific Technical Decisions

### B.1 OCR: Processing Pipeline [OPEN]
**Question:** What handles the document image → structured data extraction?

**Option A: Cloud OCR Service (Document AI / Textract / Azure DI)**
- Pros: High accuracy on standard documents, pre-trained on IDs, minimal code
- Cons: Per-page cost, vendor lock-in, may not handle all AU document types

**Option B: LLM Vision (Gemini/GPT-4o/Claude vision)**
- Pros: Flexible — can extract any fields from any document type via prompting, handles non-standard layouts
- Cons: More expensive per call, slower, prompt engineering required

**Option C: Hybrid (Cloud OCR primary + LLM fallback)**
- Pros: Use the cheap/fast option first, fall back to the flexible option when confidence is low
- Cons: Two systems to maintain

**Leaning toward:** Option C. Cloud OCR (whichever provider we choose) handles standard documents well and cheaply. LLM vision handles edge cases. Confidence threshold determines which path is taken.

---

### B.2 RAG: Vector Store [DECIDED]
**Decision:** pgvector (Postgres extension)

**Reasoning:**
- Same database as everything else — no new infrastructure to deploy, monitor, or pay for
- Multi-tenancy via RLS applies to vectors the same way it applies to all other data — unified enforcement
- HNSW indexes handle the expected scale (<100K vectors initially) with no performance concerns
- Migration path to a dedicated vector DB exists if scale demands it later
- Keeps the stack simple for a 2-person team

---

### B.3 RAG: Embedding Model [OPEN]
**Question:** Which model converts text chunks into vectors?

| Model | Dimensions | Quality (MTEB) | Cost | AU Residency |
|---|---|---|---|---|
| text-embedding-004 (Google) | 768 | Good | $0.00001/1K tokens | Yes (Vertex AI Sydney) |
| text-embedding-3-large (OpenAI) | 3072 | Best-in-class | $0.00013/1K tokens | No guarantee |
| Cohere embed-v3 | 1024 | Very good | $0.0001/1K tokens | No guarantee |
| BGE-large-en-v1.5 (open source) | 1024 | Good | Free (self-hosted) | Yes (self-hosted) |

**Leaning toward:** Depends on cloud decision. If GCP → Google's embedding model (data stays in AU). The quality differences between top embedding models are small enough that data residency compliance should be the deciding factor, not benchmark scores.

---

### B.4 RAG: Retrieval Strategy [DECIDED]
**Decision:** Hybrid search (vector + BM25 keyword) with Reciprocal Rank Fusion. Add cross-encoder reranking later if accuracy is insufficient.

**Reasoning:**
- NDIS policy content has both semantic queries ("what are restrictive practice requirements") and exact matches ("Practice Standard 4.3.2") — pure vector search misses the second type
- pgvector handles vector search, Postgres `tsvector`/`tsquery` handles keyword search — both in the same database, no extra infra
- RRF (Reciprocal Rank Fusion) combines scores from both retrieval methods
- Cross-encoder reranking deferred — adds 100-300ms latency and model complexity. Add only if retrieval quality testing shows it's needed

---

### B.5 RAG: Chunking Strategy [DECIDED — needs validation with real data]
**Decision:** Structure-aware chunking (by section/heading) with recursive fallback for oversized sections.

**Approach:**
1. Parse document → identify section headings (NDIS docs are well-structured with numbered sections)
2. Each section becomes a chunk, with full heading hierarchy preserved as metadata (e.g., `"Part 4 > 4.3 Core Module > 4.3.2 Risk Management"`)
3. If a section exceeds ~1500 tokens, recursively split by paragraphs → sentences
4. Parent section title attached to each sub-chunk so retrieval context is preserved

**Reasoning:**
- NDIS policy documents have clear hierarchical structure — chunking by section preserves the most meaning
- Heading metadata enables better retrieval and citation (user sees which section the answer came from)
- Needs empirical validation with real NDIS documents — parameters (max chunk size, overlap, heading depth) tuned with data, not guesswork

**Blocked on:** Sample NDIS policy PDFs from Sandeep (see QUESTIONS_FOR_CLIENT.md §3.1)

---

## C. Infrastructure & Operations Decisions

### C.1 CI/CD Pipeline [OPEN]
**Question:** How does code go from a commit to a running service?

**Options:** GitHub Actions, GitLab CI, Cloud Build (GCP), CodePipeline (AWS)

**Leaning toward:** Whatever the team already uses for version control. If GitHub → GitHub Actions. If GitLab → GitLab CI. Don't add a new tool just for CI/CD.

---

### C.2 Infrastructure as Code [OPEN]
**Question:** How do we define and reproduce our cloud infrastructure?

**Options:** Terraform, Pulumi, cloud-native (CloudFormation/Deployment Manager)

**Leaning toward:** Terraform if anyone on the team knows it. Otherwise, start with manual setup + documented runbooks for the first sprint, and add IaC once the infrastructure stabilizes. Premature IaC on a 2-person team can slow you down.

---

### C.3 Monitoring & Observability [OPEN]
**Question:** How do we know if our services are healthy, and how do we debug production issues?

**Minimum viable monitoring:**
- Health check endpoints on every service
- Cloud-native logging (Cloud Logging / CloudWatch)
- Error alerting (PagerDuty, Slack, or just email)

**Can add later:**
- Distributed tracing (Jaeger/OpenTelemetry)
- Custom dashboards (Grafana)
- AI-specific metrics (latency per model call, token usage, confidence distributions)

**Leaning toward:** Start with cloud-native logging + basic health checks. Add observability tooling when there's something in production to observe.

---

## D. Decisions That Can Wait

These are real decisions but they're premature right now. Documented here so we don't forget them:

- **Voice infrastructure** (LiveKit vs. Twilio vs. custom) — wait until Module 3
- **Report template engine** (LaTeX vs. HTML-to-PDF vs. DOCX) — wait until Reporting module
- **Batch processing architecture** (for Communication Log Analysis, Medication tracking) — wait until those modules
- **Cost optimization** (spot instances, model routing, caching) — wait until we have production traffic to measure
- **Horizontal scaling strategy** — wait until we have real usage data

---

## Summary: Decision Priority

**Must decide FIRST (blocks everything):**
1. Cloud provider (A.1) — but partially depends on client answer
2. Deployment model (A.2) — how do we run our services
3. Language & framework (A.3) — what do we write code in

**Must decide before Module 1 (OCR):**
4. OCR processing pipeline (B.1)

**Must decide before Module 2 (RAG):**
5. LLM provider (A.5)
6. Vector store (B.2)
7. Embedding model (B.3)
8. Retrieval strategy (B.4)
9. Chunking strategy (B.5)

**Can decide as we go:**
- Multi-tenancy details (A.4) — the approach is clear (RLS), implementation details come during coding
- CI/CD (C.1) — set up when we start coding
- IaC (C.2) — add when infra stabilizes
- Monitoring (C.3) — add when something is running
