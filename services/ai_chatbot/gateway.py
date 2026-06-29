"""ai_chatbot gateway — one origin fronting Staff + Policy/Proc.

Serves a shell page (toggle + two pre-loaded iframes) and reverse-proxies both
existing Streamlit apps (and the policy FastAPI) under this single origin, so
they embed without cross-origin / X-Frame-Options trouble. Optionally spawns and
health-checks the children itself (MANAGE_CHILDREN).

Run:
    cd services/ai_chatbot && ./run.sh
    # or: uvicorn gateway:app --host 0.0.0.0 --port 8003
"""
import asyncio
import contextlib
import json
import logging
import os
import signal
import sys
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from langfuse import get_client, observe, propagate_attributes

import config
from conversation_store import store_user_message, store_ai_response, get_recent_messages
from gateway_extensions import ServiceOrchestrator, health_check_services
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

try:
    langfuse = get_client()
except Exception:
    langfuse = None  # type: ignore[assignment]
_SERVICE = "ai-chatbot"

# uvloop: 10-40% faster event loop (production default). Set the policy at import
# time, before any event loop is created. Must come AFTER `logger` is defined.
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    logger.info("[gateway] uvloop enabled (10-40% faster event loop)")
except ImportError:
    logger.warning("[gateway] uvloop not available, using standard asyncio")


class RouteRequest(BaseModel):
    """A user message plus the UI context that selects how it is routed.

    Routing is chip-driven: `context.category` decides the backend section. There
    is no free-text classification — a request with no category is out of scope.

    `context.category` values:
      • "shifts"    → staff service, STAFF section  (shifts, rosters, team)
      • "client"    → staff service, CLIENT section (participant info)
      • "policy"    → policy service                (organisational policy)
      • "procedure" → policy service                (compliance procedures)

    Multi-turn conversations (Phase 2):
      • `conversation_id` (UUID): Platform conversation ID. Pass same ID for follow-up turns.
      • `is_new_chat` (bool): Set `true` on first turn only. Gateway loads prior messages on follow-ups.
    """

    question: str = Field(
        ...,
        description="The user's message. May be empty when a chip is tapped with no "
                    "text — the section's default question is used.",
        examples=["What are my shifts this week?"],
    )
    context: dict = Field(
        default_factory=dict,
        description="UI context. REQUIRED fields:\n"
                    "• `category` (str): The tapped chip (shifts/client/policy/procedure)\n"
                    "• `conversation_id` (UUID): Platform conversation ID (create via POST /conversations)\n"
                    "\nOptional fields:\n"
                    "• `is_new_chat` (bool): Set true on first turn only, false/omit on follow-ups\n"
                    "• `session_id` (str): Session tracking\n"
                    "• `session_title` (str): Display name",
        examples=[
            {"category": "shifts", "conversation_id": "550e8400-e29b-41d4-a716-446655440000", "is_new_chat": True},
            {"category": "shifts", "conversation_id": "550e8400-e29b-41d4-a716-446655440000", "is_new_chat": False},
        ],
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "description": "Turn 1: New conversation (create via POST /conversations first)",
                    "question": "What are my shifts this week?",
                    "context": {
                        "category": "shifts",
                        "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
                        "is_new_chat": True
                    }
                },
                {
                    "description": "Turn 2: Follow-up (prior messages auto-loaded)",
                    "question": "Who will be working Monday?",
                    "context": {
                        "category": "shifts",
                        "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
                        "is_new_chat": False
                    }
                },
                {
                    "description": "Turn 3: Another follow-up (full context available)",
                    "question": "How many shifts do I have total?",
                    "context": {
                        "category": "shifts",
                        "conversation_id": "550e8400-e29b-41d4-a716-446655440000"
                    }
                },
            ]
        }
    }


async def _wait_healthy(client: httpx.AsyncClient, url: str, timeout: float) -> bool:
    """Poll a child health URL until it answers 2xx or the timeout elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = await client.get(url, timeout=3)
            if r.status_code < 400:
                return True
        except Exception:
            pass
        await asyncio.sleep(0.5)
    return False


async def _is_up(client: httpx.AsyncClient, url: str) -> bool:
    try:
        r = await client.get(url, timeout=2)
        return r.status_code < 400
    except Exception:
        return False


async def _pump_logs(name: str, proc: asyncio.subprocess.Process) -> None:
    """Stream a child's stdout/stderr to the gateway terminal (prefixed) AND to
    logs/<name>.log so you can `tail -f` a single service in isolation."""
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = config.LOGS_DIR / f"{name}.log"
    prefix = f"[{name}] ".encode()
    with open(log_path, "wb", buffering=0) as fh:
        async for line in proc.stdout:
            sys.stderr.buffer.write(prefix + line)
            sys.stderr.buffer.flush()
            fh.write(line)


async def _spawn_children(app: FastAPI) -> None:
    client: httpx.AsyncClient = app.state.client
    procs = []
    for spec in config.child_specs():
        # Reuse an already-running instance instead of double-spawning (avoids
        # port collisions when the service is started separately).
        if await _is_up(client, spec["health_url"]):
            print(f"[gateway] {spec['name']} already running — reusing", file=sys.stderr)
            procs.append({"name": spec["name"], "proc": None, "health_url": spec["health_url"]})
            continue

        # PYTHONUNBUFFERED so child logs stream live through the pipe (no buffering).
        env = {**os.environ, "PYTHONUNBUFFERED": "1", **(spec.get("env") or {})}
        print(f"[gateway] starting {spec['name']}: {' '.join(spec['argv'])}", file=sys.stderr)
        proc = await asyncio.create_subprocess_exec(
            *spec["argv"], cwd=spec["cwd"], env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        # Background task drains the child's output (prefixed + to a log file).
        asyncio.create_task(_pump_logs(spec["name"], proc))
        procs.append({"name": spec["name"], "proc": proc, "health_url": spec["health_url"]})
    app.state.children = procs

    # Health-gate so the shell only shows once children can serve.
    for child in procs:
        ok = await _wait_healthy(client, child["health_url"], config.CHILD_HEALTH_TIMEOUT)
        child["healthy_at_start"] = ok
        status = "ready" if ok else "TIMEOUT (continuing anyway)"
        print(f"[gateway] {child['name']} {status}", file=sys.stderr)


async def _terminate_children(app: FastAPI) -> None:
    for child in getattr(app.state, "children", []):
        proc = child["proc"]
        if proc is None or proc.returncode is not None:
            continue  # reused/already-exited — nothing to stop
        print(f"[gateway] stopping {child['name']} (pid {proc.pid})", file=sys.stderr)
        with contextlib.suppress(ProcessLookupError):
            proc.send_signal(signal.SIGTERM)
    for child in getattr(app.state, "children", []):
        proc = child["proc"]
        if proc is None:
            continue
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Shared pooled client = lower latency (connection reuse) for proxy + health.
    app.state.client = httpx.AsyncClient(timeout=httpx.Timeout(None), follow_redirects=False)
    app.state.children = []

    # Initialize service orchestrator for query routing.
    # NOTE: policy queries go to the policy FastAPI (POLICY_API_PORT, default 8000),
    # NOT the policy Streamlit UI (POLICY_PORT 8602). Pointing the adapter at 8602
    # causes ConnectError on /query/stream even though /health (checked on 8000) passes.
    staff_url = os.getenv("STAFF_ORIGIN", "http://127.0.0.1:8601")
    policy_url = os.getenv("POLICY_ORIGIN", "http://127.0.0.1:8000")
    jwt_secret = os.getenv("JWT_SECRET", "sena-local-qa-secret-change-in-prod")
    app.state.orchestrator = ServiceOrchestrator(
        staff_url=staff_url,
        policy_url=policy_url,
        jwt_secret=jwt_secret,
    )

    if config.MANAGE_CHILDREN:
        await _spawn_children(app)
    try:
        yield
    finally:
        if config.MANAGE_CHILDREN:
            await _terminate_children(app)
        with contextlib.suppress(Exception):
            await app.state.orchestrator.aclose()
        await app.state.client.aclose()


app = FastAPI(
    title="SENA ai_chatbot gateway",
    version="2.0.0",
    lifespan=lifespan,
    description=(
        "Single production entry point for the SENA assistant (Flutter mobile / "
        "React web).\n\n"
        "**The frontend integrates with THIS gateway only — never the staff or "
        "policy-proc services directly.** Those are internal, reachable solely over "
        "the private docker network; the gateway is the trust boundary that validates "
        "the JWT and routes each request.\n\n"
        "**One endpoint, chip-driven routing.** The frontend sends every message to "
        "`POST /ai-chatbot/route` with the tapped chip in `context.category`; the gateway "
        "routes it to the right backend section and streams the answer back as "
        "Server-Sent Events. There is no free-text classification — no chip means "
        "out of scope.\n\n"
        "**Sections are independent:** a `shifts` request can never reach client "
        "data, and vice-versa.\n\n"
        "**SSE events:** `meta` (routing) → `token` (answer) → `usage` "
        "(input/output token counts for the question) → `done`; or `error`."
    ),
    openapi_tags=[
        {"name": "Routing", "description": "Chip-driven query routing with SSE streaming."},
        {"name": "Health", "description": "Gateway + child-service health."},
    ],
    # nginx forwards /ai-chatbot/* to this app WITHOUT stripping the prefix, so the
    # docs / redoc / openapi must live under that same prefix to be reachable at
    # http://<host>/ai-chatbot/docs (etc.). The absolute prefixed openapi_url is
    # NOT touched by nginx's sub_filter (which only rewrites the bare /openapi.json).
    docs_url="/ai-chatbot/docs",
    redoc_url="/ai-chatbot/redoc",
    openapi_url="/ai-chatbot/openapi.json",
)


# ---- CORS ----
# Browser clients (React dashboard, local Vite dev) require CORS. Without this,
# the preflight `OPTIONS /ai-chatbot/route` gets 405 and the browser reports a
# CORS error. Server-to-server callers (Flutter, curl) are unaffected.
#
# Origins are an explicit allow-list (NOT "*") because requests carry an
# Authorization bearer header and we keep allow_credentials=True. Override or
# extend via the CORS_ALLOW_ORIGINS env var (comma-separated).
_default_cors_origins = [
    "https://dev-dashboard.isena.org",
    "https://dashboard.isena.org",
    "http://localhost:5173",
    "http://localhost:3000",
    "http://localhost:8080",
]
_env_cors_origins = [o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "").split(",") if o.strip()]
_cors_origins = _env_cors_origins or _default_cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],          # includes OPTIONS preflight + POST
    allow_headers=["*"],          # Authorization, Content-Type, etc.
    expose_headers=["*"],
)


# ---- Health ----

@app.get("/")
async def root():
    """The gateway is a JSON routing API now — no UI. Point clients at /ai-chatbot/route."""
    return JSONResponse({
        "service": "SENA ai_chatbot gateway",
        "endpoints": {"route": "POST /ai-chatbot/route", "health": "GET /ai-chatbot/healthz"},
    })


@app.get("/ai-chatbot/healthz")
async def healthz():
    # Probe staff + policy at the SAME origins the orchestrator routes to
    # (STAFF_ORIGIN / POLICY_ORIGIN) — correct whether they're in-process children
    # (localhost) or standalone containers (docker network). The endpoint itself
    # always returns 200 so the container's own liveness check passes; the body
    # reports each backend's true reachability for ops/debugging.

    # Primary: orchestrator-aware health check (uses actual routing origins)
    children = await health_check_services(app.state.orchestrator)

    # Supplement: ONLY in subprocess mode (MANAGE_CHILDREN=true) also probe the
    # in-process children. In network mode the real backends are the staff/policy
    # origins already checked above, so skip the child_specs probes — otherwise they
    # always report false (no localhost children exist) and clutter the response.
    if config.MANAGE_CHILDREN:
        client: httpx.AsyncClient = app.state.client
        for spec in config.child_specs():
            if spec["name"] not in children:
                try:
                    r = await client.get(spec["health_url"], timeout=2)
                    children[spec["name"]] = r.status_code < 400
                except Exception:
                    children[spec["name"]] = False

    return JSONResponse({"gateway": True, "children": children})


# HTTP Bearer security scheme — makes Swagger render the 🔒 "Authorize" button and a
# lock icon on this endpoint, so it's obvious a JWT MUST be sent. auto_error=False so
# our own explicit 401 below stays the source of truth (and the docs render cleanly).
bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="ISENA JWT",
    description="The ISENA access token from `POST /auth/ai/login`. Sent as `Authorization: Bearer <JWT>`.",
)


@app.post(
    "/ai-chatbot/route",
    tags=["Routing"],
    summary="Ask a question (JWT required) → streams the answer as SSE",
    response_description="Server-Sent Events: meta → token → usage → done (or error).",
    responses={
        200: {
            "description": (
                "**Server-Sent Events stream** (`Content-Type: text/event-stream`). Each "
                "line is `data: <json>`. **Four** event types are emitted, in this order:\n\n"
                "1. **`meta`** — routing decided (+ `session_id`, `conversation_id` if multi-turn):\n"
                "   `{\"type\":\"meta\",\"session_id\":\"sess-abc123\",\"conversation_id\":\"uuid\",\"routing\":{\"target_services\":[\"staff\"],\"routing_reason\":\"...\"}}`\n"
                "2. **`token`** — the answer text (one or more of these):\n"
                "   `{\"type\":\"token\",\"text\":\"You have 2 shifts this week...\"}`\n"
                "3. **`usage`** — Bedrock token counts for this question:\n"
                "   `{\"type\":\"usage\",\"input_tokens\":2496,\"output_tokens\":320}`\n"
                "4. **`done`** — stream finished:\n"
                "   `{\"type\":\"done\"}`\n\n"
                "On failure a single **`error`** event is sent instead of the above: "
                "`{\"type\":\"error\",\"text\":\"...\"}`."
            ),
            "content": {"text/event-stream": {"example": (
                'data: {"type": "meta", "session_id": "sess-abc123", "routing": {"target_services": ["staff"], '
                '"routing_reason": "Category \'shifts\' routed to staff."}}\n\n'
                'data: {"type": "token", "text": "You have 2 shifts this week: ..."}\n\n'
                'data: {"type": "usage", "input_tokens": 2496, "output_tokens": 320}\n\n'
                'data: {"type": "done"}\n\n'
            )}},
        },
        401: {"description": "Missing or invalid JWT — no `Authorization: Bearer <token>` header."},
    },
)
@observe(name="ai-chatbot-route", capture_input=False, capture_output=False)
async def route_query(
    req: RouteRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    """Route one chip-selected message to the right backend section and stream the reply.

    ### Auth — REQUIRED
    Send the ISENA JWT as **`Authorization: Bearer <JWT>`** (obtain it from
    `POST /auth/ai/login`). In Swagger, click **Authorize 🔒** and paste the token once.
    The gateway forwards it to the backend, which validates it. No token → **401**.

    ### Routing
    Decided by `context.category` (shifts / client / policy / procedure). No category →
    out of scope (the stream returns a single guidance message). Sections are
    independent — a `shifts` message cannot return client data.

    ### Response — SSE, 4 event types
    `meta` (routing) → `token` (answer, ×N) → `usage` (input/output tokens) → `done`.
    On error, a single `error` event instead. See the **200** response for each shape.
    """
    jwt_token = credentials.credentials if credentials else None
    if not jwt_token:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization bearer token (JWT)")
    orchestrator: ServiceOrchestrator = app.state.orchestrator

    if langfuse is not None:
        try:
            conv_id = (req.context or {}).get("conversation_id") or ""
            with propagate_attributes(session_id=conv_id):
                langfuse.update_current_span(
                    input={"question": req.question[:500], "category": (req.context or {}).get("category")},
                    metadata={"service": _SERVICE, "category": (req.context or {}).get("category")},
                )
        except Exception:
            pass

    async def event_stream():
        try:
            full_answer = []
            usage = {}
            conv_id = (req.context or {}).get("conversation_id")
            client: httpx.AsyncClient = app.state.client
            enriched_context = dict(req.context or {})

            # Validate conversation_id is provided (required for message storage and context)
            if not conv_id:
                raise ValueError(
                    "conversation_id is required in context. "
                    "Create one via POST /conversations, then pass it in all requests."
                )

            # Load prior messages for context injection (if follow-up turn)
            if conv_id and not enriched_context.get("is_new_chat"):
                prior_messages = await get_recent_messages(
                    conv_id, limit=5, jwt_token=jwt_token, client=client
                )
                if prior_messages:
                    enriched_context["message_history"] = prior_messages
                    logger.debug(f"Enriched context with {len(prior_messages)} prior messages")

            # Store user message (fire-and-forget, non-blocking)
            if conv_id:
                asyncio.create_task(
                    store_user_message(conv_id, req.question, jwt_token, client)
                )

            async for event in orchestrator.route_and_stream(
                question=req.question,
                jwt_token=jwt_token,
                context=enriched_context,
            ):
                if event.get("type") == "token":
                    full_answer.append(event.get("text", ""))
                elif event.get("type") == "usage":
                    usage = event
                elif event.get("type") == "done" and conv_id and full_answer:
                    # Store AI response (fire-and-forget, non-blocking)
                    asyncio.create_task(
                        store_ai_response(
                            conv_id, "".join(full_answer), usage, jwt_token, client
                        )
                    )

                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            logger.exception("Error in route_and_stream")
            yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            # Stream SSE events in real time — stop nginx/proxies from buffering the
            # response (X-Accel-Buffering is honoured by nginx per-response), and
            # stop any cache from holding it.
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.HOST, port=config.GATEWAY_PORT)
