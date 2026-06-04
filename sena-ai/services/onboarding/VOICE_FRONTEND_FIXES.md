# Voice Onboarding — Frontend (Flutter) Fixes Needed

Two issues reported on the staff voice flow (apply to **all** voice onboarding flows). The backend side of each is now fixed/handled; the remaining work is in the Flutter client. Frame shapes below are the exact contract the backend expects.

---

## Issue 1 — On-screen validation errors never reach the voice agent

**Symptom:** participant changes a field (e.g. date of birth) and the **screen** shows a red validation error, but the **voice assistant says nothing** — it can't tell the participant what's wrong.

**Why:** the backend is a relay (Option D). It only knows about a validation failure if Flutter **tells** it. Two cases:

- **Voice-initiated** change (agent called `update_field`): already works — Flutter returns `{ok:false, reason}` to the tool call and the agent speaks it. ✅
- **Screen-initiated** change (participant typed/picked a value, or a field was rejected on the screen *without* a voice tool call): **Flutter currently sends nothing**, so the agent is blind. ❌ ← this is the bug.

### Backend (already done — 2026-06-04)
The backend now turns a screen validation error into a **spoken cue** on BOTH channels:
- `validation_failed` control frame → `_handle_validation_failed` → speaks it (pre-existing).
- `screen_state` / `screen_state_v2` carrying `field_errors` → now ALSO injects a `[SCREEN VALIDATION] … re-ask` cue for **newly-appearing** errors (new; only fires once per new error, so it won't nag on repeated screen updates).

So the moment Flutter reports the error on **either** channel, the agent will verbalise it and re-ask.

### Flutter — DO THIS
On **every** on-screen validation failure (typed input, date picker, dropdown, etc.), send ONE of:

**Option A — dedicated control frame (preferred, most explicit):**
```json
{
  "type": "validation_failed",
  "section_id": "basics",
  "field_id": "date_of_birth",
  "repeatable_index": null,
  "reason_human": "You must be at least 18 years old",
  "code": "client_validation_failed"
}
```
- `section_id` + `field_id` are REQUIRED (backend drops the frame if either is missing).
- `repeatable_index` only for repeatable rows (else `null`).
- `reason_human` is spoken to the participant verbatim → write it the way you want it heard.
- When the participant fixes it, send `{"type":"validation_cleared","section_id":...,"field_id":...,"repeatable_index":...}` so the agent stops re-asking.

**Option B — include `field_errors` in the screen_state you already send:**
```json
{ "type": "screen_state_v2", "data": { "step_id": "staff_personal_information",
  "field_errors": { "basics.date_of_birth": "You must be at least 18 years old" } } }
```
- Key = dotted `section.field`; value = the human reason.
- NOTE: if you send `screen_state_v2` with a `turn` key, the backend takes the TurnPayload fast-path and **does not** read `field_errors`. To use Option B, send the screen_state **without** a `turn` key (or use Option A).

Either option now produces a spoken re-ask. Option A is recommended because it's unambiguous and carries `validation_cleared`.

---

## Issue 2 — Voice assistant doesn't auto-start at the top of the screen

**Symptom:** the agent doesn't greet/start on its own when the voice screen opens; feels like it waits.

**Why:** `gemini-3.1-flash-live-preview` has **no proactive audio** — the model will not speak first on its own. The backend works around this by injecting a hidden opener turn the moment the WS connects, which makes the agent greet (you can see `AGENT_SAID 'Hi …'` at turn 0 in the logs).

### Backend (already done — 2026-06-04)
Previously the opener was injected **only** when there was bootstrap state to seed; if a screen opened with no seed state, nothing was sent and the agent stayed silent. The backend now **always** injects an opener cue on connect (`kickoff_greeting_injected`), so a greeting is guaranteed server-side on every screen.

### Flutter — DO THIS
The greeting is only *heard* if the client is connected and playing audio when it arrives. On screen mount, **without waiting for a user tap**:
1. **Open the WS** (`/ws/onboarding/{session_id}`) as soon as the session is created.
2. **Start the audio player** immediately so the `turn_start` → audio chunks are played (don't lazy-init the player on first user interaction).
3. **Start the mic stream** right away (gated by `_agentSpeaking` per the echo rule — mute mic on `turn_start`, unmute on `turn_complete`/`interrupted`), so barge-in works and the silence-watchdog timer is fed.
4. Do **not** require a "tap to start" — the backend greets on connect; the screen should be live on mount.

If today there is a manual "start voice" button, auto-trigger that path in the screen's init/`onReady`.

---

## Issue 3 — voice-set values don't render LIVE (e.g. DOB updates only after a session restart)

**Symptom:** the agent updates a field (date of birth), the value IS saved (a new session re-fetches it from the app backend and shows it), but the **current screen doesn't update live** — the date-picker keeps showing the old value until reload.

**Root cause (confirmed by backend trace — this is a Flutter fix, not backend):**
In Option D the backend is a **pure relay**. The flow is:
```
Gemini → update_field → backend → tool_request → Flutter (validate + apply + return {ok:true, state})
```
The backend **does NOT emit any `field_updated` / `state` event afterward** — by design. (`api.md` lists those events, but they are unimplemented and intentionally so for Option D — re-emitting would double-apply.) **The new value reaches Flutter inside the `tool_request` it just processed.** So the screen has everything it needs to update *immediately*; the widget simply isn't rebuilding from Flutter's own state.

**Flutter — DO THIS (general rule, applies to EVERY voice-updated field, not just DOB):**
- The moment you handle an `update_field` `tool_request` and decide `ok:true`, **patch your form/controller state AND rebuild the bound widget right then** — do not wait for any backend event (there isn't one).
- Bind every input widget **reactively to the form state** (e.g. the date-picker's displayed value reads from `state.basics.date_of_birth`), so a state change repaints the widget.
- Non-text widgets are the usual offenders: **date pickers, dropdowns, checkboxes, multi-select chips** often render from a local `initialValue` captured at build time and never rebuild. They must read live from form state.
- Verify with: text fields (e.g. address) that *do* update live use the same path the date-picker should use — make the date-picker follow it.

**DOB specifics:**
- Valid voice DOB → `update_field(section="basics", field="date_of_birth", value="YYYY-MM-DD")` → rebuild the date-picker from state (per the rule above).
- Invalid DOB (under 18) rejected on screen → emit the `validation_failed` frame from **Issue 1** so the agent can say *"you must be at least 18"* and re-ask. (Voice-initiated under-18 rejections already work via the tool response; this is for picker-initiated ones.)
- The age rule (`≥18`, not future) stays **client-side** — the backend does not validate; it relays your `reason_human` verbatim to the agent.

---

## Backend parity guarantee (FYI — no action needed)

Staff onboarding (and every future voice flow) runs the **identical** backend engine as client onboarding — verified flow-agnostic by audit (no `if client`/`if staff`/`step_id ==` branches anywhere). Behaviour differs only by the prompt file (`prompts/steps/<flow>/<step_id>.md`) and the schema you POST. **Every backend fix is automatically shared across all flows** — you never need to ask "does this work for staff too?" for backend logic. The only per-flow surface you own is sending the right `step.id` + schema (see `STAFF_ONBOARDING_HANDOFF.md`).

---

## Quick test after wiring
1. Open the voice screen cold → agent greets within ~2–3 s with no tap. (Issue 2)
2. Type an under-18 DOB in the picker → agent says the age error and re-asks. (Issue 1, Option A/B)
3. Fix the DOB → agent stops re-asking (send `validation_cleared` if using Option A).
