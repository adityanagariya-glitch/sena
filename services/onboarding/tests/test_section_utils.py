from __future__ import annotations

import pytest

from onboarding.voice.turn_payload import VisibleField
from onboarding.prompts._section_utils import (
    _is_empty,
    form_completion_tier,
    has_incomplete_rows,
    has_unfilled_enums,
    needs_guidance,
    section_complete,
    step,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_field(
    path: str,
    *,
    required: bool = True,
    readonly: bool = False,
    value: object = None,
    section: str | None = None,
    repeatable_index: int | None = None,
) -> VisibleField:
    return VisibleField(
        path=path,
        label=path,
        type="text",
        required=required,
        readonly=readonly,
        value=value,
        section=section,
        repeatable_index=repeatable_index,
    )


# ---------------------------------------------------------------------------
# _is_empty
# ---------------------------------------------------------------------------

class TestIsEmpty:
    def test_none_is_empty(self):
        assert _is_empty(None) is True

    def test_empty_string_is_empty(self):
        assert _is_empty("") is True

    def test_empty_list_is_empty(self):
        assert _is_empty([]) is True

    def test_empty_dict_is_empty(self):
        assert _is_empty({}) is True

    def test_non_empty_string_not_empty(self):
        assert _is_empty("hello") is False

    def test_non_empty_list_not_empty(self):
        assert _is_empty(["a"]) is False

    def test_non_empty_dict_not_empty(self):
        assert _is_empty({"k": "v"}) is False

    def test_zero_not_empty(self):
        assert _is_empty(0) is False

    def test_false_not_empty(self):
        assert _is_empty(False) is False


# ---------------------------------------------------------------------------
# section_complete
# ---------------------------------------------------------------------------

class TestSectionComplete:
    def test_empty_section_returns_true(self):
        """No fields matching the prefix → vacuously complete."""
        fields = [make_field("other.name", value="Alice")]
        assert section_complete("basics", fields) is True

    def test_all_required_filled_returns_true(self):
        fields = [
            make_field("basics.name", value="Alice"),
            make_field("basics.dob", value="2000-01-01"),
        ]
        assert section_complete("basics", fields) is True

    def test_one_required_empty_returns_false(self):
        fields = [
            make_field("basics.name", value="Alice"),
            make_field("basics.dob", value=None),
        ]
        assert section_complete("basics", fields) is False

    def test_readonly_field_ignored_even_if_empty(self):
        fields = [
            make_field("basics.name", value="Alice"),
            make_field("basics.id", required=True, readonly=True, value=None),
        ]
        assert section_complete("basics", fields) is True

    def test_optional_field_ignored_even_if_empty(self):
        fields = [
            make_field("basics.name", value="Alice"),
            make_field("basics.nickname", required=False, value=None),
        ]
        assert section_complete("basics", fields) is True

    def test_prefix_not_substring_match(self):
        """'basics_extra.field' should not match prefix 'basics'."""
        fields = [
            make_field("basics_extra.field", value=None),
        ]
        assert section_complete("basics", fields) is True

    def test_partially_filled_returns_false(self):
        fields = [
            make_field("basics.a", value="x"),
            make_field("basics.b", value=""),
            make_field("basics.c", value="y"),
        ]
        assert section_complete("basics", fields) is False


# ---------------------------------------------------------------------------
# has_unfilled_enums
# ---------------------------------------------------------------------------

class TestHasUnfilledEnums:
    def test_all_filled_returns_false(self):
        fields = [
            make_field("basics.gender", value="male"),
            make_field("basics.language", value="en"),
        ]
        assert has_unfilled_enums(["basics.gender", "basics.language"], fields) is False

    def test_one_empty_returns_true(self):
        fields = [
            make_field("basics.gender", value=None),
            make_field("basics.language", value="en"),
        ]
        assert has_unfilled_enums(["basics.gender", "basics.language"], fields) is True

    def test_path_not_in_visible_fields_returns_true(self):
        fields = [make_field("basics.language", value="en")]
        assert has_unfilled_enums(["basics.gender"], fields) is True

    def test_empty_field_paths_returns_false(self):
        fields = [make_field("basics.gender", value="male")]
        assert has_unfilled_enums([], fields) is False

    def test_empty_string_value_returns_true(self):
        fields = [make_field("basics.gender", value="")]
        assert has_unfilled_enums(["basics.gender"], fields) is True


# ---------------------------------------------------------------------------
# has_incomplete_rows
# ---------------------------------------------------------------------------

def _ec_field(idx: int, subfield: str, value: object = None) -> VisibleField:
    return make_field(
        f"emergency_contacts[{idx}].{subfield}",
        value=value,
        section="emergency_contacts",
        repeatable_index=idx,
    )


class TestHasIncompleteRows:
    def test_zero_rows_min_rows_1_returns_true(self):
        assert has_incomplete_rows("emergency_contacts", 1, []) is True

    def test_zero_rows_min_rows_0_returns_false(self):
        """min_rows=0 asks: any started-but-incomplete row? Zero rows = no."""
        assert has_incomplete_rows("emergency_contacts", 0, []) is False

    def test_one_complete_row_min_rows_1_returns_false(self):
        fields = [
            _ec_field(0, "name", "Alice"),
            _ec_field(0, "relation", "sister"),
        ]
        assert has_incomplete_rows("emergency_contacts", 1, fields) is False

    def test_one_incomplete_row_min_rows_1_returns_true(self):
        fields = [
            _ec_field(0, "name", "Alice"),
            _ec_field(0, "relation", None),  # missing
        ]
        assert has_incomplete_rows("emergency_contacts", 1, fields) is True

    def test_min_rows_0_started_but_incomplete_returns_true(self):
        fields = [
            _ec_field(0, "name", "Alice"),
            _ec_field(0, "relation", None),
        ]
        assert has_incomplete_rows("emergency_contacts", 0, fields) is True

    def test_min_rows_0_all_rows_complete_returns_false(self):
        fields = [
            _ec_field(0, "name", "Alice"),
            _ec_field(0, "relation", "sister"),
        ]
        assert has_incomplete_rows("emergency_contacts", 0, fields) is False

    def test_readonly_field_in_row_ignored(self):
        fields = [
            _ec_field(0, "name", "Alice"),
            make_field(
                "emergency_contacts[0].id",
                required=True,
                readonly=True,
                value=None,
                section="emergency_contacts",
                repeatable_index=0,
            ),
        ]
        assert has_incomplete_rows("emergency_contacts", 1, fields) is False

    def test_two_rows_need_two_complete_one_incomplete(self):
        fields = [
            _ec_field(0, "name", "Alice"),
            _ec_field(0, "relation", "sister"),
            _ec_field(1, "name", "Bob"),
            _ec_field(1, "relation", None),  # row 1 incomplete
        ]
        assert has_incomplete_rows("emergency_contacts", 2, fields) is True

    def test_two_rows_both_complete_need_two(self):
        fields = [
            _ec_field(0, "name", "Alice"),
            _ec_field(0, "relation", "sister"),
            _ec_field(1, "name", "Bob"),
            _ec_field(1, "relation", "brother"),
        ]
        assert has_incomplete_rows("emergency_contacts", 2, fields) is False


# ---------------------------------------------------------------------------
# needs_guidance
# ---------------------------------------------------------------------------

class TestNeedsGuidance:
    def test_empty_field_returns_true(self):
        fields = [make_field("basics.dob", value=None)]
        assert needs_guidance("basics.dob", fields) is True

    def test_filled_field_returns_false(self):
        fields = [make_field("basics.dob", value="2000-01-01")]
        assert needs_guidance("basics.dob", fields) is False

    def test_field_not_found_returns_true(self):
        fields = [make_field("basics.name", value="Alice")]
        assert needs_guidance("basics.dob", fields) is True

    def test_empty_string_value_returns_true(self):
        fields = [make_field("basics.gender", value="")]
        assert needs_guidance("basics.gender", fields) is True


# ---------------------------------------------------------------------------
# form_completion_tier
# ---------------------------------------------------------------------------

class TestFormCompletionTier:
    def test_no_required_fields_returns_late(self):
        fields = [make_field("a.b", required=False, value=None)]
        assert form_completion_tier(fields) == "late"

    def test_empty_list_returns_late(self):
        assert form_completion_tier([]) == "late"

    def test_zero_percent_filled_returns_early(self):
        fields = [
            make_field("a.1", value=None),
            make_field("a.2", value=None),
            make_field("a.3", value=None),
        ]
        assert form_completion_tier(fields) == "early"

    def test_30_percent_filled_returns_early(self):
        # 3 out of 10 filled = 0.30 → early (boundary inclusive)
        fields = [make_field(f"a.{i}", value="x" if i < 3 else None) for i in range(10)]
        assert form_completion_tier(fields) == "early"

    def test_50_percent_filled_returns_mid(self):
        fields = [make_field(f"a.{i}", value="x" if i < 5 else None) for i in range(10)]
        assert form_completion_tier(fields) == "mid"

    def test_69_percent_filled_returns_mid(self):
        # 6.9/10 → below 0.70, mid
        fields = [make_field(f"a.{i}", value="x" if i < 69 else None) for i in range(100)]
        assert form_completion_tier(fields) == "mid"

    def test_70_percent_filled_returns_late(self):
        fields = [make_field(f"a.{i}", value="x" if i < 7 else None) for i in range(10)]
        assert form_completion_tier(fields) == "late"

    def test_100_percent_filled_returns_late(self):
        fields = [make_field(f"a.{i}", value="x") for i in range(5)]
        assert form_completion_tier(fields) == "late"

    def test_readonly_fields_excluded(self):
        """Readonly required fields don't count toward tier calculation."""
        fields = [
            make_field("a.1", required=True, readonly=True, value=None),  # excluded
            make_field("a.2", required=True, readonly=False, value="x"),  # 1/1 filled
        ]
        assert form_completion_tier(fields) == "late"


# ---------------------------------------------------------------------------
# @step decorator
# ---------------------------------------------------------------------------

_ALWAYS_BLOCK = "Always included text."
_INCOMPLETE_BLOCK = "Incomplete row text."
_UNFILLED_BLOCK = "Unfilled enum text."


class TestStepDecorator:
    def test_always_blocks_always_present(self):
        @step(always=[_ALWAYS_BLOCK])
        def build(visible_fields: list[VisibleField]) -> str: ...

        result = build([])
        assert _ALWAYS_BLOCK in result

    def test_function_body_not_called(self):
        called = []

        @step(always=[_ALWAYS_BLOCK])
        def build(visible_fields: list[VisibleField]) -> str:
            called.append(True)
            return "should not appear"

        build([])
        assert called == [], "Decorated function body must not be called"

    def test_name_and_doc_preserved(self):
        @step(always=[_ALWAYS_BLOCK])
        def build(visible_fields: list[VisibleField]) -> str:
            """My docstring."""
            ...

        assert build.__name__ == "build"
        assert build.__doc__ == "My docstring."

    def test_if_incomplete_included_when_condition_true(self):
        # No fields → fewer than 1 complete row → has_incomplete_rows returns True
        @step(
            always=[_ALWAYS_BLOCK],
            if_incomplete=[("emergency_contacts", 1, _INCOMPLETE_BLOCK)],
        )
        def build(visible_fields: list[VisibleField]) -> str: ...

        result = build([])
        assert _INCOMPLETE_BLOCK in result

    def test_if_incomplete_excluded_when_condition_false(self):
        # Provide a complete row
        fields = [
            _ec_field(0, "name", "Alice"),
            _ec_field(0, "relation", "sister"),
        ]

        @step(
            always=[_ALWAYS_BLOCK],
            if_incomplete=[("emergency_contacts", 1, _INCOMPLETE_BLOCK)],
        )
        def build(visible_fields: list[VisibleField]) -> str: ...

        result = build(fields)
        assert _INCOMPLETE_BLOCK not in result
        assert _ALWAYS_BLOCK in result

    def test_if_unfilled_included_when_field_empty(self):
        fields = [make_field("basics.gender", value=None)]

        @step(
            always=[_ALWAYS_BLOCK],
            if_unfilled=(["basics.gender"], _UNFILLED_BLOCK),
        )
        def build(visible_fields: list[VisibleField]) -> str: ...

        result = build(fields)
        assert _UNFILLED_BLOCK in result

    def test_if_unfilled_excluded_when_all_filled(self):
        fields = [make_field("basics.gender", value="male")]

        @step(
            always=[_ALWAYS_BLOCK],
            if_unfilled=(["basics.gender"], _UNFILLED_BLOCK),
        )
        def build(visible_fields: list[VisibleField]) -> str: ...

        result = build(fields)
        assert _UNFILLED_BLOCK not in result

    def test_multiple_always_blocks_joined(self):
        @step(always=["Block A", "Block B", "Block C"])
        def build(visible_fields: list[VisibleField]) -> str: ...

        result = build([])
        assert "Block A" in result
        assert "Block B" in result
        assert "Block C" in result

    def test_all_conditions_active(self):
        """When both if_incomplete and if_unfilled trigger, both blocks appear."""
        fields = [make_field("basics.gender", value=None)]

        @step(
            always=[_ALWAYS_BLOCK],
            if_incomplete=[("emergency_contacts", 1, _INCOMPLETE_BLOCK)],
            if_unfilled=(["basics.gender"], _UNFILLED_BLOCK),
        )
        def build(visible_fields: list[VisibleField]) -> str: ...

        result = build(fields)
        assert _ALWAYS_BLOCK in result
        assert _INCOMPLETE_BLOCK in result
        assert _UNFILLED_BLOCK in result

    def test_no_optional_args(self):
        """Decorator works with only always=."""
        @step(always=["Only block"])
        def build(visible_fields: list[VisibleField]) -> str: ...

        result = build([])
        assert result == "Only block"
