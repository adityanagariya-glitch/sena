"""Guards for the staff onboarding flow.

Staff onboarding reuses the entire voice engine (tools, bridge, routes, base
prompt) and adds only per-step prompt fragments (`prompts/steps/staff/*.md`) plus
reference StepSchema fixtures. These tests assert:

1. Each staff step fragment loads via the same `prompt_builder` dispatch the
   runtime uses (filename == step_id).
2. No staff fragment copy-pasted client (NDIS-participant) field/section ids —
   the staff flow has no care plan, goals, or medical sections.
3. Each reference schema parses as a StepSchema and its `voice_coverage` paths
   resolve to real, voice-eligible (non-readonly) fields.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sena_common.voice.schema_spec import StepSchema
from sena_common.voice.prompt_builder import _step_rules_section

STAFF_STEP_IDS = [
    "staff_personal_information",
    "staff_role_information",
    "staff_documents",
    "staff_banking",
    "staff_policies",
]

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "staff"

# Client-flow copy-paste tells: section/field ids that belong ONLY to the
# participant flow. Their presence in a staff fragment means the client step
# file was duplicated instead of authored from the staff inventory.
_CLIENT_LEAKAGE_TOKENS = [
    "ndis_plan",
    "ndis_goals",
    "plan_info",
    "plan_management",
    "support_coordinator",
    "medical_overview",
    "medical_history",
    "preferred_languages",
    "about_me",
    "interpreter_required",
    "home_address",
    "service_address",
    "emergency_contacts",
]


@pytest.mark.parametrize("step_id", STAFF_STEP_IDS)
def test_staff_step_fragment_loads(step_id: str) -> None:
    fragment = _step_rules_section(step_id)
    assert fragment.strip(), f"empty/missing staff fragment for {step_id}"
    assert "context override" in fragment.lower(), (
        f"{step_id} missing the staff CONTEXT OVERRIDE header"
    )


@pytest.mark.parametrize("step_id", STAFF_STEP_IDS)
def test_staff_fragment_has_no_client_leakage(step_id: str) -> None:
    body = _step_rules_section(step_id).lower()
    leaked = [tok for tok in _CLIENT_LEAKAGE_TOKENS if tok in body]
    assert not leaked, f"{step_id} leaked client-flow tokens: {leaked}"


@pytest.mark.parametrize("step_id", STAFF_STEP_IDS)
def test_staff_reference_schema_parses(step_id: str) -> None:
    raw = json.loads((_FIXTURE_DIR / f"schema_{step_id}.json").read_text(encoding="utf-8"))
    schema = StepSchema.model_validate(raw)
    assert schema.step_id == step_id


@pytest.mark.parametrize("step_id", STAFF_STEP_IDS)
def test_voice_coverage_paths_resolve_to_writable_fields(step_id: str) -> None:
    raw = json.loads((_FIXTURE_DIR / f"schema_{step_id}.json").read_text(encoding="utf-8"))
    schema = StepSchema.model_validate(raw)
    for path in schema.voice_coverage:
        section_id, _, field_id = path.partition(".")
        spec = schema.get_field_spec(section_id, field_id)
        assert spec is not None, f"{step_id}: voice_coverage path '{path}' has no FieldSpec"
        assert not spec.readonly, f"{step_id}: readonly '{path}' must not be voice-covered"


def test_loader_resolves_steps_across_flow_subfolders() -> None:
    """After flow-grouping, the recursive loader resolves a client step
    (steps/client/) and a staff step (steps/staff/) by step_id alone, and
    returns empty for an unknown step."""
    assert _step_rules_section("personal_information").strip(), "client step did not resolve"
    assert _step_rules_section("staff_personal_information").strip(), "staff step did not resolve"
    assert _step_rules_section("no_such_step").strip() == "", "unknown step must be empty"
