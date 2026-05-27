# Phase 1 Usage Log — what gets emitted, when

Every successful LLM call now emits ONE structlog JSON line with `event=ai_usage`. This doc shows the exact shape per call site, with realistic field values, plus how to find them in your log stream.

> **PREREQUISITE — you may not be seeing any logs yet.**
> If you have NOT done `pip install -e sena-ai/shared/` against the SENA_AI venv, the imports fall back to a no-op stub. NO events are emitted. To activate: install sena-common editable, then restart uvicorn.
>
> Quick test:
> ```powershell
> python -c "from sena_common.usage_logger import emit_usage, UsageFeature; emit_usage(tenant_id='test', user_id='u', feature=UsageFeature.CASE_NOTE_SUMMARY, model='gemini-3-flash-preview', session_id='s'); print('OK')"
> ```
> If you see a JSON line printed → real logger active. If you see `OK` alone → real logger active but writing to a different sink (depends on structlog config). If `ImportError` → stub is active, no logging.

---

## 1. Voice Onboarding — Gemini Live (per turn, in `gemini_live.py`)

**Emit point:** every `turn_complete` server event. Cumulative-to-delta math so each event is THIS TURN's cost.

**Example log line (pretty-printed):**

```json
{
  "event": "ai_usage",
  "timestamp": "2026-05-26T14:23:18.421Z",
  "level": "info",
  "logger": "ai_usage",

  "tenant_id": "phase1_tbd",
  "user_id": null,
  "feature": "voice_onboarding",
  "model": "gemini-3.1-flash-live-preview",
  "session_id": "sess_a1b2c3d4",
  "prompt_tokens": 540,
  "response_tokens": 320,
  "cached_tokens": 0,
  "audio_seconds_in": 0.0,
  "audio_seconds_out": 0.0,
  "tool_call_count": 1,
  "latency_ms": null,
  "success": true,
  "failure_reason": null,

  "turn_id": 7,
  "audio_chunks_out": 14
}
```

**What's per-turn here:**
- `prompt_tokens` / `response_tokens` — delta since last `turn_complete`
- `tool_call_count` — number of function calls Gemini made in this turn (e.g. 1 = one `update_field`)
- `audio_chunks_out` — count of 24kHz PCM chunks streamed to client this turn
- `turn_id` — 0-indexed turn counter within the session

**Per-screen rollup:** the per-screen prompt model isn't shipped yet (PLAN #1, Phase 2). For now each onboarding step = one WebSocket session = one `session_id`. Group by `session_id` to get per-step totals. A typical 5-step onboarding flow shows ~5 distinct `session_id` values, each with ~8-15 `ai_usage` rows (one per turn).

**Query examples (jq):**

```bash
# Total tokens per session (per-step rollup)
cat onboarding.log | jq -c 'select(.event=="ai_usage") | {session_id, prompt_tokens, response_tokens}' \
  | jq -s 'group_by(.session_id) | map({session: .[0].session_id, prompt: map(.prompt_tokens) | add, response: map(.response_tokens) | add})'

# Average turn cost for voice_onboarding feature
cat onboarding.log | jq -c 'select(.event=="ai_usage" and .feature=="voice_onboarding")' \
  | jq -s 'map(.prompt_tokens + .response_tokens) | add / length'

# How many tool calls per turn on average?
cat onboarding.log | jq -c 'select(.event=="ai_usage" and .feature=="voice_onboarding")' \
  | jq -s 'map(.tool_call_count) | add / length'
```

---

## 2. Case Note Drafting — Bedrock Claude (per call, in `bedrock_service.py`)

**Emit point:** after every successful `invoke_model` (one row per dictation turn). Failure path emits with `success: false`.

**Success example:**

```json
{
  "event": "ai_usage",
  "timestamp": "2026-05-26T14:30:11.108Z",
  "level": "info",
  "logger": "ai_usage",

  "tenant_id": "phase1_tbd",
  "user_id": null,
  "feature": "case_note_drafting",
  "model": "anthropic.claude-3-5-sonnet-20241022-v2:0",
  "session_id": null,
  "prompt_tokens": 2840,
  "response_tokens": 612,
  "cached_tokens": 0,
  "audio_seconds_in": 0.0,
  "audio_seconds_out": 0.0,
  "tool_call_count": 0,
  "latency_ms": 1640,
  "success": true,
  "failure_reason": null,

  "history_turns": 3
}
```

**Failure example** (Bedrock 503 / timeout after retries):

```json
{
  "event": "ai_usage",
  "timestamp": "2026-05-26T14:30:55.992Z",
  "tenant_id": "phase1_tbd",
  "user_id": null,
  "feature": "case_note_drafting",
  "model": "anthropic.claude-3-5-sonnet-20241022-v2:0",
  "session_id": null,
  "prompt_tokens": 0,
  "response_tokens": 0,
  "cached_tokens": 0,
  "tool_call_count": 0,
  "latency_ms": 6018,
  "success": false,
  "failure_reason": "bedrock_provider_unavailable"
}
```

**What's per-call:**
- `prompt_tokens` = `payload["usage"]["input_tokens"]`
- `response_tokens` = `payload["usage"]["output_tokens"]`
- `cached_tokens` = `cache_read_input_tokens + cache_creation_input_tokens` (Anthropic prompt-cache)
- `history_turns` = how many prior dictation turns Bedrock had to reason over

---

## 3. Voice Onboarding (personal-details sub-flow) — Bedrock Claude

Same shape as #2 but `feature: "voice_onboarding"`. This is the personal-details voice sub-flow that historically uses Bedrock (not Gemini Live). Extra field:

```json
{
  "event": "ai_usage",
  "feature": "voice_onboarding",
  "model": "anthropic.claude-3-5-sonnet-20241022-v2:0",
  "prompt_tokens": 1450,
  "response_tokens": 380,
  "latency_ms": 920,
  "success": true,

  "history_turns": 2,
  "missing_field_count": 4
}
```

---

## 4. Case Note Summary / PSR Summary / Monthly Report — Gemini Flash

All three features share the `summarise()` function in `summarizer.py`. The CALLER passes `feature=...` to pick which one. Shape:

**Case Note Summary example:**

```json
{
  "event": "ai_usage",
  "timestamp": "2026-05-26T14:45:02.341Z",
  "tenant_id": "phase1_tbd",
  "user_id": null,
  "feature": "case_note_summary",
  "model": "gemini-3-flash-preview",
  "session_id": null,
  "prompt_tokens": 4823,
  "response_tokens": 412,
  "cached_tokens": 0,
  "tool_call_count": 0,
  "latency_ms": 480,
  "success": true,
  "failure_reason": null,

  "new_note_count": 5
}
```

**PSR Summary** (same shape, different feature):

```json
{
  "event": "ai_usage",
  "feature": "psr_summary",
  "model": "gemini-3-flash-preview",
  "prompt_tokens": 11400,
  "response_tokens": 2280,
  "cached_tokens": 1200,
  "latency_ms": 1820,
  "success": true,
  "new_note_count": 12
}
```

**Monthly Report:**

```json
{
  "event": "ai_usage",
  "feature": "monthly_report",
  "model": "gemini-3-flash-preview",
  "prompt_tokens": 24800,
  "response_tokens": 4900,
  "cached_tokens": 3200,
  "latency_ms": 3420,
  "success": true,
  "new_note_count": 38
}
```

**NOTE — route handler must pass `feature=`**: by default `summarise()` uses `CASE_NOTE_SUMMARY`. PSR and Monthly Report routes must explicitly pass `feature=UsageFeature.PSR_SUMMARY` or `feature=UsageFeature.MONTHLY_REPORT`. Until they do, these features are tagged as case_note_summary. Phase 1.5 followup.

---

## 5. Case Note Classifier — Gemini Flash

In `classifier.py`. Currently emits as `case_note_summary` because classifier feeds the summary pipeline. If the incident-detection route adds a classifier call with `feature=INCIDENT_REPORT_ANALYSIS`, it'll show as that.

```json
{
  "event": "ai_usage",
  "feature": "case_note_summary",
  "model": "gemini-3-flash-preview",
  "prompt_tokens": 1840,
  "response_tokens": 220,
  "cached_tokens": 0,
  "latency_ms": 320,
  "success": true,

  "paragraph_len": 1240
}
```

---

## 6. Per-screen view — voice onboarding step-by-step

Right now: **one onboarding step = one WebSocket session = one `session_id`**. Per-screen breakdown (Phase 2, PLAN #1) doesn't ship yet.

To see a per-screen rollup TODAY:

```bash
# All ai_usage events for one session, grouped by step (= session_id)
cat onboarding.log | jq -c '
  select(.event=="ai_usage" and .feature=="voice_onboarding")
  | {session_id, turn_id, prompt_tokens, response_tokens, tool_call_count}
' | jq -s '
  group_by(.session_id)
  | map({
      step_session: .[0].session_id,
      turn_count: length,
      total_prompt: map(.prompt_tokens) | add,
      total_response: map(.response_tokens) | add,
      total_tool_calls: map(.tool_call_count) | add
    })
'
```

Expected output (5-step onboarding):

```json
[
  { "step_session": "sess_step1_personal", "turn_count": 12, "total_prompt": 8400, "total_response": 5200, "total_tool_calls": 9 },
  { "step_session": "sess_step2_requirements", "turn_count": 6, "total_prompt": 4100, "total_response": 2600, "total_tool_calls": 4 },
  { "step_session": "sess_step3_ndis_plan", "turn_count": 9, "total_prompt": 6900, "total_response": 3800, "total_tool_calls": 6 },
  { "step_session": "sess_step4_documents", "turn_count": 4, "total_prompt": 2200, "total_response": 1400, "total_tool_calls": 2 },
  { "step_session": "sess_step5_medical", "turn_count": 8, "total_prompt": 5600, "total_response": 3300, "total_tool_calls": 7 }
]
```

Sum of all 5 = total onboarding flow token spend (~50k tokens prompt + ~16k response for this hypothetical run). That's the basis for the tier sizing in `TOKEN_ESTIMATES_FOR_CLIENT.md` once 4 weeks of real data lands.

---

## 7. How to actually see these logs

`structlog` in SENA uses the same writers configured per service in `core/logging.py`. By default it writes JSON to stdout. Three paths to capture:

### Local dev (uvicorn running in your terminal)

You see the logs directly in the terminal. Pipe stdout to a file:

```powershell
python -m uvicorn src.onboarding.main:create_app --factory --reload --port 8089 *> onboarding.log
# Then in another terminal:
Get-Content onboarding.log -Wait | Select-String "ai_usage"
```

### EC2 deploy

Docker stdout → CloudWatch via the `awslogs` driver (already configured per `docker-compose.deploy.yml`). Filter the log group with:

```
{ $.event = "ai_usage" }
```

Then query subsets:

```
{ $.event = "ai_usage" && $.feature = "case_note_summary" }
{ $.event = "ai_usage" && $.success = false }
{ $.event = "ai_usage" && $.tenant_id != "phase1_tbd" }   # once Phase 1.5 ships real tenant_id
```

### Quick local one-liner

```bash
# Watch only ai_usage events as they fire
tail -f onboarding.log | jq 'select(.event=="ai_usage")'

# Sum total tokens consumed in the last hour
tail -n 10000 onboarding.log | jq -s '
  [.[] | select(.event=="ai_usage")]
  | { total_prompt: map(.prompt_tokens) | add,
      total_response: map(.response_tokens) | add,
      call_count: length }
'
```

---

## 8. What you DON'T see (and why)

- **No prompt text / response text.** Hard rule — NDIS APP 11 compliance. Only counters land in logs.
- **No participant data.** No DOB, name, NDIS number anywhere in the emit.
- **No tenant breakdown YET.** `tenant_id` is currently the sentinel `"phase1_tbd"` because the auth context isn't threaded through to the LLM call sites. Phase 1.5 fixes this — adds `tenant_id=ctx.tenant_id` kwarg at every route handler. Until then, all calls roll up under one bucket.
- **`session_id` is null for Bedrock case-note-drafting today.** The voice service's `dictation_service.py` calls `bedrock.run_dictation_turn(...)` without passing `session_id`. Phase 1.5 fixes this too — needs ~3 LOC in `dictation_service.py` to pass the existing `session.shift_id`.

---

## 9. Sample 1-minute log capture (synthesised, illustrative)

A typical 1-minute window mid-onboarding for one participant might look like:

```jsonc
{"event":"ai_usage","feature":"voice_onboarding","model":"gemini-3.1-flash-live-preview","session_id":"sess_step1","prompt_tokens":480,"response_tokens":290,"tool_call_count":1,"turn_id":0,"audio_chunks_out":12,"success":true}
{"event":"ai_usage","feature":"voice_onboarding","model":"gemini-3.1-flash-live-preview","session_id":"sess_step1","prompt_tokens":620,"response_tokens":310,"tool_call_count":1,"turn_id":1,"audio_chunks_out":14,"success":true}
{"event":"ai_usage","feature":"voice_onboarding","model":"gemini-3.1-flash-live-preview","session_id":"sess_step1","prompt_tokens":580,"response_tokens":405,"tool_call_count":2,"turn_id":2,"audio_chunks_out":18,"success":true}
{"event":"ai_usage","feature":"voice_onboarding","model":"gemini-3.1-flash-live-preview","session_id":"sess_step1","prompt_tokens":540,"response_tokens":320,"tool_call_count":1,"turn_id":3,"audio_chunks_out":14,"success":true}
{"event":"ai_usage","feature":"voice_onboarding","model":"gemini-3.1-flash-live-preview","session_id":"sess_step1","prompt_tokens":610,"response_tokens":290,"tool_call_count":1,"turn_id":4,"audio_chunks_out":11,"success":true}
{"event":"ai_usage","feature":"case_note_drafting","model":"anthropic.claude-3-5-sonnet-20241022-v2:0","session_id":null,"prompt_tokens":2840,"response_tokens":612,"latency_ms":1640,"success":true,"history_turns":3}
{"event":"ai_usage","feature":"case_note_summary","model":"gemini-3-flash-preview","session_id":null,"prompt_tokens":4823,"response_tokens":412,"latency_ms":480,"success":true,"new_note_count":5}
```

5 voice turns + 1 case-note drafting + 1 case-note summary = 7 events / minute. Roughly 420 events/hour for one active user. At Tier 4 (~20 workers concurrent) that's ~8,000 events/hour worst case — well within structlog/CloudWatch capacity.

---

## 10. Next steps

| What | Where |
|------|-------|
| Real tenant_id breakdown | Phase 1.5 — thread from AuthContext at route handlers (~4 LOC × 6 routes) |
| `session_id` on Bedrock case-note rows | Phase 1.5 — pass `session_id=session.shift_id` from `dictation_service.py` |
| PSR / Monthly Report `feature=` | Phase 1.5 — pass at the case_review route handler that calls `summarise()` |
| Nightly Postgres rollup | Phase 2 — see `PLAN.md` (the full architecture plan) |
| Athena queries on per-turn forensic data | Phase 2 — once CloudWatch → S3 export wired |
