"""MOBILE case-note monthly summary API (support-worker token).

Source: GET /mobile/organization-member/case-note/get-all-data (the authenticated
member's own notes WITH full content). No server-side date filter, so notes are
filtered to the requested month locally. Produces a real narrative summary of note
CONTENT. Runs independently on port 8603.

    POST /casenote/monthly-summary
    Header: Authorization: Bearer <support-worker jwt>
    Body:   { organizationId, memberId, month (1-12), year }

Note: get-all-data is member-self — it returns the TOKEN holder's notes. memberId in
the body is echoed back for traceability; the token determines whose notes are read.
A non-support-worker token gets 403 here (use the /org API instead).
"""
import asyncio
import calendar
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from auth import validate_jwt
from dates import note_in_month
from casenote_client import fetch_member_notes, NotSupportWorkerError, CaseNoteAPIError
from bedrock_client import call_bedrock

logger = logging.getLogger("casenote.mobile")


class MonthlySummaryRequest(BaseModel):
    organizationId: str = Field(..., min_length=1)
    memberId: str = Field(..., min_length=1)
    month: int = Field(..., ge=1, le=12)
    year: int = Field(..., ge=2000, le=2100)


class MonthlySummaryResponse(BaseModel):
    mode: str
    period: str
    organizationId: str
    memberId: str
    noteCount: int
    totalNotesFetched: int
    summary: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
    logger.info("casenote-monthly-mobile starting up")
    yield
    logger.info("casenote-monthly-mobile shutting down")


app = FastAPI(title="SENA Case-Note Monthly Summary (Mobile)", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "casenote-monthly-mobile"}


@app.post("/casenote/monthly-summary", response_model=MonthlySummaryResponse)
async def monthly_summary(req: MonthlySummaryRequest, authorization: str = Header(None)) -> MonthlySummaryResponse:
    token = (authorization or "").replace("Bearer ", "").strip()
    ok, err, _ = validate_jwt(token)
    if not ok:
        raise HTTPException(status_code=401, detail=err)

    # Blocking I/O (requests + sync boto3) runs in a worker thread so the event
    # loop stays free to serve other requests (FastAPI best practice).
    return await asyncio.to_thread(_build_summary, token, req)


def _build_summary(token: str, req: MonthlySummaryRequest) -> MonthlySummaryResponse:
    period = f"{calendar.month_name[req.month]} {req.year}"

    try:
        all_notes = fetch_member_notes(token)
    except NotSupportWorkerError:
        raise HTTPException(status_code=403,
                            detail="Token is not authorized as a support worker. Use the /org API instead.")
    except CaseNoteAPIError as e:
        raise HTTPException(status_code=e.status_code or 502, detail=f"Case-note fetch failed: {e}")

    notes = [n for n in all_notes if note_in_month(n, req.year, req.month)]
    summary = _summarize(notes, period) if notes else (
        f"No case notes found for {period}. There is nothing to summarise for this period."
    )

    return MonthlySummaryResponse(
        mode="mobile_content",
        period=f"{req.year}-{req.month:02d}",
        organizationId=req.organizationId,
        memberId=req.memberId,
        noteCount=len(notes),
        totalNotesFetched=len(all_notes),
        summary=summary,
    )


def _summarize(notes: list[dict], period: str) -> str:
    blocks = [f"--- Case note {i} ---\n{json.dumps(n, ensure_ascii=False, default=str)[:4000]}"
              for i, n in enumerate(notes[:60], 1)]
    notes_text = "\n\n".join(blocks)
    system_prompt = (
        f"You are summarising a support worker's NDIS case notes for {period}. You are given the "
        "raw JSON of each note (field names may vary). Produce a concise Markdown monthly summary, "
        "omitting any section with no supporting content: **Overview** (how many notes, which "
        "clients, shape of the month), **Recurring themes**, **Client progress & concerns** "
        "(grouped by client), **Incidents & risks** (incident/safety/handover content), "
        "**Follow-ups** (outstanding actions). Be factual and grounded ONLY in the provided notes. "
        "Do not invent details. If the notes are sparse, say so plainly."
    )
    messages = [{"role": "user", "content": [{"text":
        f"Here are {len(notes)} case notes for {period}:\n\n{notes_text}\n\nWrite the monthly summary."}]}]
    return call_bedrock(messages, system_prompt, use_guardrail=False) or \
        "Unable to generate a summary (the model returned no output)."


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8603, log_level="info")
