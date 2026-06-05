# SENA AI Token Consumption Estimates — Tier Sizing

**Audience:** SENA client team for credit-model design
**Status:** ENGINEERING ESTIMATE (no production telemetry yet — see §5 for the logging system that will replace these with measured numbers)
**Date:** 2026-05-26

---

## 0. How to read this doc

We have **not yet shipped usage logging**, so every number below is an estimate derived from:
1. Published model rates (Gemini Live, Gemini Flash, Bedrock Claude 3.5 Sonnet)
2. Typical session shapes we've observed in dev + staging
3. Audio-token math: Gemini Live meters voice at ~32 tokens/sec for input and ~32 tokens/sec for output

Treat as ±30% accuracy. Section 5 describes the logging system we will build to replace these with measured per-org data within ~4 weeks of activation.

---

## 1. Per-feature token cost (single use)

| Feature | Model | Input tokens | Output tokens | Notes |
|---------|-------|--------------|---------------|-------|
| Voice Onboarding Assistant (30 min) | Gemini Live `3.1-flash-live-preview` | ~115,000 audio | ~115,000 audio | +20 tool calls × ~500 tokens = ~10k overhead. ~5 min of effective dialogue = active turns; rest is listen/think time. |
| Voice Onboarding Assistant (60 min) | Gemini Live | ~230,000 audio | ~230,000 audio | Doubles linearly. +30 tool calls overhead. |
| Case Note Drafting Voice Assistant (5 min typical) | Bedrock Claude 3.5 Sonnet | ~3,000 | ~1,000 | Per shift. Multi-turn dictation with ~5 turns × 800-token transcript. |
| Case Note Summary (per note, async) | Gemini Flash `gemini-3-flash-preview` | ~5,000 | ~500 | Reads full case note + 5 prior notes. |
| Incident Report Analysis | Gemini Flash | ~8,000 | ~1,500 | Single incident + cross-reference past flags. |
| AI Chat (30 min, ~15 turns) | Gemini Flash | ~30,000 | ~8,000 | Conversational, no audio. Token count scales with history retention. |
| AI Chat (60 min, ~30 turns) | Gemini Flash | ~75,000 | ~18,000 | Non-linear — history grows. |
| PSR (Periodic Service Record) Summary | Gemini Flash | ~12,000 | ~2,500 | Quarterly. Reads 10-15 case notes + plan. |
| Monthly Report | Gemini Flash | ~25,000 | ~5,000 | Aggregates all notes + shifts + incidents for the month. |
| Staff Onboarding Document Extraction | Gemini Flash (multimodal) | ~6,000 | ~800 | Per doc. ID + ABN + bank details. ~4-6 docs/staff. |

**Per-feature one-line summary:**

- **30-min voice onboarding ≈ 240k tokens**
- **60-min voice onboarding ≈ 470k tokens**
- **30-min AI chat ≈ 38k tokens**
- **60-min AI chat ≈ 93k tokens**
- **1 case note + summary + review pipeline ≈ 28k tokens**
- **1 PSR ≈ 15k tokens**
- **1 monthly report ≈ 30k tokens**

---

## 2. Tier sizing — Daily / Monthly totals

Assumptions per tier (best-guess; refine after 4 weeks of logging):

| Tier | Workers | Clients | Voice onboarding/day | Voice dictation/day | Chat/day | Case-note batch jobs/day |
|------|---------|---------|---------------------|---------------------|----------|--------------------------|
| 1 — Sole Trader | 1 | 1–3 | 1 every 2 weeks | 2–4 shifts | 1 × 15 min | 2–4 notes |
| 2 — Medium (5W / 10P) | 5 | 10 | 1–2 / week | 15–20 shifts | 3 × 30 min | 15–20 notes |
| 3 — Large (10W / 20C) | 10 | 20 | 2–3 / week | 30–40 shifts | 6 × 30 min | 30–40 notes |
| 4 — Enterprise (20W / 40C) | 20 | 40 | 1 / day | 60–80 shifts | 12 × 30 min | 60–80 notes |

### Daily token consumption per tier

| Tier | Daily total (tokens) | Daily total (millions) | Cost @ blended $1.50/1M | Monthly (×22 working days) |
|------|----------------------|------------------------|-------------------------|----------------------------|
| 1 — Sole Trader | ~150,000 | 0.15 M | $0.22 | $5 |
| 2 — Medium | ~1,200,000 | 1.2 M | $1.80 | $40 |
| 3 — Large | ~2,500,000 | 2.5 M | $3.75 | $82 |
| 4 — Enterprise | ~6,000,000 | 6.0 M | $9.00 | $198 |

Notes:
- "Blended $1.50/1M" assumes 70% Gemini Flash + 20% Gemini Live audio + 10% Bedrock Claude — rates as of 2026-05.
- **Audio sessions dominate.** A single 60-min voice onboarding (~470k tokens) consumes ~3 days of a Sole Trader's typical daily budget.
- These are CONSUMPTION estimates — the SENA platform's bill to Google/AWS. Client pricing layers margin on top.

### Average consumption based on "X minutes of AI usage per day"

| Tier | 30 min/day (typical session blend) | 60 min/day |
|------|------------------------------------|------------|
| 1 — Sole Trader | ~75,000 tokens/day | ~150,000 tokens/day |
| 2 — Medium | ~600,000 tokens/day | ~1,200,000 tokens/day |
| 3 — Large | ~1,250,000 tokens/day | ~2,500,000 tokens/day |
| 4 — Enterprise | ~3,000,000 tokens/day | ~6,000,000 tokens/day |

"30 min/day" includes ~70% voice (highest token rate) + ~30% chat/text.

---

## 3. Voice Onboarding Assistant — deeper dive

Per session:

| Session length | Tokens per session | Notes |
|----------------|-------------------|-------|
| 30 min | ~240,000 | One full participant intake |
| 60 min | ~470,000 | Complex case with multiple repeatable sections |

**Multi-client onboarding day (Tier 4 example):**

- 4 new clients onboarded × 45 min avg = 4 × ~340k = **~1.36M tokens/day**
- This is ~23% of Tier 4's daily budget for ONE activity. Practical implication: onboarding-heavy weeks burn credits faster than steady-state operation.

---

## 4. AI Chat Conversations — workers vs clients

| Audience | 30-min session | 60-min session | Why different |
|----------|---------------|----------------|---------------|
| Worker (internal — case lookup, training Q&A) | ~38,000 | ~93,000 | Heavier context (case history, NDIS docs) per query |
| Client (participant — service questions) | ~25,000 | ~60,000 | Lighter context (personal record only); shorter answer length |

Worker chat costs ~50% more per minute than client chat due to retrieval-augmented context.

---

## 5. The logging system that will replace these estimates

**Status: not yet built.** Surveyed the codebase — zero services capture `usage_metadata` or `usage` from Bedrock / Gemini responses today.

**To produce measured numbers (replacing every estimate above):**

We need to ship a centralised usage-logging layer that captures every LLM call across voice / onboarding / case_review / future features. Proposed design:

| Component | Location | What it does |
|-----------|----------|--------------|
| `usage_events` table | `ai-db` (Postgres) | Append-only — one row per LLM call: tenant_id, user_id, feature, model, started_at, prompt_tokens, response_tokens, audio_seconds_in, audio_seconds_out, latency_ms, success |
| `shared/usage_logger.py` | `sena_common` library | Context manager wraps every LLM call site; extracts `usage_metadata` (Gemini) / `usage` (Bedrock) / per-second audio counters (Live API) |
| Aggregation API | new endpoint in voice or case_review | `/v1/usage/by-org` `/v1/usage/by-feature` for billing dashboard |
| Credit-balance check | Pre-call gate | Block call if `org.credits_remaining < estimated_cost` (configurable: hard block vs warn) |

Once shipped, the estimates in §1–4 become **measured per-org averages refreshed nightly**. Pricing committee can tune credit allocations from real data within 4 weeks of activation.

**Implementation effort:** ~1 week for the logger + ingest path. ~1 week for dashboard + alert thresholds. ~2 weeks of running before useful averages emerge.

---

## 6. Recommended next step for the client conversation

1. **Use the §1–§4 numbers as a starting position** for tier pricing. Mark them ESTIMATE in any external doc.
2. **Approve building the usage-logging system** so the second client conversation in ~6 weeks is grounded in real data.
3. **Decide on credit model semantics** before logging ships:
   - 1 credit = X tokens? (simple, but exposes implementation)
   - 1 credit = 1 minute of voice OR 1k tokens of text? (abstracted, but ratios need calibration)
   - Pre-pay vs post-pay? Hard block at zero, or grace period?

This doc will be replaced with measured data once the logger ships. Until then it's the engineering baseline.

---

## Appendix — Rate sources

- Gemini Live audio metering: ~32 tokens/sec input + ~32 tokens/sec output, per Google AI Studio docs (Live API pricing page, accessed 2026-05).
- Gemini Flash standard rates: $0.30 input / $2.50 output per 1M tokens (`gemini-3-flash-preview`).
- Bedrock Claude 3.5 Sonnet: $3.00 input / $15.00 output per 1M tokens (AWS pricing page).
- Audio session durations: typical onboarding step length observed in staging dev sessions, 2026-05.
- Tier shapes: drawn from "typical NDIS provider size" buckets in the client brief.

Every number above is recomputable once the §5 logger captures 4 weeks of real data.
