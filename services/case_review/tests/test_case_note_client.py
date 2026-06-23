from __future__ import annotations

"""
Tests for the org-backend case-note fetch (stub=False), member-scoped /mobile endpoints.

Two-step flow:
  GET /mobile/organization-member/case-note/get-all-data → data.items[] (shiftId+clientId refs)
  GET /mobile/organization-member/case-note/get-data/{shiftId}/{clientId} → full content

The caller's JWT is forwarded as the outbound Authorization header.
httpx is faked via monkeypatch (respx is not a project dependency).
"""

import pytest

from clients.case_note_client import CaseNoteClient, _compose_note_body

_LIST = {
    "success": True,
    "data": {
        "items": [
            {"shiftId": "shift-1", "clientId": "client-1", "startTime": "2026-03-18T02:37:00.000Z"},
            {"shiftId": "shift-3", "clientId": "client-1", "startTime": "2026-03-16T02:37:00.000Z"},
        ],
        "pagination": {"page": 1, "limit": 10, "total": 2},
    },
}

_CONTENT = {
    ("shift-1", "client-1"): {
        "id": "note-1", "clientId": "client-1", "organizationMemberId": "staff-1",
        "updatedAt": "2026-03-18T12:53:10.151Z",
        "summaryOfShift": "Shift went well",
        "activitiesAndSkill": {"assisted": "morning routine", "practisedSkill": "communication"},
        "wellbeingAndBehaviour": {"mood": "Calm and positive"},
        "outcomesAndProgress": {}, "safetyAndHealth": {"medicationReminderGiven": True},
        "careFeedback": None, "anyIncident": False,
    },
    ("shift-3", "client-1"): {
        "id": "note-2", "clientId": "client-1", "organizationMemberId": "staff-1",
        "updatedAt": "2026-03-16T12:53:10.151Z",
        "summaryOfShift": "Community access",
        "activitiesAndSkill": {}, "wellbeingAndBehaviour": {},
        "outcomesAndProgress": {}, "safetyAndHealth": {},
        "careFeedback": "Positive", "anyIncident": True,
    },
}

# captured outbound headers, for the JWT-forwarding assertion
_seen_headers: dict = {}


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs) -> None:
        _seen_headers.clear()
        _seen_headers.update(kwargs.get("headers") or {})

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def get(self, url: str, params: dict | None = None):
        if url.endswith("/get-all-data"):
            return _FakeResponse(_LIST)
        # /mobile/organization-member/case-note/get-data/{shiftId}/{clientId}
        shift_id, client_id = url.rsplit("/", 2)[-2:]
        return _FakeResponse({"success": True, "data": _CONTENT[(shift_id, client_id)]})


# ── _compose_note_body (pure) ─────────────────────────────────────────────────

def test_compose_includes_summary_sections_and_incident() -> None:
    body = _compose_note_body(_CONTENT[("shift-1", "client-1")])
    assert "Summary of shift: Shift went well" in body
    assert "Activities & skills:" in body
    assert "morning routine" in body
    assert "Wellbeing & behaviour:" in body
    assert "Calm and positive" in body
    assert "Incident reported: no" in body


def test_compose_skips_empty_sections_and_marks_incident() -> None:
    body = _compose_note_body(_CONTENT[("shift-3", "client-1")])
    assert "Activities & skills:" not in body   # empty dict → omitted
    assert "Care feedback: Positive" in body
    assert "Incident reported: yes" in body


# ── two-step fetch ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_from_api_two_step_and_forwards_jwt(monkeypatch) -> None:
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    client = CaseNoteClient(stub=False)
    notes = await client.get_notes("staff-1", "client-1", limit=10, bearer_token="tok-abc")

    # both (shift, client) refs resolved to content notes
    assert [n.note_id for n in notes] == ["note-1", "note-2"]
    first = notes[0]
    assert first.client_id == "client-1"
    assert first.staff_id == "staff-1"            # from content.organizationMemberId
    assert first.date == "2026-03-18T02:37:00.000Z"   # from list item startTime
    assert first.transcript == ""
    assert "Shift went well" in first.drafted_note

    # caller's JWT forwarded outbound
    assert _seen_headers.get("Authorization") == "Bearer tok-abc"


@pytest.mark.asyncio
async def test_fetch_respects_limit_cap(monkeypatch) -> None:
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    client = CaseNoteClient(stub=False)
    notes = await client.get_notes("staff-1", "client-1", limit=1, bearer_token="t")
    assert len(notes) == 1
    assert notes[0].note_id == "note-1"
