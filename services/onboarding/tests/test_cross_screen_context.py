"""Tests for services/cross_screen_context.py — pure module, no I/O.

The cross-screen context now forwards ONLY the five allowlisted high-signal
concepts (name, dob, gender, goals, hobbies_interests) between steps.
Compressed residual encoding was removed because it produced noisy prompts
and the legacy leaf-only matching collided on shared field-ids (e.g.
emergency_contacts[].name vs basics.full_name).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from onboarding.models.cross_screen_summary import CrossScreenContext, StepSummary
from onboarding.models.form_state import FieldSource, FieldValue, FormState
from onboarding.services.cross_screen_context import (
    ALLOWLIST_PATHS,
    build_summary,
    render_for_prompt,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────


def _wrap(value):
    return FieldValue(value=value, source=FieldSource.voice).model_dump(mode="json")


def _make_state(values: dict, session_id: str = "sess-001", step_id: str = "personal_information") -> FormState:
    return FormState(
        session_id=session_id,
        step_id=step_id,
        participant_id="part-001",
        tenant_id="tenant-A",
        values=values,
    )


# ── 1. Allowlist contract ────────────────────────────────────────────────────


class TestAllowlistContract:
    def test_allowlist_paths_are_canonical(self):
        """Adding/removing entries here requires a product decision — pin them."""
        assert ALLOWLIST_PATHS == {
            ("basics", "full_name"):                "name",
            ("basics", "date_of_birth"):            "dob",
            ("basics", "gender"):                   "gender",
            ("requirements", "goals"):              "goals",
            ("requirements", "hobbies_interests"):  "hobbies_interests",
            ("ndis_goals", "goal"):                 "goals",
            ("summary", "primary_diagnosis"):       "diagnosis",
            ("summary", "blood_type"):              "blood_type",
            ("allergies", "title"):                 "allergies",
        }


# ── 2. Verbatim extraction — happy path ──────────────────────────────────────


class TestVerbatimExtraction:
    def test_basics_fields_extracted_with_concept_keys(self):
        state = _make_state({
            "basics": {
                "full_name":     _wrap("Sarah Chen"),
                "date_of_birth": _wrap("1990-04-12"),
                "gender":        _wrap("Female"),
                "email":         _wrap("sarah@example.com"),   # dropped
                "phone":         _wrap("+61400000000"),         # dropped
            },
        })
        summary = build_summary(state, step_number=1, step_label="Personal")
        assert summary.verbatim == {
            "name":   "Sarah Chen",
            "dob":    "1990-04-12",
            "gender": "Female",
        }
        assert summary.compressed == ""  # residual fully removed

    def test_requirements_goals_and_hobbies_extracted(self):
        state = _make_state({
            "requirements": {
                "goals":              _wrap("Independence at home"),
                "hobbies_interests":  _wrap("Chess and gardening"),
                "cultural_considerations": _wrap("Vegetarian"),  # dropped
            },
        }, step_id="participant_requirements")
        summary = build_summary(state, step_number=2, step_label="Requirements")
        assert summary.verbatim == {
            "goals":              "Independence at home",
            "hobbies_interests":  "Chess and gardening",
        }

    def test_ndis_repeatable_goals_collected_into_list(self):
        state = _make_state({
            "ndis_goals": [
                {"goal": _wrap("Find part-time work")},
                {"goal": _wrap("Build social circle")},
                {"goal": _wrap("Master public transport")},
            ],
        }, step_id="ndis_plan_details")
        summary = build_summary(state, step_number=3, step_label="NDIS Plan")
        assert summary.verbatim["goals"] == [
            "Find part-time work",
            "Build social circle",
            "Master public transport",
        ]


# ── 3. Regression: emergency-contact name MUST NOT pollute participant name ──


class TestEmergencyContactNameIsolation:
    def test_basics_full_name_wins_over_emergency_contact_name(self):
        """The previous leaf-only matcher grabbed emergency_contacts[0].name
        as verbatim["name"]. The new allowlist is keyed by (section, field)
        so this collision is structurally impossible.
        """
        state = _make_state({
            "basics": {"full_name": _wrap("Alice Participant")},
            "emergency_contacts": [
                {"name": _wrap("Bob Sibling"), "phone": _wrap("+61400000001")},
            ],
        })
        summary = build_summary(state, step_number=1, step_label="Personal")
        assert summary.verbatim["name"] == "Alice Participant"
        assert "Bob Sibling" not in str(summary.verbatim)

    def test_only_basics_full_name_no_emergency_contact_yields_name(self):
        state = _make_state({
            "emergency_contacts": [
                {"name": _wrap("Solo Contact")},
            ],
        })
        summary = build_summary(state, step_number=1, step_label="Personal")
        # emergency_contacts.name is NOT in allowlist → verbatim empty.
        assert "name" not in summary.verbatim


# ── 4. Empty / no-op behaviour ───────────────────────────────────────────────


class TestEmpty:
    def test_empty_state_yields_empty_summary(self):
        summary = build_summary(_make_state({}), step_number=1, step_label="Personal")
        assert isinstance(summary, StepSummary)
        assert summary.verbatim == {}
        assert summary.compressed == ""
        assert summary.completion_pct == 0.0

    def test_state_with_only_non_allowlisted_fields_yields_empty_verbatim(self):
        state = _make_state({
            "basics": {"phone": _wrap("+61400000000"), "email": _wrap("a@b.com")},
            "home_address": {"city": _wrap("Sydney"), "zip_code": _wrap("2000")},
        })
        summary = build_summary(state, step_number=1, step_label="Personal")
        assert summary.verbatim == {}

    def test_render_empty_bucket_returns_empty_string(self):
        assert render_for_prompt(CrossScreenContext()) == ""
        assert render_for_prompt([]) == ""


# ── 5. Render snapshot ───────────────────────────────────────────────────────


class TestRenderSnapshot:
    def _frozen_now(self) -> datetime:
        return datetime(2026, 5, 6, 12, 30, 0, tzinfo=UTC)

    def test_render_includes_concept_keys_only(self):
        now = self._frozen_now()
        summaries = [
            StepSummary(
                step_number=1,
                step_label="Personal Details",
                completed_at=now - timedelta(minutes=12),
                session_id="sess-001",
                verbatim={
                    "name":   "Sarah Chen",
                    "dob":    "1990-04-12",
                    "gender": "Female",
                    "goals":  ["independence at home", "rejoin choir"],
                    "hobbies_interests": "Chess and gardening",
                },
                compressed="",
                completion_pct=0.83,
            ),
        ]
        text = render_for_prompt(summaries, now=now)
        assert "EARLIER IN THIS ONBOARDING" in text
        assert "Step 1 — Personal Details (completed 12 min ago):" in text
        assert "Name: Sarah Chen" in text
        assert "Dob: 1990-04-12" in text
        assert "Gender: Female" in text
        assert "Goals: independence at home; rejoin choir" in text
        assert "Hobbies & interests: Chess and gardening" in text
        # Must NOT contain any non-allowlisted artifact from the legacy format.
        assert "Other captured" not in text
        assert "compressed" not in text


# ── 6. Token-budget smoke ────────────────────────────────────────────────────


class TestTokenBudgetSmoke:
    def test_full_6_step_render_well_under_threshold(self):
        """Six fully-populated steps must render well under ~1500 tokens.
        Approximate via 4 chars/token; threshold 1500 tokens → 6000 chars.
        """
        now = datetime(2026, 5, 6, 12, 30, 0, tzinfo=UTC)
        summaries = [
            StepSummary(
                step_number=i,
                step_label=f"Step {i}",
                completed_at=now - timedelta(minutes=10 * i),
                session_id=f"sess-{i:03d}",
                verbatim={
                    "name":   "Sarah Chen",
                    "dob":    "1990-04-12",
                    "gender": "Female",
                    "goals":  ["one", "two", "three"],
                    "hobbies_interests": "Chess and gardening",
                },
                compressed="",
                completion_pct=0.95,
            )
            for i in range(1, 7)
        ]
        text = render_for_prompt(summaries, now=now)
        assert text.startswith("EARLIER IN THIS ONBOARDING")
        assert len(text) < 6000, f"prompt block too large: {len(text)} chars"


# ── 7. Render cap ────────────────────────────────────────────────────────────


class TestRenderCap:
    def test_only_last_five_steps_rendered(self):
        now = datetime(2026, 5, 6, 12, 30, 0, tzinfo=UTC)
        # 7 steps; only steps 3..7 should render (last 5).
        summaries = [
            StepSummary(
                step_number=i,
                step_label=f"Step {i}",
                completed_at=now - timedelta(minutes=10 * (8 - i)),
                session_id=f"sess-{i:03d}",
                verbatim={"name": f"Step{i}Name"},
                compressed="",
                completion_pct=1.0,
            )
            for i in range(1, 8)
        ]
        text = render_for_prompt(summaries, now=now)
        assert "Step 1 —" not in text
        assert "Step 2 —" not in text
        assert "Step 3 —" in text
        assert "Step 7 —" in text


# ── 8. Medical concepts cross-screen (product decision 2026-06-04) ────────────


class TestMedicalConceptsCrossScreen:
    def test_medical_summary_fields_extracted(self):
        state = _make_state({
            "summary": {
                "primary_diagnosis":  _wrap("Autism Spectrum Disorder"),
                "blood_type":         _wrap("O+"),
                "primary_doctor":     _wrap("Dr Smith"),        # dropped
                "doctor_phone":       _wrap("+61400000000"),    # dropped
            },
            "allergies": [
                {"title": _wrap("Penicillin"), "description": _wrap("rash")},
                {"title": _wrap("Peanuts"),    "description": _wrap("anaphylaxis")},
            ],
        }, step_id="medical")
        summary = build_summary(state, step_number=5, step_label="Medical")
        assert summary.verbatim["diagnosis"] == "Autism Spectrum Disorder"
        assert summary.verbatim["blood_type"] == "O+"
        assert summary.verbatim["allergies"] == ["Penicillin", "Peanuts"]
        # Non-allowlisted medical fields stay scoped to the step.
        assert "Dr Smith" not in str(summary.verbatim)
        # Allergy descriptions are NOT carried (only the concise title).
        assert "anaphylaxis" not in str(summary.verbatim)

    def test_medical_concepts_render(self):
        now = datetime(2026, 5, 6, 12, 30, 0, tzinfo=UTC)
        summaries = [
            StepSummary(
                step_number=5,
                step_label="Medical",
                completed_at=now - timedelta(minutes=3),
                session_id="sess-005",
                verbatim={
                    "diagnosis":  "Autism Spectrum Disorder",
                    "blood_type": "O+",
                    "allergies":  ["Penicillin", "Peanuts"],
                },
                compressed="",
                completion_pct=1.0,
            ),
        ]
        text = render_for_prompt(summaries, now=now)
        assert "Diagnosis: Autism Spectrum Disorder" in text
        assert "Blood type: O+" in text
        assert "Allergies: Penicillin; Peanuts" in text
