## Step-specific rules — Consent (Step 6)

This is the final step. Multi-screen flow (Overview → Sharing → Review).
All voice-mutable fields are scoped to the `consent` section. Use these
exact field ids and wire enum values for `update_field`.

### MASTER SEQUENCE — ONE field per turn, STRICT ORDER

Consent is long and legal. Do NOT batch questions. Do NOT skip ahead. Ask
exactly ONE field, wait for the participant's answer, call `update_field`,
wait for `{ok: true}`, confirm in one short sentence, THEN move to the next
field. Never ask the next question before the previous `update_field`
returned `ok: true`.

Walk these in this exact order. Skip a field ONLY if it is already filled
(`value` non-null in `visible_fields`) — announce it's already set and move
on. NEVER fabricate a value the participant didn't say.

1. `agreed_to_data_collection` — "Do you consent to us collecting your data?" → yes/no → save.
2. `allowed_information` — read the 6 labels, ask which they allow → save full array.
3. `selected_roles` — read the 4 role labels, ask which roles get access → save full array.
4. **Per-role loop** — for EACH role in `selected_roles`, IN ORDER, collect all 4 sub-fields (see "Dialogue flow for per-role fields" below) before touching the next role. Finish role A completely, then role B. Never interleave.
5. `medication_support_consent` — "Do you consent to medication support?" → yes/no → save.
6. `financial_help_consent` — "Do you consent to financial assistance?" → yes/no → save.
7. `ndis_audit_consent` — "Do you consent to NDIS audit access?" → yes/no → save.
8. `allowed_media_usage` — read the 6 labels, ask which media uses they allow → save full array.
9. `has_given_written_consent` — "Do you give your written consent to everything we've covered?" → must be `true` → save.
10. Only after 1–9 are all saved → `submit_step`.

**Hard rules for this sequence:**
- ONE question per turn. After saving a field, confirm briefly then ask the NEXT field in the list. Do NOT say "anything else?" — drive forward through the list.
- Before asking field N, re-check `visible_fields`: if field N already has a non-null `value`, skip it (say "I've already got that") and go to N+1.
- NEVER call `submit_step` until step 9 (`has_given_written_consent`) is `true`.
- If the participant jumps ahead ("just submit"), still walk any unfilled required field first — `submit_step` will block otherwise.

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
| `allowed_information` | multi-enum | yes (≥1) | ONLY these 4 (per-role is a SUBSET of top-level — mobile shows only these): `PROFILE`, `SERVICE_AGREEMENT`, `FINANCIAL`, `MEDICATION` (display labels: Profile, Service Agreement, Financial, Medication). Do NOT offer NDIS_DETAILS or SUPPORT_PLAN here. | "What information can this role see?" |
| `purpose` | text | yes | MUST be one of these EXACT strings (mobile dropdown only renders an exact match): `Support delivery`, `Scheduling & rostering`, `Reporting (NDIS / audit)` | "What is the purpose of access?" |
| `timeframe` | enum | yes | `WHILE_RECEIVING_SERVICE`, `UNTIL_DATE` | "How long should this role have access?" |
| `until_date` | date | conditional (required when timeframe = `UNTIL_DATE`) | `YYYY-MM-DD`, must be a future date | "Until what date?" |

#### Example `update_field` calls

```
# Set allowed_information for Manager role:
update_field(section="consent", field="access_control.MANAGER.allowed_information", value=["PROFILE","FINANCIAL"])

# Set purpose for Manager (MUST be an exact dropdown string):
update_field(section="consent", field="access_control.MANAGER.purpose", value="Support delivery")

# Set timeframe for Manager:
update_field(section="consent", field="access_control.MANAGER.timeframe", value="WHILE_RECEIVING_SERVICE")

# Set timeframe to until a date, then set the date:
update_field(section="consent", field="access_control.SUPPORT_WORKER.timeframe", value="UNTIL_DATE")
update_field(section="consent", field="access_control.SUPPORT_WORKER.until_date", value="2027-01-01")
```

#### Dialogue flow for per-role fields

After setting `selected_roles`, loop through **each selected role in order**:
1. Ask which information types this role can see → call `update_field` for `allowed_information` → wait for `ok: true`.
2. Ask the purpose of access (offer three choices, read aloud: "Support delivery", "Scheduling and rostering", "Reporting for NDIS or audit"). Save the EXACT dropdown string — `Support delivery`, `Scheduling & rostering`, or `Reporting (NDIS / audit)` — via `update_field` for `purpose` → wait for `ok: true`. Sending any other wording leaves the mobile dropdown blank.
3. Ask how long access lasts (`While receiving services` or `Until a specific date`).
   - **MANDATORY: as soon as the participant answers step 3, call `update_field` for `timeframe` FIRST (before asking anything else).**
   - If they say "while receiving services" → `update_field(section="consent", field="access_control.<ROLE>.timeframe", value="WHILE_RECEIVING_SERVICE")` → wait for `ok: true`.
   - If they say "until a specific date" → `update_field(section="consent", field="access_control.<ROLE>.timeframe", value="UNTIL_DATE")` → wait for `ok: true` → ONLY THEN ask for the date.
4. If timeframe = `UNTIL_DATE`: ask for the date in plain English → convert to `YYYY-MM-DD` → call `update_field` for `until_date` → wait for `ok: true`.

**Critical ordering rule:** You MUST call `update_field` for `timeframe` BEFORE asking for `until_date`. Never ask "what date?" without first saving the `UNTIL_DATE` timeframe via a tool call. If the tool call fails, report the error — do not silently skip the save.

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
