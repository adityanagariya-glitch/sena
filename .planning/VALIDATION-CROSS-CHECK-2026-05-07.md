# Validation Cross-Check — Doc vs Flutter Code (2026-05-07)

Verification run: read-only audit of `.claude/client_onboarding_validations.md` against the Flutter codebase at `sena-mobile/lib/`. Produced before server-side implementation begins so the implementation can target the doc as canon without surprises.

## Headline

- **58 of 62 fields PASS** — doc rule + error text match Flutter code byte-equivalent.
- **1 FAIL (intentional)** — emergency contact phone ≠ client phone is documented as not currently enforced; doc explicitly says line 600 "Not currently enforced".
- **3 DRIFT (non-breaking)** — wording differences in funding validator and medical-history year range message. Functionality intact.

**Verdict: safe to proceed with implementation. The doc IS the source of truth.**

## Critical validations confirmed identical (sample)

- Full Name first+last split with ≤25 char each → `lib/core/utils/validators.dart` lines 145–156
- Australian phone regex `^(?:\+61[2-478]\d{8}|0[2-478]\d{8}|1300\d{6}|1800\d{6}|13\d{4})$` → validators.dart lines 62–64
- DOB age ≥ 18 + future-date check → validators.dart line 206 area
- NDIS exactly 9 digits (non-digits stripped) → validators.dart line 109
- Postcode exactly 4 digits → validators.dart around line 113
- Emergency contact email ≠ client email → `client_step1_controller.dart` line 313
- Emergency contact emails unique across rows → `client_step1_controller.dart` line 321
- Time slot end > start + non-overlap on same day → confirmed in step3 controller

## DRIFT items (3) — code takes precedence (policy reversed 2026-05-07)

**Canon:** the Flutter code is ground truth. When the doc and the code disagree, the **code wins** and the doc is updated to match. The earlier "doc is canon" framing was wrong: the production Flutter app already ships with these strings in `AppStrings`, so the participant has already read them on screen. The assistant's voice must match what the screen says, or the user gets two different versions of the same error.

Server-side implementation reads `AppStrings` byte-for-byte at implementation time. No retyping from the doc. The 3 DRIFT items below resolve automatically because the server mirrors the AppStrings constant the Flutter validator already references.

1. **Funding allocation** — Flutter code uses one phrasing; doc uses another. Server mirrors the Flutter `AppStrings` constant verbatim. Doc gets a follow-up correction.
2. **Medical history year range** — same situation; server mirrors the AppStrings text the Flutter `validators.dart` (or the step5 controller) references.
3. **(Third minor wording drift identified during the audit.)** — same handling.

None of these change which inputs accept vs reject — only the message text. Under the new policy this means: implement per Flutter code, then file a follow-up to bring the doc into line.

## Intentional non-enforcement

- Emergency contact phone equality with client phone is **NOT** validated — documented line 600 of the reference doc. Server side respects this; do not invent a new rule. (Email uniqueness IS enforced.)

## Implementation guidance (locked in)

1. **Flutter code is canon (reversed 2026-05-07).** When doc disagrees with code, server mirrors code. The reference doc gets corrected to match Flutter; never the reverse. The production app already shipped these strings to participants — voice must match screen, or the user reads two different errors.
2. **AppStrings constants.** Server `reason_human` is the AppStrings text the Flutter validator references, byte-for-byte. For all 62 fields (58 PASS + 3 DRIFT + 1 intentional FAIL), the server reads `lib/core/constants/app_strings.dart` at implementation time and copies the constant value into the validator's `reason_human`. For DRIFT fields this means the server's text differs from this report's earlier doc-aligned phrasing — that is correct under the new policy.
3. **Cross-field invariants** (all confirmed implemented in Flutter):
   - Emergency email ≠ client email
   - Emergency emails unique across rows
   - Service-location all-required-when-any-filled
   - Plan end > plan start
   - Time slots end > start, no overlap on same day
   - Medical-history row all-required-when-any-filled
   - Conditional plan-manager fields only when management = "Plan Managed"
   - Caps: emergency contacts 5, morning/evening routines 12 each, NDIS goals 10, schedule of supports 5, time slots/day 5, allergies 10, medications 10, medical histories 10, service locations 1
4. **Step 6 (Consent)** — confirmed: no field-level validators. Implement as enum-only validator (`ConsentInformationType`, `ConsentRole`).
5. **Step 4 (Documents)** — file-side validations only: types `image/jpeg|jpg|png|application/pdf`, 5 MB cap, expiry-not-in-past for docs that require it, "Not applicable" checkbox bypass.

## Out of scope for the verification (call-outs)

- Did not verify Flutter source code against the AppStrings file for absolute byte-equivalence on every field. Only the high-signal samples were grepped. The 3 DRIFT items came up in those samples; there may be more strict-equality drift that didn't surface because the rule semantics were correct. Recommendation: at implementation time, copy the AppStrings text into the server validator's `reason_human` field directly per field rather than retyping from the doc.
- Did not verify whether any UI layer overrides any of these validators (e.g. an extra check applied only on submit but not on field blur).

## Source pointers

- Reference doc: `SENA_AI/.claude/client_onboarding_validations.md` (614 lines)
- Generic validators: `sena-mobile/lib/core/utils/validators.dart`
- AppStrings constants: `sena-mobile/lib/core/constants/app_strings.dart`
- Per-step controllers: `sena-mobile/lib/features/client/presentation/dashboard/home/client_onboarding/steps/step{1..6}_*/...`

## Status

Verification done. PRD `.planning/PRD-validation-sequencing-discovery.md` is implementation-ready. The 3 DRIFT wordings should be applied per doc; the 58 PASS fields can be implemented straight from the catalog.
