---
id: 0018
title: bsp_mentioned_in_note always True — alert_required never fires for UNAUTHORISED cases
date: 2026-05-13
symptom_keywords: alert_required False UNAUTHORISED bsp_mentioned_in_note True negative mention graph pipeline alert never fires
files_affected: pipeline/graph.py
---

## Symptom

`alert_required` is `False` for every UNAUTHORISED restrictive practice case, even when:
- `cross_check.authorisation_status == "Unauthorised Restrictive Practice"`
- `evaluator.incident_detected == True`
- `evaluator.confidence == ConfidenceLevel.HIGH`
- `evaluator.policy_violation_risk == "Critical"`

All 8 form API test scenarios that should have `alert_required=True` return `False`.

## Root Cause

The `alert_required` condition in `pipeline/graph.py` included `not evaluator.bsp_mentioned_in_note`:

```python
alert_required = (
    cross_check is not None
    and cross_check.authorisation_status == AuthorisationStatus.UNAUTHORISED
    and evaluator is not None
    and evaluator.confidence == ConfidenceLevel.HIGH
    and not evaluator.bsp_mentioned_in_note   # ← THIS GATE
)
```

The evaluator prompt instructs the model: *"check whether the case note explicitly references a Behaviour Support Plan, PBSP, practitioner approval, authorisation, or BSP-aligned strategy."*

The model correctly detects BSP mentions — but also sets `bsp_mentioned_in_note: true` for **negative mentions** like:
- "No behaviour support plan was available on site"
- "BSP review recommended" (case note flags the absence)
- "No BSP or practitioner authorisation is referenced" (evaluator's own reasoning leaking into the field)

Because every flagged case note either mentions BSP (negatively) or the evaluator's reasoning quotes BSP absence, `bsp_mentioned_in_note` is `True` in nearly 100% of cases, permanently blocking `alert_required`.

## Fix

Remove `not evaluator.bsp_mentioned_in_note` from the `alert_required` condition. The `cross_check` SQL lookup is the authoritative BSP authority — it queries the actual `behaviour_support_plans` table for an active record matching `(client_id, practice_type)`. No text-matching heuristic is needed.

**Before (`pipeline/graph.py`):**
```python
alert_required = (
    cross_check is not None
    and cross_check.authorisation_status == AuthorisationStatus.UNAUTHORISED
    and evaluator is not None
    and evaluator.confidence == ConfidenceLevel.HIGH
    and not evaluator.bsp_mentioned_in_note
)
```

**After:**
```python
alert_required = (
    cross_check is not None
    and cross_check.authorisation_status == AuthorisationStatus.UNAUTHORISED
    and evaluator is not None
    and evaluator.incident_detected
    and evaluator.confidence != ConfidenceLevel.LOW
)
```

Changes:
- Removed `not evaluator.bsp_mentioned_in_note` — SQL is the authority
- Changed `confidence == HIGH` to `confidence != LOW` — fires on MEDIUM and HIGH (MEDIUM = implied/context-dependent, still warrants alert for UNAUTHORISED)
- Added `evaluator.incident_detected` explicit check — belt-and-suspenders guard

## Verification

```bash
conda activate sena_env
python scripts/test_form_api.py
# Expected:
# SCENARIO 1 CLEAR            → alert_required: False ✓
# SCENARIO 2 UNAUTHORISED     → alert_required: True  ✓
# SCENARIO 3 AUTHORISED       → alert_required: False ✓
# SCENARIO 4 UNAUTHORISED     → alert_required: True  ✓
# SCENARIO 5 AUTHORISED       → alert_required: False ✓
# SCENARIO 6 UNAUTHORISED     → alert_required: True  ✓
# SCENARIO 7 NO INCIDENT      → alert_required: False ✓
# SCENARIO 8 UNAUTHORISED     → alert_required: True  ✓
```

## Watch Out For

- **`bsp_mentioned_in_note` is still useful**: Keep the field — it's valuable for the `ADMINISTRATIVE_REVIEW` verdict path in `api/routes.py` `_build_response()`. Just don't use it to gate `alert_required`.
- **The `bsp_mention_excerpt` field**: Same caveat — the model may populate this with "No BSP referenced" text. Don't use it to determine authorisation status.
- **Positive BSP mention in note ≠ authorisation**: Even if a worker writes "following the BSP", that doesn't mean the BSP exists or is current. `cross_check` SQL is the only reliable authority.
- **Verdict routing vs alert_required**: These are separate concerns. `alert_required` triggers the webhook. Verdict is determined by `_build_response()` in `api/routes.py`. Don't conflate them.
