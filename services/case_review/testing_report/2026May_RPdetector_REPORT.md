# SENA Restrictive Practice Detector (Demo)
## Reflective Testing & Evaluation Report

**Version:** v1.0  
**Date:** 11/05/2026

---

## 1. Purpose of Testing

Testing was conducted on the SENA Restrictive Practice Detector demo to evaluate the AI's ability to:

- identify restrictive practice indicators from natural-language case notes,
- interpret subtle and implied restrictive language,
- differentiate between supervision and restriction,
- recognise participant autonomy and safety context,
- and assess how contextual wording influences escalation outcomes.

The testing focused specifically on contextual interpretation rather than explicit keyword-only detection.

---

## 2. Testing Methodology

Testing was conducted using a deidentified baseline case note with no restrictive practice language initially present. Single-sentence modifications were then progressively introduced into the case note to test:

- subtle restrictive practice implications,
- environmental restraint indicators,
- physical restraint indicators,
- participant autonomy language,
- safety/emergency justification language,
- BSP justification language,
- and contradictory contextual information.

Each variation was independently analysed through the demo environment and documented via screenshot evidence.

---

## 3. Baseline Case Note (Control Sample)

The following case note was used as the baseline testing document prior to sentence modifications:

*\*Highlighted text indicates the sentence variation introduced for this specific AI detection test.*

---

### Case Note 1 – 01/05/2026 – 9:00 AM to 1:00 PM

**Did the Client work towards/ achieve their NDIS goals during the shift**

The participant partially worked towards their NDIS goals during today's shift. The participant engaged in community access by attending both the new and previous office locations of the service provider, demonstrating willingness to participate in activities and assist where possible. The participant also engaged in general conversation, followed directions, and returned home appropriately when feeling fatigued.

However, concerns remain regarding routine, safety, and decision-making, as the participant left the residence early in the morning without informing family members and was initially unaccounted for. This behaviour continues to present risk in relation to absconding and poor decision-making.

---

**Initial meet and greet: How did the client greet you today? What was the environment of the home? Describe the mood and actions of the client.**

When the support worker arrived, the participant was not present in the home. The support worker checked the participant's room and the remainder of the house but was unable to locate the participant.

Family members initially believed the participant was home; however, after the support worker advised otherwise, they contacted the participant's parent/guardian. The participant's parent/guardian later confirmed they had not seen the participant that morning. The support worker remained at the residence for over an hour.

As the support worker was preparing to leave, the participant returned home. The participant then engaged appropriately with the support worker and appeared calm. The participant explained they had gone for a walk to obtain cigarettes.

---

**What is the activity/activities planned for the shift today? Please describe the clients emotions, were they happy about the activities, were they conflicted about the activities? What is the clients reason for that chosen activity/activities?**

The activities for the shift included attending the service provider's office locations and assisting with any required tasks.

Upon arrival, no work was available, and the participant and support worker were redirected to another office location. No staff or tasks were available there either.

The participant remained cooperative throughout and later chose to return home as they felt tired. Once home, the participant ate lunch and chose to rest in their room.

---

**Conversations? Throughout the shift, please describe any observations of moods, behaviours during conversations, what were the topics of the conversations, moods while talking about these topics?**

General conversation occurred throughout the shift. The participant was calm and engaged.

The participant explained their absence earlier in the morning, stating they had gone to look for cigarettes.

At the end of the shift, the support worker reminded the participant of an upcoming appointment at a police station scheduled for Monday. The participant acknowledged this and stated they would remain at home and behave appropriately.

---

**Behaviours: What were the behaviours identified during the shift?**

Positive behaviours observed:

- Engaged appropriately once present
- Cooperative and followed directions
- Communicated openly regarding actions
- Returned home and settled appropriately

Concerning behaviours observed:

- Left the residence without informing family members
- Initially unaccounted for (absconding behaviour)
- Ongoing pattern of prioritising cigarette-seeking behaviour

No aggression or escalation was observed during the shift.

---

**Could you identify any triggers during the shift?**

A likely trigger identified was lack of cigarettes, which led the participant to leave the residence unsupervised.

Ongoing triggers/risk factors include:

- Impulsivity
- Lack of routine or supervision
- Substance-related behaviours

---

**End of shift: What was the clients demeanour when concluding the shift?**

At the end of the shift, the participant was calm and resting in their room.

The support worker remained until the participant's parent/guardian returned home to ensure supervision. The participant was left in a stable and safe environment.

---

**What is the plan for the next shift?**

- Reinforce importance of remaining at home and informing family/supports of whereabouts
- Support attendance at upcoming appointment
- Continue monitoring absconding behaviours and associated triggers
- Encourage structured activities and routine
- Continue supporting decision-making and safety awareness

---

## 4. Escalation Testing Matrix

| Ref | Testing Variation | Inserted Sentence | AI Outcome | Observations |
|-----|-------------------|-------------------|------------|--------------|
| A1 | Baseline Control | No inserted restrictive language | CLEAR | AI appropriately did not escalate behavioural or supervision concerns where no restrictive practice language was present. |
| A2 | Subtle Environmental Restriction | "Staff remained positioned near the front doorway and discouraged the participant from leaving the residence due to concerns regarding absconding behaviours." | UNAUT… | AI interpreted implied movement restriction and environmental control despite no explicit physical restraint wording. |
| A3 | Explicit Physical Restriction | "Staff blocked the doorway and prevented the participant from leaving." | UNAUT… | AI correctly identified overt restrictive intervention language and escalated severity appropriately. |
| A4 | Redirection / Physical Presence | "Staff positioned themselves near the doorway and redirected the participant away from leaving." | UNAUT… | AI interpreted physical positioning and redirection as restrictive intervention behaviour. |
| A5 | Close Supervision Near Exit | "Staff maintained close supervision near the exit due to ongoing absconding concerns." | UNAUT… | AI appeared sensitive to exit positioning and absconding context despite absence of explicit restriction wording. |
| A6 | Benign Safety Monitoring | "Staff remained nearby to ensure participant safety." | NO INCI… | Safety-focused and passive language appeared to suppress escalation. |
| B1 | Autonomy / Reassurance Framing | "Staff remained near the doorway to provide reassurance while allowing the participant freedom to leave if desired." | NO INCI… | Participant autonomy language significantly reduced restrictive interpretation. |
| B2 | Passive Monitoring | "Staff monitored the participant from nearby due to absconding concerns." | NO INCI… | AI appeared to distinguish monitoring from environmental restriction/control. |
| B3 | Participant Agency | "The participant independently chose to remain inside after discussion with staff." | CLEAR | Participant agency and voluntary decision-making strongly suppressed escalation. |
| B4 | Emergency Safety Context | "Staff remained near the exit temporarily due to immediate concerns regarding road safety." | NO INCI… | Emergency/safety context appeared to reduce restrictive interpretation. |
| B5 | BSP Justification Only | "Intervention aligned with approved BSP strategies." | NO INCI… | BSP reference alone did not trigger escalation. |
| B6 | Restriction + BSP Conflict Test | "Staff positioned themselves near the doorway and redirected the participant away from leaving. Intervention aligned with approved BSP strategies." | UNAUT… | AI continued detecting restrictive practice but appeared to downgrade severity when BSP justification language was introduced. |

---

## 5. Key Behavioural Findings

### Contextual Interpretation Appears Present

The AI demonstrated behaviour beyond simple keyword matching and appeared capable of contextual interpretation and semantic weighting. The detector appeared sensitive to combinations of:

- doorway positioning,
- exit proximity,
- movement restriction,
- redirection,
- and absconding-related context.

### Participant Autonomy Reduced Escalation

Statements indicating:

- participant choice,
- voluntary compliance,
- freedom to leave,
- or independent decision-making

significantly reduced escalation likelihood. This suggests the AI may be weighting participant agency heavily during interpretation.

### Emergency/Safety Context Reduced Escalation

Safety-focused wording such as:

- reassurance,
- road safety,
- temporary positioning,
- and passive monitoring

appeared less likely to trigger restrictive practice detection. This suggests the AI may be differentiating between:

- behavioural containment, and
- emergency/duty-of-care safety positioning.

### Inferential Interpretation Was Observed

In several tests, the AI appeared to infer restrictive intent despite no explicit wording stating:

- "prevented,"
- "restrained,"
- or "blocked."

This suggests the detector may be interpreting implied environmental control and coercive positioning contextually.

### Contradictory Context Produced Severity Reduction

When restrictive intervention wording was combined with: "Intervention aligned with approved BSP strategies," the AI:

- continued detecting restrictive practice,
- but reduced the risk level from HIGH to LOW.

This suggests competing contextual weighting may already exist within the model logic.

---

## 6. Risks & Concerns Identified

### Potential Overinterpretation of Intent

The AI occasionally inferred restrictive intent beyond explicitly documented wording. While potentially useful for safeguarding, this may increase false-positive risk in nuanced support environments.

### Limited Ambiguity Handling

The current model appears heavily binary once restrictive thresholds are crossed. There was limited evidence of:

- uncertainty handling,
- confidence scaling,
- or "possible restrictive practice" style outputs.

### Authorisation Verification Gap

The detector identified restrictive intervention indicators but did not appear capable of:

- verifying active PBSP authorisation,
- checking uploaded restrictive practice approvals,
- confirming expiry dates,
- or differentiating between unauthorised practice and potentially authorised but undocumented practice.

This was particularly evident in the BSP conflict test.

### Operational Documentation Risk

Overly aggressive escalation may unintentionally encourage:

- defensive documentation,
- wording avoidance,
- or reduced reporting transparency by staff.

This may become operationally significant in real-world environments if not balanced carefully.

---

## 7. Recommendations & Enhancement Suggestions

### Confidence/Probability Scaling

Consider introducing outputs such as:

- Possible Restrictive Practice Detected
- Moderate Confidence
- Administrative Review Recommended

rather than purely binary escalation states.

### Contradiction Recognition Layer

Where restrictive language exists alongside:

- PBSP references,
- practitioner guidance,
- or authorisation wording,

the system should potentially flag for administrative review, rather than automatically classify as unauthorised.

### Explainability Layer

Future iterations may benefit from displaying:

- detected trigger phrases,
- contextual reasoning,
- suppression factors,
- and escalation rationale.

This would improve staff understanding, audit defensibility, and organisational trust in the AI output.

### Administrative Investigation Prompts

Where restrictive indicators are identified, the system could prompt management to verify:

- PBSP uploads,
- interim PBSP status,
- restrictive practice authorisations,
- expiry dates,
- and practitioner approvals.

### Evidence Cross-Referencing

Future development could allow the detector to cross-reference:

- participant PBSP records,
- restrictive practice registers,
- uploaded approvals,
- and participant-specific authorisations

before determining whether a practice is authorised or unauthorised.

---

## 8. Screenshot Reference Index

| Screenshot Ref | Description |
|----------------|-------------|
| A1 | Baseline Control |
| A2 | Subtle Environmental Restriction |
| A3 | Explicit Physical Restriction |
| A4 | Redirection / Physical Presence |
| A5 | Close Supervision Near Exit |
| A6 | Benign Safety Monitoring |
| B1 | Autonomy / Reassurance Framing |
| B2 | Passive Monitoring |
| B3 | Participant Agency |
| B4 | Emergency Safety Context |
| B5 | BSP Justification Only |
| B6 | Restriction + BSP Conflict Test |

---

## 9. Final Reflection

The testing demonstrated promising contextual interpretation capabilities beyond simple keyword detection. The detector appeared capable of recognising:

- implied environmental restriction,
- participant autonomy,
- emergency safety framing,
- and contextual behavioural control indicators.

The AI also appeared capable of inferential reasoning, particularly where restrictive intent was implied rather than explicitly stated.

The most significant future opportunity identified is the development of:

- ambiguity handling,
- authorisation verification,
- evidence cross-referencing,
- and explainability mechanisms

to support operational accuracy, compliance confidence, and safe real-world implementation. Overall, the current demo appears to be a strong foundational step toward a highly sophisticated restrictive practice detection system within the SENA CRM environment.
