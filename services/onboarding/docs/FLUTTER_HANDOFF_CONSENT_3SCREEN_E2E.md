# Flutter Handoff — Consent 3-Screen Voice, END-TO-END (authoritative)

> **Audience:** sena-mobile Flutter dev. **Status:** backend DONE; Flutter NOT done.
> **This supersedes the root-cause pointer in `FLUTTER_HANDOFF_CONSENT_PER_SCREEN.md`.** That doc told you
> to change `client_consent_voice_handler.dart:31` (the per-*turn* payload). That is **not** what selects the
> prompt, which is why the implemented fix didn't work. The value that selects the prompt is the
> **session-create request BODY `step`**, derived from `schema.stepId`. Read §2 carefully.

---

## 0. The one thing that was wrong

The prompt is chosen **only** by **`schema.step_id`** — the `step_id` *inside* the `schema` object of the POST
body. The backend builds the prompt turn from it (`ws_routes.py:163` → `build_system_prompt` →
`rglob("{schema.step_id}.md")`). The **top-level body `step`** only sets FormState/state (`routes.py:336`); it
does **not** pick the prompt. URL query, per-turn `step.id`, and `screen_state_v2` do nothing for prompt
selection either.

Proof from the last run's logs: the body carried `"step": "consent_overview"` **and**
`"schema": {"step_id": "consent"}` in the SAME request, and the overview screen ran the sharing prompt. So
the per-screen top-level `step` was already correct — `schema.step_id` was the hardcoded culprit.

**Vary `schema.step_id` per screen (`consent_overview` / `consent` / `consent_review`). Setting the top-level
`step` alone — which the last fix did — does nothing.**

---

## 1. The three IDs (memorise this table)

| Screen (order) | `step` to send in body | Loads prompt file | Prompt size | Agent behaviour |
|---|---|---|---|---|
| 1. Consent **Overview** (info) | `consent_overview` | `consent_overview.md` | 1592 ch | Explains the screen; fills nothing; never submits |
| 2. Consent **Sharing** (fill) | `consent` | `consent.md` | 6280 ch | Fills the 7 consent fields; per-role direction; Continue/confirm |
| 3. Consent **Review & Confirm** | `consent_review` | `consent_review.md` | 2315 ch | Ticks written-consent checkbox; drives Confirm & Submit |

All three prompt files already exist in the backend. Routing is automatic via `rglob("{step}.md")` — no
backend allowlist, no backend change. Send the right `step`, get the right prompt.

---

## 2. Pure backend contract (how it actually works — no guessing)

### 2.1 Endpoint
`POST /v1/onboarding/session` (via nginx: `POST https://<host>/onboarding/v1/onboarding/session`).

### 2.2 Request body (exact fields — `services/onboarding/api/routes.py` `CreateSessionRequest`)
```jsonc
{
  "participant_id": "<uuid>",          // required
  "step": "consent_overview",          // required — SELECTS THE PROMPT. MUST be the screen's id.
  "schema": { /* StepSchema */          // required (JSON key is "schema")
    "step_id": "consent_overview",      // MUST equal "step" above. See 2.4 — set BOTH.
    "step_label": "Consent",
    "sections": [ /* this screen's sections/fields only */ ],
    "voice_coverage": [ /* paths the agent may touch on THIS screen */ ]
  },
  "bootstrap": {                        // the authoritative state contract (preferred over initial_state)
    "mode": "page_handoff",             // new_user | returning_same_page | page_handoff
    "current_page_values": { },         // THIS screen's current values only (see 2.5)
    "readonly_paths": [ ],
    "prior_pages": { "step:5": { } },   // optional cross-screen summary; backend can auto-hydrate
    "participant_display_name": "Al"
  },
  "locale": "en-AU",
  "tenant_id": "<uuid>"
}
```
Legacy `initial_state` still works but `bootstrap` wins; use `bootstrap`.

### 2.3 What the backend does with it (`routes.py`)
- `step_id = req.step` (line 336) → stored on FormState; logged as `session_create_resolved_bootstrap step=<X>`.
- The system prompt is rendered **once at WS connect** from `schema.step_id` →
  `prompt_builder._step_rules_section(step_id)` → `steps_dir.rglob(f"{step_id}.md")` (`prompt_builder.py:92`).
- A live screen<->session safety net now runs: if `get_current_state` returns a `step_id` ≠ the session's
  step, the backend logs `screen_session_mismatch` and tells the agent to ask you to reopen on the right
  screen. (Added 2026-06-22 — it will fire loudly if you create the session with the wrong `step`.)

### 2.4 Set BOTH `step` and `schema.step_id`
`req.step` drives FormState/state; `schema.step_id` drives the rendered prompt's turn. Keep them **identical**
per screen so state and prompt never disagree. In the current datasource the body `step` is already derived
from `schema.stepId` (`voice_onboarding_remote_datasource.dart:84` → `'step': schema.stepId`), so the single
source of truth you must vary is **`schema.stepId`**.

### 2.5 `bootstrap.current_page_values` must be THIS screen's values
The previous bug also shipped the **sharing** screen's `info_sharing.*` values as bootstrap on every consent
screen (because the sink read the shared consent controller). Each screen's bootstrap must carry only its own
fields: Overview = none/info fields; Sharing = the 7 `consent.*` fields; Review = the review fields.

### 2.6 Response (`CreateSessionResponse`)
```jsonc
{ "session_id": "<uuid>", "ws_url": "/ws/onboarding/<session_id>", "expires_at": "...",
  "resumption_handle": null, "token_usage": { } }
```
Then connect: `wss://<host>/onboarding` + `ws_url` + `?tenant_id=<id>&participant_id=<id>&roles=worker`.
The WS sends `ready` first (no send before it); `ready.state.step_id` will equal your `step` when correct.

---

## 3. Every Flutter change required

### 3.1 Create per-screen schema configs (LOAD-BEARING)
Today there is one `Step6ConsentSchema` with `stepId: 'consent'` (`lib/core/voice_schemas/step6_consent_schema.dart:24`),
reused for all three screens. Create three configs (or one parameterised by screen) so `stepId` varies:
- `consent_overview` schema — overview/info sections, `voice_coverage: []` (nothing voice-fillable).
- `consent` schema — the existing sharing schema (`stepId: 'consent'`, the 7 `consent.*` fields + per-role).
- `consent_review` schema — review section + `has_given_written_consent`.

### 3.2 Each screen creates and owns its OWN voice session
Today only the **Overview** screen calls `bind(...)` (`consent_overview_screen.dart:122-127`); Sharing reuses
that session and Review has no voice. Required:
- **Overview** → `VoiceSessionBinder.bind(stepConfig: ConsentOverviewSchema())` (`step=consent_overview`).
- **Sharing** → its own `bind(stepConfig: Step6ConsentSchema())` (`step=consent`) with the consent controller sink.
- **Review** → its own `bind(stepConfig: ConsentReviewSchema())` (`step=consent_review`); voice **must be live** here.

### 3.3 Dispose the session on navigation (same rule as the §8 binding bug)
On leaving each consent screen, fully tear the session down (close WS, dispose controller, unregister the
`tool_request` handler) BEFORE the next screen binds. One session = one screen = one prompt; the backend
cannot swap prompts mid-session. A stale controller answering the next screen's tool calls reproduces the
exact "stuck on the wrong screen" failure.

### 3.4 Per-screen `bootstrap.current_page_values`
Build the bootstrap from the screen that is mounting, not from a shared controller (see §2.5).

### 3.5 Keep `screen_state_v2` aligned (defensive, not the fix)
Continue pushing `screen_state_v2` with the matching `step_id` per screen. It does NOT select the prompt, but
the backend safety net compares it to the session step — aligned values keep the mismatch warning silent.

### 3.6 Wire the `confirm_dialog` tool (Sharing screen popup)
On Sharing, the "Are you sure you want to continue?" dialog can be answered by voice. Backend emits
`confirm_dialog({"decision":"yes"|"no"})`; add a handler that taps Yes/No on the open dialog and returns
`{ok:true}`, or `{ok:false, reason:"no dialog open"}`. Additive — keep the manual Continue path.

### 3.7 Written-consent checkbox (Review screen)
Already wired (`client_consent_voice_handler.dart` → `ctrl.hasGivenWrittenConsent`). With voice live on Review
(§3.2), the agent ticks it via `update_field("consent","has_given_written_consent", true)` and drives
**Confirm & Submit**. Confirm & Submit stays a human/legal gate — keep it tappable; the agent guides.

### 3.8 Submit returns a STRUCTURED result, never bare (carry over from MASTER §2.4)
On any submit/advance, return `{ok:true}` or `{ok:false, blockers:[{path,label,reason}]}` — never a bare
`{ok:false}`. The agent reads `blockers[0].reason` verbatim and stays put.

---

## 4. End-to-end per screen (copy this flow ×3)

For **each** consent screen, on mount:
1. Build that screen's `StepSchema` with `step_id` = the screen's id (§1).
2. `POST /v1/onboarding/session` with body `step` = same id, `schema` = that schema, `bootstrap.current_page_values`
   = this screen's values, `participant_id`, `tenant_id`.
3. Open WS `wss://<host>/onboarding{ws_url}?tenant_id=…&participant_id=…&roles=worker`; wait for `ready`.
4. Start mic/playback; handle `tool_request` (update_field / confirm_dialog / submit_step) → reply
   `tool_response` within 5s; push `screen_state_v2`.
5. On navigation away: dispose this session (§3.3) before the next screen binds.

### Concrete `step` per screen (the whole point)
```
Overview screen  → body.step = "consent_overview"  → consent_overview.md
Sharing screen   → body.step = "consent"           → consent.md
Review screen    → body.step = "consent_review"     → consent_review.md
```

---

## 5. What does NOT select the prompt (why the last fix failed)

| Layer | Selects prompt? |
|-------|-----------------|
| Body `step` / `schema.step_id` | ✅ **YES — this is the only one** |
| POST **URL** query `?step=…` | ❌ no (logging/routing only) |
| Per-turn payload `step.id` (`client_consent_voice_handler.dart:31`) | ❌ no |
| `screen_state_v2.data.step_id` | ❌ no (only feeds the live-screen safety net) |

If you only changed the bottom three, the prompt never changes. This is exactly what the logs showed.

---

## 6. Verification (do this to confirm the fix)

⚠️ Do NOT verify via `session_create_resolved_bootstrap step=` or the `ready` event's `state.step_id` — both
reflect the **top-level `step`** (`req.step`), which is already per-screen-correct even when `schema.step_id`
is wrong. They look right while the bug persists (this is what fooled the last fix).

1. **Which prompt actually loaded (definitive):** backend log `gemini_bridge_constructed instruction_chars`
   must DIFFER per screen — the per-step fragment sizes are overview ≈ 1592, sharing ≈ 6280, review ≈ 2315,
   so the totals differ. Same `instruction_chars` on two consent screens = same prompt = still broken.
2. **No `screen_session_mismatch`** warning in the backend log during the consent flow (the safety net fires
   when the live screen disagrees with the session).
3. **Behaviour:** on Overview the agent explains and never says "shall we submit?"; on Review it drives the
   checkbox + Confirm & Submit.

---

## 7. Acceptance checklist (hand back when all true)
- [ ] Three schema configs exist with `stepId` = `consent_overview` / `consent` / `consent_review`.
- [ ] Each consent screen creates and disposes its **own** voice session (Overview, Sharing, Review).
- [ ] `session_create_resolved_bootstrap step=` logs the correct id per screen (§6.1).
- [ ] `bootstrap.current_page_values` carries only the mounting screen's fields.
- [ ] Overview: explains only, no submit. Sharing: fills + answers the confirm dialog by voice. Review: voice
      live, ticks written-consent, drives Confirm & Submit.
- [ ] Submit returns `{ok:false, blockers:[…]}` (never bare `{ok:false}`).
- [ ] No `screen_session_mismatch` warnings in the backend log during the consent flow.

---

## 8. Related backend/docs
- Prompt resolver: `services/onboarding/voice/prompt_builder.py:81-92` (`_step_rules_section`, `rglob`).
- Create handler: `services/onboarding/api/routes.py:202` (`create_session`; `step=req.step`).
- Safety net: `services/onboarding/voice/tools.py` `_flag_screen_mismatch` (see `FLUTTER_DEV_SCREEN_SESSION_BINDING.md`, MASTER §8).
- Prompts: `services/onboarding/prompts/steps/client/consent_overview.md` · `consent.md` · `consent_review.md`.
- Supersedes the root-cause pointer in `FLUTTER_HANDOFF_CONSENT_PER_SCREEN.md` (items 3-4 there — confirm_dialog + checkbox — still valid).
