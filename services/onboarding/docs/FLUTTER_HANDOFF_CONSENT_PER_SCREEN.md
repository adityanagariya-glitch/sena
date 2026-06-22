# Flutter hand-off — per-screen consent prompts + assistant dialog/checkbox control

**Date:** 2026-06-18 · **Owner of this change:** `sena-mobile` Flutter team ·
**Backend side:** DONE (this commit).

## Why

The three consent screens (Overview, Sharing, Review & Confirm) all run one voice
session that hardcodes `step.id = 'consent'`
(`lib/features/onboarding/client/presentation/voice/client_consent_voice_handler.dart:31`).
The backend selects the system prompt purely by `{step.id}.md`
(`services/onboarding/voice/prompt_builder.py` → `_step_rules_section`, recursive
`rglob`). One `step.id` → one prompt → a single `consent.md` had to cover all
three screens at once, which made the model hallucinate (mixing overview chatter,
field-filling, and the final checkbox).

The backend now ships **three** prompts. They only take effect once Flutter sends
a **distinct `step.id` per screen**.

## Backend is already done (no further backend work)

| File | Change |
|------|--------|
| `prompts/steps/client/consent_overview.md` | NEW — explain-only prompt for the Overview screen. |
| `prompts/steps/client/consent.md` | TRIMMED — Sharing-screen only (field-filling + per-role direction + Continue/confirm). |
| `prompts/steps/client/consent_review.md` | NEW — Review screen: tick written-consent checkbox + Confirm & Submit. |
| `voice/tools.py` | NEW tool `confirm_dialog(decision: "yes"\|"no")` in `FUNCTION_DECLS` + `_KNOWN_TOOLS` + preflight. Generic bridge proxy. |

Routing is automatic: drop-in files resolve via `{step.id}.md`. No backend
allowlist rejects the new ids (`_step_id_to_number` hashes arbitrary ids).

## Required Flutter changes

### 1. Distinct `step.id` per screen (load-bearing)

Each consent screen must report its own `step.id` to the backend in the
`TurnPayload` `step` object (the value at `client_consent_voice_handler.dart:31`):

| Screen | Flutter file | `step.id` to send | Loads prompt |
|--------|--------------|-------------------|--------------|
| Overview | `consent_overview_screen.dart` | `consent_overview` | `consent_overview.md` |
| Sharing | `consent_sharing_screen.dart` | `consent` *(unchanged)* | `consent.md` |
| Review & Confirm | `consent_review_screen.dart` | `consent_review` | `consent_review.md` |

Keep `label`/`number` as you like (e.g. `Consent`, `6`); only `id` drives prompt
selection.

### 2. One voice session per screen (NOT one shared session)

The backend builds the system prompt **once, at session creation**
(`api/ws_routes.py:212`, from the initial `TurnPayload`). A single live session
**cannot** swap prompts mid-flow. So each screen must run its **own** WS voice
session with its own `step.id` — consistent with the existing "one WS session =
one onboarding step" design. Practically: start (or restart) the voice session on
entering each consent screen, and close it on navigation away.

- **Overview:** voice session with `step.id=consent_overview`. The prompt does NOT
  field-fill or submit; the user taps **Continue** manually to advance.
- **Sharing:** voice session with `step.id=consent` — behaves exactly as today
  (field-filling + per-role on-screen direction). **Keep this working as-is.**
- **Review:** voice session with `step.id=consent_review`. **Voice must be active
  on this screen** — today it ends at Sharing. The prompt ticks the checkbox and
  drives Confirm & Submit, so the session has to be live here.

### 3. Wire the new `confirm_dialog` tool (Sharing screen popup)

On the Sharing screen, pressing **Continue** raises the "Are you sure you want to
continue?" dialog (`consent_sharing_screen.dart` → `_showConsentConfirmDialog` /
`_ConsentConfirmDialog`, "No"/"Yes" buttons). The assistant can now answer it:

- Backend emits `confirm_dialog({"decision": "yes"})` → tap the **Yes** button
  (proceed to Review).
- `confirm_dialog({"decision": "no"})` → tap the **No** button (dismiss, stay).

Add a handler case in `client_consent_voice_handler.dart` for `confirm_dialog`
that taps the corresponding button on the currently-shown dialog and returns
`{ok: true}`, or `{ok: false, reason: "no dialog open"}` if none is showing.
Leave the existing voice Continue/advance path working — `confirm_dialog` is
additive.

### 4. Checkbox is already wired — just keep it reachable on Review

`consent.has_given_written_consent` is **already** handled by the voice handler
(`client_consent_voice_handler.dart:128` → `ctrl.hasGivenWrittenConsent`). The
Review screen's `AppCheckboxTile` is bound to `controller.hasGivenWrittenConsent`.
So with voice active on the Review screen (item 2), the assistant ticking the box
via `update_field("consent","has_given_written_consent", true)` already flows
through — verify it visibly ticks and enables the **Confirm & Submit** button. No
new wiring needed beyond keeping the session alive on Review.

## Acceptance checklist

- [ ] Overview screen: ask "what is this screen about?" → assistant explains, fills
      nothing, does not submit.
- [ ] Sharing screen: existing field-filling + per-role flow unchanged.
- [ ] Sharing screen: assistant can answer the "Are you sure?" popup via voice
      (`confirm_dialog` yes/no taps the right button).
- [ ] Review screen: voice is live; assistant ticks/unticks the written-consent
      box and drives Confirm & Submit.
- [ ] Each screen loads its own prompt (confirm via server logs / `prompt_version`).
