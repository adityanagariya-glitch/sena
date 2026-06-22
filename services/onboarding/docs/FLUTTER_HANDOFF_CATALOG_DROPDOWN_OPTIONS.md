# Flutter Handoff — Expose NDIS catalog options to the voice agent

**Owner:** sena-mobile (Flutter team)
**Backend contact:** SENA onboarding service (port 8083)
**Severity:** P1 — degraded voice UX on Client Onboarding Step 3 (NDIS Plan)
**Scope of change:** 3 lines in 1 Dart file. No new dependencies.

---

## TL;DR

In `client_step3_voice_handler.dart`, three `'enum_values': null` entries in
`_visibleFields()` must be populated from the controller's already-loaded
NDIS catalog. Without this, the voice agent receives no options for
`support_purpose` / `support_category` / `support_item` and either says
"there are no options" or invents wrong ones from training data.

---

## Why this is needed (root cause)

The voice agent receives a per-turn payload via `_visibleFields()` that
declares every field on screen: `path`, `value`, `enum_values`, `required`,
etc. The Gemini system prompt instructs the agent to read enum options from
this payload (never from training data) and quote them back verbatim when
the participant asks "what are my options?".

Today, on Step 3 — Schedule of Supports section, the handler sends:

```dart
'enum_values': null,   // line 1143 — support_purpose
'enum_values': null,   // line 1155 — support_category
'enum_values': null,   // line 1167 — support_item
```

…even though the catalog data is already loaded in the controller
(`ctrl.purposeOptions`, `row.categoryOptions`, `row.itemOptions` — used at
lines 359 / 400 / 441 of the same file to fuzzy-match the agent's guess
after it lands). The agent has nothing to read, so it confabulates from
stale NDIS price-guide memory.

---

## Exact change

**File:**
`lib/features/onboarding/client/presentation/voice/client_step3_voice_handler.dart`

**Function:** `_visibleFields()` (starts ~line 998)
**Block:** the `support_schedule` repeatable loop (starts ~line 1132)

### Diff — three field maps, change one line each

```dart
// line 1137 block — support_purpose
        {
          'path': 'support_schedule[$i].support_purpose',
          'label': 'Support ${i + 1} Purpose',
          'type': 'text',
          'required': true,
          'readonly': false,
          'value': row.breadcrumb?.purpose?.name,
-         'enum_values': null,
+         'enum_values': ctrl.purposeOptions.isEmpty
+             ? null
+             : ctrl.purposeOptions.map((p) => p.name).toList(),
          'validations_hint': 'Spoken name of the NDIS support purpose',
          'repeatable_index': i,
          'section': 'support_schedule',
        },

// line 1149 block — support_category
        {
          'path': 'support_schedule[$i].support_category',
          'label': 'Support ${i + 1} Category',
          'type': 'text',
          'required': true,
          'readonly': false,
          'value': row.breadcrumb?.category?.name,
-         'enum_values': null,
+         'enum_values': row.categoryOptions.isEmpty
+             ? null
+             : row.categoryOptions.map((c) => c.name).toList(),
          'validations_hint': 'Spoken name of the NDIS support category',
          'repeatable_index': i,
          'section': 'support_schedule',
        },

// line 1161 block — support_item
        {
          'path': 'support_schedule[$i].support_item',
          'label': 'Support ${i + 1} Item',
          'type': 'text',
          'required': true,
          'readonly': false,
          'value': row.breadcrumb?.supportName,
-         'enum_values': null,
+         'enum_values': row.itemOptions.isEmpty
+             ? null
+             : row.itemOptions.map((i) => i.variantType).toList(),
          'validations_hint': 'Spoken name of the NDIS support item',
          'repeatable_index': i,
          'section': 'support_schedule',
        },
```

### Why the `isEmpty ? null : ...` ternary

The voice contract treats `null` and `[]` as different signals:

| `enum_values` | Means | Agent behaviour |
|---|---|---|
| `null` | "Options unknown / not loaded yet" | Agent asks user to read what's on screen |
| `[]` | "No options exist right now" | Agent says "no options available" |
| `[…]` | The list to read verbatim | Agent quotes back exactly |

For the catalog dropdowns:
- `purposeOptions.isEmpty` happens before the NDIS catalog API responds → send `null`
- `categoryOptions.isEmpty` happens when no `support_purpose` is chosen yet → send `null` (the cascade dependency means "you must pick the parent first" — agent will route through `support_purpose` instead)
- `itemOptions.isEmpty` same story for `support_category`

Sending `null` while empty avoids the misleading "no options exist" reading.

### Variable name shadowing — heads-up

The third map uses `i.variantType` inside the `.map((i) => ...)`. The outer
loop variable is also `i` (the row index, e.g. `support_schedule[$i]`). The
inner `i` shadows it but is not used in the same expression. If your linter
flags this, rename to `.map((item) => item.variantType)`. Functionally
identical.

---

## Optional polish (not blocking)

If the catalog model exposes a stable wire id distinct from the spoken
label, prefer sending the wire id list and let the backend translate. Today
`p.name` / `c.name` / `i.variantType` are the labels users see on screen,
which matches what the agent should speak. If a future refactor introduces
`p.wireId`, switch to those — labels can change copy without breaking the
voice contract.

---

## Verification

### Manual smoke test

1. Run the onboarding service locally:
   ```bash
   cd SENA/services
   PYTHONPATH=".;onboarding" uvicorn onboarding.main:create_app --factory --reload --port 8083
   ```
2. Launch the Flutter client against this backend (dev flavor).
3. Onboard to Step 3. When you reach Schedule of Supports, start the voice
   agent and say: **"What are my options for support purpose?"**
4. **Before fix:** agent says "I can't see any options" or lists wrong NDIS
   categories from memory.
   **After fix:** agent reads back the exact items currently in
   `ctrl.purposeOptions` (e.g. "Core Supports, Capacity Building, Capital
   Supports").

### Wire-level check (faster than UI loop)

Tap the screen-state inspector in the dev tools, find the WS frame for the
current turn, and look for the `visible_fields` array. The three entries
above should now carry a populated `enum_values` list once the catalog has
loaded.

### Cascade check

Add a new support row. The agent should:
- Ask for `support_purpose` and read the live purpose list.
- After you pick a purpose, ask for `support_category` and read **only the
  categories valid for that purpose** (i.e. `row.categoryOptions` after
  cascade refresh — not the full set).
- Same again for `support_item`.

If the agent reads the wrong list, the controller is not refreshing
`categoryOptions` / `itemOptions` synchronously when the parent changes —
in that case ping backend so we can coordinate a re-emit of `visible_fields`
on cascade events.

---

## Out of scope for this change

- **Backend prompt edits.** The Gemini system prompt for this step
  (`SENA/services/onboarding/prompts/steps/client/ndis_plan_details.md`)
  already tells the agent to read options from `[SCREEN]`. No backend
  change is required as long as this Flutter fix lands.
- **Schema fixture sync.** The dev-only fixture
  `SENA/services/onboarding/fixtures/schema_ndis_plan_details.json` still
  references obsolete fields (`support_name`, `duration_hours`, etc.).
  Backend team will rewrite it separately — it does not affect production
  since the Flutter app sends `Step3NdisPlanSchema` inline at session
  create.

---

## Files referenced

| Purpose | Path |
|---|---|
| File to change | `lib/features/onboarding/client/presentation/voice/client_step3_voice_handler.dart` |
| Source of truth for option lists | `ClientStep3Controller.purposeOptions` + `SupportScheduleRow.categoryOptions` + `SupportScheduleRow.itemOptions` |
| Voice schema (already lists these field ids) | `lib/core/voice_schemas/step3_ndis_plan_schema.dart` |
| Catalog model definitions | `lib/features/onboarding/client/data/models/catalog/ndis_catalog_models.dart` |
| Backend prompt that reads these options | `SENA/services/onboarding/prompts/steps/client/ndis_plan_details.md` |

---

## Sign-off checklist

- [ ] Three `enum_values: null` lines replaced with the ternary pattern above.
- [ ] `dart analyze` clean.
- [ ] Manual smoke test passes (agent reads back live options).
- [ ] Cascade test passes (category list narrows after purpose selection).
