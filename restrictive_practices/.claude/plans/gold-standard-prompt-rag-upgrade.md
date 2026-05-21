# Plan — Gold-Standard Prompt & RAG Upgrade Using Client Benchmark Doc

## Context

The client delivered `2026May_Casenote_CIR-DummyExamples_Feedback.md` (1215 lines) containing:
1. **Field-Description Guidance** (lines 7-104) — what each of the 6 case-note form sections *should* contain
2. **Quality benchmark spectrum** — 2 Premium, 1 Average, 1 Poor case-note examples + 1 High-Risk Incident note
3. **Incident-form feedback** — 10 structured recommendations from the client (severity, category, ongoing risk, etc.)
4. **5 dummy Incident Reports** spanning verbal escalation, property damage, medication refusal, fall/first aid, and self-harm/critical

The module currently has **5 LLM prompts** (triage, evaluator, summary, incident_draft, drafter). **None** carry few-shot examples. Only `evaluator.py` consults RAG. The client doc is a gold-standard benchmark — this plan upgrades every prompt against it while keeping token costs disciplined, ingests the doc into pgvector for hybrid retrieval, expands the incident schema with 3 client-priority fields, and adds a quality-score field surfaced in `/draft` and `/evaluate`.

User answers driving this design:
- **Scope:** upgrade all 5 prompts, but optimise token consumption (ultra-compact inline few-shots, not full-note dumps)
- **RAG:** Hybrid — short inline canonical few-shot + ingest full doc into pgvector
- **Incident form:** Phase 1 = severity + incident_category + ongoing_risk fields (3 priority adds; defer the other 7)
- **Quality scorer:** Yes — surface in both `/draft` and `/evaluate`

---

## Architecture Changes Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  NEW RAG CORPUS (ingest .md file → tagged chunks in pgvector)       │
│   • document_type="Casenote Style Standard"  (Premium/Average/Poor) │
│   • document_type="Field Description Standard"                      │
│   • document_type="Incident Report Standard"  (5 dummy reports)     │
└─────────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
   drafter.py            summary.py           incident_draft.py
   (inline FS +          (inline FS +         (inline FS +
    RAG retrieve)         RAG retrieve)        RAG retrieve)
        │                     │                     │
        │                     │                     │
   triage.py            evaluator.py
   (inline FS only)     (existing RAG + inline FS)

Every prompt also gets a tight "Style Guide" header (clinical, objective, third-person).
```

---

## Files to Modify / Create

### New
- `scripts/ingest_style_standards.py` — CLI that ingests the client doc into pgvector with three new `document_type` tags
- `pipeline/quality_score.py` — small standalone helper that returns `(score: float, label: str, gaps: list[str])` from the AI output; called by both drafter and summary nodes
- `pipeline/style_examples.py` — module-level **constants** holding the ultra-compact inline few-shot snippets (single source of truth, imported by every prompt file → keeps duplication out of the prompt strings)
- `scripts/test_quality_score.py` — smoke test for the new scorer

### Modified
- `pipeline/triage.py` — prepend 2-line few-shot (clean + flagged) + style guide
- `pipeline/evaluator.py` — prepend reasoning-style snippet + style guide (RAG already wired)
- `pipeline/summary.py` — prepend Premium narrative snippet + style guide + RAG retrieve call
- `pipeline/incident_draft.py` — prepend 1 dummy-incident snippet + style guide + RAG retrieve call + 3 new fields
- `pipeline/drafter.py` — prepend field-description guidance + Premium/Poor contrast + RAG retrieve call
- `pipeline/rag.py` — extend `retrieve_policy_chunks` to accept a `document_type_filter` param; OR add new helper `retrieve_style_chunks(query, document_type, db, top_k)` that filters by document_type at query time
- `models/schemas.py`
  - `IncidentDraftOutput` + `_IncidentReportSection` — add `severity`, `incident_categories`, `ongoing_risk` (3 sub-flags)
  - `SummaryOutput` + `_SummarySection` — add `note_quality_score: float`, `note_quality_label: str`, `quality_gaps: list[str]`
  - `CaseDraftResponse` — add the same 3 quality fields (so `/draft` surfaces them too)
- `pipeline/graph.py` — quality_score helper is called inside the summary_node; no topology change
- `api/routes.py` — `_build_response()` propagates the new fields
- `models/db.py` — no change; new chunks just use existing `NDISPolicyChunk` table with new `document_type` values

---

## Token Discipline Strategy

The user explicitly asked us to optimise token cost. **Ultra-compact** few-shots only (not full notes):

| Prompt | Inline few-shot size | Source |
|--------|---------------------|--------|
| triage.py | ~2 lines (1 clean + 1 RP one-liner) | trimmed Premium 2 + High-Risk Incident |
| evaluator.py | ~3 sentences (clinical reasoning style example) | High-Risk Incident "Reasoning" pattern |
| summary.py | ~6 bullets total (1 progress, 1 risk, 1 pattern, 1 highlight) | Premium Note 2 distilled |
| incident_draft.py | ~5 sentences (Section 3 — Detailed Description from Verbal Escalation report) | Incident Report 1 |
| drafter.py | Field-description block (~30 lines, lines 7-104 trimmed) + 1 Premium "Describe" + 1 Poor "Describe" contrast pair | Premium 1 vs Poor 1 |

Total per-call addition: ~150-400 tokens. On Haiku (drafter, summary, triage) at ~$0.25/1M input, this is negligible. On Sonnet (evaluator, incident_draft) it's a couple of cents per call — still cheap relative to verdict value.

All few-shot snippets live in `pipeline/style_examples.py` as Python constants. Each prompt file imports the relevant constant. **Single source of truth** — if the client revises the gold standard, we update one file.

---

## RAG Ingest Strategy

### New ingest script: `scripts/ingest_style_standards.py`

Parses `2026May_Casenote_CIR-DummyExamples_Feedback.md` and produces three chunk groups:

1. **`document_type="Casenote Style Standard"`** — 4 chunks, one per quality tier:
   - Premium Note 1 (Mel Gibson) — `category="Casenote/Premium/CommunityAccess"`, `risk_level="N/A"`
   - Premium Note 2 (Sophie Bennett) — `category="Casenote/Premium/AnxietyExposure"`
   - Average Note (Marcus Hill) — `category="Casenote/Average/HouseholdSupport"`
   - Poor Note (Olivia Green) — `category="Casenote/Poor/Reference"`

2. **`document_type="Field Description Standard"`** — 6 chunks, one per form section (lines 28-104 split on `---`).
   `category="Field/Section1"` … `category="Field/Section6"`

3. **`document_type="Incident Report Standard"`** — 5 chunks, one per dummy report:
   - Verbal Escalation, Property Damage, Medication Refusal, Fall/FirstAid, Self-Harm/Critical
   - `category="Incident/VerbalEscalation"` etc.
   - `risk_level` per report: Low/Medium/High/Critical

Uses the existing `cohere.embed-english-v3` embedder via Bedrock (1024-dim halfvec) — no schema change.

Chunk size: NOT applied to these — each example/section ingests as ONE chunk (~800-2000 chars each, within the 1200-char chunker default but we bypass the splitter). Manual `DocumentChunk(...)` construction passed to `upsert_chunks()`.

### New RAG helper: `pipeline/rag.py:retrieve_style_chunks()`

```python
async def retrieve_style_chunks(
    query: str,
    document_type: str,
    db: AsyncSession,
    top_k: int = 2,
) -> list[PolicyChunk]
```

Same cosine search as `retrieve_policy_chunks` but adds a `WHERE document_type = :doc_type` filter. Top-K kept small (2 by default) — these are reference examples, not policy chunks.

Wiring:
- **drafter** queries `retrieve_style_chunks(transcript_first_200_chars, "Field Description Standard", db, 2)` → injects matched field guidance into prompt
- **summary** queries `retrieve_style_chunks(behavioural_events_or_describe, "Casenote Style Standard", db, 1)` → 1 closest premium example
- **incident_draft** queries `retrieve_style_chunks(incident_summary, "Incident Report Standard", db, 1)` → most similar dummy incident report
- **evaluator** keeps existing RAG (no change to query path; could also pull a style chunk in future)
- **triage** stays RAG-free (cost-sensitive gate)

### Cost shape after change

| Step | Model | Tokens in | RAG calls | Per-note ∆ cost |
|------|-------|-----------|-----------|-----------------|
| triage | Haiku | +~50 (few-shot) | 0 | negligible |
| summary | Haiku | +~200 (few-shot + 1 RAG chunk) | 1 embed + cosine | <$0.0005 |
| drafter | Sonnet | +~600 (field guide + 1 RAG chunk) | 1 embed + cosine | ~$0.002 |
| evaluator | Sonnet | +~150 (style snippet) | existing | negligible |
| incident_draft | Sonnet | +~400 (few-shot + 1 RAG chunk) | 1 embed + cosine | ~$0.001 (only when triggered) |

Net per `/evaluate` call (clean note): +~$0.0005. Per flagged note: +~$0.0035. Well within budget.

---

## Schema Additions (key shapes)

### `SummaryOutput` (internal) + `_SummarySection` (response) — add quality fields

```python
class SummaryOutput(BaseModel):
    ai_confidence: float = Field(0.0, ge=0.0, le=1.0)
    progress_identified: list[str] = []
    potential_risks: list[str] = []
    patterns_detected: list[str] = []
    flagged_highlights: list[str] = []
    # NEW
    note_quality_score: float = Field(0.0, ge=0.0, le=1.0)
    note_quality_label: str = "Average"   # Premium | Average | Poor
    quality_gaps: list[str] = []          # Concrete fixes the worker can apply
```

### `IncidentDraftOutput` + `_IncidentReportSection` — add 3 priority fields

```python
class IncidentDraftOutput(BaseModel):
    # ...existing fields...
    # NEW
    severity: str = "Low"                       # Low | Medium | High | Critical
    incident_categories: list[str] = []         # multi-select from canonical list
    ongoing_risk_present: bool = False
    participant_currently_safe: bool = True
    staff_currently_safe: bool = True
    emergency_services_required: bool = False
```

**Canonical `incident_categories` list** (used in the incident_draft prompt as authoritative options):
Behavioural incident · Medication issue · Restrictive practice · Injury · Absconding · Allegation · Abuse or neglect · Property damage · Police involvement · Hospitalisation · Environmental hazard · Staff misconduct

### `CaseDraftResponse` — add quality fields (for /draft response symmetry)

```python
# After draft_note, add:
note_quality_score: float = Field(0.0, ge=0.0, le=1.0)
note_quality_label: str = "Average"
quality_gaps: list[str] = []
```

These three fields are populated by the **same `quality_score.py` helper** the summary uses — single source of scoring logic.

---

## Quality Scorer (`pipeline/quality_score.py`)

A small stateless helper. Two implementation options:

**Option A (recommended, no extra LLM call):** Heuristic + style match against Premium examples
- Counts populated sections (out of 6) → completeness sub-score
- Length per section vs Premium baseline (Premium "Describe" is ~80-120 words; Poor is <15) → richness sub-score
- Presence of clinical language markers (Premium: "demonstrated", "regulated", "implemented"; Poor: "ok", "was quiet") → tone sub-score
- Weighted aggregate → `note_quality_score`
- `label`: ≥0.75 → Premium, 0.45-0.75 → Average, <0.45 → Poor
- `gaps`: list of which sections fell below baseline ("Section 3 (Behaviour) lacks detail — add observable indicators and timing")

**Option B:** Tiny additional Haiku call rating against Premium style
- Cleaner output but +1 LLM call per `/evaluate` and `/draft`
- User asked for token discipline — defer this option.

**Choice: Option A (heuristic).** Zero LLM cost. Deterministic. Easy to tune. Lives at `pipeline/quality_score.py:score_note(note: CaseNoteInput) -> tuple[float, str, list[str]]`.

---

## Critical Reuse (don't re-derive)

- **`pipeline/style_examples.py` (new)** — every prompt file imports `FEW_SHOT_TRIAGE`, `FEW_SHOT_SUMMARY`, `FEW_SHOT_DRAFTER`, etc. Single edit point.
- **`pipeline/rag.py:retrieve_policy_chunks`** — extended (not duplicated) to support a document_type filter.
- **`scripts/ingest_docs.py`** — copy its `_chunks_from_pdf` pattern; new `_chunks_from_markdown` reads the .md file and constructs `DocumentChunk` objects directly.
- **`ingestion/embedder.py:upsert_chunks`** — reuse unchanged.
- **`CaseNoteInput.to_text()`** — keep using; still the input to every prompt.
- **`_make_client()` and `_extract_json()`** — already duplicated per prompt file; no consolidation in this phase.

---

## Implementation Order

1. **Style examples module** — create `pipeline/style_examples.py` with the 5 trimmed few-shot constants. No logic, just strings. Verify imports.

2. **Quality scorer** — create `pipeline/quality_score.py:score_note()`. Heuristic only. Unit-smoke with 3 cases (Premium / Average / Poor from client doc).

3. **Schema scaffolding** — extend `SummaryOutput`, `_SummarySection`, `IncidentDraftOutput`, `_IncidentReportSection`, `CaseDraftResponse` per shapes above. Compile-check imports.

4. **RAG filter extension** — extend `pipeline/rag.py` with `retrieve_style_chunks(query, document_type, db, top_k)`. Reuse existing embedder.

5. **Ingest script** — `scripts/ingest_style_standards.py` that parses the .md file into 15 chunks (4 casenotes + 6 field-sections + 5 incident reports). Run: `python scripts/ingest_style_standards.py`. Verify: `make audit-chunks` shows new `document_type` rows.

6. **Drafter upgrade** — `pipeline/drafter.py`: prepend `FEW_SHOT_DRAFTER` + field-description block; call `retrieve_style_chunks` for Field Description Standard chunks; populate `note_quality_score/label/gaps` via `quality_score.score_note()` at return.

7. **Summary upgrade** — `pipeline/summary.py`: prepend `FEW_SHOT_SUMMARY`; call `retrieve_style_chunks` for 1 Casenote Style Standard chunk; populate quality fields. Update `summary_node` in `graph.py` to pass `db` from state.

8. **Incident-draft upgrade** — `pipeline/incident_draft.py`: prepend `FEW_SHOT_INCIDENT`; call `retrieve_style_chunks` for Incident Report Standard; extract the 3 new fields (severity, incident_categories, ongoing_risk*).

9. **Triage upgrade** — `pipeline/triage.py`: prepend `FEW_SHOT_TRIAGE` (2-line clean+RP contrast). No RAG.

10. **Evaluator upgrade** — `pipeline/evaluator.py`: prepend `FEW_SHOT_EVAL_REASONING` style snippet. Existing RAG stays.

11. **API wiring** — `api/routes.py:_build_response()`: copy `note_quality_score`, `note_quality_label`, `quality_gaps` from `result.summary` → `summary_section`; copy `severity`, `incident_categories`, `ongoing_risk_*` from `result.incident_draft` → `incident_report_section`.

12. **Tests** — `scripts/test_quality_score.py` (3 fixture cases); rerun `scripts/test_summary.py`, `scripts/test_incident_draft.py`, `scripts/test_draft_endpoint.py`, `scripts/test_form_api.py` end-to-end.

13. **Docs sweep** — update `CLAUDE.md` (new files in table, new env-or-script step `python scripts/ingest_style_standards.py` in Run Commands, new schema fields documented in the AI Summary + Incident Report sections), bump `.claude/SESSION_START.md`, mark task done in `.claude/tasks/TASKS.md`.

---

## Verification

```bash
# Ingest the gold-standard chunks (one-time)
python scripts/ingest_style_standards.py
make audit-chunks    # expect rows for the 3 new document_types

# Unit-level smoke
python scripts/test_quality_score.py
python scripts/test_summary.py
python scripts/test_incident_draft.py
python scripts/test_draft_endpoint.py

# End-to-end regression
python scripts/test_form_api.py     # 8 scenarios — expect quality fields populated
python scripts/test_sarah_note.py

# Manual A/B sanity
make server
# Run Swagger test cases (scripts/swagger_test_cases.md) — compare the verdict reasoning,
# summary bullets, and incident_report narrative against the Premium/dummy examples
# in the client doc. They should now read in third-person clinical voice.
```

Acceptance:
- `/evaluate` summary bullets use third-person clinical voice ("Participant demonstrated…", not "He was ok…")
- `/draft` response includes `note_quality_score`, `note_quality_label`, `quality_gaps`
- Poor input (terse transcript like "did some cleaning") → `note_quality_label="Poor"`, `quality_gaps` lists missing detail
- Premium input → `note_quality_label="Premium"`, empty or near-empty gaps
- Incident report extracts the 3 new fields (`severity`, `incident_categories`, `ongoing_risk_*`)
- pgvector `rp_ndis_policy_chunks` has 15 new rows across 3 new `document_type` values
- All existing tests still pass

---

## Out of Scope (Phase 2)

Per client note "some will have to be parked for 2nd phase":
- Incident-form additions 4-10 from the client doc (RP authorisation fields, external notifications, attachment expansion, dynamic field logic, draft saving, audit tracking, voice-to-text)
- Multi-shift longitudinal quality trends ("worker X notes consistently Poor over 2 weeks")
- Refactoring duplicate `_make_client()` / `_extract_json()` into a shared util
- A separate `/quality` endpoint
- Premium-style fine-tuning (e.g. fine-tuned Haiku model)

---

## Risks / Gotchas

- **Style few-shots can over-anchor the model** — keep them ultra-compact and label them as "STYLE REFERENCE, do NOT copy verbatim". If the model starts producing names from the examples ("Mel"), shrink the few-shot or strip names from the constants.
- **Heuristic quality scorer can be gamed** — workers padding sections with filler. Tune via the client's Premium/Average/Poor word counts; consider Option B (LLM-based) in Phase 2 if abuse appears.
- **RAG cost on every drafter call** — adds one embedding query per `/draft`. Mitigation: cache the embedding of the first 200 chars of the transcript per session if the same transcript hits `/draft` twice. Defer caching unless metrics show it matters.
- **`document_type` filter on cosine query** — verify the HNSW index doesn't degrade when we add a WHERE clause; pgvector handles this fine because HNSW supports post-filter on small result sets, but if perf drops we add an index on `(document_type, embedding)` or use a separate query path.
- **Client doc updates** — when client revises the .md, re-run `ingest_style_standards.py` (idempotent via `ON CONFLICT DO UPDATE` already in `upsert_chunks`).
- **Schema drift** — the 3 new incident fields are additive with defaults; existing clients get safe defaults. No migration needed since `create_tables()` runs on startup and the JSONB column stores the new fields opaquely in `rp_case_note_runs.evaluator_output`.
