"""FastAPI wrapper for the SENA Staff service.

Two INDEPENDENT sections, one per UI chip — they never share tools or data:

  • POST /staff/query/stream   → "Check Shifts" chip   (shifts, rosters, team)
  • POST /client/query/stream  → "Client's information" chip (participant data)

A staff-section request can never reach client data, and vice-versa: each section
is handed only its own tool set (see services/staff/tools/registry.py). The
frontend (chip-selector) decides which endpoint to call — there is no free-text
classification here.

Every endpoint streams Server-Sent Events (SSE):

    data: {"type": "meta",  "session_id": "..."}                  # routing acknowledged
    data: {"type": "token", "text": "..."}                        # the answer (one block today)
    data: {"type": "usage", "input_tokens": N, "output_tokens": N}# Bedrock tokens for this question
    data: {"type": "done"}                                        # stream finished
    data: {"type": "error", "text": "..."}                        # something went wrong
"""
import asyncio
import json
import logging
from typing import AsyncGenerator, Optional

from fastapi import FastAPI, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from router import process_query
from auth import authenticate_with_jwt

logger = logging.getLogger(__name__)

# ── OpenAPI metadata ─────────────────────────────────────────────────────────────
TAGS_METADATA = [
    {"name": "Staff", "description": "Worker's own work — shifts, rosters, shift "
                                     "details, and the staff/team directory."},
    {"name": "Client", "description": "Participant data — client list, details, "
                                      "support workers, guardians, search/filter."},
    {"name": "Health", "description": "Liveness probe for orchestration."},
]

app = FastAPI(
    title="SENA Staff API",
    version="2.0.0",
    description=__doc__,
    openapi_tags=TAGS_METADATA,
)


# ── Request / response models ────────────────────────────────────────────────────
class QueryRequest(BaseModel):
    """A user question for one section, plus optional session context."""

    question: str = Field(
        ...,
        min_length=1,
        description="The user's natural-language question for THIS section.",
        examples=["What are my shifts this week?"],
    )
    session_id: Optional[str] = Field(
        None,
        description="Conversation id to continue a thread. Omit/null to start fresh.",
        examples=["3f9c1a7e-staff-001"],
    )
    session_title: Optional[str] = Field(
        None,
        description="Optional human-readable title for a new conversation.",
        examples=["This week's roster"],
    )
    is_new_chat: bool = Field(
        False,
        description="True to begin a brand-new conversation (clears prior turns).",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "question": "What are my shifts this week?",
                    "session_id": None,
                    "session_title": "This week's roster",
                    "is_new_chat": True,
                }
            ]
        }
    }


# SSE is a streaming media type, not a JSON body — these examples document the
# event shapes for the Swagger UI "Responses" section.
_SSE_OK_EXAMPLE = (
    'data: {"type": "meta", "session_id": "staff-session"}\n\n'
    'data: {"type": "token", "text": "Here are your shifts this week: ..."}\n\n'
    'data: {"type": "usage", "input_tokens": 2496, "output_tokens": 320}\n\n'
    'data: {"type": "done"}\n\n'
)
_SSE_RESPONSES = {
    200: {
        "description": "SSE stream of meta → token → usage → done (or an error event). "
                       "The `usage` event reports Bedrock input/output tokens for the question.",
        "content": {"text/event-stream": {"example": _SSE_OK_EXAMPLE}},
    }
}


# ── Helpers ──────────────────────────────────────────────────────────────────────
def _sse(event: dict) -> str:
    """Encode one dict as an SSE `data:` frame."""
    return f"data: {json.dumps(event)}\n\n"


async def _error_stream(text: str) -> AsyncGenerator[str, None]:
    """One-shot error event stream (validation failures, before work starts)."""
    yield _sse({"type": "error", "text": text})


def _scoped_stream(req: QueryRequest, authorization: Optional[str], scope: str) -> StreamingResponse:
    """Build the SSE StreamingResponse for a section.

    Validation (question + auth) happens HERE, before the generator is created —
    yielding an error mid-stream after headers are sent corrupts the chunked body
    (``incomplete chunked read`` on the client). So bad requests return a clean,
    single-event error stream instead.
    """
    question = (req.question or "").strip()
    token = (authorization or "").replace("Bearer ", "").strip()
    print(f"Staff API [{scope}]: query received: {question!r}", flush=True)

    if not question:
        return StreamingResponse(_error_stream("Question is required"),
                                 media_type="text/event-stream")
    if not token:
        return StreamingResponse(_error_stream("Missing Authorization bearer token"),
                                 media_type="text/event-stream")
    if not authenticate_with_jwt(token):
        return StreamingResponse(_error_stream("Invalid or expired JWT token"),
                                 media_type="text/event-stream")

    async def event_stream() -> AsyncGenerator[str, None]:
        # process_query is synchronous (and slow: a multi-step agent loop). Run it
        # in a worker thread so the event loop stays free for other requests.
        # `usage` is populated in-place with this question's Bedrock token counts.
        usage: dict = {}
        print(f"[STREAM:{scope}] calling process_query (in thread)...", flush=True)
        try:
            result = await asyncio.to_thread(process_query, question, scope, usage)
        except Exception as exc:  # noqa: BLE001 — must never crash the stream
            import traceback
            print(f"[STREAM:{scope} ERR] {type(exc).__name__}: {exc}", flush=True)
            traceback.print_exc()
            yield _sse({"type": "error", "text": "Sorry, something went wrong. Please try again."})
            return

        yield _sse({"type": "meta", "session_id": req.session_id or f"{scope}-session"})
        if isinstance(result, str) and result:
            # Sent whole — splitting on whitespace would collapse markdown
            # tables/lists onto one line.
            yield _sse({"type": "token", "text": result})
        # Token usage for THIS question (input + output), emitted before done.
        yield _sse({
            "type": "usage",
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
        })
        yield _sse({"type": "done"})
        print(f"[STREAM:{scope}] complete", flush=True)

    return StreamingResponse(event_stream(), media_type="text/event-stream", status_code=200)


# ── Endpoints ────────────────────────────────────────────────────────────────────
@app.get("/health", tags=["Health"], summary="Liveness probe")
async def health_check() -> dict:
    """Return ``{"status": "ok"}`` when the service is up."""
    return {"status": "ok"}


@app.post(
    "/staff/query/stream",
    tags=["Staff"],
    summary="Ask a STAFF-section question (shifts, rosters, team)",
    response_description="SSE stream of meta → token → done.",
    responses=_SSE_RESPONSES,
)
async def staff_query_stream(req: QueryRequest, authorization: str = Header(None)):
    """Answer a question using ONLY staff/shift tools.

    Scope: shifts, rosters, shift details, the staff/team directory, plus general
    identity tools (who am I, current time, my organisations). Client data is
    **not** reachable from here.

    **Example**

    ```
    POST /staff/query/stream
    Authorization: Bearer <JWT>
    {"question": "What are my shifts this week?", "is_new_chat": true}
    ```
    """
    return _scoped_stream(req, authorization, scope="staff")


@app.post(
    "/client/query/stream",
    tags=["Client"],
    summary="Ask a CLIENT-section question (participant info)",
    response_description="SSE stream of meta → token → done.",
    responses=_SSE_RESPONSES,
)
async def client_query_stream(req: QueryRequest, authorization: str = Header(None)):
    """Answer a question using ONLY client tools.

    Scope: client list, client details, support workers, guardians, and
    search/filter, plus general identity tools. Shift/staff data is **not**
    reachable from here.

    **Example**

    ```
    POST /client/query/stream
    Authorization: Bearer <JWT>
    {"question": "Who are my clients?", "is_new_chat": true}
    ```
    """
    return _scoped_stream(req, authorization, scope="client")


@app.post(
    "/query/stream",
    tags=["Staff"],
    summary="[Deprecated] Legacy staff endpoint — use /staff/query/stream",
    deprecated=True,
    responses=_SSE_RESPONSES,
)
async def legacy_query_stream(req: QueryRequest, authorization: str = Header(None)):
    """Backwards-compatible alias that maps to the **staff** section.

    Kept so existing callers (e.g. the CLI test harness) keep working. New
    integrations should call `/staff/query/stream` or `/client/query/stream`.
    """
    return _scoped_stream(req, authorization, scope="staff")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8601, log_level="info")
