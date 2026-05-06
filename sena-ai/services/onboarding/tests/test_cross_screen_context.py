"""Tests for services/cross_screen_context.py — pure module, no I/O.

Five tests per the PRD:
1. round_trip          — compress → decompress is byte-equivalent (lossless).
2. verbatim_passthrough — six high-signal fields preserved exactly.
3. empty_form_state    — empty FormState produces an empty StepSummary, not None.
4. render_snapshot     — rendered prompt block has the expected shape.
5. token_budget_smoke  — fully-populated 6-step participant renders under threshold.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from onboarding.models.cross_screen_summary import CrossScreenContext, StepSummary
from onboarding.models.form_state import FieldSource, FieldValue, FormState
from onboarding.services.cross_screen_context import (
    KEY_ALIASES,
    VERBATIM_FIELDS,
    build_summary,
    compress_residual,
    decompress,
    render_for_prompt,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _wrap(value):
    return FieldValue(value=value, source=FieldSource.voice).model_dump(mode="json")


def _make_state(values: dict, session_id: str = "sess-001") -> FormState:
    return FormState(
        session_id=session_id,
        step_id="personal_information",
        participant_id="part-001",
        tenant_id="tenant-A",
        values=values,
    )


def _populated_personal_state() -> FormState:
    return _make_state({
        "basics": {
            "name": _wrap("Sarah Chen"),
            "dob": _wrap("1990-04-12"),
            "gender": _wrap("female"),
            "phone": _wrap("+61400000000"),
            "email": _wrap("sarah@example.com"),
        },
        "address": {
            "street": _wrap("12 Pitt St"),
            "city": _wrap("Sydney"),
            "postcode": _wrap("2000"),
        },
        "emergency_contacts": [
            {"name": _wrap("Mum"), "phone": _wrap("+61400000001")},
            {"name": _wrap("Dad"), "phone": _wrap("+61400000002")},
        ],
        "goals": {
            "goals": _wrap(["independence at home", "rejoin choir"]),
        },
        "hobbies": {
            "hobbies": _wrap(["gardening", "chess", "audiobooks"]),
        },
    })


# ── 1. Round-trip property test (lossless guarantee) ─────────────────────────


class TestRoundTrip:
    def test_compress_then_decompress_preserves_residual(self):
        """The PRD's lossless guarantee: compress → decompress recovers a
        payload byte-equivalent to the original residual modulo key order.
        We assert by re-encoding both ends with sort_keys=True and comparing.
        """
        state = _populated_personal_state()

        # Exclude verbatim leaves so we exercise the residual encoding path.
        exclude = {
            "basics.name",
            "basics.dob",
            "basics.gender",
            "goals.goals",
            "hobbies.hobbies",
        }

        encoded = compress_residual(state, exclude_keys=exclude)
        assert encoded, "fixture must produce a non-empty residual"

        decoded = decompress(encoded)
        re_encoded = json.dumps(decoded, separators=(",", ":"), sort_keys=True, default=str)

        # Build the expected residual independently to assert equivalence.
        # `goals` and `hobbies` collapse to {} after the verbatim leaf is
        # stripped, so they are dropped by the `_is_meaningful` filter.
        expected = {
            "address": {"street": "12 Pitt St", "city": "Sydney", "postcode": "2000"},
            "emergency_contacts": [
                {"name": "Mum", "phone": "+61400000001"},
                {"name": "Dad", "phone": "+61400000002"},
            ],
            "basics": {
                "phone": "+61400000000",
                "email": "sarah@example.com",
            },
        }
        expected_encoded = json.dumps(expected, separators=(",", ":"), sort_keys=True)
        assert re_encoded == expected_encoded

    def test_empty_residual_round_trips(self):
        encoded = compress_residual(_make_state({}), exclude_keys=set())
        assert encoded == ""
        assert decompress(encoded) == {}

    def test_decompress_unknown_alias_passes_through(self):
        """Aliases the table doesn't recognise round-trip as their literal alias."""
        unknown = json.dumps({"zz_made_up": {"foo": 1}}, separators=(",", ":"))
        assert decompress(unknown) == {"zz_made_up": {"foo": 1}}


# ── 2. Verbatim passthrough ──────────────────────────────────────────────────


class TestVerbatimPassthrough:
    def test_six_fields_preserved_exactly(self):
        state = _populated_personal_state()
        summary = build_summary(state, step_number=1, step_label="Personal Details")
        assert summary.verbatim["name"] == "Sarah Chen"
        assert summary.verbatim["dob"] == "1990-04-12"
        assert summary.verbatim["gender"] == "female"
        assert summary.verbatim["goals"] == ["independence at home", "rejoin choir"]
        assert summary.verbatim["hobbies"] == ["gardening", "chess", "audiobooks"]
        # interests not in fixture → must be absent (not None)
        assert "interests" not in summary.verbatim

    def test_verbatim_set_is_canonical(self):
        """Verbatim field set is the PRD-specified six. Drift requires PRD update."""
        assert VERBATIM_FIELDS == frozenset(
            {"name", "dob", "gender", "goals", "hobbies", "interests"}
        )

    def test_verbatim_excluded_from_compressed(self):
        state = _populated_personal_state()
        summary = build_summary(state, step_number=1, step_label="Personal Details")
        # Verbatim leaves must not also appear inside the compressed residual.
        decoded = decompress(summary.compressed)
        assert "Sarah Chen" not in summary.compressed
        # The verbatim leaves are gone from their parent sections too.
        if "basics" in decoded:
            assert "name" not in decoded["basics"]
            assert "dob" not in decoded["basics"]
            assert "gender" not in decoded["basics"]


# ── 3. Empty FormState ────────────────────────────────────────────────────────


class TestEmptyFormState:
    def test_empty_state_yields_empty_summary_not_none(self):
        empty = _make_state({})
        summary = build_summary(empty, step_number=1, step_label="Personal Details")
        assert isinstance(summary, StepSummary)
        assert summary.verbatim == {}
        assert summary.compressed == ""
        assert summary.completion_pct == 0.0
        assert summary.session_id == "sess-001"

    def test_render_empty_bucket_returns_empty_string(self):
        assert render_for_prompt(CrossScreenContext()) == ""
        assert render_for_prompt([]) == ""


# ── 4. Render snapshot ────────────────────────────────────────────────────────


class TestRenderSnapshot:
    def _frozen_now(self) -> datetime:
        return datetime(2026, 5, 6, 12, 30, 0, tzinfo=timezone.utc)

    def test_render_contains_expected_shape(self):
        now = self._frozen_now()
        summaries = [
            StepSummary(
                step_number=1,
                step_label="Personal Details",
                completed_at=now - timedelta(minutes=12),
                session_id="sess-001",
                verbatim={
                    "name": "Sarah Chen",
                    "dob": "1990-04-12",
                    "gender": "female",
                    "goals": ["independence at home", "rejoin choir"],
                    "hobbies": ["gardening", "chess"],
                },
                compressed=json.dumps({"ec": [{"name": "Mum"}]}, separators=(",", ":")),
                completion_pct=0.83,
            ),
            StepSummary(
                step_number=2,
                step_label="Lifestyle",
                completed_at=now - timedelta(minutes=4),
                session_id="sess-002",
                verbatim={"interests": ["audiobooks"]},
                compressed="",
                completion_pct=1.0,
            ),
        ]
        text = render_for_prompt(summaries, now=now)
        assert "EARLIER IN THIS ONBOARDING" in text
        assert "Step 1 — Personal Details (completed 12 min ago):" in text
        assert "Step 2 — Lifestyle (completed 4 min ago):" in text
        assert "Name: Sarah Chen" in text
        assert "DOB: 1990-04-12" in text or "Dob: 1990-04-12" in text
        assert "Gender: female" in text
        assert "Goals: independence at home; rejoin choir" in text
        assert "Hobbies: gardening; chess" in text
        assert 'Other captured (compressed): {"ec":[{"name":"Mum"}]}' in text
        assert "Interests: audiobooks" in text


# ── 5. Token-budget smoke ─────────────────────────────────────────────────────


class TestTokenBudgetSmoke:
    def test_fully_populated_6_step_render_under_threshold(self):
        """Guard rail: a fully populated 6-step participant must produce a
        rendered prompt block well under ~1500 tokens. Approximate via 4
        chars/token; threshold 1500 tokens → 6000 chars. The PRD documents
        this as a smoke check, not a strict assertion."""
        now = datetime(2026, 5, 6, 12, 30, 0, tzinfo=timezone.utc)
        summaries: list[StepSummary] = []
        for i in range(1, 7):
            summaries.append(StepSummary(
                step_number=i,
                step_label=f"Step {i}",
                completed_at=now - timedelta(minutes=10 * i),
                session_id=f"sess-{i:03d}",
                verbatim={
                    "name": "Sarah Chen",
                    "dob": "1990-04-12",
                    "gender": "female",
                    "goals": ["a goal", "another goal", "a third goal"],
                    "hobbies": ["gardening", "chess", "audiobooks"],
                    "interests": ["volunteering", "music"],
                },
                compressed=json.dumps({
                    "ec": [{"n": "Mum", "p": "+614000000" + str(i)}],
                    "addr": {"street": "12 Pitt St", "city": "Sydney", "postcode": "2000"},
                    "med": [{"name": "ibuprofen", "dose": "400mg"}],
                }, separators=(",", ":")),
                completion_pct=0.95,
            ))
        text = render_for_prompt(summaries, now=now)
        assert text.startswith("EARLIER IN THIS ONBOARDING")
        # ~4 chars per token; 1500-token budget → 6000 char ceiling.
        assert len(text) < 6000, f"prompt block too large: {len(text)} chars"

    def test_known_aliases_table_is_stable(self):
        """The KEY_ALIASES map is the on-disk shape. Removing or renaming an
        entry breaks decompression of older summaries — only additions are
        safe. This test pins a few canonical entries so accidental deletions
        fail loudly."""
        for original, alias in [
            ("emergency_contacts", "ec"),
            ("address", "addr"),
            ("medical_history", "mh"),
            ("ndis_goals", "ng"),
            ("communication_preferences", "cp"),
        ]:
            assert KEY_ALIASES.get(original) == alias
