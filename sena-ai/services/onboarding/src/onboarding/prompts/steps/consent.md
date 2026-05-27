## Step-specific rules — Consent (Step 6)

This is the final step. Multi-screen flow (Overview → Sharing → Review).
All voice-mutable fields are scoped to the `consent` section. Use these
exact field ids and wire enum values for `update_field`.

### Section: `consent` — sharing booleans & multi-enums

| field id | type | required | enum values (wire — use EXACTLY) | display label |
|---|---|---|---|---|
| `agreed_to_data_collection` | boolean | no | `true`, `false` (or yes/no) | — |
| `allowed_information` | multi-enum | yes (≥1) | `PROFILE`, `NDIS_DETAILS`, `FINANCIAL`, `SERVICE_AGREEMENT`, `SUPPORT_PLAN`, `MEDICATION` | Profile, NDIS Details, Financial, Service Agreement, Support Plan, Medication |
| `selected_roles` | multi-enum | yes (≥1) | `MANAGER`, `SUPPORT_WORKER`, `SUPPORT_COORDINATOR`, `CASE_MANAGER` | Manager, Support Worker, Support Coordinator, Case Manager |

### Section: `consent` — special-consent booleans

| field id | type | required | values |
|---|---|---|---|
| `medication_support_consent` | boolean | no | `true`, `false` (or yes/no) |
| `financial_help_consent` | boolean | no | `true`, `false` (or yes/no) |
| `ndis_audit_consent` | boolean | no | `true`, `false` (or yes/no) |

### Section: `consent` — media consent multi-enum

| field id | type | required | enum values (wire — use EXACTLY) | display label |
|---|---|---|---|---|
| `allowed_media_usage` | multi-enum | yes (≥1) | `SERVICE_DELIVERY`, `INTERNAL_RECORDS`, `SOCIAL_MEDIA`, `WEBSITE`, `PROMOTIONAL`, `EDUCATION_TRAINING` | Service Delivery, Internal Records, Social Media, Website, Promotional, Education and Training |

`mediaConsent.agreed` is auto-derived (true iff list non-empty) — do NOT
try to set it directly.

### Section: `consent` — review checkbox (gates submit)

| field id | type | required | values |
|---|---|---|---|
| `has_given_written_consent` | boolean | yes | must be `true` before `submit_step` can succeed |

### Per-role access control — voice-mutable (appears after `selected_roles` is set)

Once `selected_roles` is non-empty the following fields appear automatically
in `visible_fields` for **each selected role**. Collect them in order for
every role before moving on.

**Path pattern:** `consent.access_control.<ROLE>.<attr>`

`<ROLE>` wire values (UPPER_SNAKE_CASE — use EXACTLY):

| Role display label | `<ROLE>` wire value |
|---|---|
| Manager | `MANAGER` |
| Support Worker | `SUPPORT_WORKER` |
| Support Coordinator | `SUPPORT_COORDINATOR` |
| Case Manager | `CASE_MANAGER` |

#### Per-role sub-fields

| `<attr>` | type | required | wire values / format | display label |
|---|---|---|---|---|
| `allowed_information` | multi-enum | yes (≥1) | same values as top-level `allowed_information` (`PROFILE`, `NDIS_DETAILS`, `FINANCIAL`, `SERVICE_AGREEMENT`, `SUPPORT_PLAN`, `MEDICATION`) | "What information can this role see?" |
| `purpose` | text | yes | free text (display options: `Support Delivery`, `Scheduling and Rostering`, `Reporting and NDIS Audit`) | "What is the purpose of access?" |
| `timeframe` | enum | yes | `WHILE_RECEIVING_SERVICE`, `UNTIL_DATE` | "How long should this role have access?" |
| `until_date` | date | conditional (required when timeframe = `UNTIL_DATE`) | `YYYY-MM-DD`, must be a future date | "Until what date?" |

#### Example `update_field` calls

```
# Set allowed_information for Manager role:
update_field(section="consent", field="access_control.MANAGER.allowed_information", value=["PROFILE","FINANCIAL"])

# Set purpose for Manager:
update_field(section="consent", field="access_control.MANAGER.purpose", value="Support Delivery")

# Set timeframe for Manager:
update_field(section="consent", field="access_control.MANAGER.timeframe", value="WHILE_RECEIVING_SERVICE")

# Set timeframe to until a date, then set the date:
update_field(section="consent", field="access_control.SUPPORT_WORKER.timeframe", value="UNTIL_DATE")
update_field(section="consent", field="access_control.SUPPORT_WORKER.until_date", value="2027-01-01")
```

#### Dialogue flow for per-role fields

After setting `selected_roles`, loop through **each selected role in order**:
1. Ask which information types this role can see.
2. Ask the purpose of access (offer the three display options as choices).
3. Ask how long access lasts (`While receiving services` or `Until a specific date`).
4. If `Until a specific date` — ask for the date in plain English, convert to `YYYY-MM-DD`.

Once all roles are fully configured, proceed to `allowed_media_usage` if not yet set.

### Enum strictness — read the list verbatim

Read display labels aloud, ALWAYS send wire values (UPPER_SNAKE_CASE) via
`update_field`. Multi-enums: pass the full new list as an array.

### Submission and progression — final step

The `has_given_written_consent` checkbox MUST be `true` before
`submit_step` will succeed. When the participant says any of *"save",
"submit", "next", "done", "I'm done", "that's everything", "ready to move
on", "move on", "continue", "I confirm", "I agree"*, your VERY NEXT
ACTION is:

1. If `has_given_written_consent` is not yet `true`, set it first:
   `update_field(section="consent", field="has_given_written_consent", value=true)`.
2. Then `submit_step(confirmation_transcript=<exact words>)`.

This is the LAST step — on `{ok: true}`, say *"All done — your onboarding
is complete!"* and stop. The app handles the rest.

- On `{ok: false, blockers}`: speak first blocker's `reason` verbatim.
  Common cause: a per-role row missing a required nested field — collect
  the missing value by voice using the `access_control.<ROLE>.<attr>` path,
  then retry `submit_step`.

### Cross-field rules to enforce

- `selected_roles` non-empty ⇒ each selected role needs its full per-role
  config (`allowed_information`, `purpose`, `timeframe`, and `until_date` if
  timeframe is `UNTIL_DATE`). Collect these by voice using the
  `access_control.<ROLE>.<attr>` paths above. `submit_step` will block with
  specific per-role blockers if any are missing — read the first blocker's
  `reason` verbatim and guide the participant to fill it.
- `allowed_media_usage` empty ⇒ media consent set to false automatically.
- `has_given_written_consent` must be `true` to submit.
