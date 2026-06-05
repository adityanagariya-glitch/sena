# Staff Onboarding — Field Inventory

Source of truth for the SENA voice agent. Every field listed here mirrors the
Flutter UI behaviour. **The voice backend MUST NOT impose validations beyond
what the frontend enforces, and MUST refuse to mutate readonly fields.**

- Code root: `lib/features/onboarding/staff/`
- Validators: `lib/core/utils/validators/base_validators.dart` (`class AppValidators`)
- Entities: `lib/features/onboarding/staff/domain/entities/`
- Generated: 2026-06-04

---

## Conventions

- **id** — voice schema id (dot-path the voice backend should use).
- **wire_path** — the path in the PUT payload to `staff/onboard/stepN`.
- **readonly** — `true` means voice agent MUST NOT call `update_field`; if asked to change it, refuse with the readonly script.
- **required** — `true` means the form blocks `advance_step` until non-empty.
- **enum_values** — exact strings the field accepts. Voice agent MUST map spoken text to one of these literals; any other value is rejected.
- **visible_if** — when set, the field is hidden until the controlling field equals the named value. Voice agent MUST NOT ask for hidden fields.
- **repeatable** — `{min, max}` rows; item-level fields listed under the row.

---

# Step 1 — Personal Information

## Basics

| id | label | type | required | readonly | validations | enum_values |
|----|-------|------|----------|----------|-------------|-------------|
| `basics.full_name` | Full Name | text | true | false | `requiredWithMaxLength(v, 25)`: required; max 25 chars | — |
| `basics.email` | Email Address | email | true | **true** | display only — readonly, pre-filled from invite | — |
| `basics.phone` | Phone Number | phone | true | false | `australianMobile`: E.164 (`+61[2-478]XXXXXXXX`), national (`0[2-478]XXXXXXXX`), `1300/1800` + 6 digits, `13` + 4 digits | — |
| `basics.date_of_birth` | Date of Birth | date | true | false | `dateOfBirthAtLeast18`: not future + age ≥ 18 | — |
| `basics.gender` | Gender | dropdown | true | false | `requiredField` | `Male`, `Female`, `Other` |
| `basics.cultural_background` | Cultural Background | dropdown | true | false | `requiredField` | `Australian`, `Indian`, `Asian` |
| `basics.languages_spoken` | Languages Spoken | multi-enum | true | false | required (≥1 selection) | `English`, `Mandarin`, `Arabic`, `Vietnamese`, `Cantonese`, `Punjabi`, `Greek`, `Italian`, `Hindi`, `Spanish` |
| `basics.requires_interpreter` | Requires Interpreter | boolean | false | false | no validation (defaults false) | `Yes`, `No` |
| `basics.profile_picture` | Profile Photo | file | true | false | max 5 MB; mime: `image/jpeg`, `image/png`, `image/webp` | — |

Wire mapping: `fullName`, `email` (readonly), `phone`, `dateOfBirth` (ISO `YYYY-MM-DD`),
`gender`, `culturalBackground`, `languagesSpoken`, `requiresInterpreter`, `profilePictureUrl`.

## Address

| id | label | type | required | readonly | validations |
|----|-------|------|----------|----------|-------------|
| `address.address` | Address | text (autocomplete) | true | false | `requiredWithMaxLength(v, 100)`: required + max 100 chars |
| `address.state` | State | text (autocomplete) | true | false | `requiredWithMaxLength(v, 25)`: required + max 25 chars |
| `address.city` | City | text (autocomplete) | true | false | `requiredWithMaxLength(v, 25)`: required + max 25 chars |
| `address.zip_code` | Zip Code | text (digits only) | true | false | `staffOnboardingZipCode`: 1–4 digits, range 0–9999 |

Wire mapping: `address`, `state`, `city`, `zipCode` (stored as int).

## Step 1 cross-field rules

- Phone normalised before validation (trim).
- `zip_code` input formatter: digits only; max 4 chars.
- `date_of_birth` picker range: 1900-01-01 to (today − 18 years).
- Email is pre-filled from the invitation and rendered as a disabled field; voice agent must refuse any mutation.

---

# Step 2 — Role Information

## Role (readonly, pre-filled)

| id | label | type | required | readonly | validations |
|----|-------|------|----------|----------|-------------|
| `role_info.role` | Role | text | false | **true** | display only — pre-filled from shell |
| `role_info.department` | Department | text | false | **true** | display only — comma-separated list, pre-filled |

## Experience

| id | label | type | required | readonly | validations |
|----|-------|------|----------|----------|-------------|
| `role_info.experience` | Relevant Experience | textarea | true | false | `requiredWithMaxLength(v, 500)`: required + max 500 chars |

Wire mapping: `relevantExperience`.

## Step 2 cross-field rules

- `role` and `department` are server-prefilled read-only display fields; voice agent must refuse changes to both.
- Experience textarea: min lines 12, max lines 12 in UI; max 500 chars enforced.

---

# Step 3 — Documents Upload

Document slot list is loaded dynamically from `GetStaffOnboardRequiredDocumentsUsecase`.
Each slot exposes the fields below.

## Required document slot (per backend-defined slot)

| id | label | type | required | readonly | constraints |
|----|-------|------|----------|----------|-------------|
| `documents.{slot_id}.document` | `{slot.name}` | file_upload | from slot meta | false | mime: `application/pdf`, `image/jpeg`, `image/png`, `image/webp`; max 5 MB |
| `documents.{slot_id}.expiry_date` | Expiry Date | date | required iff slot `hasExpiry == true` AND file uploaded | false | `futureDateRequired`; `firstDate = today + 1`, `lastDate = 2100-12-31` |
| `documents.{slot_id}.not_applicable` | Not Applicable | checkbox | false | false | shown only when `slot.isRequired == false` |
| `documents.{slot_id}.ocr_data` | OCR Fields | map of text fields | false | false | editable text fields per extracted key (Name, Certificate Number, Expiry Date, Card Number) |

Wire shape per slot:
```json
"uploadedDocument": {
  "{slot_id}": {
    "notApplicable": false,
    "document": "<s3-url>",
    "fileName": "...",
    "fileSize": 12345,
    "expiresAt": "YYYY-MM-DD"
  }
}
```

## Step 3 validation rules

- Required slots (`isRequired: true`) must have a file — cannot be `notApplicable: true`.
- Optional slots must either have a file OR have `notApplicable: true`.
- `expiry_date` required iff backend slot has `hasExpiry == true` AND file is present.
- Expiry date must be strictly after today (not today itself).
- File size ≤ 5 MB (5,242,880 bytes).
- Allowed extensions: `pdf`, `jpg`, `jpeg`, `png`, `webp`.

---

# Step 4 — Banking & Superannuation Details

## Bank Details

| id | label | type | required | readonly | validations |
|----|-------|------|----------|----------|-------------|
| `banking.bank_name` | Bank Name | text | true | false | `requiredWithMaxLength(v, 50)`: required + max 50 chars |
| `banking.account_holder_name` | Account Holder Name | text | true | false | `requiredWithMaxLength(v, 50)`: required + max 50 chars |
| `banking.bsb` | BSB | text (digits only) | true | false | `bsb`: exactly 6 digits (`^\d{6}$`) |
| `banking.account_number` | Account Number | text (digits only) | true | false | `accountNumber`: required + max 12 chars/digits |

Wire mapping: `bankName`, `accountHolderName`, `bsb`, `accountNumber`.

## Superannuation

| id | label | type | required | readonly | validations |
|----|-------|------|----------|----------|-------------|
| `superannuation.fund_name` | Super Fund Name | text | true | false | `requiredWithMaxLength(v, 50)`: required + max 50 chars |
| `superannuation.fund_abn` | Super ABN | text (digits only) | true | false | `superFundAbn`: exactly 11 digits (`^\d{11}$`) |
| `superannuation.member_number` | Member Number | text | true | false | `requiredWithMaxLength(v, 50)`: required + max 50 chars |

Wire mapping: `superFundName`, `superFundAbn`, `memberNumber`.

## Tax Declaration Document (conditional)

Same document-slot structure as Step 3. Document list fetched from
`GetStaffOnboardRequiredBankDocumentsUsecase`.

| id | label | type | required | constraints |
|----|-------|------|----------|-------------|
| `banking.documents.{slot_id}.document` | `{slot.name}` | file_upload | from slot meta | mime: PDF/JPG/PNG/WebP; max 5 MB |
| `banking.documents.{slot_id}.expiry_date` | Expiry Date | date | iff `hasExpiry == true` | future date required |

## Step 4 cross-field rules

- `bsb` and `account_number` input formatter: digits only.
- `fund_abn` input formatter: digits only.
- Document validation runs after text-field form validation.
- Legacy GET responses may include `taxFileDeclarationDocument` (string URL) — new PUT uses `uploadedDocument` map keyed by slot UUID.

---

# Step 5 — Policies Acknowledgement

## Policies list (dynamic, server-provided)

| id | label | type | required | readonly |
|----|-------|------|----------|----------|
| `policies[i].policy_name` | Policy Name | text (display) | — | **true** |
| `policies[i].policy_description` | Description | text (display) | — | **true** |
| `policies[i].acknowledged` | Acknowledged | boolean (tap action) | true | false |

Each policy has:
- `id` (String) — assignee policy id
- `policyId` (String) — policy definition id
- `name` (String) — display name
- `description` (String) — policy text
- `acknowledgedAt` (DateTime?) — null = not yet acknowledged

## Step 5 validation rules

- ALL policies must be acknowledged (`acknowledgedAt` must not be null for every entry).
- `allPoliciesAcknowledged` getter on controller enforces this; `advance_step` is blocked until true.
- Acknowledgement confirmed server-side via `CheckStaffOnboardPoliciesAcknowledgedUsecase` before completing onboarding.
- Completion via `CompleteStaffOnboardingUsecase`.

## Step 5 voice-mutability note

Policies are acknowledged one at a time by tapping an acknowledge button (or voice trigger).
The voice agent may call `acknowledge_policy(assignee_policy_id)` per policy.
Policy content (name, description) is **readonly** — voice agent must refuse changes.

---

# Readonly registry (voice agent — refuse to mutate)

```
basics.email
role_info.role
role_info.department
policies[i].policy_name
policies[i].policy_description
```

If asked to change a readonly field, respond with the readonly script.

---

# Global validators reference

| Validator | Signature | Rule |
|-----------|-----------|------|
| `requiredField` | `requiredField(v, {message})` | non-null, non-empty after trim |
| `requiredWithMaxLength` | `requiredWithMaxLength(v, max)` | required + max chars after trim |
| `australianMobile` | `australianMobile(v)` | `+61[2-478]XXXXXXXX`, `0[2-478]XXXXXXXX`, `1300/1800` + 6 digits, `13` + 4 digits |
| `dateOfBirthAtLeast18` | `dateOfBirthAtLeast18(date)` | not future, age ≥ 18 |
| `staffOnboardingZipCode` | `staffOnboardingZipCode(v)` | 1–4 digits, range 0–9999 |
| `bsb` | `bsb(v)` | exactly 6 digits `^\d{6}$` |
| `accountNumber` | `accountNumber(v)` | required + max 12 chars |
| `superFundAbn` | `superFundAbn(v)` | exactly 11 digits `^\d{11}$` |
| `futureDateRequired` | `futureDateRequired(date)` | must be strictly after today |
| `maxFileSize` | `maxFileSize(bytes, maxBytes)` | file ≤ maxBytes (5 MB = 5,242,880 bytes) |

## File upload constants (all steps)

| Constraint | Value |
|------------|-------|
| Max file size | 5,242,880 bytes (5 MB) |
| Allowed extensions | `pdf`, `jpg`, `jpeg`, `png`, `webp` |
| Allowed MIME types | `application/pdf`, `image/jpeg`, `image/png`, `image/webp` |

---

# Cross-step recap (`prior_pages`)

The voice backend's `prior_pages` carries only these handoff keys across steps:
`full_name`, `role`, `department`. Everything else is per-step state and must be
re-collected on each step.
