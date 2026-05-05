"""Tests for Redis-backed FormStateRepo."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from onboarding.models.form_state import FieldSource, FormState
from onboarding.models.schema_spec import StepSchema

FIXTURES = Path(__file__).parent.parent / "fixtures"


def personal_schema() -> StepSchema:
    data = json.loads((FIXTURES / "schema_personal_information.json").read_text())
    return StepSchema.model_validate(data)


def make_state(session_id: str = "sess-001") -> FormState:
    return FormState(
        session_id=session_id,
        step_id="personal_information",
        participant_id="part-001",
    )


class TestCreateAndGet:
    async def test_roundtrip(self, repo):
        state = make_state()
        schema = personal_schema()
        await repo.create_session(state, schema, ttl_sec=300)

        retrieved = await repo.get_state("sess-001")
        assert retrieved is not None
        assert retrieved.session_id == "sess-001"
        assert retrieved.step_id == "personal_information"

    async def test_missing_session_returns_none(self, repo):
        result = await repo.get_state("nonexistent")
        assert result is None

    async def test_schema_roundtrip(self, repo):
        state = make_state()
        schema = personal_schema()
        await repo.create_session(state, schema, ttl_sec=300)

        retrieved = await repo.get_schema("sess-001")
        assert retrieved is not None
        assert retrieved.step_id == "personal_information"
        assert len(retrieved.sections) > 0


class TestStateUpdate:
    async def test_set_field_and_save(self, repo):
        state = make_state()
        schema = personal_schema()
        await repo.create_session(state, schema, ttl_sec=300)

        state.set_field("basics", "full_name", "Alice", confidence=0.98, turn_id=1)
        await repo.save_state(state, ttl_sec=300)

        reloaded = await repo.get_state("sess-001")
        assert reloaded.values["basics"]["full_name"]["value"] == "Alice"
        assert reloaded.values["basics"]["full_name"]["confidence"] == 0.98

    async def test_repeatable_field(self, repo):
        state = make_state()
        schema = personal_schema()
        await repo.create_session(state, schema, ttl_sec=300)

        state.set_field("emergency_contacts", "name", "Bob", repeatable_index=0)
        state.set_field("emergency_contacts", "relation", "Parent", repeatable_index=0)
        await repo.save_state(state, ttl_sec=300)

        reloaded = await repo.get_state("sess-001")
        assert reloaded.values["emergency_contacts"][0]["name"]["value"] == "Bob"


class TestWsLock:
    async def test_acquire_and_release(self, repo):
        assert await repo.acquire_ws_lock("sess-001", ttl_sec=60) is True
        assert await repo.is_ws_locked("sess-001") is True
        await repo.release_ws_lock("sess-001")
        assert await repo.is_ws_locked("sess-001") is False

    async def test_second_acquire_fails(self, repo):
        await repo.acquire_ws_lock("sess-001", ttl_sec=60)
        result = await repo.acquire_ws_lock("sess-001", ttl_sec=60)
        assert result is False


class TestTranscript:
    async def test_append_and_get(self, repo):
        entry = {"speaker": "user", "text": "My name is Alice", "turn_id": 1}
        await repo.append_transcript("sess-001", entry, ttl_sec=300)
        await repo.append_transcript("sess-001", {"speaker": "agent", "text": "Hi Alice", "turn_id": 2}, ttl_sec=300)

        entries = await repo.get_transcript("sess-001")
        assert len(entries) == 2
        assert entries[0]["speaker"] == "user"
        assert entries[1]["speaker"] == "agent"


class TestResumption:
    async def test_save_and_retrieve(self, repo):
        await repo.save_resumption_handle("handle-abc", "sess-001", ttl_sec=60)
        sid = await repo.get_session_by_handle("handle-abc")
        assert sid == "sess-001"

    async def test_missing_handle_returns_none(self, repo):
        result = await repo.get_session_by_handle("nonexistent-handle")
        assert result is None
