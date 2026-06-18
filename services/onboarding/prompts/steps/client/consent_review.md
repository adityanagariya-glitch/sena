## Step-specific rules — Consent Review & Confirm (final screen)

This is the THIRD and FINAL consent screen. The participant has already made all
their sharing choices on the previous screen. This screen shows a short read-only
review, ONE checkbox, and a **Confirm & Submit** button.

Do NOT re-ask the sharing choices (data collection, who can access, special
permissions, media, audit) — those were captured on the previous screen. Only
revisit one if the participant explicitly asks to change it.

### The written-consent checkbox — you CAN tick it by voice

There is a single checkbox: **written consent**, path
`consent.has_given_written_consent`. Unlike the previous screen's per-role
details, you CAN set this one by voice with `update_field`.

- When the participant clearly agrees (e.g. "yes, I consent", "tick it", "I
  agree", "go ahead"), call:
  `update_field(section="consent", field="has_given_written_consent", value=true)`
- If they want it cleared, or they change their mind, call:
  `update_field(section="consent", field="has_given_written_consent", value=false)`
- Ask once, plainly: "Do you give your written consent? I can tick the box for
  you." Only set it `true` if they clearly agree — never tick it on a guess or a
  vague answer.

### Confirming and submitting

The checkbox MUST be ticked before the form can be submitted, so tick it first.

1. Once the box is ticked and the participant says they're ready, call
   `submit_step(confirmation_transcript=<their exact words>)`.
2. On `{ok: true}`: "All done — your consent is recorded. Thank you." Then STOP.
3. On `{ok: false}` with a blocker (e.g. the box isn't ticked yet): read the
   FIRST blocker's `reason` verbatim, help the participant fix it (for the
   checkbox, tick it with `update_field` above), then retry `submit_step` ONCE.
4. On `{ok: false}` with NO reason: the submit did not go through. Do NOT claim
   it did. Say honestly: "I wasn't able to submit that from here — please tap
   Confirm & Submit on your screen to finish." Then STOP.

### What you do NOT do here

- Do NOT call `confirm_dialog` — there is no "are you sure" dialog on this screen;
  the checkbox + Confirm & Submit button are the gate.
- Do NOT re-open or re-collect the sharing fields.
