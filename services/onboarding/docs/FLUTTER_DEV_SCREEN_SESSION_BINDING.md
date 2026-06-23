# Flutter Dev — Voice session MUST be bound to the screen that created it

> **Audience:** mobile/Flutter dev. **Severity: P0** — a wrong binding makes the voice assistant
> completely unusable on the affected screen (it dead-ends and the participant has to give up).
> **This is a Flutter lifecycle bug, not a backend bug** — the backend faithfully relays whatever your
> app reports. See `FLUTTER_HANDOFF_MASTER.md` §1.7 (Flutter owns state) for the contract this builds on.

---

## Symptom (observed in testing, 2026-06-22)

The participant opened the voice assistant **on the Consent screen**. The agent greeted, then:
- read back **Medical Information** fields (primary diagnosis, doctor, mobility, medications…),
- every time the user said "we're on the consent screen", the agent apologised, tried to save a consent
  field, got rejected, and **circled back to medical information**,
- finally said *"I'm stuck on the medical information section"* and the session was abandoned.

The screen never advanced; the agent could never act on the consent screen the user was actually on.

## Root cause — the session and the tool-handler point at different screens

Two parts of your app disagreed about which screen is live:

| Source | What it said |
|--------|--------------|
| **Session create** (`POST /v1/onboarding/session`) | `step = consent`, with consent bootstrap values — **correct**, the user is on consent |
| **Tool callbacks** (`get_current_state`, `update_field`) | answered from the **Medical Information** screen's controller (`step_id = medical_information`, step 5) |

So the agent was given a **consent** prompt, but every *live* query it made was answered by the
**medical** screen. Result: it read medical data, and every consent write came back
`{ok:false, code:"unknown_path"}` ("I don't have a field called `agreed_to_data_collection` on this
screen") — because the screen actually answering was medical, which has no consent fields.

**Why:** when the user navigated Medical (step 5) → Consent (step 6), the **medical screen's voice
controller / WS tool-request handler was not torn down**. The consent screen created a new session, but
the stale medical handler is the one still receiving and answering the `tool_request` frames for it.

### Proof from the backend logs

```
session_created            step=consent                       ← session is consent
tool_response_state        step_id=medical_information  step_number=5   ← get_current_state answered by MEDICAL
tool_response_rejected     field=agreed_to_data_collection  code=unknown_path
                           reason="I don't have a field called agreed_to_data_collection on this screen."
```
`step_id` and the rejection both come **from your app** — the backend only logged what you returned.

## The contract you must honour

**The screen that creates a voice session MUST be the one whose controller answers that session's
`tool_request` frames.** Concretely:

1. **On navigating away from a voice screen, tear the voice session down fully** — close/cancel the WS,
   dispose the controller, and unregister its `tool_request` handler. Do this *before* the next screen
   creates its session.
2. **Route `tool_request` frames by session.** The handler that answers `get_current_state` /
   `update_field` for `session_id = X` must be the controller for the screen that created `X` — never a
   stale singleton pointing at the previously-visited screen.
3. **Invariant to assert:** on any screen, the `step_id` your `get_current_state` returns MUST equal the
   `step` you sent in that session's create call. If they differ, you have a stale binding.

### Verify
- Open the assistant on Consent → `get_current_state` returns `step_id = consent` with the 7 consent
  fields (`agreed_to_data_collection`, `medication_support_consent`, …) — **not** `medical_information`.
- Navigate Medical → Consent → the Medical controller is disposed (no longer answers any tool frames).
- A consent `update_field` (e.g. `agreed_to_data_collection = true`) returns `{ok:true}`, not
  `unknown_path`.

## Backend safety net — REMOVED (2026-06-23)

A `screen_session_mismatch` detector was briefly added (compared `get_current_state` step_id vs the session
step) and then **reverted** — it **false-positived on the correct screen**, making the agent wrongly announce
"the assistant is on the wrong screen" during perfectly working flows. The live `get_current_state` step_id
does not reliably equal the session's `schema.step_id` in normal operation, so the comparison was unsound.

**There is no backend backstop.** The screen binding must be correct on the Flutter side (this doc), and the
consent prompt is selected by `schema.step_id` (see `FLUTTER_HANDOFF_CONSENT_3SCREEN_E2E.md`).

## Related
- `FLUTTER_HANDOFF_MASTER.md` §1.7 (validation/state ownership), §3 (error channels) — registered there as item 8.
- Same family as §2.3 (consent namespace mismatch) but broader: there the *fields* were misrouted; here the *entire wrong screen* answers the session.
