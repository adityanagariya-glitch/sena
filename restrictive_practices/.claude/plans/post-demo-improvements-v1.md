# Post-Demo Improvements Plan — Client Feedback v1.0

## Context

Client tested the deployed demo and produced a 12-case escalation testing matrix
(`testing_report/2026May_RPdetector_REPORT.md`). Four operational concerns to address:

1. **Binary outputs** — no middle tier between NO_INCIDENT and UNAUTHORISED
2. **No contradiction recognition** — BSP mentioned in note but no DB match → admin review
3. **No explainability** — no trigger phrases / suppression factors surfaced
4. **No admin action guidance** — no next-steps checklist per outcome

## Files Modified

| Path | Changes |
|------|---------|
| `models/schemas.py` | Added `ConfidenceLevel` enum; added `POSSIBLE` + `ADMINISTRATIVE_REVIEW` to `VerdictOutcome`; extended `EvaluatorOutput`, `_DetectedPracticeSection`, `_VerdictSection` |
| `pipeline/evaluator.py` | Extended `_EvaluatorResponse` + `_EVALUATOR_PROMPT`; passes new fields to `EvaluatorOutput` |
| `pipeline/graph.py` | `alert_required` now requires HIGH confidence + no BSP mention in note |
| `api/routes.py` | Full confidence-scaled + contradiction-aware `_build_response`; passes phrases to detected_practice |
| `demo_ui.html` | New verdict CSS classes; trigger/suppression chips; next-steps checklist |

## Verdict Logic (after)

```
triage.flagged=False                          → CLEAR
ev=None OR ev.incident_detected=False         → NO_INCIDENT
ev.confidence=Low                             → NO_INCIDENT (suppressed)
cc.authorisation_status=AUTHORISED_REVIEW     → AUTHORISED_USE
ev.bsp_mentioned_in_note AND cc.bsp_id=None   → ADMINISTRATIVE_REVIEW
ev.confidence=Medium AND cc.bsp_id=None       → POSSIBLE
else (High, no BSP)                           → UNAUTHORISED
```

## Acceptance Criteria

| Test | Before | Target |
|------|--------|--------|
| A2 (subtle environmental) | UNAUTHORISED | POSSIBLE |
| A4 (redirection) | UNAUTHORISED | POSSIBLE |
| A5 (close supervision near exit) | UNAUTHORISED | POSSIBLE |
| A3 (explicit physical) | UNAUTHORISED | UNAUTHORISED (unchanged) |
| B6 (restriction + BSP conflict) | UNAUTHORISED | ADMINISTRATIVE_REVIEW |
| B1–B4 (autonomy/safety) | NO_INCIDENT / CLEAR | unchanged |
