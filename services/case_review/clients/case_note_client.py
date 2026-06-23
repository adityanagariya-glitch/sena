from __future__ import annotations

"""
Case-note source client.

Two modes (selected by `stub`):

  stub=True  → load fixtures from fixtures/sample_notes.json (local dev / tests).

  stub=False → call the SENA org backend (member-scoped /mobile endpoints) in two
  steps, authenticated as the calling staff member by FORWARDING their JWT:
      1. GET {base}/mobile/organization-member/case-note/get-all-data
           ?clientId=<uuid>&limit=<N>&page=1&sortByStartTime=d
         → data.items[]: { shiftId, clientId, startTime, ... }
           (the member is implied by the bearer token, so staff_id is not sent)
      2. GET {base}/mobile/organization-member/case-note/get-data/{shiftId}/{clientId}
         (one per note, concurrent)
         → full content: { id, summaryOfShift, activitiesAndSkill, wellbeingAndBehaviour,
                           outcomesAndProgress, safetyAndHealth, careFeedback,
                           anyIncident, organizationMemberId, ... }

The backend has no raw transcript; the structured content fields are composed into
CaseNoteDTO.drafted_note for the summarizer. At most `case_note_fetch_limit` notes
are fetched per call (default 10).
"""

import asyncio
import json
from pathlib import Path
from typing import Any

import structlog

from models.schemas import CaseNoteDTO

log = structlog.get_logger(__name__)

# Fixtures live at services/case_review/fixtures/sample_notes.json — one level up
# from this clients/ dir (parents[1] == the case_review package root).
_FIXTURES_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "sample_notes.json"

_fixture_cache: list[CaseNoteDTO] | None = None

# Structured content sections (in render order) → human-readable headings.
_CONTENT_SECTIONS: list[tuple[str, str]] = [
    ("activitiesAndSkill", "Activities & skills"),
    ("wellbeingAndBehaviour", "Wellbeing & behaviour"),
    ("outcomesAndProgress", "Outcomes & progress"),
    ("safetyAndHealth", "Safety & health"),
]


def _load_fixtures() -> list[CaseNoteDTO]:
    global _fixture_cache
    if _fixture_cache is None:
        raw = json.loads(_FIXTURES_PATH.read_text())
        _fixture_cache = [CaseNoteDTO(**n) for n in raw]
    return _fixture_cache


def _render_section(value: Any) -> str:
    """Flatten a structured section (dict / scalar) into readable lines."""
    if isinstance(value, dict):
        lines = [f"  - {k}: {v}" for k, v in value.items() if v not in (None, "", {}, [])]
        return "\n".join(lines)
    return f"  {value}".rstrip()


def _compose_note_body(data: dict[str, Any]) -> str:
    """
    Build the drafted-note text the summarizer ingests from the structured
    GET /organization/case-note/{id} payload.
    """
    parts: list[str] = []

    summary = data.get("summaryOfShift")
    if summary:
        parts.append(f"Summary of shift: {summary}")

    for key, heading in _CONTENT_SECTIONS:
        rendered = _render_section(data.get(key))
        if rendered:
            parts.append(f"{heading}:\n{rendered}")

    feedback = data.get("careFeedback")
    if feedback:
        parts.append(f"Care feedback: {feedback}")

    review = data.get("reviewNote")
    if review:
        parts.append(f"Review note: {review}")

    parts.append(f"Incident reported: {'yes' if data.get('anyIncident') else 'no'}")
    return "\n\n".join(parts)


class CaseNoteClient:
    """Fetch case notes for a (staff, client) pair — fixtures or org backend."""

    def __init__(self, *, stub: bool = True) -> None:
        self._stub = stub

    async def get_notes(
        self,
        staff_id: str,
        client_id: str,
        limit: int = 10,
        *,
        bearer_token: str | None = None,
    ) -> list[CaseNoteDTO]:
        if self._stub:
            return self._stub_notes(staff_id, client_id, limit)
        return await self._fetch_from_api(client_id, limit, bearer_token)

    # ── Stub ──────────────────────────────────────────────────────────────────

    def _stub_notes(self, staff_id: str, client_id: str, limit: int) -> list[CaseNoteDTO]:
        notes = _load_fixtures()
        # filter by staff/client if they match fixture IDs, else return all
        filtered = [
            n for n in notes
            if n.staff_id == staff_id and n.client_id == client_id
        ]
        if not filtered:
            filtered = notes  # dev convenience: return all if no match
        return filtered[:limit]

    # ── Real API (SENA org backend, member-scoped /mobile endpoints) ────────────

    async def _fetch_from_api(
        self,
        client_id: str,
        limit: int,
        bearer_token: str | None,
    ) -> list[CaseNoteDTO]:
        import httpx

        from core.settings import settings

        # Hard cap — never pull more than the configured limit (default 10).
        effective_limit = max(1, min(limit, settings.case_note_fetch_limit))
        base = settings.case_note_api_base_url.rstrip("/")

        # Forward the caller's JWT (the endpoints are scoped to the authenticated
        # member); fall back to a configured service token if no caller token.
        token = bearer_token or settings.case_note_api_token
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        async with httpx.AsyncClient(base_url=base, headers=headers, timeout=15.0) as http:
            # 1. Discovery: this member's notes for the client, newest-first.
            list_resp = await http.get(
                "/mobile/organization-member/case-note/get-all-data",
                params={
                    "clientId": client_id,
                    "limit": effective_limit,
                    "page": 1,
                    "sortByStartTime": "d",
                },
            )
            list_resp.raise_for_status()
            items = ((list_resp.json().get("data") or {}).get("items")) or []

            # Each item needs a (shiftId, clientId) pair to fetch content. Cap it.
            refs = [
                it for it in items if it.get("shiftId") and it.get("clientId")
            ][:effective_limit]
            if not refs:
                log.info("case_note_client.no_notes", client_id=client_id)
                return []

            # 2. Fetch each note's content concurrently by (shiftId, clientId).
            async def _fetch_one(ref: dict[str, Any]) -> CaseNoteDTO | None:
                shift_id, c_id = ref["shiftId"], ref["clientId"]
                resp = await http.get(
                    f"/mobile/organization-member/case-note/get-data/{shift_id}/{c_id}"
                )
                resp.raise_for_status()
                data = resp.json().get("data") or {}
                if not data:
                    return None
                return CaseNoteDTO(
                    note_id=str(data.get("id") or f"{shift_id}:{c_id}"),
                    date=str(ref.get("startTime") or data.get("updatedAt") or ""),
                    staff_id=str(data.get("organizationMemberId") or ""),
                    client_id=str(data.get("clientId") or c_id),
                    transcript="",  # backend has no raw transcript
                    drafted_note=_compose_note_body(data),
                )

            results = await asyncio.gather(
                *(_fetch_one(r) for r in refs), return_exceptions=True
            )

        notes: list[CaseNoteDTO] = []
        for r in results:
            if isinstance(r, Exception):
                log.warning("case_note_client.note_fetch_failed", error=str(r)[:120])
                continue
            if r is not None:
                notes.append(r)

        log.info(
            "case_note_client.fetched",
            requested=effective_limit,
            list_items=len(refs),
            fetched=len(notes),
        )
        return notes
