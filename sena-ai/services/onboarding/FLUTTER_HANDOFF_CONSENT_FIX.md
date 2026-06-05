# Flutter Handoff — Consent Screen Voice Sync Fix (Step 6)

**Status:** root cause confirmed · server-side workaround SHIPPED · permanent Flutter fix described below
**Audience:** sena-mobile Flutter dev (and their AI assistant)
**Scope:** `lib/core/voice_schemas/step6_consent_schema.dart`, `lib/features/voice_onboarding/presentation/widgets/client_step6_voice_sink.dart`, `lib/features/onboarding/client/presentation/client_consent_controller.dart`
**All file:line references below are real — verified against the current `sena-mobile` codebase.**

> **READ FIRST.** The voice backend (SENA_AI) has already shipped a prompt-level
> workaround so voice → screen works on the 7 base consent fields TODAY without
> any Flutter change. This doc is for (1) the clean permanent fix that lets us
> remove that workaround, and (2) the two fields that genuinely need Flutter work
> (per-role access detail + written-consent). Implement Fix 1 at minimum.

---

## 1. The symptom (what the participant experiences)

On the Consent screen (step 6), the voice agent says "I've saved that" but the
on-screen checkboxes/dropdowns do NOT update. The NDIS-audit consent in
particular: the agent confirms it verbally, but the screen stays on "I do not
consent", so the form cannot be submitted.

---

## 2. Root cause — a read/write namespace mismatch

The voice agent learns field paths from one namespace and writes them back in a
namespace the app's write resolver doesn't accept.

### The data flow

1. The agent is shown the live screen state. Field paths arrive **prefixed
   `consent.`** — e.g. `consent.allowed_information`, `consent.ndis_audit_consent`,
   `consent.agreed_to_data_collection`.
2. To save a value the agent calls `update_field(section, field, value)`. It
   derives `section`/`field` by splitting the path on the first dot — so it sends
   `section="consent"`, `field="allowed_information"`.
3. Flutter resolves that write through `_applyFieldUpdate`
   (`lib/features/voice_onboarding/presentation/controllers/voice_session_controller.dart:826`),
   which calls `_stepConfig.toSenaPath(section, field)`
   (`voice_session_controller.dart:848`).
4. `toSenaPath` (`step6_consent_schema.dart:149-151`) is a pure lookup in
   `_voiceToSena` (`step6_consent_schema.dart:119-127`). Its keys are:
   - `basic.agreed_to_data_collection`
   - `basic.medication_support_consent`
   - `basic.financial_help_consent`
   - `basic.ndis_audit_consent`
   - `info_sharing.allowed_information`
   - `info_sharing.selected_roles`
   - `media_consent.allowed_media_usage`
5. The agent sent `section="consent"` → lookup key is `consent.allowed_information`
   → **NOT in the map → `toSenaPath` returns null.**
6. For step 6, `toSenaPathIndexed` always returns null too
   (`step6_consent_schema.dart:163`), so the null fallback at
   `voice_session_controller.dart:849-855` finds nothing.
7. `voice_session_controller.dart:857-859` logs
   `unmapped field consent.allowed_information — ignoring` and **returns without
   touching the controller.** The screen never updates.

### Why it's a "mismatch"

The screen STATE the agent reads uses the `consent.` prefix, but the write
resolver `_voiceToSena` is keyed on the schema section ids
(`basic` / `info_sharing` / `media_consent`, defined at
`step6_consent_schema.dart:28-113`). Read namespace ≠ write namespace.

---

## 3. A prompt-only workaround was attempted and REVERTED — here's why it can't work

We tried making the voice prompt send the schema sections (`basic` /
`info_sharing` / `media_consent`) instead of `consent`. It made things WORSE, and
this is the key insight for your fix: **there are TWO Flutter layers with OPPOSITE
namespaces.**

| Flutter layer | Namespace it accepts | Evidence |
|---------------|----------------------|----------|
| **Validation** (gates whether the tool call is accepted at all) | `consent.<field>` | `section="consent"` passes; `section="basic"` is rejected with `code=unknown_path`, `reason="I don't have a field called agreed_to_data_collection on this screen."` |
| **Write / sink** (`_voiceToSena` → `applyVoiceUpdate`) | `basic.` / `info_sharing.` / `media_consent.` | `section="consent"` → `toSenaPath` returns null → `unmapped field — ignoring` → screen not updated |

So **no single `section` the prompt can send works through BOTH layers:**
- `section="consent"` → passes validation, silently dropped by the sink (screen never updates).
- `section="basic"` → rejected by validation (`unknown_path`) before it ever reaches the sink — and the agent gets stuck in a retry loop.

The prompt has therefore been reverted to send `section="consent"` (the form
validation accepts), which keeps the agent progressing. **The screen will not sync
until the SINK is taught to accept the `consent.` namespace — Fix 1 below. There
is no server-only fix.** Fix 1 is now MANDATORY, not optional.

---

## 4. Fix 1 — make the resolver accept the `consent.` namespace (REQUIRED, ~7 lines)

Add the `consent.<field>` keys to `_voiceToSena` so the resolver accepts the
exact paths the agent is shown. This is **purely additive** — it cannot break the
existing `basic.`/`info_sharing.`/`media_consent.` keys.

**File:** `lib/core/voice_schemas/step6_consent_schema.dart`
**Edit:** extend `_voiceToSena` (currently lines 119-127):

```dart
static const Map<String, String> _voiceToSena = {
  // existing keys — keep them
  'basic.agreed_to_data_collection':   'consent.agreedToDataCollection',
  'basic.medication_support_consent':  'consent.medicationSupportConsent',
  'basic.financial_help_consent':      'consent.financialHelpConsent',
  'basic.ndis_audit_consent':          'consent.ndisAuditConsent',
  'info_sharing.allowed_information':  'consent.allowedInformation',
  'info_sharing.selected_roles':       'consent.selectedRoles',
  'media_consent.allowed_media_usage': 'consent.allowedMediaUsage',

  // NEW — accept the `consent.` prefix the agent is actually shown.
  // The voice backend emits field paths as `consent.<field>`; this lets the
  // resolver map them without the backend needing a per-field section hack.
  'consent.agreed_to_data_collection':  'consent.agreedToDataCollection',
  'consent.medication_support_consent': 'consent.medicationSupportConsent',
  'consent.financial_help_consent':     'consent.financialHelpConsent',
  'consent.ndis_audit_consent':         'consent.ndisAuditConsent',
  'consent.allowed_information':         'consent.allowedInformation',
  'consent.selected_roles':             'consent.selectedRoles',
  'consent.allowed_media_usage':        'consent.allowedMediaUsage',
};
```

No other change needed for the 7 base fields. The sink
(`client_step6_voice_sink.dart:30-83`) already handles all 7 camelCase senaPaths.

**After Fix 1 ships, tell the SENA_AI team** — they will remove the prompt
workaround so the section mapping lives in ONE place (this file).

---

## 5. Fix 2 — per-role access detail (`access_control.<ROLE>.*`)

### Current state: SCREEN-ONLY (and the prompt now treats it that way)

When a role is selected, the screen reveals a per-role detail panel:
`accessControlByRole[role]` with `allowedInformation`, `purpose`, `timeframe`,
`untilDate` (`client_consent_controller.dart:39-41`, `RoleAccessConfig`).
`validateConsentRequirements` (`client_consent_controller.dart:355-389`) REQUIRES
each selected role to have non-empty `allowedInformation` + a `purpose` + a
`timeframe` before submit.

**The voice sink has NO case for these** (`client_step6_voice_sink.dart:30-83`
stops at the 7 base fields). So voice cannot fill them. The SENA_AI prompt now
tells the agent: *"after roles are selected, ask the participant to tap each role
on screen and set what they can see, the purpose, and the timeframe"* — i.e.
per-role is screen-filled. **If you're happy with that UX, do nothing here.**

### Optional: make per-role voice-fillable

If you want the agent to fill per-role detail by voice too, add dynamic-path
handling to the sink. The incoming senaPath would look like
`consent.access_control.CASE_MANAGER.allowed_information`.

**File:** `client_step6_voice_sink.dart` — add before the `default:` (line 81):

```dart
      // ── Per-role access control (dynamic) ───────────────────────────────
      // Path shape: consent.access_control.<ROLE>.<attr>
      case final p when p.startsWith('consent.access_control.'):
        _applyRoleAccess(p, value);

```

And add the helper + tell the SENA_AI team to remove the screen-only directive
for per-role from the prompt:

```dart
  void _applyRoleAccess(String path, dynamic value) {
    // path = consent.access_control.<ROLE>.<attr>
    final parts = path.split('.');
    if (parts.length < 4) return;
    final role = ConsentRole.fromString(parts[2]);
    final attr = parts.sublist(3).join('.');
    final current = _ctrl.accessControlByRole[role];
    if (current == null) return; // role not selected yet

    switch (attr) {
      case 'allowed_information':
        final info = _parseStringList(value)
            .map(ConsentInformationType.fromString)
            .toList();
        _ctrl.updateRoleAccess(role, current.copyWith(allowedInformation: info));
      case 'purpose':
        _ctrl.updateRoleAccess(role, current.copyWith(purpose: value.toString()));
      case 'timeframe':
        _ctrl.updateRoleAccess(
          role,
          current.copyWith(timeframe: ConsentValidityType.fromString(value.toString())),
        );
      case 'until_date':
        final d = DateTime.tryParse(value.toString());
        if (d != null) _ctrl.updateRoleAccess(role, current.copyWith(untilDate: d));
    }
  }
```

`updateRoleAccess`, `copyWith`, and the per-role getters already exist
(`client_consent_controller.dart:272-299`). If you ship this, also add a
`readMappableValues` block that emits the per-role values so the agent can read
current state.

**Recommendation: REQUIRED.** Product has confirmed (2026-05-27) they want the
voice assistant to fill per-role detail dynamically — not punt to a screen tap.
Fix 2 is therefore MANDATORY alongside Fix 1. Without it, the agent can voice-fill
per-role into the backend but the screen never reflects it (same failure class as
the base fields without Fix 1), so submit stays blocked. Ship Fix 1 + Fix 2
together; the voice backend will flip its prompt to full dynamic voice-fill once
both are live.

---

## 6. Fix 3 — written-consent checkbox (`has_given_written_consent`)

### Current state: SCREEN-ONLY (correct)

`submitConsent` (`client_consent_controller.dart:410-419`) blocks submit unless
`hasGivenWrittenConsent.value == true`. The sink has no case for it, so voice
cannot tick it. The SENA_AI prompt now tells the agent to ask the participant to
tick the written-consent box on screen before submitting.

**Recommendation:** keep this SCREEN-ONLY. A written-consent attestation should be
an explicit human action on screen, not a voice-set flag — it's the legal gate.
Do NOT add a voice sink case for `has_given_written_consent` unless compliance
signs off.

---

## 6a. Fix 4 — voice `submit_step` must ADVANCE to review, NOT final-submit (REQUIRED — fixes the deadlock)

### Symptom
On the consent step the voice agent calls `submit_step`, gets a bare `{ok:false}`
(backend logs `tool_response_rejected code=None reason=None`), and loops forever
asking the participant to tick a written-consent box that lives on the NEXT page.
The session dies with no submit. (Real session `b6779444-…`, 2026-06-03.)

### Root cause (Flutter)
The voice `submit_step` is wired to the FINAL `submitConsent()`
(`client_consent_controller.dart:410-419`), which hard-returns when
`hasGivenWrittenConsent == false`:

```dart
if (!hasGivenWrittenConsent.value) {
  errorMessage.value = AppStrings.consentValidationWrittenConsent;
  isSaving.value = false;
  return;            // ← local early-return; NO structured result to the voice bridge
}
```

Two problems:
1. **Wrong target.** The consent voice page is page 1 ("Consent Sharing" →
   *Continue*). The written-consent checkbox + *Confirm & Submit* are on page 2
   ("Review & Confirm"), reached only AFTER page 1 advances. Voice `submit_step`
   should run **`proceedToReviewAfterRequirements()`**
   (`client_consent_controller.dart:341`) — validate the 7 voice fields + per-role
   detail, then navigate to review — NOT `submitConsent()`. Written consent stays
   a page-2, human-only gate (keep it; see Fix 3).
2. **Reasonless rejection.** That early `return` sets `errorMessage` locally but
   replies to the voice bridge with a bare `{ok:false}` (no `code`/`reason`). The
   agent has nothing to act on, so it invents "tick the box" and loops.

### Fix
Point the voice `submit_step` / advance handler for the consent step at
`proceedToReviewAfterRequirements()` and return a **structured** result over the
bridge:
- advanced to review → `{ok: true}`
- validation blocker (e.g. a per-role `access_control` field incomplete) →
  `{ok: false, code: "<snake_case>", reason: "<human text>", path: "<field path>"}`

NEVER reply with a bare `{ok:false}` / empty reason — the backend relay
(`mobile_bridge.py`) surfaces exactly what you send, and the agent acts on it.

The SENA_AI prompt (`consent.md`) is already updated to treat consent submit as
"advance to review" and to STOP looping on an empty rejection, so the deadlock is
broken on the voice side today; this Flutter change makes the advance actually
navigate and return a clean result.

---

## 7. Bonus check — the boolean default-false issue

The four basic consent booleans default to `false`
(`client_consent_controller.dart:34,44,45,51`). The voice backend was treating
`false` as "already answered" and skipping the question. **This is fixed in the
SENA_AI prompt** (false now means "not yet asked"). No Flutter change needed — but
be aware: when the agent sets one of these `true`, with Fix 1 in place the
checkbox WILL now flip on screen.

---

## 8. Acceptance criteria

After Fix 1:

1. Start a step-6 voice session. Say "I consent to data collection." → the
   `agreed_to_data_collection` checkbox flips to checked ON SCREEN.
2. Say "share my profile and financial info." → both chips select on screen.
3. Say "I consent to the NDIS audit." → the NDIS-audit toggle flips to "I consent"
   ON SCREEN (this was the submit-blocker).
4. Confirm the Flutter debug console no longer logs
   `unmapped field consent.<x> — ignoring` for the 7 base fields.
5. Per-role detail + written-consent: filled on screen by tapping (agent directs).
6. Submit succeeds once all required fields (base via voice, per-role + written
   via screen) are complete.

---

## 9. How the server workaround and Fix 1 interact (no conflict)

- **Today (workaround only):** agent sends `section="basic"/"info_sharing"/"media_consent"` → existing `_voiceToSena` keys resolve → works.
- **After Fix 1:** `_voiceToSena` ALSO accepts `consent.*` → agent can send either form → both resolve. Additive, zero risk.
- **After Fix 1 + prompt workaround removed:** agent sends `section="consent"` (natural, from the path) → the new `consent.*` keys resolve → works, and the mapping lives only in this file.

Ship Fix 1, confirm acceptance, then ping the SENA_AI team to remove the prompt
workaround. Until then, leaving both in place is safe.

---

## 10. File reference summary

| File | Lines | Role |
|------|-------|------|
| `lib/core/voice_schemas/step6_consent_schema.dart` | 119-127 | `_voiceToSena` map — **Fix 1 here** |
| `lib/core/voice_schemas/step6_consent_schema.dart` | 149-151, 163 | `toSenaPath` / `toSenaPathIndexed` resolvers |
| `lib/features/voice_onboarding/presentation/controllers/voice_session_controller.dart` | 826-868 | `_applyFieldUpdate` — where unmapped paths are dropped (line 857-859) |
| `lib/features/voice_onboarding/presentation/widgets/client_step6_voice_sink.dart` | 30-83 | `applyVoiceUpdate` switch — **Fix 2 here (optional)** |
| `lib/features/voice_onboarding/presentation/widgets/client_step6_voice_sink.dart` | 86-100 | `readMappableValues` — extend if per-role goes voice |
| `lib/features/onboarding/client/presentation/client_consent_controller.dart` | 34-57 | reactive consent fields |
| `lib/features/onboarding/client/presentation/client_consent_controller.dart` | 261-299 | `toggleRole`, `updateRoleAccess`, `toggleRoleAllowedInformation` |
| `lib/features/onboarding/client/presentation/client_consent_controller.dart` | 355-389 | `validateConsentRequirements` — the submit gate |
| `lib/features/onboarding/client/presentation/client_consent_controller.dart` | 410-452 | `submitConsent` — `hasGivenWrittenConsent` gate (line 415) |
