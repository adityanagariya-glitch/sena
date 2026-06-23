from __future__ import annotations

"""
Case-note source client.

Two modes (selected by `stub`):

  stub=True  → load fixtures from fixtures/sample_notes.json (local dev / tests).

  stub=False → call the SENA org backend in two steps:
      1. GET {base}/organization/case-note/get-all
           ?clientId=<uuid>&memberId=<staff uuid>&limit=<N>
           &status=completed&sortByUpdatedAt=d
         → register rows: { clientId, memberId, caseNoteId, shiftStartDate, ... }
           (caseNoteId is null for pending notes — those are skipped)
      2. GET {base}/organization/case-note/{caseNoteId}  (one per note, concurrent)
         → full content: { summaryOfShift, activitiesAndSkill, wellbeingAndBehaviour,
                           outcomesAndProgress, safetyAndHealth, careFeedback,
                           anyIncident, reviewNote, ... }

The org backend has no raw transcript; the structured content fields are composed
into CaseNoteDTO.drafted_note for the summarizer. At most `case_note_fetch_limit`
notes are fetched per call (default 10).
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
    ) -> list[CaseNoteDTO]:
        if self._stub:
            return self._stub_notes(staff_id, client_id, limit)
        return await self._fetch_from_api(staff_id, client_id, limit)

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

    # ── Real API (SENA org backend) ────────────────────────────────────────────

    async def _fetch_from_api(
        self,
        staff_id: str,
        client_id: str,
        limit: int,
    ) -> list[CaseNoteDTO]:
        import httpx

        from core.settings import settings

        # Hard cap — never pull more than the configured limit (default 10).
        effective_limit = max(1, min(limit, settings.case_note_fetch_limit))
        base = settings.case_note_api_base_url.rstrip("/")
        headers = {"Accept": "application/json"}
        if settings.case_note_api_token:
            headers["Authorization"] = f"Bearer {settings.case_note_api_token}"

        async with httpx.AsyncClient(base_url=base, headers=headers, timeout=15.0) as http:
            # 1. Register: newest-first, completed only (those have a caseNoteId).
            reg_resp = await http.get(
                "/organization/case-note/get-all",
                params={
                    "clientId": client_id,
                    "memberId": staff_id,
                    "limit": effective_limit,
                    "page": 1,
                    "status": "completed",
                    "sortByUpdatedAt": "d",
                },
            )
            reg_resp.raise_for_status()
            rows = reg_resp.json().get("data") or []

            # Keep only rows with an actual case note, newest first, capped.
            register = [r for r in rows if r.get("caseNoteId")][:effective_limit]
            if not register:
                log.info("case_note_client.no_notes", staff_id=staff_id, client_id=client_id)
                return []

            # 2. Fetch each note's content concurrently.
            async def _fetch_one(row: dict[str, Any]) -> CaseNoteDTO | None:
                cid = row["caseNoteId"]
                resp = await http.get(f"/organization/case-note/{cid}")
                resp.raise_for_status()
                data = resp.json().get("data") or {}
                return CaseNoteDTO(
                    note_id=str(data.get("id") or cid),
                    date=str(row.get("shiftStartDate") or data.get("updatedAt") or ""),
                    staff_id=str(data.get("organizationMemberId") or row.get("memberId") or staff_id),
                    client_id=str(data.get("clientId") or row.get("clientId") or client_id),
                    transcript="",  # org backend has no raw transcript
                    drafted_note=_compose_note_body(data),
                )

            results = await asyncio.gather(
                *(_fetch_one(r) for r in register), return_exceptions=True
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
            register_rows=len(register),
            fetched=len(notes),
        )
        return notes
