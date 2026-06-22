# Flutter Dev — `preferred_schedule` Overlap Validation (Option-D, client-owned)

> **Audience:** mobile/Flutter dev integrating the NDIS-plan voice step (`ndis_plan_details`).
> **Status:** NEW responsibility — not previously handed over. The backend currently has no
> deterministic overlap gate (it was attempted in the voice prompt only, which the LLM cannot
> enforce reliably). In Option-D **the client owns validation**, so this gate belongs in Flutter.

---

## TL;DR

When the voice agent sends an `update_field` `tool_request` for `preferred_schedule`, **you** must
check the proposed schedule for same-day time-slot overlaps and, if any overlap exists, reply with
`{"ok": false, "reason": "..."}`. The agent reads your `reason` **out loud, verbatim** — so write it
as a sentence a participant would understand. If there's no overlap, accept as normal.

The backend cannot do this for you: the prompt asks the model to do interval math in its head across a
multi-turn conversation, which fails in practice. The client has the proposed value in hand and can
check it deterministically — so this is a client gate.

> **This is a specific instance of the contract in `FLUTTER_HANDOFF_MASTER.md` — §1.7 (Flutter is the
> authoritative validator) + §3 (voice-initiated rejections return `{ok:false, reason}` to the tool
> call). Read those for the generic mechanism; this doc is only the `preferred_schedule`-specific rule.
> Registered as item 7 in the MASTER priority table.**

---

## When this fires

Only for `update_field` calls where `args.field == "preferred_schedule"` (inside the repeatable
`support_schedule` section). Every other field is unaffected.

### The `tool_request` you receive (server → client)

```json
{
  "type": "tool_request",
  "request_id": "a1b2c3...",
  "tool": "update_field",
  "args": {
    "section": "support_schedule",
    "field": "preferred_schedule",
    "repeatable_index": 0,
    "value": "Mon 09:00-18:00; Mon 17:00-19:00"
  }
}
```

> ⚠️ **`value` REPLACES the entire schedule for that row** — it is always the FULL set of days+times,
> never a delta. So you validate the proposed `value` **against itself** (intra-string), NOT against
> whatever was on screen before. No prior-state diffing needed.

### The `tool_response` you send back (client → server)

You MUST reply within **5 seconds** or the backend times out and the fill fails silently.

Reject (overlap found):
```json
{
  "type": "tool_response",
  "request_id": "a1b2c3...",
  "result": {
    "ok": false,
    "code": "schedule_overlap",
    "reason": "That overlaps your Monday slot 09:00 to 18:00 — the new Monday slot has to start at 18:00 or later. What time works?"
  }
}
```

Accept (no overlap) — your normal success path:
```json
{
  "type": "tool_response",
  "request_id": "a1b2c3...",
  "result": { "ok": true, "state": { /* your Option-D screen state */ } }
}
```

---

## ⛔ Two MORE things you MUST do — surface the error + gate submit (THE bug from testing)

Rejecting the `update_field` tool call (above) is not enough. In testing this happened:

> The overlap error showed **inline on the screen**, but the assistant said *"everything looks good,
> let's submit"*, called `submit_step`, the backend **ended the session** — yet the screen was still
> showing the inline validation error and never advanced.

**Why:** the backend is a **pure relay**. On `submit_step` it forwards to your controller and does exactly
what you return — `{ok:true}` ⇒ it says "all saved" and ends the step. It has **zero visibility** into
your inline screen errors. If you don't tell it, the agent is blind and will happily submit.

So beyond the `update_field` reply, you owe TWO more behaviours:

**A. Surface the inline error to voice the moment it appears** (MASTER §3). When the overlap is detected
on screen — whether typed/picked OR set by voice — send a control frame so the agent knows and re-asks
instead of declaring success:
```json
{ "type": "validation_failed",
  "section_id": "support_schedule", "field_id": "preferred_schedule", "repeatable_index": 0,
  "reason_human": "Your Monday slots 09:00-18:00 and 17:00-19:00 overlap — the second has to start at 18:00 or later.",
  "code": "schedule_overlap" }
```
When the user fixes it, send `{ "type": "validation_cleared", "section_id": "support_schedule", "field_id": "preferred_schedule", "repeatable_index": 0 }` so the agent stops re-asking.

**B. GATE `submit_step` — never return `{ok:true}` while the screen has unresolved errors** (MASTER §2.4
precedent). When the agent calls `submit_step` and any field (overlap included) is invalid, return:
```json
{ "ok": false,
  "blockers": [ { "path": "support_schedule[0].preferred_schedule",
                  "label": "Preferred schedule",
                  "reason": "Monday slots overlap — fix the times before submitting." } ] }
```
The agent reads the first `blocker.reason` verbatim and stays on the step. **NEVER** reply with a bare
`{ok:false}` (no reason) or `{ok:true}` when inline errors are showing — that is exactly what ended the
session prematurely. The submit gate is the same check as `checkOverlap` below, run across every row
before you allow submission.

---

## The DSL you must parse

`value` is a plain string (NOT JSON) in this exact format:

```
"<DAY>[, <DAY>...] <START>-<END>[; <DAY> <START>-<END>...]"
```

- **Comma-joined days share the same time range:** `"Mon, Wed, Sat 18:25-22:25"` = Mon, Wed and Sat each `18:25–22:25`.
- **Semicolons separate independent ranges:** `"Mon 22:00-22:30; Wed 09:00-12:00; Sat 06:00-09:00"`.
- Times are 24-hour `HH:mm`. `END` is strictly after `START`.
- Days: `Mon Tue Wed Thu Fri Sat Sun` (the agent may also emit `MO TU WE TH FR SA SU`).

**Expansion step (required before checking):** flatten the string into a list of `(day, start, end)`
tuples — split on `;`, then for each segment split the leading comma-list of days and apply the one
time range to each day.

## The overlap rule

Group the expanded tuples by day. For each day, no two ranges may overlap:

```
overlap(a, b)  ⇔  max(a.start, b.start) < min(a.end, b.end)
```

- **Touching ranges are OK:** `Mon 10:00-13:00; Mon 13:00-16:00` is valid (`end == start`, no overlap).
- Compare times as minutes-since-midnight to avoid string-compare bugs.

---

## Dart sketch

```dart
class Slot { final String day; final int start; final int end; Slot(this.day, this.start, this.end); }

int _min(String hhmm) { final p = hhmm.split(':'); return int.parse(p[0]) * 60 + int.parse(p[1]); }

const _dayAlias = {'MO':'Mon','TU':'Tue','WE':'Wed','TH':'Thu','FR':'Fri','SA':'Sat','SU':'Sun'};

List<Slot> _parse(String value) {
  final slots = <Slot>[];
  for (final seg in value.split(';').map((s) => s.trim()).where((s) => s.isNotEmpty)) {
    // seg = "Mon, Wed, Sat 18:25-22:25"  ->  days part + "HH:mm-HH:mm"
    final m = RegExp(r'^(.*?)(\d{2}:\d{2})-(\d{2}:\d{2})$').firstMatch(seg.trim());
    if (m == null) continue; // malformed segment: let it through or reject as you prefer
    final days = m.group(1)!.split(',').map((d) => d.trim()).where((d) => d.isNotEmpty);
    final start = _min(m.group(2)!), end = _min(m.group(3)!);
    for (final d in days) slots.add(Slot(_dayAlias[d.toUpperCase()] ?? d, start, end));
  }
  return slots;
}

/// Returns a user-facing reason if there's a same-day overlap, else null.
String? checkOverlap(String value) {
  final byDay = <String, List<Slot>>{};
  for (final s in _parse(value)) (byDay[s.day] ??= []).add(s);
  for (final entry in byDay.entries) {
    final list = entry.value..sort((a, b) => a.start - b.start);
    for (var i = 1; i < list.length; i++) {
      final a = list[i - 1], b = list[i];
      if (a.start < b.end && b.start < a.end) {           // overlap (touching is OK)
        return 'That overlaps your ${entry.key} slot ${_fmt(a.start)} to ${_fmt(a.end)} — '
               'the new ${entry.key} slot has to start at ${_fmt(a.end)} or later. What time works?';
      }
    }
  }
  return null;
}

String _fmt(int m) => '${(m ~/ 60).toString().padLeft(2,'0')}:${(m % 60).toString().padLeft(2,'0')}';
```

Wire-up:
```dart
if (req.tool == 'update_field' && req.args['field'] == 'preferred_schedule') {
  final reason = checkOverlap(req.args['value'] as String);
  if (reason != null) {
    send(toolResponse(req.requestId, ok: false, code: 'schedule_overlap', reason: reason));
    return; // do NOT apply the field
  }
}
// ...otherwise apply + send ok:true as usual
```

---

## Test vectors (must match)

| `value` | Result |
|---------|--------|
| `Mon 09:00-18:00` | ✅ accept |
| `Mon 10:00-13:00; Mon 13:00-16:00` | ✅ accept (touching) |
| `Mon, Wed, Sat 18:25-22:25` | ✅ accept (different days) |
| `Mon 10:00-22:00; Mon 16:00-23:00` | ❌ reject — overlap 16:00–22:00 |
| `Tue 09:00-12:00; Tue 14:00-17:00; Tue 11:00-15:00` | ❌ reject — third range overlaps both |
| `Mon, Tue 09:00-12:00; Tue 11:00-13:00` | ❌ reject — Tue 11:00–12:00 overlaps |

---

## Why client-side, not backend

This step is **Option-D mobile-authoritative** (`mobile_bridge.py` forwards each tool call and blocks for
your `tool_response`; the agent speaks your `reason`). The voice prompt has a "soft" ask — it will *try*
to avoid overlaps and will relay your rejection gracefully — but it is NOT a reliable gate and must not be
treated as one. The deterministic gate is here. See `FLUTTER_HANDOFF_MASTER.md` §1.7 (validation
ownership) + §3 (voice vs screen error channels) for the full `tool_request`/`tool_response` contract
this builds on.

If you'd prefer the backend to also enforce this as defense-in-depth (reject before forwarding to you),
ask the backend team — it's a small server-side validator, but per Option-D the client is the source of
truth for validation.
