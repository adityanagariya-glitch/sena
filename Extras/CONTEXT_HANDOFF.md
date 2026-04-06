# SENA AI/ML Backend — Central Context Handoff Document

> **THIS IS A LIVING DOCUMENT.** Update it every time you complete a task, make a decision, encounter a bug, or change direction. Read it at the start of every new chat session. It is the single source of truth.

---

## 1. Project Overview

### What is Sena?
Sena is an AI-powered **multi-tenant SaaS platform** for Australian **NDIS (National Disability Insurance Scheme)** service providers. It helps disability support organizations manage participants, staff, shifts, case notes, compliance, and reporting.

### What does OUR team own?
We own the **AI/ML backend layer only**. The broader platform (HR, payroll, shifts, client management, frontend) is built by a separate client-side team. We are a vendor AI team building AI services that integrate with their platform.

### Team
| Person | Role | Capacity |
|--------|------|----------|
| **User** (you/me) | AI/ML development lead, senior, owns architecture + implementation | Full-time |
| **Team lead** | 3-4 years experience, supports at every phase | Full-time |
| **Intern** | Learning, handles guided tasks (doc research, seed data, notes) | Assisted |
| **Effective builders** | **2 people** (user + team lead; intern is support) | |

### Client-side contacts
| Person | Role |
|--------|------|
| **Sandeep** | PM/coordinator (our primary point of contact) |
| **Jill** | Frontend lead |
| **Nishant** | Backend manager |

### Tech Stack (Decided)
| Component | Choice | Status |
|-----------|--------|--------|
| Language | **Python 3.12** | DECIDED |
| Framework | **FastAPI** (async, lightweight) | DECIDED |
| Database | **PostgreSQL 16** with **pgvector** extension | DECIDED |
| ORM | **SQLAlchemy 2.0** (async) | DECIDED |
| Migrations | **Alembic** (centralized, all services share one AI DB) | DECIDED |
| Multi-tenancy | **Row-Level Security (RLS)** + app-level filtering | DECIDED |
| Vector store | **pgvector** (same Postgres, no extra infra) | DECIDED |
| RAG retrieval | **Hybrid search** (vector + BM25 keyword) with RRF | DECIDED |
| RAG chunking | **Structure-aware** (by heading/section) with recursive fallback | DECIDED (needs validation) |
| Settings | **Pydantic Settings** (env vars, prefix `SENA_`) | DECIDED |
| Linting | **ruff** (replaces black + isort + flake8) | DECIDED |
| Type checking | **mypy** strict mode | DECIDED |
| Testing | **pytest** + pytest-asyncio + httpx + testcontainers | DECIDED |
| Logging | **structlog** (JSON output) | DECIDED |
| Container | **Docker** + docker-compose for local dev | DECIDED |
| Repo structure | **Monorepo** (`sena-ai/`) | DECIDED |

### Decisions NOT yet made (blocked on client)
| Decision | Blocker | Unblocks |
|----------|---------|----------|
| Cloud Provider (A.1) | Client meeting — what does their platform use? | LLM, OCR engine, embeddings, deployment, storage |
| Deployment Model (A.2) | Cloud provider decision | How we run services |
| LLM Provider (A.5) | Cloud provider decision | All AI generation features |
| OCR Pipeline (B.1) | Cloud provider + doc types from Sandeep | Module 1 implementation |
| Embedding Model (B.3) | Cloud provider decision | RAG vector generation |
| CI/CD (C.1) | Cloud provider + team's git host | Automated builds/deploys |

### Hard Legal Requirements
1. **Multi-tenant data isolation** — legally mandated, zero cross-tenant leakage
2. **Human-in-the-loop** — all AI outputs require manager/compliance approval before action
3. **Australian data residency** — sensitive data must stay in AU jurisdiction
4. **NDIS compliance** — AI must understand and enforce NDIS regulations

### AI Modules (Full Scope — 10 total)
| # | Module | Platform | Priority |
|---|--------|----------|----------|
| 1 | **OCR Document Extraction** | Mobile | Starter (Module 1) |
| 2 | **Policy/Compliance RAG Chatbot** | Web | Starter (Module 2) |
| 3 | **Voice Onboarding Assistant** | Mobile | Next after starters |
| 4 | Case Note Drafting | Mobile | Later |
| 5 | Case Note Review & Insight Extraction | Web + Mobile | Later |
| 6 | Restrictive Practices Drafting | Web | Later |
| 7 | Risk Flagging & Escalation | Web + Mobile | Later |
| 8 | Reporting | Web + Mobile | Later |
| 9 | Communication Log Analysis | Web + Mobile | Later |
| 10 | Medication & Health Risk Detection | Web + Mobile | Later |

**Why OCR first:** Zero dependencies on other teams, quick win, builds the deployment pipeline.
**Why RAG second:** Foundational infra (embeddings, vector store, retrieval) reused by 5+ later modules, tests multi-tenancy early.
**Why NOT voice first:** Voice requires real-time streaming infra, frontend coordination, and form field definitions — too many external dependencies for a starter.

---

## 2. Completed Work

### Planning Phase (Completed)
- **Context ingestion:** Read kickoff transcript (`AI Planning & R&D Kickoff Transcript.txt`), meeting notes (`sena_meeting_notes.md`), intern's architecture docs (`docs/architecture/*.md`), gap analysis (`prompt.txt`)
- **Scope clarification:** Established we own AI/ML layer only, not full platform
- **Module sequencing:** Mapped dependencies across all 10 modules; selected OCR + RAG as starters, Voice as Module 3
- **5 foundational tech decisions locked in:** FastAPI, RLS, pgvector, hybrid search, structure-aware chunking
- **Client questions documented:** 12 prioritized questions in `QUESTIONS_FOR_CLIENT.md`
- **Internal decisions documented:** 14 decisions (5 decided, 5 blocked) in `TECHNICAL_DECISIONS.md`
- **Sprint 0 defined:** 3-track parallel plan in `SPRINT_0_PLAN.md`

### Sprint 0 Track A: Monorepo Scaffold (Completed)
Built the entire foundational codebase — **40 files** in `sena-ai/`. This is the reference architecture every future service copies.

**Key deliverables:**

| What | File(s) | Description |
|------|---------|-------------|
| Tenant context middleware | `shared/src/sena_common/middleware/tenant_context.py` | Abstract `TenantResolver` protocol, `HeaderTenantResolver` (dev), `JWTTenantResolver` (stub), context var propagation, exempt paths for health checks |
| DB session factory | `shared/src/sena_common/db/session.py` | Async sessions that auto-set `app.current_tenant` for RLS. `get_session(tenant_id)` and `get_session_no_tenant()` |
| SQLAlchemy base + mixins | `shared/src/sena_common/db/base.py` | `TenantMixin` (auto `tenant_id` column), `TimestampMixin`, `Tenant` model |
| RLS policies | `scripts/setup_rls.sql` | `ocr_jobs`: strict tenant isolation. `document_chunks`: allows SYSTEM tenant for shared NDIS docs |
| Restricted DB user | `scripts/init_db.sql` | `sena_app` role (NOT superuser — superusers bypass RLS) |
| Error handling | `shared/src/sena_common/middleware/error_handler.py` | `TenantIsolationError`, `ResourceNotFoundError`, standard error body, global exception handlers |
| Request ID middleware | `shared/src/sena_common/middleware/request_id.py` | Correlation ID propagation via `X-Request-ID` header |
| Response schemas | `shared/src/sena_common/schemas/responses.py` | `ApiResponse[T]` generic envelope, `HealthResponse` |
| Error responses | `shared/src/sena_common/schemas/errors.py` | `error_response()` helper for consistent error JSONResponse |
| Settings | `shared/src/sena_common/config/settings.py` | Pydantic `BaseSettings` with `SENA_` env prefix |
| OCR app factory | `services/ocr/src/ocr/main.py` | `create_app()` — registers middleware chain (RequestID → Tenant), exception handlers, routers, lifespan (DB init/close) |
| OCR routes | `services/ocr/src/ocr/api/routes.py` | `GET /health` (no tenant needed), `POST /extract` (scaffold, returns 501) |
| OCR config | `services/ocr/src/ocr/core/config.py` | `OCRSettings` extending base settings |
| Docker Compose | `docker-compose.yml` | Postgres 16 + pgvector, OCR service with hot reload, health check |
| Dockerfile | `services/ocr/Dockerfile` | Python 3.12 slim, installs shared lib + service deps |
| Seed data | `scripts/seed_dev_data.py` | 3 test tenants + SYSTEM tenant with deterministic UUIDs |
| Alembic config | `migrations/alembic.ini`, `migrations/env.py` | Async migration setup against `Base.metadata` |
| Tenant isolation tests | `shared/tests/test_tenant_isolation.py` | 3 critical RLS tests: A can't see B, SYSTEM visible to all, private chunks isolated |
| Test fixtures | `shared/tests/conftest.py` | Test engine, session factory, seed tenants fixtures |
| OCR route tests | `services/ocr/tests/test_routes.py` | Health check 200, reject without tenant, scaffold returns 501 |
| Code quality | `pyproject.toml`, `.pre-commit-config.yaml` | ruff + mypy strict + pytest config |
| Developer commands | `Makefile` | `make up/down/test/lint/format/migrate/seed/clean/rebuild/check-rls` |
| Env template | `.env.example` | All env vars with blocked sections for cloud-dependent config |

---

## 3. Current Status — WHERE WE ARE RIGHT NOW

**Phase:** Sprint 0 scaffold is BUILT. No code has been RUN yet.

**What exists:**
- Complete monorepo at `sena-ai/` with 40 files
- All planning docs (`SPRINT_0_PLAN.md`, `QUESTIONS_FOR_CLIENT.md`, `TECHNICAL_DECISIONS.md`, `CLAUDE.md`)
- Intern's reference docs in `docs/architecture/` (treat as rough exploration ONLY)

**What has NOT been done yet:**
- `docker compose up` has NOT been tested
- Tests have NOT been run
- No Alembic migration files have been generated (the `migrations/versions/` directory is empty)
- No git repo has been initialized
- No client meeting has been held
- No cloud provider is confirmed
- No actual OCR or RAG logic is implemented (only scaffolds)

**Blocking items:**
1. Client meeting needed to answer 3 critical questions (cloud provider, integration approach, auth system)
2. Real data expected ~end of March 2026
3. Sample NDIS documents needed for RAG development
4. OCR document types need confirmation from Sandeep

---

## 4. Active Debugging Context

No active debugging — code has not been run yet.

---

## 5. Code Patterns & Standards Established

### Monorepo Structure
```
sena-ai/
├── shared/              # Shared library (sena_common) — installed as editable dep
│   ├── src/sena_common/
│   │   ├── middleware/  # Tenant context, error handling, request ID
│   │   ├── db/          # Session factory, base models, mixins
│   │   ├── auth/        # Token/auth protocols
│   │   ├── schemas/     # Response envelopes, error helpers
│   │   └── config/      # Pydantic settings
│   └── tests/           # Shared tests (tenant isolation)
├── services/
│   ├── ocr/             # Module 1 service (reference pattern)
│   │   ├── src/ocr/
│   │   │   ├── main.py          # App factory (create_app)
│   │   │   ├── api/routes.py    # Endpoints
│   │   │   ├── core/config.py   # Service-specific settings
│   │   │   ├── models/          # Pydantic request/response schemas
│   │   │   └── service/         # Business logic
│   │   └── tests/
│   └── rag/             # Module 2 service (same structure, not yet created)
├── migrations/          # Centralized Alembic migrations
├── scripts/             # DB init, RLS setup, seed data
├── docker-compose.yml
├── Makefile
└── pyproject.toml       # Root config for ruff/mypy/pytest
```

### Tenant Isolation Pattern (THE critical pattern)
Every request flows through:
1. **TenantMiddleware** extracts `tenant_id` from request (header in dev, JWT in prod)
2. Stores in Python `contextvars` as `TenantContext(tenant_id, user_id, role)`
3. **`get_session(tenant_id)`** sets `SET app.current_tenant = :tenant_id` on DB connection
4. **RLS policies** in Postgres filter rows automatically via `current_setting('app.current_tenant')`
5. Even if app code forgets `WHERE tenant_id =`, the database enforces isolation

### Auth Pattern (swappable)
- `TenantResolver` is a `Protocol` (abstract interface)
- `HeaderTenantResolver` — dev mode, reads `X-Tenant-ID`, `X-User-ID`, `X-User-Role` headers
- `JWTTenantResolver` — production mode, validates JWT (stub, waiting on client auth confirmation)
- Middleware accepts any `TenantResolver` implementation

### API Response Pattern
All endpoints return:
```json
{
  "status": "success | error",
  "data": { ... },
  "error": { "code": "...", "message": "..." },
  "metadata": { "request_id": "...", "tenant_id": "...", "timestamp": "..." }
}
```

### Error Handling
- `TenantIsolationError` → 403 (logged as CRITICAL)
- `ResourceNotFoundError` → 404
- `RequestValidationError` → 422 with field-level details
- `HTTPException` → pass-through status code
- Unhandled `Exception` → 500 (generic message, never leaks internals)

### Service Settings Pattern
- Base `Settings` class in shared library with `SENA_` env prefix
- Each service extends: `class OCRSettings(Settings): service_name = "sena-ocr"`
- Cached with `@lru_cache`

### Database Users
- `sena` — superuser for migrations ONLY
- `sena_app` — restricted role for runtime queries (RLS enforced)

### Test Tenant UUIDs (deterministic, used everywhere)
```python
TENANT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Sunshine Care Services
TENANT_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Metro Disability Support
TENANT_C = "cccccccc-cccc-cccc-cccc-cccccccccccc"  # Regional Living Assist
SYSTEM   = "00000000-0000-0000-0000-000000000000"  # Shared NDIS docs
```

### `SYSTEM` Tenant Pattern
- Shared NDIS documents are owned by the `SYSTEM` tenant (UUID all zeros)
- RLS policy on `document_chunks` allows rows where `tenant_id = current_tenant OR tenant_id = SYSTEM`
- `ocr_jobs` does NOT allow SYSTEM access (strict isolation)

---

## 6. Important Technical Decisions & Rationale

### DECIDED

| # | Decision | Choice | Why |
|---|----------|--------|-----|
| A.3 | Language & Framework | Python + FastAPI | AI/ML ecosystem is Python-first. FastAPI for async lightweight APIs, not CRUD-heavy Django. |
| A.4 | Multi-Tenancy | RLS + app-level filtering + metadata-filtered vector search | RLS = safety net even if code has bugs. 2-person team doesn't need schema-per-tenant ops overhead. Meets AU privacy law. |
| B.2 | Vector Store | pgvector | Same DB as everything else = no extra infra. RLS applies uniformly. HNSW handles expected scale (<100K vectors). |
| B.4 | RAG Retrieval | Hybrid (vector + BM25) with RRF | NDIS has both semantic queries and exact matches ("Practice Standard 4.3.2"). Cross-encoder reranking deferred until needed. |
| B.5 | RAG Chunking | Structure-aware by heading/section, recursive fallback | NDIS docs are well-structured. Heading hierarchy preserved as metadata for citations. Needs validation with real docs. |

### OPEN (blocked on client)

| # | Decision | Leaning Toward | See |
|---|----------|---------------|-----|
| A.1 | Cloud Provider | Match whatever the platform team uses | `TECHNICAL_DECISIONS.md` |
| A.2 | Deployment | Cloud Run or equivalent (managed containers), dedicated compute for voice later | `TECHNICAL_DECISIONS.md` |
| A.5 | LLM Provider | Cloud provider's native AI services (data residency) | `TECHNICAL_DECISIONS.md` |
| B.1 | OCR Pipeline | Hybrid (cloud OCR primary + LLM vision fallback) | `TECHNICAL_DECISIONS.md` |
| B.3 | Embedding Model | Cloud provider's embedding model (data residency) | `TECHNICAL_DECISIONS.md` |

### DEFERRED (premature)
- Voice infrastructure (LiveKit vs Twilio) — wait for Module 3
- Report template engine — wait for Reporting module
- Batch processing architecture — wait for later modules
- Cost optimization — wait for production traffic

---

## 7. Known Issues & Gotchas

1. **Intern docs are NOT decisions.** Files in `docs/architecture/` were created by an intern as initial exploration. Treat them as rough starting points. They are NOT finalized specs, NOT production grade, and NOT constraints on our architecture.

2. **Client expects "everything ready to use"** (all 10 modules). No defined deadline exists. This is also an evaluation of the AI team's capability — first impressions matter.

3. **No API contracts exist** between AI team and platform team. Integration approach (API-based vs shared DB) is the single most important undecided question.

4. **Real data expected ~end of March 2026.** Until then, we work with synthetic/seed data.

5. **"Near 100% accuracy" RAG expectation** from Sandeep. This is unrealistic for any RAG system. Need to educate the client on confidence scores, human review workflows, and what "good" looks like.

6. **Superuser bypass of RLS.** The `sena_app` DB user MUST NOT be a superuser. Superusers bypass RLS entirely. The `init_db.sql` script creates this restricted user correctly.

7. **Context variable for tenant.** The tenant context uses Python's `contextvars`. This is per-task safe in async code but be careful with background tasks that run outside the request lifecycle — they need their own tenant context setup.

8. **SYSTEM tenant in document_chunks.** The RLS policy for `document_chunks` allows reading SYSTEM tenant rows from any tenant. This is intentional for shared NDIS docs. But `ocr_jobs` does NOT have this exception — it's strict isolation.

9. **Migrations use superuser, runtime uses restricted user.** Alembic connects as `sena` (superuser). The app connects as `sena_app` (restricted). The `docker-compose.yml` uses `sena_app` for the OCR service.

10. **Health check exemption.** `GET /health`, `/docs`, `/openapi.json`, `/redoc` bypass tenant middleware. All other paths require tenant context.

---

## 8. Future Roadmap — WHAT'S NEXT

### Immediate Next Steps (in order)

1. **Test the scaffold end-to-end**
   - Run `docker compose up` and verify Postgres + OCR service start
   - Generate first Alembic migration (`alembic revision --autogenerate`)
   - Run `alembic upgrade head` to create tables
   - Run `make seed` to populate test tenants
   - Hit `GET http://localhost:8001/v1/ocr/health` and verify response
   - Run `pytest` to check test suite status

2. **Initialize git repo**
   - `git init` in `sena-ai/`
   - Initial commit with scaffold

3. **Schedule client meeting to answer blocking questions**
   - Top 3 (blocks everything): cloud provider, integration approach, auth system
   - Module 1 specific: which document types for OCR
   - Module 2 specific: sample NDIS policy docs
   - Full agenda in `QUESTIONS_FOR_CLIENT.md`

4. **Intern tasks (parallel)**
   - Download public NDIS documents from NDIS Quality and Safeguards Commission website
   - Catalog: document name, URL, page count, structure notes
   - Write 10 Q&A pairs per document (2-3 docs) — becomes RAG evaluation test set
   - Find/create sample Australian ID images for OCR testing

### After Client Meeting

5. **Unlock cloud-dependent decisions** (A.1, A.2, A.5, B.1, B.3)
6. **Provision cloud account** in Australian region
7. **Set up CI/CD pipeline**
8. **Verify model access** (LLM, OCR engine, embedding model)
9. **First staging deployment** (health check reachable at staging URL)

### Module 1 Implementation (OCR)

10. Confirm document types with Sandeep
11. Design OCR processing pipeline (cloud OCR + LLM fallback)
12. Implement file upload → processing → extraction → storage flow
13. Build confidence scoring and validation
14. Integration tests with real document images

### Module 2 Implementation (RAG Chatbot)

15. Build document ingestion pipeline (PDF → chunks → embeddings → pgvector)
16. Implement hybrid retrieval (vector + BM25 + RRF)
17. Build RAG query endpoint with tenant-scoped retrieval
18. Test with NDIS documents
19. Evaluate against Q&A test set (intern builds this)

### Module 3 Planning (Voice Onboarding)

20. Get onboarding form field definitions from Jill
21. Evaluate voice infra options (LiveKit, Twilio, etc.)
22. Design real-time sync between voice agent and mobile UI

---

## 9. Development Workflow

### Local Development Setup
```bash
cd sena-ai
cp .env.example .env        # Edit if needed
docker compose up -d         # Start Postgres + OCR service
make migrate                 # Run Alembic migrations
make seed                    # Populate test tenants
make test                    # Run test suite
make lint                    # Ruff + mypy
```

### Key Commands (Makefile)
| Command | What it does |
|---------|-------------|
| `make up` | `docker compose up -d` |
| `make down` | `docker compose down` |
| `make logs` | `docker compose logs -f` |
| `make test` | `pytest -v` |
| `make lint` | `ruff check . && ruff format --check . && mypy ...` |
| `make format` | `ruff format . && ruff check --fix .` |
| `make migrate` | `alembic upgrade head` (via Docker) |
| `make seed` | Run seed script (via Docker) |
| `make clean` | `docker compose down -v` (destroys data) |
| `make rebuild` | `docker compose build --no-cache` |
| `make check-rls` | Verify RLS is enabled on tables |

### Testing Strategy
- **Unit tests:** Per-service (`services/ocr/tests/`)
- **Integration tests:** Tenant isolation in `shared/tests/test_tenant_isolation.py` — run against real Postgres
- **Test DB:** `sena_ai_test` database (separate from dev)
- **Framework:** pytest + pytest-asyncio + httpx `AsyncClient` + testcontainers

### How to Test Endpoints Manually
```bash
# Health check (no tenant needed)
curl http://localhost:8001/v1/ocr/health

# OCR extract (requires tenant header)
curl -X POST http://localhost:8001/v1/ocr/extract \
  -H "X-Tenant-ID: aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa" \
  -H "X-User-ID: test-user" \
  -H "X-User-Role: admin" \
  -F "document_type=drivers_licence" \
  -F "file=@test-image.jpg"
```

---

## 10. Quick Reference

### Key File Locations
| What | Path |
|------|------|
| Tenant middleware (most critical) | `sena-ai/shared/src/sena_common/middleware/tenant_context.py` |
| DB session factory with RLS | `sena-ai/shared/src/sena_common/db/session.py` |
| SQLAlchemy models/mixins | `sena-ai/shared/src/sena_common/db/base.py` |
| RLS SQL policies | `sena-ai/scripts/setup_rls.sql` |
| DB init (restricted user) | `sena-ai/scripts/init_db.sql` |
| OCR app factory | `sena-ai/services/ocr/src/ocr/main.py` |
| OCR routes | `sena-ai/services/ocr/src/ocr/api/routes.py` |
| Error handling | `sena-ai/shared/src/sena_common/middleware/error_handler.py` |
| Response schemas | `sena-ai/shared/src/sena_common/schemas/responses.py` |
| Settings base | `sena-ai/shared/src/sena_common/config/settings.py` |
| Docker Compose | `sena-ai/docker-compose.yml` |
| Tenant isolation tests | `sena-ai/shared/tests/test_tenant_isolation.py` |
| Seed data | `sena-ai/scripts/seed_dev_data.py` |
| Sprint 0 plan | `SPRINT_0_PLAN.md` |
| Client questions | `QUESTIONS_FOR_CLIENT.md` |
| Technical decisions | `TECHNICAL_DECISIONS.md` |
| Project context (for CLAUDE.md) | `CLAUDE.md` |
| Kickoff transcript | `AI Planning & R&D Kickoff Transcript.txt` |
| Meeting notes | `sena_meeting_notes.md` |
| Intern's specs (reference only) | `docs/architecture/*.md` |

### Important Names/IDs
- Database: `sena_ai` (dev), `sena_ai_test` (test)
- DB superuser: `sena` / password `localdev`
- DB app user: `sena_app` / password `localdev`
- Env var prefix: `SENA_`
- OCR service port: `8001` (maps to container `8000`)
- Tenant A UUID: `aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa` (Sunshine Care)
- Tenant B UUID: `bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb` (Metro Disability)
- Tenant C UUID: `cccccccc-cccc-cccc-cccc-cccccccccccc` (Regional Living)
- SYSTEM UUID: `00000000-0000-0000-0000-000000000000`

### Adding a New Service (copy the OCR pattern)
1. Create `services/<name>/` mirroring `services/ocr/` structure
2. Create `<Name>Settings(Settings)` in `core/config.py`
3. Create `create_app()` in `main.py` following OCR's factory pattern
4. Add service to `docker-compose.yml` with next available port
5. Add test paths to root `pyproject.toml` `[tool.pytest.ini_options]`
6. Add mypy path to root `pyproject.toml` `[tool.mypy]`

---

## 11. Session History Log

```
[2026-03-06] Session 1 — Full discovery & planning
  - Ingested all project context (kickoff transcript, meeting notes, intern docs)
  - Established scope: AI/ML backend layer only
  - Identified team constraints: 2 effective builders
  - Mapped module dependencies, selected OCR + RAG as starters
  - Made 5 foundational technical decisions (FastAPI, RLS, pgvector, hybrid search, structure-aware chunking)
  - Created QUESTIONS_FOR_CLIENT.md (12 questions)
  - Created TECHNICAL_DECISIONS.md (14 decisions, 5 decided, 5 blocked)
  - Created SPRINT_0_PLAN.md (3 parallel tracks)
  - Built entire monorepo scaffold (40 files) as Sprint 0 Track A deliverable
  - Context limit reached — created this handoff document

[2026-03-06] Session 1 ended — Ready to resume with scaffold validation
```

---

## 12. Last Updated Timestamp

**Last Updated:** 2026-03-06
**Currently Working On:** Sprint 0 scaffold is BUILT but NOT YET TESTED
**Next Action:** Run `docker compose up` in `sena-ai/` and verify the scaffold works end-to-end (health check, DB connection, seed data, tests). Then initialize git repo.

---

## INSTRUCTIONS FOR THE AI

### Behavioral Framework
The user engaged this conversation with a specific operating model:
- **Act as an Elite Principal Software Architect** — challenge assumptions, don't be a yes-person
- **Ask one question at a time** during discovery (don't dump 10 questions at once)
- **Iterative decision-making** — present options with trade-offs, get confirmation, lock in, move forward
- **Async planning** — accumulate questions for client/senior, don't block on them. Continue working on what we can decide now
- **Everything is open** — no prior decision is sacred unless explicitly marked DECIDED in this document
- **Intern docs are not constraints** — the `docs/architecture/` files were created by an intern with limited experience. Treat as rough exploration only

### How to Use This Document
1. **Read this ENTIRE document** at the start of every new session
2. **Update it incrementally** as you work (don't rewrite from scratch)
3. **Move completed items** from "Future Roadmap" to "Completed Work"
4. **Add gotchas** to "Known Issues" as you discover them
5. **Append decisions** to "Technical Decisions" when made
6. **Update "Current Status"** whenever you switch tasks
7. **Log milestones** in "Session History Log"

### Context Files to Read (in order of importance)
If you need more detail than this document provides:
1. `CONTEXT_HANDOFF.md` (this file — always read first)
2. `CLAUDE.md` (project context for Claude Code sessions)
3. `TECHNICAL_DECISIONS.md` (full decision details with trade-offs)
4. `QUESTIONS_FOR_CLIENT.md` (what's blocked on client answers)
5. `SPRINT_0_PLAN.md` (detailed Sprint 0 definition with task assignments)
6. The actual code in `sena-ai/` (read if you need implementation details)
7. `AI Planning & R&D Kickoff Transcript.txt` (if you need original client conversation context)
