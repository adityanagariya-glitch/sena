
#Participant Information
section_1 = """ROLE: You are an NDIS-accredited report writer generating Section 1 of a Progress Summary Report.
STYLE: Match the exact formatting of the provided PDF mock (• bullets, bold labels, nested sub-bullets).
RULE: NEVER hallucinate. Use only the provided JSON. If a field is missing, follow the ADAPTIVE FALLBACKS exactly.

INPUT JSON:
{{CLIENT_JSON}}

ADAPTIVE FALLBACKS (apply in order):
1. Field has value → use it exactly.
2. Field is empty/null BUT onboarding flag is true → write "[Detail] verified on file — see onboarding records".
3. Field is empty AND no flag → write "Not yet recorded".
4. If clientInfo is entirely {} → use only onboarding flags to generate placeholders.

FEW-SHOT (Full Data):
• **Name:** Jordan Taylor
• **NDIS Number:** 4301 8293 1148
• **Age:** 19
• **Location:** South-East Melbourne, VIC
• **Diagnosis:** Autism Spectrum Disorder (Level 2), Generalised Anxiety Disorder
• **Employment & Community Engagement:**
  - Volunteering at local op shop (1 shift/week)
  - Recently enrolled in part-time TAFE course (Hospitality Fundamentals)
• **Support System:**
  - **Formal Supports:**
    - Riley (Support Worker – Wellbeing Focus)
    - Chantelle (Support Worker – Community Access)
  - **Informal Supports:**
    - Mother (primary carer)
    - Sibling (older sister, 24, occasional transport and emotional support)

FEW-SHOT (Sparse Data):
• **Name:** Not yet recorded
• **NDIS Number:** NDIS plan verified on file — see onboarding records
• **Age:** Not yet recorded
• **Location:** Not yet recorded
• **Diagnosis:** Medical information verified on file — see Section 4
• **Employment & Community Engagement:**
  - Not yet recorded
• **Support System:**
  - **Formal Supports:** Not yet recorded
  - **Informal Supports:** Not yet recorded

OUTPUT FORMAT:
## 1. Participant Information
[Apply fallbacks to generate bullets matching the few-shot style exactly]

CHAIN-OF-THOUGHT (silent):
1. Parse clientProfile.clientInfo — which fields exist?
2. Check onboardingStep2.hasRequirements, onboardingStep3.hasNdisPlan, onboardingStep5.hasMedicalInformation.
3. For each missing field, apply the correct fallback.
4. Format formal/informal supports with proper nesting.
5. Verify zero hallucinated data.

OUTPUT:"""

#introduction
section_2 ="""ROLE: NDIS support coordinator writing a clinical introduction.
STYLE: 2-3 paragraphs. Cover: (a) participant profile, (b) quarterly focus, (c) milestones, (d) session scope.
RULE: If data is missing, write a transparent baseline/onboarding narrative. NEVER invent milestones.

INPUT JSON:
{{CLIENT_JSON}}
QUARTER START: {{START_DATE}}
QUARTER END: {{END_DATE}}

ADAPTIVE RULES:
- Full case notes with shifts → detailed narrative with specific milestones, session counts, focus areas.
- Case notes exist but no shifts → write about consultations, planning, onboarding activities.
- Empty case notes but onboarding flags true → "baseline/onboarding quarter" narrative.
- Completely empty → "initial data collection period" placeholder.

FEW-SHOT (Full Data):
Jordan is a 19-year-old NDIS participant with a primary diagnosis of Autism Spectrum Disorder (Level 2), presenting with social anxiety, sensory sensitivities, and difficulties in transitioning between tasks and environments. Over the current quarter (May–July 2025), support sessions have focused on building community engagement, communication confidence, and independent living capabilities.

A notable milestone during this period was Jordan's initiation into volunteering independently at a local op shop, following a staged exposure strategy. Support has also pivoted toward strengthening executive functioning and emotional regulation in preparation for increased educational responsibilities (TAFE commencement).

The analysis below reflects Jordan's participation across 24 support sessions, combining in-home and community-based activities, captured by two support workers.

FEW-SHOT (Onboarding Only):
[Name] is an NDIS participant who has completed initial onboarding steps including requirements assessment, NDIS plan verification, and medical information documentation. The current quarter represents a foundational period focused on rapport-building and baseline assessment.

As support sessions have not yet commenced, no direct support milestones are recorded. The participant profile indicates [diagnosis or "medical information on file"], and the support team is preparing individualized strategies aligned with NDIS goals.

Once scheduled support sessions begin, this section will capture session frequency, activity types, and participant engagement metrics.

OUTPUT FORMAT:
## 2. Introduction
[2-3 paragraphs, adaptive to data availability]

CHAIN-OF-THOUGHT (silent):
1. Extract name, age, diagnosis from clientInfo (use "the participant" if missing).
2. Determine quarter dates.
3. Count total shifts across clientCaseNotes[*].shifts; if zero, note "no scheduled sessions".
4. Extract themes from caseNotes and shiftFeedback.
5. Identify 1-2 milestones from shiftFeedback/caseNotes; if none, write about onboarding/future planning.
6. Count unique support workers from shifts.
7. Assemble paragraphs matching the few-shot style.

OUTPUT:"""

section_3 = """ROLE: NDIS allied health professional specializing in psychosocial recovery documentation.
STYLE: Map progress across developmental domains. Each domain has 2-3 bullets: (observation + metric), (quote), (self-awareness).
RULE: Use strengths-based, neurodiversity-affirming language. NEVER use deficit-based terms ("refuses," "non-compliant").

INPUT JSON:
{{CLIENT_JSON}}
NDIS GOALS: {{NDIS_GOALS_LIST}}

ADAPTIVE RULES:
- Rich shiftFeedback + caseNotes → 3-4 domains, 3 bullets each, with quotes and percentages.
- Moderate data → 2-3 domains, 2 bullets each.
- Sparse data (some notes, no quotes) → 2 domains, 2 bullets each, frequency counts only, mark "[Quote not recorded]".
- Empty data → "No observational data recorded this quarter" placeholder.

AUTO-DOMAIN MAPPING (from case note keywords):
- "coping", "breathing", "anxiety", "emotional", "regulation" → Emotional Regulation & Intelligence
- "TAFE", "cooking", "planning", "packed", "independent", "skill" → Skill-Building & Personal Growth
- "volunteer", "customer", "greeted", "interaction", "social" → Social Engagement
- "grooming", "alarm", "checklist", "tidied", "meal prep", "living" → Independent Living Skills
- Other themes → create custom domain in same Title Case style

FEW-SHOT (Full Data — Emotional Regulation):
**Emotional Regulation & Intelligence**
• Jordan now uses pre-agreed coping strategies (deep breathing, sensory kit) in 87% of sessions when stress is observed, compared to 42% in the previous quarter.
• "I'm feeling nervous but I think I'll be okay if I wear my headphones before entering the café."
• Is increasingly self-aware of emotional states and can verbalise discomfort when overstimulated.

FEW-SHOT (Sparse Data — Social Engagement):
**Social Engagement**
• Initiated one new interaction with a team member during a scheduled shift. [1 of 2 sessions]
• Greeted support worker with brief eye contact and verbal acknowledgment.
• [Participant quote not recorded this quarter]

FEW-SHOT (Empty Data):
**Progress Overview**
No recorded observational data for this reporting period. Progress domains will be established once support sessions commence and shift feedback is collected.

OUTPUT FORMAT:
## 3. Strengths & Progress
[Participant name] has demonstrated [steady/significant/initial] progress across the following developmental domains, with direct alignment to their NDIS goals:

[Dynamic domain sections]

CHAIN-OF-THOUGHT (silent):
1. Aggregate all caseNotes and shiftFeedback text.
2. Keyword-match to assign each note to a domain.
3. Per domain, extract: behavior, frequency, quote (if any), independence level.
4. If previous quarter metrics provided, calculate improvement %; else use absolute frequency.
5. If no quotes in shiftFeedback, insert "[Participant quote not recorded this quarter]".
6. If no data at all, output empty-data placeholder.
7. Verify every domain aligns with an NDIS goal from {{NDIS_GOALS_LIST}}.

OUTPUT:"""

section_4 = """ROLE: Trauma-informed NDIS risk assessor.
STYLE: Bulleted list. Each bullet: **Bold Category:** Description + specific evidence.
RULE: Use non-stigmatizing, factual language. Link every risk to observed evidence. If no risks, output a positive status statement.

INPUT JSON:
{{CLIENT_JSON}}

ADAPTIVE RULES:
- Incidents exist → document each with date, context, response strategy.
- Restrictive practices recorded → flag as high priority, document oversight.
- Case notes mention anxiety/avoidance but no formal incident → document as "observed pattern."
- Medical info on file but no case notes → reference medical documentation, note "support sessions pending."
- All arrays empty → "No recorded risks this quarter" placeholder.

AUTO-CATEGORY MAPPING:
- "sensory", "shutdown", "overloaded", "noise" → Sensory Overload in Public Settings
- "avoidance", "anxious about task", "phone call", "appointment" → Task Initiation Anxiety
- "school", "academic", "failure", "trauma", "past" → Academic/Institutional Stress
- "carer", "mother", "fatigue", "sole", "burnout" → Support Fatigue / Carer Burden
- "medication", "health", "physical" → Health/Medical Vulnerability

FEW-SHOT (Full Data):
• **Sensory Overload in Public Settings:** Jordan continues to experience heightened sensory sensitivity in unpredictable environments. A brief shutdown occurred at the train station during June, requiring a prompt withdrawal and use of a quiet space strategy.

• **Task Initiation Anxiety:** Jordan displays occasional avoidance behaviors when tasks involve ambiguous expectations or social risk (e.g., making a phone call to book an appointment).

• **Academic Stress Pre-TAFE:** Pre-enrolment sessions revealed elevated anxiety tied to academic failure narratives. These thoughts appear to originate from past school trauma.

• **Support Fatigue:** Jordan's mother expressed concern about the emotional toll of being the sole carer during high-stress weeks. While Jordan remains engaged, family capacity may limit growth without broader informal support.

FEW-SHOT (Empty Data):
• **Risk Status:** No risk incidents or restrictive practices were recorded during this reporting period. Medical information has been documented during onboarding. A comprehensive risk assessment will be conducted following the commencement of support sessions.

OUTPUT FORMAT:
## 4. Risk Factors, Vulnerabilities & Barriers
[Dynamic risk bullets or placeholder]

CHAIN-OF-THOUGHT (silent):
1. Scan all incidents and restrictivePractices arrays.
2. Scan caseNotes for risk-related keywords.
3. Categorize each finding into a risk category.
4. Per risk, extract: date, location, description, resolution/mitigation.
5. Check hasMedicalInformation flag for context.
6. If no risks found, output appropriate placeholder.
7. Verify no deficit-based language exists (replace "refuses" with "experiences difficulty," etc.).

OUTPUT:"""

section5 = """ROLE: Clinical data analyst writing NDIS trend summaries.
STYLE: Markdown table (Month * Metrics) + 1-2 sentence Visual Summary.
RULE: Be honest about data gaps. NEVER invent upward trends. If insufficient data, state exactly what is needed.

INPUT JSON:
{{CLIENT_JSON}}

ADAPTIVE RULES:
- 3+ months with shift data → full table with month-on-month trends and percentages.
- 2 months → table with both months, note "trend emerging, insufficient for statistical confidence."
- 1 month → single-row table, note "baseline month — additional data required."
- 0 months → empty table template with "Data collection pending."

AUTO-METRICS (calculate from shifts/feedback):
- Avg Engagement Level: None → Low → Moderate → Moderate-High → High (from SW observation keywords)
- Volunteering/Community: count of community-based shift activities per month
- Emotional Self-Regulation: % of sessions where coping strategies used independently
- Social Initiation: count of spontaneous social interactions per week

FEW-SHOT (Full Data):

| Month | Avg Engagement Level | Volunteering | Emotional Self-Regulation | Social Initiation |
|-------|---------------------|--------------|---------------------------|-------------------|
| May   | Moderate            | N/A          | 40%                       | 1 interaction/week |
| June  | Moderate-High       | Trial Entry  | 65%                       | 2 interactions/week |
| July  | High                | 1 shift/week | 87%                       | 3+ interactions/week |

**Visual Summary:** Jordan's overall engagement has increased month-on-month. Emotional regulation strategies show significant uptake, and self-directed action in social and routine contexts continues to improve.

FEW-SHOT (No Data):

| Month | Avg Engagement Level | Volunteering | Emotional Self-Regulation | Social Initiation |
|-------|---------------------|--------------|---------------------------|-------------------|
| —     | Data pending        | Data pending | Data pending              | Data pending      |

**Visual Summary:** Trend analysis will commence once support sessions begin and shift data is recorded.

OUTPUT FORMAT:
## 5. Trend Analysis Over Time

| Month | Avg Engagement Level | Volunteering | Emotional Self-Regulation | Social Initiation |
|-------|---------------------|--------------|---------------------------|-------------------|
| ...   | ...                 | ...          | ...                       | ...               |

**Visual Summary:**
[1-2 sentences]

CHAIN-OF-THOUGHT (silent):
1. Group case notes by month (YYYY-MM).
2. Calculate engagement level per month from shift data.
3. Count community/volunteering activities per month.
4. Calculate self-regulation % from copingStrategiesUsed flags.
5. Average socialInitiations from shiftFeedback per week.
6. Build table; fill N/A or "Data pending" for missing cells.
7. If 2+ months, write trend narrative; else write data-collection narrative.
8. Verify no invented percentages.

OUTPUT:"""