"""Backend case-note API client — supports BOTH data paths (see api_main.py).

Live testing (2026-06) established:
  - GET /organization/case-note/get-all  → works with an ADMIN/org token; returns
    register METADATA only (clientName, shiftName, dates, status, caseNoteId — no text).
    Real envelope is NESTED: { data: { data: [...], pagination: {...} } }.
  - GET /mobile/organization-member/case-note/get-all-data → returns the authenticated
    SUPPORT WORKER's own notes WITH full content, but 401s ("User is not authorized as
    support worker") for an admin/owner token.

So two mutually-exclusive modes depending on the caller's JWT role:
  - CONTENT mode (support-worker token): fetch_member_notes() → full note bodies.
  - REGISTER ROLLUP mode (admin token): fetch_register() → metadata only.

api_main.py tries content first and falls back to rollup on NotSupportWorkerError.

`_get` is a requests wrapper with exponential-backoff retry (max 3) on 5xx/network
errors; 4xx are returned immediately (auth/permission are not retryable).
"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from config import API_BASE_URL, VERBOSE
from auth import get_auth_headers

REGISTER_PATH = "/organization/case-note/get-all"
ALL_DATA_PATH = "/mobile/organization-member/case-note/get-all-data"
NOTE_PATH = "/mobile/organization-member/case-note/get-data/{shiftId}/{clientId}"

_TIMEOUT = 15
_MAX_RETRIES = 3
_NOTE_FETCH_WORKERS = 12


class CaseNoteAPIError(Exception):
    """Backend call failed on the first page (network, 5xx, or unexpected 4xx)."""

    def __init__(self, status_code: int, message: str, details: str = ""):
        self.status_code = status_code
        self.details = details
        super().__init__(message)


class NotSupportWorkerError(CaseNoteAPIError):
    """The 401 "User is not authorized as support worker" — token lacks the mobile role.

    Signals api_main to fall back from CONTENT mode to REGISTER ROLLUP mode.
    """


def _log(msg: str) -> None:
    if VERBOSE:
        print(f"[casenote_client] {msg}", file=sys.stderr, flush=True)


def _get(path: str, token: str, params: dict | None = None) -> tuple[bool, int, dict | None, str | None]:
    """GET {API_BASE_URL}{path} with retry. Returns (ok, status_code, body, error)."""
    url = f"{API_BASE_URL}{path}"
    headers = get_auth_headers(token)
    last_status, last_err = 0, None

    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=_TIMEOUT)
            if resp.status_code in (200, 201):
                try:
                    return True, resp.status_code, resp.json(), None
                except ValueError:
                    return False, resp.status_code, None, "non-JSON response"
            if 400 <= resp.status_code < 500:  # auth/permission/not-found — don't retry
                _log(f"✗ {resp.status_code} {path} (no retry) — {resp.text[:200]}")
                return False, resp.status_code, _safe_json(resp), resp.text[:300]
            last_status, last_err = resp.status_code, f"API returned {resp.status_code}"
            _log(f"⚠ {resp.status_code} {path} (attempt {attempt + 1}/{_MAX_RETRIES})")
        except requests.exceptions.RequestException as e:
            last_status, last_err = 0, str(e)
            _log(f"⚠ {type(e).__name__} {path} (attempt {attempt + 1}/{_MAX_RETRIES})")

        if attempt < _MAX_RETRIES - 1:
            time.sleep(2 ** attempt)  # 1s, 2s

    return False, last_status, None, last_err or "request failed"


def _safe_json(resp) -> dict | None:
    try:
        return resp.json()
    except ValueError:
        return None


def _is_support_worker_401(status_code: int, body: dict | None, details: str | None) -> bool:
    if status_code != 401:
        return False
    msg = ((body or {}).get("message") or "") + " " + (details or "")
    return "support worker" in msg.lower()


def _unwrap(body: dict | None) -> tuple[list, dict]:
    """Extract (rows, pagination) from either the nested or flattened envelope."""
    if not isinstance(body, dict):
        return [], {}
    outer = body.get("data")
    if isinstance(outer, dict):  # nested: { data: { data: [...], pagination: {...} } }
        rows = outer.get("data") if isinstance(outer.get("data"), list) else []
        return rows, (outer.get("pagination") or {})
    if isinstance(outer, list):  # flattened: { data: [...], pagination: {...} }
        return outer, (body.get("pagination") or {})
    return [], {}


def _paginate(path: str, token: str, base_params: dict, limit: int) -> tuple[list[dict], int]:
    """Page through any nested-envelope list endpoint. Returns (rows, reported_total)."""
    rows: list[dict] = []
    reported_total = 0
    page = 1
    while True:
        ok, status, body, err = _get(path, token, params={**base_params, "page": page, "limit": limit})
        if not ok:
            if page == 1:
                if _is_support_worker_401(status, body, err):
                    raise NotSupportWorkerError(status, "not authorized as support worker", err or "")
                raise CaseNoteAPIError(status, err or "request failed", err or "")
            _log(f"{path} page {page} failed, stopping: {err}")
            break

        page_rows, pagination = _unwrap(body)
        rows.extend(page_rows)
        reported_total = pagination.get("total", reported_total) or reported_total
        if not pagination.get("hasNext"):
            break
        page += 1

    _log(f"{path}: {len(rows)} rows, reported total={reported_total}")
    return rows, reported_total


# ---- REGISTER ROLLUP mode (admin token) ----

def fetch_register(token: str, member_id: str, shift_date_from: str, shift_date_to: str,
                   limit: int = 100) -> tuple[list[dict], int]:
    """Page the org case-note register for one member + shift-date window (metadata only)."""
    return _paginate(
        REGISTER_PATH, token,
        {"memberId": member_id, "shiftDateFrom": shift_date_from, "shiftDateTo": shift_date_to},
        limit,
    )


# ---- CONTENT mode (support-worker token) ----

def fetch_member_notes(token: str, limit: int = 100) -> list[dict]:
    """Page the authenticated member's own case notes WITH full content (get-all-data).

    Raises NotSupportWorkerError if the token lacks the support_worker role (→ fall back
    to register rollup). The endpoint has no date filter; callers filter by month locally.
    """
    rows, _ = _paginate(ALL_DATA_PATH, token, {}, limit)
    return rows


def fetch_note(token: str, shift_id: str, client_id: str) -> dict | None:
    """Fetch one case note's full body (support-worker token only). None on error."""
    ok, status, body, err = _get(NOTE_PATH.format(shiftId=shift_id, clientId=client_id), token)
    if not ok:
        _log(f"note fetch failed shift={shift_id} client={client_id}: {err}")
        return None
    if isinstance(body, dict) and "data" in body:
        return body["data"]
    return body
