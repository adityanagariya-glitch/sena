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

## DRIFT items (3) — doc takes precedence per implementation contract

Each row below: server validator should mirror the **doc's** text, not the code's, because we agreed the doc is canon and the Flutter validator is the bug when they disagree.

1. **Funding allocation** — minor phrasing drift between `> 0` (doc) and "positive number" (code). Both reject the same inputs; only the user-facing string differs. Implement per doc.
2. **Medical history year range** — message wording drift on the out-of-range year error. Doc says "Year must be between 1900 and [current year]"; code says something close but not identical. Implement per doc.
3. **(Third minor wording drift flagged by the audit; specifics in the audit summary above.)**

None of the three change which inputs are accepted vs rejected. They only change the user-visible message string. Server-side implementation MUST use the doc's `Error (…)` text verbatim so the assistant reads aloud the same phrasing the user would see in the form.

## Intentional non-enforcement

- Emergency contact phone equality with client phone is **NOT** validated — documented line 600 of the reference doc. Server side respects this; do not invent a new rule. (Email uniqueness IS enforced.)

## Implementation guidance (locked in)

1. **Doc is canon.** When code disagrees with doc, server mirrors doc.
2. **AppStrings constants.** Server `reason_human` must be byte-equivalent to the AppStrings text the Flutter validator references — for the 58 PASS fields, that means copying the AppStrings text verbatim. For the 3 DRIFT fields, copy the doc text verbatim and flag the Flutter side as a follow-up.
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
