# Client Onboarding — Field-by-Field Validation Reference

All 6 steps in order. Each field: required/optional, rule, error message.

---

## Step 1 — Personal Details

### Profile Photo
| Attribute | Value |
|---|---|
| Required | Yes (pre-form gate) |
| Allowed types | image/jpeg, image/jpg, image/png, image/webp |
| Max size | 5 MB (5,242,880 bytes) |
| Error (missing) | Snackbar: "Profile picture is required" |
| Error (wrong type / too large) | Silent reject (no upload) |

### Full Name
| Attribute | Value |
|---|---|
| Required | Yes |
| Rule | Must contain first + last (space-separated). First name ≤ 25 chars. Last name (everything after first space) ≤ 25 chars. |
| Error (empty) | "This field is required" |
| Error (no last name) | "Full name must include a first and last name" |
| Error (part > 25) | "Must be at most 25 characters" |

### Email Address
| Attribute | Value |
|---|---|
| Required | Yes |
| Rule | Display-only (disabled field); pre-filled from auth profile — not editable by user |

### Phone Number
| Attribute | Value |
|---|---|
| Required | Yes |
| Rule | Australian format: `+61[2-478]XXXXXXXX` OR `0[2-478]XXXXXXXX` OR `1300XXXXXX` OR `1800XXXXXX` OR `13XXXX`. Spaces stripped before check. |
| Error (empty) | "This field is required" |
| Error (invalid) | "Please enter a valid Australian mobile number" |

### Date of Birth
| Attribute | Value |
|---|---|
| Required | Yes |
| Rule | Must not be in the future. Client must be **at least 18 years old**. |
| Error (empty/not selected) | "This field is required" |
| Error (future date) | "Date of birth cannot be in the future" |
| Error (under 18) | "Must be at least 18 years old" |

### Gender
| Attribute | Value |
|---|---|
| Required | Yes |
| Rule | Must select one of the dropdown options |
| Error (empty) | "This field is required" |

### About Me
| Attribute | Value |
|---|---|
| Required | Yes |
| Max length | 250 characters |
| Error (empty) | "This field is required" |
| Error (> 250) | "Must be at most 250 characters" |

### Preferred Language
| Attribute | Value |
|---|---|
| Required | Yes (at least 1) |
| Rule | Multi-select from `LanguageEnum` values |
| Error (none selected) | "This field is required" (inline) / Snackbar: "At least one language is required" |

### Interpreter Required
| Attribute | Value |
|---|---|
| Required | Yes |
| Rule | Toggle (Yes / No). Defaults to No. No validation error — always has a value. |

---

### Primary Address (residential)

#### Address
| Attribute | Value |
|---|---|
| Required | Yes |
| Max length | 100 characters |
| Error (empty) | "This field is required" |
| Error (> 100) | "Must be at most 100 characters" |

#### State
| Attribute | Value |
|---|---|
| Required | Yes |
| Max length | 25 characters |
| Error (empty) | "This field is required" |
| Error (> 25) | "Must be at most 25 characters" |

#### City
| Attribute | Value |
|---|---|
| Required | Yes |
| Max length | 25 characters |
| Error (empty) | "This field is required" |
| Error (> 25) | "Must be at most 25 characters" |

#### Postcode
| Attribute | Value |
|---|---|
| Required | Yes |
| Rule | Exactly 4 digits (`^\d{4}$`). Digits only (keyboard + formatter). |
| Error (empty) | "This field is required" |
| Error (not 4 digits) | "Please enter a valid 4-digit Australian postcode" |

---

### Service Location (optional section — conditional)

All service location fields are **optional** when the section is blank. If **any** one field is filled, all four become required.

#### Service Address
| Attribute | Value |
|---|---|
| Required | Conditional (see above) |
| Max length | 100 characters |
| Error (empty when partial) | "This field is required" |
| Error (> 100) | "Must be at most 100 characters" |

#### Service State
| Attribute | Value |
|---|---|
| Required | Conditional |
| Max length | 25 characters |

#### Service City
| Attribute | Value |
|---|---|
| Required | Conditional |
| Max length | 25 characters |

#### Service Postcode
| Attribute | Value |
|---|---|
| Required | Conditional |
| Rule | Exactly 4 digits when filled |
| Error (not 4 digits) | "Please enter a valid 4-digit Australian postcode" |

---

### Emergency Contacts (1–5 contacts)

Min 1 required, max 5. Add/remove via UI.

#### Name
| Attribute | Value |
|---|---|
| Required | Yes |
| Max length | 25 characters |
| Error (empty) | "This field is required" |
| Error (> 25) | "Must be at most 25 characters" |

#### Relationship
| Attribute | Value |
|---|---|
| Required | Yes |
| Rule | Dropdown from predefined options. Max 25 chars. |
| Error (empty) | "This field is required" |

#### Email
| Attribute | Value |
|---|---|
| Required | Yes |
| Rule | Valid email format. Max 50 chars. Must **not** match client's own email. Must be **unique** across all emergency contacts. |
| Error (empty / invalid format) | "This field is required" / "Please enter a valid email address" |
| Error (matches client email) | "Emergency contact email must not match your email address" |
| Error (duplicate across contacts) | "Emergency contact emails must be unique" |
| Error (> 50) | "Must be at most 50 characters" |

#### Phone
| Attribute | Value |
|---|---|
| Required | Yes |
| Rule | Australian phone (same regex as client phone field) |
| Error (empty) | "This field is required" |
| Error (invalid) | "Please enter a valid Australian mobile number" |

---

## Step 2 — Requirements

### Cultural Considerations
| Attribute | Value |
|---|---|
| Required | Yes |
| Max length | 250 characters |
| Error (empty) | "This field is required" |
| Error (> 250) | "Must be at most 250 characters" |

### What's Most Important to Me
| Attribute | Value |
|---|---|
| Required | Yes |
| Max length | 250 characters |
| Error (empty) | "This field is required" |
| Error (> 250) | "Must be at most 250 characters" |

### My Goals
| Attribute | Value |
|---|---|
| Required | Yes |
| Max length | 250 characters |
| Error (empty) | "This field is required" |
| Error (> 250) | "Must be at most 250 characters" |

### Hobbies & Interests
| Attribute | Value |
|---|---|
| Required | Yes |
| Max length | 250 characters |
| Error (empty) | "This field is required" |
| Error (> 250) | "Must be at most 250 characters" |

### Communication Modes
| Attribute | Value |
|---|---|
| Required | Yes (at least 1 chip) |
| Options | AAC Device, Verbal/Spoken, Written Text/Email, Auslan, Communication Board, Support Person, Visual Supports |
| Error (none selected) | "At least one communication mode is required" |

### Communication Styles
| Attribute | Value |
|---|---|
| Required | Yes (at least 1 chip) |
| Options | Simple Instructions, Detailed Explanations (Step-by-Step), Reassurance (Extra Time), Routine-Based (Written Instructions), Visual Cues, Yes/No Questions, Repeat & Rephrase, Slowly & Calmly, Gestures & Signs |
| Error (none selected) | "At least one communication style is required" |

### Morning Routine (0–12 entries)
Each routine row has **Time** + **Description**. Both optional, but cross-validated:

| Field | Rule |
|---|---|
| Time | Required if Description filled |
| Description | Required if Time filled. Max 100 chars. |
| Error (time missing when desc filled) | "This field is required" |
| Error (desc missing when time filled) | "This field is required" |
| Error (desc > 100) | "Must be at most 100 characters" |

### Evening Routine (0–12 entries)
Same rules as Morning Routine above.

---

## Step 3 — NDIS Plan

### NDIS Number
| Attribute | Value |
|---|---|
| Required | Yes |
| Rule | Exactly 9 digits (non-digits stripped). Max 9 chars input. |
| Error (empty) | "This field is required" |
| Error (≠ 9 digits) | "NDIS number must be exactly 9 digits" |

### Plan Start Date
| Attribute | Value |
|---|---|
| Required | Yes |
| Rule | Any date selectable via date picker |
| Error (not selected) | "This field is required" |

### Plan End Date
| Attribute | Value |
|---|---|
| Required | Yes |
| Rule | Must be **after** Plan Start Date |
| Error (not selected) | "This field is required" |
| Error (not after start) | "Date must be after the start date" |

### Plan Management
| Attribute | Value |
|---|---|
| Required | Yes |
| Options | Self Managed, Plan Managed, NDIA Managed, Plan Nominee Managed |
| Error (empty) | "This field is required" |

---

### Plan Manager Fields (shown only when Plan Management = "Plan Managed")

#### Plan Manager Name
| Attribute | Value |
|---|---|
| Required | Yes |
| Rule | Letters and spaces only. Min 3 chars. Max 25 chars. |
| Error (empty) | "This field is required" |
| Error (non-letters) | "Only letters and spaces are allowed" |
| Error (< 3) | "Must be at least 3 characters" |
| Error (> 25) | "Must be at most 25 characters" |

#### Contact Email
| Attribute | Value |
|---|---|
| Required | Yes |
| Rule | Valid email format. Max 50 chars. |
| Error (empty / invalid) | "This field is required" / "Please enter a valid email address" |
| Error (> 50) | "Must be at most 50 characters" |

#### Billing Email
| Attribute | Value |
|---|---|
| Required | Yes |
| Rule | Valid email format. Max 50 chars. |
| Error (empty / invalid) | "This field is required" / "Please enter a valid email address" |
| Error (> 50) | "Must be at most 50 characters" |

---

### Support Coordinator (read-only, pre-filled by system)

Name and email are display-only (`readOnly: true`). No validation.

---

### NDIS Goals (1–10 entries)

Each goal is a free-text area.

| Attribute | Value |
|---|---|
| Required | Yes (each visible entry) |
| Rule | `requiredField` — cannot be empty |
| Error (empty) | "This field is required" |

---

### Funding Allocation (optional currency fields)

4 optional fields: Daily Living, Social & Community, Support Coordination, Improved Daily Living.

| Attribute | Value |
|---|---|
| Required | No |
| Rule | If filled: must be a valid positive number > 0. Max 14 chars (incl. comma separators). |
| Error (zero or negative) | "Amount must be greater than 0" |
| Error (non-numeric) | "Invalid amount" |

---

### Schedule of Supports (1–5 support items)

Each support item contains:

#### Support Name
| Attribute | Value |
|---|---|
| Required | Yes |
| Max length | 100 characters |
| Error (empty) | "This field is required" |
| Error (> 100) | "Must be at most 100 characters" |

#### Support Category
| Attribute | Value |
|---|---|
| Required | Yes |
| Rule | Dropdown from `SupportCategory` enum values |
| Error (empty) | "This field is required" |

#### Description
| Attribute | Value |
|---|---|
| Required | No |
| Rule | If filled: min 5 chars, max 255 chars |
| Error (< 5) | "Must be at least 5 characters" |
| Error (> 255) | "Must be at most 255 characters" |

#### Frequency
| Attribute | Value |
|---|---|
| Required | Yes |
| Options | As Required, Daily, Weekly, Fortnightly, Monthly, Once Off |
| Error (empty) | "This field is required" |

#### Duration (hours)
| Attribute | Value |
|---|---|
| Required | Yes |
| Rule | Whole number. Min 1, max 24. Digits only, max 2 chars. |
| Error (empty) | "This field is required" |
| Error (non-integer) | "Duration must be a whole number of hours" |
| Error (< 1) | "Duration must be at least 1 hour" |
| Error (> 24) | "Duration cannot exceed 24 hours" |

#### Preferred Days (day chips)
| Attribute | Value |
|---|---|
| Required | Yes (at least 1 day per support item must have a time slot) |
| Error (no day selected with slot) | "At least one preferred day is required" (inline under chips) |

#### Time Slots (per day, max 5 slots per day)

Each slot has Start Time and End Time.

| Field | Rule |
|---|---|
| Start Time | Required. Time picker. |
| End Time | Required. Must be **after** Start Time. |
| Overlap | Slots for same day must not overlap. |
| Error (start empty) | "This field is required" |
| Error (end empty) | "This field is required" |
| Error (end ≤ start) | "End time must be after start time" |
| Error (slots overlap) | "Time slots must not overlap" |

---

## Step 4 — Documents

Documents are fetched from the API (`/client/documents/required-document`). Each required document slot is rendered dynamically. There are no free-text fields with character limits in this step — validation is file-based:

| Rule | Detail |
|---|---|
| File types allowed | image/jpeg, image/jpg, image/png, application/pdf |
| Max file size | 5 MB (5,242,880 bytes) |
| Required docs | Determined by API response (each `RequiredDocumentEntity` defines whether it is mandatory) |
| Expiry date | Some docs require an expiry date — must not be in the past |
| "Not applicable" checkbox | Marks a required doc as N/A — bypasses file upload requirement for that slot |

Additional "Other Documents" section: optional, no hard validation.

---

## Step 5 — Medical

### Primary Diagnosis
| Attribute | Value |
|---|---|
| Required | Yes |
| Max length | 250 characters |
| Error (empty) | "This field is required" |
| Error (> 250) | "Must be at most 250 characters" |

### Secondary Diagnosis
| Attribute | Value |
|---|---|
| Required | No |
| Rule | If filled: min 5 chars, max 250 chars |
| Error (< 5) | "Secondary diagnosis must be at least 5 characters long" |
| Error (> 250) | "Must be at most 250 characters" |

### Blood Type
| Attribute | Value |
|---|---|
| Required | No |
| Options | A+, A−, B+, B−, AB+, AB−, O+, O− |

### Primary Doctor Name
| Attribute | Value |
|---|---|
| Required | Yes |
| Max length | 50 characters |
| Error (empty) | "This field is required" |
| Error (> 50) | "Must be at most 50 characters" |

### Primary Doctor Phone
| Attribute | Value |
|---|---|
| Required | No |
| Rule | If filled: valid Australian phone format |
| Error (invalid) | "Please enter a valid Australian mobile number" |

### Last Medical Checkup Date
| Attribute | Value |
|---|---|
| Required | No |
| Rule | Date picker. Range: last 10 years to today. |

---

### Allergies & Sensitivity (0–10 entries)

#### Title
| Attribute | Value |
|---|---|
| Required | Yes |
| Max length | 25 characters (input shows 50 but validator caps at 25) |
| Error (empty) | "This field is required" |
| Error (> 25) | "Must be at most 25 characters" |

#### Description
| Attribute | Value |
|---|---|
| Required | Yes |
| Rule | Min 5 chars, max 250 chars |
| Error (empty) | "This field is required" |
| Error (< 5) | "Description must be at least 5 characters long" |
| Error (> 250) | "Must be at most 250 characters" |

---

### Current Medications (0–10 entries)

#### Medication Name
| Attribute | Value |
|---|---|
| Required | Yes |
| Max length | 50 characters |
| Error (empty) | "This field is required" |
| Error (> 50) | "Must be at most 50 characters" |

#### Dosage
| Attribute | Value |
|---|---|
| Required | Yes |
| Max length | 50 characters |
| Error (empty) | "This field is required" |
| Error (> 50) | "Must be at most 50 characters" |

#### Frequency
| Attribute | Value |
|---|---|
| Required | Yes |
| Max length | 50 characters |
| Error (empty) | "This field is required" |
| Error (> 50) | "Must be at most 50 characters" |

#### Purpose
| Attribute | Value |
|---|---|
| Required | Yes |
| Rule | Min 5 chars, max 100 chars |
| Error (empty) | "This field is required" |
| Error (< 5) | "Purpose must be at least 5 characters long" |
| Error (> 100) | "Must be at most 100 characters" |

#### Notes
| Attribute | Value |
|---|---|
| Required | No |
| Rule | If filled: min 5 chars, max 100 chars |
| Error (< 5) | "Notes must be at least 5 characters long" |
| Error (> 100) | "Must be at most 100 characters" |

---

### Medical History (0–10 entries)

All fields in each row are **conditionally required**: if any one field in the row has a value, all three become required.

#### Title
| Attribute | Value |
|---|---|
| Required | Conditional (see above) |
| Max length | 25 characters |
| Error (empty when row has value) | "This field is required" |
| Error (> 25) | "Must be at most 25 characters" |

#### Year
| Attribute | Value |
|---|---|
| Required | Conditional |
| Rule | Year picker. Range: 1900 to current year. |
| Error (empty when row has value) | "Year is required" |
| Error (out of range) | "Year must be between 1900 and [current year]" |

#### Description
| Attribute | Value |
|---|---|
| Required | Conditional |
| Rule | Min 5 chars, max 100 chars |
| Error (empty when row has value) | "This field is required" |
| Error (< 5) | "Description must be at least 5 characters long" |
| Error (> 100) | "Must be at most 100 characters" |

---

### Mobility Status
| Attribute | Value |
|---|---|
| Required | Yes |
| Options | Independent, Uses Walking Aid, Wheelchair User, Bed Bound, Requires Assistance |
| Error (empty) | "This field is required" |

### Support Requirements
| Attribute | Value |
|---|---|
| Required | Yes |
| Max length | 250 characters |
| Error (empty) | "This field is required" |
| Error (> 250) | "Must be at most 250 characters" |

---

## Step 6 — Consent

Step 6 is rendered as a policy acknowledgement flow. No free-text fields — user toggles consent types and validity periods. No character-limit validations apply. Consent types and roles are defined by `ConsentInformationType` and `ConsentRole` enums.

---

## Cross-Step Rules (global)

| Rule | Detail |
|---|---|
| Emergency contact phone ≠ client phone | Not currently enforced client-side (only email uniqueness is checked) |
| Emergency contact email ≠ client email | Enforced (Step 1) |
| Emergency contact emails unique | Enforced across all rows (Step 1) |
| Plan end > plan start | Enforced (Step 3) |
| Profile picture required | Enforced as pre-form snackbar gate (Step 1) |
| Max emergency contacts | 5 (Step 1) |
| Max morning/evening routines | 12 each (Step 2) |
| Max NDIS goals | 10 (Step 3) |
| Max schedule of supports | 5 (Step 3) |
| Max time slots per day | 5 (Step 3) |
| Max allergies | 10 (Step 5) |
| Max medications | 10 (Step 5) |
| Max medical histories | 10 (Step 5) |
| Max service locations | 1 (Step 1 UI only shows one) |
