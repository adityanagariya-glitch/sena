"""Heuristic case note quality scorer — zero LLM cost.

Scores a CaseNoteInput against Premium/Average/Poor word-count and language
baselines derived from 2026May_Casenote_CIR-DummyExamples_Feedback.md.

Returns (score: float 0.0-1.0, label: str, gaps: list[str]).
Labels: "Premium" (≥0.75), "Average" (0.45-0.74), "Poor" (<0.45).
"""

from __future__ import annotations

from models.schemas import CaseNoteInput

# Clinical language markers present in Premium notes
_PREMIUM_MARKERS = {
    "demonstrated", "observed", "indicated", "appeared", "presented",
    "implemented", "regulated", "facilitated", "maintained", "engaged",
    "escalation", "de-escalation", "dysregulation", "baseline",
    "independently", "verbal prompts", "physical guidance", "reassurance",
    "participated", "initiated", "communicated", "responded",
}

# Vague terms common in Poor notes
_POOR_MARKERS = {
    "was ok", "ok today", "was good", "was fine", "was quiet", "did some",
    "talked for", "seemed", "a bit", "stayed in",
}

# Premium baseline word counts per field (sourced from Premium Note 1 + 2)
_PREMIUM_BASELINES: dict[str, int] = {
    "describe": 60,
    "assisted": 20,
    "practised_skill": 15,
    "participants_level_of_independence": 15,
    "observations": 40,
    "mood": 15,
    "behavioural_events": 20,
    "what_went_well": 25,
    "what_needs_further_support": 15,
}

# Section names for gap messages
_SECTION_LABELS: dict[str, str] = {
    "describe": "Section 1 (Describe)",
    "assisted": "Section 2 (Assisted)",
    "practised_skill": "Section 2 (Practised Skill)",
    "participants_level_of_independence": "Section 2 (Independence Level)",
    "observations": "Section 2 (Observations)",
    "mood": "Section 3 (Mood)",
    "behavioural_events": "Section 3 (Behavioural Events)",
    "what_went_well": "Section 4 (What Went Well)",
    "what_needs_further_support": "Section 4 (What Needs Further Support)",
}


def _word_count(text: str | None) -> int:
    if not text:
        return 0
    return len(text.split())


def _richness_sub_score(note: CaseNoteInput) -> float:
    """Compare word counts against Premium baselines; returns 0.0-1.0."""
    scores: list[float] = []
    for field, baseline in _PREMIUM_BASELINES.items():
        value = getattr(note, field, None)
        wc = _word_count(value)
        if baseline > 0:
            scores.append(min(1.0, wc / baseline))
    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def _completeness_sub_score(note: CaseNoteInput) -> float:
    """Fraction of the 9 scored sections that have any content; returns 0.0-1.0."""
    filled = sum(
        1 for field in _PREMIUM_BASELINES
        if _word_count(getattr(note, field, None)) > 0
    )
    return filled / len(_PREMIUM_BASELINES)


def _tone_sub_score(note: CaseNoteInput) -> float:
    """Presence of clinical markers minus penalty for poor markers; returns 0.0-1.0."""
    all_text = note.to_text().lower()

    premium_hits = sum(1 for marker in _PREMIUM_MARKERS if marker in all_text)
    poor_hits = sum(1 for marker in _POOR_MARKERS if marker in all_text)

    # Expect at least 5 premium markers for a 0.8+ tone score
    tone = min(1.0, premium_hits / 5.0)
    # Each poor marker deducts 0.1
    tone = max(0.0, tone - poor_hits * 0.1)
    return tone


def _gap_messages(note: CaseNoteInput) -> list[str]:
    """Return plain-English suggestions for underfilled sections."""
    gaps: list[str] = []
    for field, baseline in _PREMIUM_BASELINES.items():
        value = getattr(note, field, None)
        wc = _word_count(value)
        label = _SECTION_LABELS.get(field, field)
        if wc == 0:
            gaps.append(f"{label} is empty - add content before submission")
        elif wc < baseline // 2:
            gaps.append(
                f"{label} is brief ({wc} words) - add specific observable details "
                f"(aim for ~{baseline} words)"
            )
    return gaps


def score_note(note: CaseNoteInput) -> tuple[float, str, list[str]]:
    """Return (score, label, gaps) for the given case note.

    score: 0.0-1.0
    label: "Premium" | "Average" | "Poor"
    gaps: list of actionable gap messages for the worker
    """
    richness = _richness_sub_score(note)
    completeness = _completeness_sub_score(note)
    tone = _tone_sub_score(note)

    # Weighted aggregate: completeness 40%, richness 40%, tone 20%
    score = round(completeness * 0.4 + richness * 0.4 + tone * 0.2, 3)

    if score >= 0.75:
        label = "Premium"
    elif score >= 0.45:
        label = "Average"
    else:
        label = "Poor"

    gaps = _gap_messages(note)

    return score, label, gaps
