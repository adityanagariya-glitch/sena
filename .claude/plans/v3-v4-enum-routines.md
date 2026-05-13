# Plan — V3 (enum validator) + V4 (mandatory routines)

**Date:** 2026-05-12  
**Status:** Approved — executing  
**Bugs fixed:** V3 (enum validator accepts any string) + V4 (morning/evening routines called optional)

---

## 1. Executive Summary

Two onboarding-voice bugs share a common surface: schema-awareness in the validation path. V3 and V4 both stem from validators and prompt-builder helpers that consult only the rules table or scalar fields — never the schema's `options` or `repeatable.min`. The fix threads `FieldSpec`/`SectionSpec` access into `validate_field` and the next-required-field computation, extends `ValidationRejection` with an `allowed_values` field, flips two `min: 0 → 1` flags in the requirements fixture, and tightens the system prompt. No tenant boundary, Redis schema, or webhook contract changes.

---

## 2. Subtask DAG

**Wave 1 (parallel — no deps):** S1, S2, S3, S4  
**Wave 2 (parallel):** S5 (needs S1+S2), S9 (needs S3+S4)  
**Wave 3 (parallel):** S6 (needs S5), S7 (needs S1), S10 (needs S4)  
**Wave 4:** S8 (needs S7)  
**Wave 5:** S11 (needs S5,S6,S8,S9,S10)  
**Wave 6:** S12 (regression sweep)  

### S1 — Extend ValidationRejection with allowed_values
- **File:** `services/onboarding/src/onboarding/services/validators/base.py`
- **Change:** Add `allowed_values: list[str] | None = None` field to `ValidationRejection`
- **Tests:** `test_validators.py` — default None; model_dump round-trips a populated list
- **Accept:** Backward compat (default None); mypy strict passes

### S2 — StepSchema.get_field_spec() helper
- **File:** `services/onboarding/src/onboarding/models/schema_spec.py`
- **Change:** Add `get_field_spec(section_id, field_id) -> FieldSpec | None` method on `StepSchema`; handles both regular `.fields` and repeatable `.item_fields`
- **Tests:** `test_schema.py` — repeatable item_fields lookup, non-repeatable lookup, unknown returns None
- **Accept:** Returns None (not exception) for unknown pairs

### S3 — Fixture: flip routine min 0→1
- **File:** `services/onboarding/fixtures/schema_participant_requirements.json`
- **Change:** `morning_routine.repeatable.min: 0 → 1`, `evening_routine.repeatable.min: 0 → 1`
- **Tests:** `test_schema.py` — load fixture, assert sections min == 1 for both
- **Accept:** Fixture validates against StepSchema model; no other field touched

### S4 — section_min_unmet() pure helper
- **File:** `services/onboarding/src/onboarding/services/validators/sequencing.py`
- **Change:** Add `section_min_unmet(section: SectionSpec, section_values: Any) -> bool`
- **Tests:** `test_sequencing.py` — non-repeatable→False; min=0→False; min=1 + 0 rows→True; min=1 + 1 row→False; min=2 + 1 row→True
- **Accept:** Pure function, no IO; tolerates None/[]/dict for section_values

### S5 — _v_multi_enum_required: enforce options (V3)
- **File:** `services/onboarding/src/onboarding/services/validators/field_rules.py`
- **Change:** Extend `validate_field(...)` with `field_spec: FieldSpec | None = None` kwarg; inside, for multi_enum fields with field_spec.options, check each selected value case-insensitively against options; return `ValidationRejection(code="enum_invalid", ..., allowed_values=field_spec.options)` on mismatch
- **Tests:** empty→required; all-in-options→ok; one-not-in-options→enum_invalid with allowed_values; case-insensitive pass; field_spec=None→no options check
- **Accept:** Backward compat; suggested_fix populated with 2-3 examples

### S6 — tools._update_field: resolve FieldSpec, pass to validate_field; sentinel guard
- **File:** `services/onboarding/src/onboarding/services/tools.py`
- **Change:** In `_update_field`, before calling `validate_field`, resolve `fs = self._schema.get_field_spec(section_id, field_id)` and pass `field_spec=fs`; add defensive sentinel reject at entry for `field_id == '__section_min__'`
- **Tests:** mode_of_communication=['Walkie Talkies']→enum_invalid+allowed_values; ['Verbal (spoken)']→ok; field='__section_min__'→ok:false sentinel error
- **Accept:** No FUNCTION_DECLS change; sentinel logs at info

### S7 — _upsert_validation_error: persist allowed_values
- **File:** `services/onboarding/src/onboarding/services/tools.py`
- **Change:** When upserting a validation error, include `allowed_values` key when `rej.allowed_values is not None`
- **Tests:** state.pending_validation_errors[0]['allowed_values'] present after enum_invalid; absent for non-enum rejections
- **Accept:** Dedup key unchanged; backward compat

### S8 — prompt_builder: render allowed_values in error block
- **File:** `services/onboarding/src/onboarding/services/prompt_builder.py`
- **Change:** In `_render_pending_validation_errors`, when err has 'allowed_values', append `Allowed values: <comma-joined>`
- **Tests:** render fake error with allowed_values→block contains joined options; absent when key missing
- **Accept:** Full list rendered (≤9 strings)

### S9 — _compute_next_required_field: section-min short-circuit (V4)
- **File:** `services/onboarding/src/onboarding/services/prompt_builder.py`
- **Change:** At start of each section iteration, check `section_min_unmet(section, state.values.get(section.id))`; if true, return synthetic `{"section_id": section.id, "field_id": "__section_min__", "label": f"At least {section.repeatable.min} {section.label} entr(ies) required"}`
- **Tests:** morning_routine min=1 + 0 rows→synthetic returned; 1 row→scalar fields iterated normally
- **Accept:** Short-circuit before field-level iteration; sentinel `__` prefix documented

### S10 — _advance_step: section-min gate (V4)
- **File:** `services/onboarding/src/onboarding/services/tools.py`
- **Change:** After recompute_completion, BEFORE cross_rejections, iterate `self._schema.sections`; for any with `section_min_unmet`, emit `field_skipped_warning` with synthesised missing_fields and return `{ok:false, error:'section_min_unmet', sections:[...]}`
- **Tests:** advance with 0 morning_routine rows→ok:false+no webhook; with 1 row each→falls through to existing logic
- **Accept:** Webhook fire untouched; ordering: completion→section-min→pending→cross-field→fire

### S11 — System prompt: enum_invalid rule + mandatory routines numbered rule
- **File:** `services/onboarding/src/onboarding/prompts/onboarding_system.md`
- **Change:** Add Rule 13 (enum_invalid re-ask) and Rule 14 (mandatory routines) after Rule 12
- **Tests:** `test_prompt_builder.py` — build_system_prompt output contains both rule texts
- **Accept:** Numbering sequential; additive only; "MANDATORY" uppercase, "NEVER tell the participant these are optional"

### S12 — Regression sweep
- Full `pytest services/onboarding/tests/ -x -q` green
- `test_function_decls_cover_all_handlers` still passes
- Zero new failures

---

## 3. Prompt update spec (exact text for S11)

**Rule 13 — Enum option re-ask.**
When `pending_validation_errors` contains an entry with `code: "enum_invalid"`, the previous answer for that field was NOT in the allowed set and was REJECTED. Re-ask the participant using ONLY the values listed in `allowed_values`. Read 2–3 of them aloud as examples; do not invent new options; do not paraphrase the option text. Wait for the participant to choose one or more from that list, then call `update_field` with the canonical-cased string(s) exactly as they appear in `allowed_values`.

**Rule 14 — Mandatory routine sections.**
The `morning_routine` and `evening_routine` sections are MANDATORY — at least one entry in each is required before `advance_step` will succeed. NEVER tell the participant these are optional. If they say they have no routine, gently insist with a concrete example: "even something simple counts — like brushing your teeth at 7am, or watching the news before bed." Only after recording at least one entry in each section can you attempt to advance.

---

## 4. Open Questions

1. `_section_min_unmet` location → sequencing.py (recommended, avoids circular dep with prompt_builder)
2. `allowed_values` always-emit vs conditional → always-emit (None when absent) for simpler rendering
3. Verify `requirements.mode_of_communication` in `voice_coverage` (must be true for voice path to reach validator)
4. `suggested_fix` for `enum_invalid` → list 2-3 examples from options + "see allowed values"
5. Single `enum` fields (gender, plan_management) NOT in scope — politically sensitive open-text by design; separate ticket

---

## 5. Compliance notes

- V3 closes a data-quality hole (wrong string in mode_of_communication → downstream care plans affected)
- V4 makes a documented business rule enforceable (routine info feeds risk assessment)
- Human-in-the-loop: unaffected; webhook still gated by consent + completion
- Tenant isolation: unaffected — pure validators + prompt building, no new Redis keys
