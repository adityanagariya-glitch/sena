from __future__ import annotations

"""
Tests for the org-backend case-note fetch (stub=False).

Verifies the two-step flow:
  GET /organization/case-note/get-all  → register rows (caseNoteId refs)
  GET /organization/case-note/{id}     → full content (composed into drafted_note)

httpx is faked via monkeypatch (respx is not a project dependency).
"""

import json

import pytest

from clients.case_note_client import CaseNoteClient, _compose_note_body

_REGISTER = {
    "success": True,
    "data": [
        {
            "clientId": "client-1", "memberId": "staff-1", "workerName": "Staff 2",
            "shiftId": "shift-1", "shiftStartDate": "2026-03-18T02:37:00.000Z",
            "caseNoteId": "note-1", "status": "completed",
        },
        {
            "clientId": "client-1", "memberId": "staff-1", "workerName": "Ariel",
            "shiftId": "shift-2", "shiftStartDate": "2026-03-17T02:37:00.000Z",
            "caseNoteId": None, "status": "pending",   # ← must be skipped
        },
        {
            "clientId": "client-1", "memberId": "staff-1", "workerName": "Staff 2",
            "shiftId": "shift-3", "shiftStartDate": "2026-03-16T02:37:00.000Z",
            "caseNoteId": "note-2", "status": "completed",
        },
    ],
}

_CONTENT = {
    "note-1": {
        "id": "note-1", "clientId": "client-1", "organizationMemberId": "staff-1",
        "updatedAt": "2026-03-18T12:53:10.151Z",
        "summaryOfShift": "Shift went well",
        "activitiesAndSkill": {"cooking": "boiled pasta independently"},
        "wellbeingAndBehaviour": {}, "outcomesAndProgress": {}, "safetyAndHealth": {},
        "careFeedback": None, "anyIncident": False, "reviewNote": None,
    },
    "note-2": {
        "id": "note-2", "clientId": "client-1", "organizationMemberId": "staff-1",
        "updatedAt": "2026-03-16T12:53:10.151Z",
        "summaryOfShift": "Community access",
        "activitiesAndSkill": {}, "wellbeingAndBehaviour": {},
        "outcomesAndProgress": {}, "safetyAndHealth": {},
        "careFeedback": "Positive", "anyIncident": True, "reviewNote": None,
    },
}


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def get(self, url: str, params: dict | None = None):
        if url == "/organization/case-note/get-all":
            return _FakeResponse(_REGISTER)
        note_id = url.rsplit("/", 1)[-1]
        return _FakeResponse({"success": True, "data": _CONTENT[note_id]})


# ── _compose_note_body (pure) ─────────────────────────────────────────────────

def test_compose_includes_summary_sections_and_incident() -> None:
    body = _compose_note_body(_CONTENT["note-1"])
    assert "Summary of shift: Shift went well" in body
    assert "Activities & skills:" in body
    assert "boiled pasta independently" in body
    assert "Incident reported: no" in body


def test_compose_skips_empty_sections() -> None:
    body = _compose_note_body(_CONTENT["note-1"])
    # empty dict sections must not appear
    assert "Wellbeing & behaviour:" not in body
    assert "Care feedback:" not in body  # None → omitted


def test_compose_marks_incident_and_feedback() -> None:
    body = _compose_note_body(_CONTENT["note-2"])
    assert "Care feedback: Positive" in body
    assert "Incident reported: yes" in body


# ── two-step fetch ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_from_api_two_step(monkeypatch) -> None:
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    client = CaseNoteClient(stub=False)
    notes = await client.get_notes("staff-1", "client-1", limit=10)

    # pending row (caseNoteId=None) skipped → only 2 notes
    assert [n.note_id for n in notes] == ["note-1", "note-2"]
    first = notes[0]
    assert first.client_id == "client-1"
    assert first.staff_id == "staff-1"
    assert first.date == "2026-03-18T02:37:00.000Z"  # from register row
    assert first.transcript == ""  # org backend has no transcript
    assert "Shift went well" in first.drafted_note


@pytest.mark.asyncio
async def test_fetch_respects_limit_cap(monkeypatch) -> None:
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    client = CaseNoteClient(stub=False)
    notes = await client.get_notes("staff-1", "client-1", limit=1)
    assert len(notes) == 1
    assert notes[0].note_id == "note-1"
