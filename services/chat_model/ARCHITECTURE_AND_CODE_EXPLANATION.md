# Chat Model Service - Architecture & Implementation Guide

## Table of Contents
1. [Architecture Overview](#architecture-overview)
2. [Design Patterns](#design-patterns)
3. [Request Flow](#request-flow)
4. [Key Components](#key-components)
5. [Setup & Running](#setup--running)
6. [Data Layer](#data-layer)
7. [Extending the Service](#extending-the-service)
8. [Performance & Scaling](#performance--scaling)

---

## Architecture Overview

### Layered Architecture

```
┌─────────────────────────────────────────────┐
│ HTTP Layer (FastAPI)                        │
│ Routes, auth, rate limiting, validation     │
├─────────────────────────────────────────────┤
│ Business Logic Layer                        │
│ ChatService: RAG chains, session mgmt       │
├─────────────────────────────────────────────┤
│ Data Access Layer                           │
│ AuditRepo, RedisChatMessageHistory, pgvector│
├─────────────────────────────────────────────┤
│ External Services                           │
│ Gemini LLM, PostgreSQL, Redis, Google API   │
└─────────────────────────────────────────────┘
```

### Technology Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| API Framework | FastAPI 0.104+ | REST endpoints, async/await, dependency injection |
| Session Store | Redis 5.0+ | Distributed, ephemeral conversation storage |
| Vector Store | PostgreSQL + pgvector | Multi-instance document embeddings, RLS support |
| ORM | SQLAlchemy 2.0+ (asyncio) | Async database operations, audit log persistence |
| RAG Framework | LangChain 0.1+ | Chain composition, memory management, retriever abstraction |
| LLM | Google Gemini API | Primary inference engine, streaming support |
| Embeddings | Google Embeddings API | Text → vector conversion for semantic search |
| Rate Limiter | slowapi | Per-IP request throttling |
| Logging | structlog + python-json-logger | Structured JSON output for observability |

### Concurrency Model

Service uses async/await throughout (asyncio event loop). Single process handles 100+ concurrent requests:

```python
# Non-blocking I/O means event loop switches between requests
async def send_message(session_id, user_message, tenant_id):
    # While waiting for LLM (2-5 sec), other requests continue
    response = await self.conversational_rag_chain.ainvoke(...)
    
    # While waiting for Redis, other requests continue
    history = await self._get_session_history(...)
    
    # While audit log is written, other requests continue
    await audit_repo.append_audit(...)
```

**Throughput implication:** 1000 concurrent users × 2-5 sec latency = 2000-5000 processes (traditional sync) vs ~10 processes (async).

---

## Design Patterns

### 1. Singleton Pattern with Lifespan Management

Initialize expensive resources once, share across request lifecycle.

**Implementation in `main.py`:**

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup — executed once when app starts
    configure_logging(settings.log_level)
    await initialize_db_engine()
    redis_client = await initialize_redis_client()
    await initialize_chat_service(redis_client)
    
    yield  # App services requests here
    
    # Shutdown — executed once when app stops
    await shutdown_redis_client()
    await shutdown_db_engine()
```

**Usage in `api/deps.py`:**

```python
_chat_service: Optional[ChatService] = None

async def initialize_chat_service(redis_client: redis.Redis):
    global _chat_service
    _chat_service = ChatService(redis_client)

async def get_chat_service() -> ChatService:
    if _chat_service is None:
        raise RuntimeError("ChatService not initialized")
    return _chat_service

# In route handler:
@app.post("/v1/chat/message")
async def chat_message(
    chat_service: ChatService = Depends(get_chat_service)
):
    # FastAPI calls get_chat_service(), receives singleton
    response = await chat_service.send_message(...)
```

**Rationale:** Gemini API initialization + model loading takes 1-2 seconds. Doing this per-request adds 1-2 sec overhead per user. Singleton pattern amortizes this cost across all requests.

### 2. Dependency Injection with Request Scoping

```python
# Process-scoped singleton
async def get_chat_service() -> ChatService:
    return _chat_service

# Request-scoped
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with _async_session_maker() as session:
        yield session
        # Session automatically closed after endpoint completes

# Header-based context
async def auth_context_dependency(
    x_tenant_id: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
    x_user_role: Optional[str] = Header(None),
) -> AuthContext:
    # Extract and validate auth info
    return AuthContext(...)
```

FastAPI DI system handles injection:

```python
@app.post("/v1/chat/message")
async def chat_message(
    request: ChatRequest,
    auth: AuthContext = Depends(auth_context_dependency),
    chat_service: ChatService = Depends(get_chat_service),
    db_session: AsyncSession = Depends(get_db_session),
):
    # All injected by FastAPI
```

### 3. Exception Hierarchy with Specific Handling

```python
class ChatServiceError(Exception):
    """Base exception — service-level failures"""
    pass

class LLMError(ChatServiceError):
    """LLM API failures (Gemini)"""
    pass

class VectorStoreError(ChatServiceError):
    """Vector store failures (pgvector)"""
    pass

class SessionError(ChatServiceError):
    """Session/Redis failures"""
    pass
```

Route handlers map exceptions to HTTP status codes:

```python
try:
    response = await chat_service.send_message(...)
except LLMError as e:
    # Service dependency down
    raise HTTPException(status_code=503, detail=f"LLM error: {e}")
except SessionError as e:
    # Transient issue
    raise HTTPException(status_code=500, detail=f"Session error: {e}")
except ChatServiceError as e:
    # Catch-all for service errors
    raise HTTPException(status_code=500, detail=f"Service error: {e}")
```

### 4. Retrieval-Augmented Generation (RAG) Pattern

LangChain orchestrates a multi-step chain:

```
User Message
    ↓
[History-Aware Reformulation]
  Input:  chat_history + user question
  Output: standalone question (contextual)
    ↓
[Document Retrieval]
  Search pgvector for semantically similar docs
  Return top-k matches
    ↓
[LLM Invocation]
  Input:  retrieved docs + chat history + question
  Output: grounded answer
    ↓
[Session Persistence]
  Store exchange in Redis
    ↓
[Audit Logging]
  Insert record in PostgreSQL
```

Implementation in `services/chat_service.py`:

```python
def _setup_rag_chain(self):
    # Reformulate question based on history
    contextualize_prompt = ChatPromptTemplate.from_messages([
        ("system", "Formulate a standalone question from chat history."),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{input}"),
    ])
    
    # Ground answer in documents
    qa_prompt = ChatPromptTemplate.from_messages([
        ("system", """Use context to answer. If unsure, say 'I don't know'."""),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{input}"),
    ])
    
    # Compose chains
    history_aware_retriever = create_history_aware_retriever(
        self.llm, self.retriever, contextualize_prompt
    )
    question_answer_chain = create_stuff_documents_chain(self.llm, qa_prompt)
    rag_chain = create_retrieval_chain(history_aware_retriever, question_answer_chain)
    
    # Add message history wrapper
    self.conversational_rag_chain = RunnableWithMessageHistory(
        rag_chain,
        self._get_session_history,
        input_messages_key="input",
        history_messages_key="chat_history",
        output_messages_key="answer",
    )
```

### 5. Multi-Tenant Isolation Strategy

Isolation enforced at three levels:

**Level 1: HTTP Header Validation**
```python
# Header proves tenant identity
X-Tenant-ID: 550e8400-e29b-41d4-a716-446655440000
```

**Level 2: Session Key Scoping**
```python
scoped_session_id = f"{tenant_id}:{session_id}"
# "550e8400-...:abc123" — uniquely identifies tenant's session
session = redis_client.get(scoped_session_id)
```

**Level 3: Database RLS (Row-Level Security)**
```sql
ALTER TABLE chat_audit_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON chat_audit_logs
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
```

Even if attacker knows another tenant's session ID, accessing it requires:
1. Valid auth token for their own tenant
2. Session key includes their tenant_id
3. Database policy prevents cross-tenant reads

---

## Request Flow

### POST /v1/chat/message — Complete Flow

**Request:**
```http
POST /v1/chat/message HTTP/1.1
Content-Type: application/json
X-Tenant-ID: 550e8400-e29b-41d4-a716-446655440000
X-User-ID: 550e8400-e29b-41d4-a716-446655440001
X-User-Role: user

{
  "message": "What is NDIS?",
  "session_id": "optional-uuid"
}
```

**Step 1: Route Handler (api/routes.py)**

```python
@router.post("/v1/chat/message")
async def chat_message(
    request: ChatRequest,
    auth: AuthContext = Depends(auth_context_dependency),
    chat_service: ChatService = Depends(get_chat_service),
):
    # Pydantic validates request schema
    # DI provides auth context from headers
    # DI provides singleton ChatService
```

**Step 2: Auth Extraction (api/deps.py)**

```python
# Auth mode: dev_header (default) or jwt
if settings.auth_mode == "jwt":
    # Validate RS256 signature, issuer, audience
    payload = jwt.decode(token, settings.jwt_public_key_pem, ...)
    tenant_id = UUID(payload["tenant_id"])
else:
    # Extract from headers
    tenant_id = UUID(x_tenant_id)
    user_id = UUID(x_user_id)
```

**Step 3: Rate Limiting (slowapi)**

```python
@limiter.limit("20/minute")  # Per IP address
async def chat_message(...):
    # If exceeded, returns 429 Too Many Requests
```

**Step 4: Session ID Generation**

```python
session_id = request.session_id or str(uuid4())
```

**Step 5: Call ChatService.send_message() (services/chat_service.py)**

```python
async def send_message(self, session_id: str, user_message: str, tenant_id: str):
    # Scope session to tenant
    scoped_session_id = f"{tenant_id}:{session_id}"
    
    # Invoke RAG chain (async, non-blocking)
    response = await self.conversational_rag_chain.ainvoke(
        {"input": user_message},
        config={"configurable": {"session_id": scoped_session_id}}
    )
    
    # Get conversation history from Redis
    history = self._get_session_history(scoped_session_id)
    conversation = [
        Message(role=msg.type, content=msg.content)
        for msg in history.messages
    ]
    
    return response["answer"], conversation
```

**Inside ainvoke (LangChain execution):**

1. **Retriever** — Search pgvector for similar documents
   ```python
   # Vector similarity search
   docs = self.retriever.invoke({"input": user_message})
   ```

2. **History Reformulator** — Rewrite question with context
   ```python
   # Input: chat_history + "What is NDIS?"
   # Output: "What is NDIS?" (reformulated using history)
   ```

3. **QA Chain** — Invoke LLM with docs + history
   ```python
   # Gemini receives:
   # - Context: [retrieved documents]
   # - Chat history: [prior exchanges]
   # - Question: [current question]
   # Generates grounded answer
   ```

4. **Session Storage** — RedisChatMessageHistory auto-saves
   ```python
   # LangChain automatically stores exchange in Redis
   # Key: "{tenant_id}:{session_id}"
   # Value: ChatMessageHistory with all messages
   ```

**Step 6: Audit Logging (repositories/audit_repo.py)**

```python
audit_repo = AuditRepo(db_session)
await audit_repo.append_audit(
    tenant_id=auth.tenant_id,
    user_id=auth.user_id,
    session_id=session_id,
    question=request.message,
    answer="".join(full_response),
    doc_ids=[],
    latency_ms=int((time.time() - start_time) * 1000),
)
```

Insert into PostgreSQL `chat_audit_logs` table (append-only).

**Step 7: Build Response (api/routes.py)**

```python
return ChatResponse(
    session_id=session_id,
    response=response["answer"],
    conversation=conversation,
)
```

JSON response:
```json
{
  "session_id": "abc123",
  "response": "NDIS is the National Disability Insurance Scheme...",
  "conversation": [
    {"role": "user", "content": "What is NDIS?"},
    {"role": "assistant", "content": "NDIS is..."}
  ]
}
```

**Step 8: Structured Logging (core/logging.py)**

```python
logger.info(
    "chat.message",
    tenant_id=str(auth.tenant_id),
    session_id=session_id,
    msg_len=len(request.message),
    latency_ms=int((time.time() - start_time) * 1000),
)
```

Stdout output (JSON):
```json
{
  "event": "chat.message",
  "timestamp": "2026-05-05T12:34:56.789Z",
  "level": "info",
  "tenant_id": "550e8400-...",
  "session_id": "abc123",
  "msg_len": 14,
  "latency_ms": 2850
}
```

**Total flow:** HTTP request → Auth → Rate limit → Validation → ChatService → Vector search → LLM → Redis → PostgreSQL → Audit log → Response → Structured log

---

## Key Components

### ChatService (`services/chat_service.py`)

Core business logic. Manages LLM, embeddings, vector store, RAG chains.

**Initialization:**
```python
def __init__(self, redis_client: redis.Redis):
    self.redis_client = redis_client
    self.api_key = settings.gemini_api_key
    self.model_id = settings.gemini_model_id
    
    # Initialize LLM
    self.llm = ChatGoogleGenerativeAI(
        model=self.model_id,
        temperature=0.3,  # Deterministic (0=deterministic, 1=creative)
        google_api_key=self.api_key,
    )
    
    # Initialize embeddings (for vector search)
    self.embeddings = GoogleGenerativeAIEmbeddings(
        model="models/embedding-001",
        google_api_key=self.api_key
    )
    
    # Load or create vector store
    self.vectorstore = self._get_vectorstore()
    self.retriever = self.vectorstore.as_retriever(
        search_kwargs={"k": 6}  # Return top 6 documents
    )
    
    # Setup RAG chain
    self._setup_rag_chain()
```

**Key methods:**

1. `_get_vectorstore()` — Manage pgvector index
   - Checks if documents already indexed
   - If not, loads from `data/` folder, creates embeddings, stores in PostgreSQL
   - Returns PostgresVectorStore instance

2. `send_message()` — Synchronous wrapper around ainvoke()
   - Calls `conversational_rag_chain.ainvoke()`
   - Returns (answer, conversation_history)

3. `astream_message()` — Generator for streaming
   - Yields tokens from `astream_events()`
   - Used by `/v1/chat/stream` endpoint

4. `get_session()` — Retrieve session history from Redis
   - Returns conversation or None if expired

5. `clear_session()` — Delete session from Redis
   - Force clears conversation history

### AuditRepo (`repositories/audit_repo.py`)

Handles audit log persistence.

```python
async def append_audit(
    self,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    session_id: str,
    question: str,
    answer: str,
    doc_ids: list[str],
    latency_ms: int,
    tokens_in: int = 0,
    tokens_out: int = 0,
) -> ChatAuditLog:
    row = ChatAuditLog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
        question=question,
        answer=answer,
        doc_ids=doc_ids,
        latency_ms=latency_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        created_at=datetime.now(timezone.utc),
    )
    self._s.add(row)
    await self._s.commit()
    await self._s.refresh(row)
    return row
```

Insert always succeeds (append-only). Queries use indexes on `tenant_id`, `user_id`, `session_id`.

### Database Layer (`models/db.py`)

SQLAlchemy ORM models using Mapped syntax (Python 3.12+):

```python
class ChatAuditLog(Base):
    __tablename__ = "chat_audit_logs"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), 
        primary_key=True, 
        default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), 
        nullable=False, 
        index=True  # For tenant queries
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), 
        nullable=False, 
        index=True
    )
    session_id: Mapped[str] = mapped_column(
        String(36), 
        nullable=False, 
        index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    doc_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        nullable=False, 
        default=datetime.utcnow
    )
```

### Settings Configuration (`core/settings.py`)

Pydantic BaseSettings for environment-based configuration:

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SENA_AI_",
        case_sensitive=False
    )
    
    # Service
    chat_model_port: int = Field(default=8085, alias="CHAT_MODEL_PORT")
    redis_url: str = Field(alias="REDIS_URL")
    ai_db_url: str = Field(default="postgresql+asyncpg://...", alias="AI_DB_URL")
    
    # LLM
    gemini_api_key: str = Field(alias="GEMINI_API_KEY")
    gemini_model_id: str = Field(default="gemini-3.1-flash-live-preview")
    
    # Auth
    auth_mode: str = Field(default="dev_header", alias="AUTH_MODE")
    jwt_issuer: str | None = Field(default=None)
    jwt_audience: str | None = Field(default=None)
    jwt_public_key_pem: str | None = Field(default=None)
    
    # Session
    redis_session_ttl_seconds: int = Field(default=86400, alias="REDIS_SESSION_TTL_SECONDS")
    
    # Rate limit
    rate_limit_per_minute: int = Field(default=20, alias="RATE_LIMIT_PER_MINUTE")
    
    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
```

Validation happens on instantiation. All values from environment or defaults.

---

## Setup & Running

### Prerequisites

- Python 3.12+
- PostgreSQL 14+ with pgvector extension
- Redis 6.0+
- Google Gemini API key

### 1. Install Dependencies

```bash
cd services/chat_model
pip install -e ".[dev]"
```

Installs from `pyproject.toml`:
- FastAPI, uvicorn
- Pydantic, pydantic-settings
- SQLAlchemy (asyncio), asyncpg
- Langchain + plugins
- structlog, python-json-logger
- pytest, mypy, ruff (dev)

### 2. Configure Environment

Create `.env`:
```bash
SENA_AI_GEMINI_API_KEY=your-key-here
SENA_AI_REDIS_URL=redis://localhost:6379
SENA_AI_AI_DB_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/ai_db
```

### 3. Initialize Database

```bash
# Start PostgreSQL (if using Docker)
docker-compose up -d

# Create schema
alembic upgrade head
```

Alembic creates `chat_audit_logs` table with pgvector extension setup.

### 4. Prepare Documents

```bash
mkdir -p data/
# Add .txt or .md files to data/ folder
# Service loads on startup
```

### 5. Run Service

```bash
uvicorn src.chat_model.main:create_app --factory --reload --port 8085
```

Output:
```
INFO:     Uvicorn running on http://127.0.0.1:8085
INFO:     Application startup complete
```

First startup loads documents → creates embeddings → stores in pgvector (1-2 min).

### 6. Verify

```bash
# Health check
curl http://localhost:8085/health

# Chat message (with auth headers)
curl -X POST http://localhost:8085/v1/chat/message \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: 550e8400-e29b-41d4-a716-446655440000" \
  -H "X-User-ID: 550e8400-e29b-41d4-a716-446655440001" \
  -H "X-User-Role: user" \
  -d '{"message": "What is NDIS?"}'
```

---

## Data Layer

### Vector Store (pgvector)

Stores embeddings alongside documents in PostgreSQL.

**Schema:**
```sql
CREATE TABLE langchain_pg_embedding (
    id BIGSERIAL PRIMARY KEY,
    collection_id UUID,
    embedding VECTOR(768),  -- Google embeddings are 768-dim
    document TEXT,
    cmetadata JSONB,
    created_at TIMESTAMP
);

CREATE INDEX ON langchain_pg_embedding 
USING ivfflat (embedding vector_cosine_ops)
WHERE collection_id = ...;
```

**Search query:**
```sql
SELECT document, distance
FROM langchain_pg_embedding
WHERE collection_id = $1
ORDER BY embedding <-> query_embedding  -- Cosine distance
LIMIT 6;
```

LangChain abstracts this via `vectorstore.similarity_search()`.

### Session Storage (Redis)

Stores conversation history per session.

**Key structure:**
```
{tenant_id}:{session_id}
"550e8400-...:abc123"
```

**Value:**
```python
# RedisChatMessageHistory stores as JSON-serialized messages
[
    HumanMessage(content="What is NDIS?"),
    AIMessage(content="NDIS is..."),
    HumanMessage(content="More details?"),
    AIMessage(content="..."),
]
```

**TTL:** 86400 seconds (1 day). Redis auto-deletes expired keys.

### Audit Trail (PostgreSQL)

Append-only immutable log.

**Indexes:**
- `tenant_id` — Fast tenant queries
- `user_id` — Fast user activity queries
- `session_id` — Fast session lookups

**RLS Policy:**
```sql
ALTER TABLE chat_audit_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON chat_audit_logs
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
```

Database enforces isolation at SQL level.

---

## Extending the Service

### Add New Endpoint

1. **Schema** (`models/schemas.py`):
```python
class MyRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)

class MyResponse(BaseModel):
    result: str
```

2. **Method** (`services/chat_service.py`):
```python
async def process_query(self, query: str) -> str:
    # Business logic
    return result
```

3. **Route** (`api/routes.py`):
```python
@router.post("/v1/chat/process")
async def process(
    request: MyRequest,
    auth: AuthContext = Depends(auth_context_dependency),
    chat_service: ChatService = Depends(get_chat_service),
):
    try:
        result = await chat_service.process_query(request.query)
        return MyResponse(result=result)
    except ChatServiceError as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### Modify LLM Configuration

In `services/chat_service.py`, line ~65:
```python
self.llm = ChatGoogleGenerativeAI(
    model="gemini-1.5-pro",  # Change model
    temperature=0.7,  # Higher = more creative
    google_api_key=self.api_key,
)
```

### Adjust Retrieval

In `services/chat_service.py`, line ~84:
```python
self.retriever = self.vectorstore.as_retriever(
    search_kwargs={"k": 3}  # Return 3 docs instead of 6
)
```

### Add Environment Variable

1. **Settings** (`core/settings.py`):
```python
my_config: str = Field(default="default", alias="MY_CONFIG")
```

2. **Usage:**
```python
from chat_model.core.settings import settings
value = settings.my_config
```

3. **Documentation** (`.env.example`):
```
SENA_AI_MY_CONFIG=my_value
```

### Add Database Migration

```bash
alembic revision --autogenerate -m "Add new column"
```

Edit generated migration (`migrations/versions/XXXX_*.py`):
```python
def upgrade():
    op.add_column('chat_audit_logs', sa.Column('new_col', sa.String(255)))

def downgrade():
    op.drop_column('chat_audit_logs', 'new_col')
```

Update ORM (`models/db.py`):
```python
class ChatAuditLog(Base):
    # ...
    new_col: Mapped[str] = mapped_column(String(255), nullable=True)
```

---

## Performance & Scaling

### Profiling a Request

```bash
# Enable slow query logging in PostgreSQL
# Enable slow LLM call logging in structlog
LOG_LEVEL=DEBUG python -m uvicorn src.chat_model.main:create_app --factory
```

### Bottlenecks & Solutions

| Bottleneck | Cause | Solution |
|-----------|-------|----------|
| LLM latency (2-5s) | Gemini API | Use faster model, adjust temperature |
| Vector search slow | Too many documents, poor indexes | Partition by tenant, increase k in chunk_size |
| Redis latency | Network round-trip | Use local Redis or Redis Cluster |
| PostgreSQL audit insert slow | Lock contention | Use batch inserts, separate audit replica |
| High memory usage | Large document corpus | Implement pagination, document pruning |

### Scaling Horizontally

Service is stateless (state in Redis, pgvector, PostgreSQL):

```
┌─────────────┐
│ Load        │
│ Balancer    │
└──────┬──────┘
       │
       ├─ Instance 1 (port 8085)
       ├─ Instance 2 (port 8085)
       ├─ Instance 3 (port 8085)
       └─ Instance N (port 8085)
       
       ↓ All share
       
       ┌─────────────────┐
       │ Redis           │
       │ (session store) │
       └─────────────────┘
       
       ┌──────────────────────┐
       │ PostgreSQL ai-db     │
       │ (pgvector + audit)   │
       └──────────────────────┘
```

Add instances without code changes. Load balancer distributes requests.

### Monitoring Key Metrics

From structured logs (JSON output):

```bash
# Average latency per tenant
jq -s 'group_by(.tenant_id) | map({tenant: .[0].tenant_id, avg_latency: (map(.latency_ms) | add / length)})' logs.jsonl

# Error rate
jq 'select(.level == "error") | .event' logs.jsonl | sort | uniq -c

# Top slow queries
jq 'select(.latency_ms > 5000) | {session: .session_id, latency: .latency_ms, msg_len: .msg_len}' logs.jsonl | sort -k3 -rn | head -20
```

### Load Testing

Using k6:

```bash
npm install -g k6

# Create script (scripts/load_test.js)
import http from 'k6/http';
import { check } from 'k6';

export let options = {
  vus: 100,      // 100 concurrent users
  duration: '30s',
};

export default function () {
  let payload = JSON.stringify({
    message: 'What is NDIS?',
  });
  
  let params = {
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': '550e8400-e29b-41d4-a716-446655440000',
      'X-User-ID': '550e8400-e29b-41d4-a716-446655440001',
      'X-User-Role': 'user',
    },
  };
  
  let res = http.post('http://localhost:8085/v1/chat/message', payload, params);
  check(res, {
    'status is 200': (r) => r.status === 200,
    'latency < 5s': (r) => r.timings.duration < 5000,
  });
}

# Run
k6 run scripts/load_test.js
```

Output shows throughput, latency percentiles, error rate.

---

## Summary

**Chat Model Service** is a production async RAG chatbot:

- **Stateless** — All state in Redis, PostgreSQL, pgvector
- **Async** — Non-blocking I/O, handles 1000+ concurrent users
- **Multi-tenant** — Isolation at HTTP, application, database layers
- **Observable** — Structured JSON logging, audit trail
- **Extensible** — Clean separation of concerns (routes, service, repos, models)
- **Scalable** — Horizontal scaling via load balancing
