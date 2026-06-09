"""Tests for schema_spec.py Pydantic models."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from sena_common.voice.schema_spec import FieldSpec, FieldType, SectionSpec


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
        from sena_common.voice.schema_spec import RepeatableConfig
        with pytest.raises(ValidationError, match="item_fields"):
            SectionSpec(id="x", label="X", repeatable=RepeatableConfig(min=1))

    def test_non_repeatable_requires_fields(self):
        with pytest.raises(ValidationError):
            SectionSpec(id="x", label="X")

    def test_is_repeatable(self):
        from sena_common.voice.schema_spec import RepeatableConfig
        section = SectionSpec(
            id="contacts",
            label="Contacts",
            repeatable=RepeatableConfig(min=1, max=5),
            item_fields=[FieldSpec(id="name", type=FieldType.text)],
        )
        assert section.is_repeatable is True


