# Plan — Add AI Summary + Incident Report Drafting to `/evaluate`

## Context

The `/evaluate` endpoint currently runs a 4-step LangGraph pipeline (triage → rag → evaluator → cross_check) and returns a restrictive-practice verdict. Two pieces of the user-facing flow are missing:

1. **AI Summary** — every evaluated shift form should produce a single-shift summary mirroring `Case Note 5.png` (Progress Identified / Potential Risks / Patterns Detected / Flagged Highlights), excluding the restrictive-practices flagging which the existing evaluator already covers.
2. **Incident Report Draft** — when the worker ticked `incident_occurred=True` OR the pipeline detected an `UNAUTHORISED` restrictive practice, the response must include a draft incident report mirroring `Case Note 6.png`, structured per the NDIS Commission's detailed incident-management guidance (5 reportable incident categories + 24h/5-business-day timeframes).

Both pieces ship inline in the existing `EvaluateResponse` (no new endpoints). The `/draft` response must also be made structurally compatible with the `/evaluate` request so the UI can pass it straight through.

User answers driving the design:
- Summary scope = **single shift** (no longitudinal aggregation; no new DB queries)
- Incident trigger = **`incident_occurred=True` OR `UNAUTHORISED` verdict**
- Delivery = **inline in `EvaluateResponse`**

---

## Files to Modify / Create

### New
- `pipeline/summary.py` — single-shift summariser (Haiku via Bedrock `converse`, cost-optimised; ~512–1024 tokens)
- `pipeline/incident_draft.py` — incident report drafter (Sonnet via Bedrock `converse`; ~2048–4096 tokens, conditional)
- `scripts/test_summary.py` — smoke test, 4–6 fixtures
- `scripts/test_incident_draft.py` — smoke test, 4–6 fixtures covering both triggers

### Modified
- `models/schemas.py`
  - Add `SummaryOutput`, `IncidentDraftOutput`, response sections `_SummarySection`, `_IncidentReportSection`
  - Extend `EvaluateResponse` with `summary: _SummarySection` (always) and `incident_report: _IncidentReportSection | None` (conditional)
  - Extend `CaseDraftResponse` with `transcript: str | None = None` and `uploaded_documents: list[str] | None = None`
  - Extend `PipelineResult` with `summary: SummaryOutput | None` and `incident_draft: IncidentDraftOutput | None`
- `pipeline/graph.py`
  - Add `summary_node` (runs in parallel after triage, regardless of `flagged`)
  - Add `incident_draft_node` (conditional edge after `cross_check_step`)
  - Update `PipelineState` TypedDict
  - Add routing fn `_route_after_cross_check` → `incident_draft_step` or `END`
- `pipeline/drafter.py` — pass `transcript` through to `CaseDraftResponse`
- `api/routes.py` — `_build_response()` wires the new sections in
- `CLAUDE.md` — update architecture diagram + file table + verdict-routing section
- `.claude/SESSION_START.md` and `.claude/tasks/TASKS.md` — note the new pipeline steps

---

## Pipeline Topology (after changes)

```
START → triage_step (Haiku, maxTokens=512)
        ├──────────────────────────► summary_step (Haiku, maxTokens=1024)
        │
        ├─ flagged=False ─────────────────────────────────► join → [incident?] → END
        └─ flagged=True  → rag → evaluator → cross_check ──► join → [incident?] → END

[incident?] = True when:
  evaluator.confidence == HIGH  AND  cross_check.authorisation_status == UNAUTHORISED
  OR
  note.incident_occurred == True

→ summary_node always runs (it's a shift summary, not a compliance step)
→ incident_draft_node runs only when [incident?] = True
```

Implementation note: LangGraph's `add_conditional_edges` is already used for `_route_after_triage`; reuse the same pattern. `summary_node` can be wired as a parallel edge from `triage_step` AND `cross_check_step` so it always runs once — simplest is to wire it as an edge from START or as a sibling of triage. **Recommended:** add `summary_node` as an unconditional edge: `START → triage_step` and `START → summary_step` in parallel — LangGraph fan-out is supported and keeps the topology clean. The `incident_draft_node` runs only after both branches have joined.

### Cost shape

| Step | Model | Tokens | Runs |
|------|-------|--------|------|
| triage | Haiku | 512 | every note |
| **summary (new)** | Haiku | 1024 | every note |
| rag | n/a | embed only | ~30% of notes |
| evaluator | Sonnet | 8192 | ~30% of notes |
| cross_check | n/a (SQL) | — | ~30% of notes |
| **incident_draft (new)** | Sonnet | 4096 | only when triggered |

Net new cost on clean notes: 1× Haiku call. Net new cost on flagged notes with an incident: 1× Haiku + 1× Sonnet (only when the worker or the AI actually surfaced an incident).

---

## Schema Additions (key shapes)

### `SummaryOutput` (internal — emitted by `pipeline/summary.py`)
```
ai_confidence: float                  # 0.0–1.0, e.g. 0.84
progress_identified: list[str]        # 2–5 bullets, positive observations
potential_risks: list[str]            # 0–4 bullets
patterns_detected: list[str]          # 0–3 bullets
flagged_highlights: list[str]         # 2–4 verbatim quotes from the form
```

### `IncidentDraftOutput` (internal — emitted by `pipeline/incident_draft.py`)
Mirrors Case Note 6.png + NDIS Commission reportable-incident requirements:
```
incident_type: str                    # e.g. "Behaviour of Concern (No Injury)" |
                                      #      "Unauthorised Restrictive Practice"
date_of_incident: str | None
time_of_incident: str | None
location: str | None
staff_involved: list[str]
incident_description: str
immediate_actions_taken: list[str]
restrictive_practice_used: bool
restrictive_practice_category: str | None
risk_assessment: str                  # "Immediate risk: Low|Medium|High|Critical"
contributing_factors: list[str]
follow_up_actions: list[str]
compliance_checks: list[dict]         # [{"label": "...", "passed": bool}]
reportable: bool                      # true if NDIS-Commission-reportable
notification_timeframe: str | None    # "24 hours" | "5 business days" | None
notification_authority: str           # "NDIS Quality and Safeguards Commission"
```

Five (+1) reportable-incident categories (per NDIS rules, used in the prompt as the source of truth for `reportable` and `notification_timeframe`):
1. Death of a person with disability — **24h**
2. Serious injury of a person with disability — **24h**
3. Abuse or neglect of a person with disability — **24h**
4. Unlawful sexual or physical contact with, or assault of, a person with disability — **24h**
5. Sexual misconduct committed against, or in the presence of, a person with disability — **24h**
6. Use of a restrictive practice not in accordance with an authorisation/PBSP — **5 business days**

### `EvaluateResponse` additions
- `summary: _SummarySection` (always populated)
- `incident_report: _IncidentReportSection | None` (populated when triggered)

### `CaseDraftResponse` additions (alignment fix)
- `transcript: str | None = None` — pass-through of the original transcript so the UI can re-submit it inside `CaseNoteInput.transcript`
- `uploaded_documents: list[str] | None = None` — shape compatibility; `/draft` leaves it `None`, UI fills before `/evaluate`

---

## Critical Reuse (don't re-derive)

- **`CaseNoteInput.to_text()`** — already exists; pass `note.to_text()` to both the summary prompt and the incident-draft prompt (do NOT reach into individual form fields). Same convention as triage/rag/evaluator/drafter.
- **`pipeline/triage.py:_make_client()` and `_extract_json()`** — copy the same Bedrock client factory + JSON-from-free-text extractor into the two new files. (Both functions are 6–10 lines; copying preserves the per-step independence; refactoring into a shared util is a follow-up.)
- **`pipeline/triage.py` prompt shape** — single-quoted JSON-only response, free-text JSON extracted via `_extract_json`. Same shape works for summary + incident_draft.
- **`api/routes.py:_build_response()`** — wire the two new sections in here; pattern matches the existing `_DetectedPracticeSection` / `_AuthorisationSection` blocks.
- **Verdict routing logic** — existing priority order in `_build_response()` is already correct; new code only adds sections, never overrides verdict selection.

---

## Implementation Order (for the executor)

1. **Schema scaffolding** — `models/schemas.py`: add `SummaryOutput`, `IncidentDraftOutput`, the two response sections, extend `EvaluateResponse` + `PipelineResult` + `CaseDraftResponse`. No logic yet, just shapes. Run `python -c "from models.schemas import EvaluateResponse"` to smoke-check imports.
2. **`pipeline/drafter.py` alignment** — populate `transcript` and `uploaded_documents=None` in the `CaseDraftResponse(...)` return.
3. **`pipeline/summary.py`** — new file, Haiku via `converse`, `maxTokens=1024`, `temperature=0.0`. Prompt requires 4 bullet groups + a 0.0–1.0 confidence score. Verify with `scripts/test_summary.py`.
4. **`pipeline/incident_draft.py`** — new file, Sonnet via `converse`, `maxTokens=4096`, `temperature=0.0`. Prompt includes the 5+1 reportable-incident categories as authoritative reference. Verify with `scripts/test_incident_draft.py`.
5. **`pipeline/graph.py`** — add nodes, add parallel `START → summary_step` edge, add conditional edge after `cross_check_step` → `incident_draft_step` or END. Update `PipelineState` TypedDict. Verify with `make test`.
6. **`api/routes.py:_build_response()`** — populate `summary` (always) and `incident_report` (when triggered) on the response.
7. **End-to-end:** rerun `python scripts/test_form_api.py` (8 scenarios) + `python scripts/test_sarah_note.py` — both should still pass AND now include `summary` + (where applicable) `incident_report` sections.
8. **Docs sweep:** update `CLAUDE.md` architecture diagram + file table; bump `.claude/SESSION_START.md` and `.claude/tasks/TASKS.md`.

---

## Verification

Run all the following end-to-end:

```bash
# Unit-level smoke
python scripts/test_summary.py
python scripts/test_incident_draft.py

# Full pipeline regression
make test            # triage → rag → evaluator → cross_check → pipeline (existing)
make test-sarah      # multi-practice complex fixture
python scripts/test_form_api.py     # 8 real-data scenarios, all 4 verdicts × 5 practice types
python scripts/test_draft_endpoint.py  # 10 drafter scenarios + verify new transcript/uploaded_documents fields

# Server-level
make server          # uvicorn on :8084
# Then in another shell:
curl -X POST http://localhost:8084/v1/restrictive-practices/evaluate \
     -H 'Content-Type: application/json' \
     -d @scripts/fixtures/clean_note.json | jq '.summary, .incident_report'
# Expect: summary populated, incident_report = null

curl -X POST http://localhost:8084/v1/restrictive-practices/evaluate \
     -H 'Content-Type: application/json' \
     -d @scripts/fixtures/unauthorised_rp.json | jq '.summary, .incident_report'
# Expect: summary populated, incident_report populated, reportable=true, notification_timeframe="5 business days"

curl -X POST http://localhost:8084/v1/restrictive-practices/evaluate \
     -H 'Content-Type: application/json' \
     -d @scripts/fixtures/worker_ticked_incident.json | jq '.incident_report.reportable'
# Expect: incident_report populated even though no RP found
```

Acceptance:
- Every `/evaluate` call returns `summary` (4 bullet groups + `ai_confidence`)
- `incident_report` present iff (`incident_occurred=True` OR verdict=`UNAUTHORISED`)
- `incident_report.reportable=true` and `notification_timeframe="5 business days"` for unauthorised RP
- `/draft` response now includes `transcript` and `uploaded_documents`; round-trip into `/evaluate` works without UI-side reshaping
- All existing tests still pass
- DB audit row (`rp_case_note_runs`) still written for every run

---

## Out of Scope (defer)

- Longitudinal multi-note summary (the "Reviewed Period: 10–16 Jan 2025" aggregation in Case Note 5.png) — user confirmed single-shift first
- Persisting incident drafts (currently stateless; worker submits the final form via the platform's own incident-management endpoint)
- A "Draft Incident" button calling a separate endpoint — user chose inline delivery
- Refactoring `_make_client()` / `_extract_json()` into a shared module — duplicate now, consolidate in a follow-up

---

## Risks / Gotchas

- **Latency:** every `/evaluate` now does an extra Haiku call for the summary. For clean notes (~70%), pipeline time goes from ~1× Haiku to 2× Haiku in parallel — same wall-clock if the graph runs `triage_step` and `summary_step` concurrently (LangGraph supports this).
- **Cost on unauthorised RP path:** adds 1× Sonnet (4096 tok) per incident. Acceptable since incidents are rare and the value is high.
- **JSON robustness:** Bedrock `converse` returns free text; reuse `_extract_json()` to tolerate stray markdown fences. Existing pattern, already proven in triage/evaluator/drafter.
- **Compliance correctness:** the incident-draft prompt MUST list the 5 reportable-incident categories verbatim and the 24h/5-business-day mapping so the model doesn't hallucinate timeframes. Lift the wording from `evaluator.py`'s existing reporting-obligations block to stay consistent.
- **`HALFVEC(1024)` / Bedrock conventions** — neither new step touches embeddings or the DB, so no migration needed.
