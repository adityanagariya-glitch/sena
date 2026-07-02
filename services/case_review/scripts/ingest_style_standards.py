"""Ingest 2026May_Casenote_CIR-DummyExamples_Feedback.md into pgvector.

Creates 15 chunks across 3 new document_type values:
  - "Casenote Style Standard"     (4 chunks: Premium1, Premium2, Average, Poor)
  - "Field Description Standard"  (6 chunks: one per form section)
  - "Incident Report Standard"    (5 chunks: Verbal Escalation, Property Damage,
                                   Medication Refusal, Fall/FirstAid, Self-Harm/Critical)

Run: python scripts/ingest_style_standards.py
Verify: make audit-chunks  (expect 15 new rows in rp_ndis_policy_chunks)
"""

import asyncio
import sys
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.chunker import DocumentChunk  # noqa: E402
from ingestion.embedder import upsert_chunks  # noqa: E402
from db.session import get_db  # noqa: E402

# ── Source doc path ────────────────────────────────────────────────────────────

_SOURCE_DOC = Path(__file__).parent.parent / "2026May_Casenote_CIR-DummyExamples_Feedback.md"


# ── Chunk definitions ──────────────────────────────────────────────────────────

_CASENOTE_CHUNKS = [
    {
        "chunk_id": "style-casenote-premium-1",
        "document_type": "Casenote Style Standard",
        "category": "Casenote/Premium/CommunityAccess",
        "risk_level": "N/A",
        "document_source": "2026May_Casenote_CIR-DummyExamples_Feedback.md",
        "text": (
            "PREMIUM CASE NOTE — Community Access / Emotional Regulation\n\n"
            "Describe: Participant engaged positively throughout the majority of the shift and "
            "demonstrated ongoing progress toward several NDIS goals, including emotional regulation, "
            "community participation, communication, and independence. The shift focused on community "
            "engagement, emotional processing following interpersonal conflict at home, and social "
            "interaction with peers and staff.\n\n"
            "Observations: Participant demonstrated improved confidence engaging socially within group "
            "settings compared to previous community access shifts. While discussing frustrations, "
            "maintained an appropriate tone, remained regulated, and was able to reflect on emotions "
            "without escalation. Mood visibly improved during leisure-based conversations — became more "
            "animated, maintained stronger eye contact, and demonstrated positive social engagement.\n\n"
            "Mood: Initially mildly subdued and frustrated; presentation improved progressively "
            "throughout the shift, becoming more relaxed, engaged, and socially interactive.\n\n"
            "What went well: Participant demonstrated positive emotional insight and effectively "
            "communicated feelings relating to family conflict without escalation. Remained socially "
            "engaged throughout the shift and independently participated in multiple community-based "
            "activities.\n\n"
            "Quality indicators: Third-person clinical voice, specific observable indicators, "
            "NDIS goal references, mood trajectory (not just snapshot), detail on support strategies."
        ),
    },
    {
        "chunk_id": "style-casenote-premium-2",
        "document_type": "Casenote Style Standard",
        "category": "Casenote/Premium/AnxietyExposure",
        "risk_level": "N/A",
        "document_source": "2026May_Casenote_CIR-DummyExamples_Feedback.md",
        "text": (
            "PREMIUM CASE NOTE — Anxiety & Community Exposure\n\n"
            "Describe: Participant participated in a planned community access shift focused on gradually "
            "increasing confidence within busy public environments. At commencement, participant appeared "
            "visibly anxious regarding attending the shopping centre due to anticipated crowd levels. "
            "Observable indicators included speaking quietly, avoiding prolonged eye contact, fidgeting "
            "with sleeves, and repeatedly seeking reassurance.\n\n"
            "Observations: Participant initially appeared overwhelmed entering the shopping centre due "
            "to noise and crowd levels. Support worker implemented grounding strategies, including "
            "relocating briefly to a quieter seating area and discussing the plan in smaller steps. "
            "Following this intervention, participant appeared calmer and was able to continue "
            "participating. Compared to previous shifts, tolerated the community environment for a "
            "significantly longer period before requesting a break.\n\n"
            "What went well: Participant demonstrated increased distress tolerance within a busy "
            "environment and required fewer reassurance prompts than during previous outings. "
            "Independently engaged in brief conversations with staff and maintained participation "
            "throughout the majority of the shift.\n\n"
            "Quality indicators: Specific observable anxiety indicators, named grounding strategies, "
            "comparison to baseline, outcome measured against prior shifts."
        ),
    },
    {
        "chunk_id": "style-casenote-average-1",
        "document_type": "Casenote Style Standard",
        "category": "Casenote/Average/HouseholdSupport",
        "risk_level": "N/A",
        "document_source": "2026May_Casenote_CIR-DummyExamples_Feedback.md",
        "text": (
            "AVERAGE CASE NOTE — Household Support (competent but less detailed)\n\n"
            "Describe: Participant participated appropriately throughout the shift and completed planned "
            "household tasks. Support focused on meal preparation, cleaning, and social interaction. "
            "Participant appeared in a positive mood and was cooperative.\n\n"
            "Observations: Participant interacted appropriately with housemates and remained engaged "
            "throughout the shift. Demonstrated confidence completing cooking tasks and followed "
            "instructions safely within the kitchen environment.\n\n"
            "Mood: Positive and engaged.\n\n"
            "Quality gap: Mood is a snapshot label only (no trajectory). Observations lack specific "
            "observable indicators. Describe does not reference NDIS goals. Fields are shorter than "
            "Premium baseline — acceptable but improvable."
        ),
    },
    {
        "chunk_id": "style-casenote-poor-1",
        "document_type": "Casenote Style Standard",
        "category": "Casenote/Poor/Reference",
        "risk_level": "N/A",
        "document_source": "2026May_Casenote_CIR-DummyExamples_Feedback.md",
        "text": (
            "POOR CASE NOTE — Intentionally weak documentation (DO NOT replicate this style)\n\n"
            "Describe: Participant was ok today. We did some cleaning and talked for a while. "
            "She stayed in her room a bit but came out later.\n\n"
            "Assisted: Cleaning and lunch.\n\n"
            "Practised skill: Daily living.\n\n"
            "Independence level: Needed prompting.\n\n"
            "Observations: Participant was quiet.\n\n"
            "Mood: Low mood.\n\n"
            "What went well: Participant helped with cleaning.\n\n"
            "What needs further support: Motivation.\n\n"
            "Why this is Poor: First-person voice, vague labels ('was ok', 'was quiet'), no specific "
            "observable indicators, no NDIS goal references, no mood trajectory, no description of "
            "support strategies, no detail on barriers or prompting used. Any concerns = Yes but no "
            "explanation provided."
        ),
    },
]

_FIELD_SECTION_CHUNKS = [
    {
        "chunk_id": "style-field-section-1",
        "document_type": "Field Description Standard",
        "category": "Field/Section1/SummaryOfShift",
        "risk_level": "N/A",
        "document_source": "2026May_Casenote_CIR-DummyExamples_Feedback.md",
        "text": (
            "FIELD GUIDANCE — Section 1: Summary of Shift\n\n"
            "Describe: Brief summary of what the support worker focused on, what activities occurred, "
            "how the participant presented, and how the participant responded. Should reference relevant "
            "NDIS goals where applicable. 2-4 sentences minimum. Third-person, clinical voice."
        ),
    },
    {
        "chunk_id": "style-field-section-2",
        "document_type": "Field Description Standard",
        "category": "Field/Section2/Activities",
        "risk_level": "N/A",
        "document_source": "2026May_Casenote_CIR-DummyExamples_Feedback.md",
        "text": (
            "FIELD GUIDANCE — Section 2: Activities Completed & Skill-Building\n\n"
            "Assisted: What the worker assisted the participant with. Be specific about tasks and support type.\n\n"
            "Practised skill: Skill/s the participant practised during the shift. Name specific skills.\n\n"
            "Participant's level of independence: How independently the participant completed tasks. "
            "Use concrete descriptors: 'independently with verbal prompts only', 'required physical guidance', "
            "'completed independently for the first time'.\n\n"
            "Observations: Relevant observations about engagement, barriers, confidence, prompts needed, "
            "or progress. Must include specific observable indicators — eye contact, vocal tone, posture, "
            "response to prompts, comparison to baseline where possible."
        ),
    },
    {
        "chunk_id": "style-field-section-3",
        "document_type": "Field Description Standard",
        "category": "Field/Section3/WellbeingBehaviour",
        "risk_level": "N/A",
        "document_source": "2026May_Casenote_CIR-DummyExamples_Feedback.md",
        "text": (
            "FIELD GUIDANCE — Section 3: Well-being & Behaviour\n\n"
            "Mood: Participant's mood and emotional presentation. Include initial state AND trajectory "
            "(how it changed across the shift). Not just a snapshot label — describe observable indicators.\n\n"
            "Behavioural events: Any notable behavioural events. Describe observable behaviours, "
            "triggers, escalation timeline, staff response, and outcome. If none: 'No behavioural events observed.'\n\n"
            "Any concerns: Yes/No. If Yes, the behavioural_events or other fields must explain why."
        ),
    },
    {
        "chunk_id": "style-field-section-4",
        "document_type": "Field Description Standard",
        "category": "Field/Section4/Outcomes",
        "risk_level": "N/A",
        "document_source": "2026May_Casenote_CIR-DummyExamples_Feedback.md",
        "text": (
            "FIELD GUIDANCE — Section 4: Outcomes & Progress\n\n"
            "What went well: Positive outcomes, achievements, engagement, successful strategies. "
            "Be specific — 'completed checkout independently for the first time' not 'went well'.\n\n"
            "What needs further support: Areas requiring follow-up, repeated prompts, barriers, risks, "
            "or skills needing continued practice. Reference specific strategies or goals.\n\n"
            "Participant's comments: Direct or paraphrased participant feedback where relevant. "
            "Include verbatim quotes where available."
        ),
    },
    {
        "chunk_id": "style-field-section-5",
        "document_type": "Field Description Standard",
        "category": "Field/Section5/Safety",
        "risk_level": "N/A",
        "document_source": "2026May_Casenote_CIR-DummyExamples_Feedback.md",
        "text": (
            "FIELD GUIDANCE — Section 5: Safety / Health Monitoring\n\n"
            "Medication reminders given: Yes/No\n"
            "Safety hazards observed: Yes/No\n"
            "Any injuries: Yes/No\n"
            "Text Box: Required if medication, hazards, injuries, or health/safety matters apply. "
            "Describe what occurred, what was done, and any follow-up needed."
        ),
    },
    {
        "chunk_id": "style-field-section-6",
        "document_type": "Field Description Standard",
        "category": "Field/Section6/Notes",
        "risk_level": "N/A",
        "document_source": "2026May_Casenote_CIR-DummyExamples_Feedback.md",
        "text": (
            "FIELD GUIDANCE — Section 6: Notes / Additional Comments\n\n"
            "Carer feedback: Feedback from family, guardian, carer, stakeholder, or other relevant person. "
            "Include who provided feedback, what was said, and any relevant context.\n\n"
            "Did any incident occur: Yes/No. If Yes, a full incident report should be completed."
        ),
    },
]

_INCIDENT_REPORT_CHUNKS = [
    {
        "chunk_id": "style-incident-verbal-escalation",
        "document_type": "Incident Report Standard",
        "category": "Incident/VerbalEscalation",
        "risk_level": "Low",
        "document_source": "2026May_Casenote_CIR-DummyExamples_Feedback.md",
        "text": (
            "INCIDENT REPORT EXAMPLE — Verbal Escalation / No Physical Harm\n\n"
            "Summary: Participant became verbally escalated following a disagreement with a housemate "
            "regarding shared resource access. Escalation involved raised vocal tone, pacing, and refusal "
            "to disengage from the disagreement. Support worker implemented de-escalation strategies "
            "successfully. No physical aggression toward others occurred.\n\n"
            "Detailed description: Early indicators of emotional dysregulation included repetitive "
            "questioning, pacing, visible tension in posture, and progressively raised vocal tone. "
            "Support worker attempted early intervention through calm verbal communication, offering "
            "structured choices, and encouraging temporary separation from the shared area. Participant "
            "initially declined these supports and continued arguing verbally. During escalation, "
            "participant raised his voice further and struck the arm of a nearby chair with an open hand. "
            "No direct threats toward others were made, and no physical contact occurred. Support worker "
            "reduced environmental stimulation by guiding the other party to a separate room temporarily "
            "while continuing calm verbal reassurance. After approximately 20 minutes, participant "
            "returned to baseline presentation.\n\n"
            "Immediate actions: Verbal de-escalation, reduce environmental stimulation, temporary "
            "separation of parties, encourage emotional regulation strategies, monitor throughout, "
            "notify supervisor.\n\n"
            "Severity: Low. Reportable: No (no NDIS reportable category met)."
        ),
    },
    {
        "chunk_id": "style-incident-property-damage",
        "document_type": "Incident Report Standard",
        "category": "Incident/PropertyDamage",
        "risk_level": "Medium",
        "document_source": "2026May_Casenote_CIR-DummyExamples_Feedback.md",
        "text": (
            "INCIDENT REPORT EXAMPLE — Property Damage in SIL Home\n\n"
            "Summary: Participant became emotionally escalated following changes to planned activities "
            "due to external conditions. During escalation, participant threw an object causing property "
            "damage.\n\n"
            "Detailed description: Participant initially appeared disappointed but regulated. "
            "Approximately 10 minutes later became increasingly frustrated. Observable behaviours "
            "included pacing, raised vocal tone, rapid speech, and repeated statements regarding "
            "unfairness. During escalation, participant threw an object toward the floor causing damage. "
            "No threats toward staff occurred. Support worker maintained calm communication, provided "
            "emotional validation, and allowed participant space while monitoring. After approximately "
            "15 minutes, participant appeared calmer.\n\n"
            "Immediate actions: Remove damaged items, implement de-escalation, reduce verbal demands, "
            "support emotional regulation.\n\n"
            "Severity: Medium (property damage). Reportable: No."
        ),
    },
    {
        "chunk_id": "style-incident-medication-refusal",
        "document_type": "Incident Report Standard",
        "category": "Incident/MedicationRefusal",
        "risk_level": "Low",
        "document_source": "2026May_Casenote_CIR-DummyExamples_Feedback.md",
        "text": (
            "INCIDENT REPORT EXAMPLE — Medication Refusal\n\n"
            "Summary: Participant declined prescribed medication despite multiple prompts and discussion "
            "regarding importance of medication adherence.\n\n"
            "Detailed description: Support worker provided scheduled medication reminder as per support "
            "plan. Participant acknowledged the reminder but advised they did not feel like taking "
            "medication. Support worker calmly discussed the purpose of the medication and encouraged "
            "reconsideration. Participant remained polite but declined repeatedly. Appeared mildly "
            "withdrawn throughout the interaction. No signs of acute medical distress were observed. "
            "Participant continued participating in normal morning activities. Support worker respected "
            "participant choice while documenting refusal in accordance with medication support procedures.\n\n"
            "Immediate actions: Document refusal in medication records, monitor for changes in "
            "presentation, notify supervisor.\n\n"
            "Severity: Low. Reportable: No. Incident category: Medication issue."
        ),
    },
    {
        "chunk_id": "style-incident-fall-first-aid",
        "document_type": "Incident Report Standard",
        "category": "Incident/FallFirstAid",
        "risk_level": "Medium",
        "document_source": "2026May_Casenote_CIR-DummyExamples_Feedback.md",
        "text": (
            "INCIDENT REPORT EXAMPLE — Fall Requiring First Aid\n\n"
            "Summary: Participant experienced a minor fall while transferring within the bathroom "
            "environment. Minor skin tear observed to forearm. First aid provided.\n\n"
            "Detailed description: While transferring from shower chair toward mobility walker, "
            "participant appeared to lose balance briefly and slipped sideways against the wall before "
            "lowering partially to the floor. Support worker immediately assisted into a seated position "
            "and completed a primary assessment. Participant remained conscious, responsive, and oriented. "
            "Participant reported mild discomfort to forearm where contact occurred. A small superficial "
            "skin tear was identified. No head strike observed or reported. Participant denied dizziness, "
            "nausea, or significant pain. First aid was administered including wound cleaning and dressing "
            "application.\n\n"
            "Immediate actions: Assist safely from floor, primary assessment, administer first aid, "
            "monitor for deterioration, notify supervisor and family.\n\n"
            "Severity: Medium (injury with first aid). Reportable: Potentially — assess whether this "
            "constitutes 'Serious injury' under Category 1 (24h notification). Minor skin tear typically "
            "does not meet serious injury threshold. Incident category: Injury."
        ),
    },
    {
        "chunk_id": "style-incident-self-harm-critical",
        "document_type": "Incident Report Standard",
        "category": "Incident/SelfHarmCritical",
        "risk_level": "Critical",
        "document_source": "2026May_Casenote_CIR-DummyExamples_Feedback.md",
        "text": (
            "INCIDENT REPORT EXAMPLE — Self-Harm Disclosure / Critical Incident\n\n"
            "Summary: Participant disclosed thoughts of self-harm during emotional support conversation "
            "relating to ongoing feelings of hopelessness and social isolation. Immediate safety and "
            "escalation procedures implemented.\n\n"
            "Detailed description: Participant appeared noticeably withdrawn and emotionally flat. "
            "Observable indicators included limited eye contact, quiet speech, prolonged periods of "
            "silence, and reduced engagement. While discussing feelings of isolation and low mood, "
            "participant disclosed experiencing thoughts of self-harm over the previous several days. "
            "Stated they had been 'feeling like giving up' and reported difficulty managing emotions. "
            "Support worker remained calm and engaged in supportive conversation to assess immediate "
            "safety. Participant denied immediate intent or current plans but acknowledged ongoing "
            "intrusive thoughts. Support worker implemented critical incident procedures, maintained "
            "supervision, and contacted supervisor immediately. Participant agreed to contact mental "
            "health provider and identified safe family members.\n\n"
            "Immediate actions: Maintain supervision, supportive conversation, contact supervisor, "
            "encourage mental health supports, do not leave alone.\n\n"
            "Severity: Critical. Reportable: Yes — possible abuse/neglect or serious harm risk. "
            "Notify NDIS Commission within 24 hours if serious harm occurred. Incident category: "
            "Allegation, Abuse or neglect (if self-harm thoughts relate to service provision context)."
        ),
    },
]

ALL_CHUNKS = _CASENOTE_CHUNKS + _FIELD_SECTION_CHUNKS + _INCIDENT_REPORT_CHUNKS


def _to_doc_chunks(raw: list[dict]) -> list[DocumentChunk]:
    return [
        DocumentChunk(
            chunk_id=c["chunk_id"],
            text=c["text"],
            category=c["category"],
            document_source=c["document_source"],
            risk_level=c["risk_level"],
            document_type=c["document_type"],
        )
        for c in raw
    ]


async def _ingest() -> None:
    chunks = _to_doc_chunks(ALL_CHUNKS)
    print(f"Ingesting {len(chunks)} style-standard chunks...")

    async for db in get_db():
        await upsert_chunks(chunks, db)
        print(f"Done. {len(chunks)} chunks upserted.")
        break  # get_db is an async generator; one session is enough


if __name__ == "__main__":
    if not _SOURCE_DOC.exists():
        print(f"WARNING: source doc not found at {_SOURCE_DOC}")
        print("Proceeding with hardcoded chunks anyway...")
    asyncio.run(_ingest())
