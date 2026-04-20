# Sprint 0 Definition — Sena AI/ML Backend

## Context

The Sena AI team (2 effective builders + 1 intern) needs to set up the foundational infrastructure before coding Module 1 (OCR) and Module 2 (RAG Chatbot). Currently: no repo, no cloud account, no deployment pipeline. Several critical decisions are blocked on client answers (cloud provider, auth system, integration approach). Sprint 0 focuses on building everything that is cloud-agnostic NOW, while preparing to unblock the cloud-dependent work via a client meeting.

**Exit condition:** A developer can clone the repo, run `docker compose up`, have a working FastAPI service connected to Postgres with pgvector and RLS policies, run the test suite, and begin writing module-specific code.

---

## Three Parallel Tracks

| Track | What | Blocked on | Who |
|-------|------|-----------|-----|
| **A: Cloud-Agnostic Foundation** | Repo, scaffold, DB, tests, Docker | Nothing — start immediately | Senior lead + Team lead |
| **B: Client Meeting & Research** | Unblock cloud/auth/integration decisions, gather NDIS docs | Meeting scheduling | Senior lead + Intern |
| **C: Cloud-Dependent Setup** | Cloud account, CI/CD, model access, first deployment | Track B answers | Senior lead + Team lead |

---

## Track A: Cloud-Agnostic Foundation (Start Day 1)

### A.1 Monorepo Setup

Create a monorepo (single repo for all AI services — 2-person team doesn't benefit from multi-repo overhead).

**Structure:**
```
sena-ai/
├── docker-compose.yml
├── .env.example
├── .pre-commit-config.yaml
├── pyproject.toml                    # root tooling config (ruff, mypy, pytest)
├── Makefile                          # make up, make test, make lint, make migrate, make seed
├── services/
│   ├── ocr/                          # Module 1
│   │   ├── Dockerfile
│   │   ├── pyproject.toml
│   │   ├── src/ocr/
│   │   │   ├── main.py              # FastAPI app factory
│   │   │   ├── api/routes.py
│   │   │   ├── core/config.py
│   │   │   ├── models/              # Pydantic request/response schemas
│   │   │   └── service/             # Business logic
│   │   └── tests/
│   └── rag/                          # Module 2 (same structure, created later)
├── shared/                           # Shared library (installed as editable dep in each service)
│   ├── pyproject.toml
│   ├── src/sena_common/
│   │   ├── middleware/
│   │   │   ├── tenant_context.py    # Extract tenant_id, set DB session var
│   │   │   ├── error_handler.py     # Global exception handling
│   │   │   └── request_id.py        # Correlation ID propagation
│   │   ├── db/
│   │   │   ├── session.py           # Async SQLAlchemy session factory
│   │   │   ├── base.py             # Declarative base with TenantMixin, TimestampMixin
│   │   │   └── rls.py              # RLS policy setup helpers
│   │   ├── auth/
│   │   │   └── token.py            # TenantResolver protocol (abstract interface)
│   │   ├── schemas/
│   │   │   ├── responses.py        # Standard API response envelope
│   │   │   └── errors.py           # Standard error models
│   │   └── config/settings.py      # Pydantic BaseSettings
│   └── tests/
│       └── test_tenant_isolation.py # THE critical RLS test
├── migrations/                       # Alembic (centralized — all services share one AI DB)
│   ├── alembic.ini
│   ├── env.py
│   └── versions/
├── scripts/
│   ├── seed_dev_data.py            # Populate dev DB with test tenants
│   └── setup_rls.sql               # RLS policy SQL
└── docs/
    ├── architecture/               # Existing intern specs (reference only)
    └── runbooks/                   # Deployment and operations guides
```

**Assigned to:** Senior lead creates structure + architectural decisions. Team lead populates boilerplate.

---

### A.2 FastAPI Service Scaffold (OCR as reference)

Build the OCR service skeleton end-to-end. Every future service copies this pattern.

**What it includes:**

1. **App factory** (`create_app()`) — registers middleware, sets up lifespan events (DB pool), includes routers

2. **Tenant context middleware** (the most critical shared code):
   - Abstract `TenantResolver` protocol — so auth implementation can be swapped later
   - `HeaderTenantResolver` for local dev (reads `X-Tenant-ID` header)
   - `JWTTenantResolver` stub (implemented after client confirms auth system)
   - Stores tenant_id in Python `contextvars`
   - Sets Postgres session variable `SET app.current_tenant = :tenant_id` for RLS
   - Rejects requests without tenant context (except `/health`)

3. **Standard response envelope:**
   ```json
   {
     "status": "success | error",
     "data": { ... },
     "error": { "code": "...", "message": "..." },
     "metadata": { "request_id": "...", "tenant_id": "...", "timestamp": "..." }
   }
   ```

4. **Global error handling** — catches known exceptions, returns structured JSON, never leaks internals

5. **Health check** — `GET /health` returning service name, version, DB status

6. **Structured logging** — `structlog` with JSON output, every line includes `tenant_id` + `request_id`

**Assigned to:** Senior lead = tenant middleware + auth interface. Team lead = error handling, response models, health check, logging.

---

### A.3 Docker Local Dev Environment

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16       # Postgres 16 with pgvector pre-installed
    environment:
      POSTGRES_DB: sena_ai
      POSTGRES_USER: sena
      POSTGRES_PASSWORD: localdev
    ports: ["5432:5432"]
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./scripts/setup_rls.sql:/docker-entrypoint-initdb.d/01-rls.sql

  ocr-service:
    build: { context: ., dockerfile: services/ocr/Dockerfile }
    environment:
      DATABASE_URL: postgresql+asyncpg://sena_app:localdev@postgres:5432/sena_ai
      ENVIRONMENT: development
    ports: ["8001:8000"]
    volumes:                              # hot reload
      - ./services/ocr/src:/app/src
      - ./shared/src:/app/shared/src
    depends_on: [postgres]
```

**Assigned to:** Team lead.

---

### A.4 Database Schema + RLS Policies

**Core schema via Alembic migrations:**

- `tenants` table (id, name, slug, is_active, timestamps)
- `ocr_jobs` table (id, tenant_id, document_type, status, extracted_fields JSONB, confidence, timestamps)
- `document_chunks` table (id, tenant_id, document_id, chunk_index, content, heading_hierarchy, embedding vector(768), content_tsvector, metadata JSONB, timestamps)
- HNSW index on embeddings, GIN index on tsvector

**RLS policies (legally critical):**
```sql
ALTER TABLE ocr_jobs ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON ocr_jobs
    USING (tenant_id = current_setting('app.current_tenant')::uuid);

-- document_chunks allows SYSTEM tenant for shared NDIS docs
ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON document_chunks
    USING (
        tenant_id = current_setting('app.current_tenant')::uuid
        OR tenant_id = '00000000-0000-0000-0000-000000000000'
    );
```

**Critical:** The application DB user (`sena_app`) must NOT be a superuser. Superusers bypass RLS entirely. Use a separate superuser role only for Alembic migrations.

**SQLAlchemy integration:**
- `TenantMixin` — auto-adds `tenant_id` column to every model
- `TimestampMixin` — auto-adds `created_at`, `updated_at`
- Session factory sets `app.current_tenant` on every connection checkout

**Assigned to:** Senior lead = schema design, RLS policies, session/tenant propagation. Team lead = Alembic scaffolding, model boilerplate.

---

### A.5 Testing Framework

**Stack:** pytest + pytest-asyncio + httpx (AsyncClient) + testcontainers-python (real Postgres, not mocks)

**The one test that matters most:**
```python
async def test_tenant_isolation():
    """Tenant A's data is invisible to Tenant B. Legal requirement."""
    # Insert a record as Tenant A
    # Query as Tenant B → assert zero results
    # Query as Tenant A → assert one result
```

This test validates RLS works. It runs against a real Postgres (via testcontainers). If it ever fails, all other work stops.

Additional Sprint 0 tests: health check returns 200, requests without tenant_id are rejected.

**Assigned to:** Senior lead = tenant isolation test + conftest fixtures. Team lead = health check tests, route test patterns.

---

### A.6 Code Quality Tooling

- `ruff` for linting + formatting (replaces black + isort + flake8)
- `mypy` strict mode on shared library
- `pre-commit` hooks running ruff + mypy before every commit

Config in root `pyproject.toml`. **Assigned to:** Team lead.

---

## Track B: Client Meeting & Research (Start Day 1, parallel to Track A)

### B.1 Client Meeting — Agenda

**Must answer before ANY development:**

| # | Question | Ask | Unblocks |
|---|----------|-----|----------|
| 1 | What cloud provider does the platform use? | Nishant | LLM, OCR engine, embedding, deployment, storage |
| 2 | API-based integration or shared DB access? | Nishant | How every AI module reads/writes platform data |
| 3 | What auth system exists? Does the token include an org/tenant ID? | Nishant | Multi-tenant data isolation |

**Must answer before Module 1 (OCR):**

| # | Question | Ask | Unblocks |
|---|----------|-----|----------|
| 4 | Which government ID types does OCR need to handle? | Sandeep | Module 1 scope |
| 5 | Can we get sample images of each type? (redacted/dummy OK) | Sandeep | Testing |
| 6 | What fields must be extracted from each type? | Sandeep | Output schema |

**Must answer before Module 2 (RAG):**

| # | Question | Ask | Unblocks |
|---|----------|-----|----------|
| 7 | Sample NDIS policy documents? Are Practice Standards publicly available? | Sandeep | RAG development + chunking validation |
| 8 | How do orgs upload their own policies? (portal? file upload?) | Sandeep/Nishant | Ingestion pipeline design |
| 9 | Who uploads shared NDIS docs vs. per-tenant docs? | Sandeep | Multi-tenancy design for shared knowledge base |

**Preparation:** Senior lead prepares a one-page integration diagram (Option A: API-based vs Option B: shared DB) and a proposed JWT claims structure for Nishant to confirm.

**Assigned to:** Senior lead prepares materials + leads technical discussion. Intern sends agenda ahead of time + takes notes.

---

### B.2 NDIS Document Research (Intern, parallel)

Many NDIS documents are publicly available on the NDIS Quality and Safeguards Commission website.

**Intern tasks:**
1. Download NDIS Practice Standards and Quality Indicators
2. Download Regulated Restrictive Practices Guide
3. Download NDIS Code of Conduct
4. Create a catalog: document name, URL, page count, structure notes (numbered sections? tables?)
5. Write 10 question-answer pairs per document (2-3 docs) — these become the **RAG evaluation test set**

**Assigned to:** Intern. This is the most valuable intern contribution in Sprint 0.

---

### B.3 Sample Data / Test Fixtures (Intern, parallel)

1. Create 3 fake service provider organizations with realistic AU details
2. Create 2-3 fake users per tenant with different roles
3. Find or create sample Australian ID images for OCR testing
4. Format as seed script (`scripts/seed_dev_data.py`)

**Assigned to:** Intern, with data format guidance from team lead.

---

## Track C: Cloud-Dependent Setup (After client meeting)

### C.1 Cloud Account + Postgres

Whichever cloud is confirmed:
- Create project/account in Australian region
- Provision managed Postgres with pgvector extension, SSL enforced, automated backups
- Create restricted application DB role (NOT superuser)
- Set up container registry
- Create service account/IAM with minimal permissions

**Assigned to:** Senior lead = architecture + IAM. Team lead = provisioning.

### C.2 CI/CD Pipeline

Use whatever matches the team's version control (GitHub → GitHub Actions, GitLab → GitLab CI).

**Minimum viable pipeline:**
```
On push to main: lint → type check → test → build Docker image → push to registry
On PR: lint → type check → test → post results as comment
```

No auto-deploy yet — first deployment is manual.

**Assigned to:** Team lead.

### C.3 Model Access Verification

Based on cloud provider:

| Cloud | LLM | Embeddings | OCR |
|-------|-----|-----------|-----|
| GCP | Gemini via Vertex AI (Sydney) | text-embedding-004 | Document AI |
| AWS | Claude/Titan via Bedrock (Sydney) | Titan Embeddings | Textract |
| Azure | GPT-4o via Azure OpenAI (AU East) | text-embedding-3-large | Document Intelligence |

Write a simple test script that sends one request to each model endpoint and confirms a response.

**Assigned to:** Senior lead.

### C.4 First Deployment (Staging Only)

Deploy the OCR scaffold (just health check) to staging. Verify: service starts, DB connection works, health check returns 200.

Document the procedure in `docs/runbooks/deploy.md`.

**Assigned to:** Senior lead + team lead pair on this.

---

## Task Assignment Summary

### Senior Lead

| Priority | Task | Track | Est. Days |
|----------|------|-------|-----------|
| 1 | Repo structure + service scaffold architecture | A.1, A.2 | 0.5 |
| 2 | Tenant context middleware + auth interface | A.2 | 1.5 |
| 3 | DB schema + RLS policies + session propagation | A.4 | 1.5 |
| 4 | Tenant isolation integration test | A.5 | 0.5 |
| 5 | Client meeting prep + lead meeting | B.1 | 1 |
| 6 | Cloud account + IAM + model access | C.1, C.3 | 1 |
| 7 | First staging deployment (pair) | C.4 | 0.5 |
| | **Total** | | **~6-7 days** |

### Team Lead

| Priority | Task | Track | Est. Days |
|----------|------|-------|-----------|
| 1 | Docker Compose setup | A.3 | 1 |
| 2 | FastAPI boilerplate (errors, responses, health, logging) | A.2 | 1.5 |
| 3 | Alembic scaffolding + initial migration | A.4 | 1 |
| 4 | Code quality tooling + Makefile | A.6 | 0.5 |
| 5 | Basic route test patterns | A.5 | 0.5 |
| 6 | CI/CD pipeline | C.2 | 1 |
| 7 | First staging deployment (pair) | C.4 | 0.5 |
| | **Total** | | **~6-7 days** |

### Intern

| Task | Track | Est. Days |
|------|-------|-----------|
| Download + catalog public NDIS documents | B.2 | 2-3 |
| Write RAG evaluation Q&A pairs (10 per doc, 2-3 docs) | B.2 | 2 |
| Create fake tenant/user seed data | B.3 | 1 |
| Find/create sample OCR test images | B.3 | 1-2 |
| Send meeting agenda, take notes | B.1 | As needed |
| Write local dev setup runbook | — | 0.5 |
| **Total** | | **~7-8 days** |

---

## Explicitly NOT in Sprint 0

- **Infrastructure as Code (Terraform/Pulumi)** — infra will change; documented runbooks first
- **Redis/caching** — not needed until Voice module (Module 3)
- **Distributed tracing / custom dashboards** — nothing to observe yet
- **Rate limiting** — no external users yet
- **Voice infrastructure (LiveKit, WebRTC)** — Module 3
- **Cross-encoder reranking** — deferred per technical decisions
- **LangChain or any RAG framework** — build with direct API calls first, understand mechanics before adding abstractions
- **Multi-environment (dev/staging/prod)** — staging only; prod when there's something to ship
- **Auto-deployment** — manual deploy first to validate pipeline

---

## Definition of Done

### Must be true (blocks Module 1):

- [ ] Repo exists with monorepo structure, all team members can clone
- [ ] `docker compose up` starts Postgres+pgvector and OCR service, health check returns 200
- [ ] Tenant context middleware works — no tenant_id = rejected, valid tenant_id = propagated to DB
- [ ] RLS policies active — tenant isolation test passes (Tenant A invisible to Tenant B)
- [ ] Application DB user is NOT a superuser (verified)
- [ ] `alembic upgrade head` creates all tables, indexes, and RLS policies from blank DB
- [ ] Test suite green: health check + tenant isolation + no-tenant-rejected
- [ ] Linting and type checking pass (`ruff check .` + `mypy .`)
- [ ] Client meeting completed — cloud, integration approach, and auth answers documented

### Should be true:

- [ ] Cloud account provisioned with managed Postgres in AU region
- [ ] CI/CD pipeline runs on push (lint → test → build)
- [ ] First "hello world" deployment — scaffold health check reachable at staging URL
- [ ] LLM/OCR/Embedding model access verified with test call
- [ ] OCR document types confirmed by Sandeep
- [ ] Sample NDIS documents obtained
- [ ] Seed script works (`make seed` populates 3 test tenants)

### Nice to have:

- [ ] RAG evaluation question set (10+ Q&A pairs)
- [ ] Sample OCR test images for each confirmed document type
- [ ] Local dev setup runbook written and tested by someone other than its author

---

## Files to create/modify

| File | Purpose |
|------|---------|
| `QUESTIONS_FOR_CLIENT.md` | Already exists — update with meeting outcomes |
| `TECHNICAL_DECISIONS.md` | Already exists — update as decisions are made post-meeting |
| `CLAUDE.md` | Already exists — update with Sprint 0 outcomes |
| New repo: all files in the monorepo structure above | The deliverable of Sprint 0 |
