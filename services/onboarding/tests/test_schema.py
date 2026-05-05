"""Tests for schema_spec.py Pydantic models."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from onboarding.models.schema_spec import FieldSpec, FieldType, SectionSpec, StepSchema

FIXTURES = Path(__file__).parent.parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class TestFieldSpec:
    def test_enum_requires_options(self):
        with pytest.raises(ValidationError, match="options"):
            FieldSpec(id="x", type=FieldType.enum)

    def test_valid_enum(self):
        f = FieldSpec(id="gender", type=FieldType.enum, options=["Male", "Female"])
        assert f.options == ["Male", "Female"]

    def test_visible_if_stored(self):
        f = FieldSpec(
            id="interpreter_lang",
            type=FieldType.text,
            visible_if={"interpreter_required": True},
        )
        assert f.visible_if == {"interpreter_required": True}


class TestSectionSpec:
    def test_repeatable_requires_item_fields(self):
        from onboarding.models.schema_spec import RepeatableConfig
        with pytest.raises(ValidationError, match="item_fields"):
            SectionSpec(id="x", label="X", repeatable=RepeatableConfig(min=1))

    def test_non_repeatable_requires_fields(self):
        with pytest.raises(ValidationError):
            SectionSpec(id="x", label="X")

    def test_is_repeatable(self):
        from onboarding.models.schema_spec import RepeatableConfig
        section = SectionSpec(
            id="contacts",
            label="Contacts",
            repeatable=RepeatableConfig(min=1, max=5),
            item_fields=[FieldSpec(id="name", type=FieldType.text)],
        )
        assert section.is_repeatable is True


class TestFixtureSchemas:
    @pytest.mark.parametrize("filename", [
        "schema_personal_information.json",
        "schema_participant_requirements.json",
        "schema_ndis_plan_details.json",
        "schema_documents.json",
        "schema_medical_information.json",
    ])
    def test_fixture_valid(self, filename):
        data = load_fixture(filename)
        if "_comment" in data:
            data = {k: v for k, v in data.items() if k != "_comment"}
        schema = StepSchema.model_validate(data)
        assert schema.step_id
        assert len(schema.sections) > 0

    def test_personal_info_required_count(self):
        data = load_fixture("schema_personal_information.json")
        schema = StepSchema.model_validate(data)
        # Basics: full_name, email, phone, dob, gender, bio, lang, interpreter_required = 8
        # home_address: address, state, city, zip = 4
        # emergency_contacts: 0 (repeatable, logic differs)
        count = schema.required_field_count()
        assert count >= 8

    def test_personal_info_step_progress(self):
        data = load_fixture("schema_personal_information.json")
        schema = StepSchema.model_validate(data)
        assert schema.progress_percent == 20
