# Swagger UI Test Cases — `/evaluate` + `/draft`

Server: `http://localhost:8084/docs`

---

## Case 1 — Clean note → `summary` only, `incident_report = null`

**Endpoint:** `POST /v1/restrictive-practices/evaluate`

**Expect:** `summary` populated (progress/risks/patterns/highlights), `incident_report = null`

```json
{
  "case_note_id": "00000000-0000-0000-0000-000000000001",
  "client_id": "client-henry-001",
  "worker_id": "worker-wilium-001",
  "shift_date": "14 May 2026",
  "shift_time": "9:00 AM - 1:00 PM",
  "worker_position": "Support Worker",
  "describe": "Accompanied Henry to the local shopping centre for weekly grocery shopping and a coffee.",
  "assisted": "Assisted with selecting items, navigating the store, and completing the self-checkout.",
  "practised_skill": "Self-checkout independently using EFTPOS card with verbal prompts only.",
  "participants_level_of_independence": "High — required only verbal prompts at checkout.",
  "observations": "Henry was engaged and confident throughout. No behavioural incidents.",
  "mood": "Calm and positive. Smiled frequently and initiated conversation with the barista.",
  "behavioural_events": null,
  "any_concerns": false,
  "what_went_well": "Henry completed checkout independently for the first time without physical guidance.",
  "what_needs_further_support": "Continue practising money handling for cash transactions.",
  "participant_comments": "Henry said he enjoyed the outing and wants to try the new café next week.",
  "medication_reminders_given": true,
  "safety_hazards_observed": false,
  "any_injuries": false,
  "carer_feedback": null,
  "incident_occurred": false
}
```

---

## Case 2 — Worker ticked incident → `summary` + `incident_report` (worker-driven, no RP)

**Endpoint:** `POST /v1/restrictive-practices/evaluate`

**Expect:** `summary` + `incident_report` both populated. `incident_report.reportable` likely `false` (no RP, no serious injury). `compliance_checks` array present.

```json
{
  "case_note_id": "00000000-0000-0000-0000-000000000002",
  "client_id": "client-sarah-002",
  "worker_id": "worker-wilium-001",
  "shift_date": "14 May 2026",
  "shift_time": "5:00 PM - 9:00 PM",
  "worker_position": "Support Worker",
  "describe": "Evening support at home including meal preparation and personal care.",
  "assisted": "Assisted with dinner preparation and evening routine.",
  "mood": "Anxious and unsettled at start of shift. Became calmer after dinner.",
  "behavioural_events": "Sarah became distressed during meal prep and threw a plate. Staff used verbal de-escalation and provided a quiet space. Participant calmed within 15 minutes.",
  "any_concerns": true,
  "what_went_well": "De-escalation was effective. Sarah was calm by end of shift.",
  "what_needs_further_support": "Review triggers around meal times. Consult behaviour support practitioner.",
  "medication_reminders_given": true,
  "safety_hazards_observed": true,
  "any_injuries": false,
  "carer_feedback": "Mother called and was informed of the incident.",
  "incident_occurred": true
}
```

---

## Case 3 — Unauthorised physical restraint → `UNAUTHORISED` verdict + `incident_report` (AI-driven)

**Endpoint:** `POST /v1/restrictive-practices/evaluate`

**Expect:**
- `verdict.outcome = "UNAUTHORISED RESTRICTIVE PRACTICE DETECTED"`
- `incident_report.reportable = true`
- `incident_report.notification_timeframe = "5 business days"`
- `incident_report.restrictive_practice_used = true`
- `incident_report.restrictive_practice_category` = Physical Restraint or Seclusion

```json
{
  "case_note_id": "00000000-0000-0000-0000-000000000003",
  "client_id": "client-james-003",
  "worker_id": "worker-dave-002",
  "shift_date": "14 May 2026",
  "shift_time": "2:00 PM - 6:00 PM",
  "worker_position": "Support Worker",
  "describe": "Community outing to the park followed by return to group home.",
  "assisted": "Assisted with transport and community access.",
  "mood": "Agitated on return. Resisted entering the house.",
  "behavioural_events": "James refused to enter the house and became physically aggressive. Staff held James by both arms and guided him inside the room and held the door closed from outside until he calmed down. No behaviour support plan was in place for this response.",
  "any_concerns": true,
  "what_went_well": "James eventually calmed after 20 minutes.",
  "what_needs_further_support": "Urgent behaviour support plan required. Current staff responses need review.",
  "medication_reminders_given": false,
  "safety_hazards_observed": false,
  "any_injuries": false,
  "incident_occurred": true
}
```

---

## Case 4 — Serious injury + restraint → 24h notification

**Endpoint:** `POST /v1/restrictive-practices/evaluate`

**Expect:**
- `incident_report.reportable = true`
- `incident_report.notification_timeframe = "24 hours"` (serious injury + restraint)
- `incident_report.any_injuries = true`

```json
{
  "case_note_id": "00000000-0000-0000-0000-000000000004",
  "client_id": "client-tom-004",
  "worker_id": "worker-anna-003",
  "shift_date": "14 May 2026",
  "shift_time": "8:00 AM - 12:00 PM",
  "worker_position": "Support Worker",
  "describe": "Morning support including breakfast and community walk.",
  "mood": "Confused and distressed in the morning.",
  "behavioural_events": "Tom became very agitated and attempted to leave the house. Staff physically blocked the doorway and restrained Tom by holding his arms to prevent him from leaving. During the restraint Tom fell and sustained a laceration to his forehead requiring first aid.",
  "any_concerns": true,
  "what_went_well": "First aid was administered promptly.",
  "what_needs_further_support": "Incident report to be submitted. Review of behaviour management strategies required urgently.",
  "medication_reminders_given": true,
  "safety_hazards_observed": true,
  "any_injuries": true,
  "injury_description": "Laceration to forehead approximately 3cm. Treated with wound closure strips on site. No hospital visit required but wound monitored.",
  "incident_occurred": true
}
```

---

## Case 5 — `/draft` alignment check (transcript pass-through)

**Endpoint:** `POST /v1/restrictive-practices/draft`

**Expect:** response includes `transcript` field echoing the input string, `uploaded_documents = null`, all 6 form sections AI-filled. Confirms round-trip compatibility — this response can be posted directly to `/evaluate`.

```json
{
  "case_note_id": "00000000-0000-0000-0000-000000000005",
  "client_id": "client-henry-001",
  "worker_id": "worker-wilium-001",
  "shift_date": "14 May 2026",
  "shift_time": "9:00 AM - 1:00 PM",
  "worker_position": "Support Worker",
  "transcript": "So today I took Henry to the shopping centre, we did the groceries, he used the self-checkout by himself which was great. He was in a good mood the whole time. No incidents. I gave him his medication reminder before we left."
}
```

---

## Swagger UI note

Paste JSON directly into the request body text box. Do NOT press Enter inside string values — use `\n` for line breaks if needed (see issues-solved/0010).
