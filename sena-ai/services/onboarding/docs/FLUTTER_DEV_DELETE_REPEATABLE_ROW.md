# Flutter Dev Handoff — Repeatable-Row Deletion via Voice

**Audience:** Flutter team building the onboarding screens that wrap the
voice agent.

**Why this doc exists:** Production session `4339494d` (2026-05-20) — the
user said *"remove the morning routine"* on the voice channel. The agent
acknowledged verbally but the row was never removed from the screen
because Flutter was either (a) not subscribed to the `row_deleted` event
or (b) not reconciling its local state when the event arrived. The
backend now fires the event reliably; the rest is on the client.

---

## 1. Trigger flow (server-side, for context)

```
User speaks:    "Remove the morning routine."
                          │
                          ▼
Voice agent calls         delete_repeatable_row(section_id, [row_index])
                          │
                          ▼
Server dispatcher         _delete_repeatable_row in tools.py
                          │   ├── validates section is repeatable
                          │   ├── infers row_index=0 if section has exactly 1 row
                          │   ├── checks min-rows constraint
                          │   ├── splices row out of FormState.values
                          │   ├── decrements state.repeatable_rows[section_id]
                          │   ├── adjusts state.focused_repeatable_index
                          │   └── persists to Redis
                          ▼
WebSocket emit            event 1: row_deleted   (delta event)
                          event 2: state         (full snapshot)
```

Two events fire **in order** for every deletion. Flutter should handle
**both** but treat the second (`state`) as authoritative if there is any
disagreement.

---

## 2. WebSocket event contracts

### `row_deleted` (delta event — primary trigger)

```jsonc
{
  "type": "row_deleted",
  "section_id": "morning_routine",
  "deleted_index": 2,
  "remaining_rows": 3
}
```

| Field | Type | Notes |
|---|---|---|
| `section_id` | string | Repeatable section the row was removed from. Matches the section key Flutter uses in its local `formState`. |
| `deleted_index` | int | Zero-based index of the row that just went away. |
| `remaining_rows` | int | Authoritative new count from the server. Use to validate your local count. |

### `state` (full snapshot — reconciliation)

```jsonc
{
  "type": "state",
  "state": {
    "session_id": "…",
    "step_id": "…",
    "values": { /* full FormState.values dict */ },
    "completion": { "required_total": 8, "required_filled": 3, … },
    "focused_section": "morning_routine" | null,
    "focused_repeatable_index": 0 | null,
    "repeatable_rows": { "morning_routine": 3, … },
    /* …other FormState fields… */
  }
}
```

Always emitted **immediately after** `row_deleted`. The `values` and
`repeatable_rows` keys are authoritative for the new shape.

---

## 3. Required Flutter handler

```dart
case 'row_deleted':
  final sectionId = event['section_id'] as String;
  final deletedIndex = event['deleted_index'] as int;
  final remainingRows = event['remaining_rows'] as int;

  // 1. Mutate local FormState
  final rows = formState.values[sectionId];
  if (rows is List && deletedIndex < rows.length) {
    formState.values[sectionId] = [
      for (var i = 0; i < rows.length; i++)
        if (i != deletedIndex) rows[i],
    ];
  }

  // 2. Adjust focused_repeatable_index if it was at or beyond the deleted row
  if (formState.focusedSection == sectionId) {
    final f = formState.focusedRepeatableIndex;
    if (remainingRows == 0) {
      formState.focusedSection = null;
      formState.focusedRepeatableIndex = null;
    } else if (f != null && f >= remainingRows) {
      formState.focusedRepeatableIndex = remainingRows - 1;
    } else if (f != null && f > deletedIndex) {
      formState.focusedRepeatableIndex = f - 1;
    }
  }

  // 3. Trigger UI rebuild — collapse the deleted row, re-number siblings
  notifyListeners();

  // 4. Log for QA
  AppLogger.info('voice.row_deleted',
      section: sectionId, index: deletedIndex, remaining: remainingRows);
  break;

case 'state':
  // Authoritative reconciliation — replace local FormState wholesale
  formState = FormState.fromJson(event['state']);
  notifyListeners();
  break;
```

**Anti-pattern (the bug from session 4339494d):** ignoring the event
because your `default:` branch logs a warning and returns. That hides the
event and the row stays on screen forever. The `default:` arm MUST log
at WARN level and surface unknown event types to the dev console — but
NEVER silently swallow them.

---

## 4. Required UX behaviour

| Scenario | UX |
|---|---|
| User says *"remove the morning routine"* and section has 1 row | Row collapses out of view immediately on `row_deleted`. If the section becomes empty AND `min=0`, show empty-state placeholder. |
| User says *"remove the morning routine"* and section has multiple rows | Server returns `rejection.code = row_index_ambiguous`. Agent asks user to specify which row. NO Flutter action needed — wait for next event. |
| User says *"remove"* with no row content | Server returns `rejection.code = section_already_empty`. Agent says so. No Flutter action. |
| Deletion violates `min` (e.g. emergency_contacts min=1, currently 1 row) | Server returns plain `error` string. Agent tells the user the section has a minimum row count. No Flutter action. |

---

## 5. Sequence with `field_updated` / re-numbering

Deletion may also shift remaining rows' indices. Watch for follow-on
`field_updated` events targeting rows whose index is `> deleted_index`
— the server may rebroadcast their `field_updated` envelopes with the
new index. Use `state` as source of truth if `field_updated` payloads
look inconsistent with your local view.

---

## 6. Manual test recipe

1. Add 3 morning_routine rows on the screen via the voice agent.
2. Say *"remove the second one"*.
3. **Expected:** row at index 1 disappears within ~500ms. Remaining row
   that was at index 2 is now visible at index 1 with its data intact.
4. Say *"remove the morning routine"*.
5. **Expected:** if 1 row remains, it disappears. If 2 rows remain,
   agent asks *"which one"* — Flutter does nothing yet.
6. Hit "Save And Continue".
7. **Expected:** webhook payload's `state.values.morning_routine` matches
   what's visible on screen — no phantom rows, no missing rows.

---

## 7. Open work (track on your side)

- [ ] Wire the `row_deleted` handler if not present.
- [ ] Confirm `default:` arm of `VoiceEventModel.parse` logs WARN —
      cross-reference the canonical event list in
      `.claude/rules/api.md` of the AI repo.
- [ ] Add a regression widget test: emit a fake `row_deleted` event
      and assert the row vanishes within a frame.
- [ ] Smoke test on a screen where `min > 0` (emergency_contacts):
      voice deletion of the last row above min should fail cleanly.

---

## 8. Server contract summary (one-line)

> When the user asks to remove a row by voice, the backend ALWAYS emits
> `row_deleted` followed by a full `state` snapshot. If Flutter handles
> these two events, the screen will stay in sync.
