"""ORG case-note monthly summary API (admin / org token).

Source: GET /organization/case-note/get-all (register — METADATA only, no note text).
So this API produces a STATUS roll-up (completed vs pending per client), not a
content summary. Runs independently on port 8602.

    POST /casenote/monthly-summary
    Header: Authorization: Bearer <admin jwt>
    Body:   { organizationId, memberId, month (1-12), year }
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
from dates import month_window
from casenote_client import fetch_register, CaseNoteAPIError
from bedrock_client import call_bedrock

logger = logging.getLogger("casenote.org")


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
    shiftCount: int
    withNoteCount: int
    pendingCount: int
    reportedTotal: int
    summary: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
    logger.info("casenote-monthly-org starting up")
    yield
    logger.info("casenote-monthly-org shutting down")


app = FastAPI(title="SENA Case-Note Monthly Summary (Org)", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "casenote-monthly-org"}


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
    dfrom, dto = month_window(req.year, req.month)

    try:
        rows, reported_total = fetch_register(token, req.memberId, dfrom, dto)
    except CaseNoteAPIError as e:
        raise HTTPException(status_code=e.status_code or 502, detail=f"Case-note register fetch failed: {e}")

    with_note = sum(1 for r in rows if r.get("caseNoteId"))
    summary = _summarize(rows, period) if rows else (
        f"No case notes found for {period}. There is nothing to summarise for this period."
    )

    return MonthlySummaryResponse(
        mode="org_register",
        period=f"{req.year}-{req.month:02d}",
        organizationId=req.organizationId,
        memberId=req.memberId,
        shiftCount=len(rows),
        withNoteCount=with_note,
        pendingCount=len(rows) - with_note,
        reportedTotal=reported_total,
        summary=summary,
    )


def _summarize(rows: list[dict], period: str) -> str:
    rows_text = json.dumps(rows[:240], ensure_ascii=False, default=str)[:32000]
    system_prompt = (
        f"You are producing a case-note STATUS roll-up for {period}. You are given case-note "
        "REGISTER records (metadata only — no note text). Each has clientName, shiftName, shift "
        "dates, status (completed/pending/reviewed) and caseNoteId (null = no note). Produce a "
        "concise Markdown roll-up: **Totals** (shifts, notes completed/reviewed vs pending/missing), "
        "**By client** (per-client counts, clients with missing notes), **Compliance flags** (shifts "
        "still pending a note). Be factual and grounded ONLY in the records. State explicitly that "
        "this is a status roll-up based on metadata, not a summary of note content."
    )
    messages = [{"role": "user", "content": [{"text":
        f"Here are the register records for {period}:\n\n{rows_text}\n\nWrite the status roll-up."}]}]
    return call_bedrock(messages, system_prompt, use_guardrail=False) or \
        "Unable to generate a roll-up (the model returned no output)."


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8602, log_level="info")
