"""SENA Casenote Monthly Report — FastAPI service.

**Flow**
1. Caller sends ``POST /casenote/monthly-report`` with a client ID, date range, and Bearer JWT.
2. Service fetches all client data from the SENA backend (``GET /ai/client-data``).
3. Sections 1–6 run in parallel via Bedrock; section 7 runs after (needs 3/4/5).
4. Section 5 automatically loads the previous month's trend for cross-month comparison.
5. Section 5 output is auto-saved to ``trends/{client_id}/{YYYY-MM}.json``.
6. Merged report saved as ``reports/{client_id}_report.md`` and returned as raw HTML.

**Port:** 8602
"""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import markdown as md_lib
import requests
from fastapi import FastAPI, Header, HTTPException, Security
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from auth import get_auth_headers, validate_jwt
from cleaner import clean
from config import API_BASE_URL, bedrock_runtime, MODEL_ID
from trend_store import get_previous_trend, list_trends, save_trend
import prompt as P

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
REPORTS_DIR = HERE / "reports"
MAX_TOKENS = 4096

_bearer = HTTPBearer(auto_error=False)

_TAGS = [
    {
        "name": "Report",
        "description": (
            "Generate a full 7-section NDIS Progress Summary Report for a client.\n\n"
            "Fetches client data from the SENA backend, runs all sections through "
            "AWS Bedrock (Claude Sonnet) in parallel, and returns raw HTML."
        ),
    },
    {
        "name": "Trend",
        "description": (
            "Store and retrieve monthly trend data (Section 5 output).\n\n"
            "Trend entries are **saved automatically** after every report generation. "
            "The previous month's trend is automatically injected into the next "
            "month's Section 5 prompt so the model can produce ↑ ↓ → comparisons.\n\n"
            "Use these endpoints to manually backfill history or inspect stored data."
        ),
    },
    {
        "name": "Health",
        "description": "Liveness probe for container orchestration and load balancers.",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    REPORTS_DIR.mkdir(exist_ok=True)
    yield


app = FastAPI(
    title="SENA Casenote Monthly Report API",
    version="1.0.0",
    description=__doc__,
    lifespan=lifespan,
    openapi_tags=_TAGS,
    swagger_ui_parameters={"defaultModelsExpandDepth": 2, "docExpansion": "list"},
)


# ── Request / response models ─────────────────────────────────────────────────

class ReportRequest(BaseModel):
    client_id: str = Field(
        ...,
        description="Client UUID from the SENA system.",
        examples=["0ce6359f-9138-4e05-b83b-6c39875f1828"],
    )
    date_from: str = Field(
        ...,
        description="Report start date in **YYYY-MM-DD** format. The month of this date is used as the reporting period.",
        examples=["2026-05-01"],
    )
    date_to: str = Field(
        ...,
        description="Report end date in **YYYY-MM-DD** format.",
        examples=["2026-05-31"],
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "client_id": "0ce6359f-9138-4e05-b83b-6c39875f1828",
                    "date_from": "2026-05-01",
                    "date_to": "2026-05-31",
                }
            ]
        }
    }


class TrendEntry(BaseModel):
    client_id: str = Field(..., description="Client UUID.")
    period: str = Field(..., description="Reporting month — YYYY-MM.", examples=["2026-05"])
    trend_text: str = Field(..., description="Section 5 (Trend Analysis) markdown output.")
    saved_at: str = Field(..., description="ISO-8601 UTC timestamp when this entry was saved.")


class TrendListResponse(BaseModel):
    client_id: str
    count: int = Field(..., description="Total number of stored trend entries for this client.")
    trends: list[TrendEntry] = Field(..., description="All entries, newest first.")


class TrendSaveResponse(BaseModel):
    status: str = Field(..., examples=["saved"])
    period: str = Field(..., examples=["2026-05"])
    file: str = Field(..., description="Server path where the trend JSON was written.")


class HealthResponse(BaseModel):
    status: str = Field(..., examples=["ok"])


# ── Internal helpers ──────────────────────────────────────────────────────────

def _fetch_client_data(client_id: str, date_from: str, date_to: str, token: str) -> dict:
    """Call GET /ai/client-data and return the inner data object.

    Raises ValueError if the backend returns a non-200 status or empty data.
    """
    url = f"{API_BASE_URL}/ai/client-data"
    params = {"clientId": client_id, "dateFrom": date_from, "dateTo": date_to}
    resp = requests.get(url, params=params, headers=get_auth_headers(token), timeout=30)
    if resp.status_code != 200:
        raise ValueError(f"Backend returned {resp.status_code}: {resp.text[:200]}")
    body = resp.json()
    data = body.get("data") or body
    if not data:
        raise ValueError("Backend returned empty data for this client / date range.")
    return data


def _normalize(section: dict | str) -> dict:
    if isinstance(section, dict):
        return section
    if isinstance(section, str) and section.strip():
        return {"system": "", "user": section}
    return {}


def _fill(text: str, subs: dict) -> str:
    for k, v in subs.items():
        text = text.replace(k, v)
    return text


def _build_subs(data: dict, section_outputs: dict[int, str]) -> dict:
    client = data.get("client", {})
    goals = client.get("ndisPlanGoals") or client.get("personalGoals") or []
    return {
        "{{CLIENT_JSON}}":    json.dumps(data, indent=2, ensure_ascii=False),
        "{{START_DATE}}":     str(data.get("dateFrom", "")),
        "{{END_DATE}}":       str(data.get("dateTo", "")),
        "{{NDIS_GOALS_LIST}}": ", ".join(goals) if isinstance(goals, list) else str(goals),
        "{{SECTION_3}}":      section_outputs.get(3, ""),
        "{{SECTION_4}}":      section_outputs.get(4, ""),
        "{{SECTION_5}}":      section_outputs.get(5, ""),
    }


def _call_bedrock(section: dict, subs: dict) -> tuple[str, dict]:
    system = section.get("system", "")
    user = _fill(section.get("user", ""), subs)
    resp = bedrock_runtime.converse(
        modelId=MODEL_ID,
        system=[{"text": system}] if system else [],
        messages=[{"role": "user", "content": [{"text": user}]}],
        inferenceConfig={"maxTokens": MAX_TOKENS},
    )
    text = ""
    for block in (resp.get("output") or {}).get("message", {}).get("content", []):
        if "text" in block:
            text += block["text"]
    return clean(text.strip()), resp.get("usage") or {}


async def _run_one(i: int, sec: dict, subs: dict, client_id: str) -> tuple[int, str]:
    logger.info("[%s] section %d → Bedrock", client_id, i)
    text, usage = await asyncio.to_thread(_call_bedrock, sec, subs)
    logger.info("[%s] section %d done  in=%d out=%d", client_id, i,
                usage.get("inputTokens", 0), usage.get("outputTokens", 0))
    return i, text


async def _generate_report(data: dict, client_id: str, current_period: str) -> str:
    """Run sections 1-6 in parallel, then section 7 (needs 3/4/5 context).

    Section 5 automatically receives the previous month's trend as extra context
    so the model can produce cross-month ↑ ↓ → arrows.
    Section 5 output is auto-saved to the trend store after completion.
    """
    sections: list[tuple[int, dict]] = []
    for i in range(1, 50):
        obj = getattr(P, f"section_{i}", None)
        if obj is None:
            continue
        sec = _normalize(obj)
        if "user" in sec:
            sections.append((i, sec))

    wave1 = [(i, sec) for i, sec in sections if i != 7]
    wave2 = [(i, sec) for i, sec in sections if i == 7]

    # Fetch previous month trend before wave 1 (used in section 5 context)
    prev = await asyncio.to_thread(get_previous_trend, client_id, current_period)
    prev_trend_text = prev["trend_text"] if prev else ""
    if prev_trend_text:
        logger.info("[%s] previous trend found for %s", client_id, prev["period"])
    else:
        logger.info("[%s] no previous trend — section 5 will be baseline month", client_id)

    base_subs = _build_subs(data, {})

    # Section 5 gets an augmented prompt that prepends the previous month's trend
    def _subs_for(i: int) -> dict:
        if i == 5 and prev_trend_text:
            s5 = dict(base_subs)
            s5["{{CLIENT_JSON}}"] = (
                f"PREVIOUS MONTH TREND (for cross-month comparison):\n"
                f"{prev_trend_text}\n\n"
                f"CURRENT MONTH DATA:\n{base_subs['{{CLIENT_JSON}}']}"
            )
            return s5
        return base_subs

    logger.info("[%s] wave 1: %d sections in parallel", client_id, len(wave1))
    results = await asyncio.gather(
        *[_run_one(i, sec, _subs_for(i), client_id) for i, sec in wave1]
    )
    section_outputs: dict[int, str] = dict(results)

    # Auto-save section 5 trend after wave 1
    if 5 in section_outputs:
        saved_at = datetime.now(timezone.utc).isoformat()
        await asyncio.to_thread(save_trend, client_id, current_period, section_outputs[5], saved_at)
        logger.info("[%s] trend saved for %s", client_id, current_period)

    for i, sec in wave2:
        logger.info("[%s] wave 2: section %d (uses 3/4/5 context)", client_id, i)
        _, text = await _run_one(i, sec, _build_subs(data, section_outputs), client_id)
        section_outputs[i] = text

    parts = [section_outputs[i] for i, _ in sections if i in section_outputs]
    merged_md = "\n\n---\n\n".join(parts)
    (REPORTS_DIR / f"{client_id}_report.md").write_text(merged_md + "\n", encoding="utf-8")
    logger.info("[%s] report saved", client_id)
    return md_lib.markdown(merged_md, extensions=["tables", "fenced_code"])


# ── Endpoints ─────────────────────────────────────────────────────────────────

def _token(creds: HTTPAuthorizationCredentials | None) -> str:
    return creds.credentials if creds else ""


@app.get(
    "/health",
    summary="Liveness probe",
    tags=["Health"],
    response_model=HealthResponse,
    responses={200: {"description": "Service is running."}},
)
async def health() -> HealthResponse:
    """Returns `{"status": "ok"}`. Use this to verify the service is up before sending reports."""
    return HealthResponse(status="ok")


@app.post(
    "/casenote/monthly-report",
    response_class=HTMLResponse,
    summary="Generate a 7-section NDIS monthly progress report",
    tags=["Report"],
    responses={
        200: {
            "description": (
                "Raw HTML of the full 7-section NDIS Progress Summary Report, ready to render in the browser.\n\n"
                "Sections included:\n"
                "1. Participant Information\n"
                "2. Introduction\n"
                "3. Strengths & Progress\n"
                "4. Risk Factors, Vulnerabilities & Barriers\n"
                "5. Trend Analysis Over Time\n"
                "6. Support Worker Approaches\n"
                "7. Recommendations & Intervention Strategies"
            ),
            "content": {
                "text/html": {
                    "example": (
                        "<h2>1. Participant Information</h2>"
                        "<ul><li><strong>Name:</strong> Michael Smith</li>"
                        "<li><strong>NDIS Number:</strong> 0004 3343 4000</li></ul>"
                        "<h2>2. Introduction</h2><p>...</p>"
                    )
                }
            },
        },
        401: {"description": "JWT is missing, expired, or cannot be decoded."},
        502: {"description": "SENA backend returned a non-200 response or empty data for this client/period."},
    },
)
async def monthly_report(
    req: ReportRequest,
    creds: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> HTMLResponse:
    """
    **What this does**

    1. Validates your Bearer JWT (expiry check — no round-trip to the auth server).
    2. Calls `GET /ai/client-data` on the SENA backend using your token to fetch all client data for the date range.
    3. Runs **sections 1–6 in parallel** through AWS Bedrock (Claude Sonnet `au.anthropic.claude-sonnet-4-6`).
    4. If a previous month's trend exists, it is automatically injected into Section 5 to produce ↑ ↓ → arrows.
    5. Runs **Section 7** after sections 3, 4, 5 are ready (it uses their output as context).
    6. Strips internal model reasoning/verification blocks from all output.
    7. Saves the merged report to `reports/{client_id}_report.md` on the server.
    8. Auto-saves Section 5 (Trend Analysis) to the trend store for next month's comparison.
    9. Returns the report as **raw HTML** — pass directly to `innerHTML` on the frontend.

    **Typical wall-clock time:** ~30–60 s (limited by slowest parallel Bedrock call).
    """
    token = _token(creds)
    valid, error_msg, _ = validate_jwt(token)
    if not valid:
        return HTMLResponse(f"<p>401 Unauthorized: {error_msg}</p>", status_code=401)

    try:
        data = await asyncio.to_thread(
            _fetch_client_data, req.client_id, req.date_from, req.date_to, token
        )
    except ValueError as exc:
        return HTMLResponse(f"<p>502 Backend error: {exc}</p>", status_code=502)

    current_period = req.date_from[:7]   # "2026-05-01" → "2026-05"
    html = await _generate_report(data, req.client_id, current_period)
    return HTMLResponse(content=html, status_code=200)


# ── Trend endpoints ───────────────────────────────────────────────────────────

class TrendSaveRequest(BaseModel):
    client_id: str = Field(
        ...,
        description="Client UUID from the SENA system.",
        examples=["0ce6359f-9138-4e05-b83b-6c39875f1828"],
    )
    period: str = Field(
        ...,
        description="Reporting month in **YYYY-MM** format.",
        examples=["2026-05"],
    )
    trend_text: str = Field(
        ...,
        description=(
            "Section 5 (Trend Analysis) markdown output to store for this month. "
            "This is the raw text returned by Bedrock for the trend section."
        ),
        examples=["## 5. Trend Analysis Over Time\n\n| Month | Avg Engagement Level | ..."],
    )

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "client_id": "0ce6359f-9138-4e05-b83b-6c39875f1828",
                "period": "2026-05",
                "trend_text": "## 5. Trend Analysis Over Time\n\n| Month | Avg Engagement Level | Volunteering/Community | Emotional Self-Regulation | Social Initiation |\n|-------|---------------------|------------------------|---------------------------|-------------------|\n| May 2026 | Moderate-High | 2 shifts | 100% *(est.)* | 2 interactions/week |\n\n**Visual Summary:** May 2026 is a baseline month.",
            }]
        }
    }


@app.post(
    "/casenote/trend/save",
    summary="Manually save a monthly trend entry",
    tags=["Trend"],
    response_model=TrendSaveResponse,
    responses={
        200: {"description": "Trend entry written to `trends/{client_id}/{period}.json`."},
        401: {"description": "JWT is missing, expired, or cannot be decoded."},
    },
)
async def trend_save(
    req: TrendSaveRequest,
    creds: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> TrendSaveResponse:
    """
    **When to use this**

    You normally do **not** need to call this endpoint — `POST /casenote/monthly-report`
    saves Section 5 automatically after every run.

    Use this endpoint to:
    - **Backfill** trend data for months before the service was deployed.
    - **Override** a stored trend entry (e.g. after a report was corrected).

    The saved entry will be picked up automatically the next time a report is generated
    for this client in a subsequent month.
    """
    token = _token(creds)
    valid, error_msg, _ = validate_jwt(token)
    if not valid:
        raise HTTPException(status_code=401, detail=error_msg)

    saved_at = datetime.now(timezone.utc).isoformat()
    path = await asyncio.to_thread(save_trend, req.client_id, req.period, req.trend_text, saved_at)
    return TrendSaveResponse(status="saved", period=req.period, file=str(path))


@app.get(
    "/casenote/trend/{client_id}",
    summary="Get all stored trend entries for a client",
    tags=["Trend"],
    response_model=TrendListResponse,
    responses={
        200: {"description": "All trend entries for this client, newest first."},
        401: {"description": "JWT is missing, expired, or cannot be decoded."},
        404: {"description": "No trend history found for this client ID."},
    },
)
async def trend_list(
    client_id: str,
    creds: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> TrendListResponse:
    """
    Returns every stored monthly trend entry for the given client, sorted **newest first**.

    Each entry contains:
    - `period` — the month (YYYY-MM)
    - `trend_text` — the Section 5 markdown saved for that month
    - `saved_at` — UTC timestamp of when it was saved

    **How the trend store is used**

    When `POST /casenote/monthly-report` runs for period `2026-06`, the service looks up
    the most recent entry before June (e.g. `2026-05`) and prepends it to Section 5's
    prompt context. This allows the model to output cross-month comparison arrows
    (↑ ↓ →) without needing full historical data in the client JSON.
    """
    token = _token(creds)
    valid, error_msg, _ = validate_jwt(token)
    if not valid:
        raise HTTPException(status_code=401, detail=error_msg)

    entries = await asyncio.to_thread(list_trends, client_id)
    if not entries:
        raise HTTPException(status_code=404, detail=f"No trend data found for client '{client_id}'.")
    return TrendListResponse(client_id=client_id, count=len(entries), trends=entries)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8602, log_level="info")
