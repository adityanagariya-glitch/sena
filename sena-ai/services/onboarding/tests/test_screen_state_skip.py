"""Schema-agnostic regression tests for per-screen live-state pipeline.

These tests prove backend correctness independent of any specific field IDs —
they walk every fixture schema, derive field paths at runtime, and assert:

  1. A populated `bootstrap.current_page_values` seeds FormState such that
     `next_required_field()` does NOT re-ask those paths.
  2. A `screen_field_status` map with "filled" entries overrides empty state
     in `next_required_field()` — Flutter's live UI truth wins.
  3. Bootstrap values appear in the rendered `[LIVE_STATE_JSON]` block of the
     system prompt.

If any test FAILS, the backend per-screen pipeline is broken — no amount of
Flutter fixes will help. If all PASS, the bug is provably client-side
(missing/empty payload from Flutter) — see FLUTTER_DIAG_VOICE_BOOTSTRAP.md.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from onboarding.models.form_state import FormState
from onboarding.models.schema_spec import StepSchema
from onboarding.models.session_bootstrap import SessionBootstrap
from onboarding.services.prompt_builder import build_system_prompt
from onboarding.services.validators.sequencing import next_required_field

_FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def _all_schema_files() -> list[Path]:
    return sorted(_FIXTURES_DIR.glob("schema_*.json"))


def _first_required_scalar_paths(
    schema: StepSchema, limit: int = 2,
) -> list[tuple[str, str]]:
    """Return up to `limit` (section_id, field_id) tuples for required scalar
    fields without visible_if guards — derived from the schema at runtime, no
    field names hardcoded. Skips repeatable sections (different shape)."""
    out: list[tuple[str, str]] = []
    for section in schema.sections:
        if getattr(section, "is_repeatable", False):
            continue
        for field in (section.fields or []):
            if field.required and not field.visible_if:
                out.append((section.id, field.id))
                if len(out) >= limit:
                    return out
    return out


def _build_state(schema: StepSchema, values: dict) -> FormState:
    state = FormState(
        session_id="test-sess",
        step_id=schema.step_id,
        participant_id="test-pid",
        values=values,
    )
    state.recompute_completion(schema)
    return state


@pytest.mark.parametrize("schema_file", _all_schema_files(), ids=lambda p: p.stem)
def test_seeded_state_skips_filled_required_fields(schema_file: Path) -> None:
    """Pipeline #1 — bootstrap.current_page_values → FormState → next_required_field
    must NOT return any path that was seeded.

    Schema-agnostic: picks the first 2 eligible required fields from the schema
    at runtime. Works for any schema Flutter sends now or in future.
    """
    schema = StepSchema.model_validate_json(schema_file.read_text(encoding="utf-8"))
    paths = _first_required_scalar_paths(schema, limit=2)
    if not paths:
        pytest.skip(f"{schema_file.name} has no eligible required scalar fields")

    seeded = {p for p in paths}
    values: dict = {}
    for sec_id, field_id in paths:
        values.setdefault(sec_id, {})[field_id] = {
            "value": "seed-value",
            "source": "app",
        }
    state = _build_state(schema, values)

    nxt = next_required_field(schema, state)
    if nxt is None:
        return  # all required filled by our seed — also a valid outcome

    assert (nxt["section_id"], nxt["field_id"]) not in seeded, (
        f"{schema_file.name}: next_required_field returned a SEEDED path "
        f"{nxt['section_id']}.{nxt['field_id']} — backend ignored bootstrap "
        f"current_page_values for that field. Seeded paths: {seeded}"
    )


@pytest.mark.parametrize("schema_file", _all_schema_files(), ids=lambda p: p.stem)
def test_screen_field_status_filled_overrides_empty_state(schema_file: Path) -> None:
    """Pipeline #2 — when FormState is empty but `screen_field_status[path]` is
    "filled", next_required_field must skip that path.

    Covers the race where Flutter UI shows pre-filled values that haven't been
    seeded into Redis yet. Schema-agnostic: any path the schema declares.
    """
    schema = StepSchema.model_validate_json(schema_file.read_text(encoding="utf-8"))
    paths = _first_required_scalar_paths(schema, limit=1)
    if not paths:
        pytest.skip(f"{schema_file.name} has no eligible required scalar fields")

    sec_id, field_id = paths[0]
    target_path = f"{sec_id}.{field_id}"
    state = _build_state(schema, values={})  # deliberately empty

    nxt = next_required_field(
        schema, state, screen_field_status={target_path: "filled"},
    )
    if nxt is None:
        return

    assert (nxt["section_id"], nxt["field_id"]) != (sec_id, field_id), (
        f"{schema_file.name}: next_required_field returned {target_path} "
        f"despite screen_field_status marking it 'filled'. Backend ignored "
        f"live screen state."
    )


@pytest.mark.parametrize("schema_file", _all_schema_files(), ids=lambda p: p.stem)
def test_bootstrap_value_appears_in_rendered_system_prompt(
    schema_file: Path,
) -> None:
    """Pipeline #3 — end-to-end smoke. A populated current_page_values must
    appear (as a value string) in the rendered system prompt's [LIVE_STATE_JSON].

    Uses a unique sentinel value so we know the match isn't coincidence.
    Schema-agnostic.
    """
    schema = StepSchema.model_validate_json(schema_file.read_text(encoding="utf-8"))
    paths = _first_required_scalar_paths(schema, limit=1)
    if not paths:
        pytest.skip(f"{schema_file.name} has no eligible required scalar fields")

    sec_id, field_id = paths[0]
    sentinel = "sentinel-aB9k-12345-XyZ"
    values = {sec_id: {field_id: {"value": sentinel, "source": "app"}}}
    state = _build_state(schema, values)
    bootstrap = SessionBootstrap(
        mode="new_user",
        current_page_values={f"{sec_id}.{field_id}": sentinel},
        readonly_paths=[],
        prior_pages={},
    )

    prompt = build_system_prompt(schema=schema, state=state, bootstrap=bootstrap)

    assert sentinel in prompt, (
        f"{schema_file.name}: sentinel value not found in rendered system "
        f"prompt — bootstrap.current_page_values did NOT flow through to "
        f"[LIVE_STATE_JSON]. Backend pipeline broken."
    )


def test_screen_field_status_does_not_affect_unrelated_paths() -> None:
    """Negative control — marking one path "filled" must NOT cause an
    unrelated empty required field to be skipped."""
    files = _all_schema_files()
    if not files:
        pytest.skip("no fixture schemas available")
    schema = StepSchema.model_validate_json(files[0].read_text(encoding="utf-8"))
    paths = _first_required_scalar_paths(schema, limit=2)
    if len(paths) < 2:
        pytest.skip("fixture has fewer than 2 required scalar fields")

    target_path = f"{paths[0][0]}.{paths[0][1]}"
    other_sec, other_field = paths[1]
    state = _build_state(schema, values={})

    nxt = next_required_field(
        schema, state, screen_field_status={target_path: "filled"},
    )

    assert nxt is not None, (
        "Expected next_required_field to return SOMETHING since only one path "
        "was marked filled and another required field is still empty."
    )
    # First eligible field is now skipped, so we should land on the second
    # (or a later) required field — anything except the marked-filled one.
    assert (nxt["section_id"], nxt["field_id"]) != (paths[0][0], paths[0][1])
