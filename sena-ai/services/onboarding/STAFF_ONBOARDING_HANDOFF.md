# Staff Onboarding — Voice Integration Handoff

Contract for the Flutter / app-backend team to wire **staff (support-worker)
onboarding** into the existing voice service. The voice engine is unchanged — the
same `POST /v1/onboarding/session` + `WSS /ws/onboarding/{session_id}`, the same 7
tools, the same WS events. Staff differs only in the **step ids** you send and the
**schema** you put in the session-create payload.

Field source of truth: `staff_onboarding_field_inventory.md`. Backend behaviour
per step is driven by `step.id` → `prompts/steps/<flow>/{step_id}.md` (already
authored under `prompts/steps/staff/`; the loader resolves the file recursively).

---

## 1. Step id contract (MUST match exactly)

Send `step.id` as one of these. They are distinct from client step ids, so there
is no collision — a staff session never loads a participant prompt.

| Inventory step | `step.id` to send | Reference schema |
|---|---|---|
| 1 Personal Information | `staff_personal_information` | `tests/fixtures/staff/schema_staff_personal_information.json` |
| 2 Role Information | `staff_role_information` | `tests/fixtures/staff/schema_staff_role_information.json` |
| 3 Documents Upload | `staff_documents` | `tests/fixtures/staff/schema_staff_documents.json` |
| 4 Banking & Superannuation | `staff_banking` | `tests/fixtures/staff/schema_staff_banking.json` |
| 5 Policies Acknowledgement | `staff_policies` | `tests/fixtures/staff/schema_staff_policies.json` |

> ⚠️ **Silent-fail warning.** The backend selects per-step rules by exact filename
> match (`prompt_builder._step_rules_section`). If you send any `step.id` other than
> the five above, the agent runs the **generic base prompt with NO staff field rules
> and logs no error** — it will sound plausible but won't know the fields. There is
> NO runtime guard; this table is the contract. Staff voice schemas do not yet exist
> in Flutter (`lib/core/voice_schemas/` currently holds client steps only) — you are
> creating them; use these exact ids. Flutter `FieldType.choice/multiChoice/longText`
> map to backend `enum/multi_enum/textarea` (your client serializer already does this).

### Backend prompt-file layout & the step_id↔filename rule (post-refactor 2026-06-04)

Backend step prompts are now flow-grouped on disk — `prompts/steps/client/*.md` and
`prompts/steps/staff/*.md`. **This is internal only; nothing changes in the schema you
POST or the WS protocol.** The loader resolves `{step.id}.md` *recursively* under
`prompts/steps/`, so the subfolder is backend organisation — the lookup key is still
just `step.id`.

**HARD RULE:** the `stepId` you send MUST equal the backend prompt filename basename
(globally unique). Match → the step's voice rules load. Mismatch → the agent runs on
the base prompt with NO step-specific field rules (silent, no crash).

**Worked warning — a real, pre-existing mismatch in the CLIENT flow (learn from it):**
client step 3 sends `stepId: 'ndis_plan'` but the backend file is `ndis_plan_details.md`;
step 5 sends `'medical'` but the file is `medical_information.md`. Those two steps'
voice prompts currently DO NOT load (logged in `.claude/tasks/followups.md`). For staff,
send EXACTLY these ids — they match the authored files: `staff_personal_information`,
`staff_role_information`, `staff_documents`, `staff_banking`, `staff_policies`.

The reference schemas are the canonical `StepSchema` shape (`models/schema_spec.py`).
Adapt them as the inline `schema` you POST. Document slots (Step 3, the Step-4 tax
doc, and the Step-5 policy list) are **dynamic** — inject the real slot ids /
policy rows at runtime; the `{slot_id}` placeholders in the fixtures show the
per-slot field shape.

## 2. Session creation

`POST /v1/onboarding/session` with: `participant_id` (the staff member's id),
`step` (= the `step.id` above), `schema` (the inline StepSchema), `initial_state`
/ `bootstrap` (pre-filled values incl. readonly email, role, department), `tenant_id`.
No new fields, no new route. Server stays a thin relay.

## 3. Field paths, enums, readonly (what the agent will call `update_field` with)

Section + field ids the agent uses (`update_field(section, field, value, repeatable_index?)`):

**Step 1 `staff_personal_information`** — sections `basics`, `address`
- `basics`: `full_name`, `email` (RO), `phone`, `date_of_birth`, `gender`, `cultural_background`, `languages_spoken`, `requires_interpreter`, `profile_picture` (RO/file)
- `address`: `address`, `state`, `city`, `zip_code` (1–4 digits, 0–9999)
- Enums: `gender` = Male|Female|Other · `cultural_background` = Australian|Indian|Asian · `languages_spoken` (multi) = English|Mandarin|Arabic|Vietnamese|Cantonese|Punjabi|Greek|Italian|Hindi|Spanish

**Step 2 `staff_role_information`** — section `role_info`
- `role` (RO), `department` (RO), `experience` (≤500 chars, the only voice-fillable field)

**Step 3 `staff_documents`** — section `documents` (dynamic slots)
- per slot: `{slot_id}.document` (file, screen upload — voice opens picker via `update_field(field="{slot}.document", value="true")`), `{slot_id}.expiry_date`, `{slot_id}.not_applicable`

**Step 4 `staff_banking`** — sections `banking`, `superannuation`, `tax_documents`
- `banking`: `bank_name`, `account_holder_name`, `bsb` (6 digits), `account_number` (≤12 digits)
- `superannuation`: `fund_name`, `fund_abn` (11 digits), `member_number`
- `tax_documents`: `{slot_id}.document` (file), `{slot_id}.expiry_date` — dotless section id (the bridge splits the path on the first `.`)

**Step 5 `staff_policies`** — repeatable section `policies`
- per row: `policy_name` (RO), `policy_description` (RO), `acknowledged` (boolean)

### Readonly registry (agent refuses to mutate)
```
basics.email
basics.profile_picture        (file — upload from screen)
role_info.role
role_info.department
policies[i].policy_name
policies[i].policy_description
documents.{slot}.document     (file — voice only opens the picker)
```

## 4. voice_coverage per step (fields the agent may voice-fill)

- S1: all `basics.*` except `email`, `profile_picture`; all `address.*`
- S2: `role_info.experience` only
- S3: dynamic — per-slot `expiry_date` / `not_applicable` (files are screen-only)
- S4: all `banking.*` + `superannuation.*` text fields (tax doc is screen-only)
- S5: `policies.acknowledged` only

Send `voice_coverage` in the schema to restrict the agent to these paths.

## 5. Policy acknowledgement — NO new tool

There is **no** `acknowledge_policy` tool. The agent acknowledges a policy via the
existing `update_field`:

```
update_field(section="policies", field="acknowledged", value=true, repeatable_index=N)
```

Your Flutter controller must accept this write on the policy at row `N` and set its
`acknowledgedAt`. Do not expose a separate acknowledge tool to the bridge. The step
cannot submit until every row's `acknowledged` is true (enforce in Flutter; the
agent guides).

## 6. Validation ownership (unchanged — Option D)

Flutter remains the **authoritative validator**. The backend relays `update_field`
and reports back whatever your controller returns (`{ok:true}` or
`{ok:false, reason}` / `{ok:false, blockers:[...]}`). All staff validations (BSB 6,
ABN 11, zip 1–4 digits, age ≥18, max-lengths, required-doc rules) live in Flutter
(`AppValidators`) exactly as in client onboarding. The voice prompts encode these
only so the agent *formats* and *re-asks* correctly — they do not enforce.

## 7. Cross-step handoff (`prior_pages`)

The backend carries only these keys across steps: `full_name`, `role`,
`department`. Everything else is per-step state, re-collected each step. Populate
these in the bootstrap so the agent can greet by name and reference the role.
