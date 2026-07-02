"""SENA Casenote Monthly Report — FastAPI service.

**Flow**
1. Caller sends ``POST /casenote/monthly-report`` with a client ID, date range, and Bearer JWT.
2. Service fetches all client data from the SENA backend (``GET /ai/client-data``).
3. Sections 1–6 run in parallel via Bedrock; section 7 runs after (needs 3/4/5).
4. Section 5 automatically loads the previous month's trend for cross-month comparison.
5. Section 5 output is auto-saved to ``trends/{client_id}/{YYYY-MM}.json``.
6. Merged report saved as ``reports/{client_id}_report.md`` and returned as raw HTML.

**Port:** 8602

**Performance:** Uses uvloop (if available), ThreadPoolExecutor, and async/await for max speed.
"""
import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import markdown as md_lib
import requests
from fastapi import Depends, FastAPI, Header, HTTPException, Security
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

# Use uvloop for faster async event loop (10-4x faster than default)
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass  # Fall back to default event loop

from langfuse import observe, get_client

from outbound_sign import sign_headers
from rsa_auth import verify_rsa
from bedrock_retry import converse_with_retry, sum_usage
from cleaner import clean
from config import API_BASE_URL, bedrock_runtime, MODEL_ID
from linter import lint
from stats import build_risk_register, compute_stats, extract_milestones, extract_quotes
from trend_store import get_previous_month_stats, get_previous_trend, list_trends, save_month_stats, save_trend
import prompt as P

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

langfuse = get_client()
# Distinct from bedrock_client.py's "casenote_monthly" tag — this is the
# per-section report generation loop in api_main.py's _call_bedrock, a
# separate call path from that module's functions.
_SERVICE = "casenote_monthly"

HERE = Path(__file__).resolve().parent

# Anti-hallucination guards: the LLM NEVER receives raw arrays it could miscount.
# It receives only Python-computed facts + a SIZE-BOUNDED sample of narrative text.
# These bounds keep the payload constant whether the period is monthly or yearly.
EVIDENCE_CHAR_BUDGET = 12_000   # total chars of case-note narrative excerpts sent to LLM
EXCERPT_FIELD_CHARS = 320       # per-field truncation for each case note
MAX_MILESTONES = 15             # cap Python-extracted milestones passed to LLM
MAX_QUOTES = 15                 # cap Python-extracted quotes passed to LLM
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
    # Create thread pool for CPU-bound tasks (stats, linting, markdown conversion)
    # Use 4 workers; adjust based on CPU cores if needed
    app.state.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="sena-worker-")
    yield
    # Cleanup
    app.state.executor.shutdown(wait=True)


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
        pattern=r"^[A-Za-z0-9_-]{1,64}$",  # used in file paths — no separators/dots allowed
        description="Client UUID from the SENA system.",
        examples=["0ce6359f-9138-4e05-b83b-6c39875f1828"],
    )
    organization_id: str = Field(
        ...,
        description="Organization UUID from the SENA system.",
        examples=["org-123e4567-e89b-12d3-a456-426614174000"],
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

def _fetch_client_data(client_id: str, organization_id: str, date_from: str, date_to: str, page: int = 1) -> dict:
    """Call GET /ai/client-data and return the inner data object.

    Raises ValueError if the backend returns a non-200 status or empty data.
    """
    url = f"{API_BASE_URL}/ai/client-data"
    params = {"clientId": client_id, "organizationId": organization_id, "dateFrom": date_from, "dateTo": date_to, "page": page}
    # Authenticate as the trusted AI service: sign with our RSA private key
    # (platform verifies with our public key). No per-user JWT is forwarded.
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        **sign_headers(),  # X-AI-Timestamp + X-AI-Signature (GET → empty body)
    }
    resp = requests.get(url, params=params, headers=headers, timeout=30)
    if resp.status_code != 200:
        raise ValueError(f"Backend returned {resp.status_code}: {resp.text[:200]}")
    body = resp.json()
    data = body.get("data") or body
    if not data:
        raise ValueError("Backend returned empty data for this client / date range.")
    return data


def _fetch_client_data_all(
    client_id: str,
    organization_id: str,
    date_from: str,
    date_to: str,
    max_pages: int = None  # No hard limit (handles quarterly/yearly data)
) -> dict:
    """Fetch ALL pages of client data, merging day lists and deduping by date.

    Pagination signals (spec: loop while page < totalPages; tolerate hasNext):
    - continues while EITHER hasNext is true OR totalPages says more pages remain
    - stops on an empty page (guards against a backend stuck on hasNext=true)
    - hard cap max_pages prevents runaway loops against a misbehaving backend
    """
    all_days = []
    pagination_info = None
    client_info = None
    page_num = 0
    max_pages = max_pages or 999  # Effectively unlimited, but guard against infinite loops

    logger.info(f"[{client_id}] Starting pagination (unlimited pages)")

    for page_num in range(1, max_pages + 1):
        try:
            data = _fetch_client_data(client_id, organization_id, date_from, date_to, page=page_num)
        except ValueError as e:
            logger.warning(f"[{client_id}] Pagination stopped at page {page_num}: {e}")
            break

        # Collect client info on first page
        if page_num == 1 and data.get("client"):
            client_info = data["client"]

        # Merge days
        days_key = "days" if "days" in data else "data"
        page_days = data.get(days_key) or []
        all_days.extend(page_days)

        # Track pagination
        pagination_info = data.get("pagination", {})
        total_pages = pagination_info.get("totalPages", 1)
        has_next = pagination_info.get("hasNext", False)

        logger.info(f"[{client_id}] Page {page_num}/{total_pages}: fetched {len(page_days)} day records (total: {len(all_days)})")

        # Empty page → nothing more to gain, even if the backend claims otherwise
        if not page_days and page_num > 1:
            logger.warning(f"[{client_id}] Page {page_num} returned no day records — stopping pagination")
            break

        # More pages if EITHER signal says so (some backends send only totalPages)
        if not has_next and page_num >= total_pages:
            logger.info(f"[{client_id}] Pagination complete: {page_num} pages, {len(all_days)} total day records")
            break
    else:
        logger.error(f"[{client_id}] Pagination hit max_pages={max_pages} without a natural stop — data may be incomplete")

    # Dedupe by date (keep first occurrence) + log size
    seen = set()
    deduped = []
    for day in all_days:
        day_date = day.get("date") or day.get("bucketDate", "")
        if day_date and day_date in seen:
            logger.warning(f"[{client_id}] Duplicate date in pagination: {day_date}, skipping")
            continue
        if day_date:
            seen.add(day_date)
        deduped.append(day)

    logger.info(f"[{client_id}] Data size: {len(all_days)} days raw → {len(deduped)} days deduped")

    return {"data": deduped, "client": client_info, "pagination": pagination_info or {}}


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


def _build_case_note_excerpts(days: list[dict]) -> list[dict]:
    """Return a SIZE-BOUNDED sample of case-note narrative text for qualitative colour.

    Anti-hallucination design:
      • Only narrative text fields are included — NEVER the countable structured arrays.
      • Most-recent-first, capped by EVIDENCE_CHAR_BUDGET, so quarterly/yearly periods
        produce the same bounded payload as a month (no truncation, no token blow-up).
      • The LLM cannot count sessions/incidents from this — those live in metrics only.
    """
    excerpts: list[dict] = []
    used = 0
    # Most recent days first — a progress report cares most about the latest period.
    for day in sorted(days, key=lambda d: d.get("date") or d.get("bucketDate") or "", reverse=True):
        day_date = day.get("date") or day.get("bucketDate") or ""
        for note in day.get("caseNotes") or []:
            if not isinstance(note, dict):
                continue

            def _txt(key: str) -> str:
                v = note.get(key)
                return v[:EXCERPT_FIELD_CHARS] if isinstance(v, str) else ""

            fields = {
                "summary":   _txt("summaryOfShift"),
                "skills":    _txt("activitiesAndSkill"),
                "wellbeing": _txt("wellbeingAndBehaviour"),
                "outcomes":  _txt("outcomesAndProgress"),
                "safety":    _txt("safetyAndHealth"),
            }
            fields = {k: v for k, v in fields.items() if v.strip()}
            if not fields:
                continue
            size = sum(len(v) for v in fields.values())
            if used + size > EVIDENCE_CHAR_BUDGET:
                return excerpts
            used += size
            excerpts.append({"date": day_date, **fields})
    return excerpts


def _build_evidence(data: dict, stats: dict) -> str:
    """Build the curated, size-bounded evidence payload sent to the LLM.

    Contains ONLY: client profile, Python-computed metrics, Python-extracted
    milestones/quotes/risk-register, and a bounded sample of narrative text.
    The raw shifts[]/incidents[]/full caseNotes[] arrays are deliberately excluded —
    the model cannot miscount data it never receives.
    """
    days = data.get("days") or data.get("data") or []
    client = data.get("client", {})

    all_feedback = [f for day in days for f in (day.get("shiftFeedback") or [])]
    all_incidents = [i for day in days for i in (day.get("incidents") or [])]
    all_rps = [r for day in days for r in (day.get("restrictivePractices") or [])]
    all_complaints = [c for day in days for c in (day.get("clientComplaints") or [])]

    evidence = {
        "clientProfile": {
            "name":          client.get("name") or client.get("clientName"),
            "age":           client.get("age"),
            "diagnosis":     client.get("diagnosis"),
            "location":      client.get("location"),
            "ndisNumber":    client.get("ndisNumber"),
            "goals":         client.get("ndisPlanGoals") or client.get("personalGoals") or [],
            "supportWorkers": client.get("formalSupports") or client.get("supportWorkers") or [],
        },
        "metrics":      stats,
        "milestones":   extract_milestones(days)[:MAX_MILESTONES],
        "quotes":       extract_quotes(all_feedback)[:MAX_QUOTES],
        "riskRegister": build_risk_register(all_incidents, all_rps, all_complaints),
        "caseNoteExcerpts": _build_case_note_excerpts(days),
        "_rules": (
            "ALL counts, totals, percentages and trends are in `metrics` — copy them "
            "verbatim, never recalculate. `milestones`, `quotes` and `riskRegister` are "
            "the ONLY permissible sources for those items. `caseNoteExcerpts` is a bounded "
            "qualitative SAMPLE for narrative colour only — never count or total it, and "
            "never infer period-wide figures from it."
        ),
    }
    return json.dumps(evidence, indent=2, ensure_ascii=False)


def _build_subs(data: dict, section_outputs: dict[int, str], stats: dict | None = None) -> dict:
    client = data.get("client", {})
    goals = client.get("ndisPlanGoals") or client.get("personalGoals") or []
    stats = stats or {}

    return {
        "{{CLIENT_JSON}}":    _build_evidence(data, stats),
        "{{START_DATE}}":     str(data.get("dateFrom", "")),
        "{{END_DATE}}":       str(data.get("dateTo", "")),
        "{{NDIS_GOALS_LIST}}": ", ".join(goals) if isinstance(goals, list) else str(goals),
        "{{SECTION_3}}":      section_outputs.get(3, ""),
        "{{SECTION_4}}":      section_outputs.get(4, ""),
        "{{SECTION_5}}":      section_outputs.get(5, ""),
    }


@observe(as_type="generation", name="casenote-monthly-section", capture_input=False, capture_output=False)
def _call_bedrock(section: dict, subs: dict) -> tuple[str, dict]:
    system = section.get("system", "")
    user = _fill(section.get("user", ""), subs)
    payload = {
        "modelId": MODEL_ID,
        "system": [{"text": system}] if system else [],
        "messages": [{"role": "user", "content": [{"text": user}]}],
        "inferenceConfig": {"maxTokens": MAX_TOKENS},
    }
    resp = converse_with_retry(bedrock_runtime, payload, attempts=3, base_delay=1.5)
    if resp.get("stopReason") == "max_tokens":
        # Output was cut mid-generation — never ship a truncated compliance section silently
        logger.warning("Bedrock output TRUNCATED at maxTokens=%d — section may be incomplete", MAX_TOKENS)
    text = ""
    for block in (resp.get("output") or {}).get("message", {}).get("content", []):
        if "text" in block:
            text += block["text"]
    text = clean(text.strip())
    text, violations = lint(text)
    if violations:
        logger.info("Language violations found and corrected: %s", violations[:3])
    usage = resp.get("usage") or {}
    langfuse.update_current_generation(
        model=MODEL_ID,
        input=user[:2000],
        output=text[:2000],
        usage_details={
            "input": usage.get("inputTokens", 0),
            "output": usage.get("outputTokens", 0),
        },
        metadata={"service": _SERVICE, "section": section.get("id") or section.get("title")},
    )
    return text, usage


async def _run_one(i: int, sec: dict, subs: dict, client_id: str) -> tuple[int, str, dict]:
    logger.info("[%s] section %d → Bedrock", client_id, i)
    text, usage = await asyncio.to_thread(_call_bedrock, sec, subs)
    logger.info("[%s] section %d done  in=%d out=%d", client_id, i,
                usage.get("inputTokens", 0), usage.get("outputTokens", 0))
    return i, text, usage




async def _generate_report(data: dict, client_id: str, current_period: str) -> tuple[str, dict]:
    """Run sections 1-6 in parallel, then section 7 (needs 3/4/5 context).

    Returns (html, usage_totals) where usage_totals has inputTokens, outputTokens, totalTokens.

    **Optimization:** Stats computation and trend loading run in parallel.
    """
    # PARALLEL: Compute stats and load previous month stats concurrently
    async def _compute_and_load_stats():
        try:
            stats = await asyncio.to_thread(
                compute_stats, data, data.get("dateFrom", ""), data.get("dateTo", "")
            )
        except ValueError as e:
            logger.error("[%s] stats computation failed: %s", client_id, e)
            stats = {}
        return stats

    async def _load_prev_stats():
        prev = await asyncio.to_thread(get_previous_month_stats, client_id, current_period)
        return prev.get("stats", {}) if prev else {}

    # Run stats computation and trend loading in parallel
    stats, prev_stats = await asyncio.gather(
        _compute_and_load_stats(),
        _load_prev_stats(),
        return_exceptions=False
    )

    # Compute MoM deltas if previous month exists
    if prev_stats:
        from stats import mom_deltas
        stats["momDeltas"] = mom_deltas(stats, prev_stats)
        logger.info("[%s] MoM deltas computed for %s", client_id, current_period)

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

    prev = await asyncio.to_thread(get_previous_trend, client_id, current_period)
    prev_trend_text = prev["trend_text"] if prev else ""
    if prev_trend_text:
        logger.info("[%s] previous trend found for %s", client_id, prev["period"])
    else:
        logger.info("[%s] no previous trend — section 5 will be baseline month", client_id)

    base_subs = _build_subs(data, {}, stats)

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
    wave1_results = await asyncio.gather(
        *[_run_one(i, sec, _subs_for(i), client_id) for i, sec in wave1]
    )

    section_outputs: dict[int, str] = {i: text for i, text, _ in wave1_results}
    all_usages: list[dict] = [usage for _, _, usage in wave1_results]

    if 5 in section_outputs:
        saved_at = datetime.now(timezone.utc).isoformat()
        await asyncio.to_thread(save_trend, client_id, current_period, section_outputs[5], saved_at)
        logger.info("[%s] trend saved for %s", client_id, current_period)

    for i, sec in wave2:
        logger.info("[%s] wave 2: section %d (uses 3/4/5 context)", client_id, i)
        _, text, usage = await _run_one(i, sec, _build_subs(data, section_outputs, stats), client_id)
        section_outputs[i] = text
        all_usages.append(usage)

    parts = [section_outputs[i] for i, _ in sections if i in section_outputs]
    merged_md = "\n\n---\n\n".join(parts)

    # PARALLEL: Markdown conversion and stats saving run concurrently (both CPU/IO bound)
    totals = sum_usage(all_usages)
    logger.info("[%s] report saved  total_tokens=%d", client_id, totals["totalTokens"])

    # Define concurrent tasks
    async def _save_markdown_file():
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        (REPORTS_DIR / f"{client_id}_report.md").write_text(merged_md + "\n", encoding="utf-8")

    async def _save_stats():
        saved_at = datetime.now(timezone.utc).isoformat()
        await asyncio.to_thread(save_month_stats, client_id, current_period, stats, saved_at)
        logger.info("[%s] month stats saved for %s", client_id, current_period)

    async def _convert_markdown():
        return await asyncio.to_thread(
            md_lib.markdown, merged_md, extensions=["tables", "fenced_code", "sane_lists"]
        )

    # Run all three in parallel: markdown conversion + stats save + file write
    html, _, _ = await asyncio.gather(
        _convert_markdown(),
        _save_stats(),
        _save_markdown_file(),
        return_exceptions=False
    )

    return html, totals


# ── Endpoints ─────────────────────────────────────────────────────────────────

def _token(creds: HTTPAuthorizationCredentials | None) -> str:
    return creds.credentials if creds else ""


@app.get(
    "/psr-report/health",
    summary="Liveness probe",
    tags=["Health"],
    response_model=HealthResponse,
    responses={200: {"description": "Service is running."}},
)
async def health() -> HealthResponse:
    """Returns `{"status": "ok"}`. Use this to verify the service is up before sending reports."""
    return HealthResponse(status="ok")


@app.post(
    "/psr-report/monthly-report",
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
                "7. Recommendations & Intervention Strategies\n\n"
                "**Response headers (token usage across all 7 sections):**\n"
                "- `X-Input-Tokens` — total Bedrock input tokens consumed\n"
                "- `X-Output-Tokens` — total Bedrock output tokens generated\n"
                "- `X-Total-Tokens` — combined total"
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
    _: None = Depends(verify_rsa),
) -> HTMLResponse:
    """
    **What this does**

    1. Authenticates the caller via the X-Signature key (verify_rsa).
    2. Calls `GET /ai/client-data` on the SENA backend, signing the request with
       our RSA private key (the backend verifies with our public key — no user JWT).
    3. Runs **sections 1–6 in parallel** through AWS Bedrock (Claude Sonnet `au.anthropic.claude-sonnet-4-6`).
    4. If a previous month's trend exists, it is automatically injected into Section 5 to produce ↑ ↓ → arrows.
    5. Runs **Section 7** after sections 3, 4, 5 are ready (it uses their output as context).
    6. Strips internal model reasoning/verification blocks from all output.
    7. Saves the merged report to `reports/{client_id}_report.md` on the server.
    8. Auto-saves Section 5 (Trend Analysis) to the trend store for next month's comparison.
    9. Returns the report as **raw HTML** — pass directly to `innerHTML` on the frontend.

    **Typical wall-clock time:** ~30–60 s (limited by slowest parallel Bedrock call).
    """
    # Endpoint auth is the X-Signature key (verify_rsa). The downstream
    # /ai/client-data fetch authenticates as the service via its own RSA
    # signature (see outbound_sign) — no per-user token is threaded through.
    try:
        data = await asyncio.to_thread(
            _fetch_client_data_all, req.client_id, req.organization_id, req.date_from, req.date_to
        )
    except ValueError as exc:
        return HTMLResponse(f"<p>502 Backend error: {exc}</p>", status_code=502)

    current_period = req.date_from[:7]   # "2026-05-01" → "2026-05"
    html, tokens = await _generate_report(data, req.client_id, current_period)
    return HTMLResponse(
        content=html,
        status_code=200,
        headers={
            "X-Input-Tokens":  str(tokens["inputTokens"]),
            "X-Output-Tokens": str(tokens["outputTokens"]),
            "X-Total-Tokens":  str(tokens["totalTokens"]),
        },
    )


# ── Trend endpoints ───────────────────────────────────────────────────────────

class TrendSaveRequest(BaseModel):
    client_id: str = Field(
        ...,
        pattern=r"^[A-Za-z0-9_-]{1,64}$",  # used in file paths — no separators/dots allowed
        description="Client UUID from the SENA system.",
        examples=["0ce6359f-9138-4e05-b83b-6c39875f1828"],
    )
    period: str = Field(
        ...,
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",  # becomes a filename — strict YYYY-MM only
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
    "/psr-report/trend/save",
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
    _: None = Depends(verify_rsa),
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
    saved_at = datetime.now(timezone.utc).isoformat()
    path = await asyncio.to_thread(save_trend, req.client_id, req.period, req.trend_text, saved_at)
    return TrendSaveResponse(status="saved", period=req.period, file=str(path))


@app.get(
    "/psr-report/trend/{client_id}",
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
    _: None = Depends(verify_rsa),
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
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", client_id):
        raise HTTPException(status_code=422, detail="Invalid client_id format.")

    entries = await asyncio.to_thread(list_trends, client_id)
    if not entries:
        raise HTTPException(status_code=404, detail=f"No trend data found for client '{client_id}'.")
    return TrendListResponse(client_id=client_id, count=len(entries), trends=entries)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8602, log_level="info")
