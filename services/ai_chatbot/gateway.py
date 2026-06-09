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
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import JSONResponse, StreamingResponse

import config
from gateway_extensions import ServiceOrchestrator
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

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
    """

    question: str = Field(
        ...,
        description="The user's message. May be empty when a chip is tapped with no "
                    "text — the section's default question is used.",
        examples=["What are my shifts this week?"],
    )
    context: dict = Field(
        default_factory=dict,
        description="UI context. Must include `category` (the tapped chip). May also "
                    "carry session_id / session_title / is_new_chat.",
        examples=[{"category": "shifts", "is_new_chat": True}],
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"question": "What are my shifts this week?",
                 "context": {"category": "shifts", "is_new_chat": True}},
                {"question": "Who are my clients?",
                 "context": {"category": "client", "is_new_chat": True}},
                {"question": "What is the leave policy?",
                 "context": {"category": "policy", "is_new_chat": True}},
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
        "**One endpoint, chip-driven routing.** The frontend sends every message to "
        "`POST /api/route` with the tapped chip in `context.category`; the gateway "
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
)


# ---- Health ----

@app.get("/")
async def root():
    """The gateway is a JSON routing API now — no UI. Point clients at /api/route."""
    return JSONResponse({
        "service": "SENA ai_chatbot gateway",
        "endpoints": {"route": "POST /api/route", "health": "GET /healthz"},
    })


@app.get("/healthz")
async def healthz():
    client: httpx.AsyncClient = app.state.client
    results = {}
    for spec in config.child_specs():
        try:
            r = await client.get(spec["health_url"], timeout=2)
            results[spec["name"]] = r.status_code < 400
        except Exception:
            results[spec["name"]] = False
    return JSONResponse({"gateway": True, "children": results})


@app.post(
    "/api/route",
    tags=["Routing"],
    summary="Route a chip-selected message and stream the answer (SSE)",
    response_description="text/event-stream of meta → token → done (or error).",
    responses={
        200: {
            "description": "SSE stream. Each line is `data: <json>`.",
            "content": {"text/event-stream": {"example": (
                'data: {"type": "meta", "routing": {"target_services": ["staff"], '
                '"routing_reason": "Category \'shifts\' routed to staff."}}\n\n'
                'data: {"type": "token", "text": "Here are your shifts this week: ..."}\n\n'
                'data: {"type": "usage", "input_tokens": 2496, "output_tokens": 320}\n\n'
                'data: {"type": "done"}\n\n'
            )}},
        },
        401: {"description": "Missing or invalid Authorization bearer token."},
    },
)
async def route_query(
    req: RouteRequest,
    authorization: str = Header(None, description="Bearer <JWT> — the ISENA token from POST /auth/ai/login."),
):
    """Route one chip-selected message to the right backend section and stream the reply.

    **Auth:** `Authorization: Bearer <JWT>` (the ISENA token). The gateway forwards
    it to the backend, which validates it.

    **Routing:** decided by `context.category` (shifts / client / policy /
    procedure). No category → out of scope (the stream returns a single guidance
    message). Sections are independent — a `shifts` message cannot return client data.

    **Example**

    ```
    POST /api/route
    Authorization: Bearer <JWT>
    {"question": "What are my shifts this week?", "context": {"category": "shifts"}}
    ```
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    jwt_token = authorization.removeprefix("Bearer ")
    orchestrator: ServiceOrchestrator = app.state.orchestrator

    async def event_stream():
        try:
            async for event in orchestrator.route_and_stream(
                question=req.question,
                jwt_token=jwt_token,
                context=req.context or {},
            ):
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
