from __future__ import annotations

"""
Stub client for the other engineer's case-note drafting service.

Real contract (planned):
  GET {drafting_service_url}/case-notes
    ?staff_id=<uuid>&client_id=<uuid>&limit=<int>
  → { note_id, date, transcript, drafted_note, staff_id, client_id }[]

Until the real API is available, this stub returns fixtures loaded from
fixtures/sample_notes.json. Swap _fetch_from_api() into get_notes() when
the real service is reachable.
"""

import json
from pathlib import Path

from case_review.models.schemas import CaseNoteDTO

_FIXTURES_PATH = Path(__file__).resolve().parents[4] / "fixtures" / "sample_notes.json"

_fixture_cache: list[CaseNoteDTO] | None = None


def _load_fixtures() -> list[CaseNoteDTO]:
    global _fixture_cache
    if _fixture_cache is None:
        raw = json.loads(_FIXTURES_PATH.read_text())
        _fixture_cache = [CaseNoteDTO(**n) for n in raw]
    return _fixture_cache


class CaseNoteClient:
    """
    Fetch case notes for a (staff, client) pair.
    Uses fixture stub. Replace stub=False to call real service.
    """

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

    # ── Real API (future) ─────────────────────────────────────────────────────

    async def _fetch_from_api(
        self,
        staff_id: str,
        client_id: str,
        limit: int,
    ) -> list[CaseNoteDTO]:
        import httpx
        from case_review.core.settings import settings

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{settings.drafting_service_url}/case-notes",
                params={"staff_id": staff_id, "client_id": client_id, "limit": limit},
                headers={"X-Api-Key": settings.drafting_service_api_key},
            )
            resp.raise_for_status()
            return [CaseNoteDTO(**n) for n in resp.json()]
