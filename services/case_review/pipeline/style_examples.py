"""Ultra-compact few-shot style snippets for all LLM prompts.

Single source of truth — import these constants into every prompt file.
All snippets are STYLE REFERENCES only; models must NOT copy names or verbatim text.
Sourced from 2026May_Casenote_CIR-DummyExamples_Feedback.md (client gold-standard doc).
"""

# ── Style Guide (prepended to every prompt) ───────────────────────────────────

STYLE_GUIDE = """\
WRITING STYLE — MANDATORY:
- Third-person, clinical, objective voice ("Participant demonstrated…", NOT "He was ok…")
- Past tense, complete sentences, no abbreviations
- Specific observable indicators (e.g. "raised vocal tone", "avoided eye contact") not vague labels ("upset")
- No subjective judgements ("seemed fine", "was good") — describe observable behaviours only
- Professional NDIS documentation register throughout
"""

# ── Triage few-shot (2 examples — clean + RP) ─────────────────────────────────

FEW_SHOT_TRIAGE = """\
STYLE EXAMPLES (illustrating the difference between clean and flagged notes):

CLEAN EXAMPLE:
"Participant engaged positively throughout the community access shift. No aggressive, unsafe, or \
escalated behaviours observed. Mild emotional distress was identified early relating to conflict at \
home; however, participant remained regulated and responsive to support strategies."
→ flagged: false

FLAGGED EXAMPLE:
"Participant became physically aggressive. Staff held participant by both arms and guided him \
inside the room and held the door closed from outside until he calmed down. No behaviour support \
plan was in place for this response."
→ flagged: true, action_summary: "Staff physically restrained participant by holding arms and \
secured room exit — possible Physical Restraint and Seclusion without BSP authorisation."
"""

# ── Summary few-shot (6 bullets from Premium Note 2 — Sophie Bennett) ─────────

FEW_SHOT_SUMMARY = """\
STYLE EXAMPLE (Premium-quality shift summary — use this REGISTER, not these details):

progress_identified:
  - "Participant demonstrated increased distress tolerance within a busy community environment"
  - "Participant required fewer reassurance prompts than during previous outings"
  - "Participant independently engaged in brief conversations with service staff"

potential_risks:
  - "Ongoing anxiety triggers related to crowded public environments"

patterns_detected:
  - "Paced community exposure strategy continues to improve participation duration"

flagged_highlights:
  - "Sophie initially appeared overwhelmed entering the shopping centre due to noise and crowd levels"
  - "Support worker implemented grounding strategies, including relocating briefly to a quieter seating area"
"""

# ── Drafter few-shot (field guidance + Premium vs Poor contrast) ───────────────

FEW_SHOT_DRAFTER = """\
FIELD QUALITY STANDARD — use this to guide extraction quality:

DESCRIBE field — what good looks like:
  PREMIUM: "Participant engaged positively throughout the majority of the shift and demonstrated \
ongoing progress toward several NDIS goals, including emotional regulation, community participation, \
communication, and independence. The shift focused on community engagement and emotional processing \
following interpersonal conflict at home."
  POOR: "Participant was ok today. We did some cleaning and talked for a while."

Rule: Premium describe fields are 2–4 sentences, name specific NDIS goals, describe the participant's \
presentation and the shift focus. Poor describe fields are vague, use first person, and lack clinical detail.

OBSERVATIONS field — what good looks like:
  PREMIUM: "Participant demonstrated improved confidence engaging socially within group settings. \
While discussing frustrations, maintained an appropriate tone, remained regulated, and was able to \
reflect on emotions without escalation."
  POOR: "Participant was quiet."

Rule: Observations must include specific observable indicators (eye contact, vocal tone, posture, \
engagement level) and note any change from baseline.

MOOD field — what good looks like:
  PREMIUM: "Initially mildly subdued and frustrated; presentation improved progressively throughout \
the shift, becoming more relaxed, engaged, and socially interactive."
  POOR: "Low mood."

Rule: Mood entries must note initial state AND trajectory, not just a snapshot label.
"""

# ── Incident report few-shot (Section 3 from Incident Report 1 — Verbal Escalation) ──

FEW_SHOT_INCIDENT = """\
STYLE EXAMPLE — Detailed incident description (use this REGISTER, not these details):

"At approximately 6:20 PM, participant and housemate became involved in a disagreement regarding \
shared use of facilities. Early indicators of emotional dysregulation included repetitive questioning, \
pacing, visible tension in posture, and progressively raised vocal tone. Support worker attempted \
early intervention through calm verbal communication, offering structured choices, and encouraging \
temporary separation from the shared area. Participant initially declined these supports and continued \
escalating verbally. During escalation, participant raised his voice further and struck the arm of \
a nearby chair with an open hand. No direct threats toward others were made, and no physical contact \
occurred between participants. Support worker reduced environmental stimulation by guiding the other \
party to a separate room temporarily while continuing calm verbal reassurance. After approximately \
20 minutes, participant returned to baseline presentation."

Key elements: exact time, specific observable indicators, staff actions in sequence, outcome timeline.
"""

# ── Evaluator few-shot (clinical reasoning style) ─────────────────────────────

FEW_SHOT_EVAL_REASONING = """\
CLINICAL REASONING STYLE EXAMPLE (use this register, not these details):

"The case note documents that staff physically held the participant by both arms and subsequently \
held the door closed to prevent exit — these phrases constitute explicit Physical Restraint and \
Seclusion under NDIS (Regulated Restrictive Practices) Rules 2014. No reference to a Behaviour \
Support Plan or practitioner authorisation is present. The participant's subsequent calming does not \
constitute retrospective authorisation. Confidence: High."

Key elements: cite exact phrases from the note, name the specific NDIS category, note presence or \
absence of authorisation, state confidence with justification.
"""
