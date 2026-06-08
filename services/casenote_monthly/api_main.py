"""SENA Casenote Monthly Report — FastAPI service.

**Flow**
1. Caller sends ``POST /casenote/monthly-report`` with a client ID, date range, and Bearer JWT.
2. Service fetches all client data from the SENA backend (``GET /ai/client-data``).
3. Runs 7 NDIS-report sections sequentially through AWS Bedrock (Claude Sonnet).
4. Strips thinking/verification blocks from model output.
5. Saves the merged report as ``reports/{client_id}_report.md``.
6. Returns the report as **raw HTML** ready for the frontend to render.

**Port:** 8602
"""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import markdown as md_lib
import requests
from fastapi import FastAPI, Header
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from auth import get_auth_headers, validate_jwt
from cleaner import clean
from config import API_BASE_URL, bedrock_runtime, MODEL_ID
import prompt as P

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
REPORTS_DIR = HERE / "reports"
MAX_TOKENS = 4096


@asynccontextmanager
async def lifespan(app: FastAPI):
    REPORTS_DIR.mkdir(exist_ok=True)
    yield


app = FastAPI(
    title="SENA Casenote Monthly Report",
    version="1.0.0",
    description=__doc__,
    lifespan=lifespan,
)


# ── Request / response models ─────────────────────────────────────────────────

class ReportRequest(BaseModel):
    """What the caller must send to generate a monthly NDIS report."""

    client_id: str = Field(
        ...,
        description="Client UUID from the SENA system.",
        examples=["0ce6359f-9138-4e05-b83b-6c39875f1828"],
    )
    date_from: str = Field(
        ...,
        description="Report start date  (YYYY-MM-DD).",
        examples=["2026-05-01"],
    )
    date_to: str = Field(
        ...,
        description="Report end date  (YYYY-MM-DD).",
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


def _generate_report(data: dict, client_id: str) -> str:
    """Run all prompt sections against client data. Blocking — called via to_thread."""
    sections: list[tuple[int, dict]] = []
    for i in range(1, 50):
        obj = getattr(P, f"section_{i}", None)
        if obj is None:
            continue
        sec = _normalize(obj)
        if "user" in sec:
            sections.append((i, sec))

    logger.info("[%s] %d section(s) to run", client_id, len(sections))

    section_outputs: dict[int, str] = {}
    parts: list[str] = []

    for i, sec in sections:
        logger.info("[%s] section %d → Bedrock", client_id, i)
        subs = _build_subs(data, section_outputs)
        text, usage = _call_bedrock(sec, subs)
        section_outputs[i] = text
        parts.append(text)
        logger.info(
            "[%s] section %d done  in=%d out=%d",
            client_id, i,
            usage.get("inputTokens", 0), usage.get("outputTokens", 0),
        )

    merged_md = "\n\n---\n\n".join(parts)
    report_path = REPORTS_DIR / f"{client_id}_report.md"
    report_path.write_text(merged_md + "\n", encoding="utf-8")
    logger.info("[%s] saved → %s", client_id, report_path)

    return md_lib.markdown(merged_md, extensions=["tables", "fenced_code"])


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get(
    "/health",
    summary="Liveness probe",
    tags=["Health"],
)
async def health() -> dict:
    """Returns ``{"status": "ok"}`` when the service is running."""
    return {"status": "ok"}


@app.post(
    "/casenote/monthly-report",
    response_class=HTMLResponse,
    summary="Generate a monthly NDIS progress report",
    description=(
        "Fetches all client data from the SENA backend for the given date range, "
        "runs 7 AI-generated NDIS report sections via AWS Bedrock, and returns "
        "the full report as **raw HTML**.\n\n"
        "The report is also saved to `reports/{client_id}_report.md` on the server.\n\n"
        "**Authorization:** pass a valid SENA Bearer JWT in the `Authorization` header."
    ),
    tags=["Report"],
    responses={
        200: {
            "description": "Raw HTML of the merged 7-section NDIS progress report.",
            "content": {"text/html": {"example": "<h2>1. Participant Information</h2><p>...</p>"}},
        },
        401: {"description": "Missing or invalid JWT token."},
        502: {"description": "SENA backend returned an error for the given client / date range."},
    },
)
async def monthly_report(
    req: ReportRequest,
    authorization: str | None = Header(
        None,
        description="Bearer JWT from SENA login.  Format: `Bearer <token>`",
    ),
) -> HTMLResponse:
    """
    **Steps:**
    1. Validates the Bearer JWT locally (expiry check).
    2. Calls `GET /ai/client-data` on the SENA backend to retrieve client data.
    3. Runs all 7 NDIS report sections through AWS Bedrock (Claude Sonnet).
    4. Saves the merged report as `reports/{client_id}_report.md`.
    5. Returns the report as raw HTML.

    **Example request body:**
    ```json
    {
        "client_id": "0ce6359f-9138-4e05-b83b-6c39875f1828",
        "date_from": "2026-05-01",
        "date_to":   "2026-05-31"
    }
    ```
    """
    token = (authorization or "").removeprefix("Bearer ").strip()
    valid, error_msg, _ = validate_jwt(token)
    if not valid:
        return HTMLResponse(f"<p>401 Unauthorized: {error_msg}</p>", status_code=401)

    try:
        data = await asyncio.to_thread(
            _fetch_client_data, req.client_id, req.date_from, req.date_to, token
        )
    except ValueError as exc:
        return HTMLResponse(f"<p>502 Backend error: {exc}</p>", status_code=502)

    html = await asyncio.to_thread(_generate_report, data, req.client_id)
    return HTMLResponse(content=html, status_code=200)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8602, log_level="info")
